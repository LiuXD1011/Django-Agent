from django.apps import AppConfig
from django.db.backends.signals import connection_created


class KnowledgeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'knowledge'

    def ready(self):
        from . import signals  # noqa: F401
        from .sqlite_search import load_sqlite_vec_on_connect

        connection_created.connect(load_sqlite_vec_on_connect, dispatch_uid="knowledge_load_sqlite_vec")
