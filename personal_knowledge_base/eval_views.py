"""
RAG 评估 API 视图

提供 RAG 评估功能的 API 端点。
"""

import hashlib
import json
import logging
import random
import uuid

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils.http import content_disposition_header
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .authentication import require_auth
from .eval_dataset_registry import DatasetNotFoundError, get_dataset_spec, registered_dataset_specs
from .open_rag_benchmark import (
    OpenRagDatasetError,
    MAX_SAMPLE_SIZE as OPEN_RAG_MAX_SAMPLE_SIZE,
    TASK_TYPE as OPEN_RAG_TASK_TYPE,
    dataset_metadata,
    mark_open_dataset_queued,
    open_dataset_status,
    open_rag_prepare_lock,
    run_open_rag_evaluation,
    run_open_rag_chunking,
    run_open_rag_retrieval,
)
from .rag_eval import RagasEvaluationError, get_default_eval_questions, run_rag_evaluation
from .responses import fail, ok
from .tasks import enqueue

logger = logging.getLogger(__name__)

DATASET_RESOURCE_TYPE = "rag_eval_datasets"
TESTSET_RESOURCE_TYPE = "rag_eval_testsets"
REVIEW_MODES = {"auto", "manual", "sample"}
REVIEW_STATUSES = {"approved", "rejected", "pending_review"}
QUESTION_TYPES = {"simple", "reasoning", "multi-context"}
MAX_EVAL_QUESTIONS = 100
DEFAULT_TESTSET_SIZE = 100
DEFAULT_OPEN_RAG_SAMPLE_SIZE = 180
PUBLIC_DATASET_COUNTS = {
    "open_rag_benchmark_180": 180,
    "open_rag_benchmark_100": 180,
    "open_rag_benchmark_full": 3045,
    "open_rag_benchmark": 3045,
}
class MalformedJsonBody(ValueError):
    pass


def parse_body(request, *, strict_json=False):
    if request.content_type and request.content_type.startswith("multipart/"):
        return request.POST.dict()
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except Exception as exc:
        if strict_json:
            raise MalformedJsonBody("malformed JSON body") from exc
        return {}


def auth_context(request):
    try:
        return require_auth(request)
    except PermissionError:
        return None, None


def _with_report(tenant, *, evaluation_type: str, evaluator: str, dataset, result: dict, configuration=None, public_dataset=False) -> dict:
    from .eval_reports import save_evaluation_report, save_open_evaluation_report

    save = save_open_evaluation_report if public_dataset else save_evaluation_report
    metadata = save(
        tenant=tenant,
        evaluation_type=evaluation_type,
        evaluator=evaluator,
        verified=bool(result.get("verified", True)),
        dataset=dataset,
        result=result,
        configuration=configuration or {},
    )
    return {**result, **metadata}


def _resource_payload(resource) -> dict:
    data = resource.data or {}
    return {
        "id": resource.id,
        "name": resource.name,
        "status": resource.status,
        "review_mode": data.get("review_mode", "auto"),
        "question_types": data.get("question_types", []),
        "knowledge_base_id": data.get("knowledge_base_id", ""),
        "schema_version": data.get("schema_version", "evaluation_v2"),
        "version": data.get("version", 1),
        "dataset_hash": data.get("dataset_hash", ""),
        "published_at": data.get("published_at"),
        "review_summary": data.get("review_summary", {}),
        "entries": data.get("entries", []),
        "generated": len(data.get("entries", [])),
        "created_at": resource.created_at.isoformat() if resource.created_at else "",
        "updated_at": resource.updated_at.isoformat() if resource.updated_at else "",
    }


def _validate_eval_entry(tenant, entry: dict, knowledge_base_id: str = "") -> list[str]:
    """Validate an immutable candidate against this tenant's source spans."""
    errors = []
    if not isinstance(entry.get("question"), str) or not entry["question"].strip():
        errors.append("question")
    if not isinstance(entry.get("answer"), str) or not entry["answer"].strip():
        errors.append("answer")
    evidence = entry.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return errors + ["evidence"]

    from .models import Chunk

    ids = [str(item.get("chunk_id") or "") for item in evidence if isinstance(item, dict)]
    if len(ids) != len(evidence) or not all(ids):
        return errors + ["evidence"]
    chunks = {
        chunk.id: chunk
        for chunk in Chunk.objects.filter(
            tenant=tenant,
            id__in=ids,
            deleted_at__isnull=True,
            knowledge__tenant=tenant,
            knowledge_base__tenant=tenant,
        ).select_related("knowledge")
    }
    for item in evidence:
        chunk = chunks.get(str(item.get("chunk_id")))
        if chunk is None:
            errors.append("evidence")
            continue
        start, end = item.get("source_start"), item.get("source_end")
        if not isinstance(start, int) or not isinstance(end, int) or start >= end:
            errors.append("source_span")
            continue
        if start < chunk.start_at or end > chunk.end_at:
            errors.append("source_span")
        if item.get("knowledge_id") and str(item["knowledge_id"]) != str(chunk.knowledge_id):
            errors.append("evidence")
        if knowledge_base_id and str(chunk.knowledge_base_id) != str(knowledge_base_id):
            errors.append("knowledge_base")
    return sorted(set(errors))


def _dataset_knowledge_base_id(tenant, entries: list[dict]) -> str:
    from .models import Chunk

    chunk_ids = {
        str(evidence.get("chunk_id") or "")
        for entry in entries
        for evidence in (entry.get("evidence") or [])
        if isinstance(evidence, dict) and evidence.get("chunk_id")
    }
    if not chunk_ids:
        return ""
    knowledge_base_ids = set(
        Chunk.objects.filter(
            tenant=tenant,
            id__in=chunk_ids,
            deleted_at__isnull=True,
        ).values_list("knowledge_base_id", flat=True)
    )
    return str(next(iter(knowledge_base_ids))) if len(knowledge_base_ids) == 1 else ""


def _normalize_eval_entries(tenant, entries, review_mode: str, knowledge_base_id: str = "") -> list[dict]:
    if not isinstance(entries, list):
        raise ValueError("entries must be a list")
    normalized = []
    sampled_indexes = set()
    if review_mode == "sample" and entries:
        sample_count = max(1, (len(entries) + 9) // 10)
        sampled_indexes = set(random.Random(20260819).sample(range(len(entries)), sample_count))
    for index, raw in enumerate(entries):
        raw = raw if isinstance(raw, dict) else {}
        item = {
            "schema_version": "evaluation_v2",
            "id": str(raw.get("id") or uuid.uuid4().hex[:16]),
            "question": raw.get("question", ""),
            "answer": raw.get("answer", ""),
            "reference_answer": raw.get("reference_answer", raw.get("ground_truth", raw.get("answer", ""))),
            "ground_truth": raw.get("ground_truth", ""),
            "evidence": raw.get("evidence", []),
            "documents": raw.get("documents", []),
            "review_sampled": review_mode == "sample" and index in sampled_indexes,
        }
        errors = _validate_eval_entry(tenant, item, knowledge_base_id)
        if item["evidence"]:
            from .models import Knowledge
            knowledge_ids = {str(e.get("knowledge_id") or "") for e in item["evidence"] if isinstance(e, dict)}
            versions = {
                str(knowledge.id): knowledge.file_hash
                for knowledge in Knowledge.objects.filter(
                    id__in=knowledge_ids, tenant=tenant, deleted_at__isnull=True
                )
            }
            for evidence in item["evidence"]:
                if isinstance(evidence, dict):
                    evidence.setdefault("file_hash", versions.get(str(evidence.get("knowledge_id")), ""))
            item["documents"] = [
                {"knowledge_id": knowledge_id, "file_hash": file_hash}
                for knowledge_id, file_hash in sorted(versions.items())
            ]
        item["validation_errors"] = errors
        if review_mode in {"auto", "sample"}:
            item["status"] = "approved" if not errors else "rejected"
        else:
            item["status"] = "pending_review"
        normalized.append(item)
    return normalized


def _evaluation_dataset_hash(entries: list[dict]) -> str:
    immutable = [
        {
            "id": entry.get("id"),
            "question": entry.get("question"),
            "reference_answer": entry.get("reference_answer"),
            "documents": entry.get("documents", []),
            "evidence": entry.get("evidence", []),
        }
        for entry in entries
    ]
    return _dataset_hash(immutable)


def _evaluation_dataset_data(*, review_mode: str, entries: list[dict], existing=None, **extra) -> dict:
    existing = existing if isinstance(existing, dict) else {}
    summary = {
        "total": len(entries),
        "approved": sum(entry.get("status") == "approved" for entry in entries),
        "rejected": sum(entry.get("status") == "rejected" for entry in entries),
        "pending": sum(entry.get("status") == "pending_review" for entry in entries),
    }
    return {
        **existing,
        **extra,
        "schema_version": "evaluation_v2",
        "version": int(existing.get("version") or 1),
        "review_mode": review_mode,
        "entries": entries,
        "dataset_hash": _evaluation_dataset_hash(entries),
        "review_summary": summary,
        "published_at": existing.get("published_at"),
    }


def _dataset_resource(tenant, dataset_id: str, resource_type: str | None = DATASET_RESOURCE_TYPE):
    from .models import GenericResource

    query = GenericResource.objects.filter(
        id=dataset_id,
        tenant=tenant,
        deleted_at__isnull=True,
    )
    if resource_type is not None:
        query = query.filter(resource_type=resource_type)
    else:
        query = query.filter(resource_type__in=(DATASET_RESOURCE_TYPE, TESTSET_RESOURCE_TYPE))
    return query.first()


def _approved_questions(tenant, resource) -> list[dict]:
    questions = []
    for entry in (resource.data or {}).get("entries", []):
        if entry.get("status") != "approved":
            continue
        if _validate_eval_entry(tenant, entry):
            continue
        # ``ground_truth`` is only a caller-supplied reference. It is never a
        # generated RAG answer substituted by this evaluation flow.
        questions.append({
            "question": entry["question"],
            "ground_truth": entry.get("ground_truth", ""),
            "evidence": entry["evidence"],
        })
    return questions


@csrf_exempt
def rag_eval_open_datasets(request):
    """List the single registered public dataset without importing it."""
    user, tenant = auth_context(request)
    if not tenant:
        return fail("unauthorized", 401, "unauthorized")
    if request.method != "GET":
        return fail("method not allowed", 405)

    return ok({"datasets": [dataset_metadata(spec) for spec in registered_dataset_specs()]})


def _open_dataset_spec_or_404(dataset_id, version="arxiv-v1"):
    try:
        return get_dataset_spec(dataset_id, version), None
    except DatasetNotFoundError:
        return None, fail("open dataset not found", 404, "open_dataset_not_found")


@csrf_exempt
def rag_eval_open_dataset_status(request, dataset_id):
    user, tenant = auth_context(request)
    if not tenant:
        return fail("unauthorized", 401)
    if request.method != "GET":
        return fail("method not allowed", 405)
    spec, error = _open_dataset_spec_or_404(dataset_id)
    if error:
        return error
    return ok(dataset_metadata(spec))


@csrf_exempt
def rag_eval_open_dataset_prepare(request, dataset_id):
    user, tenant = auth_context(request)
    if not tenant:
        return fail("unauthorized", 401)
    if request.method != "POST":
        return fail("method not allowed", 405)
    spec, error = _open_dataset_spec_or_404(dataset_id)
    if error:
        return error
    from .models import TaskRecord

    with open_rag_prepare_lock(spec, blocking=False) as acquired:
        if not acquired:
            return ok({**dataset_metadata(spec), "status": "queued", "task_id": ""}, status=202)
        active = None
        for candidate in TaskRecord.objects.filter(
            task_type=OPEN_RAG_TASK_TYPE,
            status__in=("pending", "running"),
        ).order_by("-created_at"):
            payload = candidate.payload if isinstance(candidate.payload, dict) else {}
            if payload.get("dataset_version") == spec.version and payload.get("dataset_id") in {
                "open_rag_benchmark", "open_rag_benchmark_180", "open_rag_benchmark_100", "open_rag_benchmark_full"
            }:
                active = candidate
                break
        if active is None and open_dataset_status(spec)["ready"]:
            return ok({**dataset_metadata(spec), "task_id": ""})
        if active is None:
            from django.conf import settings

            lock_held = bool(getattr(settings, "APP_TASKS_SYNC", False))
            mark_open_dataset_queued(spec)
            active = enqueue(
                OPEN_RAG_TASK_TYPE,
                lambda: __import__("personal_knowledge_base.open_rag_benchmark", fromlist=["prepare_open_rag_dataset"]).prepare_open_rag_dataset(spec, lock_already_held=lock_held),
                {"dataset_id": spec.dataset_id, "dataset_version": spec.version},
            )
    return ok({**dataset_metadata(spec), "status": "queued" if active.status == "pending" else "downloading", "task_id": str(active.id)}, status=202)


OPEN_RAG_CHUNKING_STRATEGIES = (
    "fixed_window",
    "recursive",
    "auto_parent_child",
    "semantic_parent_child",
)
# 评测可选全集：四个门禁策略 + 生产 heading/layout/record（生产形态、父子块开启）
EVALUATION_CHUNKING_STRATEGIES = OPEN_RAG_CHUNKING_STRATEGIES + ("heading", "layout", "record")
INDEX_ALGORITHM_VERSION = "evaluation-index-v2"


class EvaluationConfigurationError(ValueError):
    """A safe, client-facing preflight failure."""

    def __init__(self, code: str, message: str, status: int = 422):
        self.code = code
        self.status = status
        super().__init__(message)


def _normalize_chunking_configuration(data: dict) -> tuple[str, list[str], bool]:
    """Normalize primary/comparison chunking while retaining one old request shape."""
    old_present = "chunking_strategies" in data
    old_value = data.get("chunking_strategies")
    if old_present and old_value is not None and not isinstance(old_value, list):
        raise ValueError("chunking_strategies must be a list")
    old_values = [str(value) for value in (old_value or [])]
    new_present = "primary_chunking_strategy" in data or "comparison_chunking_strategies" in data
    primary = str(data.get("primary_chunking_strategy") or (old_values[0] if old_values else "auto_parent_child"))
    comparisons_raw = data.get("comparison_chunking_strategies")
    if comparisons_raw is None:
        comparisons = old_values[1:] if old_values else []
    elif isinstance(comparisons_raw, list):
        comparisons = [str(value) for value in comparisons_raw]
    else:
        raise ValueError("comparison_chunking_strategies must be a list")
    if old_present and new_present and old_values and old_values != [primary, *comparisons]:
        raise ValueError("chunking_strategies conflicts with primary/comparison chunking fields")
    if not primary:
        raise ValueError("primary_chunking_strategy is required")
    if primary in comparisons:
        raise ValueError("primary chunking strategy cannot be a comparison strategy")
    if len(comparisons) != len(set(comparisons)):
        raise ValueError("comparison chunking strategies must be unique")
    if primary not in EVALUATION_CHUNKING_STRATEGIES or not set(comparisons).issubset(EVALUATION_CHUNKING_STRATEGIES):
        raise ValueError("unsupported chunking strategy")
    return primary, comparisons, bool(old_present and not new_present)


def _model_name_for_config(model_config) -> str:
    if not model_config:
        return ""
    return str(model_config.get("model") or model_config.get("name") or model_config.get("id") or "")


def _effective_evaluation_pipeline(tenant, configuration: dict) -> dict:
    """Resolve the actual retrieval/model pipeline at task creation time."""
    from .model_providers import active_embedding_config, active_rerank_config, default_model

    embedding_config = active_embedding_config(tenant)
    rerank_config = active_rerank_config(tenant) if configuration["rerank_enabled"] else None
    answer_model = _validate_model_choice(tenant, configuration.get("answer_model_id", ""))
    judge_model = _validate_model_choice(tenant, configuration.get("judge_model_id", ""), judge=True)
    if not configuration.get("answer_model_id"):
        answer_model = default_model(tenant, "chat") if tenant is not None else None
    if not configuration.get("judge_model_id"):
        judge_model = default_model(tenant, "chat") if tenant is not None else None
    return {
        "embedding_model": _model_name_for_config(embedding_config),
        "embedding_model_id": str((embedding_config or {}).get("model_id") or ""),
        "vector_distance_metric": "l2",
        "rrf_k": int(getattr(settings, "SEARCH_RRF_K", 60)),
        "index_algorithm_version": INDEX_ALGORITHM_VERSION,
        "answer_model": _model_name_for_config({
            "model": (answer_model.parameters or {}).get("model") if answer_model else getattr(settings, "LLM_CHAT_MODEL", ""),
            "name": answer_model.name if answer_model else "",
            "id": answer_model.id if answer_model else "",
        }),
        "answer_model_id": str(answer_model.id) if answer_model else "",
        "judge_model": _model_name_for_config({
            "model": (judge_model.parameters or {}).get("model") if judge_model else getattr(settings, "LLM_CHAT_MODEL", ""),
            "name": judge_model.name if judge_model else "",
            "id": judge_model.id if judge_model else "",
        }),
        "judge_model_id": str(judge_model.id) if judge_model else "",
        "rerank": {
            "requested": bool(configuration["rerank_enabled"]),
            "effective": bool(rerank_config),
            "status": "disabled" if not configuration["rerank_enabled"] else ("enabled" if rerank_config else "unavailable"),
            "model": _model_name_for_config(rerank_config),
            "model_id": str((rerank_config or {}).get("model_id") or ""),
        },
        "degradations": [],
    }


def _preflight_evaluation_configuration(tenant, configuration: dict, *, legacy_contract: bool = False) -> dict:
    """Reject requested capabilities which cannot be executed strictly.

    Old synchronous callers are still accepted for one compatibility release;
    all normalized ``/runs`` requests (the workbench contract) go through the
    strict branch.
    """
    from .model_providers import active_embedding_config, active_rerank_config

    needs_embedding = configuration["retrieval_strategy"] in {"vector", "hybrid"}
    needs_semantic = configuration["primary_chunking_strategy"] == "semantic_parent_child" or "semantic_parent_child" in configuration["comparison_chunking_strategies"]
    embedding_config = active_embedding_config(tenant)
    # Legacy fields are normalized for compatibility, but capability checks
    # remain strict so an old client cannot obtain a false verified result.
    if needs_embedding and not embedding_config:
        raise EvaluationConfigurationError("embedding_model_required", "vector or hybrid retrieval requires an available embedding model")
    if needs_semantic and not embedding_config:
        raise EvaluationConfigurationError("semantic_model_required", "semantic parent-child chunking requires an available embedding model")
    if configuration["rerank_enabled"] and not active_rerank_config(tenant):
        raise EvaluationConfigurationError("rerank_model_required", "Rerank is enabled but no available Rerank model was found")
    effective = _effective_evaluation_pipeline(tenant, configuration)
    if not legacy_contract:
        from .model_providers import default_model

        has_env_chat = bool(getattr(settings, "LLM_USE_ENV_CHAT", False) and getattr(settings, "LLM_CHAT_API_KEY", ""))
        if not configuration.get("answer_model_id") and not has_env_chat and default_model(tenant, "chat") is None:
            raise EvaluationConfigurationError("answer_model_required", "an available Answer model is required")
        if not configuration.get("judge_model_id") and not has_env_chat and default_model(tenant, "chat") is None:
            raise EvaluationConfigurationError("judge_model_required", "an available Judge model is required")
    if not configuration["rerank_enabled"]:
        effective["rerank"].update({"effective": False, "status": "disabled"})
    return effective


def _requested_configuration(configuration: dict) -> dict:
    return {
        "source": configuration.get("source", {}),
        "primary_chunking_strategy": configuration.get("primary_chunking_strategy"),
        "comparison_chunking_strategies": list(configuration.get("comparison_chunking_strategies") or []),
        "retrieval_strategy": configuration.get("retrieval_strategy"),
        "rerank_enabled": bool(configuration.get("rerank_enabled")),
        "answer_model_id": configuration.get("answer_model_id", ""),
        "judge_model_id": configuration.get("judge_model_id", ""),
    }


def _open_run_configuration(data: dict, tenant) -> tuple[dict, str]:
    dataset_id = str(data.get("open_dataset_id") or "")
    version = str(data.get("dataset_version") or "arxiv-v1")
    sample_size = max(1, min(int(data.get("sample_size", DEFAULT_OPEN_RAG_SAMPLE_SIZE)), OPEN_RAG_MAX_SAMPLE_SIZE))
    seed = int(data.get("seed", 20260819))
    retrieval_strategy = str(data.get("retrieval_strategy") or "hybrid").lower()
    if retrieval_strategy not in {"keyword", "vector", "hybrid"}:
        raise ValueError("unsupported retrieval strategy")
    strategies = tuple(str(item) for item in (data.get("chunking_strategies") or OPEN_RAG_CHUNKING_STRATEGIES))
    if not strategies or len(strategies) != len(set(strategies)) or not set(strategies).issubset(EVALUATION_CHUNKING_STRATEGIES):
        raise ValueError("chunking strategies must be a non-empty unique subset of supported strategies")
    configuration = {
        "tenant_id": tenant.id,
        "dataset_id": dataset_id,
        "dataset_version": version,
        "sample_size": sample_size,
        "seed": seed,
        "retrieval_strategy": retrieval_strategy,
        "chunking_strategies": list(strategies),
        "primary_chunking_strategy": strategies[0],
        "comparison_chunking_strategies": list(strategies[1:]),
        "requested_configuration": {
            "primary_chunking_strategy": strategies[0],
            "comparison_chunking_strategies": list(strategies[1:]),
            "retrieval_strategy": retrieval_strategy,
            "rerank_enabled": bool(data.get("rerank_enabled", True)),
        },
        "eval_llm_model": str(data.get("eval_llm_model") or ""),
    }
    fingerprint = hashlib.sha256(json.dumps(configuration, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    configuration["configuration_fingerprint"] = fingerprint
    return configuration, fingerprint


def _iso(value):
    return value.isoformat() if isinstance(value, timezone.datetime) else None


def _open_run_payload(record) -> dict:
    raw_payload = getattr(record, "payload", {})
    raw_result = getattr(record, "result", {})
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    runtime = raw_result if isinstance(raw_result, dict) else {}
    status = str(getattr(record, "status", "queued"))
    if status == "pending":
        status = "queued"
    record_progress = getattr(record, "progress", 0) or 0
    created_at = getattr(record, "created_at", None)
    updated_at = getattr(record, "updated_at", None)
    record_id = str(getattr(record, "id", ""))
    return {
        "run_id": record_id,
        "status": "cancelled" if status == "cancelled" else status,
        "run_status": "cancelled" if status == "cancelled" else status,
        "stage": runtime.get("stage", payload.get("stage", "")),
        "progress": float(runtime.get("progress", record_progress)),
        "stage_progress": float(runtime.get("stage_progress", payload.get("stage_progress", 0))),
        "completed_stages": runtime.get("completed_stages", payload.get("completed_stages", [])),
        "sample_size": payload.get("sample_size", 180),
        "partial_metrics": runtime.get("partial_metrics", {}),
        "report_url": runtime.get("report_url"),
        "error": (getattr(record, "error_message", "") if isinstance(getattr(record, "error_message", ""), str) else "") or runtime.get("error") or None,
        "verified": runtime.get("verified"),
        "created_at": _iso(created_at),
        "updated_at": _iso(updated_at),
        "started_at": _iso(created_at),
        "completed_at": _iso(updated_at) if status in {"completed", "partial", "failed", "cancelled"} else None,
    }


def _evaluation_metrics(runtime: dict) -> dict:
    partial = runtime.get("partial_metrics") if isinstance(runtime.get("partial_metrics"), dict) else {}
    direct = runtime.get("metrics") if isinstance(runtime.get("metrics"), dict) else {}
    partial = partial or direct
    if isinstance(partial.get("primary"), dict):
        primary = partial.get("primary") or {}
        comparisons = partial.get("comparisons") if isinstance(partial.get("comparisons"), dict) else {}
    else:
        primary = {
            "retrieval": partial.get("retrieval", {}),
            "rag": partial.get("rag", partial.get("ragas", {})),
        }
        comparisons = {}
        if isinstance(partial.get("chunking"), dict):
            comparisons = partial["chunking"].get("strategies", {}) or {}
    # Flat aliases keep old downloads/status consumers working while the
    # primary/comparisons shape is authoritative for the workbench.
    primary_retrieval = primary.get("retrieval", {}) if isinstance(primary, dict) else {}
    primary_rag = primary.get("rag", primary.get("ragas", {})) if isinstance(primary, dict) else {}
    comparison_payload = comparisons if isinstance(comparisons, dict) else {}
    return {
        "primary": {"retrieval": primary_retrieval, "rag": primary_rag},
        "comparisons": comparison_payload,
        "rag": primary_rag,
        "retrieval": primary_retrieval,
        "chunking": {"strategies": comparison_payload},
    }


def _requested_from_payload(payload: dict) -> dict:
    requested = payload.get("requested_configuration")
    if isinstance(requested, dict):
        return requested
    primary = payload.get("primary_chunking_strategy")
    comparisons = payload.get("comparison_chunking_strategies")
    old = payload.get("chunking_strategies") or []
    return {
        "source": payload.get("source", {}),
        "primary_chunking_strategy": primary or (old[0] if old else "auto_parent_child"),
        "comparison_chunking_strategies": list(comparisons if isinstance(comparisons, list) else old[1:]),
        "retrieval_strategy": payload.get("retrieval_strategy", "hybrid"),
        "rerank_enabled": bool(payload.get("rerank_enabled", True)),
        "answer_model_id": payload.get("answer_model_id", ""),
        "judge_model_id": payload.get("judge_model_id", ""),
    }


def _evaluation_run_payload(record) -> dict:
    payload = record.payload if isinstance(record.payload, dict) else {}
    runtime = record.result if isinstance(record.result, dict) else {}
    legacy = _open_run_payload(record)
    metrics = _evaluation_metrics(runtime)
    total_questions = int(runtime.get("total_questions") or payload.get("sample_size") or 0)
    completed_questions = int(runtime.get("completed_questions") or 0)
    created_at = getattr(record, "created_at", None)
    updated_at = getattr(record, "updated_at", None)
    end_at = updated_at if str(getattr(record, "status", "")) in {"completed", "partial", "failed", "cancelled"} else timezone.now()
    elapsed_seconds = runtime.get("elapsed_seconds")
    if elapsed_seconds is None and hasattr(created_at, "isoformat") and hasattr(end_at, "isoformat"):
        elapsed_seconds = max(0.0, (end_at - created_at).total_seconds())
    progress = float(legacy.get("progress") or 0)
    eta_seconds = runtime.get("eta_seconds", runtime.get("estimated_remaining_seconds"))
    if eta_seconds is None and elapsed_seconds is not None and 0 < progress < 1:
        eta_seconds = max(0.0, float(elapsed_seconds) * (1 - progress) / progress)
    requested = _requested_from_payload(payload)
    effective = runtime.get("effective_pipeline") or payload.get("effective_pipeline") or {}
    verification_status = str(runtime.get("verification_status") or "").lower()
    if verification_status not in {"verified", "degraded", "unverified", "failed"}:
        if str(getattr(record, "status", "")) == "failed":
            verification_status = "failed"
        elif runtime.get("verified") is True:
            verification_status = "verified"
        elif runtime.get("verified") is False and metrics["primary"].get("retrieval"):
            verification_status = "degraded"
        else:
            verification_status = "unverified"
    report_data = runtime.get("report") if isinstance(runtime.get("report"), dict) else {}
    report_id = str(
        report_data.get("id") or report_data.get("report_id") or runtime.get("report_id") or ""
    )
    report_url = report_data.get("url") or report_data.get("report_url") or runtime.get("report_url")
    available = bool(report_data.get("available", bool(report_id and report_url)))
    if report_id and not report_data.get("available"):
        try:
            from .eval_reports import report_exists
            from .models import Tenant

            owner = Tenant.objects.filter(id=str(payload.get("tenant_id") or "")).first()
            if owner is not None:
                available = report_exists(owner, report_id)
        except Exception:
            pass
    report_freshness = str(runtime.get("freshness_status") or (report_data.get("freshness_status") if report_data else "unknown") or "unknown")
    if report_id:
        try:
            from .eval_reports import get_evaluation_report
            from .models import Tenant

            owner = Tenant.objects.filter(id=str(payload.get("tenant_id") or "")).first()
            stored_report = get_evaluation_report(owner, report_id) if owner is not None else None
            if stored_report:
                available = True
                report_freshness = str(stored_report.get("freshness_status") or report_freshness)
                report_url = stored_report.get("report_url") or report_url
        except Exception:
            pass
    report = {"id": report_id or None, "url": report_url or None, "available": bool(available and (report_id or report_url))}
    return {
        **legacy,
        "run_id": str(getattr(record, "id", "")),
        "run_status": legacy["status"],
        "source": payload.get("source", {}),
        "requested_configuration": requested,
        "effective_pipeline": effective,
        "configuration_fingerprint": payload.get("configuration_fingerprint", ""),
        "metrics": metrics,
        "partial_metrics": metrics,
        "verification_status": verification_status,
        "freshness_status": report_freshness,
        "completed_questions": completed_questions,
        "total_questions": total_questions,
        "failed_questions": int(runtime.get("failed_questions") or 0),
        "valid_coverage": runtime.get("valid_coverage"),
        "elapsed_seconds": round(float(elapsed_seconds), 1) if elapsed_seconds is not None else None,
        "eta_seconds": round(float(eta_seconds), 1) if eta_seconds is not None else None,
        "estimated_remaining_seconds": round(float(eta_seconds), 1) if eta_seconds is not None else None,
        "report": report,
    }


def _tenant_task_record(tenant, run_id: str):
    from .models import TaskRecord

    for candidate in TaskRecord.objects.filter(id=run_id, task_type="open_rag_evaluation"):
        payload = candidate.payload if isinstance(candidate.payload, dict) else {}
        if str(payload.get("tenant_id")) == str(tenant.id):
            return candidate
    return None


def _cancel_evaluation_record(record):
    """Publish cancellation immediately while workers stop cooperatively."""
    from django.core.cache import cache
    from .models import TaskRecord

    if record.status in {"pending", "running"}:
        now = timezone.now()
        TaskRecord.objects.filter(id=record.id, status__in=("pending", "running")).update(
            status="cancelled",
            cancel_requested_at=now,
            error_message="cancelled by user",
            claimed_by="",
            lease_expires_at=None,
            updated_at=now,
        )
        cache.set(
            f"task:{record.id}",
            {"status": "cancelled", "error": "cancelled by user"},
            timeout=7 * 24 * 60 * 60,
        )
        record.refresh_from_db()
    return record


def _validate_model_choice(tenant, model_id: str, *, judge=False):
    if not model_id:
        return None
    from .model_providers import is_env_chat_model_id
    from .models import ModelConfig

    if is_env_chat_model_id(model_id):
        from django.conf import settings

        if settings.LLM_USE_ENV_CHAT and settings.LLM_CHAT_API_KEY:
            return None
        raise ValueError("model not found")
    model = ModelConfig.objects.filter(
        id=model_id,
        tenant=tenant,
        status="active",
        deleted_at__isnull=True,
    ).first()
    if model is None:
        raise ValueError("model not found")
    model_type = str(model.type or "").strip().lower().replace("-", "_")
    chat_types = {"chat", "knowledgeqa", "llm", "judge", "answer", "text_generation"}
    if model_type not in chat_types:
        raise ValueError("judge model must support chat" if judge else "answer model must support chat")
    return model


def _dataset_hash(data: dict) -> str:
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _unified_run_configuration(tenant, data: dict) -> tuple[dict, str]:
    if not isinstance(data, dict):
        raise ValueError("request body must be a JSON object")
    source = data.get("source")
    if not isinstance(source, dict):
        raise ValueError("source is required")
    source_type = str(source.get("type") or "")
    retrieval_strategy = str(data.get("retrieval_strategy") or "hybrid").lower()
    if retrieval_strategy not in {"keyword", "vector", "hybrid"}:
        raise ValueError("unsupported retrieval strategy")
    primary, comparisons, legacy_contract = _normalize_chunking_configuration(data)
    answer_model_id = str(data.get("answer_model_id") or "")
    judge_model_id = str(data.get("judge_model_id") or "")
    _validate_model_choice(tenant, answer_model_id)
    _validate_model_choice(tenant, judge_model_id, judge=True)

    normalized_source = dict(source)
    if source_type == "open_dataset":
        dataset_id = str(source.get("dataset_id") or "")
        version = str(source.get("dataset_version") or "arxiv-v1")
        if dataset_id not in PUBLIC_DATASET_COUNTS:
            raise DatasetNotFoundError("open dataset not found")
        spec = get_dataset_spec(dataset_id, version)
        if not open_dataset_status(spec).get("ready"):
            raise OpenRagDatasetError("open dataset is not ready")
        sample_size = PUBLIC_DATASET_COUNTS[dataset_id]
        normalized_source = {"type": source_type, "dataset_id": dataset_id, "dataset_version": version}
        dataset_hash = spec.sha256
        dataset_id_for_task = spec.dataset_id
        dataset_version = spec.version
    elif source_type == "tenant_dataset":
        dataset_id = str(source.get("dataset_id") or "")
        knowledge_base_id = str(source.get("knowledge_base_id") or "")
        resource = _dataset_resource(tenant, dataset_id, None)
        if resource is None:
            raise LookupError("dataset not found")
        if resource.status != "published" or (resource.data or {}).get("schema_version") != "evaluation_v2":
            raise PermissionError("dataset_not_published")
        bound_knowledge_base_id = str((resource.data or {}).get("knowledge_base_id") or "")
        if not bound_knowledge_base_id or bound_knowledge_base_id != knowledge_base_id:
            raise ValueError("dataset knowledge base does not match")
        from .models import KnowledgeBase
        if not KnowledgeBase.objects.filter(
            id=knowledge_base_id, tenant=tenant, deleted_at__isnull=True
        ).exists():
            raise LookupError("knowledge base not found")
        entries = list((resource.data or {}).get("entries") or [])
        if not entries:
            raise ValueError("dataset has no entries")
        sample_size = len(entries)
        dataset_hash = str((resource.data or {}).get("dataset_hash") or _dataset_hash(entries))
        normalized_source = {
            "type": source_type,
            "dataset_id": resource.id,
            "knowledge_base_id": knowledge_base_id,
            "dataset_version": str((resource.data or {}).get("version") or "1"),
        }
        dataset_id_for_task = resource.id
        dataset_version = normalized_source["dataset_version"]
    else:
        raise ValueError("unsupported source type")

    configuration = {
        "tenant_id": str(tenant.id),
        "source": normalized_source,
        "dataset_id": dataset_id_for_task,
        "dataset_version": dataset_version,
        "dataset_hash": dataset_hash,
        "sample_size": sample_size,
        "seed": int(data.get("seed", 20260819)),
        "retrieval_strategy": retrieval_strategy,
        "rerank_enabled": bool(data.get("rerank_enabled", True)),
        "primary_chunking_strategy": primary,
        "comparison_chunking_strategies": comparisons,
        # Compatibility for workers and old clients.  The canonical fields
        # above are what participate in the fingerprint.
        "chunking_strategies": [primary, *comparisons],
        "answer_model_id": answer_model_id,
        "judge_model_id": judge_model_id,
        "index_algorithm_version": INDEX_ALGORITHM_VERSION,
        "legacy_contract": legacy_contract,
    }
    configuration["requested_configuration"] = _requested_configuration(configuration)
    fingerprint = _dataset_hash({
        key: value for key, value in configuration.items()
        if key not in {"configuration_fingerprint", "legacy_contract", "requested_configuration"}
    })
    configuration["configuration_fingerprint"] = fingerprint
    return configuration, fingerprint


def _create_unified_run(tenant, data: dict):
    from .models import TaskRecord

    try:
        configuration, fingerprint = _unified_run_configuration(tenant, data)
        effective = _preflight_evaluation_configuration(
            tenant,
            configuration,
            legacy_contract=bool(configuration.get("legacy_contract")),
        )
        configuration["effective_pipeline"] = effective
        configuration["requested_configuration"] = _requested_configuration(configuration)
        # Effective model signatures are part of the run snapshot.  A model
        # change therefore cannot silently attach new results to an old run.
        fingerprint = _dataset_hash({
            key: value for key, value in configuration.items()
            if key not in {"configuration_fingerprint", "legacy_contract", "requested_configuration", "effective_pipeline"}
        } | {"effective_pipeline": effective})
        configuration["configuration_fingerprint"] = fingerprint
    except EvaluationConfigurationError as exc:
        return None, fail(str(exc), exc.status, exc.code)
    except PermissionError:
        return None, fail("dataset must be published", 422, "dataset_not_published")
    except DatasetNotFoundError:
        return None, fail("open dataset not found", 404, "open_dataset_not_found")
    except OpenRagDatasetError:
        return None, fail("open dataset is not ready", 409, "open_dataset_not_ready")
    except LookupError as exc:
        return None, fail(str(exc), 404, "resource_not_found")
    except (TypeError, ValueError) as exc:
        return None, fail(str(exc), 400, "invalid_configuration")
    active = None
    for candidate in TaskRecord.objects.filter(
        task_type="open_rag_evaluation", status__in=("pending", "running")
    ).order_by("-created_at"):
        candidate_payload = candidate.payload if isinstance(candidate.payload, dict) else {}
        if str(candidate_payload.get("tenant_id")) == str(tenant.id) and candidate_payload.get("configuration_fingerprint") == fingerprint:
            active = candidate
            break
    if active is None:
        active = enqueue("open_rag_evaluation", None, configuration)
    return _evaluation_run_payload(active), None


@csrf_exempt
def rag_eval_runs(request, run_id="", action=""):
    """Create, inspect, cancel and resume one tenant-scoped evaluation task."""
    user, tenant = auth_context(request)
    if not tenant:
        return fail("unauthorized", 401, "unauthorized")
    if request.method == "GET" and not run_id:
        if str(request.GET.get("active") or "").lower() not in {"1", "true", "yes"}:
            return fail("active=true is required", 400, "invalid_query")
        from .models import TaskRecord
        active = None
        for candidate in TaskRecord.objects.filter(
            task_type="open_rag_evaluation", status__in=("pending", "running")
        ).order_by("-created_at"):
            payload = candidate.payload if isinstance(candidate.payload, dict) else {}
            if str(payload.get("tenant_id")) == str(tenant.id):
                active = candidate
                break
        if active is None:
            for candidate in TaskRecord.objects.filter(
                task_type="open_rag_evaluation", status__in=("partial", "failed", "cancelled")
            ).order_by("-updated_at"):
                payload = candidate.payload if isinstance(candidate.payload, dict) else {}
                if str(payload.get("tenant_id")) == str(tenant.id):
                    active = candidate
                    break
        return ok({"active_run": _evaluation_run_payload(active) if active else None})
    if request.method == "POST" and not run_id:
        try:
            data = parse_body(request, strict_json=True)
        except MalformedJsonBody:
            return fail("malformed JSON body", 400, "invalid_json")
        payload, error = _create_unified_run(tenant, data)
        return error or ok(payload, status=202)
    record = _tenant_task_record(tenant, run_id) if run_id else None
    if record is None:
        return fail("run not found", 404, "run_not_found")
    if request.method == "GET" and not action:
        return ok(_evaluation_run_payload(record))
    if request.method != "POST":
        return fail("method not allowed", 405)
    from .models import TaskRecord
    if action == "cancel":
        return ok(_evaluation_run_payload(_cancel_evaluation_record(record)))
    if action == "resume":
        if record.status not in {"failed", "partial", "cancelled"}:
            return fail("run is not resumable", 409, "run_not_resumable")
        TaskRecord.objects.filter(id=record.id).update(
            status="pending",
            cancel_requested_at=None,
            error_message="",
            claimed_by="",
            lease_expires_at=None,
            updated_at=timezone.now(),
        )
        record.refresh_from_db()
        return ok(_evaluation_run_payload(record), status=202)
    return fail("method not allowed", 405)


@csrf_exempt
def rag_eval_run_estimate(request):
    user, tenant = auth_context(request)
    if not tenant:
        return fail("unauthorized", 401, "unauthorized")
    if request.method != "POST":
        return fail("method not allowed", 405)
    try:
        data = parse_body(request, strict_json=True)
        configuration, _fingerprint = _unified_run_configuration(tenant, data)
        effective = _preflight_evaluation_configuration(
            tenant, configuration, legacy_contract=bool(configuration.get("legacy_contract"))
        )
    except EvaluationConfigurationError as exc:
        return fail(str(exc), exc.status, exc.code)
    except (DatasetNotFoundError, OpenRagDatasetError, LookupError, TypeError, ValueError) as exc:
        code = "open_dataset_not_ready" if isinstance(exc, OpenRagDatasetError) else "invalid_configuration"
        status = 409 if isinstance(exc, OpenRagDatasetError) else 400
        return fail(str(exc), status, code)

    from django.db.models import Avg
    from .models import ModelUsage

    averages = {
        str(row["model_type"]).lower(): float(row["average"] or 0) / 1000
        for row in ModelUsage.objects.filter(tenant=tenant, success=True)
        .values("model_type").annotate(average=Avg("duration_ms"))
    }
    count = int(configuration["sample_size"])
    strategies = [configuration["primary_chunking_strategy"], *configuration["comparison_chunking_strategies"]]
    strategy_count = len(strategies)
    batch_size = 32
    retrieval_needs_vectors = configuration["retrieval_strategy"] in {"vector", "hybrid"}
    source = configuration.get("source") or {}
    estimated_documents = count
    if source.get("type") == "open_dataset":
        try:
            estimated_documents = int(get_dataset_spec(configuration["dataset_id"], configuration["dataset_version"]).expected_documents)
        except Exception:
            pass
    chunk_count_per_strategy = max(estimated_documents * 4, count * 4, 1)
    chunk_embedding_calls = (
        ((chunk_count_per_strategy + batch_size - 1) // batch_size) * strategy_count
        if retrieval_needs_vectors or "semantic_parent_child" in strategies else 0
    )
    query_embedding_calls = (
        ((count + batch_size - 1) // batch_size) * strategy_count
        if retrieval_needs_vectors else 0
    )
    calls = {
        "chunk_embeddings": chunk_embedding_calls,
        "query_embeddings": query_embedding_calls,
        "rerank": count * strategy_count if configuration["rerank_enabled"] else 0,
        "answer": count,
        "judge": count,
    }
    duration_per_call = {
        "embedding": averages.get("embedding", 0.05),
        "rerank": averages.get("rerank", 0.02),
        "chat": averages.get("knowledgeqa", averages.get("chat", 0.5)),
        "judge": averages.get("judge", averages.get("chat", 0.5)),
    }
    model_seconds = (
        (calls["chunk_embeddings"] + calls["query_embeddings"]) * duration_per_call["embedding"]
        + calls["rerank"] * duration_per_call["rerank"]
        + calls["answer"] * duration_per_call["chat"]
        + calls["judge"] * duration_per_call["judge"]
    )
    reusable = []
    try:
        from .open_rag_benchmark import _ISOLATED_INDEX_CACHE

        reusable = [
            strategy for strategy in strategies
            if any(key[1] == configuration.get("dataset_hash") and key[3] == strategy for key in _ISOLATED_INDEX_CACHE)
        ]
    except Exception:
        reusable = []
    cache_payload = {
        "reusable_strategy_indexes": reusable,
        "indexes_to_build": [strategy for strategy in strategies if strategy not in reusable],
        "key_prefix": f"{configuration.get('dataset_hash', '')}:{configuration.get('index_algorithm_version', '')}",
    }
    calls["chunk_embeddings"] = (
        ((chunk_count_per_strategy + batch_size - 1) // batch_size) * len(cache_payload["indexes_to_build"])
        if retrieval_needs_vectors or "semantic_parent_child" in strategies else 0
    )
    model_seconds = (
        (calls["chunk_embeddings"] + calls["query_embeddings"]) * duration_per_call["embedding"]
        + calls["rerank"] * duration_per_call["rerank"]
        + calls["answer"] * duration_per_call["chat"]
        + calls["judge"] * duration_per_call["judge"]
    )
    return ok({
        "sample_size": count,
        "strategy_count": strategy_count,
        "strategies": strategies,
        "estimated_seconds": round(model_seconds, 1) if model_seconds else None,
        "estimated_calls": calls,
        "estimated_model_calls": sum(calls.values()),
        "cache": cache_payload,
        "requested_configuration": _requested_configuration(configuration),
        "effective_pipeline": effective,
        "based_on_history": bool(averages),
    })


def _create_open_rag_run(tenant, data: dict):
    """Validate, deduplicate, and enqueue one public evaluation run."""
    from .models import TaskRecord

    if not isinstance(data, dict):
        return None, fail("request body must be a JSON object", 400, "invalid_configuration")
    try:
        configuration, fingerprint = _open_run_configuration(data, tenant)
        spec = get_dataset_spec(configuration["dataset_id"], configuration["dataset_version"])
    except (ValueError, DatasetNotFoundError) as exc:
        return None, fail(str(exc) or "invalid open evaluation configuration", 400, "invalid_configuration")
    if not open_dataset_status(spec).get("ready"):
        return None, fail("open dataset is not ready", 409, "open_dataset_not_ready")
    active = None
    for candidate in TaskRecord.objects.filter(
        task_type="open_rag_evaluation", status__in=("pending", "running"),
    ).order_by("-created_at"):
        candidate_payload = candidate.payload if isinstance(candidate.payload, dict) else {}
        if str(candidate_payload.get("tenant_id")) == str(tenant.id) and candidate_payload.get("configuration_fingerprint") == fingerprint:
            active = candidate
            break
    if active is None:
        active = enqueue("open_rag_evaluation", None, configuration)
    return _open_run_payload(active), None


@csrf_exempt
def rag_eval_open_runs(request, run_id="", action=""):
    """Create and monitor one tenant-scoped unified public evaluation task."""
    user, tenant = auth_context(request)
    if not tenant:
        return fail("unauthorized", 401, "unauthorized")
    from .models import TaskRecord

    if request.method == "POST" and not run_id:
        try:
            data = parse_body(request, strict_json=True)
        except MalformedJsonBody:
            return fail("malformed JSON body", 400, "invalid_json")
        payload, error = _create_open_rag_run(tenant, data)
        return error or ok(payload, status=202)

    if not run_id or request.method not in {"GET", "POST"}:
        return fail("method not allowed", 405)
    record = None
    for candidate in TaskRecord.objects.filter(
        id=run_id,
        task_type="open_rag_evaluation",
    ):
        candidate_payload = candidate.payload if isinstance(candidate.payload, dict) else {}
        if str(candidate_payload.get("tenant_id")) == str(tenant.id):
            record = candidate
            break
    if record is None:
        return fail("run not found", 404, "run_not_found")
    if request.method == "POST":
        if action != "cancel":
            return fail("method not allowed", 405)
        return ok(_open_run_payload(_cancel_evaluation_record(record)))
    return ok(_open_run_payload(record))


@csrf_exempt
def rag_eval_datasets(request, dataset_id=""):
    """Create/list/read tenant-scoped candidates and their review state."""
    user, tenant = auth_context(request)
    if not tenant:
        return fail("unauthorized", 401)
    if request.method == "GET":
        if dataset_id:
            resource = _dataset_resource(tenant, dataset_id)
            if resource is None:
                return fail("dataset not found", 404, "dataset_not_found")
            return ok(_resource_payload(resource))
        from .models import GenericResource
        resources = GenericResource.objects.filter(
            tenant=tenant, resource_type=DATASET_RESOURCE_TYPE, deleted_at__isnull=True
        ).order_by("-created_at")
        return ok({"datasets": [_resource_payload(resource) for resource in resources]})
    if request.method != "POST" or dataset_id:
        return fail("method not allowed", 405)
    data = parse_body(request)
    review_mode = data.get("review_mode", "auto")
    if review_mode not in REVIEW_MODES:
        return fail("invalid review_mode", 400)
    knowledge_base_id = str(data.get("knowledge_base_id") or "")
    if knowledge_base_id:
        from .models import KnowledgeBase

        if not KnowledgeBase.objects.filter(
            id=knowledge_base_id, tenant=tenant, deleted_at__isnull=True
        ).exists():
            return fail("knowledge base not found", 404, "knowledge_base_not_found")
    try:
        entries = _normalize_eval_entries(
            tenant, data.get("entries", []), review_mode, knowledge_base_id
        )
    except ValueError as exc:
        return fail(str(exc), 400)
    knowledge_base_id = knowledge_base_id or _dataset_knowledge_base_id(tenant, entries)
    from .models import GenericResource
    resource = GenericResource.objects.create(
        tenant=tenant,
        resource_type=DATASET_RESOURCE_TYPE,
        name=str(data.get("name") or "RAG evaluation dataset")[:255],
        status="draft",
        data=_evaluation_dataset_data(
            review_mode=review_mode,
            entries=entries,
            knowledge_base_id=knowledge_base_id,
        ),
    )
    return ok(_resource_payload(resource), status=201)


@csrf_exempt
def rag_eval_dataset_review(request, dataset_id):
    """Review endpoints change status only; candidate content remains immutable."""
    user, tenant = auth_context(request)
    if not tenant:
        return fail("unauthorized", 401)
    if request.method != "POST":
        return fail("method not allowed", 405)
    resource = _dataset_resource(tenant, dataset_id, None)
    if resource is None:
        return fail("dataset not found", 404, "dataset_not_found")
    if resource.status == "published":
        return fail("published dataset is immutable", 409, "dataset_immutable")
    data = parse_body(request)
    status = data.get("status")
    entry_ids = data.get("entry_ids")
    if status not in REVIEW_STATUSES or not isinstance(entry_ids, list) or not entry_ids:
        return fail("status and entry_ids are required", 400)
    selected = {str(entry_id) for entry_id in entry_ids}
    entries = list((resource.data or {}).get("entries", []))
    found = 0
    for entry in entries:
        if str(entry.get("id")) in selected:
            entry["status"] = status
            found += 1
    if found != len(selected):
        return fail("entry not found", 404, "dataset_entry_not_found")
    resource.data = _evaluation_dataset_data(
        review_mode=(resource.data or {}).get("review_mode", "auto"),
        entries=entries,
        existing=resource.data,
    )
    resource.save(update_fields=["data", "updated_at"])
    if data.get("publish") is True:
        error = _publish_dataset_resource(tenant, resource)
        if error:
            return error
    return ok(_resource_payload(resource))


def _publish_dataset_resource(tenant, resource):
    if resource.status == "published":
        return fail("published dataset is immutable", 409, "dataset_immutable")
    entries = list((resource.data or {}).get("entries") or [])
    approved = [entry for entry in entries if entry.get("status") == "approved"]
    knowledge_base_id = str((resource.data or {}).get("knowledge_base_id") or "")
    knowledge_base_id = knowledge_base_id or _dataset_knowledge_base_id(tenant, approved)
    if (
        not knowledge_base_id
        or not approved
        or any(_validate_eval_entry(tenant, entry, knowledge_base_id) for entry in approved)
    ):
        return fail("dataset has no valid approved entries", 422, "unverified_eval_dataset")
    data = _evaluation_dataset_data(
        review_mode=(resource.data or {}).get("review_mode", "auto"),
        entries=approved,
        existing=resource.data,
        knowledge_base_id=knowledge_base_id,
    )
    data["version"] = int((resource.data or {}).get("version") or 0) + 1
    data["published_at"] = timezone.now().isoformat()
    resource.status = "published"
    resource.data = data
    resource.save(update_fields=["status", "data", "updated_at"])
    return None


@csrf_exempt
def rag_eval_dataset_publish(request, dataset_id):
    user, tenant = auth_context(request)
    if not tenant:
        return fail("unauthorized", 401)
    if request.method != "POST":
        return fail("method not allowed", 405)
    resource = _dataset_resource(tenant, dataset_id, None)
    if resource is None:
        return fail("dataset not found", 404, "dataset_not_found")
    error = _publish_dataset_resource(tenant, resource)
    if error:
        return error
    return ok(_resource_payload(resource))


@csrf_exempt
def rag_eval_run(request):
    """
    运行 RAG 评估。

    POST /api/v1/rag-eval/run
    Body:
        - questions: 评估问题列表（可选，不提供则使用默认问题）
        - eval_llm_model: 评估用的 LLM 模型（可选）
    """
    user, tenant = auth_context(request)
    if not tenant:
        return fail("unauthorized", 401)
    if request.method != "POST":
        return fail("method not allowed", 405)

    data = parse_body(request)
    questions = data.get("questions")
    dataset_id = data.get("dataset_id")
    open_dataset_id = str(data.get("open_dataset_id") or "")
    open_dataset_version = str(data.get("dataset_version") or "arxiv-v1")
    sample_size = max(1, min(int(data.get("sample_size", DEFAULT_OPEN_RAG_SAMPLE_SIZE)), OPEN_RAG_MAX_SAMPLE_SIZE))
    seed = int(data.get("seed", 0))
    eval_llm_model = data.get("eval_llm_model", "")
    knowledge_base_id = str(data.get("knowledge_base_id") or "")

    if sum(bool(value) for value in (dataset_id, open_dataset_id, knowledge_base_id)) > 1:
        return fail("dataset_id and knowledge_base_id are mutually exclusive", 400)
    if open_dataset_id:
        payload, error = _create_open_rag_run(tenant, {
            **data,
            "open_dataset_id": open_dataset_id,
            "dataset_version": open_dataset_version,
            "retrieval_strategy": data.get("retrieval_strategy") or data.get("strategy") or "hybrid",
        })
        return error or ok(payload, status=202)
    if knowledge_base_id:
        from .models import KnowledgeBase

        if not KnowledgeBase.objects.filter(
            id=knowledge_base_id,
            tenant=tenant,
            deleted_at__isnull=True,
        ).exists():
            return fail("knowledge base not found", 404, "knowledge_base_not_found")

    if dataset_id:
        if questions is not None:
            return fail("questions and dataset_id are mutually exclusive", 400)
        dataset = _dataset_resource(tenant, str(dataset_id), None)
        if dataset is None:
            return fail("dataset not found", 404, "dataset_not_found")
        questions = _approved_questions(tenant, dataset)
        if not questions:
            return fail("dataset has no verified approved entries", 422, "unverified_eval_dataset")
    elif questions is None:
        # Prefer the tenant's saved questions. Defaults are used only before a
        # tenant has saved any questions, so they cannot overwrite saved data.
        questions = _load_eval_questions(tenant)

    if not questions:
        return fail("No evaluation questions provided", 400)

    try:
        # 运行评估
        result = run_rag_evaluation(
            tenant=tenant,
            questions=questions,
            eval_llm_model=eval_llm_model,
            knowledge_base_id=knowledge_base_id,
        )

        # 转换 details 为可序列化的 dict
        details = []
        for d in result.details:
            details.append({
                "question": d.question,
                "answer": d.answer[:500],
                "contexts_count": len(d.contexts),
                "ground_truth": d.ground_truth[:200] if d.ground_truth else "",
                "faithfulness": round(d.faithfulness, 4),
                "answer_relevancy": round(d.answer_relevancy, 4),
                "context_precision": round(d.context_precision, 4),
                "context_recall": round(d.context_recall, 4),
                "answer_correctness": round(d.answer_correctness, 4),
            })

        result_data = {
            "faithfulness": round(result.faithfulness, 4),
            "answer_relevancy": round(result.answer_relevancy, 4),
            "context_precision": round(result.context_precision, 4),
            "context_recall": round(result.context_recall, 4),
            "answer_correctness": round(result.answer_correctness, 4),
            "total_questions": result.total_questions,
            "eval_time_ms": result.eval_time_ms,
            "details": details,
            "verified": True,
        }
        return ok(
            _with_report(
                tenant,
                evaluation_type="rag",
                evaluator="ragas",
                dataset=questions,
                result=result_data,
                configuration={"eval_llm_model": eval_llm_model or getattr(settings, "LLM_CHAT_MODEL", "")},
            )
        )

    except RagasEvaluationError:
        logger.exception("RAG evaluation failed in Ragas")
        return fail("Ragas evaluation failed", 502, "ragas_evaluation_failed")
    except Exception as e:
        logger.exception("RAG evaluation failed")
        return fail(f"Evaluation failed: {str(e)}", 500)


def _ragas_testset_entries(
    tenant,
    size: int,
    eval_llm_model: str,
    review_mode: str,
    knowledge_base_id: str = "",
    question_types: list[str] | None = None,
) -> list[dict]:
    """Generate Ragas candidates from tenant chunks and attach exact source spans."""
    from langchain_core.documents import Document

    from .models import Chunk
    from .ragas_adapter import generate_testset_candidates

    chunks_query = Chunk.objects.filter(
        tenant=tenant,
        is_enabled=True,
        deleted_at__isnull=True,
        knowledge__tenant=tenant,
        knowledge__deleted_at__isnull=True,
        knowledge_base__tenant=tenant,
        knowledge_base__deleted_at__isnull=True,
    ).select_related("knowledge")
    if knowledge_base_id:
        chunks_query = chunks_query.filter(knowledge_base_id=knowledge_base_id)
    chunks = list(chunks_query[:200])
    documents = [
        Document(
            page_content=chunk.content,
            metadata={
                "chunk_id": chunk.id,
                "knowledge_id": chunk.knowledge_id,
                "source_start": chunk.start_at,
                "source_end": chunk.end_at,
            },
        )
        for chunk in chunks
        if chunk.content.strip() and chunk.end_at > chunk.start_at
    ]
    generated = generate_testset_candidates(documents, size, eval_llm_model, question_types, tenant=tenant)
    by_content = {chunk.content: chunk for chunk in chunks}
    entries = []
    for candidate in generated:
        contexts = candidate.get("reference_contexts") or []
        evidence = []
        for context in contexts:
            chunk = by_content.get(context)
            if chunk:
                evidence.append({
                    "chunk_id": chunk.id,
                    "knowledge_id": chunk.knowledge_id,
                    "source_start": chunk.start_at,
                    "source_end": chunk.end_at,
                })
        entries.append({
            "question": candidate.get("user_input", ""),
            "answer": candidate.get("reference", ""),
            "ground_truth": candidate.get("reference", ""),
            "evidence": evidence,
        })
    return _normalize_eval_entries(tenant, entries, review_mode, knowledge_base_id)


@csrf_exempt
def rag_eval_testsets(request, testset_id=""):
    """Generate/list/read Ragas TestsetGenerator candidates without scoring them."""
    user, tenant = auth_context(request)
    if not tenant:
        return fail("unauthorized", 401)
    if request.method == "GET":
        if testset_id:
            resource = _dataset_resource(tenant, testset_id, TESTSET_RESOURCE_TYPE)
            if resource is None:
                return fail("testset not found", 404, "testset_not_found")
            return ok(_resource_payload(resource))
        from .models import GenericResource
        resources = GenericResource.objects.filter(
            tenant=tenant, resource_type=TESTSET_RESOURCE_TYPE, deleted_at__isnull=True
        ).order_by("-created_at")
        return ok({"testsets": [_resource_payload(resource) for resource in resources]})
    if request.method != "POST" or testset_id:
        return fail("method not allowed", 405)
    data = parse_body(request)
    review_mode = data.get("review_mode", "auto")
    if review_mode not in REVIEW_MODES:
        return fail("invalid review_mode", 400)
    question_types = data.get("question_types") or ["simple", "reasoning"]
    if not isinstance(question_types, list) or not question_types or not set(question_types).issubset(QUESTION_TYPES):
        return fail("invalid question_types", 400)
    knowledge_base_id = str(data.get("knowledge_base_id") or "")
    if knowledge_base_id:
        from .models import KnowledgeBase

        if not KnowledgeBase.objects.filter(
            id=knowledge_base_id,
            tenant=tenant,
            deleted_at__isnull=True,
        ).exists():
            return fail("knowledge base not found", 404, "knowledge_base_not_found")
    try:
        size = max(1, min(int(data.get("testset_size", DEFAULT_TESTSET_SIZE)), MAX_EVAL_QUESTIONS))
        entries = _ragas_testset_entries(
            tenant,
            size,
            data.get("eval_llm_model", ""),
            review_mode,
            knowledge_base_id,
            question_types,
        )
    except Exception:
        logger.exception("Ragas testset generation failed")
        return fail("Ragas testset generation failed", 502, "ragas_evaluation_failed")
    from .models import GenericResource
    resource = GenericResource.objects.create(
        tenant=tenant,
        resource_type=TESTSET_RESOURCE_TYPE,
        name=str(data.get("name") or "Ragas testset")[:255],
        status="draft",
        data=_evaluation_dataset_data(
            review_mode=review_mode,
            entries=entries,
            question_types=question_types,
            knowledge_base_id=knowledge_base_id,
        ),
    )
    return ok(_resource_payload(resource), status=201)


@csrf_exempt
def rag_eval_questions(request):
    """
    获取/管理评估问题。

    GET /api/v1/rag-eval/questions - 获取评估问题列表
    POST /api/v1/rag-eval/questions - 添加评估问题
    """
    user, tenant = auth_context(request)
    if not tenant:
        return fail("unauthorized", 401)

    if request.method == "GET":
        # 从数据库或文件加载评估问题
        questions = _load_eval_questions(tenant)
        return ok({"questions": _with_question_ids(questions)})

    elif request.method == "POST":
        data = parse_body(request)
        question = data.get("question")
        ground_truth = data.get("ground_truth", "")

        if not question:
            return fail("Question is required", 400)

        # 保存评估问题
        _save_eval_question(tenant, question, ground_truth)
        return ok({"message": "Question added"})

    return fail("Method not allowed", 405)


def _eval_question_id(entry: dict) -> str:
    """旧数据没有 id，用内容哈希生成稳定 id，删除时才能精确定位。"""
    raw = f"{entry.get('question', '')}|{entry.get('ground_truth', '')}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _with_question_ids(questions) -> list[dict]:
    normalized = []
    for raw in questions or []:
        entry = dict(raw or {})
        if not entry.get("id"):
            entry["id"] = _eval_question_id(entry)
        normalized.append(entry)
    return normalized


@csrf_exempt
def rag_eval_question_delete(request, question_id):
    """
    删除评估问题。

    DELETE /api/v1/rag-eval/questions/<question_id>
    """
    user, tenant = auth_context(request)
    if not tenant:
        return fail("unauthorized", 401)
    if request.method != "DELETE":
        return fail("Method not allowed", 405)

    from .models import GenericResource

    resource = GenericResource.objects.filter(
        tenant=tenant,
        resource_type="rag_eval_questions",
    ).first()

    current = _with_question_ids(_load_eval_questions(tenant))
    remaining = [entry for entry in current if str(entry.get("id")) != str(question_id)]
    if len(remaining) == len(current):
        return fail("question not found", 404)

    # 首次删除默认问题时落库，保证删除结果在下次加载时仍然生效
    if resource is None:
        resource = GenericResource(tenant=tenant, resource_type="rag_eval_questions", data={})
    resource.data = {**(resource.data or {}), "questions": remaining}
    resource.save()
    return ok({"message": "Question deleted", "remaining": len(remaining)})


def _load_eval_questions(tenant) -> list[dict]:
    """加载评估问题"""
    # 从 GenericResource 加载
    from .models import GenericResource

    resource = GenericResource.objects.filter(
        tenant=tenant,
        resource_type="rag_eval_questions",
    ).first()

    if resource and resource.data:
        return resource.data.get("questions", [])

    # 返回默认问题
    return get_default_eval_questions()


@csrf_exempt
def rag_eval_generate(request):
    """
    从知识库自动生成评估问题。

    POST /api/v1/rag-eval/generate
    Body:
        - num_questions: 要生成的问题数量（默认 100，最多 100）
        - question_types: 问题类型列表（默认 ["simple", "reasoning"]）
    """
    user, tenant = auth_context(request)
    if not tenant:
        return fail("unauthorized", 401)

    data = parse_body(request)
    num_questions = max(1, min(int(data.get("num_questions", DEFAULT_TESTSET_SIZE)), MAX_EVAL_QUESTIONS))
    question_types = data.get("question_types", ["simple", "reasoning"])

    try:
        from .eval_generator import generate_and_save_eval_questions

        questions = generate_and_save_eval_questions(
            tenant=tenant,
            num_questions=num_questions,
            question_types=question_types,
        )

        return ok({
            "generated": len(questions),
            "questions": questions,
        })

    except Exception as e:
        logger.exception("Failed to generate eval questions")
        return fail(f"Generation failed: {str(e)}", 500)


def _save_eval_question(tenant, question: str, ground_truth: str):
    """保存评估问题"""
    from .models import GenericResource

    resource, created = GenericResource.objects.get_or_create(
        tenant=tenant,
        resource_type="rag_eval_questions",
        defaults={"data": {"questions": []}},
    )

    questions = resource.data.get("questions", [])
    questions.append({
        "id": uuid.uuid4().hex[:16],
        "question": question,
        "ground_truth": ground_truth,
    })
    resource.data = {"questions": questions}
    resource.save(update_fields=["data", "updated_at"])


@csrf_exempt
def rag_eval_history(request):
    """
    获取评估历史。

    GET /api/v1/rag-eval/history
    """
    user, tenant = auth_context(request)
    if not tenant:
        return fail("unauthorized", 401)

    from .eval_reports import recent_evaluation_reports

    return ok({"history": recent_evaluation_reports(tenant)})


@csrf_exempt
def rag_eval_report(request, run_id):
    """Download or delete one tenant-scoped evaluation report."""
    user, tenant = auth_context(request)
    if not tenant:
        return fail("unauthorized", 401)
    from .eval_reports import delete_evaluation_report, get_evaluation_report

    if request.method == "DELETE":
        if not delete_evaluation_report(tenant, run_id):
            return fail("report not found", 404, "report_not_found")
        return HttpResponse(status=204)
    if request.method != "GET":
        return fail("method not allowed", 405)
    report = get_evaluation_report(tenant, run_id)
    if report is None:
        return fail("report not found", 404, "report_not_found")
    response = HttpResponse(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        content_type="application/json; charset=utf-8",
    )
    response["Content-Disposition"] = content_disposition_header(True, f"rag-eval-{run_id}.json")
    return response


@csrf_exempt
def retrieval_eval_run(request):
    """
    运行确定性检索评估（MRR@10 / Recall@20，新管线 vs 基线）。

    POST /api/v1/rag-eval/retrieval
    Body:
        - dataset: 可选，覆盖默认数据集（[{query, kb_ids, relevant_chunk_ids}]）
    """
    user, tenant = auth_context(request)
    if not tenant:
        return fail("unauthorized", 401)
    from .retrieval_eval import load_retrieval_dataset, run_retrieval_comparison

    data = parse_body(request)
    open_dataset_id = str(data.get("open_dataset_id") or "")
    if open_dataset_id:
        payload, error = _create_open_rag_run(tenant, {
            **data,
            "retrieval_strategy": data.get("retrieval_strategy") or data.get("strategy") or "hybrid",
        })
        return error or ok(payload, status=202)
    dataset = data.get("dataset")
    effective_dataset = dataset if dataset is not None else load_retrieval_dataset()
    try:
        result = run_retrieval_comparison(tenant.id, dataset=effective_dataset)
    except Exception as exc:
        logger.exception("retrieval eval failed")
        return fail(f"retrieval eval failed: {exc}", 500)
    return ok(
        _with_report(
            tenant,
            evaluation_type="retrieval",
            evaluator="deterministic",
            dataset=effective_dataset,
            result=result,
            configuration={
                "k_hit": result.get("k_hit"),
                "k_mrr": result.get("k_mrr"),
                "k_recall": result.get("k_recall"),
                "pipeline": result.get("pipeline", {}),
            },
        )
    )


@csrf_exempt
def chunking_eval_run(request):
    """Run isolated, tenant-scoped chunking comparison evaluation."""
    user, tenant = auth_context(request)
    if not tenant:
        return fail("unauthorized", 401)
    if request.method != "POST":
        return fail("method not allowed", 405)

    try:
        data = parse_body(request, strict_json=True)
    except MalformedJsonBody:
        return fail("malformed JSON body", 400, "invalid_json")
    if not isinstance(data, dict):
        return fail("request body must be a JSON object", 400)
    open_dataset_id = str(data.get("open_dataset_id") or "")
    if open_dataset_id:
        payload, error = _create_open_rag_run(tenant, {
            **data,
            "chunking_strategies": data.get("chunking_strategies") or data.get("strategies") or OPEN_RAG_CHUNKING_STRATEGIES,
        })
        return error or ok(payload, status=202)
    dataset = data.get("dataset")
    strategies = data.get("strategies")
    if dataset is not None and not isinstance(dataset, list):
        return fail("dataset must be a list", 400)
    if strategies is not None and (
        not isinstance(strategies, list) or not all(isinstance(strategy, str) for strategy in strategies)
    ):
        return fail("strategies must be a list of strings", 400)

    from .chunking_eval import load_chunking_dataset, run_chunking_comparison

    try:
        effective_dataset = dataset
        if effective_dataset is None:
            effective_dataset, _declared_status = load_chunking_dataset()
        result = run_chunking_comparison(tenant.id, dataset=effective_dataset, strategies=strategies)
    except Exception:
        logger.exception("chunking eval failed")
        return fail("chunking evaluation failed", 500, "chunking_eval_failed")
    return ok(
        _with_report(
            tenant,
            evaluation_type="chunking",
            evaluator="deterministic_source_span",
            dataset=effective_dataset,
            result=result,
            configuration={"strategies": strategies or []},
        )
    )
