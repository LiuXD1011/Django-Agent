import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from requests.exceptions import ReadTimeout


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.test import override_settings

from personal_knowledge_base import memory


class MemoryTimeoutHandlingTest(unittest.TestCase):
    def test_structured_completion_does_not_retry_or_mislabel_timeout_as_json_parse_failure(self):
        with patch.object(memory, "_chat_completion_raw", side_effect=ReadTimeout("read timed out")) as caller:
            with self.assertLogs("personal_knowledge_base.memory", level="WARNING") as logs:
                result = memory._structured_completion(None, "prompt", memory.EXTRACT_KEYWORDS_SCHEMA)

        self.assertIsNone(result)
        self.assertEqual(caller.call_count, 1)
        log_text = "\n".join(logs.output)
        self.assertIn("timed out", log_text.lower())
        self.assertNotIn("Failed to parse LLM response as JSON", log_text)

    @override_settings(
        LLM_USE_ENV_CHAT=True,
        LLM_CHAT_API_KEY="sk-test",
        LLM_CHAT_BASE_URL="https://example.test/v1",
        LLM_CHAT_MODEL="qwen3.7-plus",
        LLM_EXTRACT_MODEL="qwen3.7-plus",
        LLM_CHAT_MODEL_TIMEOUT=60,
    )
    def test_memory_raw_completion_disables_thinking_for_structured_background_tasks(self):
        captured = {}

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"choices": [{"message": {"content": "{\"keywords\": [\"memory\"]}"}}]}

        def fake_post(url, headers, json, timeout):
            captured["url"] = url
            captured["body"] = json
            captured["timeout"] = timeout
            return FakeResponse()

        with patch("requests.post", side_effect=fake_post):
            result = memory._chat_completion_raw(
                None,
                [{"role": "user", "content": "extract memory"}],
                response_format={"type": "json_schema", "json_schema": memory.EXTRACT_KEYWORDS_SCHEMA},
            )

        self.assertEqual(result, "{\"keywords\": [\"memory\"]}")
        self.assertEqual(captured["timeout"], 60)
        self.assertIs(captured["body"]["enable_thinking"], False)
        self.assertEqual(captured["body"]["max_tokens"], 2048)
        self.assertEqual(captured["body"]["model"], "qwen3.7-plus")


if __name__ == "__main__":
    unittest.main(verbosity=2)
