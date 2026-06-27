"""
查询理解模块（Query Understanding）

参考 WeKnora 的 query_understand.go，在单次 LLM 调用中完成：
1. 查询改写（指代消解、补全省略信息、保留检索关键词）
2. 意图识别（9 种意图，非检索意图跳过搜索）
"""

import json
import logging
import re

logger = logging.getLogger(__name__)

# ── 意图定义 ─────────────────────────────────────────────────────────
INTENT_GREETING = "greeting"
INTENT_KB_SEARCH = "kb_search"
INTENT_WEB_SEARCH = "web_search"
INTENT_FOLLOW_UP = "follow_up"
INTENT_CHITCHAT = "chitchat"
INTENT_CLARIFICATION = "clarification"
INTENT_SUMMARIZE = "summarize"
INTENT_IMAGE_ONLY = "image_only"
INTENT_DOC_ONLY = "doc_only"

# 不需要检索的意图
NON_RETRIEVAL_INTENTS = {INTENT_GREETING, INTENT_CHITCHAT, INTENT_FOLLOW_UP, INTENT_CLARIFICATION, INTENT_SUMMARIZE}


# ── 改写 + 意图识别 Prompt ──────────────────────────────────────────
UNDERSTAND_PROMPT = """你是一个查询理解助手。你需要完成以下三个任务：

## 任务一：查询改写
对用户问题进行改写，要求：
- 消解指代（将"它"、"这个"、"那个"、"他们"等替换为明确的主语）
- 补全省略的关键信息
- 保留原始含义和风格
- 结果必须是一个完整的问题，不超过 30 个字
- **必须保留原文中的实体、关键词和核心检索词**
- 如果是概括性的访问请求（如"整理一下知识库资料"），保持原始关键描述

## 任务二：意图识别
按以下优先级从上到下判断意图，第一个匹配即返回：

1. `greeting` — 纯粹的问候、感谢、告别
2. `summarize` — 要求总结对话本身（不是知识库内容）
3. `web_search` — 需要实时/外部信息，知识库中不太可能有
4. `kb_search` — 搜索/查找/查询/阅读/浏览/整理/列出/提取知识库内容；即使附带图片/文档也适用
5. `clarification` — 问题模糊、不完整，需要澄清
6. `follow_up` — 引用前文对话，仅靠历史即可回答
7. `image_only` — 仅分析附带图片
8. `doc_only` — 仅分析附带文档
9. `chitchat` — 闲聊

不确定时默认返回 `kb_search`。

## 任务三：图片分析
如果提供了图片描述，给出图片内容的简要描述。

## 输出格式
严格输出 JSON，不要添加 markdown 标记：
{{"rewrite_query": "改写后的问题", "intent": "意图", "image_description": "图片描述或空字符串"}}

## 用户问题
{query}
"""


def understand_query(tenant, query: str, history: list[dict] | None = None, has_images: bool = False) -> dict:
    """
    分析用户查询，返回：
    {
        "rewrite_query": str,  # 改写后的查询
        "intent": str,         # 意图
        "image_description": str,  # 图片描述
    }
    """
    from .model_providers import role_completion

    prompt = UNDERSTAND_PROMPT.format(query=query)

    try:
        raw = role_completion("question", prompt, query, max_chars=500)
        result = _parse_understand_response(raw)
        # 验证意图
        valid_intents = {
            INTENT_GREETING, INTENT_KB_SEARCH, INTENT_WEB_SEARCH, INTENT_FOLLOW_UP,
            INTENT_CHITCHAT, INTENT_CLARIFICATION, INTENT_SUMMARIZE,
            INTENT_IMAGE_ONLY, INTENT_DOC_ONLY,
        }
        if result.get("intent") not in valid_intents:
            result["intent"] = INTENT_KB_SEARCH
        if not result.get("rewrite_query"):
            result["rewrite_query"] = query
        return result
    except Exception:
        logger.exception("Query understanding failed")
        return {"rewrite_query": query, "intent": INTENT_KB_SEARCH, "image_description": ""}


def _parse_understand_response(raw: str) -> dict:
    """解析 LLM 返回的 JSON，支持多种字段名别名。"""
    raw = (raw or "").strip()
    if not raw:
        return {}

    # 尝试直接解析
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # 尝试提取第一个 JSON 块
    match = re.search(r"\{[\s\S]*?\}", raw)
    if match:
        try:
            data = json.loads(match.group())
            # 字段别名映射
            result = {}
            result["rewrite_query"] = (
                data.get("rewrite_query")
                or data.get("rewritten_query")
                or data.get("query")
                or data.get("question")
                or ""
            )
            result["intent"] = data.get("intent") or INTENT_KB_SEARCH
            result["image_description"] = (
                data.get("image_description")
                or data.get("image_desc")
                or data.get("image_text")
                or data.get("description")
                or ""
            )
            # 合并 OCR 文本
            ocr = data.get("ocr_text") or data.get("ocr") or ""
            if ocr and ocr not in result["image_description"]:
                if result["image_description"]:
                    result["image_description"] += "\n\n[OCR]\n" + ocr
                else:
                    result["image_description"] = ocr
            return result
        except json.JSONDecodeError:
            pass

    return {}


def needs_retrieval(intent: str) -> bool:
    """判断该意图是否需要知识库检索。"""
    return intent not in NON_RETRIEVAL_INTENTS


# ── 意图特定的 System Prompt 覆盖 ────────────────────────────────────
INTENT_SYSTEM_PROMPTS = {
    INTENT_GREETING: "你是一个友好的 AI 助手。用户正在向你打招呼，请简洁友好地回应。",
    INTENT_CHITCHAT: "你是一个友好的 AI 助手。用户在和你闲聊，请自然友好地回应。",
    INTENT_CLARIFICATION: "你是一个有帮助的 AI 助手。用户的问题不够明确，请礼貌地请求更多信息。",
    INTENT_SUMMARIZE: "你是一个善于总结的 AI 助手。请根据之前的对话内容进行总结。",
}


def get_intent_system_prompt(intent: str) -> str | None:
    """获取意图特定的 system prompt 覆盖。"""
    return INTENT_SYSTEM_PROMPTS.get(intent)
