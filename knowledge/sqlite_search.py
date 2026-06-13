from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import connection


def sqlite_vec_available(raw_connection):
    try:
        raw_connection.execute("SELECT vec_version()").fetchone()
        return True
    except Exception:
        return False


def load_sqlite_vec(db_connection):
    if db_connection.vendor != "sqlite":
        raise ImproperlyConfigured("sqlite-vec search requires the SQLite database backend.")
    if db_connection.connection is None:
        db_connection.ensure_connection()

    raw_connection = db_connection.connection
    loaded_connection_id = getattr(db_connection, "_sqlite_vec_loaded_connection_id", None)
    if loaded_connection_id == id(raw_connection) and sqlite_vec_available(raw_connection):
        return
    if sqlite_vec_available(raw_connection):
        db_connection._sqlite_vec_loaded_connection_id = id(raw_connection)
        return

    try:
        import sqlite_vec
    except ImportError as exc:
        raise ImproperlyConfigured("Missing dependency: install sqlite-vec to use knowledge search.") from exc

    try:
        raw_connection.enable_load_extension(True)
        sqlite_vec.load(raw_connection)
    except Exception as exc:
        raise ImproperlyConfigured(f"Unable to load sqlite-vec: {exc}") from exc
    finally:
        try:
            raw_connection.enable_load_extension(False)
        except Exception:
            pass

    if not sqlite_vec_available(raw_connection):
        raise ImproperlyConfigured("sqlite-vec loaded but vec0 is unavailable on the active SQLite connection.")

    db_connection._sqlite_vec_loaded_connection_id = id(raw_connection)


def load_sqlite_vec_on_connect(sender, connection, **kwargs):
    if connection.vendor == "sqlite":
        load_sqlite_vec(connection)


def vector_dim():
    return int(getattr(settings, "EMBEDDING_VECTOR_DIM", 96))


def ensure_search_tables():
    load_sqlite_vec(connection)
    dim = vector_dim()
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_kbchunk_vec
            USING vec0(
                chunk_id integer primary key,
                kb_id integer partition key,
                embedding float[{dim}]
            )
            """
        )
        cursor.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_kbchunk_fts
            USING fts5(content, tokenize='trigram')
            """
        )
        cursor.execute(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_wikipage_vec
            USING vec0(
                page_id integer primary key,
                kb_id integer partition key,
                embedding float[{dim}]
            )
            """
        )
        cursor.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_wikipage_fts
            USING fts5(title, content, tokenize='trigram')
            """
        )
