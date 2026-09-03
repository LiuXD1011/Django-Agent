"""Cross-worker SSE event and stream state storage."""

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .db_retry import retry_on_db_lock

logger = logging.getLogger(__name__)


@dataclass
class StreamEvent:
    event_type: str
    data: dict
    offset: int
    timestamp: float = field(default_factory=time.time)


class MessageStream:
    """In-process view of a durable message stream."""

    def __init__(self, message_id: str, session_id: str):
        self.message_id = str(message_id)
        self.session_id = str(session_id)
        self.events: list[StreamEvent] = []
        self.is_complete = False
        self.is_error = False
        self.error_message = ""
        self.final_content = ""
        self.final_refs: list = []
        self.final_steps: list = []
        self.final_duration_ms = 0
        self.created_at = time.time()
        self._lock = threading.Lock()

    def append_event(self, event_type: str, data: dict, offset: int | None = None) -> StreamEvent:
        with self._lock:
            event = StreamEvent(
                event_type=event_type,
                data=data,
                offset=len(self.events) if offset is None else offset,
            )
            self.events.append(event)
            if event_type == "complete":
                self.is_complete = True
            elif event_type == "error":
                self.is_error = True
                self.error_message = data.get("content", "")
            return event

    def get_events(self, from_offset: int = 0) -> list[StreamEvent]:
        with self._lock:
            return self.events[from_offset:]

    @property
    def age(self) -> float:
        return time.time() - self.created_at


class StreamManager:
    """Memory cache backed by database state and an append-only event log."""

    _instance = None
    _lock = threading.Lock()
    TTL = 3600

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._streams: dict[str, MessageStream] = {}
                cls._instance._data_lock = threading.Lock()
                cls._instance._cleanup_thread = threading.Thread(
                    target=cls._instance._cleanup_loop, daemon=True
                )
                cls._instance._cleanup_thread.start()
            return cls._instance

    @staticmethod
    def _models():
        from .models import StreamEventRecord, StreamState

        return StreamEventRecord, StreamState

    def create_stream(self, message_id: str, session_id: str) -> MessageStream:
        return self.ensure_stream(message_id, session_id, replace=True)

    def ensure_stream(self, message_id: str, session_id: str, replace: bool = False) -> MessageStream:
        message_id, session_id = str(message_id), str(session_id)
        with self._data_lock:
            if not replace and message_id in self._streams:
                return self._streams[message_id]
            stream = self._hydrate_stream(message_id, session_id)
            if replace:
                stream = MessageStream(message_id, session_id)
            self._streams[message_id] = stream
            _, StreamState = self._models()

            def _upsert_state():
                StreamState.objects.update_or_create(
                    message_id=message_id,
                    defaults={"session_id": session_id},
                )

            retry_on_db_lock(_upsert_state)
            logger.info("[StreamManager] Registered stream for message %s", message_id)
            return stream

    def _hydrate_stream(self, message_id: str, session_id: str) -> MessageStream:
        StreamEventRecord, StreamState = self._models()
        stream = MessageStream(message_id, session_id)
        state = StreamState.objects.filter(message_id=message_id).first()
        if state:
            stream.session_id = state.session_id
            stream.created_at = state.created_at.timestamp()
            stream.is_complete = state.is_complete
            stream.is_error = state.is_error
            stream.error_message = state.error_message
            stream.final_content = state.final_content
            stream.final_refs = state.final_refs or []
            stream.final_steps = state.final_steps or []
            stream.final_duration_ms = state.final_duration_ms
        for record in StreamEventRecord.objects.filter(message_id=message_id).order_by("offset"):
            stream.append_event(record.event_type, record.data or {}, offset=record.offset)
        return stream

    def get_stream(self, message_id: str) -> MessageStream | None:
        message_id = str(message_id)
        stream = self._streams.get(message_id)
        if stream:
            return stream
        StreamEventRecord, StreamState = self._models()
        if not StreamState.objects.filter(message_id=message_id).exists():
            return None
        session_id = StreamState.objects.filter(message_id=message_id).values_list("session_id", flat=True).first()
        stream = self._hydrate_stream(message_id, session_id or "")
        with self._data_lock:
            return self._streams.setdefault(message_id, stream)

    def remove_stream(self, message_id: str):
        message_id = str(message_id)
        StreamEventRecord, StreamState = self._models()

        def _delete_state():
            with transaction.atomic():
                StreamEventRecord.objects.filter(message_id=message_id).delete()
                StreamState.objects.filter(message_id=message_id).delete()

        with self._data_lock:
            self._streams.pop(message_id, None)
            retry_on_db_lock(_delete_state)
        logger.info("[StreamManager] Removed stream for message %s", message_id)

    def set_final_result(self, message_id: str, content: str, refs: list = None, steps: list = None, duration_ms: int = 0):
        stream = self.get_stream(message_id)
        if stream:
            stream.final_content = content
            stream.final_refs = refs or []
            stream.final_steps = steps or []
            stream.final_duration_ms = duration_ms
        _, StreamState = self._models()
        retry_on_db_lock(
            lambda: StreamState.objects.filter(message_id=str(message_id)).update(
                final_content=content,
                final_refs=refs or [],
                final_steps=steps or [],
                final_duration_ms=duration_ms,
                updated_at=timezone.now(),
            )
        )

    def append_event(self, message_id: str, event_type: str, data: dict) -> StreamEvent | None:
        message_id = str(message_id)
        stream = self.get_stream(message_id)
        if not stream:
            return None
        StreamEventRecord, StreamState = self._models()

        def _persist_event():
            with transaction.atomic():
                offset = StreamEventRecord.objects.filter(message_id=message_id).count()
                record = StreamEventRecord.objects.create(
                    message_id=message_id,
                    session_id=stream.session_id,
                    event_type=event_type,
                    data=data,
                    offset=offset,
                )
                state_updates = {"updated_at": timezone.now()}
                if event_type == "complete":
                    state_updates["is_complete"] = True
                elif event_type == "error":
                    state_updates.update(is_error=True, error_message=data.get("content", ""))
                StreamState.objects.filter(message_id=message_id).update(**state_updates)
                return record

        record = retry_on_db_lock(_persist_event)
        with self._data_lock:
            return stream.append_event(event_type, data, offset=record.offset)

    def get_events(self, message_id: str, from_offset: int = 0) -> list[StreamEvent]:
        stream = self._streams.get(str(message_id))
        if stream:
            self._refresh_stream(stream)
            return stream.get_events(from_offset)
        stream = self.get_stream(message_id)
        return stream.get_events(from_offset) if stream else []

    def _refresh_stream(self, stream: MessageStream):
        StreamEventRecord, StreamState = self._models()
        with self._data_lock:
            known_offsets = {event.offset for event in stream.events}
            for record in StreamEventRecord.objects.filter(
                message_id=stream.message_id,
                offset__gte=len(stream.events),
            ).order_by("offset"):
                if record.offset not in known_offsets:
                    stream.append_event(record.event_type, record.data or {}, offset=record.offset)
            state = StreamState.objects.filter(message_id=stream.message_id).first()
            if state:
                stream.is_complete = state.is_complete
                stream.is_error = state.is_error
                stream.error_message = state.error_message
                stream.final_content = state.final_content
                stream.final_refs = state.final_refs or []
                stream.final_steps = state.final_steps or []
                stream.final_duration_ms = state.final_duration_ms

    def is_complete(self, message_id: str) -> bool:
        stream = self.get_stream(message_id)
        return stream.is_complete if stream else True

    def _cleanup_loop(self):
        while True:
            time.sleep(300)
            cutoff = timezone.now() - timedelta(seconds=self.TTL)
            try:
                StreamEventRecord, StreamState = self._models()
                expired = list(StreamState.objects.filter(created_at__lt=cutoff).values_list("message_id", flat=True))
                with self._data_lock:
                    StreamEventRecord.objects.filter(message_id__in=expired).delete()
                    StreamState.objects.filter(message_id__in=expired).delete()
                    for message_id in expired:
                        self._streams.pop(message_id, None)
            except Exception:
                logger.exception("[StreamManager] Failed to clean expired streams")


stream_manager = StreamManager()
