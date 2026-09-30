"""Measure observability facade overhead with validated synthetic scenarios.

This measures the facade, not full application request latency. No real model
calls or application credentials are used. Each enabled run has a separate SDK
resource, and transport validation is performed outside the timed loop.
"""
import os
import socket
import statistics
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class SinkHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("content-length", 0) or 0))
        self.server.received_requests += 1
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


def make_client(base_url):
    from langfuse import Langfuse
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
    from opentelemetry.sdk.trace.sampling import ALWAYS_ON

    class CounterExporter(SpanExporter):
        count = 0

        def export(self, spans):
            self.count += len(spans)
            return SpanExportResult.SUCCESS

    exporter = CounterExporter()
    provider = TracerProvider(sampler=ALWAYS_ON)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    # base_url must be explicit: an application's BASE_URL env wins over SDK host.
    client = Langfuse(public_key="pk-bench-" + uuid4().hex, secret_key="sk-bench-synthetic",
                      base_url=base_url, tracer_provider=provider, sample_rate=1.0,
                      timeout=2, flush_at=256, flush_interval=1)
    return client, exporter


def bench(label, exporter=None, iterations=200):
    from personal_knowledge_base import observability as obs

    durations = []
    before = exporter.count if exporter is not None else 0
    for index in range(iterations):
        started = time.perf_counter()
        handle = obs.start_business_trace("bench.turn", session_id="bench", metadata={"i": index})
        if handle is not None:
            with obs.child_span("bench.retrieve"):
                call = obs.start_model_call(model_call_id=f"bench-{index}", model="bench-model",
                                            provider="bench", scenario="chat")
                obs.finish_model_call(call, usage={"prompt_tokens": 10, "completion_tokens": 5})
        obs.close_business_trace(handle, output={"ok": True})
        durations.append((time.perf_counter() - started) * 1000)
    observed = exporter.count - before if exporter is not None else 0
    expected = iterations * 3 if exporter is not None else 0
    if observed != expected:
        raise RuntimeError(f"{label}: expected {expected} observations, got {observed}")
    p50 = statistics.median(durations)
    p95 = sorted(durations)[int(iterations * 0.95)]
    print(f"{label:28} n={iterations} observations={observed} p50={p50:.3f}ms "
          f"p95={p95:.3f}ms max={max(durations):.3f}ms")
    return p50, p95


def observe_unavailable_transport(client, expected_base):
    """Observe the pinned SDK's actual prepared HTTP requests and failures."""
    from langfuse._client.span_processor import LangfuseSpanProcessor
    from requests.exceptions import ConnectionError

    processors = client._resources.tracer_provider._active_span_processor._span_processors
    exporters = [processor.span_exporter for processor in processors if isinstance(processor, LangfuseSpanProcessor)]
    if not exporters:
        raise RuntimeError("unreachable scenario has no Langfuse export processor")
    expected_url = expected_base + "/api/public/otel/v1/traces"
    state = {"attempts": 0, "connection_failures": 0, "wrong_targets": []}
    lock = threading.Lock()
    for exporter in exporters:
        session = exporter._session
        session.trust_env = False
        actual_send = session.send

        def send(request, _send=actual_send, **kwargs):
            with lock:
                if request.url != expected_url:
                    state["wrong_targets"].append(request.url)
                    # Fail before a faulty exporter can leave the local harness.
                    raise RuntimeError("unreachable exporter prepared a request for the wrong target")
                state["attempts"] += 1
            try:
                return _send(request, **kwargs)
            except ConnectionError:
                with lock:
                    state["connection_failures"] += 1
                raise

        session.send = send
    return state


def flush_bounded(client, timeout=12):
    """Keep validation bounded even if a processor stops responding."""
    finished = threading.Event()
    errors = []

    def flush():
        try:
            client.flush()
        except Exception as exc:
            errors.append(exc)
        finally:
            finished.set()

    threading.Thread(target=flush, daemon=True).start()
    if not finished.wait(timeout):
        raise RuntimeError("SDK export validation timed out")
    if errors:
        raise RuntimeError("SDK export flush failed") from errors[0]


def run_benchmarks():
    from django.test.utils import override_settings
    from personal_knowledge_base import observability as obs

    sink = ThreadingHTTPServer(("127.0.0.1", 0), SinkHandler)
    sink.received_requests = 0
    threading.Thread(target=sink.serve_forever, daemon=True).start()
    original_client = obs._client, obs._client_ready
    print("── 门面开销（不含 LLM 调用）──")
    try:
        with override_settings(LANGFUSE_ENABLED=False):
            obs._client, obs._client_ready = None, False
            bench("warmup")
            disabled = bench("A: disabled(总开关关)")
        local_url = f"http://127.0.0.1:{sink.server_address[1]}"
        with override_settings(LANGFUSE_ENABLED=True, LANGFUSE_SAMPLE_RATE=1.0):
            local_client, local_exporter = make_client(local_url)
            obs._client, obs._client_ready = local_client, True
            enabled = bench("B: enabled+local sink", local_exporter)
            flush_bounded(local_client)
            if sink.received_requests == 0:
                raise RuntimeError("local sink received no upload")
            # Reserve a port without listening so it cannot belong to another service.
            with socket.socket() as reserved:
                reserved.bind(("127.0.0.1", 0))
                unreachable_url = f"http://127.0.0.1:{reserved.getsockname()[1]}"
                unavailable_client, unavailable_exporter = make_client(unreachable_url)
                if unavailable_client._resources is local_client._resources:
                    raise RuntimeError("unreachable scenario reused the local SDK resource")
                if unavailable_client._resources.base_url != unreachable_url:
                    raise RuntimeError("unreachable scenario targets the wrong endpoint")
                transport = observe_unavailable_transport(unavailable_client, unreachable_url)
                received_before = sink.received_requests
                obs._client, obs._client_ready = unavailable_client, True
                bench("C: enabled+unreachable", unavailable_exporter)
                # Flush before releasing the reserved port or comparing sink
                # uploads; recording into the counter alone cannot pass C.
                flush_bounded(unavailable_client)
                if transport["wrong_targets"]:
                    raise RuntimeError("unreachable exporter attempted the wrong HTTP target")
                if not transport["attempts"] or not transport["connection_failures"]:
                    raise RuntimeError("unreachable exporter made no actual failed connection attempt")
                if sink.received_requests != received_before:
                    raise RuntimeError("unreachable scenario uploaded to the local sink")
                print(f"unreachable_export_attempts={transport['attempts']} "
                      f"unreachable_connection_failures={transport['connection_failures']}")
        print("validation=PASS (独立 SDK 资源、真实观测、本地上传、独立不可达目标)")
        extra_p95 = enabled[1] - disabled[1]
        threshold = max(20, disabled[1] * 0.05)
        passed = extra_p95 <= threshold
        print(f"启用相对关闭的 p95 额外延迟: {extra_p95:.3f}ms "
              f"(阈值 {threshold:.2f}ms) → {'PASS' if passed else 'FAIL'}")
        return 0 if passed else 1
    finally:
        obs._client, obs._client_ready = original_client
        sink.shutdown()
        sink.server_close()


def main():
    os.environ["no_proxy"] = os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    # Django startup recovery must not inspect or change the application's DB.
    with tempfile.TemporaryDirectory(prefix="langfuse-facade-bench-") as directory:
        os.environ["DJANGO_DB_PATH"] = str(Path(directory) / "isolated.sqlite3")
        os.environ["APP_TASKS_SYNC"] = "true"
        import django
        django.setup()
        try:
            return run_benchmarks()
        except Exception as exc:
            print(f"validation=FAIL ({type(exc).__name__}: {exc})", file=sys.stderr)
            return 1


if __name__ == "__main__":
    exit_code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    # Pinned SDK 3.15 can block while joining its idle score consumer at exit.
    # All validation/upload work is complete; avoid that unbounded shutdown.
    os._exit(exit_code)
