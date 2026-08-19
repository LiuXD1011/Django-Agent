#!/usr/bin/env python
import json
import os
import sys
import time
import unittest
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse
from unittest.mock import patch
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

import django  # noqa: E402

django.setup()

from django.contrib.staticfiles.testing import StaticLiveServerTestCase  # noqa: E402
from django.conf import settings  # noqa: E402
from django.test import override_settings  # noqa: E402
from django.test.runner import DiscoverRunner  # noqa: E402
from django.test.utils import setup_test_environment, teardown_test_environment  # noqa: E402


REPORT_PATH = PROJECT_ROOT / "tests" / "frontend_playwright_e2e_report.md"
SCREENSHOT_DIR = Path("/tmp")
PLAYWRIGHT_TEST_DATABASE = Path("/tmp/django-agent-playwright.sqlite3")

CASE_DEFINITIONS = {
    "test_platform_knowledge_and_settings_pages_render": "真实浏览器打开知识库页与模型设置页，验证核心 UI 能渲染。",
    "test_chat_page_streams_fake_agent_answer": "真实浏览器验证终态 Actor Markdown 折叠/展开与失败工具详情，并记录桌面和移动端运行指标。",
    "test_chat_recovery_attempt_for_unfinished_message": "真实浏览器加载未完成 assistant 消息，验证 continue-stream 恢复流程是否可执行。",
    "test_knowledge_reads_require_authentication_and_tenant_membership": "LiveServer 请求验证知识库详情的未认证 401 与跨租户 404 边界。",
}

CASE_RESULTS: dict[str, dict] = {}
CASE_EVIDENCE: dict[str, dict] = {}


@contextmanager
def allow_unsafe_sync_for_playwright_shutdown():
    old_value = os.environ.get("DJANGO_ALLOW_ASYNC_UNSAFE")
    os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
    try:
        yield
    finally:
        if old_value is None:
            os.environ.pop("DJANGO_ALLOW_ASYNC_UNSAFE", None)
        else:
            os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = old_value


def _case_name(test):
    return getattr(test, "_testMethodName", str(test))


def _json_preview(value, max_len=520):
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        text = str(value)
    return text if len(text) <= max_len else text[:max_len] + "..."


def fake_rag_pipeline(tenant, query, kb_ids, session=None, user=None, enable_memory=True, model_id=""):
    return SimpleNamespace(
        query=query,
        search_query=f"rewrite:{query}",
        intent="kb_search",
        refs=[
            {
                "knowledge_id": "doc-playwright",
                "knowledge_title": "浏览器联动文档",
                "knowledge_description": "Playwright 测试引用",
                "content": "浏览器联动测试片段。",
                "score": 0.92,
            }
        ],
        memory_context="",
        chat_history_context="",
        kb_names="当前知识库：\n- 浏览器测试知识库",
        system_prompt="系统提示：浏览器联动测试。",
        user_prompt=f"<context>浏览器联动测试片段。</context>\n\n<user_question>{query}</user_question>",
    )


class EvidenceResult(unittest.TextTestResult):
    def startTest(self, test):
        CASE_RESULTS[_case_name(test)] = {"started_at": time.time()}
        super().startTest(test)

    def _store(self, test, status, err=None):
        name = _case_name(test)
        started = CASE_RESULTS.get(name, {}).get("started_at", time.time())
        detail = self._exc_info_to_string(err, test) if err else ""
        CASE_RESULTS[name] = {
            **CASE_RESULTS.get(name, {}),
            "status": status,
            "duration_ms": int((time.time() - started) * 1000),
            "detail": detail,
        }

    def addSuccess(self, test):
        self._store(test, "PASS")
        super().addSuccess(test)

    def addFailure(self, test, err):
        self._store(test, "FAIL", err)
        super().addFailure(test, err)

    def addError(self, test, err):
        self._store(test, "ERROR", err)
        super().addError(test, err)

    def addSkip(self, test, reason):
        CASE_RESULTS[_case_name(test)] = {"status": "SKIP", "duration_ms": 0, "detail": reason}
        super().addSkip(test, reason)


class EvidenceRunner(unittest.TextTestRunner):
    resultclass = EvidenceResult


@override_settings(
    DEBUG=False,
    ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1", "*"],
    STATIC_URL="/static/",
    LLM_CHAT_API_KEY="",
    LLM_USE_ENV_CHAT=False,
    LLM_USE_ENV_SUMMARY=False,
    LLM_USE_ENV_TITLE=False,
    LLM_USE_ENV_QUESTION=False,
    LLM_USE_ENV_EXTRACT=False,
    LLM_USE_ENV_EMBEDDING=False,
    LLM_USE_ENV_RERANK=False,
    LLM_USE_ENV_VLM=False,
    LLM_USE_ENV_ASR=False,
)
class FrontendPlaywrightE2ETests(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:  # pragma: no cover - environment-dependent
            raise unittest.SkipTest(f"Python Playwright 未安装：{exc}") from exc
        cls._playwright = sync_playwright().start()
        cls._browser = cls._playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        try:
            cls._browser.close()
            cls._playwright.stop()
        finally:
            super().tearDownClass()

    def setUp(self):
        from personal_knowledge_base.authentication import hash_password, issue_tokens
        from personal_knowledge_base.models import KnowledgeBase, ModelConfig, Tenant, TenantMember, User

        unique = uuid4().hex[:10]
        self.tenant = Tenant.objects.create(name=f"browser-test-{unique}", api_key=f"browser-key-{unique}")
        self.user = User.objects.create(
            username=f"browser_user_{unique}",
            email=f"browser_user_{unique}@example.test",
            password_hash=hash_password("test-password"),
            tenant=self.tenant,
            preferences={"enable_memory": False},
        )
        TenantMember.objects.create(user=self.user, tenant=self.tenant, role="owner")
        self.token, _refresh = issue_tokens(self.user)
        self.kb = KnowledgeBase.objects.create(
            tenant=self.tenant,
            name="浏览器测试知识库",
            description="Playwright E2E seed",
            creator_id=self.user.id,
        )
        ModelConfig.objects.create(
            id=f"chat-browser-{unique}",
            tenant=self.tenant,
            name="browser-chat-model",
            display_name="浏览器测试模型",
            type="chat",
            source="test",
            is_default=True,
        )
        self.console_messages: list[str] = []
        self.failed_requests: list[str] = []
        self.non_2xx_api_responses: list[dict[str, object]] = []
        self.context = self._browser.new_context(
            viewport={"width": 1440, "height": 960},
            extra_http_headers={"Authorization": f"Bearer {self.token}", "X-Tenant-ID": str(self.tenant.id)},
        )
        self.context.route("**/assets/**", self._serve_frontend_asset)
        self.context.route("**/api/v1/tenants/kv/**", self._serve_empty_tenant_config)
        auth_payload = {
            "token": self.token,
            "tenant": {"id": self.tenant.id, "name": self.tenant.name},
            "user": {"id": self.user.id, "username": self.user.username, "email": self.user.email},
        }
        self.context.add_init_script(
            f"""(() => {{
              const {{token, tenant, user}} = {json.dumps(auth_payload, ensure_ascii=False)};
              localStorage.setItem('personal_kb_token', token);
              localStorage.setItem('personal_kb_tenant', JSON.stringify(tenant));
              localStorage.setItem('personal_kb_user', JSON.stringify(user));
              localStorage.setItem('personal_kb_selected_tenant_id', String(tenant.id));
            }})()""",
        )
        self.page = self.context.new_page()
        self.page.on("console", lambda msg: self.console_messages.append(f"{msg.type}: {msg.text}"))
        self.page.on("pageerror", lambda exc: self.console_messages.append(f"pageerror: {exc}"))
        self.page.on("requestfailed", self._record_failed_request)
        self.page.on("response", self._record_non_2xx_api_response)
        self.patchers = [
            patch("chat.views.index_qa_to_kb_async"),
            patch("chat.views.refresh_context_snapshot_async"),
            patch("chat.views.is_memory_available", return_value=False),
            patch("chat.views.role_completion", return_value="浏览器测试标题"),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _serve_frontend_asset(self, route):
        rel_path = urlparse(route.request.url).path.lstrip("/")
        asset_path = PROJECT_ROOT / "frontend" / "dist" / rel_path
        if not asset_path.exists():
            route.fallback()
            return
        content_type = {
            ".js": "text/javascript",
            ".css": "text/css",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".woff": "font/woff",
            ".woff2": "font/woff2",
        }.get(asset_path.suffix.lower(), "application/octet-stream")
        route.fulfill(path=str(asset_path), content_type=content_type)

    def _serve_empty_tenant_config(self, route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"success": True, "message": "success", "data": {"value": {}}}),
        )

    def tearDown(self):
        self.context.close()

    def record(self, **data):
        CASE_EVIDENCE.setdefault(self._testMethodName, {}).update(data)

    def screenshot(self, name: str):
        path = SCREENSHOT_DIR / f"django-agent-{name}.png"
        self.page.screenshot(path=str(path), full_page=True)
        return str(path)

    def _record_failed_request(self, request):
        self.failed_requests.append(f"{request.method} {urlparse(request.url).path}: {request.failure}")

    def _record_non_2xx_api_response(self, response):
        path = urlparse(response.url).path
        if path.startswith("/api/") and not 200 <= response.status < 300:
            self.non_2xx_api_responses.append({"status": response.status, "path": path})

    def page_metrics(self, label: str):
        metrics = self.page.evaluate(
            """() => ({
              viewport_width: window.innerWidth,
              document_scroll_width: document.documentElement.scrollWidth,
              document_client_width: document.documentElement.clientWidth,
              body_scroll_width: document.body.scrollWidth,
              body_client_width: document.body.clientWidth,
            })"""
        )
        metrics.update(
            {
                "label": label,
                "has_document_overflow": metrics["document_scroll_width"] > metrics["document_client_width"],
                "has_body_overflow": metrics["body_scroll_width"] > metrics["body_client_width"],
                "console_errors": [
                    message
                    for message in self.console_messages
                    if "error" in message.lower() or "pageerror" in message.lower()
                ],
                "failed_requests": list(self.failed_requests),
                "non_2xx_api_responses": list(self.non_2xx_api_responses),
            }
        )
        return metrics

    def goto_and_wait(self, path: str):
        self.page.goto(f"{self.live_server_url}{path}", wait_until="networkidle", timeout=30000)

    def test_platform_knowledge_and_settings_pages_render(self):
        self.goto_and_wait("/platform/knowledge-bases")
        self.page.get_by_text("知识库", exact=True).first.wait_for(timeout=10000)
        self.page.locator(".kb-card h3", has_text="浏览器测试知识库").wait_for(timeout=10000)
        kb_text = self.page.locator("body").inner_text(timeout=10000)
        kb_screenshot = self.screenshot("knowledge_bases_page")

        self.goto_and_wait("/platform/settings?section=models")
        self.page.get_by_text("模型").first.wait_for(timeout=10000)
        settings_text = self.page.locator("body").inner_text(timeout=10000)
        settings_screenshot = self.screenshot("settings_models_page")
        desktop_metrics = self.page_metrics("desktop-1440")
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.wait_for_timeout(250)
        mobile_metrics = self.page_metrics("mobile-390")
        self.record(
            kb_url=self.page.url,
            kb_screenshot=kb_screenshot,
            settings_screenshot=settings_screenshot,
            has_cache_words=[word for word in ["缓存", "对话", "Embedding", "ReRank", "视觉"] if word in settings_text],
            desktop_metrics=desktop_metrics,
            mobile_metrics=mobile_metrics,
            console_tail=self.console_messages[-8:],
        )
        self.assertIn("浏览器测试知识库", kb_text)
        for word in ["主题", "字体大小", "空间与 API"]:
            self.assertNotIn(word, settings_text)
        for metrics in [desktop_metrics, mobile_metrics]:
            self.assertFalse(metrics["has_document_overflow"], metrics)
            self.assertFalse(metrics["has_body_overflow"], metrics)
            self.assertEqual(metrics["console_errors"], [], metrics)
            self.assertEqual(metrics["failed_requests"], [], metrics)
            self.assertEqual(metrics["non_2xx_api_responses"], [], metrics)

    def test_knowledge_reads_require_authentication_and_tenant_membership(self):
        from personal_knowledge_base.models import KnowledgeBase, Tenant

        foreign_tenant = Tenant.objects.create(name=f"foreign-{uuid4().hex[:10]}", api_key=f"foreign-key-{uuid4().hex[:10]}")
        foreign_kb = KnowledgeBase.objects.create(
            tenant=foreign_tenant,
            name="跨租户知识库",
            description="must not be readable",
        )
        url = f"{self.live_server_url}/api/v1/knowledge-bases/{foreign_kb.id}"
        unauthenticated = self._browser.new_context()
        authenticated = self._browser.new_context(
            extra_http_headers={"Authorization": f"Bearer {self.token}", "X-Tenant-ID": str(self.tenant.id)}
        )
        try:
            unauthenticated_response = unauthenticated.request.get(url)
            cross_tenant_response = authenticated.request.get(url)
        finally:
            unauthenticated.close()
            authenticated.close()

        self.record(
            unauthenticated_status=unauthenticated_response.status,
            cross_tenant_status=cross_tenant_response.status,
            endpoint=urlparse(url).path,
        )
        self.assertEqual(unauthenticated_response.status, 401)
        self.assertEqual(cross_tenant_response.status, 404)

    def test_chat_page_streams_fake_agent_answer(self):
        from personal_knowledge_base.agent_engine import AgentResult, AgentStep
        from personal_knowledge_base.models import AgentActor, Session

        session = Session.objects.create(
            tenant=self.tenant,
            user_id=self.user.id,
            title="浏览器联动会话",
            knowledge_base_id=self.kb.id,
            agent_config={"knowledge_base_ids": [self.kb.id]},
        )

        class FakeAgentEngine:
            def __init__(self, *args, **kwargs):
                self.config = kwargs.get("agent_config", {})
                self.session_id = kwargs.get("session_id")

            def execute(self, query, history=None, context_str="", on_event=None):
                parent_message_id = self.config.get("parent_message_id", "")
                if parent_message_id:
                    AgentActor.objects.create(
                        session_id=self.session_id,
                        parent_actor_id="main",
                        actor_id="wiki_researcher-browser",
                        agent_type="wiki_researcher",
                        mode="subagent",
                        status="idle",
                        last_outcome="success",
                        input_prompt=query,
                        output="## 浏览器 Wiki Markdown 标题\n\n| 类别 | 数量 |\n| --- | ---: |\n| 概念 | 9 |",
                        parent_message_id=parent_message_id,
                    )
                if on_event:
                    on_event("thinking", {"iteration": 1, "content": "浏览器 Agent 正在分析"})
                    on_event(
                        "actor_started",
                        {
                            "response_type": "actor_started",
                            "actor_id": "wiki_researcher-browser",
                            "agent_type": "wiki_researcher",
                            "name": "Wiki 研究子 Agent",
                            "status": "running",
                        },
                    )
                    on_event(
                        "actor_completed",
                        {
                            "response_type": "actor_completed",
                            "actor_id": "wiki_researcher-browser",
                            "agent_type": "wiki_researcher",
                            "name": "Wiki 研究子 Agent",
                            "status": "idle",
                            "last_outcome": "success",
                            "output": "## 浏览器 Wiki Markdown 标题\n\n| 类别 | 数量 |\n| --- | ---: |\n| 概念 | 9 |",
                        },
                    )
                    on_event(
                        "tool_call",
                        {
                            "iteration": 1,
                            "name": "browser_failure_tool",
                            "arguments": {"query": query},
                            "tool_call_id": "browser-failure-tool-001",
                        },
                    )
                    on_event(
                        "tool_result",
                        {
                            "iteration": 1,
                            "name": "browser_failure_tool",
                            "tool_call_id": "browser-failure-tool-001",
                            "output": "Error: 浏览器工具失败",
                            "error": "浏览器工具失败",
                            "duration_ms": 7,
                        },
                    )
                return AgentResult(
                    content="浏览器联动回答",
                    steps=[AgentStep(iteration=1, thought="浏览器 fake agent")],
                    total_iterations=1,
                    duration_ms=8,
                )

        with patch("personal_knowledge_base.rag_pipeline.run_rag_pipeline", side_effect=fake_rag_pipeline), patch(
            "chat.views.AgentEngine",
            FakeAgentEngine,
        ), patch("chat.views.build_agent_history_with_snapshot", return_value=[]):
            self.goto_and_wait(f"/platform/chat/{session.id}")
            self.page.locator("textarea").fill("浏览器联动测试问题")
            self.page.locator("textarea").press("Enter")
            self.page.get_by_text("浏览器联动回答").wait_for(timeout=15000)
            actor_summary = self.page.locator(".actor-summary", has_text="Wiki 研究子 Agent")
            actor_summary.wait_for(timeout=10000)
            self.assertEqual(actor_summary.get_attribute("aria-expanded"), "false")
            actor_details = self.page.locator("#actor-detail-wiki_researcher-browser")
            self.assertFalse(actor_details.is_visible())
            self.assertFalse(actor_details.locator("h3", has_text="浏览器 Wiki Markdown 标题").is_visible())

            actor_summary.click()
            self.assertEqual(actor_summary.get_attribute("aria-expanded"), "true")
            actor_details.locator("h3", has_text="浏览器 Wiki Markdown 标题").wait_for(timeout=10000)
            self.assertTrue(actor_details.locator("table").is_visible())

            failed_tool = self.page.locator("details.tool-call-item.failed", has_text="browser_failure_tool")
            failed_tool.wait_for(timeout=10000)
            self.assertTrue(failed_tool.evaluate("element => element.open"))
            self.assertEqual(failed_tool.locator(".tool-call-icon").count(), 1)
            self.assertEqual(failed_tool.locator(".tool-result-error", has_text="浏览器工具失败").count(), 1)
            self.assertEqual(failed_tool.inner_text().count("浏览器工具失败"), 1)

            desktop_metrics = self.page_metrics("desktop-1440")
            self.page.set_viewport_size({"width": 390, "height": 844})
            self.page.wait_for_timeout(250)
            mobile_metrics = self.page_metrics("mobile-390")
            body_text = self.page.locator("body").inner_text(timeout=10000)
            screenshot = self.screenshot("chat_stream_fake_agent")

        self.record(
            screenshot=screenshot,
            has_answer="浏览器联动回答" in body_text,
            has_actor_label=("子 Agent" in body_text or "Wiki 研究子 Agent" in body_text),
            actor_initially_collapsed=True,
            actor_markdown_heading_visible_after_expand=True,
            actor_markdown_table_visible_after_expand=True,
            failed_tool_default_open=True,
            failed_tool_error_count=1,
            desktop_metrics=desktop_metrics,
            mobile_metrics=mobile_metrics,
            console_tail=self.console_messages[-12:],
        )
        self.assertIn("浏览器联动测试问题", body_text)
        self.assertIn("浏览器联动回答", body_text)
        self.assertTrue("子 Agent" in body_text or "Wiki 研究子 Agent" in body_text)
        for metrics in [desktop_metrics, mobile_metrics]:
            self.assertFalse(metrics["has_document_overflow"], metrics)
            self.assertFalse(metrics["has_body_overflow"], metrics)
            self.assertEqual(metrics["console_errors"], [], metrics)
            self.assertEqual(metrics["failed_requests"], [], metrics)
            self.assertEqual(metrics["non_2xx_api_responses"], [], metrics)

    def test_chat_recovery_attempt_for_unfinished_message(self):
        from personal_knowledge_base.models import Message, Session
        from personal_knowledge_base.stream_manager import stream_manager

        session = Session.objects.create(
            tenant=self.tenant,
            user_id=self.user.id,
            title="恢复测试会话",
            knowledge_base_id=self.kb.id,
            agent_config={"knowledge_base_ids": [self.kb.id]},
        )
        Message.objects.create(
            session=session,
            request_id=str(uuid4()),
            role="user",
            content="刷新恢复问题",
            is_completed=True,
        )
        assistant = Message.objects.create(
            session=session,
            request_id=str(uuid4()),
            role="assistant",
            content="",
            rendered_content="",
            is_completed=False,
        )
        stream = stream_manager.create_stream(assistant.id, str(session.id))
        stream.append_event("thinking", {"content": "恢复后的中间内容"})
        stream.set_final_result(content="恢复后的回答", refs=[])
        stream.append_event("complete", {"done": True, "content": "恢复后的回答"})

        self.goto_and_wait(f"/platform/chat/{session.id}")
        self.page.wait_for_timeout(1800)
        body_text = self.page.locator("body").inner_text(timeout=10000)
        screenshot = self.screenshot("chat_continue_stream_recovery")
        console_errors = [msg for msg in self.console_messages if "error" in msg.lower() or "pageerror" in msg.lower()]
        stream_manager.remove_stream(assistant.id)

        self.record(
            screenshot=screenshot,
            body_has_recovered_answer="恢复后的回答" in body_text,
            console_errors=console_errors[-10:],
            console_tail=self.console_messages[-12:],
        )
        self.assertIn("恢复后的回答", body_text)
        self.assertEqual(console_errors, [])


def write_report(result: EvidenceResult):
    total = result.testsRun
    failed = len(result.failures)
    errored = len(result.errors)
    skipped = len(result.skipped)
    passed = total - failed - errored - skipped
    lines = [
        "# 前端 Playwright 浏览器联动测试报告",
        "",
        f"- 生成时间：{datetime.now().isoformat(timespec='seconds')}",
        "- 测试脚本：`tests/test_frontend_playwright_e2e.py`",
        "- 执行命令：`/home/liuxuedeng/anaconda3/envs/django-agent/bin/python tests/test_frontend_playwright_e2e.py`",
        "- 测试口径：Django StaticLiveServer + Chromium headless；后端 LLM/Agent 用 fake 实现稳定联动。",
        f"- 汇总：共 {total} 项，PASS {passed}，FAIL {failed}，ERROR {errored}，SKIP {skipped}。",
        "",
        "## 用例结果",
        "",
        "| 用例 | 结果 | 耗时 | 目标 | 关键证据 |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for name, objective in CASE_DEFINITIONS.items():
        item = CASE_RESULTS.get(name, {"status": "NOT_RUN", "duration_ms": 0, "detail": ""})
        lines.append(
            f"| `{name}` | {item['status']} | {item.get('duration_ms', 0)} ms | {objective} | "
            f"`{_json_preview(CASE_EVIDENCE.get(name, {}))}` |"
        )
    failed_items = [(name, data) for name, data in CASE_RESULTS.items() if data.get("status") in {"FAIL", "ERROR"}]
    lines.extend(["", "## 失败与风险", ""])
    if not failed_items:
        lines.append("- 本次测试未发现失败用例。")
    else:
        for name, data in failed_items:
            detail = data.get("detail", "").strip().splitlines()
            preview = "\n".join(detail[-18:]) if detail else ""
            lines.extend([f"### `{name}`", "", f"- 状态：{data.get('status')}", f"- 证据：`{_json_preview(CASE_EVIDENCE.get(name, {}), max_len=1000)}`"])
            if preview:
                lines.extend(["", "```text", preview, "```"])
            lines.append("")
    lines.extend(
        [
            "",
            "## 覆盖范围",
            "",
            "- 覆盖：知识库页、设置页模型区域、聊天页输入发送、SSE fake Agent 回答、Actor 终态折叠与 Markdown 表格、失败工具、桌面/移动端健康指标、continue-stream 恢复、知识库 401/404 边界。",
            "- 未覆盖：真实浏览器手动长时间刷新、真实模型耗时、真实文件上传解析、生产环境网络中断。",
            f"- 截图目录：`{SCREENSHOT_DIR}`（仅 `/tmp/django-agent-*.png`，不写入仓库）。",
        ]
    )
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    setup_test_environment()
    PLAYWRIGHT_TEST_DATABASE.unlink(missing_ok=True)
    settings.DATABASES["default"]["TEST"]["NAME"] = str(PLAYWRIGHT_TEST_DATABASE)
    runner = DiscoverRunner(verbosity=0, interactive=False)
    old_config = runner.setup_databases()
    try:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(FrontendPlaywrightE2ETests)
        result = EvidenceRunner(verbosity=2).run(suite)
        write_report(result)
        return 0 if result.wasSuccessful() else 1
    finally:
        with allow_unsafe_sync_for_playwright_shutdown():
            runner.teardown_databases(old_config)
        for suffix in ("", "-journal", "-shm", "-wal"):
            Path(f"{PLAYWRIGHT_TEST_DATABASE}{suffix}").unlink(missing_ok=True)
        teardown_test_environment()


if __name__ == "__main__":
    raise SystemExit(main())
