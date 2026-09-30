"""Langfuse 链路诊断命令。

用法（在业务 Python 环境执行）：
    python manage.py langfuse_check             # 离线：配置/版本/脱敏 endpoint/SDK 兼容
    python manage.py langfuse_check --network   # 联网：服务可达性 + 凭证鉴权（有时限）
    python manage.py langfuse_check --smoke     # 冒烟：合成 trace（真实 LLM 不调用）→ flush → 查询回读

退出码（非 0 即存在问题，不把缺配置/不可达当成功）：
    0 通过；1 总开关关闭；2 SDK 未安装；3 凭证缺失；4 客户端初始化失败；
    5 服务不可达；6 鉴权失败；7 smoke 数据未能在截止时间内回读/校验不符。

smoke 只创建带 test_run_id 的合成数据，不删除服务端任何数据，不改业务数据库；
诊断与查询不在聊天主流程执行。
"""
from __future__ import annotations

import base64
import math
from urllib.parse import urlsplit, urlunsplit
import os
import sys
import time
from datetime import datetime, timezone

from django.conf import settings
from django.core.management.base import BaseCommand

DIAG_STATES = (
    "disabled",           # 总开关关闭
    "sdk_missing",        # langfuse 未安装
    "missing_credentials",  # 公钥/私钥缺失
    "initialized",        # SDK 客户端构造成功（不等于服务端健康）
    "unreachable",        # 服务不可达
    "auth_failed",        # 鉴权失败
    "verified",           # smoke 已在服务端回读验证
)


class Command(BaseCommand):
    help = "Langfuse 配置/连通性/冒烟诊断（旁路，不影响业务）"

    def add_arguments(self, parser):
        parser.add_argument("--network", action="store_true", help="联网检查服务健康与凭证鉴权")
        parser.add_argument("--smoke", action="store_true", help="上传合成 trace 并回读验证（含 network 检查）")
        parser.add_argument(
            "--deadline",
            type=float,
            default=30.0,
            help="smoke 回读轮询截止秒数（默认 30，指数退避）",
        )

    def handle(self, *args, **options):
        want_network = bool(options["network"]) or bool(options["smoke"])
        want_smoke = bool(options["smoke"])
        deadline_s = float(options["deadline"])
        if not math.isfinite(deadline_s) or deadline_s <= 0:
            self._fail("--deadline 必须为有限正数", 7)

        self._section("Langfuse 配置诊断")
        state = self._check_config()
        if state in ("disabled", "sdk_missing", "missing_credentials"):
            sys.exit({
                "disabled": 1,
                "sdk_missing": 2,
                "missing_credentials": 3,
            }[state])

        from personal_knowledge_base.observability import get_langfuse, flush_langfuse
        client = get_langfuse()
        if client is None:
            self._fail("SDK 客户端初始化失败（见应用日志）", 4)

        self.stdout.write(self.style.SUCCESS("initialized: SDK 客户端构造成功（不代表服务端可达/入库）"))

        if want_network:
            self._section("联网诊断（有时限）")
            code = self._check_network()
            if code:
                sys.exit(code)

        if want_smoke:
            self._section("冒烟上传与回读")
            code = self._run_smoke(client, flush_langfuse, deadline_s)
            if code:
                sys.exit(code)

        self._section("结果")
        self.stdout.write(self.style.SUCCESS("PASS"))

    # ── 内部实现 ──────────────────────────────────────────────

    def _check_config(self) -> str:
        enabled = bool(getattr(settings, "LANGFUSE_ENABLED", False))
        public_key = str(getattr(settings, "LANGFUSE_PUBLIC_KEY", "") or "")
        secret_key = str(getattr(settings, "LANGFUSE_SECRET_KEY", "") or "")
        base_url = str(getattr(settings, "LANGFUSE_BASE_URL", "") or "")
        ui_url = str(getattr(settings, "LANGFUSE_UI_BASE_URL", "") or base_url)
        env_name = str(getattr(settings, "LANGFUSE_TRACING_ENVIRONMENT", "") or "")
        sample_rate = getattr(settings, "LANGFUSE_SAMPLE_RATE", 1.0)
        log_content = bool(getattr(settings, "LANGFUSE_LOG_CONTENT", False))

        self.stdout.write(f"LANGFUSE_ENABLED={enabled}")
        if not enabled:
            self.stdout.write(self.style.WARNING("disabled: 总开关关闭（关闭即不出网，属正常配置）"))
            return "disabled"
        # 秘密只报存在性，不回显
        self.stdout.write(f"LANGFUSE_PUBLIC_KEY set={bool(public_key)} (pk…{public_key[-4:] if public_key else ''})")
        self.stdout.write(f"LANGFUSE_SECRET_KEY set={bool(secret_key)}")
        self.stdout.write(f"LANGFUSE_BASE_URL={self._display_url(base_url)}")
        self.stdout.write(f"LANGFUSE_UI_BASE_URL={self._display_url(ui_url)}")
        self.stdout.write(f"LANGFUSE_TRACING_ENVIRONMENT={env_name}")
        self.stdout.write(f"LANGFUSE_SAMPLE_RATE={sample_rate}")
        self.stdout.write(f"LANGFUSE_LOG_CONTENT={log_content}（true 时仍经脱敏/截断）")
        self.stdout.write(f"OTLP 上报端点（脱敏）：{self._display_url(base_url)}/api/public/otel/v1/traces")

        try:
            import langfuse
            from importlib.metadata import version as _v
            self.stdout.write(f"langfuse SDK={_v('langfuse')}（要求固定 3.15.0）")
        except Exception:
            self.stdout.write(self.style.ERROR("sdk_missing: langfuse 未安装"))
            return "sdk_missing"
        if not public_key or not secret_key:
            self.stdout.write(self.style.ERROR("missing_credentials: 公钥/私钥未配置"))
            return "missing_credentials"
        return "initialized"

    def _check_network(self) -> int:
        """区分"可达"与"鉴权成功"。返回 0 / 5 / 6。"""
        base_url = str(getattr(settings, "LANGFUSE_BASE_URL", "") or "")
        public_key = str(getattr(settings, "LANGFUSE_PUBLIC_KEY", "") or "")
        secret_key = str(getattr(settings, "LANGFUSE_SECRET_KEY", "") or "")

        import httpx

        # 直连客户端：trust_env=False 避免本机代理/no_proxy 通配格式问题（见运维文档）
        with httpx.Client(trust_env=False, timeout=10.0, follow_redirects=False) as http:
            # 1) 健康端点（无需鉴权）
            try:
                resp = http.get(f"{base_url}/api/public/health")
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"unreachable: {type(exc).__name__}"))
                return 5
            if resp.status_code != 200:
                self.stdout.write(self.style.ERROR(f"unreachable: /api/public/health -> HTTP {resp.status_code}"))
                return 5
            self.stdout.write("health: HTTP 200（服务可达）")

            # 2) 鉴权检查（列出项目，需有效 key）
            auth = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
            try:
                resp = http.get(
                    f"{base_url}/api/public/projects",
                    headers={"Authorization": f"Basic {auth}"},
                )
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"unreachable (projects): {type(exc).__name__}"))
                return 5
            if resp.status_code in (401, 403):
                self.stdout.write(self.style.ERROR(f"auth_failed: /api/public/projects -> HTTP {resp.status_code}（key 无效或无权限）"))
                return 6
            if resp.status_code != 200:
                self.stdout.write(self.style.ERROR(f"auth check unexpected: HTTP {resp.status_code}"))
                return 5
            try:
                payload = resp.json()
                rows = payload.get("data", []) if isinstance(payload, dict) else payload
                self.stdout.write(f"auth: HTTP 200，可访问项目数 {len(rows)}")
            except Exception:
                self.stdout.write("auth: HTTP 200")
        return 0

    def _run_smoke(self, client, flush_fn, deadline_s: float) -> int:
        """合成 trace（根 + 子 span + 固定用量 generation）→ flush → 轮询回读校验。"""
        from personal_knowledge_base import observability as obs

        test_run_id = f"smoke-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{os.getpid()}"
        session_id = f"smoke-session-{test_run_id}"
        usage_in, usage_out = 42, 17

        root = obs.start_business_trace(
            "langfuse.smoke",
            session_id=session_id,
            user_id="langfuse_check",
            metadata={"test_run_id": test_run_id, "synthetic": True},
        )
        if root is None or not root.trace_id or not root.observation_id:
            self._fail("smoke 根 trace 创建失败", 7)
        trace_id = getattr(root, "trace_id", "") or ""
        root_obs_id = getattr(root, "observation_id", "") or getattr(root, "id", "")
        self.stdout.write(f"trace_id={trace_id}")
        self.stdout.write(f"root_observation_id={root_obs_id}")

        with obs.child_span("smoke.child", metadata={"test_run_id": test_run_id}) as child:
            child_obs_id = getattr(child, "id", "") if child else ""
            gen_obs_id = ""
            gen = None
            try:
                gen = root.start_observation(
                    as_type="generation",
                    name="smoke.generation",
                    model="smoke-model",
                    metadata={"test_run_id": test_run_id},
                    usage_details={"input": usage_in, "output": usage_out, "total": usage_in + usage_out},
                )
                gen_obs_id = getattr(gen, "id", "")
                gen.end()
            except Exception as exc:
                self._fail(f"smoke generation 创建失败：{type(exc).__name__}", 7)
        obs.close_business_trace(root, output={"status": "completed", "test_run_id": test_run_id})

        started = time.monotonic()
        try:
            flush_fn()
        except Exception:
            pass
        self.stdout.write(f"flush 完成，用时 {time.monotonic() - started:.2f}s；开始轮询回读（截止 {deadline_s}s）")

        # 回读查询走独立查询客户端（httpx 直连，有时限，不在聊天主流程）
        code = self._verify_remote(
            trace_id=trace_id,
            session_id=session_id,
            root_obs_id=root_obs_id,
            child_obs_id=child_obs_id,
            gen_obs_id=gen_obs_id,
            usage=(usage_in, usage_out),
            test_run_id=test_run_id,
            deadline_s=deadline_s,
        )
        if code == 0:
            self.stdout.write(f"请在配置的 Langfuse 项目中搜索 trace_id={trace_id}")
            self.stdout.write(f"清理提示：如需删除本次合成数据，可在 UI 按trace_id={trace_id}或 test_run_id={test_run_id} 过滤后删除。")
        return code

    def _verify_remote(
        self,
        *,
        trace_id: str,
        session_id: str,
        root_obs_id: str,
        child_obs_id: str,
        gen_obs_id: str,
        usage: tuple,
        test_run_id: str,
        deadline_s: float,
    ) -> int:
        from langfuse.api.client import FernLangfuse
        import httpx

        base_url = str(getattr(settings, "LANGFUSE_BASE_URL", "") or "")
        public_key = str(getattr(settings, "LANGFUSE_PUBLIC_KEY", "") or "")
        secret_key = str(getattr(settings, "LANGFUSE_SECRET_KEY", "") or "")
        if not all((trace_id, root_obs_id, child_obs_id, gen_obs_id)):
            self._fail("smoke 缺少必要的根/子/generation 标识", 7)
        if not math.isfinite(deadline_s) or deadline_s <= 0:
            self._fail("--deadline 必须为有限正数", 7)
        deadline = time.monotonic() + deadline_s
        backoff = 0.25
        problems = ["trace 尚未入库"]
        with httpx.Client(trust_env=False, timeout=min(10.0, deadline_s)) as http:
            api = FernLangfuse(
                base_url=base_url, username=public_key, password=secret_key, httpx_client=http,
            )
            while time.monotonic() < deadline:
                try:
                    trace = api.trace.get(trace_id, request_options={
                        "timeout_in_seconds": max(0.001, min(10.0, deadline - time.monotonic())),
                        "max_retries": 0,
                    })
                    problems = self._remote_problems(trace, trace_id, session_id, root_obs_id,
                                                     child_obs_id, gen_obs_id, usage)
                    if not problems:
                        self.stdout.write(self.style.SUCCESS(
                            f"verified：trace_id={trace_id} 根/子/generation 与用量均在服务端确认"))
                        return 0
                except Exception as exc:
                    if getattr(exc, "status_code", None) != 404:
                        self._fail(f"回读查询失败：{type(exc).__name__}", 7)
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    time.sleep(min(backoff, remaining))
                    backoff = min(backoff * 1.6, 3.0)
        for problem in problems:
            self.stdout.write(self.style.ERROR(f"校验失败：{problem}"))
        self._fail(f"截止 {deadline_s}s 内未完整回读 test_run_id={test_run_id}", 7)

    @staticmethod
    def _remote_problems(trace, trace_id, session_id, root_id, child_id, gen_id, usage):
        problems = []
        if str(getattr(trace, "id", "")) != trace_id:
            problems.append("trace_id 不符")
        if getattr(trace, "session_id", "") != session_id:
            problems.append("session_id 不符")
        by_id = {o.id: o for o in (getattr(trace, "observations", []) or [])}
        for oid, label, kind, parent in (
            (root_id, "root", "SPAN", None),
            (child_id, "child", "SPAN", root_id),
            (gen_id, "generation", "GENERATION", root_id),
        ):
            node = by_id.get(oid)
            if node is None:
                problems.append(f"{label} 尚未入库")
                continue
            if str(getattr(node, "type", "")).upper() != kind:
                problems.append(f"{label} 类型不符")
            if str(getattr(node, "trace_id", "")) != trace_id:
                problems.append(f"{label} trace_id 不符")
            if (getattr(node, "parent_observation_id", None) or None) != parent:
                problems.append(f"{label} 父级不符")
            if getattr(node, "end_time", None) is None:
                problems.append(f"{label} 尚未结束")
        gen = by_id.get(gen_id)
        if gen is not None:
            remote_usage = getattr(gen, "usage", None)
            if (getattr(remote_usage, "input", None), getattr(remote_usage, "output", None)) != usage:
                problems.append("generation 用量不符")
        return problems

    @staticmethod
    def _display_url(value):
        try:
            parsed = urlsplit(value)
            # Diagnostic output never prints userinfo, query, fragment, or arbitrary paths.
            host = parsed.hostname or ""
            if ":" in host:
                host = "[" + host + "]"
            port = f":{parsed.port}" if parsed.port else ""
            return urlunsplit((parsed.scheme, host + port, "", "", ""))
        except ValueError:
            return "<invalid endpoint>"

    def _section(self, title: str):
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(f"── {title} " + "─" * max(0, 40 - len(title))))

    def _fail(self, msg: str, code: int):
        self.stdout.write(self.style.ERROR(msg))
        sys.exit(code)
