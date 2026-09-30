"""Actual pinned SDK exporters, synthetic keys, and ephemeral local targets."""
import os
import subprocess
import sys

from django.conf import settings
from django.test import SimpleTestCase


class BenchmarkTransportRegressions(SimpleTestCase):
    def run_benchmark(self, fault):
        code = r'''
import os
from scripts import bench_langfuse_overhead as bench
from opentelemetry.sdk.trace.export import SpanExportResult

original_make = bench.make_client
calls = []
def make(base_url):
    client, counter = original_make(base_url)
    calls.append(client)
    if len(calls) == 2:
        provider = client._resources.tracer_provider
        processors = provider._active_span_processor._span_processors
        langfuse_processors = [processor for processor in processors if type(processor).__name__ == "LangfuseSpanProcessor"]
        if FAULT == "missing":
            provider._active_span_processor._span_processors = tuple(processor for processor in processors if processor not in langfuse_processors)
        elif FAULT == "inert":
            for processor in langfuse_processors:
                processor.span_exporter.export = lambda spans: SpanExportResult.SUCCESS
        elif FAULT == "misrouted":
            for processor in langfuse_processors:
                processor.span_exporter._endpoint = calls[0]._resources.base_url + "/api/public/otel/v1/traces"
    return client, counter
bench.make_client = make
result = bench.main()
print("FAULT_RESULT=" + str(result), flush=True)
os._exit(result)
'''
        code = "FAULT = " + repr(fault) + "\n" + code
        env = {**os.environ, "LANGFUSE_ENABLED": "false", "LANGFUSE_AUTOSTART": "false",
               "APP_TASKS_SYNC": "true", "LANGFUSE_BASE_URL": "https://must-not-contact.fixture.invalid",
               "LANGFUSE_HOST": "https://also-must-not-contact.fixture.invalid",
               "OTEL_EXPORTER_OTLP_ENDPOINT": "https://external-export.fixture.invalid"}
        return subprocess.run([sys.executable, "-c", code], cwd=settings.BASE_DIR, env=env,
                              capture_output=True, text=True, timeout=40)

    def test_healthy_scenarios_observe_actual_unavailable_export_failure(self):
        result = self.run_benchmark("healthy")
        self.assertEqual(result.returncode, 0, result.stderr[-2500:])
        self.assertIn("validation=PASS", result.stdout)
        self.assertIn("unreachable_export_attempts=", result.stdout)
        self.assertIn("unreachable_connection_failures=", result.stdout)

    def test_missing_inert_or_misrouted_actual_exporter_fails_nonzero(self):
        for fault in ("missing", "inert", "misrouted"):
            with self.subTest(fault=fault):
                result = self.run_benchmark(fault)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr[-2000:])
                self.assertIn("validation=FAIL", result.stderr)
