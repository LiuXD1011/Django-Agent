"""
RAG 评估 API 视图

提供 RAG 评估功能的 API 端点。
"""

import json
import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .authentication import require_auth
from .rag_eval import EvalResult, get_default_eval_questions, run_rag_evaluation
from .responses import fail, ok

logger = logging.getLogger(__name__)


def parse_body(request):
    if request.content_type and request.content_type.startswith("multipart/"):
        return request.POST.dict()
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except Exception:
        return {}


def auth_context(request):
    try:
        return require_auth(request)
    except PermissionError:
        return None, None


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

    data = parse_body(request)
    questions = data.get("questions")
    eval_llm_model = data.get("eval_llm_model", "")

    # 如果没有提供问题，使用默认问题
    if not questions:
        questions = get_default_eval_questions()

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

        return ok({
            "faithfulness": round(result.faithfulness, 4),
            "answer_relevancy": round(result.answer_relevancy, 4),
            "context_precision": round(result.context_precision, 4),
            "context_recall": round(result.context_recall, 4),
            "answer_correctness": round(result.answer_correctness, 4),
            "total_questions": result.total_questions,
            "eval_time_ms": result.eval_time_ms,
            "details": details,
        })

    except Exception as e:
        logger.exception("RAG evaluation failed")
        return fail(f"Evaluation failed: {str(e)}", 500)


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
        return ok({"questions": questions})

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

    from .models import GenericResource

    # 加载评估历史
    resource = GenericResource.objects.filter(
        tenant=tenant,
        resource_type="rag_eval_history",
    ).first()

    history = []
    if resource and resource.data:
        history = resource.data.get("history", [])

    return ok({"history": history[-10:]})  # 返回最近 10 条


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
    from .retrieval_eval import run_retrieval_comparison

    data = parse_body(request)
    dataset = data.get("dataset")
    try:
        result = run_retrieval_comparison(tenant.id, dataset=dataset)
    except Exception as exc:
        logger.exception("retrieval eval failed")
        return fail(f"retrieval eval failed: {exc}", 500)
    return ok(result)
