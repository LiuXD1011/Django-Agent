"""
Agent history reconstruction helpers.

The runtime Agent receives OpenAI-style messages, while persisted history stores
one final assistant message plus serialized agent_steps. These helpers rebuild a
OpenAI-style multi-turn context without requiring each view to duplicate that
translation logic.
"""

import json
import re
from collections import OrderedDict
from typing import Iterable


THINK_TAG_RE = re.compile(r"(?s)<think>.*?</think>")
MAX_HISTORY_TOOL_OUTPUT_CHARS = 1000


def normalize_max_rounds(value, default: int = 5, minimum: int = 1, maximum: int = 20) -> int:
    try:
        rounds = int(value)
    except (TypeError, ValueError):
        rounds = default
    return min(max(rounds, minimum), maximum)


def _message_value(message, field: str, default=None):
    if isinstance(message, dict):
        return message.get(field, default)
    return getattr(message, field, default)


def _strip_think_tags(content: str) -> str:
    return THINK_TAG_RE.sub("", content or "").strip()


def _message_list_value(message, field: str) -> list:
    value = _message_value(message, field, [])
    return value if isinstance(value, list) else []


def _image_descriptions(images: list) -> str:
    parts: list[str] = []
    for image in images:
        if not isinstance(image, dict):
            continue
        text = image.get("caption") or image.get("description") or image.get("text")
        if text:
            parts.append(str(text))
    return "\n".join(parts)


def _attachment_summary(attachments: list) -> str:
    parts: list[str] = []
    for item in attachments:
        if isinstance(item, dict):
            name = item.get("file_name") or item.get("name") or "attachment"
            size = item.get("file_size") or item.get("size")
            parts.append(f"- {name}" + (f" ({size} bytes)" if size else ""))
        elif item:
            parts.append(f"- {item}")
    return "\n".join(parts)


def _build_user_content(message) -> str:
    content = _message_value(message, "rendered_content", "") or _message_value(message, "content", "")
    if not _message_value(message, "rendered_content", ""):
        image_text = _image_descriptions(_message_list_value(message, "images"))
        if image_text:
            content += "\n\n[用户上传图片内容]\n" + image_text
        attachment_text = _attachment_summary(_message_list_value(message, "attachments"))
        if attachment_text:
            content += "\n\n[用户上传附件]\n" + attachment_text
    return content


def _compact_history_tool_output(content: str, limit: int = MAX_HISTORY_TOOL_OUTPUT_CHARS) -> str:
    content = str(content or "")
    if len(content) <= limit:
        return content
    return content[:limit] + "\n[历史工具结果已截断，请按需重新检索]"


def _tool_call_message(tool_call: dict) -> dict:
    call_id = str(tool_call.get("id") or "")
    name = str(tool_call.get("name") or "")
    arguments = tool_call.get("arguments") or {}
    if not isinstance(arguments, str):
        arguments = json.dumps(arguments, ensure_ascii=False)
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": arguments,
        },
    }


def _tool_result_content(result) -> str:
    if isinstance(result, dict):
        if result.get("error"):
            return f"Error: {result.get('error')}"
        return _compact_history_tool_output(str(result.get("output") or ""))
    if result is None:
        return ""
    output = getattr(result, "output", "")
    error = getattr(result, "error", "")
    if error:
        return f"Error: {error}"
    return _compact_history_tool_output(str(output or ""))


def _assistant_tool_messages_from_steps(agent_steps: list[dict] | None) -> list[dict]:
    messages: list[dict] = []
    for step in agent_steps or []:
        tool_calls = step.get("tool_calls") or []
        if not tool_calls:
            continue

        assistant_tool_calls = [_tool_call_message(tool_call) for tool_call in tool_calls]
        messages.append({
            "role": "assistant",
            "content": step.get("thought") or "",
            "tool_calls": assistant_tool_calls,
        })

        for tool_call in tool_calls:
            tool_name = str(tool_call.get("name") or "")
            messages.append({
                "role": "tool",
                "tool_call_id": str(tool_call.get("id") or ""),
                "name": tool_name,
                "content": _tool_result_content(tool_call.get("result")),
            })
    return messages


def _complete_turns(history_messages: Iterable, max_rounds: int) -> list[list]:
    grouped: OrderedDict[str, list] = OrderedDict()
    for message in history_messages:
        request_id = str(_message_value(message, "request_id", ""))
        if not request_id:
            continue
        grouped.setdefault(request_id, []).append(message)

    turns: list[list] = []
    for turn in grouped.values():
        has_user = any(_message_value(m, "role") == "user" for m in turn)
        has_assistant = any(_message_value(m, "role") == "assistant" and _strip_think_tags(_message_value(m, "content", "")) for m in turn)
        if has_user and has_assistant:
            turns.append(turn)
    return turns[-max_rounds:]


def build_agent_history_messages(history_messages: Iterable, max_rounds: int = 5) -> list[dict]:
    """
    Rebuild recent Agent-mode history as OpenAI messages.

    Input can be Django Message objects or lightweight test doubles. Messages are
    grouped by request_id, the newest max_rounds completed turns are retained,
    and user rendered_content is preferred when available.
    """
    result: list[dict] = []
    for turn in _complete_turns(history_messages, max_rounds):
        user_messages = [m for m in turn if _message_value(m, "role") == "user"]
        assistant_messages = [m for m in turn if _message_value(m, "role") == "assistant"]

        for user_msg in user_messages:
            content = _build_user_content(user_msg)
            if content:
                result.append({"role": "user", "content": content})

        for assistant_msg in assistant_messages:
            result.extend(_assistant_tool_messages_from_steps(_message_value(assistant_msg, "agent_steps")))
            content = _strip_think_tags(_message_value(assistant_msg, "content", ""))
            if content:
                result.append({"role": "assistant", "content": content})

    return result


def build_rag_history_messages(history_messages: Iterable, max_rounds: int = 5) -> list[dict]:
    """Rebuild recent non-Agent RAG history as plain user/assistant pairs."""
    result: list[dict] = []
    for turn in _complete_turns(history_messages, max_rounds):
        user_messages = [m for m in turn if _message_value(m, "role") == "user"]
        assistant_messages = [m for m in turn if _message_value(m, "role") == "assistant"]
        if not user_messages or not assistant_messages:
            continue
        user_content = _build_user_content(user_messages[0])
        assistant_content = _strip_think_tags(_message_value(assistant_messages[-1], "content", ""))
        if user_content and assistant_content:
            result.append({"role": "user", "content": user_content})
            result.append({"role": "assistant", "content": assistant_content})
    return result


def build_normal_rag_messages(system_prompt: str, history_messages: list[dict], user_prompt: str) -> list[dict]:
    """Build final non-Agent LLM messages with token-budget history replay."""
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history_messages or [])
    messages.append({"role": "user", "content": user_prompt})
    return messages


def build_agent_context_if_needed(builder, refs: list, memory_context: str, kb_names: str) -> str:
    """Build Agent context whenever retrieval refs, memory, or KB metadata exists."""
    if refs or memory_context or kb_names:
        return builder(refs, memory_context, kb_names)
    return ""
