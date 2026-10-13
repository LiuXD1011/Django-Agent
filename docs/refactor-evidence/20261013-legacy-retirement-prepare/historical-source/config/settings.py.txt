import os
import sys
from pathlib import Path

from config.runtime_paths import resolve_data_directory
from config.bootstrap import ENV_FIELDS, effective_startup, persistent_secret, read_startup


BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


# ── 用户数据根（可选 APP_DATA_DIR）───────────────────────────────
# 安装目录只读时（如 Windows Program Files），把全部运行写入（SQLite 数据库、
# media/staticfiles、.cache 各类缓存与 Langfuse 启动状态）整体定向到独立的
# 用户数据根；源码资源（templates、前端 dist、静态资源来源、数据集
# manifests、.env.langfuse/docker-compose）仍从源码根 BASE_DIR 读取。
# 未设置或空白时 APP_DATA_DIR 为 None：所有运行写入维持既有行为（BASE_DIR
# 下）；运行期路径统一经 config.runtime_paths 的 helper 按当时 settings
# 解析（APP_DATA_DIR 优先，否则回落当前 settings.BASE_DIR），因此
# override_settings(BASE_DIR=...) 的隔离测试继续生效，旧根不在导入期冻结。
# 显式路径 expanduser 并解析为绝对路径；不自动迁移/复制/删除旧用户数据。
_app_data_dir_raw = os.environ.get("APP_DATA_DIR")
APP_DATA_DIR = (
    resolve_data_directory(BASE_DIR, _app_data_dir_raw)
    if (_app_data_dir_raw or "").strip()
    else None
)
# settings 装载期的写入根（settings 值本身是导入期快照；运行期动态解析
# 一律走 config.runtime_paths.app_data_root()/runtime_cache_dir()）。
_DATA_ROOT = APP_DATA_DIR if APP_DATA_DIR is not None else BASE_DIR
STARTUP_SAVED = read_startup(_DATA_ROOT)
STARTUP_CONFIG = effective_startup(_DATA_ROOT)
STARTUP_ENV_OVERRIDES = [name for name in ENV_FIELDS if name in os.environ]
for _name in ("NO_PROXY", "no_proxy"):
    os.environ.setdefault(_name, STARTUP_CONFIG["no_proxy"])
if STARTUP_CONFIG["proxy_url"]:
    for _name in ("HTTP_PROXY", "HTTPS_PROXY"):
        os.environ.setdefault(_name, STARTUP_CONFIG["proxy_url"])


# ── 安全配置 ─────────────────────────────────────────────────────
# 首次生成并持久保存（APP_DATA_DIR/.secrets/django.key，0600，带完整性校验）；
# 显式提供的 DJANGO_SECRET_KEY 始终优先；凭据加密密钥独立存储。
SECRET_KEY = persistent_secret(_DATA_ROOT, os.environ.get("DJANGO_SECRET_KEY"))
DEBUG = STARTUP_CONFIG["debug"]
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG
# Development frontend proxy only; production browser/PWA stays same-origin.
CSRF_TRUSTED_ORIGINS = STARTUP_CONFIG["cors_origins"] if DEBUG else []
# Opt in only behind a trusted proxy which strips incoming forwarded headers.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if env_bool("DJANGO_TRUST_PROXY_PROTO", False) else None


# 首次管理员初始化必须由部署环境显式开启
ALLOW_AUTO_SETUP = env_bool("ALLOW_AUTO_SETUP", False)

# ALLOWED_HOSTS: 生产环境必须限制
ALLOWED_HOSTS = STARTUP_CONFIG["allowed_hosts"]

APP_NAME = os.environ.get("APP_NAME", "个人轻量知识库")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "accounts",
    "knowledge",
    "chat",
    "wiki",
    "agent",
    "models_config",
    "personal_knowledge_base",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "accounts.device_sessions.DeviceSessionCsrfMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates", BASE_DIR / "frontend" / "dist"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]
WSGI_APPLICATION = "config.wsgi.application"

def _database_from_url(url: str) -> dict:
    """最小 DATABASE_URL 解析（W05）：postgres/postgresql 仅；显式提供 URL 即团队模式。

    只支持 postgres://user:pass@host:port/name?opt=value——团队后端的既定底座。
    SQLite 路径不经此入口，避免把共享盘 SQLite 误用为多机 HA。
    """
    from urllib.parse import parse_qsl, urlsplit

    parsed = urlsplit(url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ValueError("DATABASE_URL 仅支持 postgres://（团队模式底座）；本地开发请勿设置该变量")
    if not parsed.hostname or not parsed.path.lstrip("/"):
        raise ValueError("DATABASE_URL 缺少主机或数据库名")
    options = dict(parse_qsl(parsed.query))
    engine_options = {}
    if "sslmode" in options:
        engine_options["sslmode"] = options["sslmode"]
    if "connect_timeout" in options:
        engine_options["connect_timeout"] = int(options["connect_timeout"])
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.path.lstrip("/"),
        "USER": parsed.username or "",
        "PASSWORD": parsed.password or "",
        "HOST": parsed.hostname,
        "PORT": str(parsed.port or 5432),
        "CONN_MAX_AGE": int(options.get("conn_max_age", "60")),
        "OPTIONS": engine_options,
    }


_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if _DATABASE_URL:
    DATABASES = {"default": _database_from_url(_DATABASE_URL)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            # DJANGO_DB_PATH 供隔离测试/演练使用，优先级最高；其次用户数据根下
            # 的 db.sqlite3（APP_DATA_DIR 显式指定时），缺省仍为项目根 db.sqlite3
            "NAME": os.environ.get("DJANGO_DB_PATH") or (_DATA_ROOT / "db.sqlite3"),
            "OPTIONS": {
                "timeout": STARTUP_CONFIG["sqlite_timeout"],
                "init_command": f"PRAGMA journal_mode=WAL; PRAGMA busy_timeout={STARTUP_CONFIG['sqlite_timeout'] * 1000}; PRAGMA synchronous=NORMAL;",
            },
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "Asia/Shanghai"
LANGUAGE_CODE = "zh-hans"

STATIC_URL = "static/"
# staticfiles 收集产物是运行写入 → 用户数据根；前端 dist 来源仍在源码根。
STATIC_ROOT = _DATA_ROOT / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "frontend" / "dist" / "assets"] if (BASE_DIR / "frontend" / "dist" / "assets").exists() else []

MEDIA_URL = "/files/"
# 上传文档等用户媒体是运行写入 → 用户数据根（APP_DATA_DIR 缺省回落 BASE_DIR）。
MEDIA_ROOT = _DATA_ROOT / "media"
DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "personal-kb-locmem",
    }
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
}

def _resolve_model_config(model_type: str, default_model: str, default_base_url: str, default_api_key: str = "") -> dict:
    """
    解析非敏感的模型默认值；凭据只从数据库中的前端配置读取。
    模型与凭据由数据库配置；这些常量仅保留内部未配置状态的默认值。
    """
    # 不读取环境中的模型凭据，即使外部进程仍注入旧变量。
    api_key = ""  # Credentials are exclusively managed through the authenticated UI.
    base_url = default_base_url
    model = default_model

    return {
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
    }


# ── LLM 配置（每个模型独立配置，支持不同提供商）────────────────────
_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# 对话模型
LLM_CHAT_CONFIG = _resolve_model_config("CHAT", "qwen3.6-flash", _DEFAULT_BASE_URL)
LLM_CHAT_API_KEY = LLM_CHAT_CONFIG["api_key"]
LLM_CHAT_BASE_URL = LLM_CHAT_CONFIG["base_url"]
LLM_CHAT_MODEL = LLM_CHAT_CONFIG["model"]

# ── Langfuse 可观测性（可选，默认关闭）────────────────────────────
# 必须显式设置 LANGFUSE_ENABLED=true 才启用（v2 行为是"有密钥即启用"，升级部署需同步改环境）；
# 关闭时不出网。未配置密钥或 SDK 未安装时同样全部静默降级为本地模式。
# LOG_CONTENT 默认 False：只上报模型/场景/token/耗时等元数据，不上传 prompt 与文档内容。
LANGFUSE_ENABLED = os.environ.get("LANGFUSE_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
# BASE_URL 为新首选；HOST 为旧配置别名，仅当 BASE_URL 未设置时生效。
LANGFUSE_BASE_URL = os.environ.get("LANGFUSE_BASE_URL", "") or os.environ.get("LANGFUSE_HOST", "") or "http://localhost:3000"
LANGFUSE_HOST = LANGFUSE_BASE_URL
LANGFUSE_PUBLIC_KEY = ""
LANGFUSE_SECRET_KEY = ""
LANGFUSE_LOG_CONTENT = os.environ.get("LANGFUSE_LOG_CONTENT", "").strip().lower() in {"1", "true", "yes", "on"}
# 无业务 trace 上下文时（如管理命令、脚本）generation 的处理：skip（默认）或 standalone（建独立 trace）
LANGFUSE_ORPHAN_MODE = os.environ.get("LANGFUSE_ORPHAN_MODE", "skip")
# 评估任务是否把题目/参考答案 upsert 成 Langfuse Dataset（避免重复项默认关闭，trace 始终上报）
LANGFUSE_UPLOAD_EVAL_DATASETS = os.environ.get("LANGFUSE_UPLOAD_EVAL_DATASETS", "").strip().lower() in {"1", "true", "yes", "on"}
# Langfuse 环境标签（SDK environment 属性，区分 development/production 项目）
LANGFUSE_TRACING_ENVIRONMENT = os.environ.get("LANGFUSE_TRACING_ENVIRONMENT", "development")
# 根级采样率（0~1，子节点继承；仅门面根级判断，不与 SDK 内部采样叠加）
_langfuse_sample_rate_raw = os.environ.get("LANGFUSE_SAMPLE_RATE", "1.0")
try:
    LANGFUSE_SAMPLE_RATE = min(max(float(_langfuse_sample_rate_raw), 0.0), 1.0)
except (TypeError, ValueError):
    LANGFUSE_SAMPLE_RATE = 1.0
# 浏览器可访问的 Langfuse UI 地址（默认同 BASE_URL；容器内 API 地址与宿主浏览器地址不同时必须单独配置）
LANGFUSE_UI_BASE_URL = os.environ.get("LANGFUSE_UI_BASE_URL", "") or LANGFUSE_BASE_URL
# Langfuse 项目 ID（UI 追踪 URL 用；从 Langfuse 项目设置页 URL 取，留空则不生成跳转链接）
LANGFUSE_UI_PROJECT_ID = os.environ.get("LANGFUSE_UI_PROJECT_ID", "")
# 会话轨迹面板"查看 Langfuse 追踪"跳转开关（默认关闭；开启后仍受后端平台运维角色控制）
LANGFUSE_TRACE_LINKS_ENABLED = os.environ.get("LANGFUSE_TRACE_LINKS_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
# 轨迹调试模式：工具参数全量记值（默认仅白名单低敏参数记值，见 event_log.TOOL_ARG_VALUE_KEYS）
TRAJECTORY_DEBUG = os.environ.get("TRAJECTORY_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}

# 摘要模型（默认与对话模型相同）
LLM_SUMMARY_MODEL = LLM_CHAT_MODEL

# 标题模型
LLM_TITLE_MODEL = LLM_CHAT_MODEL

# 问题生成模型
LLM_QUESTION_MODEL = LLM_CHAT_MODEL

# 抽取模型
LLM_EXTRACT_MODEL = LLM_CHAT_MODEL

# Embedding 模型（可独立配置，默认 BGE-M3，1024 维）
LLM_EMBEDDING_CONFIG = _resolve_model_config("EMBEDDING", "BAAI/bge-m3", _DEFAULT_BASE_URL)
LLM_EMBEDDING_API_KEY = LLM_EMBEDDING_CONFIG["api_key"]
LLM_EMBEDDING_BASE_URL = LLM_EMBEDDING_CONFIG["base_url"]
LLM_EMBEDDING_MODEL = LLM_EMBEDDING_CONFIG["model"]
LLM_EMBEDDING_DIM = 1024

# Rerank 模型（可独立配置，默认 BGE-Reranker）
LLM_RERANK_CONFIG = _resolve_model_config("RERANK", "BAAI/bge-reranker-v2-m3", _DEFAULT_BASE_URL)
LLM_RERANK_API_KEY = LLM_RERANK_CONFIG["api_key"]
LLM_RERANK_BASE_URL = LLM_RERANK_CONFIG["base_url"]
LLM_RERANK_MODEL = LLM_RERANK_CONFIG["model"]

# VLM 视觉模型（可独立配置）
LLM_VLM_CONFIG = _resolve_model_config("VLM", "qwen-vl-plus", _DEFAULT_BASE_URL)
LLM_VLM_API_KEY = LLM_VLM_CONFIG["api_key"]
LLM_VLM_BASE_URL = LLM_VLM_CONFIG["base_url"]
LLM_VLM_MODEL = LLM_VLM_CONFIG["model"]

# 通用别名
LLM_API_KEY = LLM_CHAT_API_KEY
LLM_BASE_URL = LLM_CHAT_BASE_URL

# ── 其他配置 ─────────────────────────────────────────────────────
APP_EMBEDDING_DIM = int(os.environ.get("APP_EMBEDDING_DIM", "384"))
# ── 混合检索（FTS5 BM25 + BGE-M3 双路召回 + RRF + BGE-Reranker）─────
# 标准 Reciprocal Rank Fusion 平滑常数
SEARCH_RRF_K = int(os.environ.get("SEARCH_RRF_K", "60"))
# 各路召回候选数相对 top_k 的默认倍数与上限
SEARCH_KEYWORD_CANDIDATE_MULTIPLIER = int(os.environ.get("SEARCH_KEYWORD_CANDIDATE_MULTIPLIER", "4"))
SEARCH_VECTOR_CANDIDATE_MULTIPLIER = int(os.environ.get("SEARCH_VECTOR_CANDIDATE_MULTIPLIER", "4"))
SEARCH_RERANK_CANDIDATE_MULTIPLIER = int(os.environ.get("SEARCH_RERANK_CANDIDATE_MULTIPLIER", "2"))
SEARCH_MAX_CANDIDATES = int(os.environ.get("SEARCH_MAX_CANDIDATES", "200"))
# 向量重建任务每批重嵌入的 Chunk 数
VECTOR_REINDEX_BATCH_SIZE = int(os.environ.get("VECTOR_REINDEX_BATCH_SIZE", "32"))
APP_TASK_WORKERS = STARTUP_CONFIG["task_workers"]
APP_TASKS_SYNC = "test" in sys.argv
# 运行模式（W04 分层）：local=桌面/单机一体进程（默认，保持既有行为）；
# api=纯 API 副本（不启动任务执行与恢复线程）；worker=独立任务执行者；
# all-in-one=团队单机部署（API+后台）。非法值启动即失败，不静默回退。
APP_MODE = os.environ.get("APP_MODE", "local").strip().lower()
if APP_MODE not in {"local", "api", "worker", "all-in-one"}:
    raise ValueError(f"APP_MODE 无效: {APP_MODE!r}（可选 local/api/worker/all-in-one）")
RUN_TASK_BACKGROUND = APP_MODE in {"local", "worker", "all-in-one"}
LLM_CHAT_MODEL_TIMEOUT = STARTUP_CONFIG["model_timeout"]
LLM_MODEL_NUM_RETRIES = STARTUP_CONFIG["model_retries"]

NEO4J_ENABLE = env_bool("NEO4J_ENABLE", False)
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USERNAME = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = ""  # 连接密码仅从数据库读取

LLM_USE_ENV_CHAT = False
LLM_USE_ENV_SUMMARY = False
LLM_USE_ENV_TITLE = False
LLM_USE_ENV_QUESTION = False
LLM_USE_ENV_EXTRACT = False
LLM_USE_ENV_EMBEDDING = False
LLM_USE_ENV_RERANK = False
LLM_USE_ENV_VLM = False
DATA_UPLOAD_MAX_MEMORY_SIZE = 256 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 256 * 1024 * 1024

# ── CORS 配置 ─────────────────────────────────────────────────────
CORS_ALLOWED_ORIGINS = STARTUP_CONFIG["cors_origins"]
CORS_ALLOW_CREDENTIALS = True

# ── 日志配置 ─────────────────────────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": STARTUP_CONFIG["log_level"],
            "propagate": False,
        },
    },
}
