"""One-time, explicit import. Normal startup never reads the legacy app files."""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from config.bootstrap import read_legacy_config as read_legacy, ENV_FIELDS, effective_startup, persistent_secret, read_startup, startup_path, write_startup
from config.runtime_paths import app_data_root
from personal_knowledge_base.models import IntegrationConfig


SECTIONS = {
    "application": {"APP_NAME": "name"},
    "neo4j": {"NEO4J_ENABLE": "enabled", "NEO4J_URI": "uri", "NEO4J_USERNAME": "username", "NEO4J_PASSWORD": "password"},
    "langfuse": {
        "LANGFUSE_ENABLED": "enabled", "LANGFUSE_BASE_URL": "base_url", "LANGFUSE_HOST": "base_url",
        "LANGFUSE_PUBLIC_KEY": "public_key", "LANGFUSE_SECRET_KEY": "secret_key",
        "LANGFUSE_UI_BASE_URL": "ui_base_url", "LANGFUSE_UI_PROJECT_ID": "ui_project_id",
        "LANGFUSE_PROJECT_ID": "ui_project_id", "LANGFUSE_TRACE_LINKS_ENABLED": "trace_links_enabled",
        "LANGFUSE_SAMPLE_RATE": "sample_rate", "LANGFUSE_LOG_CONTENT": "log_content",
        "LANGFUSE_UPLOAD_EVAL_DATASETS": "upload_eval_datasets",
        "LANGFUSE_TRACING_ENVIRONMENT": "tracing_environment", "LANGFUSE_ORPHAN_MODE": "orphan_mode",
    },
    "local_services": {
        "LANGFUSE_AUTOSTART": "autostart", "LANGFUSE_STARTUP_TIMEOUT_SECONDS": "startup_timeout_seconds",
        "LANGFUSE_AUTO_LOGIN": "auto_login", "LANGFUSE_LOGIN_EMAIL": "login_email",
        "LANGFUSE_LOGIN_PASSWORD": "password", "LANGFUSE_LOCAL_LOGIN_USER_ID": "local_login_user_id",
    },
}
BOOLEANS = {"enabled", "trace_links_enabled", "log_content", "upload_eval_datasets", "autostart", "auto_login"}


class Command(BaseCommand):
    help = "一次性迁移旧应用配置；已有数据库与启动文件字段优先，不打印敏感值"

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True)
        parser.add_argument("--server-file", help="可选 Docker Langfuse 初始化配置，仅迁移登录与项目默认值")

    def handle(self, *args, **options):
        root = app_data_root()
        try:
            values = read_legacy(options["file"])
            known = set(ENV_FIELDS) | {"no_proxy", "DJANGO_SECRET_KEY", "APP_DATA_DIR", "DJANGO_DB_PATH", "ALLOW_AUTO_SETUP"}
            known.update(key for fields in SECTIONS.values() for key in fields)
            unknown = set(values) - known
            if unknown:
                raise ValueError("未映射配置键：" + ", ".join(sorted(unknown)))
            # Data locations and first-admin setup stay deployment/launcher concerns.
            if values.get("APP_DATA_DIR") and Path(values["APP_DATA_DIR"]).expanduser().resolve() != root.resolve():
                raise ValueError("请先使用 APP_DATA_DIR 指向旧数据目录再迁移")
            from django.conf import settings
            if values.get("DJANGO_DB_PATH") and Path(values["DJANGO_DB_PATH"]).expanduser().resolve() != Path(settings.DATABASES["default"]["NAME"]).resolve():
                raise ValueError("请先使用 DJANGO_DB_PATH 指向旧数据库再迁移")
            startup_env = {k: v for k, v in values.items() if k in ENV_FIELDS}
            if "NO_PROXY" not in startup_env and "no_proxy" in values:
                startup_env["NO_PROXY"] = values["no_proxy"]
            startup_env.setdefault("DJANGO_DEBUG", "true")  # Existing source deployments defaulted to development.
            startup_values = effective_startup(root, startup_env)
            if startup_path(root).is_file():
                startup_values = read_startup(root)
            if options.get("server_file"):
                server = read_legacy(options["server_file"])
                for source, target in {
                    "LANGFUSE_INIT_PROJECT_ID": "LANGFUSE_UI_PROJECT_ID",
                    "LANGFUSE_INIT_USER_EMAIL": "LANGFUSE_LOGIN_EMAIL",
                    "LANGFUSE_INIT_USER_PASSWORD": "LANGFUSE_LOGIN_PASSWORD",
                    "LANGFUSE_INIT_PROJECT_PUBLIC_KEY": "LANGFUSE_PUBLIC_KEY",
                    "LANGFUSE_INIT_PROJECT_SECRET_KEY": "LANGFUSE_SECRET_KEY",
                }.items():
                    if server.get(source):
                        values.setdefault(target, server[source])
                values.setdefault("LANGFUSE_AUTOSTART", "true")
                values.setdefault("LANGFUSE_AUTO_LOGIN", "true" if values.get("LANGFUSE_LOGIN_PASSWORD") and values.get("LANGFUSE_LOGIN_EMAIL") else "false")
            updates = {}
            for section, fields in SECTIONS.items():
                config = {}
                for source, target in fields.items():
                    if source not in values or target in config:
                        continue
                    raw = values[source]
                    if target in BOOLEANS:
                        if raw.lower() not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
                            raise ValueError(f"{source} 布尔值错误")
                        raw = raw.lower() in {"true", "1", "yes", "on"}
                    elif target in {"sample_rate", "startup_timeout_seconds"}:
                        raw = float(raw)
                    config[target] = raw
                updates[section] = config
            from models_config.system_config import validate_section
            for section, config in updates.items():
                validate_section(section, config)
            # A previously supplied stable Django secret must be retained, not replaced.
            supplied = values.get("DJANGO_SECRET_KEY")
            key_path = root / ".secrets" / "django.key"
            if supplied and key_path.is_file() and key_path.read_text().strip() != supplied:
                raise ValueError("现有 Django 密钥与旧配置不同，请先核对并保留原密钥")
            if supplied and not key_path.is_file():
                key_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                import os
                fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    stream.write(supplied)
            persistent_secret(root)
            with transaction.atomic():
                for section, config in updates.items():
                    if not config:
                        continue
                    row, _ = IntegrationConfig.objects.get_or_create(name=section)
                    row = IntegrationConfig.objects.select_for_update().get(name=section)
                    row.parameters = {**config, **dict(row.parameters)}
                    row.save()
                    self.stdout.write(section + ": imported (existing fields preserved)")
                write_startup(root, startup_values)
        except (OSError, ValueError, TypeError) as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write("Configuration import complete; secrets not displayed.")
