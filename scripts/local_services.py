"""Local development service startup. Never imported by Django app discovery."""
import json
import os
import subprocess
import time
from pathlib import Path
from urllib.request import ProxyHandler, build_opener


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
    directory = root / ".cache" / "langfuse"
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
        import fcntl
        with (directory / "startup.lock").open("a") as lock:
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        return finish("startup_timeout")
                    time.sleep(.2)
            if not (root / ".env.langfuse").is_file():
                return finish("missing_server_configuration")
            command = ["docker", "compose", "--env-file", str(root / ".env.langfuse"),
                       "-f", str(root / "docker-compose.langfuse.yml")]
            for args in [["config", "--quiet"], ["up", "-d"]]:
                result = subprocess.run(command + args, cwd=root, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, timeout=max(.1, deadline-time.monotonic()))
                if result.returncode:
                    return finish("compose_failed")
            opener = build_opener(ProxyHandler({}))
            while time.monotonic() < deadline:
                try:
                    with opener.open(target.geturl().rstrip("/") + "/api/public/health",
                                     timeout=max(.1, min(2, deadline-time.monotonic()))) as response:
                        if response.status == 200:
                            return finish("healthy")
                except Exception:
                    pass
                time.sleep(min(.5, max(0, deadline-time.monotonic())))
            return finish("startup_timeout")
    except FileNotFoundError:
        return finish("docker_unavailable")
    except subprocess.TimeoutExpired:
        return finish("startup_timeout")
    except Exception:
        return finish("startup_failed")
