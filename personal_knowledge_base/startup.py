import logging
import sqlite3

from django.db.backends.signals import connection_created


logger = logging.getLogger(__name__)


def _load_sqlite_vec(connection):
    if connection.vendor != "sqlite":
        return
    try:
        import sqlite_vec

        raw = connection.connection
        raw.enable_load_extension(True)
        sqlite_vec.load(raw)
        raw.enable_load_extension(False)
    except Exception as exc:  # pragma: no cover - startup diagnostics
        logger.warning("sqlite-vec could not be loaded: %s", exc)


def _on_connection_created(sender, connection, **kwargs):
    _load_sqlite_vec(connection)
    _enable_wal_mode(connection)


def _enable_wal_mode(connection):
    """启用 SQLite WAL 模式，允许读写并发，减少 database locked 错误。"""
    if connection.vendor != "sqlite":
        return
    try:
        raw = connection.connection
        raw.execute("PRAGMA journal_mode=WAL")
        raw.execute("PRAGMA busy_timeout=30000")
    except Exception:
        pass


connection_created.connect(_on_connection_created, dispatch_uid="personal_kb_sqlite_vec")


def check_sqlite_capabilities():
    con = sqlite3.connect(":memory:")
    has_fts5 = any("ENABLE_FTS5" in row[0] for row in con.execute("pragma compile_options"))
    con.close()
    if not has_fts5:
        raise RuntimeError("SQLite FTS5 is required for the 个人轻量知识库 Django backend")
