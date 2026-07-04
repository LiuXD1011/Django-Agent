"""
上下文窗口管理器

参考同类知识库系统的 Consolidator + CompressContext 两层压缩机制：
1. Consolidator：当 token > 50% 上限时，先提取关键信息，再用 LLM 摘要压缩
2. CompressContext：当 token > 80% 上限时，滑动窗口截断

关键优化：
- 压缩前先提取关键信息存入会话记忆，减少信息偏差
- 工具定义按字母排序，确保字节级稳定性（兼容 DeepSeek V4 自动前缀缓存）
- 系统提示分为不可变前缀 + 动态上下文，提高缓存命中率
"""

import json
import logging
import time

logger = logging.getLogger(__name__)

# ── Token 估算（使用 tiktoken cl100k_base BPE 编码）──────────────────
try:
    import tiktoken
    _encoder = tiktoken.get_encoding("cl100k_base")
    _has_tiktoken = True
except ImportError:
    _has_tiktoken = False
    _encoder = None
    logger.warning("tiktoken not installed, falling back to simple estimation")


def estimate_tokens(text: str) -> int:
    """
    估算 token 数。
    优先使用 tiktoken cl100k_base BPE 编码（与 OpenAI 一致），
    回退到简易估算（中文 ~1.5 字/token，英文 ~4 字符/token）。
    """
    if not text:
        return 0

    if _has_tiktoken and _encoder:
        try:
            return len(_encoder.encode(text))
        except Exception:
            pass

    # 回退：简易估算
    chinese_chars = sum(1 for c in text if '一' <= c <= '鿿')
    other_chars = len(text) - chinese_chars
    return int(chinese_chars / 1.5 + other_chars / 4)


def estimate_messages_tokens(messages: list[dict]) -> int:
    """估算消息列表的总 token 数。"""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content)
        # tool_calls 也占用 token
        tool_calls = msg.get("tool_calls")
        if tool_calls:
            total += estimate_tokens(json.dumps(tool_calls, ensure_ascii=False))
    return total


# ── KB 工具结果脱敏 ─────────────────────────────────────────────────
# 参考同类知识库系统的 redactHistoryKBResults
KB_TOOL_NAMES = {
    "knowledge_search", "grep_chunks", "list_knowledge_chunks",
    "query_knowledge_graph", "get_document_info",
    "wiki_search", "wiki_read_page", "wiki_read_source_doc",
}

REDACTED_MARKER = "[Previous retrieval result omitted — knowledge base may have changed. Please perform a fresh search.]"


def _split_system_history_current(messages: list[dict]) -> tuple[dict | None, list[dict], list[dict]]:
    """Split messages into system prompt, historical context, and current user turn."""
    system = messages[0] if messages and messages[0].get("role") == "system" else None
    body_start = 1 if system else 0

    current_round_start = len(messages)
    for i in range(len(messages) - 1, body_start - 1, -1):
        if messages[i].get("role") == "user":
            current_round_start = i
            break

    return system, messages[body_start:current_round_start], messages[current_round_start:]


def _tool_call_name_map(messages: list[dict]) -> dict[str, str]:
    """Map OpenAI tool_call IDs to function names from assistant messages."""
    names: dict[str, str] = {}
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tool_call in msg.get("tool_calls") or []:
            call_id = tool_call.get("id")
            fn = tool_call.get("function") or {}
            name = fn.get("name", "")
            if call_id and name:
                names[call_id] = name
    return names


def redact_kb_results(messages: list[dict]) -> list[dict]:
    """
    脱敏历史消息中的 KB 工具结果。
    参考同类知识库系统的 redactHistoryKBResults：将历史中所有 KB 工具调用的结果替换为脱敏标记。
    """
    system, history, current_round = _split_system_history_current(messages)
    tool_names = _tool_call_name_map(history)

    redacted_history = []
    for msg in history:
        role = msg.get("role", "")
        # 脱敏 tool 角色的消息（工具返回结果）
        if role == "tool":
            tool_name = msg.get("name") or tool_names.get(msg.get("tool_call_id", ""), "")
            if tool_name in KB_TOOL_NAMES:
                msg = {**msg, "content": REDACTED_MARKER}
        redacted_history.append(msg)

    result = []
    if system:
        result.append(system)
    result.extend(redacted_history)
    result.extend(current_round)
    return result


# ── 关键信息提取 ─────────────────────────────────────────────────
# 参考同类知识库系统的 "将每次更改的关键信息存入会话记忆"

EXTRACT_KEY_INFO_PROMPT = """请从以下对话历史中提取关键信息，用于存入会话记忆。

提取规则：
1. 用户的核心问题和意图
2. 工具调用的重要结果（如搜索到的关键文档、重要结论）
3. 已达成的共识或决策
4. 未解决的问题或待处理事项
5. 重要的实体名称、数字、日期等具体信息

要求：
- 使用简洁的要点格式
- 每条信息独立成行
- 不要遗漏重要细节
- 使用中文

对话历史：
{history}

请提取关键信息（每行一条）："""


def _extract_key_info(
    history_text: str,
    llm_caller,
    timeout: int = 30,
) -> list[str]:
    """
    从对话历史中提取关键信息。
    参考同类知识库系统的关键信息提取机制。
    """
    if not llm_caller:
        return []

    try:
        prompt = EXTRACT_KEY_INFO_PROMPT.format(history=history_text[:6000])
        messages = [
            {"role": "system", "content": "你是一个信息提取助手，擅长从对话中提取关键信息。请用中文回复。"},
            {"role": "user", "content": prompt},
        ]

        start_time = time.time()
        result = llm_caller(messages)
        elapsed = time.time() - start_time

        if elapsed > timeout:
            logger.warning(f"[KeyInfo] Extraction exceeded timeout ({elapsed:.1f}s > {timeout}s)")
            return []

        if result:
            # 解析为列表
            lines = [line.strip() for line in result.strip().split("\n") if line.strip()]
            # 过滤掉标题行
            key_info = [line for line in lines if not line.startswith("#") and len(line) > 5]
            return key_info[:20]  # 最多 20 条

    except Exception as e:
        logger.warning(f"[KeyInfo] Extraction failed: {e}")

    return []


# ── Consolidator（LLM 摘要压缩）────────────────────────────────────
# 参考同类知识库系统的 consolidator.go

CONSOLIDATION_THRESHOLD = 0.5  # token 超过 50% 上限时触发
CONTEXT_THRESHOLD = 0.8  # token 超过 80% 上限时触发滑动窗口
MAX_SUMMARIZE_RETRIES = 3  # 最大重试次数
SUMMARIZE_TIMEOUT = 60  # 摘要超时（秒）

SUMMARIZE_PROMPT = """请将以下对话历史压缩为简洁的摘要，保留以下关键信息：
1. 用户的核心问题和意图
2. 工具调用的重要结果（如搜索到的关键信息）
3. 已得出的结论和发现
4. 未解决的问题或待处理的事项

要求：
- 压缩到原文 30% 以内
- 使用中文
- 保持事实准确
- 不要添加原文没有的信息

对话历史：
{history}

请输出压缩后的摘要："""


SUMMARY_TOKEN_RESERVE = 500


def _message_tokens(message: dict) -> int:
    return estimate_tokens(json.dumps(message, ensure_ascii=False))


def _group_history_messages(messages: list[dict]) -> list[list[dict]]:
    """Group assistant tool_calls with their following tool results."""
    groups: list[list[dict]] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        group = [msg]
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            i += 1
            while i < len(messages) and messages[i].get("role") == "tool":
                group.append(messages[i])
                i += 1
            groups.append(group)
            continue
        groups.append(group)
        i += 1
    return groups


def _flatten_groups(groups: list[list[dict]]) -> list[dict]:
    return [message for group in groups for message in group]


def _format_message_for_archive(message: dict) -> str:
    role = message.get("role", "unknown")
    content = message.get("content", "")
    limit = 1000 if role == "tool" else 2000
    if role == "assistant" and message.get("tool_calls"):
        limit = 1000
    parts = [f"[{role}]: {content[:limit]}"]
    if message.get("tool_calls"):
        parts.append("[tool_calls]: " + json.dumps(message.get("tool_calls"), ensure_ascii=False)[:1000])
    return "\n".join(parts)


def _build_history_text(messages: list[dict]) -> str:
    return "\n".join(
        _format_message_for_archive(message)
        for message in messages
        if message.get("content") or message.get("tool_calls")
    )


def _raw_archive(messages: list[dict]) -> str:
    lines = []
    for message in messages:
        role = message.get("role", "unknown")
        content = message.get("content", "")
        if content:
            lines.append(f"[{role}]: {content[:500]}")
        elif message.get("tool_calls"):
            lines.append(f"[{role} tool_calls]: {json.dumps(message.get('tool_calls'), ensure_ascii=False)[:500]}")
    return "\n".join(lines)


def _summary_content_parts(
    key_info_items: list[str],
    summary: str,
    source_message_count: int,
) -> list[str]:
    content_parts: list[str] = []
    if key_info_items:
        content_parts.append("[Key Information - Preserved from earlier messages]")
        content_parts.extend(key_info_items)
        content_parts.append("")
    if summary:
        content_parts.append(f"[Memory Summary - {source_message_count} earlier messages consolidated]")
        content_parts.append(summary)
    return content_parts


def build_persistent_summary_payload(
    messages: list[dict],
    llm_caller=None,
    extract_key_info: bool = True,
) -> dict:
    """
    Build a reusable summary payload for persistent context snapshots.

    This shares the same archive/key-info/summarize logic as the runtime
    Consolidator, but returns structured fields so callers can store them.
    """
    history_text = _build_history_text(messages)
    key_info_items: list[str] = []
    if extract_key_info and llm_caller:
        key_info_items = _extract_key_info(history_text, llm_caller)

    summary = ""
    if llm_caller:
        summary = _summarize_with_retry(history_text, llm_caller)
    if not summary:
        summary = _raw_archive(messages)

    content = "\n".join(_summary_content_parts(key_info_items, summary, len(messages)))
    token_before = estimate_messages_tokens(messages)
    token_after = estimate_tokens(content)
    return {
        "content": content,
        "key_info": key_info_items,
        "summary": summary,
        "token_before": token_before,
        "token_after": token_after,
        "source_message_count": len(messages),
    }


def _split_history_by_token_budget(
    history: list[dict],
    system: dict | None,
    current_round: list[dict],
    max_tokens: int,
) -> tuple[list[dict], list[dict]]:
    """Use token budget to choose recent history to keep."""
    target_tokens = int(max_tokens * CONSOLIDATION_THRESHOLD * 0.6)
    budget = target_tokens
    if system:
        budget -= _message_tokens(system)
    budget -= estimate_messages_tokens(current_round)
    budget -= SUMMARY_TOKEN_RESERVE

    if budget <= 0:
        return history, []

    groups = _group_history_messages(history)
    kept_reversed: list[list[dict]] = []
    used = 0
    for group in reversed(groups):
        group_tokens = estimate_messages_tokens(group)
        if kept_reversed and used + group_tokens > budget:
            break
        if not kept_reversed and group_tokens > budget:
            break
        kept_reversed.append(group)
        used += group_tokens

    keep_count = len(kept_reversed)
    if keep_count == 0:
        return history, []

    retain_groups = list(reversed(kept_reversed))
    compress_groups = groups[:len(groups) - keep_count]
    return _flatten_groups(compress_groups), _flatten_groups(retain_groups)


def _summarize_with_retry(
    history_text: str,
    llm_caller,
    max_retries: int = MAX_SUMMARIZE_RETRIES,
    timeout: int = SUMMARIZE_TIMEOUT,
) -> str:
    """
    调用 LLM 生成摘要，支持重试。
    参考同类知识库系统的 summarizeWithRetry。
    """
    prompt = SUMMARIZE_PROMPT.format(history=history_text[:8000])
    messages = [
        {"role": "system", "content": "你是一个对话摘要助手，擅长提取关键信息。请用中文回复。"},
        {"role": "user", "content": prompt},
    ]

    last_error = None
    for attempt in range(max_retries):
        try:
            start_time = time.time()
            result = llm_caller(messages)
            elapsed = time.time() - start_time

            if elapsed > timeout:
                logger.warning(f"[Consolidator] Summarize attempt {attempt + 1} exceeded timeout ({elapsed:.1f}s > {timeout}s)")
                continue

            if result and len(result.strip()) > 10:
                return result.strip()

        except Exception as e:
            last_error = e
            logger.warning(f"[Consolidator] Summarize attempt {attempt + 1} failed: {e}")

        # 重试前等待
        if attempt < max_retries - 1:
            time.sleep(1)

    logger.error(f"[Consolidator] All {max_retries} summarize attempts failed. Last error: {last_error}")
    return ""


def consolidate_messages(
    messages: list[dict],
    max_tokens: int,
    llm_caller=None,
    extract_key_info: bool = True,
) -> list[dict]:
    """
    Consolidator：用 LLM 摘要压缩历史消息。
    参考同类知识库系统的 Consolidator.Consolidate 方法。

    关键优化：压缩前先提取关键信息，减少信息偏差。

    Args:
        messages: 消息列表
        max_tokens: 最大 token 上限
        llm_caller: LLM 调用函数 (messages: list[dict]) -> str
        extract_key_info: 是否在压缩前提取关键信息

    Returns:
        压缩后的消息列表
    """
    current_tokens = estimate_messages_tokens(messages)
    threshold = int(max_tokens * CONSOLIDATION_THRESHOLD)

    if current_tokens <= threshold:
        return messages

    logger.info(f"[Consolidator] Token count {current_tokens} exceeds threshold {threshold}, compressing...")

    system, history, current_round = _split_system_history_current(messages)

    if not history:
        return messages

    # 根据 token 预算从历史尾部保留近期消息，而不是按消息数量比例。
    to_compress, to_retain = _split_history_by_token_budget(history, system, current_round, max_tokens)

    if not to_compress:
        # 没有可压缩的消息，回退到滑动窗口
        return _sliding_window_compress(messages, max_tokens)

    history_text = _build_history_text(to_compress)

    # Step 1: 提取关键信息（参考同类知识库系统的 "先提取关键信息再压缩"）
    key_info_items = []
    if extract_key_info and llm_caller:
        key_info_items = _extract_key_info(history_text, llm_caller)
        if key_info_items:
            logger.info(f"[Consolidator] Extracted {len(key_info_items)} key info items")

    # Step 2: 调用 LLM 生成摘要（带重试）
    summary = ""
    if llm_caller:
        summary = _summarize_with_retry(history_text, llm_caller)

    if not summary:
        logger.warning("[Consolidator] Summarization failed, using raw archive fallback")
        summary = _raw_archive(to_compress)

    if not summary and not key_info_items:
        return _sliding_window_compress(messages, max_tokens)

    # Step 3: 组装压缩后的消息列表
    # 关键信息单独保存，不受压缩影响
    content_parts = _summary_content_parts(key_info_items, summary, len(to_compress))

    summary_msg = {
        "role": "system",
        "content": "\n".join(content_parts),
    }

    result = []
    if system:
        result.append(system)
    result.append(summary_msg)
    result.extend(to_retain)
    result.extend(current_round)

    new_tokens = estimate_messages_tokens(result)
    logger.info(f"[Consolidator] Compressed from {current_tokens} to {new_tokens} tokens")

    return result


def _sliding_window_compress(messages: list[dict], max_tokens: int) -> list[dict]:
    """
    滑动窗口截断（第二层压缩）。
    参考同类知识库系统的 CompressContext。
    """
    current_tokens = estimate_messages_tokens(messages)
    target_tokens = int(max_tokens * CONTEXT_THRESHOLD)
    if current_tokens <= target_tokens:
        return messages

    system, history, current_round = _split_system_history_current(messages)
    groups = _group_history_messages(history)

    while current_tokens > target_tokens and groups:
        removed_group = groups.pop(0)
        current_tokens -= estimate_messages_tokens(removed_group)

    result = []
    if system:
        result.append(system)
    result.extend(_flatten_groups(groups))
    result.extend(current_round)
    return result


# ── 工具定义排序（字节级稳定性）────────────────────────────────────
# 参考同类知识库系统的 GetFunctionDefinitions 排序逻辑
# DeepSeek V4 自动前缀缓存要求字节级前缀匹配

def sort_tools_for_cache(tools: list[dict]) -> list[dict]:
    """
    按工具名字母排序，确保序列化后的字节序列一致。
    参考同类知识库系统：Providers that key prompt caching on a byte-level prefix match require this.
    """
    if not tools:
        return tools
    return sorted(tools, key=lambda t: t.get("function", {}).get("name", ""))


# ── 统一入口 ─────────────────────────────────────────────────────
def manage_context_window(
    messages: list[dict],
    max_tokens: int = 120000,
    llm_caller=None,
    enable_redact: bool = True,
    enable_key_info: bool = True,
) -> list[dict]:
    """
    统一的上下文窗口管理入口。
    参考同类知识库系统的 manageContextWindow。

    流程：
    1. 脱敏历史 KB 工具结果（可选）
    2. 如果 token > 50% 上限，用 Consolidator 压缩（含关键信息提取）
    3. 如果 token > 80% 上限，用滑动窗口截断

    Args:
        messages: 消息列表
        max_tokens: 最大 token 上限
        llm_caller: LLM 调用函数
        enable_redact: 是否脱敏历史 KB 结果
        enable_key_info: 是否在压缩前提取关键信息

    Returns:
        压缩后的消息列表
    """
    # Step 1: 脱敏历史 KB 结果
    if enable_redact:
        messages = redact_kb_results(messages)

    current_tokens = estimate_messages_tokens(messages)

    # Step 2: Consolidator（LLM 摘要压缩 + 关键信息提取）
    consolidation_threshold = int(max_tokens * CONSOLIDATION_THRESHOLD)
    if current_tokens > consolidation_threshold and llm_caller:
        messages = consolidate_messages(
            messages, max_tokens, llm_caller,
            extract_key_info=enable_key_info,
        )
        current_tokens = estimate_messages_tokens(messages)

    # Step 3: 滑动窗口截断
    context_threshold = int(max_tokens * CONTEXT_THRESHOLD)
    if current_tokens > context_threshold:
        messages = _sliding_window_compress(messages, max_tokens)

    return messages
