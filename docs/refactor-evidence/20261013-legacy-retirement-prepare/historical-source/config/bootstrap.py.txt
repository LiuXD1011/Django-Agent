"""Startup-only configuration: independent of Django and the application database."""
import json
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from filelock import FileLock, Timeout

DEFAULTS = {
    "debug": False,
    "allowed_hosts": ["localhost", "127.0.0.1", "[::1]"],
    "cors_origins": ["http://localhost:5173"],
    "task_workers": 4,
    "sqlite_timeout": 30,
    "log_level": "INFO",
    "model_timeout": 60,
    "model_retries": 2,
    "no_proxy": "localhost,127.0.0.1,::1",
    "proxy_url": "",
}
ENV_FIELDS = {
    "DJANGO_DEBUG": "debug", "DJANGO_ALLOWED_HOSTS": "allowed_hosts",
    "CORS_ALLOWED_ORIGINS": "cors_origins", "APP_TASK_WORKERS": "task_workers",
    "SQLITE_TIMEOUT": "sqlite_timeout", "DJANGO_LOG_LEVEL": "log_level",
    "LLM_CHAT_MODEL_TIMEOUT": "model_timeout", "LLM_MODEL_NUM_RETRIES": "model_retries",
    "NO_PROXY": "no_proxy", "APP_PROXY_URL": "proxy_url",
}


def validate(values):
    if not isinstance(values, dict) or set(values) - set(DEFAULTS):
        raise ValueError("未知启动配置字段")
    result = dict(DEFAULTS)
    result.update(values)
    for key, value in result.items():
        expected = type(DEFAULTS[key])
        if type(value) is not expected:
            raise ValueError(f"{key} 类型错误")
    for key, minimum, maximum in (
        ("task_workers", 2, 32), ("sqlite_timeout", 1, 300),
        ("model_timeout", 1, 600), ("model_retries", 0, 10),
    ):
        if not minimum <= result[key] <= maximum:
            raise ValueError(f"{key} 需要在 {minimum} 到 {maximum} 之间")
    if result["log_level"] not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError("日志级别错误")
    for key in ("allowed_hosts", "cors_origins"):
        if not all(isinstance(item, str) and item.strip() for item in result[key]):
            raise ValueError(f"{key} 需要非空字符串列表")
    if not result["allowed_hosts"] or "*" in result["allowed_hosts"]:
        raise ValueError("请明确指定允许的主机")
    for value in result["cors_origins"] + ([result["proxy_url"]] if result["proxy_url"] else []):
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or parsed.path not in {"", "/"}
                or any(char.isspace() for char in value)):
            raise ValueError("需要不含凭据和路径的 HTTP(S) 地址")
        parsed.port
    return result


def startup_path(root):
    return Path(root) / ".settings" / "startup.json"


def read_startup(root):
    path = startup_path(root)
    return validate(json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {})


def effective_startup(root, environ=None):
    values = read_startup(root)
    env = os.environ if environ is None else environ
    for name, field in ENV_FIELDS.items():
        if name not in env:
            continue
        raw = env[name]
        default = DEFAULTS[field]
        if isinstance(default, bool):
            raw = raw.strip().lower()
            if raw not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
                raise ValueError(f"{name} 需要布尔值")
            value = raw in {"true", "1", "yes", "on"}
        elif isinstance(default, int):
            value = int(raw)
        elif isinstance(default, list):
            value = [item.strip() for item in raw.split(",") if item.strip()]
        else:
            value = raw
        values[field] = value
    return validate(values)


def write_startup(root, values):
    values = validate(values)
    path = startup_path(root)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    with FileLock(str(path.with_suffix(".lock"))):
        temporary = path.with_name(f"startup-{os.getpid()}.tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(values, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    return values


def update_startup(root, changes):
    if not isinstance(changes, dict) or set(changes) - set(DEFAULTS):
        raise ValueError("未知启动配置字段")
    path = startup_path(root)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    # One lock covers the read/merge/write so concurrent administrators keep unrelated fields.
    with FileLock(str(path.with_suffix(".update.lock"))):
        return write_startup(root, {**read_startup(root), **changes})


def _load_or_create_key(path):
    if not path.is_file():
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(secrets.token_urlsafe(64))
                stream.flush()
                os.fsync(stream.fileno())
    value = path.read_text(encoding="utf-8").strip()
    if len(value) < 32:
        raise ValueError("Django 密钥文件损坏，请恢复原文件")
    return value


def persistent_secret(root, supplied=None):
    if supplied:
        return supplied
    directory = Path(root) / ".secrets"
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    path = directory / "django.key"
    try:
        with FileLock(str(directory / "django.lock"), timeout=10):
            return _load_or_create_key(path)
    except Timeout:
        # 软锁环境（fcntl 不可用）或争持超时不能阻塞 settings 导入；
        # O_EXCL 原子创建仍保证并发进程各自得到同一个密钥。
        return _load_or_create_key(path)


def read_legacy_config(path):
    """Only explicit migration callers use this parser; boot never invokes it."""
    values = {}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values
