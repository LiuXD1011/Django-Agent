import os
import secrets
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def load_dotenv(path):
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv(BASE_DIR / ".env")

def env_bool(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


# ── 安全配置 ─────────────────────────────────────────────────────
# SECRET_KEY: 生产环境必须从环境变量读取
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if env_bool("DJANGO_DEBUG", True):
        # 开发环境使用临时密钥
        SECRET_KEY = "dev-" + secrets.token_urlsafe(32)
    else:
        raise ValueError("DJANGO_SECRET_KEY environment variable is required in production")

# DEBUG: 生产环境必须设为 False
DEBUG = env_bool("DJANGO_DEBUG", True)

# 首次管理员初始化必须由部署环境显式开启
ALLOW_AUTO_SETUP = env_bool("ALLOW_AUTO_SETUP", False)

# ALLOWED_HOSTS: 生产环境必须限制
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]

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

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {
            "timeout": 30,  # 等待锁的超时时间（秒）
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA busy_timeout=30000; PRAGMA synchronous=NORMAL;",
        },
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "Asia/Shanghai"
LANGUAGE_CODE = "zh-hans"

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "frontend" / "dist" / "assets"] if (BASE_DIR / "frontend" / "dist" / "assets").exists() else []

MEDIA_URL = "/files/"
MEDIA_ROOT = BASE_DIR / "media"
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
    解析单个模型的配置，支持独立的 API Key 和 Base URL。
    优先级：模型专用配置 > 通用 LLM_* 配置 > 默认值
    """
    # 模型专用配置（如 LLM_CHAT_API_KEY, LLM_EMBEDDING_BASE_URL）
    api_key = os.environ.get(f"LLM_{model_type}_API_KEY") or os.environ.get("LLM_API_KEY", default_api_key)
    base_url = os.environ.get(f"LLM_{model_type}_BASE_URL") or os.environ.get("LLM_BASE_URL", default_base_url)
    model = os.environ.get(f"LLM_{model_type}_MODEL", default_model)

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

# 摘要模型（默认与对话模型相同）
LLM_SUMMARY_MODEL = os.environ.get("LLM_SUMMARY_MODEL") or LLM_CHAT_MODEL

# 标题模型
LLM_TITLE_MODEL = os.environ.get("LLM_TITLE_MODEL") or LLM_CHAT_MODEL

# 问题生成模型
LLM_QUESTION_MODEL = os.environ.get("LLM_QUESTION_MODEL") or LLM_CHAT_MODEL

# 抽取模型
LLM_EXTRACT_MODEL = os.environ.get("LLM_EXTRACT_MODEL") or LLM_CHAT_MODEL

# Embedding 模型（可独立配置，默认 BGE-M3，1024 维）
LLM_EMBEDDING_CONFIG = _resolve_model_config("EMBEDDING", "BAAI/bge-m3", _DEFAULT_BASE_URL)
LLM_EMBEDDING_API_KEY = LLM_EMBEDDING_CONFIG["api_key"]
LLM_EMBEDDING_BASE_URL = LLM_EMBEDDING_CONFIG["base_url"]
LLM_EMBEDDING_MODEL = LLM_EMBEDDING_CONFIG["model"]
LLM_EMBEDDING_DIM = int(os.environ.get("LLM_EMBEDDING_DIM", "1024"))

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
APP_TASK_WORKERS = 4
APP_TASKS_SYNC = "test" in sys.argv
LLM_CHAT_MODEL_TIMEOUT = int(os.environ.get("LLM_CHAT_MODEL_TIMEOUT", "60"))

NEO4J_ENABLE = env_bool("NEO4J_ENABLE", False)
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USERNAME = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "password")

LLM_USE_ENV_CHAT = env_bool("LLM_USE_ENV_CHAT", True)
LLM_USE_ENV_SUMMARY = env_bool("LLM_USE_ENV_SUMMARY", True)
LLM_USE_ENV_TITLE = env_bool("LLM_USE_ENV_TITLE", True)
LLM_USE_ENV_QUESTION = env_bool("LLM_USE_ENV_QUESTION", True)
LLM_USE_ENV_EXTRACT = env_bool("LLM_USE_ENV_EXTRACT", True)
LLM_USE_ENV_EMBEDDING = env_bool("LLM_USE_ENV_EMBEDDING", False)
LLM_USE_ENV_RERANK = env_bool("LLM_USE_ENV_RERANK", True)
LLM_USE_ENV_VLM = env_bool("LLM_USE_ENV_VLM", True)
DATA_UPLOAD_MAX_MEMORY_SIZE = 256 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 256 * 1024 * 1024

# ── CORS 配置 ─────────────────────────────────────────────────────
CORS_ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
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
            "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
    },
}
