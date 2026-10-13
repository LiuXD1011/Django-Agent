"""
Diagnose why "__chat_history__" appears in answers to "我有哪些知识库".

Run:
    python tests/test_chat_history_root_cause.py

This is intentionally a local-data diagnostic test. It uses sqlite3 directly so
it can run even when the Django runtime dependencies are not installed.
"""

import json
import sqlite3
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "db.sqlite3"
QUESTION = "我有哪些知识库"
INTERNAL_KB = "__chat_history__"


def _json(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


class ChatHistoryRootCauseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not DB_PATH.exists():
            raise unittest.SkipTest(f"{DB_PATH} does not exist")
        cls.conn = sqlite3.connect(DB_PATH)
        cls.conn.row_factory = sqlite3.Row

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "conn"):
            cls.conn.close()

    def test_visible_kb_query_already_hides_chat_history(self):
        active_internal = self.conn.execute(
            """
            select id, name, is_temporary, deleted_at
            from knowledge_bases
            where name = ? and deleted_at is null
            """,
            [INTERNAL_KB],
        ).fetchall()
        self.assertTrue(active_internal, "No active __chat_history__ row found")
        self.assertTrue(
            all(row["is_temporary"] == 1 for row in active_internal),
            "__chat_history__ is active but not marked is_temporary=1",
        )

        visible_names = [
            row["name"]
            for row in self.conn.execute(
                """
                select name
                from knowledge_bases
                where deleted_at is null and is_temporary = 0
                order by updated_at desc
                """
            )
        ]
        self.assertNotIn(INTERNAL_KB, visible_names)
        self.assertIn("vmm", visible_names)

    def test_latest_bad_answer_was_seeded_by_relevant_memory(self):
        user_msg = self.conn.execute(
            """
            select id, session_id, content, rendered_content, created_at
            from messages
            where role = 'user' and content like ?
            order by created_at desc
            limit 1
            """,
            [f"%{QUESTION}%"],
        ).fetchone()
        self.assertIsNotNone(user_msg, f"No user message found for {QUESTION!r}")

        rendered = user_msg["rendered_content"] or ""
        self.assertIn("<relevant_memory>", rendered)
        self.assertIn(INTERNAL_KB, rendered)

        answer = self.conn.execute(
            """
            select id, content, knowledge_references, created_at
            from messages
            where session_id = ? and role = 'assistant' and created_at >= ?
            order by created_at asc
            limit 1
            """,
            [user_msg["session_id"], user_msg["created_at"]],
        ).fetchone()
        self.assertIsNotNone(answer, "No assistant answer found after latest question")
        self.assertIn(INTERNAL_KB, answer["content"] or "")

        refs = _json(answer["knowledge_references"], [])
        self.assertEqual(
            refs,
            [],
            "Latest bad answer should come from memory/context, not live KB retrieval refs",
        )

        session = self.conn.execute(
            "select agent_config from sessions where id = ?",
            [user_msg["session_id"]],
        ).fetchone()
        config = _json(session["agent_config"], {}) if session else {}
        self.assertEqual(
            config.get("knowledge_base_ids") or [],
            [],
            "Latest bad answer was not caused by an explicit selected KB in this session",
        )

    def test_original_seed_came_from_old_session_selecting_internal_kb(self):
        internal_ids = [
            row["id"]
            for row in self.conn.execute(
                """
                select id
                from knowledge_bases
                where name = ?
                order by created_at
                """,
                [INTERNAL_KB],
            )
        ]
        self.assertTrue(internal_ids, "No __chat_history__ KB ids found")

        seeded_answers = []
        for kb_id in internal_ids:
            seeded_answers.extend(
                self.conn.execute(
                    """
                    select s.id as session_id, m.id as message_id, m.created_at
                    from sessions s
                    join messages m on m.session_id = s.id
                    where s.agent_config like ?
                      and m.role = 'assistant'
                      and m.content like ?
                    order by m.created_at asc
                    """,
                    [f"%{kb_id}%", f"%{INTERNAL_KB}%"],
                ).fetchall()
            )

        self.assertTrue(
            seeded_answers,
            "No historical assistant answer both selected and mentioned __chat_history__",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
