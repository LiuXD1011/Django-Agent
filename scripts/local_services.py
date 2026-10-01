"""Local development service startup. Never imported by Django app discovery."""
import json
import os
import subprocess
import time
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

from filelock import FileLock, Timeout

from config.runtime_paths import resolve_data_directory


def local_env(root):
    values = {}
    file = Path(root) / ".env"
    if file.exists():
        for raw in file.read_text().splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("\"'")
    values.update(os.environ)
    return values


def enabled(value):
    return str(value).lower().strip() in {"true", "1", "yes", "on"}


def langfuse_api_base(env):
    return (env.get("LANGFUSE_BASE_URL") or env.get("LANGFUSE_HOST") or "http://localhost:3000").rstrip("/")


def ensure_langfuse(root):
    """Bounded, lock-protected startup of this project's existing Compose stack."""
    root = Path(root).resolve()
    env = local_env(root)
    if not enabled(env.get("LANGFUSE_AUTOSTART", "true")):
        return {"state": "disabled"}
    from urllib.parse import urlsplit
    target = urlsplit(langfuse_api_base(env))
    if target.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return {"state": "external"}
    # 启动状态目录是运行写入 → 用户数据根：从已解析的 local_env 读
    # APP_DATA_DIR（未设置/空白回落 root 既有行为）；.env.langfuse 与
    # docker-compose.langfuse.yml 仍是源码根资源。
    directory = resolve_data_directory(root, env.get("APP_DATA_DIR")) / ".cache" / "langfuse"
    directory.mkdir(parents=True, exist_ok=True)
    state = {"state": "starting", "checked_at": time.time()}
    def finish(status):
        state["state"] = status
        temporary = directory / ("startup-%s.tmp" % os.getpid())
        temporary.write_text(json.dumps(state))
        temporary.replace(directory / "startup.json")
        print("[Langfuse] " + status, flush=True)
        return state
    try:
        seconds = min(max(float(env.get("LANGFUSE_STARTUP_TIMEOUT_SECONDS", 45)), 1), 120)
    except ValueError:
        seconds = 45
    deadline = time.monotonic() + seconds
    try:
        lock = FileLock(directory / "startup.lock")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return finish("startup_timeout")
        try:
            # Lock contention shares the same monotonic startup deadline. The
            # budget is never reset or extended: the raw remainder bounds the
            # wait, and every later step re-checks it before proceeding.
            lock.acquire(timeout=remaining)
        except Timeout:
            return finish("startup_timeout")
        try:
            if not (root / ".env.langfuse").is_file():
                return finish("missing_server_configuration")
            command = ["docker", "compose", "--env-file", str(root / ".env.langfuse"),
                       "-f", str(root / "docker-compose.langfuse.yml")]
            for args in [["config", "--quiet"], ["up", "-d"]]:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return finish("startup_timeout")
                result = subprocess.run(command + args, cwd=root, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, timeout=remaining)
                if result.returncode:
                    return finish("compose_failed")
            opener = build_opener(ProxyHandler({}))
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    with opener.open(target.geturl().rstrip("/") + "/api/public/health",
                                     timeout=min(2, remaining)) as response:
                        if response.status == 200:
                            return finish("healthy")
                except Exception:
                    pass
                time.sleep(min(.5, max(0, deadline - time.monotonic())))
            return finish("startup_timeout")
        finally:
            lock.release()
    except FileNotFoundError:
        return finish("docker_unavailable")
    except subprocess.TimeoutExpired:
        return finish("startup_timeout")
    except Exception:
        return finish("startup_failed")
