"""SQLite 并发写锁重试工具。

agent 生成线程、actor 子线程与请求线程会并发写 SQLite；WAL + busy_timeout
仍会在"读事务升级写锁"竞争时抛 `database is locked`。对高频写路径
（流事件落库、消息创建）统一用指数退避重试，避免把锁冲突放大成请求 500。
"""

import logging
import time

from django.db import OperationalError

logger = logging.getLogger(__name__)


def is_db_lock_error(exc: Exception) -> bool:
    return isinstance(exc, OperationalError) and "locked" in str(exc).lower()


def retry_on_db_lock(operation, *, attempts: int = 6, base_delay: float = 0.05, max_delay: float = 0.8):
    """执行 operation()，遇到 SQLite 写锁冲突时指数退避重试后抛出。"""
    delay = base_delay
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except OperationalError as exc:
            if not is_db_lock_error(exc) or attempt == attempts:
                raise
            logger.warning(
                "SQLite database locked (attempt %s/%s), retrying in %.2fs",
                attempt, attempts, delay,
            )
            time.sleep(delay)
            delay = min(delay * 2, max_delay)
