from django.apps import AppConfig


class PersonalKnowledgeBaseConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "personal_knowledge_base"

    def ready(self):
        from django.conf import settings

        from .startup import check_sqlite_capabilities
        from .tasks import schedule_startup_recovery, start_task_runner

        check_sqlite_capabilities()
        # W04 分层：api 模式（纯 API 副本）不启动任务执行与恢复线程，
        # 由独立 worker 进程承担；local/worker/all-in-one 保持既有行为。
        if getattr(settings, "RUN_TASK_BACKGROUND", True):
            start_task_runner()
            schedule_startup_recovery()
