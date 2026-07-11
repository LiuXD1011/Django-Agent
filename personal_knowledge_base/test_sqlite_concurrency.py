import threading
from unittest.mock import PropertyMock, patch

from django.test import TestCase, override_settings

from personal_knowledge_base.chat_runtime import schedule_title_generation
from personal_knowledge_base.chat_history_kb import index_qa_to_kb_async
from personal_knowledge_base.context_snapshot import maybe_update_context_snapshot_async
from personal_knowledge_base.memory import add_episode
from personal_knowledge_base.models import Session, Tenant
from personal_knowledge_base.search import hybrid_search


class SQLiteConcurrencyTests(TestCase):
    def test_hybrid_search_keeps_sqlite_queries_on_request_thread(self):
        current_thread = threading.get_ident()
        observed_threads = []

        def record_thread(*args, **kwargs):
            observed_threads.append(threading.get_ident())
            return {}

        with (
            patch("personal_knowledge_base.search.ensure_search_tables"),
            patch("personal_knowledge_base.search._fts_search", side_effect=record_thread),
            patch("personal_knowledge_base.search._vector_search", side_effect=record_thread),
        ):
            hybrid_search(1, [], "SQLite", 5)

        self.assertEqual(observed_threads, [current_thread, current_thread])

    @override_settings(APP_TASKS_SYNC=True)
    def test_title_database_work_runs_inline_in_sync_mode(self):
        tenant = Tenant.objects.create(name="并发测试", api_key="sqlite-concurrency")
        session = Session.objects.create(tenant=tenant, title="新的对话")

        with (
            patch("personal_knowledge_base.chat_runtime.role_completion", return_value="同步标题"),
            patch("personal_knowledge_base.chat_runtime.threading.Thread") as thread_class,
        ):
            schedule_title_generation(session.id, "测试问题", tenant.id)

        thread_class.assert_not_called()
        session.refresh_from_db()
        self.assertEqual(session.title, "同步标题")

    @override_settings(APP_TASKS_SYNC=True)
    def test_nested_chat_maintenance_helpers_do_not_spawn_threads(self):
        tenant = Tenant.objects.create(
            name="维护测试",
            api_key="sqlite-maintenance",
            chat_history_config={"enabled": True},
        )
        session = Session.objects.create(tenant=tenant, title="维护会话")

        with (
            patch("personal_knowledge_base.chat_history_kb._index_qa_pair") as index_pair,
            patch("personal_knowledge_base.chat_history_kb.threading.Thread") as history_thread,
        ):
            index_qa_to_kb_async(tenant, object(), object())
        history_thread.assert_not_called()
        index_pair.assert_called_once()

        with (
            patch("personal_knowledge_base.context_snapshot.maybe_update_context_snapshot") as update_snapshot,
            patch("personal_knowledge_base.context_snapshot.threading.Thread") as snapshot_thread,
        ):
            maybe_update_context_snapshot_async(session, "rag", 5)
        snapshot_thread.assert_not_called()
        update_snapshot.assert_called_once()

    @override_settings(APP_TASKS_SYNC=True)
    def test_memory_extraction_does_not_escape_sync_test_transaction(self):
        tenant = Tenant.objects.create(name="记忆测试", api_key="sqlite-memory")
        with (
            patch("personal_knowledge_base.memory.MemoryRepository.available", new_callable=PropertyMock, return_value=True),
            patch("personal_knowledge_base.memory._structured_completion", return_value=None) as completion,
            patch("personal_knowledge_base.memory._memory_executor.submit") as submit,
        ):
            add_episode(tenant, "user", "session", [{"role": "user", "content": "问题"}])
        submit.assert_not_called()
        completion.assert_called_once()
