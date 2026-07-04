"""
RAG 评估模块

标准 RAGAs 评估流程：
1. 准备评估数据集（question + ground_truth）
2. 运行 RAG 管道获取 answer + contexts
3. 组装评估数据（question + answer + contexts + ground_truth）
4. 使用 RAGAs 评估（LLM-as-a-Judge）
5. 输出评估结果

指标说明：
- Faithfulness（忠实度）：答案是否忠实于检索到的上下文
- Answer Relevancy（答案相关性）：答案是否回答了用户问题
- Context Precision（上下文精确度）：检索到的上下文是否精确
- Context Recall（上下文召回率）：是否检索到了所有相关上下文（需要 ground_truth）
- Answer Correctness（答案正确性）：答案是否正确（需要 ground_truth）
"""

import json
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class EvalQuestion:
    """评估问题"""
    question: str
    ground_truth: str = ""  # 可选，提供后可评估 Context Recall 和 Answer Correctness


@dataclass
class EvalDetail:
    """单个问题的评估详情"""
    question: str
    answer: str
    contexts: list[str]
    ground_truth: str
    faithfulness: float = 0.0
    answer_relevancy: float = 0.0
    context_precision: float = 0.0
    context_recall: float = 0.0  # 需要 ground_truth
    answer_correctness: float = 0.0  # 需要 ground_truth


@dataclass
class EvalResult:
    """评估结果"""
    faithfulness: float = 0.0
    answer_relevancy: float = 0.0
    context_precision: float = 0.0
    context_recall: float = 0.0
    answer_correctness: float = 0.0
    total_questions: int = 0
    eval_time_ms: int = 0
    details: list[EvalDetail] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "faithfulness": round(self.faithfulness, 4),
            "answer_relevancy": round(self.answer_relevancy, 4),
            "context_precision": round(self.context_precision, 4),
            "context_recall": round(self.context_recall, 4),
            "answer_correctness": round(self.answer_correctness, 4),
            "total_questions": self.total_questions,
            "eval_time_ms": self.eval_time_ms,
            "details": [
                {
                    "question": d.question,
                    "answer": d.answer[:500],
                    "contexts_count": len(d.contexts),
                    "ground_truth": d.ground_truth[:200] if d.ground_truth else "",
                    "faithfulness": round(d.faithfulness, 4),
                    "answer_relevancy": round(d.answer_relevancy, 4),
                    "context_precision": round(d.context_precision, 4),
                    "context_recall": round(d.context_recall, 4),
                    "answer_correctness": round(d.answer_correctness, 4),
                }
                for d in self.details
            ],
        }


def run_rag_evaluation(
    tenant,
    questions: list[dict],
    eval_llm_model: str = "",
) -> EvalResult:
    """
    运行 RAG 评估。

    标准流程：
    1. 对每个问题调用 RAG 管道获取 answer + contexts
    2. 组装评估数据
    3. 使用 RAGAs 或简单方法评估

    Args:
        tenant: 租户对象
        questions: 评估问题列表，每项包含 question 和 ground_truth（可选）
        eval_llm_model: 评估用的 LLM 模型名称

    Returns:
        EvalResult 评估结果
    """
    start_time = time.time()

    # Step 1: 对每个问题调用 RAG 管道
    eval_details = []
    for item in questions:
        question = item.get("question", "")
        ground_truth = item.get("ground_truth", "")

        if not question:
            continue

        # 调用 RAG 管道
        answer, contexts = _run_rag_pipeline(tenant, question, eval_llm_model)

        eval_details.append(EvalDetail(
            question=question,
            answer=answer,
            contexts=contexts,
            ground_truth=ground_truth,
        ))

    if not eval_details:
        return EvalResult(total_questions=0, eval_time_ms=int((time.time() - start_time) * 1000))

    # Step 2: 运行评估
    try:
        result = _ragas_evaluation(eval_details, tenant, eval_llm_model)
    except ImportError:
        logger.warning("RAGAs not installed, using simple evaluation")
        result = _simple_evaluation(eval_details)
    except Exception as e:
        logger.exception("RAGAs evaluation failed, falling back to simple evaluation")
        result = _simple_evaluation(eval_details)

    result.total_questions = len(eval_details)
    result.eval_time_ms = int((time.time() - start_time) * 1000)
    return result


def _run_rag_pipeline(tenant, question: str, model_id: str = "") -> tuple[str, list[str]]:
    """
    调用 RAG 管道获取答案和上下文。

    Returns:
        (answer, contexts) 元组
    """
    from .search import hybrid_search
    from .model_providers import chat_completion
    from .models import KnowledgeBase

    # 获取知识库
    kb_ids = list(KnowledgeBase.objects.filter(
        tenant=tenant, deleted_at__isnull=True
    ).values_list("id", flat=True))

    # 检索
    contexts = []
    try:
        refs = hybrid_search(tenant.id, kb_ids, question, 5)
        contexts = [r.get("content", "")[:500] for r in refs if r.get("content")]
    except Exception as e:
        logger.warning(f"RAG retrieval failed: {e}")

    # 生成答案
    answer = ""
    try:
        context_str = "\n\n".join(contexts[:3]) if contexts else "没有找到相关信息"
        messages = [
            {"role": "system", "content": "你是一个知识库问答助手。根据提供的上下文回答问题。如果上下文没有相关信息，如实说明。"},
            {"role": "user", "content": f"上下文：\n{context_str}\n\n问题：{question}"},
        ]
        answer = chat_completion(tenant, messages, model_id)
    except Exception as e:
        logger.warning(f"RAG generation failed: {e}")
        answer = "生成答案失败"

    return answer, contexts


def _ragas_evaluation(eval_details: list[EvalDetail], tenant, eval_llm_model: str = "") -> EvalResult:
    """
    使用 RAGAs 框架评估。
    """
    from ragas import evaluate
    from ragas.metrics import faithfulness, answer_relevancy, context_precision
    from datasets import Dataset

    # 准备评估数据
    dataset_dict = {
        "question": [d.question for d in eval_details],
        "answer": [d.answer for d in eval_details],
        "contexts": [d.contexts for d in eval_details],
        "ground_truth": [d.ground_truth or d.answer for d in eval_details],  # 如果没有 ground_truth，用 answer 代替
    }

    dataset = Dataset.from_dict(dataset_dict)

    # 配置评估 LLM
    evaluator_llm = None
    try:
        from ragas.llms import LangchainLLMWrapper
        from langchain_openai import ChatOpenAI
        from django.conf import settings

        base_url = settings.LLM_CHAT_BASE_URL
        api_key = settings.LLM_CHAT_API_KEY
        model = eval_llm_model or settings.LLM_CHAT_MODEL

        evaluator_llm = LangchainLLMWrapper(ChatOpenAI(
            model=model,
            temperature=0,
            base_url=base_url,
            api_key=api_key,
        ))
    except Exception as e:
        logger.warning(f"Failed to create evaluator LLM: {e}")

    # 选择指标（根据是否有 ground_truth）
    has_ground_truth = any(d.ground_truth for d in eval_details)
    metrics = [faithfulness, answer_relevancy, context_precision]
    if has_ground_truth:
        from ragas.metrics import context_recall, answer_correctness
        metrics.extend([context_recall, answer_correctness])

    # 运行评估
    result = evaluate(
        dataset=dataset,
        metrics=metrics,
        llm=evaluator_llm,
    )

    # 构建结果
    eval_result = EvalResult(
        faithfulness=result.get("faithfulness", 0.0),
        answer_relevancy=result.get("answer_relevancy", 0.0),
        context_precision=result.get("context_precision", 0.0),
        context_recall=result.get("context_recall", 0.0) if has_ground_truth else 0.0,
        answer_correctness=result.get("answer_correctness", 0.0) if has_ground_truth else 0.0,
    )

    # 详细结果
    for i, detail in enumerate(eval_details):
        detail.faithfulness = result.get("faithfulness", 0.0)
        detail.answer_relevancy = result.get("answer_relevancy", 0.0)
        detail.context_precision = result.get("context_precision", 0.0)
        if has_ground_truth:
            detail.context_recall = result.get("context_recall", 0.0)
            detail.answer_correctness = result.get("answer_correctness", 0.0)
        eval_result.details.append(detail)

    return eval_result


def _simple_evaluation(eval_details: list[EvalDetail]) -> EvalResult:
    """
    简单评估（不依赖 RAGAs）。
    使用中文分词后的关键词匹配。
    """
    total_faithfulness = 0.0
    total_relevancy = 0.0
    total_precision = 0.0
    total_recall = 0.0
    total_correctness = 0.0

    for detail in eval_details:
        question = detail.question
        answer = detail.answer
        contexts = detail.contexts
        ground_truth = detail.ground_truth

        # Faithfulness：答案是否包含上下文中的关键词
        if contexts and answer:
            context_text = " ".join(contexts)
            answer_keywords = _extract_keywords(answer)
            if answer_keywords:
                matched = sum(1 for k in answer_keywords if k in context_text)
                detail.faithfulness = min(1.0, matched / len(answer_keywords))

        # Answer Relevancy：答案是否包含问题关键词
        if question and answer:
            question_keywords = _extract_keywords(question)
            if question_keywords:
                matched = sum(1 for k in question_keywords if k in answer)
                detail.answer_relevancy = min(1.0, matched / len(question_keywords))

        # Context Precision：上下文是否包含问题关键词
        if question and contexts:
            question_keywords = _extract_keywords(question)
            context_text = " ".join(contexts)
            if question_keywords:
                matched = sum(1 for k in question_keywords if k in context_text)
                detail.context_precision = min(1.0, matched / len(question_keywords))

        # Context Recall：ground_truth 是否被上下文覆盖（需要 ground_truth）
        if ground_truth and contexts:
            gt_keywords = _extract_keywords(ground_truth)
            context_text = " ".join(contexts)
            if gt_keywords:
                matched = sum(1 for k in gt_keywords if k in context_text)
                detail.context_recall = min(1.0, matched / len(gt_keywords))

        # Answer Correctness：答案与 ground_truth 的相似度（需要 ground_truth）
        if ground_truth and answer:
            gt_keywords = _extract_keywords(ground_truth)
            if gt_keywords:
                matched = sum(1 for k in gt_keywords if k in answer)
                detail.answer_correctness = min(1.0, matched / len(gt_keywords))

        total_faithfulness += detail.faithfulness
        total_relevancy += detail.answer_relevancy
        total_precision += detail.context_precision
        total_recall += detail.context_recall
        total_correctness += detail.answer_correctness

    n = max(1, len(eval_details))
    return EvalResult(
        faithfulness=total_faithfulness / n,
        answer_relevancy=total_relevancy / n,
        context_precision=total_precision / n,
        context_recall=total_recall / n,
        answer_correctness=total_correctness / n,
        details=eval_details,
    )


def _extract_keywords(text: str) -> list[str]:
    """
    简单的中文关键词提取。
    按标点符号和空格分词，过滤掉太短的词。
    """
    import re
    # 按标点符号和空格分词
    pattern = r"""[，。！？、；："'（）\[\]【】\s]+"""
    words = re.split(pattern, text)
    # 过滤掉太短的词和纯数字
    keywords = [w.strip() for w in words if len(w.strip()) >= 2 and not w.strip().isdigit()]
    return keywords


def get_default_eval_questions() -> list[dict]:
    """获取默认评估问题（示例）"""
    return [
        {
            "question": "什么是 RAG?",
            "ground_truth": "RAG（Retrieval Augmented Generation）是一种结合检索和生成的 AI 框架，通过从知识库中检索相关文档来增强大语言模型的回答质量。",
        },
        {
            "question": "Django 的 ORM 怎么用?",
            "ground_truth": "Django ORM 通过模型定义数据库表，使用 QuerySet API 进行 CRUD 操作，支持迁移管理。",
        },
        {
            "question": "如何优化 RAG 检索效果?",
            "ground_truth": "优化 RAG 的方法包括混合检索、Rerank、查询改写、分块优化、MMR 多样性过滤等。",
        },
    ]
