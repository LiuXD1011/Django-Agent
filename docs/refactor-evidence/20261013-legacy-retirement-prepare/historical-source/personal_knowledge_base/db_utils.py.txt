"""
数据库工具函数

提供重试逻辑和连接管理，解决 SQLite 并发写入问题。
"""

import functools
import logging
import time
from contextlib import contextmanager

from django.db import connection, transaction

logger = logging.getLogger(__name__)

# 重试配置
MAX_RETRIES = 3
RETRY_DELAY = 0.1  # 100ms
RETRY_BACKOFF = 2  # 指数退避倍数


def retry_on_locked(max_retries: int = MAX_RETRIES, delay: float = RETRY_DELAY):
    """
    装饰器：当 SQLite 报 "database is locked" 时自动重试。
    参考同类知识库系统的重试策略。
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            current_delay = delay
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    error_str = str(e).lower()
                    if "database is locked" in error_str or "database is busy" in error_str:
                        last_error = e
                        if attempt < max_retries - 1:
                            logger.warning(f"[DB Retry] {func.__name__} attempt {attempt + 1} failed, retrying in {current_delay:.1f}s: {e}")
                            time.sleep(current_delay)
                            current_delay *= RETRY_BACKOFF
                        else:
                            logger.error(f"[DB Retry] {func.__name__} failed after {max_retries} attempts: {e}")
                            raise
                    else:
                        raise
            raise last_error
        return wrapper
    return decorator


def safe_db_operation(func):
    """
    装饰器：安全执行数据库操作，自动处理连接问题。
    在后台线程中执行数据库操作时特别有用。
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            error_str = str(e).lower()
            if "database is locked" in error_str or "database is busy" in error_str:
                logger.warning(f"[DB Safe] {func.__name__} encountered lock, closing connection and retrying...")
                try:
                    connection.close()
                except Exception:
                    pass
                time.sleep(0.1)
                return func(*args, **kwargs)
            raise
    return wrapper


@contextmanager
def db_retry_context(max_retries: int = MAX_RETRIES, delay: float = RETRY_DELAY):
    """
    上下文管理器：在 with 块内自动重试数据库操作。
    """
    last_error = None
    current_delay = delay
    for attempt in range(max_retries):
        try:
            yield
            return
        except Exception as e:
            error_str = str(e).lower()
            if "database is locked" in error_str or "database is busy" in error_str:
                last_error = e
                if attempt < max_retries - 1:
                    logger.warning(f"[DB Retry] attempt {attempt + 1} failed, retrying in {current_delay:.1f}s: {e}")
                    time.sleep(current_delay)
                    current_delay *= RETRY_BACKOFF
                    # 关闭连接以释放锁
                    try:
                        connection.close()
                    except Exception:
                        pass
                else:
                    logger.error(f"[DB Retry] failed after {max_retries} attempts: {e}")
                    raise
            else:
                raise
    if last_error:
        raise last_error


def close_db_connections():
    """
    关闭当前线程的数据库连接。
    在后台线程完成数据库操作后调用，避免连接泄漏。
    """
    try:
        connection.close()
    except Exception:
        pass
