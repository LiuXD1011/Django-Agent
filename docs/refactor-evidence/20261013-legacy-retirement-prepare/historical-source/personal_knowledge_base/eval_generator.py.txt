"""
评估问题自动生成模块

从知识库文档中自动生成评估问题和 Ground Truth。
参考 RAGAs 的 TestsetGenerator 设计。

生成流程：
1. 从知识库中随机采样文档 chunks
2. 使用 LLM 从 chunks 中生成问题和答案
3. 返回结构化的评估问题列表
"""

import json
import logging
import random
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class GeneratedQuestion:
    """生成的评估问题"""
    question: str
    ground_truth: str
    source_chunk: str = ""
    question_type: str = "simple"  # simple, reasoning, multi-context


# 问题生成 Prompt
GENERATE_QUESTION_PROMPT = """你是一个评估数据集生成专家。根据以下文档内容，生成一个高质量的问答对。

文档内容：
{chunk_content}

要求：
1. 问题应该是基于文档内容的，不能脱离文档
2. 问题应该有明确的答案，答案必须在文档中
3. 问题类型：{question_type}
4. 答案应该准确、完整、简洁

请输出 JSON 格式：
{{
  "question": "生成的问题",
  "answer": "标准答案（Ground Truth）"
}}

注意：只输出 JSON，不要有其他内容。"""


# 问题类型说明
QUESTION_TYPES = {
    "simple": "简单事实问题，答案直接在文档中",
    "reasoning": "需要推理的问题，需要综合文档中的多个信息",
    "multi-context": "需要多个段落才能回答的问题",
}


def generate_eval_questions(
    tenant,
    num_questions: int = 10,
    question_types: list[str] = None,
) -> list[dict]:
    """
    从知识库自动生成评估问题。

    Args:
        tenant: 租户对象
        num_questions: 要生成的问题数量
        question_types: 问题类型列表，默认为 ["simple", "reasoning"]

    Returns:
        生成的评估问题列表
    """
    from .models import Chunk, KnowledgeBase
    from .model_providers import chat_completion

    if question_types is None:
        question_types = ["simple", "reasoning"]

    # 获取知识库
    kb_ids = list(KnowledgeBase.objects.filter(
        tenant=tenant, deleted_at__isnull=True
    ).values_list("id", flat=True))

    if not kb_ids:
        logger.warning("No knowledge bases found")
        return []

    # 获取 chunks
    chunks = list(Chunk.objects.filter(
        knowledge_base_id__in=kb_ids,
        is_enabled=True,
        deleted_at__isnull=True,
    ).values_list("id", "content")[:200])  # 限制采样范围

    if not chunks:
        logger.warning("No chunks found")
        return []

    # 随机采样
    sample_size = min(num_questions * 2, len(chunks))
    sampled_chunks = random.sample(chunks, sample_size)

    # 生成问题
    generated = []
    for chunk_id, content in sampled_chunks:
        if len(generated) >= num_questions:
            break

        if not content or len(content) < 50:
            continue

        # 截断内容
        chunk_content = content[:1500]

        # 随机选择问题类型
        q_type = random.choice(question_types)

        # 调用 LLM 生成问题
        try:
            prompt = GENERATE_QUESTION_PROMPT.format(
                chunk_content=chunk_content,
                question_type=QUESTION_TYPES.get(q_type, "简单事实问题"),
            )
            messages = [
                {"role": "system", "content": "你是一个评估数据集生成专家。请用中文生成问题和答案。只输出 JSON。"},
                {"role": "user", "content": prompt},
            ]
            result = chat_completion(tenant, messages)

            # 解析 JSON
            parsed = _parse_json_response(result)
            if parsed and parsed.get("question") and parsed.get("answer"):
                generated.append({
                    "question": parsed["question"],
                    "ground_truth": parsed["answer"],
                    "source_chunk": chunk_content[:200],
                    "question_type": q_type,
                })
                logger.info(f"Generated question: {parsed['question'][:50]}...")

        except Exception as e:
            logger.warning(f"Failed to generate question from chunk {chunk_id}: {e}")
            continue

    return generated


def _parse_json_response(text: str) -> dict | None:
    """解析 LLM 返回的 JSON"""
    try:
        # 尝试直接解析
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 尝试提取 JSON 块
    import re
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None


def generate_and_save_eval_questions(
    tenant,
    num_questions: int = 10,
    question_types: list[str] = None,
) -> list[dict]:
    """
    生成评估问题并保存到数据库。

    Args:
        tenant: 租户对象
        num_questions: 要生成的问题数量
        question_types: 问题类型列表

    Returns:
        生成的评估问题列表
    """
    from .models import GenericResource

    # 生成问题
    questions = generate_eval_questions(tenant, num_questions, question_types)

    if not questions:
        return []

    # 保存到数据库
    resource, created = GenericResource.objects.get_or_create(
        tenant=tenant,
        resource_type="rag_eval_questions",
        defaults={"data": {"questions": []}},
    )

    existing_questions = resource.data.get("questions", [])
    existing_questions.extend(questions)
    resource.data = {"questions": existing_questions}
    resource.save(update_fields=["data", "updated_at"])

    logger.info(f"Saved {len(questions)} generated questions, total: {len(existing_questions)}")

    return questions
