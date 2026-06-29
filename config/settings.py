import os
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


SECRET_KEY = "personal-knowledge-base-dev-secret"
DEBUG = True
ALLOWED_HOSTS = ["*"]
APP_NAME = os.environ.get("APP_NAME", "个人轻量知识库")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "rest_framework",
    "personal_knowledge_base",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
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

WEKNORA_EMBEDDING_DIM = int(os.environ.get("WEKNORA_EMBEDDING_DIM", "384"))
WEKNORA_TASK_WORKERS = 4
WEKNORA_TASKS_SYNC = "test" in sys.argv
WEKNORA_CHAT_MODEL_TIMEOUT = int(os.environ.get("WEKNORA_CHAT_MODEL_TIMEOUT", "60"))
ALIYUN_BAILIAN_BASE_URL = os.environ.get("ALIYUN_BAILIAN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")

ALIYUN_BAILIAN_CHAT_MODEL = os.environ.get("ALIYUN_BAILIAN_CHAT_MODEL", "qwen3.6-flash")
ALIYUN_BAILIAN_SUMMARY_MODEL = os.environ.get("ALIYUN_BAILIAN_SUMMARY_MODEL", "qwen3.6-flash")
ALIYUN_BAILIAN_TITLE_MODEL = os.environ.get("ALIYUN_BAILIAN_TITLE_MODEL", "qwen3.6-flash")
ALIYUN_BAILIAN_QUESTION_MODEL = os.environ.get("ALIYUN_BAILIAN_QUESTION_MODEL", "qwen3.6-flash")
ALIYUN_BAILIAN_EXTRACT_MODEL = os.environ.get("ALIYUN_BAILIAN_EXTRACT_MODEL", "qwen3.6-flash")
ALIYUN_BAILIAN_EMBEDDING_MODEL = os.environ.get("ALIYUN_BAILIAN_EMBEDDING_MODEL", "text-embedding-v4")
ALIYUN_BAILIAN_EMBEDDING_DIM = int(os.environ.get("ALIYUN_BAILIAN_EMBEDDING_DIM", "1024"))
ALIYUN_BAILIAN_RERANK_MODEL = os.environ.get("ALIYUN_BAILIAN_RERANK_MODEL", "qwen3-rerank")
ALIYUN_BAILIAN_VLM_MODEL = os.environ.get("ALIYUN_BAILIAN_VLM_MODEL", "qwen-vl-plus")
ALIYUN_BAILIAN_ASR_MODEL = os.environ.get("ALIYUN_BAILIAN_ASR_MODEL", "paraformer-v2")
ALIYUN_BAILIAN_ASR_URL = os.environ.get("ALIYUN_BAILIAN_ASR_URL", f"{ALIYUN_BAILIAN_BASE_URL.rstrip('/')}/audio/transcriptions")
NEO4J_ENABLE = env_bool("NEO4J_ENABLE", False)
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USERNAME = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "password")

WEKNORA_USE_BAILIAN_CHAT = env_bool("WEKNORA_USE_BAILIAN_CHAT", True)
WEKNORA_USE_BAILIAN_SUMMARY = env_bool("WEKNORA_USE_BAILIAN_SUMMARY", True)
WEKNORA_USE_BAILIAN_TITLE = env_bool("WEKNORA_USE_BAILIAN_TITLE", True)
WEKNORA_USE_BAILIAN_QUESTION = env_bool("WEKNORA_USE_BAILIAN_QUESTION", True)
WEKNORA_USE_BAILIAN_EXTRACT = env_bool("WEKNORA_USE_BAILIAN_EXTRACT", True)
WEKNORA_USE_BAILIAN_EMBEDDING = env_bool("WEKNORA_USE_BAILIAN_EMBEDDING", False)
WEKNORA_USE_BAILIAN_RERANK = env_bool("WEKNORA_USE_BAILIAN_RERANK", True)
WEKNORA_USE_BAILIAN_VLM = env_bool("WEKNORA_USE_BAILIAN_VLM", True)
WEKNORA_USE_BAILIAN_ASR = env_bool("WEKNORA_USE_BAILIAN_ASR", True)
DATA_UPLOAD_MAX_MEMORY_SIZE = 256 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 256 * 1024 * 1024
