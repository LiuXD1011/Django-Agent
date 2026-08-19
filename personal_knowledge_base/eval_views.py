"""
RAG 评估 API 视图

提供 RAG 评估功能的 API 端点。
"""

import hashlib
import json
import logging
import uuid

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils.http import content_disposition_header
from django.views.decorators.csrf import csrf_exempt

from .authentication import require_auth
from .rag_eval import RagasEvaluationError, get_default_eval_questions, run_rag_evaluation
from .responses import fail, ok

logger = logging.getLogger(__name__)

DATASET_RESOURCE_TYPE = "rag_eval_datasets"
TESTSET_RESOURCE_TYPE = "rag_eval_testsets"
REVIEW_MODES = {"auto", "manual", "sample"}
REVIEW_STATUSES = {"approved", "rejected", "pending_review"}


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


def _with_report(tenant, *, evaluation_type: str, evaluator: str, dataset, result: dict, configuration=None) -> dict:
    from .eval_reports import save_evaluation_report

    metadata = save_evaluation_report(
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
        "entries": data.get("entries", []),
        "created_at": resource.created_at.isoformat() if resource.created_at else "",
        "updated_at": resource.updated_at.isoformat() if resource.updated_at else "",
    }


def _validate_eval_entry(tenant, entry: dict) -> list[str]:
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
    return sorted(set(errors))


def _normalize_eval_entries(tenant, entries, review_mode: str) -> list[dict]:
    if not isinstance(entries, list):
        raise ValueError("entries must be a list")
    normalized = []
    for index, raw in enumerate(entries):
        raw = raw if isinstance(raw, dict) else {}
        item = {
            "id": str(raw.get("id") or uuid.uuid4().hex[:16]),
            "question": raw.get("question", ""),
            "answer": raw.get("answer", ""),
            "ground_truth": raw.get("ground_truth", ""),
            "evidence": raw.get("evidence", []),
        }
        errors = _validate_eval_entry(tenant, item)
        item["validation_errors"] = errors
        if review_mode == "auto":
            item["status"] = "approved" if not errors else "rejected"
        elif review_mode == "sample" and index % 10 == 0:
            item["status"] = "approved" if not errors else "rejected"
        else:
            item["status"] = "pending_review"
        normalized.append(item)
    return normalized


def _dataset_resource(tenant, dataset_id: str, resource_type: str = DATASET_RESOURCE_TYPE):
    from .models import GenericResource

    return GenericResource.objects.filter(
        id=dataset_id,
        tenant=tenant,
        resource_type=resource_type,
        deleted_at__isnull=True,
    ).first()


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
    try:
        entries = _normalize_eval_entries(tenant, data.get("entries", []), review_mode)
    except ValueError as exc:
        return fail(str(exc), 400)
    from .models import GenericResource
    resource = GenericResource.objects.create(
        tenant=tenant,
        resource_type=DATASET_RESOURCE_TYPE,
        name=str(data.get("name") or "RAG evaluation dataset")[:255],
        status="active",
        data={"review_mode": review_mode, "entries": entries},
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
    resource = _dataset_resource(tenant, dataset_id)
    if resource is None:
        return fail("dataset not found", 404, "dataset_not_found")
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
    resource.data = {**(resource.data or {}), "entries": entries}
    resource.save(update_fields=["data", "updated_at"])
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
    eval_llm_model = data.get("eval_llm_model", "")

    if dataset_id:
        if questions is not None:
            return fail("questions and dataset_id are mutually exclusive", 400)
        dataset = _dataset_resource(tenant, str(dataset_id))
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


def _ragas_testset_entries(tenant, size: int, eval_llm_model: str, review_mode: str) -> list[dict]:
    """Generate Ragas candidates from tenant chunks and attach exact source spans."""
    from langchain_core.documents import Document

    from .models import Chunk
    from .ragas_adapter import generate_testset_candidates

    chunks = list(
        Chunk.objects.filter(
            tenant=tenant,
            is_enabled=True,
            deleted_at__isnull=True,
            knowledge__tenant=tenant,
            knowledge__deleted_at__isnull=True,
            knowledge_base__tenant=tenant,
            knowledge_base__deleted_at__isnull=True,
        ).select_related("knowledge")[:200]
    )
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
    generated = generate_testset_candidates(documents, size, eval_llm_model)
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
    return _normalize_eval_entries(tenant, entries, review_mode)


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
    try:
        size = max(1, min(int(data.get("testset_size", 10)), 50))
        entries = _ragas_testset_entries(tenant, size, data.get("eval_llm_model", ""), review_mode)
    except Exception:
        logger.exception("Ragas testset generation failed")
        return fail("Ragas testset generation failed", 502, "ragas_evaluation_failed")
    from .models import GenericResource
    resource = GenericResource.objects.create(
        tenant=tenant,
        resource_type=TESTSET_RESOURCE_TYPE,
        name=str(data.get("name") or "Ragas testset")[:255],
        status="active",
        data={"review_mode": review_mode, "entries": entries},
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
        - num_questions: 要生成的问题数量（默认 10）
        - question_types: 问题类型列表（默认 ["simple", "reasoning"]）
    """
    user, tenant = auth_context(request)
    if not tenant:
        return fail("unauthorized", 401)

    data = parse_body(request)
    num_questions = min(int(data.get("num_questions", 10)), 50)  # 最多 50 个
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
    """Download one tenant-scoped evaluation report as JSON."""
    user, tenant = auth_context(request)
    if not tenant:
        return fail("unauthorized", 401)
    if request.method != "GET":
        return fail("method not allowed", 405)
    from .eval_reports import get_evaluation_report

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
