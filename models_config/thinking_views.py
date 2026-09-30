from copy import deepcopy
import sqlite3
import time

from django.db import connection, OperationalError, transaction
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from personal_knowledge_base.models import ModelConfig, Tenant
from personal_knowledge_base.model_providers import _role_config, env_models
from personal_knowledge_base.thinking import ROLES, DEFAULT, capability, normalize, fingerprint
from personal_knowledge_base.responses import ok, fail
from personal_knowledge_base.views import auth_context, parse_body
from personal_knowledge_base.authentication import role_for


def can_edit(user, tenant):
    return bool(user and user.is_active and
                (user.is_system_admin or role_for(user, tenant) in {"owner", "admin"}))


def _model_capability(model):
    params = model.parameters or {}
    if model.type not in {"KnowledgeQA", "chat", "VLLM", "vlm"}:
        return capability("", "")
    return capability(params.get("base_url") or params.get("baseURL") or "",
                      params.get("model") or model.name)


def _read_settings(tenant, model_id):
    config = tenant.model_thinking_config or {}
    if model_id.startswith("env-"):
        item = next((m for m in env_models(tenant) if m["id"] == model_id), None)
        if not item:
            return None
        entries = []
        for r in item["roles"]:
            role = r["key"]
            if role not in ROLES:
                continue
            cfg = _role_config(role)
            cap = capability(cfg["base_url"], cfg["model"])
            saved = (config.get("roles") or {}).get(role, {})
            stale = bool(saved and saved.get("fingerprint") != fingerprint(cfg["base_url"], cfg["model"]))
            entries.append({"role": role, "capability": cap, "stale": stale,
                            "policy": DEFAULT if stale else saved.get("policy", DEFAULT)})
        return None, entries
    model = ModelConfig.objects.filter(pk=model_id, tenant=tenant, deleted_at__isnull=True).first()
    if not model:
        return None
    return model, [{"role": "model", "capability": _model_capability(model),
                    "policy": (model.parameters or {}).get("thinking", DEFAULT), "stale": False}]


def _sqlite_lock_error(exc):
    if connection.vendor != "sqlite":
        return False
    code = getattr(exc.__cause__, "sqlite_errorcode", None)
    if code is not None:
        return code & 0xff in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
    return str(exc).lower().startswith(("database is locked", "database table is locked",
                                         "database schema is locked"))


def _revision_conflict():
    return fail("配置已更新，请刷新后重试", 409, "revision_conflict")


@csrf_exempt
def thinking_settings(request, model_id):
    user, tenant = auth_context(request)
    if not tenant:
        return fail("unauthorized", 401)
    if request.method not in {"GET", "PUT"}:
        return fail("method not allowed", 405)
    editable = can_edit(user, tenant)
    if request.method == "PUT" and not editable:
        return fail("仅租户管理员可修改思考配置", 403)
    data = parse_body(request) if request.method == "PUT" else None
    for attempt in range(4):
        try:
            # Read and validate before taking SQLite's write lock. The CAS below
            # is the first statement in the transaction, avoiding read upgrades.
            current = Tenant.objects.get(pk=tenant.pk)
            original_config = current.model_thinking_config
            config = deepcopy(original_config or {})
            revision = int(config.get("revision", 0))
            settings = _read_settings(current, model_id)
            if settings is None:
                return fail("model not found", 404)
            model, entries = settings
            if data is not None:
                if data.get("revision") != revision:
                    return _revision_conflict()
                target = next((e for e in entries if e["role"] == data.get("role")), None)
                if target is None:
                    return fail("请选择当前模型实际使用的角色", 400)
                try:
                    policy = normalize(data.get("policy"), target["capability"])
                except ValueError as exc:
                    return fail(str(exc), 400)
                if model is None:
                    cfg = _role_config(target["role"])
                    config.setdefault("roles", {})[target["role"]] = {
                        "policy": policy, "fingerprint": fingerprint(cfg["base_url"], cfg["model"])}
                config["revision"] = revision + 1
                with transaction.atomic():
                    claimed = Tenant.objects.filter(pk=current.pk, model_thinking_config=original_config).update(
                        model_thinking_config=config, updated_at=timezone.now())
                    if not claimed:
                        return _revision_conflict()
                    if model is not None:
                        # Merge into the latest parameters while holding the model
                        # lock, so concurrent credentials/settings edits survive.
                        model = ModelConfig.objects.select_for_update().filter(
                            pk=model_id, tenant=current, deleted_at__isnull=True).first()
                        if model is None:
                            transaction.set_rollback(True)
                            return fail("model not found", 404)
                        cap = _model_capability(model)
                    else:
                        cfg = _role_config(target["role"])
                        cap = capability(cfg["base_url"], cfg["model"])
                    try:
                        policy = normalize(policy, cap)
                    except ValueError as exc:
                        transaction.set_rollback(True)
                        return fail(str(exc), 400)
                    if model is not None:
                        model.parameters = {**(model.parameters or {}), "thinking": policy}
                        model.save(update_fields=["parameters", "updated_at"])
                    target["capability"] = cap
                target["policy"], target["stale"] = policy, False
                revision += 1
            return ok({"model_id": model_id, "revision": revision, "entries": entries, "editable": editable})
        except OperationalError as exc:
            # Retry only SQLite contention, after the failed atomic block exits.
            if request.method != "PUT" or not _sqlite_lock_error(exc):
                raise
            if attempt == 3:
                return fail("配置正在更新，请稍后重试", 503, "configuration_busy")
            time.sleep((0.05, 0.1, 0.2)[attempt])
