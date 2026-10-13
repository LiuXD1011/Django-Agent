"""工具调用失败处理框架测试：结构化错误分类、熔断器状态机、模型错误文本。

对齐 16.2 框架：
- 16.2.2 确定性错误返回 error_type/retryable/failed_fields，模型修正而非重试；
- 16.2.3 只有 retryable 失败进入熔断统计，Closed→Open→Half-Open 三态；
- 熔断打开期间快速失败，保护 Agent 与下游。
"""

import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from personal_knowledge_base.agent_tools import (  # noqa: E402
    ERROR_CIRCUIT_OPEN,
    ERROR_EXECUTION,
    ERROR_INVALID_ARGUMENT,
    ERROR_NOT_FOUND,
    ERROR_TRANSIENT,
    ERROR_UNKNOWN_TOOL,
    Tool,
    ToolCircuitBreaker,
    ToolRegistry,
    ToolResult,
    classify_error_text,
)


class _ScriptedTool(Tool):
    """按脚本返回/抛出的假工具。"""

    def __init__(self, behavior):
        self._behavior = behavior

    def name(self):
        return "dummy"

    def description(self):
        return "scripted dummy tool"

    def parameters(self):
        return {"type": "object", "properties": {}}

    def execute(self, args, context):
        return self._behavior(args, context)


class ErrorClassificationTests(unittest.TestCase):
    def test_transient_keywords_classified_retryable(self):
        for text in ("request timeout", "HTTP 429 rate limit", "connection reset by peer", "502 bad gateway"):
            error_type, retryable = classify_error_text(text)
            self.assertEqual(error_type, ERROR_TRANSIENT, text)
            self.assertTrue(retryable)

    def test_deterministic_errors_not_retryable(self):
        error_type, retryable = classify_error_text("something exploded unexpectedly")
        self.assertEqual(error_type, ERROR_EXECUTION)
        self.assertFalse(retryable)

    def test_validation_error_payload(self):
        result = ToolResult.validation_error("end_time must be later than start_time", failed_fields=["start_time", "end_time"])
        self.assertEqual(result.error_type, ERROR_INVALID_ARGUMENT)
        self.assertFalse(result.retryable)
        self.assertEqual(result.failed_fields, ["start_time", "end_time"])
        self.assertEqual(
            result.error_meta(),
            {"error_type": ERROR_INVALID_ARGUMENT, "retryable": False, "failed_fields": ["start_time", "end_time"]},
        )

    def test_unclassified_error_falls_back_to_keyword_classification(self):
        # 存量调用点只传 error 字符串：__post_init__ 自动按关键词兜底
        result = ToolResult(output="", error="connection reset by peer")
        self.assertEqual(result.error_type, ERROR_TRANSIENT)
        self.assertTrue(result.retryable)

    def test_model_error_text_differs_by_retryable(self):
        retryable = ToolResult.transient_error("upstream timeout").model_error_text()
        deterministic = ToolResult.validation_error("query is required", failed_fields=["query"]).model_error_text()
        self.assertIn('"retryable": true', retryable)
        self.assertIn("retry after a short wait", retryable)
        self.assertIn('"retryable": false', deterministic)
        self.assertIn("Retrying the same call will not help", deterministic)
        self.assertIn("failed_fields", deterministic)
        # 全部是合法 JSON 行（供模型稳定解析）
        meta_line = deterministic.splitlines()[1]
        self.assertEqual(json.loads(meta_line)["error_type"], ERROR_INVALID_ARGUMENT)


class ExecuteToolIntegrationTests(unittest.TestCase):
    def _registry(self, behavior):
        registry = ToolRegistry()
        registry.register(_ScriptedTool(behavior))
        return registry

    def test_unknown_tool_is_structured_and_not_retryable(self):
        result = ToolRegistry().execute_tool("nope", {}, {})
        self.assertEqual(result.error_type, ERROR_UNKNOWN_TOOL)
        self.assertFalse(result.retryable)

    def test_exception_classified_transient_and_counted(self):
        registry = self._registry(lambda args, ctx: (_ for _ in ()).throw(RuntimeError("request timeout")))
        result = registry.execute_tool("dummy", {}, {})
        self.assertEqual(result.error_type, ERROR_TRANSIENT)
        self.assertTrue(result.retryable)
        self.assertIn("RuntimeError: request timeout", result.error)
        self.assertEqual(registry.breaker.state("dummy"), "closed")  # 1 次，未达阈值

    def test_success_resets_failure_count(self):
        counter = {"n": 0}

        def behavior(args, ctx):
            counter["n"] += 1
            if counter["n"] % 2 == 1:
                raise RuntimeError("timeout")
            return ToolResult(output="ok")

        registry = self._registry(behavior)
        registry.execute_tool("dummy", {}, {})
        registry.execute_tool("dummy", {}, {})
        registry.execute_tool("dummy", {}, {})
        self.assertEqual(registry.breaker.state("dummy"), "closed")

    def test_model_message_uses_structured_text(self):
        registry = self._registry(lambda args, ctx: ToolResult.validation_error("query is required", failed_fields=["query"]))
        result = registry.execute_tool("dummy", {}, {"query": None})
        self.assertIn("Retrying the same call will not help", result.model_error_text())


class CircuitBreakerTests(unittest.TestCase):
    def test_opens_after_threshold_and_rejects(self):
        breaker = ToolCircuitBreaker(failure_threshold=3, cooldown_seconds=30)
        for _ in range(2):
            breaker.record_failure("t", retryable=True)
        self.assertEqual(breaker.state("t"), "closed")
        breaker.record_failure("t", retryable=True)
        self.assertEqual(breaker.state("t"), "open")
        allowed, retry_after = breaker.before_call("t")
        self.assertFalse(allowed)
        self.assertGreater(retry_after, 0)

    def test_deterministic_failures_never_trip_breaker(self):
        breaker = ToolCircuitBreaker(failure_threshold=3, cooldown_seconds=30)
        for _ in range(100):
            breaker.record_failure("t", retryable=False)
        self.assertEqual(breaker.state("t"), "closed")
        allowed, _ = breaker.before_call("t")
        self.assertTrue(allowed)

    def test_half_open_probe_success_closes_breaker(self):
        breaker = ToolCircuitBreaker(failure_threshold=1, cooldown_seconds=0.01)
        breaker.record_failure("t", retryable=True)
        self.assertEqual(breaker.state("t"), "open")
        time.sleep(0.02)  # 冷却期满
        allowed, _ = breaker.before_call("t")
        self.assertTrue(allowed)  # Half-Open 放行探测
        breaker.record_success("t")
        self.assertEqual(breaker.state("t"), "closed")

    def test_half_open_probe_failure_reopens(self):
        breaker = ToolCircuitBreaker(failure_threshold=1, cooldown_seconds=0.01)
        breaker.record_failure("t", retryable=True)
        time.sleep(0.02)
        allowed, _ = breaker.before_call("t")
        self.assertTrue(allowed)
        breaker.record_failure("t", retryable=True)
        allowed, retry_after = breaker.before_call("t")
        self.assertFalse(allowed)  # 探测失败 → 重新 Open
        self.assertGreater(retry_after, 0)

    def test_registry_rejects_calls_while_circuit_open(self):
        registry = ToolRegistry()

        def always_timeout(args, ctx):
            raise RuntimeError("upstream timeout")

        registry.register(_ScriptedTool(always_timeout))
        results = [registry.execute_tool("dummy", {}, {}) for _ in range(3)]
        self.assertTrue(all(r.retryable for r in results))
        fourth = registry.execute_tool("dummy", {}, {})
        self.assertEqual(fourth.error_type, ERROR_CIRCUIT_OPEN)
        self.assertIn("circuit open", fourth.error)
        self.assertIn("temporarily unavailable", fourth.model_error_text())


if __name__ == "__main__":
    unittest.main()
