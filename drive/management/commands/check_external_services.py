from uuid import uuid4

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Check SQLite, FTS5, sqlite-vec and local file storage."

    def handle(self, *args, **options):
        self._check_sqlite()
        self._check_fts5()
        self._check_sqlite_vec()
        self._check_file_storage()
        self.stdout.write(self.style.SUCCESS("All local services are ready."))

    def _check_sqlite(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        self.stdout.write(self.style.SUCCESS("SQLite OK"))

    def _check_fts5(self):
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS temp.fts5_check")
            cursor.execute("CREATE VIRTUAL TABLE temp.fts5_check USING fts5(content, tokenize='trigram')")
            cursor.execute("INSERT INTO temp.fts5_check(rowid, content) VALUES (1, %s)", ["SQLite 中文全文搜索检查"])
            cursor.execute("SELECT rowid FROM temp.fts5_check WHERE fts5_check MATCH %s", ['"全文搜索"'])
            if not cursor.fetchone():
                raise RuntimeError("SQLite FTS5 trigram check failed")
            cursor.execute("DROP TABLE temp.fts5_check")
        self.stdout.write(self.style.SUCCESS("SQLite FTS5 OK"))

    def _check_sqlite_vec(self):
        from knowledge.sqlite_search import ensure_search_tables

        ensure_search_tables()
        with connection.cursor() as cursor:
            cursor.execute("SELECT vec_version()")
            cursor.fetchone()
        self.stdout.write(self.style.SUCCESS("sqlite-vec OK"))

    def _check_file_storage(self):
        name = f"healthchecks/{uuid4().hex}.txt"
        saved_name = default_storage.save(name, ContentFile(b"ok"))
        try:
            with default_storage.open(saved_name, "rb") as stored:
                if stored.read() != b"ok":
                    raise RuntimeError("Local file storage round-trip failed")
        finally:
            if default_storage.exists(saved_name):
                default_storage.delete(saved_name)
        self.stdout.write(self.style.SUCCESS("Local file storage OK"))
