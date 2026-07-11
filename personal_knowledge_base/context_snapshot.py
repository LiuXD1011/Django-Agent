import logging
import threading
from typing import Callable, Iterable

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from .agent_history import normalize_max_rounds
from .context_manager import (
    CONSOLIDATION_THRESHOLD,
    build_persistent_summary_payload,
    estimate_messages_tokens,
)
from .models import ContextSnapshot, Message, Session

logger = logging.getLogger(__name__)


HistoryBuilder = Callable[[Iterable[Message], int], list[dict]]


def _active_snapshot(session: Session, mode: str) -> ContextSnapshot | None:
    return (
        ContextSnapshot.objects.filter(session=session, mode=mode, is_active=True)
        .order_by("-updated_at", "-created_at")
        .first()
    )


def _messages_after_snapshot(session: Session, snapshot: ContextSnapshot | None, current_user_message=None) -> QuerySet[Message]:
    qs = Message.objects.filter(session=session, is_completed=True, visible_to_user=True)
    current_id = getattr(current_user_message, "id", None)
    if current_id:
        qs = qs.exclude(id=current_id)
    if snapshot and snapshot.boundary_created_at:
        qs = qs.filter(created_at__gte=snapshot.boundary_created_at)
    return qs.order_by("created_at", "id")


def _snapshot_message(snapshot: ContextSnapshot) -> dict:
    return {
        "role": "system",
        "content": snapshot.content,
        "metadata": {
            "type": "context_snapshot",
            "snapshot_id": snapshot.id,
            "mode": snapshot.mode,
            "boundary_message_id": snapshot.boundary_message_id,
        },
    }


def build_history_with_snapshot(
    session: Session,
    mode: str,
    current_user_message,
    max_rounds: int,
    history_builder: HistoryBuilder,
) -> list[dict]:
    """Build reusable model history from a persisted snapshot plus recent tail."""
    rounds = normalize_max_rounds(max_rounds)
    snapshot = _active_snapshot(session, mode)
    recent_messages = list(_messages_after_snapshot(session, snapshot, current_user_message))
    history = history_builder(recent_messages, rounds)
    if snapshot and snapshot.content:
        return [_snapshot_message(snapshot), *history]
    return history


def build_agent_history_with_snapshot(
    session: Session,
    current_user_message,
    max_rounds: int,
    history_builder: HistoryBuilder,
) -> list[dict]:
    return build_history_with_snapshot(session, "agent", current_user_message, max_rounds, history_builder)


def build_rag_history_with_snapshot(
    session: Session,
    current_user_message,
    max_rounds: int,
    history_builder: HistoryBuilder,
) -> list[dict]:
    return build_history_with_snapshot(session, "rag", current_user_message, max_rounds, history_builder)


def _complete_turn_groups(messages: list[Message]) -> list[list[Message]]:
    grouped: dict[str, list[Message]] = {}
    order: list[str] = []
    for message in messages:
        request_id = str(message.request_id or "")
        if not request_id:
            continue
        if request_id not in grouped:
            grouped[request_id] = []
            order.append(request_id)
        grouped[request_id].append(message)

    turns: list[list[Message]] = []
    for request_id in order:
        turn = grouped[request_id]
        has_user = any(m.role == "user" for m in turn)
        has_assistant = any(m.role == "assistant" and (m.rendered_content or m.content) for m in turn)
        if has_user and has_assistant:
            turns.append(turn)
    return turns


def _message_to_plain_history(message: Message) -> dict:
    return {
        "role": message.role,
        "content": message.rendered_content or message.content,
    }


def _messages_to_plain_history(messages: list[Message]) -> list[dict]:
    return [
        _message_to_plain_history(message)
        for message in messages
        if message.role in {"user", "assistant"} and (message.rendered_content or message.content)
    ]


def _snapshot_as_history(snapshot: ContextSnapshot | None) -> list[dict]:
    if not snapshot or not snapshot.content:
        return []
    return [_snapshot_message(snapshot)]


def _select_snapshot_source(
    session: Session,
    mode: str,
    max_rounds: int,
) -> tuple[ContextSnapshot | None, list[Message], list[Message]]:
    snapshot = _active_snapshot(session, mode)
    all_messages = list(_messages_after_snapshot(session, snapshot, current_user_message=None))
    turns = _complete_turn_groups(all_messages)
    rounds = normalize_max_rounds(max_rounds)
    retained_turns = turns[-rounds:]
    retained_ids = {message.id for turn in retained_turns for message in turn}
    to_compress = [message for message in all_messages if message.id not in retained_ids]
    to_retain = [message for message in all_messages if message.id in retained_ids]
    return snapshot, to_compress, to_retain


def maybe_update_context_snapshot(
    session: Session,
    mode: str,
    max_rounds: int,
    llm_caller=None,
    max_tokens: int = 120000,
) -> ContextSnapshot | None:
    """
    Refresh the active context snapshot when persisted history exceeds threshold.

    The snapshot covers the previous active snapshot plus old completed messages,
    while the most recent max_rounds completed turns stay verbatim.
    """
    snapshot, to_compress, to_retain = _select_snapshot_source(session, mode, max_rounds)
    source_messages = [*_snapshot_as_history(snapshot), *_messages_to_plain_history(to_compress)]
    if not source_messages:
        return None

    current_tokens = estimate_messages_tokens(source_messages + _messages_to_plain_history(to_retain))
    threshold = int(max_tokens * CONSOLIDATION_THRESHOLD)
    if current_tokens <= threshold:
        return None

    payload = build_persistent_summary_payload(source_messages, llm_caller=llm_caller)
    if not payload["content"]:
        return None

    boundary = to_retain[0] if to_retain else (to_compress[-1] if to_compress else None)
    if not boundary:
        return None

    with transaction.atomic():
        ContextSnapshot.objects.filter(session=session, mode=mode, is_active=True).update(
            is_active=False,
            updated_at=timezone.now(),
        )
        return ContextSnapshot.objects.create(
            session=session,
            mode=mode,
            boundary_message_id=boundary.id,
            boundary_created_at=boundary.created_at,
            content=payload["content"],
            key_info=payload["key_info"],
            summary=payload["summary"],
            token_before=payload["token_before"],
            token_after=payload["token_after"],
            source_message_count=payload["source_message_count"],
            is_active=True,
        )


def maybe_update_context_snapshot_async(
    session: Session,
    mode: str,
    max_rounds: int,
    llm_caller=None,
    max_tokens: int = 120000,
) -> None:
    def worker():
        try:
            fresh_session = Session.objects.get(id=session.id)
            maybe_update_context_snapshot(
                session=fresh_session,
                mode=mode,
                max_rounds=max_rounds,
                llm_caller=llm_caller,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            logger.warning("[ContextSnapshot] async update failed: %s", exc)

    if getattr(settings, "APP_TASKS_SYNC", False):
        worker()
    else:
        threading.Thread(target=worker, daemon=True).start()


def refresh_context_snapshot_async(
    session: Session,
    tenant,
    mode: str,
    max_rounds: int,
    model_id: str = "",
    max_tokens: int = 120000,
) -> None:
    def llm_caller(messages):
        from .model_providers import chat_completion

        return chat_completion(tenant, messages, model_id=model_id)

    maybe_update_context_snapshot_async(
        session=session,
        mode=mode,
        max_rounds=max_rounds,
        llm_caller=llm_caller,
        max_tokens=max_tokens,
    )


def clear_context_snapshots(session: Session) -> None:
    ContextSnapshot.objects.filter(session=session).delete()
from django.conf import settings
