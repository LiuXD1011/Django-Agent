"""Single runtime source for UI-managed application and integration settings."""
from django.conf import settings

from .models import IntegrationConfig


def stored_configuration(name):
    try:
        row = IntegrationConfig.objects.filter(name=name).first()
    except Exception:
        # 数据库尚未迁移、测试隔离或连接不可用时，集成配置属于旁路增强：
        # 回退 settings 默认值，绝不能阻断启动、诊断或桌面引导路径。
        return {}
    return dict(row.parameters) if row else {}


def application_configuration():
    return {"name": settings.APP_NAME, **stored_configuration("application")}


def neo4j_configuration():
    return {
        "enabled": settings.NEO4J_ENABLE,
        "uri": settings.NEO4J_URI,
        "username": settings.NEO4J_USERNAME,
        "password": settings.NEO4J_PASSWORD,
        **stored_configuration("neo4j"),
    }


def langfuse_configuration():
    return {
        "enabled": settings.LANGFUSE_ENABLED,
        "base_url": settings.LANGFUSE_BASE_URL,
        "public_key": "", "secret_key": "",
        "ui_base_url": settings.LANGFUSE_UI_BASE_URL if settings.LANGFUSE_UI_BASE_URL != settings.LANGFUSE_BASE_URL else "", "ui_project_id": settings.LANGFUSE_UI_PROJECT_ID,
        "trace_links_enabled": settings.LANGFUSE_TRACE_LINKS_ENABLED,
        "sample_rate": settings.LANGFUSE_SAMPLE_RATE,
        "log_content": settings.LANGFUSE_LOG_CONTENT,
        "upload_eval_datasets": settings.LANGFUSE_UPLOAD_EVAL_DATASETS,
        "tracing_environment": settings.LANGFUSE_TRACING_ENVIRONMENT,
        "orphan_mode": settings.LANGFUSE_ORPHAN_MODE,
        **stored_configuration("langfuse"),
    }


def local_services_configuration():
    return {
        "autostart": False, "startup_timeout_seconds": 45, "auto_login": False,
        "login_email": "", "password": "", "local_login_user_id": "",
        **stored_configuration("local_services"),
    }
