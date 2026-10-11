"""W02 业务发布 fencing：被接管/取消的旧 worker 不得发布业务写。

审计 F08/实测 13 的回归：任务租约被新 owner 接管后，旧执行者在
chunk 替换、embedding、终态发布各边界都必须被拒绝；失败标记也不得
覆写新 owner 的文档状态。全程使用受控替身，不触网、不依赖真实模型。
"""
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.test import TransactionTestCase, override_settings
from pathlib import Path
import tempfile

from .document_processing import ChunkDiagnostics, ChunkingResult, process_knowledge
from .models import Knowledge, KnowledgeBase, TaskRecord, Tenant
from .tasks import TaskOwnershipLost, assert_task_ownership, _WORKER_IDENTITY


class AssertTaskOwnershipTests(TransactionTestCase):
    def setUp(self):
        cache.clear()
        self.tenant = Tenant.objects.create(name="fencing", api_key="fencing-key")

    def _claimed_task(self, token="owner-a"):
        record = TaskRecord.objects.create(task_type="process_knowledge", status="pending")
        TaskRecord.objects.filter(id=record.id, status="pending").update(
            status="running", claimed_by=token,
            lease_expires_at=timezone_later(),
        )
        return record.id, token

    def test_no_context_returns_none_for_legacy_direct_calls(self):
        self.assertIsNone(assert_task_ownership())

    def test_owned_worker_passes_and_taken_over_worker_is_refused(self):
        task_id, token = self._claimed_task()
        bound = _WORKER_IDENTITY.set((task_id, token))
        try:
            self.assertEqual(assert_task_ownership(), (task_id, token))
            # 接管：新 owner 改写 claimed_by，旧 worker 的谓词立即失配。
            TaskRecord.objects.filter(id=task_id).update(claimed_by="new-owner")
            with self.assertRaises(TaskOwnershipLost):
                assert_task_ownership()
        finally:
            _WORKER_IDENTITY.reset(bound)

    def test_cancelled_or_missing_records_refuse_publish(self):
        task_id, token = self._claimed_task()
        bound = _WORKER_IDENTITY.set((task_id, token))
        try:
            TaskRecord.objects.filter(id=task_id).update(status="cancelled", claimed_by="")
            with self.assertRaises(TaskOwnershipLost):
                assert_task_ownership()
            TaskRecord.objects.filter(id=task_id).delete()
            with self.assertRaises(TaskOwnershipLost):
                assert_task_ownership()
        finally:
            _WORKER_IDENTITY.reset(bound)


def timezone_later():
    from django.utils import timezone
    from datetime import timedelta

    return timezone.now() + timedelta(seconds=90)


@override_settings(APP_TASKS_SYNC=True, LANGFUSE_ENABLED=False)
class ProcessKnowledgePublishFencingTests(TransactionTestCase):
    """失主 worker 的业务发布拒绝。

    身份绑定复用 _run_task 的同一 contextvar 契约（绑定本身由
    WorkerIdentityBindingTests 覆盖）；这里验证发布侧的 fencing 谓词。
    """

    def setUp(self):
        cache.clear()
        self.tenant = Tenant.objects.create(name="fencing-flow", api_key="fencing-flow-key")
        self.kb = KnowledgeBase.objects.create(tenant=self.tenant, name="fencing-kb", type="document")
        self.knowledge = Knowledge.objects.create(
            tenant=self.tenant, knowledge_base=self.kb, type="file",
            title="fencing-doc", file_name="doc.txt", file_type="txt",
            file_path="fencing/doc.txt", file_size=5, parse_status="pending",
        )
        self._stack =ExitStackHelper()

    def tearDown(self):
        self._stack.close()

    def _bind_claimed_task(self, token="worker-old"):
        """按 _run_task 的 claim 语义建立任务行并绑定执行身份。"""
        record = TaskRecord.objects.create(
            task_type="process_knowledge", status="pending",
            payload={"knowledge_id": self.knowledge.id},
        )
        TaskRecord.objects.filter(id=record.id, status="pending").update(
            status="running", claimed_by=token,
            lease_expires_at=timezone_later(),
        )
        return record.id, token

    def _run_with_identity(self, token="worker-old"):
        task_id, token = self._bind_claimed_task(token)
        bound = _WORKER_IDENTITY.set((task_id, token))
        try:
            process_knowledge(self.knowledge.id)
        finally:
            _WORKER_IDENTITY.reset(bound)

    def _patch_pipeline(self, takeover_hook):
        """受控文档流水线：在指定阶段把任务交给新 owner。"""
        from django.core.files.storage import FileSystemStorage

        parsed = SimpleNamespace(
            text_blocks=[SimpleNamespace(block_index=0, text="fencing content")],
            images=[], warnings=[],
        )
        empty_result = ChunkingResult(
            parents=[], children=[],
            diagnostics=ChunkDiagnostics(
                requested_strategy="fixed", selected_strategy="fixed",
                size_statistics={"parents": {"count": 0}, "children": {"count": 0}},
            ),
        )

        class _Open:
            def __enter__(self):
                import io
                return io.BytesIO(b"fencing")

            def __exit__(self, *args):
                return False

        stub_storage = FileSystemStorage()
        stub_storage.open = lambda *a, **k: _Open()
        self._stack.patch("personal_knowledge_base.document_processing.default_storage", stub_storage)
        self._stack.patch("personal_knowledge_base.document_processing.parse_document", lambda *a, **k: parsed)
        self._stack.patch("personal_knowledge_base.document_processing.semantic_chunking_inputs", lambda *a, **k: {})
        # split_document 返回前执行接管钩子，复现"解析/分块边界失主"。
        def _split(parsed_arg, config, **kwargs):
            takeover_hook()
            return empty_result
        self._stack.patch("personal_knowledge_base.document_processing.split_document", _split)
        self._stack.patch("personal_knowledge_base.document_processing.process_document_images", lambda *a, **k: ([], []))
        self._stack.patch("personal_knowledge_base.document_processing.index_chunk", lambda chunk: None)
        self._stack.patch("personal_knowledge_base.document_processing.process_graph", lambda *a, **k: [])
        self._stack.patch("personal_knowledge_base.document_processing.role_completion", lambda *a, **k: "summary")
        self._stack.patch("personal_knowledge_base.document_processing.generate_questions", lambda *a, **k: [])
        self._stack.patch("personal_knowledge_base.document_processing.extract_metadata", lambda *a, **k: ({}))

    def test_taken_over_worker_cannot_replace_chunks_or_publish(self):
        def takeover():
            TaskRecord.objects.filter(
                task_type="process_knowledge", status="running",
            ).update(claimed_by="new-owner")

        self._patch_pipeline(takeover)
        with self.assertRaises(TaskOwnershipLost):
            self._run_with_identity()
        self.knowledge.refresh_from_db(fields=["parse_status", "error_message"])
        # 失主 worker 既不能发布 completed，也不能把文档改成 failed。
        self.assertNotEqual(self.knowledge.parse_status, "completed")
        self.assertNotEqual(self.knowledge.parse_status, "failed")

    def test_taken_over_worker_cannot_flip_terminal_status(self):
        def takeover_during_wiki(*args, **kwargs):
            TaskRecord.objects.filter(
                task_type="process_knowledge", status="running",
            ).update(claimed_by="new-owner")
            return {"pages": 0, "links": 0}

        self._patch_pipeline(lambda: None)
        self._stack.patch(
            "personal_knowledge_base.document_processing.enqueue_wiki_ingest",
            takeover_during_wiki,
        )
        with self.assertRaises(TaskOwnershipLost):
            self._run_with_identity()
        self.knowledge.refresh_from_db(fields=["parse_status"])
        self.assertNotEqual(self.knowledge.parse_status, "completed")
        self.assertNotEqual(self.knowledge.parse_status, "failed")

    def test_owner_worker_completes_normally(self):
        self._patch_pipeline(lambda: None)
        self._stack.patch(
            "personal_knowledge_base.document_processing.enqueue_wiki_ingest",
            lambda *a, **k: {"pages": 0, "links": 0},
        )
        self._run_with_identity()
        self.knowledge.refresh_from_db(fields=["parse_status"])
        self.assertEqual(self.knowledge.parse_status, "completed")


class ExitStackHelper:
    """便携 exit-stack：集中管理测试补丁的生命周期。"""

    def __init__(self):
        from contextlib import ExitStack

        self._stack = ExitStack()

    def patch(self, *args, **kwargs):
        from unittest.mock import patch

        return self._stack.enter_context(patch(*args, **kwargs))

    def patch_object(self, *args, **kwargs):
        from unittest.mock import patch

        return self._stack.enter_context(patch.object(*args, **kwargs))

    def close(self):
        self._stack.close()
