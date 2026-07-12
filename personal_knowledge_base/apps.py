from django.apps import AppConfig


class PersonalKnowledgeBaseConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "personal_knowledge_base"

    def ready(self):
        from .startup import check_sqlite_capabilities
        from .tasks import schedule_startup_recovery, start_task_runner

        check_sqlite_capabilities()
        start_task_runner()
        schedule_startup_recovery()
