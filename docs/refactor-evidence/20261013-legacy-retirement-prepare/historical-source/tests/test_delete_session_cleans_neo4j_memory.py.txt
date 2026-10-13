#!/usr/bin/env python
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import PropertyMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402
from django.test import Client, TestCase, override_settings  # noqa: E402

django.setup()

from personal_knowledge_base.models import Session, Tenant  # noqa: E402


class FakeTx:
    def __init__(self):
        self.queries = []

    def run(self, query, **params):
        self.queries.append((query, params))
        return []


class FakeSession:
    def __init__(self, tx):
        self.tx = tx

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute_write(self, fn):
        return fn(self.tx)


class FakeDriver:
    def __init__(self):
        self.tx = FakeTx()

    def session(self):
        return FakeSession(self.tx)


@override_settings(
    ALLOW_AUTO_SETUP=True,
    ALLOWED_HOSTS=["testserver"],
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
class DeleteSessionNeo4jMemoryCleanupViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        response = self.client.post("/api/v1/auth/auto-setup", content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.token = response.json()["data"]["token"]
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {self.token}"}

    def _create_session(self, title="memory cleanup"):
        response = self.client.post(
            "/api/v1/sessions",
            data=f'{{"title": "{title}"}}',
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 201)
        return response.json()["data"]["id"]

    @patch("personal_knowledge_base.views.delete_session_memory", create=True)
    @patch("chat.views.delete_session_memory", create=True)
    def test_single_session_delete_cleans_neo4j_memory(self, chat_delete_memory, pkb_delete_memory):
        session_id = self._create_session()

        response = self.client.delete(f"/api/v1/sessions/{session_id}", **self.headers)

        self.assertEqual(response.status_code, 200)
        chat_delete_memory.assert_called_once_with(session_id)
        pkb_delete_memory.assert_not_called()

    @patch("personal_knowledge_base.views.delete_session_memory", create=True)
    @patch("chat.views.delete_session_memory", create=True)
    def test_batch_session_delete_cleans_each_selected_session_memory(self, chat_delete_memory, pkb_delete_memory):
        first_id = self._create_session("first")
        second_id = self._create_session("second")

        response = self.client.delete(
            "/api/v1/sessions",
            data=f'{{"ids": ["{first_id}", "{second_id}"]}}',
            content_type="application/json",
            **self.headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {call.args[0] for call in chat_delete_memory.call_args_list},
            {first_id, second_id},
        )
        pkb_delete_memory.assert_not_called()

    @patch("personal_knowledge_base.views.delete_session_memory", create=True)
    @patch("chat.views.delete_session_memory", create=True)
    def test_delete_all_sessions_cleans_each_tenant_session_memory(self, chat_delete_memory, pkb_delete_memory):
        first_id = self._create_session("first")
        second_id = self._create_session("second")

        response = self.client.delete(
            "/api/v1/sessions",
            data='{"delete_all": true}',
            content_type="application/json",
            **self.headers,
        )

        self.assertEqual(response.status_code, 200)
        cleaned_ids = {call.args[0] for call in chat_delete_memory.call_args_list}
        self.assertTrue({first_id, second_id}.issubset(cleaned_ids))
        pkb_delete_memory.assert_not_called()

    @patch("personal_knowledge_base.views.delete_session_memory", create=True)
    @patch("chat.views.delete_session_memory", create=True)
    def test_clear_session_messages_cleans_neo4j_memory(self, chat_delete_memory, pkb_delete_memory):
        session_id = self._create_session()

        response = self.client.delete(f"/api/v1/sessions/{session_id}/messages", **self.headers)

        self.assertEqual(response.status_code, 200)
        chat_delete_memory.assert_called_once_with(session_id)
        pkb_delete_memory.assert_not_called()


class DeleteSessionNeo4jMemoryCleanupRepositoryTest(unittest.TestCase):
    def test_delete_session_memory_removes_session_episodes_and_unmentioned_entities(self):
        from personal_knowledge_base.memory import MemoryRepository

        driver = FakeDriver()
        repo = MemoryRepository()
        repo._driver = driver

        with patch.object(MemoryRepository, "enabled", new_callable=PropertyMock, return_value=True):
            repo.delete_session_memory("session-1")

        queries = [query for query, _params in driver.tx.queries]
        params = [params for _query, params in driver.tx.queries]
        joined = "\n".join(queries)

        self.assertIn("MATCH (e:MemoryEpisode {session_id: $session_id})", joined)
        self.assertIn("DETACH DELETE e", joined)
        self.assertIn("MATCH (n:MemoryEntity)", joined)
        self.assertIn("WHERE NOT EXISTS { MATCH (:MemoryEpisode)-[:MENTIONS]->(n) }", joined)
        self.assertIn("DETACH DELETE n", joined)
        self.assertEqual(params[0], {"session_id": "session-1"})


if __name__ == "__main__":
    unittest.main()
