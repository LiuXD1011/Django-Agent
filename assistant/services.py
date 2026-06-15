import json
import re
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.utils import timezone
from openai import OpenAI

from drive.models import UserFile

from .models import ChatMessage, Conversation


ASSISTANT_AGENT_TYPE = ChatMessage.AGENT_ASSISTANT
ASSISTANT_LABEL = "AI助手"
WEEKDAYS_ZH = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
DATE_TIME_QUERY_RE = re.compile(r"(今天|现在|当前|此刻|日期|星期|周几|礼拜几|几点|时间)")
DRIVE_FULL_LIST_LIMIT = 100
DRIVE_RECENT_LIMIT = 8
DRIVE_MATCH_LIMIT = 20
TEMP_FILE_CONTEXT_MAX_FILES = 3
TEMP_FILE_CONTEXT_CHAR_LIMIT = 12000
TEMP_FILE_CONTEXT_PER_FILE_LIMIT = 4000


def active_conversations(user):
    return Conversation.objects.filter(user=user, status=Conversation.STATUS_ACTIVE).select_related("default_kb")


def adopt_orphan_messages(user):
    orphan_messages = ChatMessage.objects.filter(user=user, conversation__isnull=True, agent_type=ASSISTANT_AGENT_TYPE)
    if not orphan_messages.exists():
        return None
    conversation = Conversation.objects.create(user=user, title="历史对话")
    orphan_messages.update(conversation=conversation)
    return conversation


def get_or_create_conversation(user, conversation_id=None, defaults=None, adopt_legacy=True):
    defaults = defaults or {}
    if conversation_id:
        conversation = active_conversations(user).filter(id=conversation_id).first()
        if conversation:
            return conversation, False
    legacy = adopt_orphan_messages(user) if adopt_legacy else None
    if legacy:
        return legacy, True
    conversation = Conversation.objects.create(user=user, **defaults)
    return conversation, True


def save_message(user, role, content, conversation, metadata=None):
    if conversation is None:
        raise ValueError("conversation is required when saving assistant messages.")
    return ChatMessage.objects.create(
        user=user,
        conversation=conversation,
        agent_type=ASSISTANT_AGENT_TYPE,
        role=role,
        content=content,
        metadata=metadata or {},
    )


def history(user, conversation=None, limit=30):
    if conversation is None:
        return []
    qs = ChatMessage.objects.filter(
        user=user,
        conversation=conversation,
        agent_type=ASSISTANT_AGENT_TYPE,
    ).order_by("-created_at")[:limit]
    return list(reversed(qs))


def _fallback_tokens(text):
    for ch in text:
        yield ch


def current_datetime_context(now=None):
    current = timezone.localtime(now or timezone.now())
    return {
        "date": current.strftime("%Y-%m-%d"),
        "time": current.strftime("%H:%M:%S"),
        "weekday": WEEKDAYS_ZH[current.weekday()],
        "timezone": settings.TIME_ZONE,
    }


def assistant_environment_prompt(now=None):
    info = current_datetime_context(now)
    return "\n".join(
        [
            "以下是当前运行环境信息：",
            "<env>",
            f"当前日期: {info['date']}",
            f"当前星期: {info['weekday']}",
            f"当前时间: {info['time']}",
            f"当前时区: {info['timezone']}",
            "</env>",
            "当用户询问今天、当前日期、星期或时间时，优先使用上述环境信息回答；不要声称无法获取当前日期或时间。",
        ]
    )


def system_prompt_with_environment(system):
    return "\n\n".join([system or "你是一个专业、简洁的中文助手。", assistant_environment_prompt()])


def local_datetime_answer(prompt):
    text = prompt or ""
    if not DATE_TIME_QUERY_RE.search(text):
        return ""
    info = current_datetime_context()
    if any(word in text for word in ["几点", "时间", "现在", "当前", "此刻"]):
        return f"现在是 {info['date']} {info['time']}（{info['timezone']}），{info['weekday']}。"
    return f"今天是 {info['date']}，{info['weekday']}。"


def _event_delta_text(event):
    choices = getattr(event, "choices", None) or []
    if not choices:
        return ""
    delta = getattr(choices[0], "delta", None)
    content = getattr(delta, "content", "") if delta else ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(item.get("text") or item.get("content") or "")
            else:
                parts.append(getattr(item, "text", "") or getattr(item, "content", "") or "")
        return "".join(parts)
    return ""


def llm_tokens(prompt, system="你是一个专业、简洁的中文助手。"):
    if not settings.LLM_API_KEY:
        local_answer = local_datetime_answer(prompt)
        if local_answer:
            yield from _fallback_tokens(local_answer)
            return
        yield from _fallback_tokens("未配置 LLM_API_KEY，AI 服务暂不可用。文件管理功能不受影响。")
        return

    try:
        client = OpenAI(api_key=settings.LLM_API_KEY, base_url=settings.LLM_BASE_URL)
        stream = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt_with_environment(system)},
                {"role": "user", "content": prompt},
            ],
            stream=True,
            temperature=0.2,
        )
        for event in stream:
            delta = _event_delta_text(event)
            if delta:
                yield delta
    except Exception as exc:
        yield from _fallback_tokens(f"模型调用失败：{exc}")


def file_info_answer(user, query):
    q = (query or "").strip().lower()
    files = UserFile.objects.filter(user=user, is_deleted=False, is_folder=False)
    folders = UserFile.objects.filter(user=user, is_deleted=False, is_folder=True)
    file_count = files.count()
    if _is_file_list_query(q):
        return _format_file_list(files, file_count, title="当前文件")
    if any(word in q for word in ["容量", "空间", "大小", "占用"]):
        quota = user.storage_quota
        return f"当前已使用 {format_size(quota.used_size)}，总容量 {format_size(quota.total_size)}，使用率 {quota.used_percent}%。"
    if any(word in q for word in ["多少", "几个", "数量", "总数"]):
        return f"共有 {file_count} 个文件、{folders.count()} 个文件夹。"
    if any(word in q for word in ["最近", "最新"]):
        recent = files.order_by("-created_at")[:DRIVE_RECENT_LIMIT]
        if not recent:
            return "当前没有文件。"
        lines = ["最近文件："]
        lines += [f"- {item.name}（{format_size(item.file_size)}）" for item in recent]
        return "\n".join(lines)
    if any(word in q for word in ["统计", "类型"]):
        by_suffix = {}
        for item in files:
            key = item.suffix or "unknown"
            by_suffix[key] = by_suffix.get(key, 0) + 1
        detail = "，".join([f"{k}: {v}" for k, v in sorted(by_suffix.items())]) or "暂无文件"
        return f"共有 {file_count} 个文件、{folders.count()} 个文件夹。类型统计：{detail}。"
    matches = files.filter(name__icontains=query.strip())[:DRIVE_MATCH_LIMIT] if query.strip() else []
    if matches:
        return "找到这些文件：\n" + "\n".join([f"- {item.name}（{format_size(item.file_size)}）" for item in matches])
    return "可以询问容量、最近文件、文件统计，或直接输入文件名搜索。"


def drive_context(user, query):
    q = (query or "").strip()
    files = UserFile.objects.filter(user=user, is_deleted=False, is_folder=False)
    folders = UserFile.objects.filter(user=user, is_deleted=False, is_folder=True)
    file_count = files.count()
    quota = user.storage_quota
    by_suffix = {}
    for item in files:
        key = item.suffix or "unknown"
        by_suffix[key] = by_suffix.get(key, 0) + 1
    recent = files.order_by("-created_at")[:DRIVE_RECENT_LIMIT]
    matches = files.filter(name__icontains=q)[:DRIVE_MATCH_LIMIT] if q else []
    lines = [
        f"容量：已使用 {format_size(quota.used_size)}，总容量 {format_size(quota.total_size)}，使用率 {quota.used_percent}%。",
        f"数量：{file_count} 个文件，{folders.count()} 个文件夹。",
    ]
    if by_suffix:
        lines.append("类型统计：" + "，".join([f"{k}: {v}" for k, v in sorted(by_suffix.items())]) + "。")
    if file_count:
        lines.append(_format_file_list(files, file_count, title="文件清单"))
    if recent:
        lines.append("最近文件：")
        lines.extend([f"- {item.name}（{format_size(item.file_size)}）" for item in recent])
    if matches:
        lines.append("文件名匹配：")
        lines.extend([f"- {item.name}（{format_size(item.file_size)}）" for item in matches])
    return "\n".join(lines)


def _is_file_list_query(query):
    return bool(re.search(r"(哪|哪些|哪几|列出|清单|列表|所有|全部|文件名)", query or ""))


def _format_file_list(files, file_count, title="文件清单"):
    if not file_count:
        return "当前没有文件。"
    limit = min(file_count, DRIVE_FULL_LIST_LIMIT)
    items = files.order_by("name", "id")[:limit]
    if file_count <= DRIVE_FULL_LIST_LIMIT:
        header = f"{title}（共 {file_count} 个，已全部列出）："
    else:
        header = f"{title}（共 {file_count} 个，以下列出前 {DRIVE_FULL_LIST_LIMIT} 个）："
    lines = [header]
    lines.extend(
        [
            f"{index}. {item.name}（{format_size(item.file_size)}，{item.suffix or 'unknown'}）"
            for index, item in enumerate(items, start=1)
        ]
    )
    if file_count > DRIVE_FULL_LIST_LIMIT:
        lines.append(f"还有 {file_count - DRIVE_FULL_LIST_LIMIT} 个文件未在本次上下文中展开。")
    return "\n".join(lines)


def _file_lookup_text(text):
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _strip_leading_index(text):
    return re.sub(r"^\s*\d+[\s._-]+", "", text or "").strip()


def _file_match_variants(name):
    full = _file_lookup_text(name)
    stem = _file_lookup_text(Path(name or "").stem)
    variants = {full, stem, _file_lookup_text(_strip_leading_index(full)), _file_lookup_text(_strip_leading_index(stem))}
    for variant in list(variants):
        for separator in (" - ", " — ", " – ", "：", ":"):
            if separator in variant:
                variants.update(_file_lookup_text(part) for part in variant.split(separator) if part.strip())
    return [item for item in variants if item]


def mentioned_files(user, query, max_files=TEMP_FILE_CONTEXT_MAX_FILES):
    query_text = _file_lookup_text(query)
    if len(query_text) < 4:
        return [], False
    matches = []
    files = (
        UserFile.objects.filter(user=user, is_deleted=False, is_folder=False)
        .select_related("stored_file")
        .order_by("name", "id")
    )
    for item in files:
        for variant in _file_match_variants(item.name):
            if len(variant) < 4:
                continue
            explicit_full = variant in query_text
            explicit_partial = len(query_text) >= 8 and query_text in variant
            if explicit_full or explicit_partial:
                matches.append(item)
                break
        if len(matches) > max_files:
            return matches[: max_files + 1], True
    return matches, False


def temporary_file_content_context(user, query):
    files, too_many = mentioned_files(user, query)
    if not files:
        return "", {"matched_files": [], "too_many": False, "parsed_files": [], "failed_files": []}
    if too_many:
        names = "，".join(item.name for item in files[:TEMP_FILE_CONTEXT_MAX_FILES])
        return (
            f"命中文件超过 {TEMP_FILE_CONTEXT_MAX_FILES} 个，请在问题中写更完整的文件名后再试。"
            f"当前部分命中：{names}",
            {
                "matched_files": [{"id": item.id, "name": item.name} for item in files],
                "too_many": True,
                "parsed_files": [],
                "failed_files": [],
            },
        )

    from knowledge import services as kb_services

    pieces = []
    parsed_files = []
    failed_files = []
    remaining = TEMP_FILE_CONTEXT_CHAR_LIMIT
    for item in files:
        if remaining <= 0:
            break
        try:
            result = kb_services.parse_user_file_result(item)
            chunks = kb_services.split_text(result.normalized_text, chunk_size=900, overlap=80)[:4]
            content = "\n\n".join(f"[片段 {index}] {chunk}" for index, chunk in enumerate(chunks, start=1))
            content = content[: min(TEMP_FILE_CONTEXT_PER_FILE_LIMIT, remaining)]
            piece = "\n".join(
                [
                    f"### {item.name}",
                    f"解析方式：{result.parser_name or result.method or 'unknown'}",
                    f"文件类型：{result.profile.family or item.suffix or 'unknown'}",
                    "内容片段：",
                    content or "未解析出可用文本。",
                ]
            )
            parsed_files.append(
                {
                    "id": item.id,
                    "name": item.name,
                    "parser": result.parser_name,
                    "method": result.method,
                    "family": result.profile.family,
                }
            )
        except Exception as exc:
            failure_code = getattr(exc, "failure_code", "")
            piece = "\n".join(
                [
                    f"### {item.name}",
                    "解析失败。",
                    f"failure_code：{failure_code or 'unknown'}",
                    f"原因：{exc}",
                ]
            )
            failed_files.append({"id": item.id, "name": item.name, "failure_code": failure_code, "error": str(exc)})
        pieces.append(piece)
        remaining -= len(piece)

    return "\n\n".join(pieces)[:TEMP_FILE_CONTEXT_CHAR_LIMIT], {
        "matched_files": [{"id": item.id, "name": item.name} for item in files],
        "too_many": False,
        "parsed_files": parsed_files,
        "failed_files": failed_files,
    }


def format_size(size):
    value = float(size or 0)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1024 or unit == "TB":
            return f"{value:.1f}{unit}" if unit != "B" else f"{int(value)}B"
        value /= 1024


def assistant_prompt(
    query,
    drive_context_text="",
    references_text="",
    file_content_context_text="",
    checkpoint_text="",
    memory_context_text="",
    recent_context_text="",
):
    sections = []
    if checkpoint_text:
        sections.append(f"当前对话 checkpoint：\n{checkpoint_text}")
    if memory_context_text:
        sections.append(f"长期记忆：\n{memory_context_text}")
    if drive_context_text:
        sections.append(f"文件信息：\n{drive_context_text}")
    if file_content_context_text:
        sections.append(f"文件库临时解析内容：\n{file_content_context_text}")
    if references_text:
        sections.append(f"知识库 references：\n{references_text}")
    if recent_context_text:
        sections.append(f"最近对话：\n{recent_context_text}")
    sections.append(f"用户问题：{query}")
    sections.append("请基于可用信息回答；如果资料不足，请明确说明不足。")
    return "\n\n".join(sections)


def sse(event):
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def timestamp():
    return datetime.now().isoformat(timespec="seconds")
