"""
StreamManager: 内存级 SSE 事件持久化存储。

参考 WeKnora 的 MemoryStreamManager 设计：
- 每个 message_id 对应一个事件列表
- 事件一旦追加就不会丢失（即使客户端断开）
- 支持增量读取（通过 offset）
- 自动清理过期事件（TTL 1小时）

这使得：
1. 后端生成与 SSE 推送完全解耦
2. 客户端断开后可重连回放所有已产生事件
3. 生成线程不受客户端连接状态影响
"""

import threading
import time
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class StreamEvent:
    """单个流式事件"""
    event_type: str  # thinking, tool_call, tool_result, answer, complete, error
    data: dict
    offset: int
    timestamp: float = field(default_factory=time.time)


class MessageStream:
    """单个消息的事件流"""

    def __init__(self, message_id: str, session_id: str):
        self.message_id = message_id
        self.session_id = session_id
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

    def append_event(self, event_type: str, data: dict) -> StreamEvent:
        """追加一个事件"""
        with self._lock:
            event = StreamEvent(
                event_type=event_type,
                data=data,
                offset=len(self.events),
            )
            self.events.append(event)

            if event_type == "complete":
                self.is_complete = True
            elif event_type == "error":
                self.is_error = True
                self.error_message = data.get("content", "")

            return event

    def get_events(self, from_offset: int = 0) -> list[StreamEvent]:
        """从指定 offset 获取事件"""
        with self._lock:
            return self.events[from_offset:]

    def set_final_result(self, content: str, refs: list = None, steps: list = None, duration_ms: int = 0):
        """设置最终结果（用于数据库持久化）"""
        with self._lock:
            self.final_content = content
            self.final_refs = refs or []
            self.final_steps = steps or []
            self.final_duration_ms = duration_ms

    @property
    def age(self) -> float:
        """存活时间（秒）"""
        return time.time() - self.created_at


class StreamManager:
    """
    全局流式事件管理器（单例模式）。

    线程安全，支持：
    - 创建/获取消息流
    - 追加事件
    - 增量读取事件
    - 自动清理过期流
    """

    _instance = None
    _lock = threading.Lock()
    TTL = 3600  # 1小时过期

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._streams: dict[str, MessageStream] = {}
                cls._instance._data_lock = threading.Lock()
                # 启动清理线程
                cls._instance._cleanup_thread = threading.Thread(
                    target=cls._instance._cleanup_loop, daemon=True
                )
                cls._instance._cleanup_thread.start()
            return cls._instance

    def create_stream(self, message_id: str, session_id: str) -> MessageStream:
        """创建新的消息流"""
        with self._data_lock:
            stream = MessageStream(message_id, session_id)
            self._streams[message_id] = stream
            logger.info(f"[StreamManager] Created stream for message {message_id}")
            return stream

    def get_stream(self, message_id: str) -> MessageStream | None:
        """获取消息流"""
        return self._streams.get(message_id)

    def remove_stream(self, message_id: str):
        """移除消息流"""
        with self._data_lock:
            self._streams.pop(message_id, None)
            logger.info(f"[StreamManager] Removed stream for message {message_id}")

    def append_event(self, message_id: str, event_type: str, data: dict) -> StreamEvent | None:
        """向指定消息流追加事件"""
        stream = self._streams.get(message_id)
        if stream:
            return stream.append_event(event_type, data)
        return None

    def get_events(self, message_id: str, from_offset: int = 0) -> list[StreamEvent]:
        """获取指定消息流的事件"""
        stream = self._streams.get(message_id)
        if stream:
            return stream.get_events(from_offset)
        return []

    def is_complete(self, message_id: str) -> bool:
        """检查消息流是否已完成"""
        stream = self._streams.get(message_id)
        return stream.is_complete if stream else True

    def _cleanup_loop(self):
        """定期清理过期的流"""
        while True:
            time.sleep(300)  # 每5分钟清理一次
            with self._data_lock:
                expired = [
                    mid for mid, stream in self._streams.items()
                    if stream.age > self.TTL
                ]
                for mid in expired:
                    del self._streams[mid]
                    logger.info(f"[StreamManager] Expired stream for message {mid}")


# 全局单例
stream_manager = StreamManager()
