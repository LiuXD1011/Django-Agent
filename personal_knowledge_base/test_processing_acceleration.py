import json
import threading
import time
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from personal_knowledge_base.model_providers import openai_compatible_chat_raw
from personal_knowledge_base.graph_rag import build_graph_for_chunks, DEFAULT_EXTRACT_CONFIG
from personal_knowledge_base.wiki_ingest import generate_candidate_pages_batch


class StructuredRequestTests(SimpleTestCase):
    def test_structured_request_sends_limits_without_changing_default_chat(self):
        response = Mock()
        response.status_code = 200
        response.raise_for_status.return_value = None
        response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        response.iter_content.return_value = [json.dumps(response.json.return_value).encode()]
        with patch("personal_knowledge_base.model_providers._http_session.post", return_value=response) as post:
            openai_compatible_chat_raw(
                "https://example.test/v1", "secret", "extract-model", [],
                max_tokens=1200, enable_thinking=False, total_timeout=90,
            )
            structured = post.call_args.kwargs["json"]
            self.assertEqual(structured["max_tokens"], 1200)
            self.assertFalse(structured["enable_thinking"])

            openai_compatible_chat_raw("https://example.test/v1", "secret", "chat-model", [])
            normal = post.call_args.kwargs["json"]
            self.assertNotIn("max_tokens", normal)
            self.assertNotIn("enable_thinking", normal)

    def test_graph_entities_use_five_chunk_batches_with_exact_mapping(self):
        chunks = [Mock(id=f"chunk-{index}", content=f"content {index}") for index in range(107)]
        calls = []
        lock = threading.Lock()
        active = 0
        peak = 0

        def complete(role, prompt, *args, **kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.002)
            keys = []
            for line in prompt.splitlines():
                if line.startswith("CHUNK "):
                    keys.append(line.split()[1])
            with lock:
                calls.append((keys, kwargs))
                active -= 1
            return json.dumps([
                {"chunk_key": key, "entities": [{"name": f"entity-{key}", "attributes": []}]}
                for key in keys
            ])

        with (
            patch("personal_knowledge_base.graph_rag.role_completion", side_effect=complete),
            patch("personal_knowledge_base.graph_rag.extract_relationships_for_batch", return_value={"node": [], "relation": []}),
            patch("personal_knowledge_base.graph_rag.build_chunk_relation_graph"),
        ):
            graphs = build_graph_for_chunks(chunks, DEFAULT_EXTRACT_CONFIG)

        self.assertEqual(len(calls), 22)
        self.assertTrue(all(len(keys) <= 5 for keys, _ in calls))
        mapped = {chunk_id for node in graphs[0]["node"] for chunk_id in node["chunks"]}
        self.assertEqual(mapped, {chunk.id for chunk in chunks})
        self.assertEqual(peak, 2)
        self.assertTrue(all(options["max_tokens"] == 1200 for _, options in calls))
        self.assertTrue(all(options["enable_thinking"] is False for _, options in calls))

    def test_wiki_generates_ten_pages_in_two_batches(self):
        knowledge = Mock()
        knowledge.title = "Paper"
        knowledge.source = "paper.pdf"
        knowledge.tenant = Mock()
        chunks = [Mock(id=f"chunk-{i}", content=f"evidence {i}") for i in range(10)]
        candidates = [{"slug": f"entity/{i}", "title": f"Entity {i}", "page_type": "entity"} for i in range(10)]
        calls = []

        def complete(role, prompt, *args, **kwargs):
            payload = json.loads(prompt.split("INPUT_JSON:\n", 1)[1])
            calls.append(kwargs)
            return json.dumps({"pages": [
                {"slug": item["slug"], "summary": "summary", "content": f"# {item['title']}", "related_pages": [], "referenced_chunks": []}
                for item in payload
            ]})

        with patch("personal_knowledge_base.wiki_ingest.role_completion", side_effect=complete):
            pages = generate_candidate_pages_batch(knowledge, candidates, chunks)

        self.assertEqual(len(calls), 2)
        self.assertEqual(set(pages), {item["slug"] for item in candidates})
        self.assertTrue(all(call["max_tokens"] == 4000 for call in calls))
        self.assertTrue(all(call["enable_thinking"] is False for call in calls))
