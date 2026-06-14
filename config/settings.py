import os
import sys
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR / ".env.local", override=True)

TESTING = "test" in sys.argv


def env(name, default="", required=False):
    value = os.getenv(name, default)
    if required and not TESTING and value in ("", None):
        raise ImproperlyConfigured(f"Missing required environment variable: {name}")
    return value


def env_bool(name, default=False):
    return str(os.getenv(name, "1" if default else "0")).strip().lower() in {"1", "true", "yes", "on"}


def env_int(name, default):
    return int(os.getenv(name, str(default)))

SECRET_KEY = env("DJANGO_SECRET_KEY", "test-secret-key" if TESTING else "", required=not TESTING)
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [host.strip() for host in env("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if host.strip()]


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'accounts',
    'drive',
    'assistant.apps.AssistantConfig',
    'knowledge.apps.KnowledgeConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': env("SQLITE_DATABASE_PATH", str(BASE_DIR / "db.sqlite3")),
    }
}


AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


LANGUAGE_CODE = 'zh-hans'

TIME_ZONE = 'Asia/Shanghai'

USE_I18N = True

USE_TZ = True


AUTH_USER_MODEL = 'accounts.User'
LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'drive:file_list'
LOGOUT_REDIRECT_URL = 'home'

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "local-cache",
    }
}
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

DEFAULT_STORAGE_QUOTA_BYTES = env_int("DEFAULT_STORAGE_QUOTA_BYTES", 10 * 1024 * 1024 * 1024)
FILE_UPLOAD_MAX_MEMORY_SIZE = env_int("FILE_UPLOAD_MAX_MEMORY_SIZE", 20 * 1024 * 1024)
DATA_UPLOAD_MAX_MEMORY_SIZE = env_int("DATA_UPLOAD_MAX_MEMORY_SIZE", 120 * 1024 * 1024)

LLM_BASE_URL = env("LLM_BASE_URL", "https://api.deepseek.com")
LLM_API_KEY = env("LLM_API_KEY", "")
LLM_MODEL = env("LLM_MODEL", "deepseek-chat")
EMBEDDING_BASE_URL = env("EMBEDDING_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
EMBEDDING_API_KEY = env("EMBEDDING_API_KEY", "")
EMBEDDING_MODEL = env("EMBEDDING_MODEL", "text-embedding-v4")
EMBEDDING_VECTOR_DIM = env_int("EMBEDDING_VECTOR_DIM", 96)
RERANK_MODEL = env("RERANK_MODEL", "qwen3-vl-rerank")
RERANK_BASE_URL = env(
    "RERANK_BASE_URL",
    "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
)
RERANK_API_KEY = env("RERANK_API_KEY", EMBEDDING_API_KEY)
VISION_BASE_URL = env("VISION_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
VISION_MODEL = env("VISION_MODEL", "qwen3.5-flash")
VISION_API_KEY = env("VISION_API_KEY", "")
VISION_MAX_PDF_PAGES = env_int("VISION_MAX_PDF_PAGES", 5)
VISION_IMAGE_DPI = env_int("VISION_IMAGE_DPI", 144)
VISION_PARSE_MAX_TOKENS = env_int("VISION_PARSE_MAX_TOKENS", 2048)
LIBREOFFICE_BINARY = env("LIBREOFFICE_BINARY", "soffice")
DOCUMENT_CONVERSION_TIMEOUT_SECONDS = env_int("DOCUMENT_CONVERSION_TIMEOUT_SECONDS", 60)
DOCUMENT_CONVERSION_MAX_MB = env_int("DOCUMENT_CONVERSION_MAX_MB", 50)
OFFICE_MIN_TOTAL_TEXT_CHARS = env_int("OFFICE_MIN_TOTAL_TEXT_CHARS", 200)
OFFICE_MIN_AVG_ENTRY_TEXT_CHARS = env_int("OFFICE_MIN_AVG_ENTRY_TEXT_CHARS", 30)
ARCHIVE_MAX_FILES = env_int("ARCHIVE_MAX_FILES", 20)
ARCHIVE_MAX_TOTAL_BYTES = env_int("ARCHIVE_MAX_TOTAL_BYTES", 20 * 1024 * 1024)
ARCHIVE_MAX_SINGLE_FILE_BYTES = env_int("ARCHIVE_MAX_SINGLE_FILE_BYTES", 10 * 1024 * 1024)
ASSISTANT_MEMORY_AUTO_ENABLED = env_bool("ASSISTANT_MEMORY_AUTO_ENABLED", not TESTING)

SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False


DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
