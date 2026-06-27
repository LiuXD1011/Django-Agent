import logging
import sqlite3
from pathlib import Path

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


def mirror_legacy_migration_records(db_path):
    db_path = Path(db_path)
    if not db_path.exists():
        return
    con = sqlite3.connect(db_path)
    try:
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "django_migrations" not in tables:
            return
        rows = con.execute("SELECT name, applied FROM django_migrations WHERE app = ?", ["weknora_app"]).fetchall()
        if not rows:
            return
        existing = {row[0] for row in con.execute("SELECT name FROM django_migrations WHERE app = ?", ["personal_knowledge_base"]).fetchall()}
        for name, applied in rows:
            if name not in existing:
                con.execute(
                    "INSERT INTO django_migrations(app, name, applied) VALUES (?, ?, ?)",
                    ["personal_knowledge_base", name, applied],
                )
        con.commit()
    except Exception as exc:  # pragma: no cover - best-effort compatibility
        logger.warning("legacy migration compatibility check failed: %s", exc)
    finally:
        con.close()
