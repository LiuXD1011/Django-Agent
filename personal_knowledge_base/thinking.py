"""Validated, per-call thinking policies; no mutable provider/global configuration."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, replace
from functools import wraps
import hashlib
import inspect
import json
from urllib.parse import urlsplit

DEFAULT = {"mode": "default", "effort": None}
ROLES = ("chat", "summary", "title", "question", "extract", "vlm")
_snapshot = ContextVar("thinking_snapshot", default=None)


def capability(base_url, model):
    host = urlsplit(base_url or "").hostname
    if host == "api.deepseek.com" and model in {"deepseek-v4-flash", "deepseek-v4-pro", "deepseek-flash"}:
        return {"profile": "deepseek-v4-chat", "modes": ["default", "off", "on"],
                "efforts": ["low", "high", "max"], "note": "旧版 V4 接口可能将 low 映射为 high；不会修改模型名称。"}
    return {"profile": "unknown", "modes": ["default"], "efforts": [],
            "note": "该端点与模型尚无已验证的思考参数适配，保持供应商默认。"}


def normalize(value, cap):
    if not isinstance(value, dict) or set(value) - {"mode", "effort"}:
        raise ValueError("thinking 必须仅包含 mode 与 effort")
    mode, effort = value.get("mode", "default"), value.get("effort")
    if mode not in cap["modes"] or (mode != "on" and effort is not None):
        raise ValueError("该模型不支持指定的思考模式")
    if effort is not None and effort not in cap["efforts"]:
        raise ValueError("该模型不支持指定的思考级别")
    return {"mode": mode, "effort": effort}


def fingerprint(base, model):
    return hashlib.sha256(json.dumps([base.rstrip("/"), model]).encode()).hexdigest()[:20]


@contextmanager
def thinking_scope():
    if _snapshot.get() is not None:
        yield
        return
    token = _snapshot.set({})
    try:
        yield
    finally:
        _snapshot.reset(token)


def scoped(function):
    """Keep one immutable policy snapshot for the whole call/Agent turn."""
    if inspect.isgeneratorfunction(function):
        @wraps(function)
        def generator(*args, **kwargs):
            # Enter/exit around each next: yielding must not leak ContextVars.
            with thinking_scope():
                state = _snapshot.get()
            iterator = function(*args, **kwargs)
            while True:
                token = _snapshot.set(state)
                try:
                    value = next(iterator)
                except StopIteration:
                    return
                finally:
                    _snapshot.reset(token)
                try:
                    yield value
                except GeneratorExit:
                    token = _snapshot.set(state)
                    try:
                        iterator.close()
                    finally:
                        _snapshot.reset(token)
                    raise
        return generator
    @wraps(function)
    def wrapped(*args, **kwargs):
        with thinking_scope():
            return function(*args, **kwargs)
    return wrapped


@dataclass(frozen=True)
class Thinking:
    mode: str = "default"
    effort: str | None = None
    source: str = "default"
    revision: int = 0
    profile: str = "unknown"

    def metadata(self, applied=False):
        return {"think_level_requested": self.effort or self.mode,
                "think_level_applied": (self.effort or self.mode) if applied else "unconfirmed",
                "think_policy_source": self.source, "think_policy_revision": self.revision,
                "think_profile": self.profile}


def resolve(tenant, *, role="chat", model=None):
    from .model_providers import _role_config
    from .models import ModelConfig, Tenant
    if model is None:
        cfg = _role_config(role)
        base, name = cfg["base_url"], cfg["model"]
    else:
        params = model.parameters or {}
        base, name = params.get("base_url") or params.get("baseURL") or "", params.get("model") or model.name
    cap = capability(base, name)
    store = _snapshot.get()
    tenant_id = getattr(tenant, "pk", None)
    if tenant_id is None:
        return Thinking(profile=cap["profile"])
    key = str(tenant_id)
    data = store.get(key) if store is not None else None
    if data is None:
        # Capture only policy data, never API credentials.
        config = Tenant.objects.filter(pk=tenant_id).values_list("model_thinking_config", flat=True).first() or {}
        models = {m["id"]: deepcopy((m["parameters"] or {}).get("thinking", DEFAULT))
                  for m in ModelConfig.objects.filter(tenant_id=tenant_id, deleted_at__isnull=True).values("id", "parameters")}
        data = (deepcopy(config), models)
        if store is not None:
            store[key] = data
    config, models = data
    if model is None:
        entry = (config.get("roles") or {}).get(role, {})
        if entry.get("fingerprint") != fingerprint(base, name):
            return Thinking(source="default" if not entry else "stale", profile=cap["profile"])
        raw, source = entry.get("policy", DEFAULT), "tenant_env"
    else:
        raw, source = models.get(model.id, DEFAULT), "model"
    try:
        policy = normalize(raw, cap)
    except ValueError:
        return Thinking(source="stale", profile=cap["profile"])
    return Thinking(**policy, source=source, revision=int(config.get("revision", 0)), profile=cap["profile"])


def options(thinking):
    # Preserve the original call signatures when no policy has been configured.
    return {"thinking": thinking} if thinking.mode != "default" else {}


def wire_options(base, model, thinking=None, enable_thinking=None):
    cap = capability(base, model)
    policy = thinking or Thinking(profile=cap["profile"])
    if enable_thinking is False and cap["profile"] == "deepseek-v4-chat":
        policy = Thinking(mode="off", source="internal", profile=cap["profile"])
    if policy.mode == "default":
        return {}, {**policy.metadata(), "think_level_applied": "default"}
    normalize({"mode": policy.mode, "effort": policy.effort}, cap)
    # Put the complete vendor extension in extra_body, which LiteLLM/OpenAI
    # forwards without dropping unknown reasoning_effort enum values (e.g. max).
    body = {"thinking": {"type": "enabled" if policy.mode == "on" else "disabled"}}
    if policy.mode == "on" and policy.effort:
        body["reasoning_effort"] = policy.effort
    return body, {**policy.metadata(), "think_level_applied": policy.effort or policy.mode}


def adapt(policy, base, model, enable_thinking=None):
    cap = capability(base, model)
    if enable_thinking is False and cap["profile"] == "deepseek-v4-chat":
        return Thinking(mode="off", source="internal", revision=policy.revision, profile=cap["profile"])
    normalize({"mode": policy.mode, "effort": policy.effort}, cap)
    return replace(policy, profile=cap["profile"])
