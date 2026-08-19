#!/usr/bin/env python
import json
import re
import sys
import time
import unittest
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = PROJECT_ROOT / "tests" / "frontend_contracts_report.md"

CASE_DEFINITIONS = {
    "test_chat_input_is_single_smart_assistant_and_always_agent_enabled": "聊天输入框收敛为智能助手，发送 payload 固定 agent_enabled=true。",
    "test_sse_client_contracts_include_stream_and_continue_message_id": "前端 SSE 客户端必须发送 stream=true，并用 message_id 调用 continue-stream。",
    "test_recovery_uses_defined_reactive_state_names": "刷新恢复未完成消息时只能引用已定义的响应式状态变量。",
    "test_settings_removed_dead_sections_and_keeps_cache_chart_roles": "设置页不应残留空间/API、主题/字体设置，并保留四类模型缓存趋势。",
}

CASE_RESULTS: dict[str, dict] = {}
CASE_EVIDENCE: dict[str, dict] = {}


def _case_name(test):
    return getattr(test, "_testMethodName", str(test))


def _json_preview(value, max_len=500):
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        text = str(value)
    return text if len(text) <= max_len else text[:max_len] + "..."


def read_rel(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


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


class EvidenceRunner(unittest.TextTestRunner):
    resultclass = EvidenceResult


class FrontendContractTests(unittest.TestCase):
    def record(self, **data):
        CASE_EVIDENCE.setdefault(self._testMethodName, {}).update(data)

    def test_chat_input_is_single_smart_assistant_and_always_agent_enabled(self):
        chat_input = read_rel("frontend/src/views/chat/components/ChatInput.vue")
        chat_view = read_rel("frontend/src/views/Chat.vue")
        self.record(
            has_smart_assistant="智能助手" in chat_input,
            emits_agent_enabled="agent_enabled: true" in chat_input,
            no_agent_list_prop="agents" not in chat_input,
            chat_view_no_list_agents="listAgents" not in chat_view,
            old_mode_mentions={word: (word in chat_input or word in chat_view) for word in ["快速问答", "Wiki 问答", "智能推理"]},
        )
        self.assertIn("智能助手", chat_input)
        self.assertIn("agent_enabled: true", chat_input)
        self.assertNotIn("listAgents", chat_view)
        for word in ["快速问答", "Wiki 问答", "智能推理"]:
            self.assertNotIn(word, chat_input)
            self.assertNotIn(word, chat_view)

    def test_sse_client_contracts_include_stream_and_continue_message_id(self):
        api_file = read_rel("frontend/src/api/index.ts")
        self.record(
            stream_chat_endpoint="'/api/v1/agent-chat'" in api_file and "'/api/v1/knowledge-chat'" in api_file,
            stream_true="stream: true" in api_file,
            continue_endpoint="/api/v1/sessions/continue-stream" in api_file,
            continue_message_id="message_id=${encodeURIComponent(messageId)}" in api_file,
            accept_sse="Accept: 'text/event-stream'" in api_file,
        )
        self.assertIn("stream: true", api_file)
        self.assertIn("/api/v1/sessions/continue-stream", api_file)
        self.assertIn("message_id=${encodeURIComponent(messageId)}", api_file)
        self.assertIn("Accept: 'text/event-stream'", api_file)

    def test_recovery_uses_defined_reactive_state_names(self):
        chat_view = read_rel("frontend/src/views/Chat.vue")
        declared_refs = set(re.findall(r"const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*ref", chat_view))
        recovery_match = re.search(r"async function _recoverIncompleteMessage\(msg: any\) \{(?P<body>.*?)\n\}", chat_view, re.S)
        self.assertIsNotNone(recovery_match, "未找到 _recoverIncompleteMessage")
        recovery_body = recovery_match.group("body")
        suspicious_refs = sorted(
            name
            for name in ["lastAssistantId", "activeAbort", "currentAssistantId", "streamAbort"]
            if f"{name}.value" in recovery_body
        )
        undefined_refs = [name for name in suspicious_refs if name not in declared_refs]
        self.record(
            declared_refs=sorted(name for name in declared_refs if name in {"currentAssistantId", "streamAbort", "lastAssistantId", "activeAbort"}),
            recovery_refs=suspicious_refs,
            undefined_refs=undefined_refs,
        )
        self.assertEqual(undefined_refs, [], f"_recoverIncompleteMessage 引用了未定义 ref: {undefined_refs}")

    def test_settings_removed_dead_sections_and_keeps_cache_chart_roles(self):
        settings = read_rel("frontend/src/views/Settings.vue")
        forbidden = ["空间与 API", "主题", "选择浅色、深色或跟随系统", "字体大小", "调整界面文字大小"]
        missing_cache_roles = [word for word in ["对话", "Embedding", "ReRank", "视觉"] if word not in settings]
        self.record(
            forbidden_present=[word for word in forbidden if word in settings],
            missing_cache_roles=missing_cache_roles,
            has_cache_series="cache_series" in settings,
        )
        for word in forbidden:
            self.assertNotIn(word, settings)
        self.assertEqual(missing_cache_roles, [])
        self.assertIn("cache_series", settings)


def write_report(result: EvidenceResult):
    total = result.testsRun
    failed = len(result.failures)
    errored = len(result.errors)
    skipped = len(result.skipped)
    passed = total - failed - errored - skipped
    lines = [
        "# 前端静态契约测试报告",
        "",
        f"- 生成时间：{datetime.now().isoformat(timespec='seconds')}",
        "- 测试脚本：`tests/test_frontend_contracts.py`",
        "- 执行命令：`/home/liuxuedeng/anaconda3/envs/django-agent/bin/python tests/test_frontend_contracts.py`",
        "- 测试口径：静态读取 Vue/TS 源码，检查关键产品契约；不启动浏览器。",
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
            preview = "\n".join(detail[-14:]) if detail else ""
            lines.extend([f"### `{name}`", "", f"- 状态：{data.get('status')}", f"- 证据：`{_json_preview(CASE_EVIDENCE.get(name, {}), max_len=900)}`"])
            if preview:
                lines.extend(["", "```text", preview, "```"])
            lines.append("")
    lines.extend(
        [
            "",
            "## 覆盖范围",
            "",
            "- 覆盖：智能助手入口收敛、SSE/continue-stream 前端契约、未完成消息恢复变量、设置页无效配置清理、模型缓存趋势文案。",
            "- 未覆盖：浏览器真实渲染和用户操作；这部分由 `tests/test_frontend_playwright_e2e.py` 覆盖。",
        ]
    )
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(FrontendContractTests)
    result = EvidenceRunner(verbosity=2).run(suite)
    write_report(result)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
