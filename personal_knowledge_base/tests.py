import json
import time
from importlib import import_module
from unittest.mock import PropertyMock, patch

from django.apps import apps
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from .models import Chunk, Knowledge, KnowledgeBase, ModelConfig, ModelUsage, Tenant, WikiPage, WikiPendingOp


@override_settings(
    DASHSCOPE_API_KEY="",
    WEKNORA_USE_BAILIAN_CHAT=False,
    WEKNORA_USE_BAILIAN_SUMMARY=False,
    WEKNORA_USE_BAILIAN_TITLE=False,
    WEKNORA_USE_BAILIAN_QUESTION=False,
    WEKNORA_USE_BAILIAN_EXTRACT=False,
    WEKNORA_USE_BAILIAN_EMBEDDING=False,
    WEKNORA_USE_BAILIAN_RERANK=False,
    WEKNORA_USE_BAILIAN_VLM=False,
    WEKNORA_USE_BAILIAN_ASR=False,
)
class PersonalKnowledgeBaseCoreFlowTests(TestCase):
    def setUp(self):
        self.client = Client()
        response = self.client.post("/api/v1/auth/auto-setup", content_type="application/json")
        self.assertIn(response.status_code, (200, 201))
        self.token = response.json()["data"]["token"]
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {self.token}"}

    def upload_knowledge(self, kb_id, name, content, tag_id="", process_config=None):
        data = {
            "file": SimpleUploadedFile(name, content.encode("utf-8"), content_type="text/plain"),
        }
        if tag_id:
            data["tag_id"] = tag_id
        if process_config is not None:
            data["process_config"] = json.dumps(process_config)
        response = self.client.post(f"/api/v1/knowledge-bases/{kb_id}/knowledge/file", data=data, **self.headers)
        self.assertEqual(response.status_code, 201)
        return response.json()["data"]["knowledge"]

    def test_core_knowledge_chat_flow(self):
        response = self.client.post(
            "/api/v1/knowledge-bases",
            data=json.dumps({"name": "研发知识库", "description": "Django migration"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 201)
        kb_id = response.json()["data"]["id"]

        knowledge = self.upload_knowledge(kb_id, "django.txt", "Django 是 Python Web 框架，支持 SQLite。")
        knowledge_id = knowledge["id"]
        for _ in range(20):
            status = self.client.get(f"/api/v1/knowledge/{knowledge_id}", **self.headers).json()["data"]["parse_status"]
            if status == "completed":
                break
            time.sleep(0.2)

        response = self.client.post(
            f"/api/v1/knowledge-bases/{kb_id}/hybrid-search",
            data=json.dumps({"query": "Python Web 框架", "top_k": 3}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.json()["data"]["items"]), 1)

        response = self.client.post(
            "/api/v1/sessions",
            data=json.dumps({"knowledge_base_id": kb_id}),
            content_type="application/json",
            **self.headers,
        )
        session_id = response.json()["data"]["id"]
        response = self.client.post(
            f"/api/v1/knowledge-chat/{session_id}",
            data=json.dumps({"query": "Django 是什么？"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["answer"])

    def test_hybrid_search_and_chat_references_deduplicate_same_content(self):
        response = self.client.post(
            "/api/v1/knowledge-bases",
            data=json.dumps({"name": "重复引用库"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 201)
        kb_id = response.json()["data"]["id"]

        duplicated_content = "Django SQLite duplicate retrieval context. " * 20
        first = self.upload_knowledge(kb_id, "duplicate-a.txt", duplicated_content)
        second = self.upload_knowledge(kb_id, "duplicate-b.txt", duplicated_content)
        self.assertNotEqual(first["id"], second["id"])

        response = self.client.post(
            f"/api/v1/knowledge-bases/{kb_id}/hybrid-search",
            data=json.dumps({"query": "duplicate retrieval context", "top_k": 5}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        items = response.json()["data"]["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(len({item["content"] for item in items}), 1)

        session = self.client.post(
            "/api/v1/sessions",
            data=json.dumps({"knowledge_base_id": kb_id}),
            content_type="application/json",
            **self.headers,
        ).json()["data"]
        response = self.client.post(
            f"/api/v1/knowledge-chat/{session['id']}",
            data=json.dumps({"query": "duplicate retrieval context"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        refs = response.json()["data"]["references"]
        self.assertEqual(len(refs), 1)
        self.assertEqual(len({ref["content"] for ref in refs}), 1)

    def test_contract_representative_routes_exist(self):
        routes = [
            ("get", "/health"),
            ("get", "/api/v1/system/info"),
            ("get", "/api/v1/models/providers"),
            ("get", "/api/v1/vector-stores/types"),
            ("get", "/api/v1/web-search-providers/types"),
            ("get", "/api/v1/agents/placeholders"),
        ]
        for method, path in routes:
            response = getattr(self.client, method)(path, **self.headers)
            self.assertLess(response.status_code, 500, path)

    def test_organization_routes_are_removed_and_bailian_status_is_visible(self):
        response = self.client.get("/api/v1/organizations", **self.headers)
        self.assertEqual(response.status_code, 404)
        response = self.client.get("/api/v1/system/info", **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertIn("bailian", response.json()["data"])
        response = self.client.get("/api/v1/models", **self.headers)
        self.assertEqual(response.status_code, 200)
        ids = {item["id"] for item in response.json()["data"]["items"]}
        self.assertTrue(any(item_id.startswith("env-aliyun-bailian-knowledgeqa-") for item_id in ids))
        self.assertTrue(any(item_id.startswith("env-aliyun-bailian-embedding-") for item_id in ids))
        self.assertTrue(any(item_id.startswith("env-aliyun-bailian-rerank-") for item_id in ids))

    def test_model_status_masks_secret_and_keeps_local_embedding_default(self):
        response = self.client.get("/api/v1/system/info", **self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["name"], settings.APP_NAME)
        self.assertIn("roles", data["bailian"])
        body = json.dumps(data, ensure_ascii=False)
        if settings.DASHSCOPE_API_KEY:
            self.assertNotIn(settings.DASHSCOPE_API_KEY, body)
        self.assertEqual(data["bailian"]["local_embedding_dimension"], 384)
        self.assertFalse(data["bailian"]["roles"]["embedding"]["enabled"])

    @patch("personal_knowledge_base.model_providers._env_text_completion", return_value="项目标题")
    def test_session_title_uses_title_role_when_available(self, _mock_completion):
        response = self.client.post("/api/v1/sessions", data=json.dumps({}), content_type="application/json", **self.headers)
        session_id = response.json()["data"]["id"]
        response = self.client.post(
            f"/api/v1/sessions/{session_id}/generate_title",
            data=json.dumps({"query": "请介绍这个知识库"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["title"], "项目标题")

    def test_session_delete_matches_reference_contract(self):
        response = self.client.post("/api/v1/sessions", data=json.dumps({"title": "待删除对话"}), content_type="application/json", **self.headers)
        self.assertEqual(response.status_code, 201)
        session_id = response.json()["data"]["id"]
        response = self.client.delete(f"/api/v1/sessions/{session_id}", **self.headers)
        self.assertEqual(response.status_code, 200)
        response = self.client.get("/api/v1/sessions", **self.headers)
        ids = {item["id"] for item in response.json()["data"]["items"]}
        self.assertNotIn(session_id, ids)

    def test_chat_contract_pagination_pin_clear_stop_and_suggestions(self):
        kb_id = self.client.post(
            "/api/v1/knowledge-bases",
            data=json.dumps({"name": "聊天状态库"}),
            content_type="application/json",
            **self.headers,
        ).json()["data"]["id"]
        session_config = {
            "agent_enabled": True,
            "agent_id": "agent-a",
            "model_id": "env-aliyun-bailian-knowledgeqa-qwen3.7-plus",
            "summary_model_id": "env-aliyun-bailian-knowledgeqa-qwen3.7-plus",
            "knowledge_base_ids": [kb_id],
            "web_search_enabled": True,
            "enable_memory": False,
            "mcp_service_ids": ["mcp-a"],
        }
        response = self.client.post("/api/v1/sessions", data=json.dumps({"title": "契约测试", "agent_config": session_config}), content_type="application/json", **self.headers)
        session_id = response.json()["data"]["id"]
        self.assertEqual(response.json()["data"]["last_request_state"], session_config)

        updated_config = {**session_config, "knowledge_base_ids": [kb_id], "web_search_enabled": False, "enable_memory": True}
        response = self.client.put(f"/api/v1/sessions/{session_id}", data=json.dumps({"agent_config": updated_config}), content_type="application/json", **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["last_request_state"], updated_config)

        response = self.client.post(f"/api/v1/sessions/{session_id}/pin", **self.headers)
        self.assertTrue(response.json()["data"]["is_pinned"])
        response = self.client.delete(f"/api/v1/sessions/{session_id}/pin", **self.headers)
        self.assertFalse(response.json()["data"]["is_pinned"])

        response = self.client.post(
            f"/api/v1/knowledge-chat/{session_id}",
            data=json.dumps({"query": "分页测试", **updated_config, "mentioned_items": [{"id": "kb", "name": "范围", "type": "kb"}], "images": [{"data": "data:image/png;base64,AA=="}], "attachment_uploads": [{"file_name": "a.txt", "file_size": 3}]}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        response = self.client.get(f"/api/v1/sessions/{session_id}", **self.headers)
        self.assertEqual(response.json()["data"]["last_request_state"]["knowledge_base_ids"], [kb_id])
        self.assertTrue(response.json()["data"]["last_request_state"]["enable_memory"])
        response = self.client.get(f"/api/v1/messages/{session_id}/load?limit=1", **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["has_more"])
        first = response.json()["data"]["items"][0]
        self.assertIn("attachments", first)

        response = self.client.post(f"/api/v1/sessions/{session_id}/stop", data=json.dumps({"message_id": first["id"]}), content_type="application/json", **self.headers)
        self.assertTrue(response.json()["data"]["stopped"])

        response = self.client.delete(f"/api/v1/sessions/{session_id}/messages", **self.headers)
        self.assertEqual(response.status_code, 200)
        response = self.client.get(f"/api/v1/messages/{session_id}/load", **self.headers)
        self.assertEqual(response.json()["data"]["items"], [])

        response = self.client.get("/api/v1/agents/builtin-quick-answer/suggested-questions", **self.headers)
        self.assertGreaterEqual(len(response.json()["data"]["questions"]), 1)

    def test_session_state_normalizes_legacy_summary_and_dirty_config(self):
        response = self.client.post(
            "/api/v1/sessions",
            data=json.dumps({"title": "脏配置", "agent_config": "legacy-bad-value"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 201)
        session_id = response.json()["data"]["id"]
        self.assertEqual(
            response.json()["data"]["last_request_state"],
            {
                "agent_enabled": False,
                "agent_id": "",
                "model_id": "",
                "summary_model_id": "",
                "knowledge_base_ids": [],
                "web_search_enabled": False,
                "enable_memory": True,
                "mcp_service_ids": [],
            },
        )

        response = self.client.put(
            f"/api/v1/sessions/{session_id}",
            data=json.dumps(
                {
                    "summary_model_id": "legacy-summary-model",
                    "model_id": "env-aliyun-bailian-knowledgeqa-qwen3.7-plus",
                    "knowledge_base_ids": "dirty-kb",
                    "mcp_service_ids": "dirty-mcp",
                    "enable_memory": False,
                }
            ),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        state = response.json()["data"]["last_request_state"]
        self.assertEqual(state["summary_model_id"], "legacy-summary-model")
        self.assertEqual(state["model_id"], "env-aliyun-bailian-knowledgeqa-qwen3.7-plus")
        self.assertEqual(state["knowledge_base_ids"], [])
        self.assertEqual(state["mcp_service_ids"], [])
        self.assertFalse(state["enable_memory"])

    def test_chat_sse_stream_contract(self):
        response = self.client.post("/api/v1/sessions", data=json.dumps({"title": "SSE"}), content_type="application/json", **self.headers)
        session_id = response.json()["data"]["id"]
        response = self.client.post(
            f"/api/v1/knowledge-chat/{session_id}",
            data=json.dumps({"query": "SSE 测试", "stream": True}),
            content_type="application/json",
            HTTP_ACCEPT="text/event-stream",
            **self.headers,
        )
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn("event: message_start", body)
        self.assertIn("event: done", body)

    def test_knowledge_base_config_and_tenant_kv_contract(self):
        response = self.client.post(
            "/api/v1/knowledge-bases",
            data=json.dumps(
                {
                    "name": "RAG Wiki 配置库",
                    "type": "document",
                    "chunking_config": {"chunk_size": 256, "chunk_overlap": 16},
                    "wiki_config": {"auto_generate_outline": True},
                    "indexing_strategy": {
                        "vector_enabled": True,
                        "keyword_enabled": True,
                        "wiki_enabled": True,
                        "graph_enabled": False,
                    },
                }
            ),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 201)
        kb_id = response.json()["data"]["id"]
        data = response.json()["data"]
        self.assertEqual(data["type"], "document")
        self.assertTrue(data["indexing_strategy"]["vector_enabled"])
        self.assertTrue(data["indexing_strategy"]["keyword_enabled"])
        self.assertTrue(data["indexing_strategy"]["wiki_enabled"])
        self.assertTrue(data["capabilities"]["wiki"])
        self.assertNotIn("faq_config", data)

        response = self.client.put(
            f"/api/v1/knowledge-bases/{kb_id}",
            data=json.dumps(
                {
                    "config": {
                        "wiki_config": {"auto_generate_outline": False, "max_pages_per_ingest": 20},
                        "indexing_strategy": {
                            "vector_enabled": True,
                            "keyword_enabled": True,
                            "wiki_enabled": True,
                            "graph_enabled": True,
                        },
                        "extract_config": {
                            "enabled": True,
                            "text": "抽取流程实体关系",
                            "tags": ["depends_on"],
                            "nodes": [{"name": "Entity"}],
                            "relations": [{"node1": "Entity", "node2": "Entity", "type": "depends_on"}],
                        },
                    }
                }
            ),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["wiki_config"], {"auto_generate_outline": False, "max_pages_per_ingest": 20})
        self.assertTrue(data["indexing_strategy"]["keyword_enabled"])
        self.assertTrue(data["indexing_strategy"]["graph_enabled"])
        self.assertTrue(data["extract_config"]["enabled"])
        self.assertTrue(data["capabilities"]["graph"])

        response = self.client.put(
            "/api/v1/tenants/kv/retrieval-config",
            data=json.dumps({"value": {"top_k": 8, "rerank": True}}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["field"], "retrieval_config")
        self.assertEqual(response.json()["data"]["value"]["top_k"], 8)

        response = self.client.get("/api/v1/tenants/kv/retrieval-config", **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["configured"])
        self.assertEqual(response.json()["data"]["value"], {"top_k": 8, "rerank": True})

    def test_wiki_type_compatibility_and_faq_removal_contract(self):
        response = self.client.post(
            "/api/v1/knowledge-bases",
            data=json.dumps({"name": "旧 Wiki 创建请求", "type": "wiki"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()["data"]
        kb_id = data["id"]
        self.assertEqual(data["type"], "document")
        self.assertTrue(data["indexing_strategy"]["wiki_enabled"])
        self.assertTrue(data["capabilities"]["wiki"])

        response = self.client.post(
            "/api/v1/knowledge-bases",
            data=json.dumps({"name": "不支持的 FAQ", "type": "faq"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 400)

        response = self.client.get(f"/api/v1/knowledge-bases/{kb_id}/faq/entries", **self.headers)
        self.assertEqual(response.status_code, 404)

    def test_graph_config_validation_system_status_and_graphrag_processing(self):
        defaulted = self.client.post(
            "/api/v1/knowledge-bases",
            data=json.dumps({"name": "坏图谱", "indexing_strategy": {"vector_enabled": True, "keyword_enabled": True, "wiki_enabled": False, "graph_enabled": True}, "extract_config": {"enabled": True}}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(defaulted.status_code, 201)
        self.assertTrue(defaulted.json()["data"]["extract_config"]["enabled"])

        invalid = self.client.post(
            "/api/v1/knowledge-bases",
            data=json.dumps({"name": "空图谱字段", "indexing_strategy": {"vector_enabled": True, "keyword_enabled": True, "wiki_enabled": False, "graph_enabled": True}, "extract_config": {"enabled": True, "text": "", "tags": [], "nodes": [], "relations": []}}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(invalid.status_code, 400)

        response = self.client.post(
            "/api/v1/knowledge-bases",
            data=json.dumps(
                {
                    "name": "图谱库",
                    "indexing_strategy": {"vector_enabled": True, "keyword_enabled": True, "wiki_enabled": False, "graph_enabled": True},
                    "extract_config": {
                        "enabled": True,
                        "text": "抽取产品和能力关系",
                        "tags": ["uses"],
                        "nodes": [{"name": "Entity"}],
                        "relations": [{"node1": "Entity", "node2": "Entity", "type": "uses"}],
                    },
                }
            ),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 201)
        kb_id = response.json()["data"]["id"]
        self.assertTrue(response.json()["data"]["capabilities"]["graph"])

        entity_payload = {"node": [{"name": "Django", "attributes": ["framework"]}, {"name": "SQLite", "attributes": ["database"]}], "relation": []}
        relation_payload = {"node": entity_payload["node"], "relation": [{"node1": "Django", "node2": "SQLite", "type": "uses", "strength": 8}]}
        with patch("personal_knowledge_base.graph_rag.Neo4jGraphRepository.available", new_callable=PropertyMock, return_value=True), patch("personal_knowledge_base.graph_rag.graph_repository.add_graph") as add_graph, patch("personal_knowledge_base.graph_rag.graph_repository.delete_graph") as delete_graph, patch("personal_knowledge_base.graph_rag.extract_entities_from_text", return_value=entity_payload) as extract_entities, patch("personal_knowledge_base.graph_rag.extract_relationships_for_batch", return_value=relation_payload) as extract_relations:
            knowledge = self.upload_knowledge(kb_id, "graph.txt", "Django 使用 SQLite。")
            knowledge_id = knowledge["id"]
            self.assertTrue(extract_entities.called)
            self.assertTrue(extract_relations.called)
            self.assertTrue(add_graph.called)
            detail = self.client.get(f"/api/v1/knowledge/{knowledge_id}", **self.headers).json()["data"]
            self.assertTrue(detail["metadata"]["graph"]["enabled"])
            self.assertEqual(detail["metadata"]["graph"]["node_count"], 2)
            self.assertEqual(detail["metadata"]["graph"]["relation_count"], 1)
            chunks = self.client.get(f"/api/v1/chunks/{knowledge_id}", **self.headers).json()["data"]["items"]
            self.assertIn("relation_chunks", chunks[0])

            response = self.client.delete(f"/api/v1/knowledge/{knowledge_id}", **self.headers)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(delete_graph.called)

        response = self.client.get("/api/v1/system/info", **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertIn("graph_database_engine", response.json()["data"])
        self.assertIn("graph_rag_enabled", response.json()["data"])
        self.assertIn("neo4j_configured", response.json()["data"])

    def test_graph_enabled_upload_completes_when_neo4j_is_not_configured(self):
        response = self.client.post(
            "/api/v1/knowledge-bases",
            data=json.dumps(
                {
                    "name": "图谱降级库",
                    "indexing_strategy": {"vector_enabled": True, "keyword_enabled": True, "wiki_enabled": False, "graph_enabled": True},
                    "extract_config": {
                        "enabled": True,
                        "text": "抽取实体关系",
                        "tags": ["related_to"],
                        "nodes": [{"name": "Entity"}],
                        "relations": [{"node1": "Entity", "node2": "Entity", "type": "related_to"}],
                    },
                }
            ),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 201)
        knowledge = self.upload_knowledge(response.json()["data"]["id"], "neo4j-off.txt", "Django 和 SQLite 相关。")
        detail = self.client.get(f"/api/v1/knowledge/{knowledge['id']}", **self.headers).json()["data"]
        self.assertEqual(detail["parse_status"], "completed")
        self.assertFalse(detail["metadata"]["graph"]["enabled"])

    def test_enrichment_failures_do_not_fail_file_parsing(self):
        kb_id = self.client.post(
            "/api/v1/knowledge-bases",
            data=json.dumps({"name": "增强降级库"}),
            content_type="application/json",
            **self.headers,
        ).json()["data"]["id"]

        with patch("personal_knowledge_base.document_processing.process_graph", side_effect=RuntimeError("graph boom")), patch("personal_knowledge_base.document_processing.role_completion", side_effect=RuntimeError("summary boom")), patch("personal_knowledge_base.document_processing.generate_questions", side_effect=RuntimeError("questions boom")), patch("personal_knowledge_base.document_processing.extract_metadata", side_effect=RuntimeError("metadata boom")):
            knowledge = self.upload_knowledge(kb_id, "fallback.txt", "核心解析内容可以正常切分和索引。")

        detail = self.client.get(f"/api/v1/knowledge/{knowledge['id']}", **self.headers).json()["data"]
        self.assertEqual(detail["parse_status"], "completed")
        self.assertEqual(detail["summary_status"], "completed")
        chunks = self.client.get(f"/api/v1/chunks/{knowledge['id']}", **self.headers).json()["data"]
        self.assertGreaterEqual(chunks["total"], 1)
        warnings = detail["metadata"]["processing_warnings"]
        self.assertEqual({item["stage"] for item in warnings}, {"graph", "summary", "questions", "metadata"})
        self.assertEqual(detail["metadata"]["generated_questions"], [])
        self.assertEqual(detail["metadata"]["extracted_metadata"], {})

    def test_model_usage_aggregation_contract(self):
        ModelUsage.objects.create(
            tenant_id=1,
            model_id="env-aliyun-bailian-chat",
            model_name="qwen3.7-plus",
            model_type="chat",
            provider="aliyun-bailian",
            scenario="chat",
            prompt_tokens=120,
            completion_tokens=80,
            total_tokens=200,
            cached_tokens=20,
            duration_ms=300,
        )
        ModelUsage.objects.create(
            tenant_id=1,
            model_id="env-aliyun-bailian-extract",
            model_name="qwen3.7-plus",
            model_type="extract",
            provider="aliyun-bailian",
            scenario="graph_entity_extract",
            success=False,
            prompt_tokens=50,
            total_tokens=50,
            error_message="timeout",
            created_at=timezone.now(),
        )

        response = self.client.get("/api/v1/models/usage?range=7", **self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["total"]["calls"], 2)
        self.assertEqual(data["total"]["success"], 1)
        self.assertEqual(data["total"]["failed"], 1)
        self.assertEqual(data["total"]["total_tokens"], 250)
        self.assertTrue(any(item["model_type"] == "chat" for item in data["by_type"]))
        self.assertTrue(any(item["scenario"] == "graph_entity_extract" for item in data["by_scenario"]))

        response = self.client.get("/api/v1/models/usage?model_type=chat", **self.headers)
        self.assertEqual(response.json()["data"]["total"]["total_tokens"], 250)
        response = self.client.get("/api/v1/models/usage?model_type=KnowledgeQA", **self.headers)
        self.assertEqual(response.json()["data"]["total"]["total_tokens"], 250)
        response = self.client.get("/api/v1/models/usage?model_type=Embedding", **self.headers)
        self.assertEqual(response.json()["data"]["total"]["total_tokens"], 0)

    def test_chunk_list_detail_update_and_delete_contract(self):
        kb_id = self.client.post(
            "/api/v1/knowledge-bases",
            data=json.dumps({"name": "分块测试"}),
            content_type="application/json",
            **self.headers,
        ).json()["data"]["id"]
        knowledge = self.upload_knowledge(kb_id, "chunk-doc.txt", "第一段内容。\n第二段内容。")
        knowledge_id = knowledge["id"]
        for _ in range(20):
            detail = self.client.get(f"/api/v1/knowledge/{knowledge_id}", **self.headers).json()["data"]
            if detail["parse_status"] == "completed":
                break
            time.sleep(0.2)

        response = self.client.get(f"/api/v1/chunks/{knowledge_id}", **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(response.json()["data"]["total"], 1)
        chunk_id = response.json()["data"]["items"][0]["id"]

        response = self.client.get(f"/api/v1/chunks/{knowledge_id}/{chunk_id}", **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["id"], chunk_id)

        response = self.client.get(f"/api/v1/chunks/by-id/{chunk_id}", **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["knowledge_id"], knowledge_id)

        response = self.client.put(
            f"/api/v1/chunks/{knowledge_id}/{chunk_id}",
            data=json.dumps({"content": "更新后的分块内容", "is_enabled": False, "metadata": {"source": "test"}}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["content"], "更新后的分块内容")
        self.assertFalse(response.json()["data"]["is_enabled"])
        self.assertEqual(response.json()["data"]["metadata"], {"source": "test"})

        response = self.client.delete(f"/api/v1/chunks/by-id/{chunk_id}", **self.headers)
        self.assertEqual(response.status_code, 200)
        response = self.client.get(f"/api/v1/chunks/by-id/{chunk_id}", **self.headers)
        self.assertEqual(response.status_code, 404)

    def test_model_credentials_are_masked_and_field_delete_updates_storage(self):
        response = self.client.post(
            "/api/v1/models",
            data=json.dumps(
                {
                    "id": "chat-test-model",
                    "name": "qwen-test",
                    "display_name": "测试模型",
                    "type": "chat",
                    "source": "openai",
                    "parameters": {"base_url": "https://example.test/v1", "api_key": "initial-secret", "model": "qwen-test"},
                }
            ),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()["data"]
        self.assertEqual(data["parameters"]["api_key"], "******")
        self.assertTrue(data["credentials_configured"])

        response = self.client.put(
            "/api/v1/models/chat-test-model/credentials",
            data=json.dumps({"credentials": {"api_key": "updated-secret", "token": "runtime-token"}}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["parameters"]["api_key"], "******")
        self.assertEqual(response.json()["data"]["parameters"]["token"], "******")
        self.assertNotIn("updated-secret", json.dumps(response.json(), ensure_ascii=False))

        response = self.client.delete("/api/v1/models/chat-test-model/credentials/api_key", **self.headers)
        self.assertEqual(response.status_code, 200)
        params = response.json()["data"]["parameters"]
        self.assertNotIn("api_key", params)
        self.assertEqual(params["token"], "******")
        self.assertTrue(response.json()["data"]["credentials_configured"])

    def test_models_use_weknora_four_primary_type_contract(self):
        response = self.client.get("/api/v1/models", **self.headers)
        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        items = payload["items"]
        types = {item["type"] for item in items if item["id"].startswith("env-aliyun-bailian-")}
        self.assertIn("KnowledgeQA", types)
        self.assertIn("Embedding", types)
        self.assertIn("Rerank", types)
        self.assertIn("VLLM", types)
        self.assertNotIn("summary", types)
        self.assertNotIn("extract", types)
        knowledgeqa_env = [item for item in items if item["id"].startswith("env-aliyun-bailian-knowledgeqa-")]
        self.assertEqual(len(knowledgeqa_env), 1)
        self.assertEqual({role["key"] for role in knowledgeqa_env[0]["roles"]}, {"chat", "summary", "title", "question", "extract"})
        self.assertEqual(payload["total"], len(items))
        self.assertEqual(payload["counts_by_type"]["chat"], 1)
        self.assertEqual(payload["counts_by_type"]["embedding"], 1)
        self.assertEqual(payload["counts_by_type"]["rerank"], 1)
        self.assertEqual(payload["counts_by_type"]["vlm"], 1)
        self.assertNotIn("asr", payload["counts_by_type"])

        response = self.client.get("/api/v1/models?type=KnowledgeQA", **self.headers)
        self.assertEqual(response.status_code, 200)
        knowledgeqa_items = response.json()["data"]["items"]
        self.assertTrue(knowledgeqa_items)
        self.assertTrue(all(item["type"] == "KnowledgeQA" for item in knowledgeqa_items))
        self.assertTrue(any(any(role["key"] == "summary" for role in item.get("roles", [])) for item in knowledgeqa_items))

        response = self.client.get("/api/v1/models?type=chat", **self.headers)
        self.assertEqual(response.status_code, 200)
        legacy_items = response.json()["data"]["items"]
        self.assertEqual({item["id"] for item in legacy_items}, {item["id"] for item in knowledgeqa_items})

        response = self.client.post(
            "/api/v1/models",
            data=json.dumps(
                {
                    "id": "weknora-type-chat",
                    "name": "qwen-compatible",
                    "display_name": "对话模型",
                    "type": "chat",
                    "source": "openai",
                    "parameters": {"base_url": "https://example.test/v1", "api_key": "secret", "model": "qwen-compatible"},
                }
            ),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["data"]["type"], "KnowledgeQA")

    def test_legacy_local_builtin_models_do_not_pollute_model_counts(self):
        tenant = Tenant.objects.first()
        ModelConfig.objects.create(id=f"builtin-local-chat-{tenant.id}", tenant=tenant, name="local-fallback", display_name="Local fallback", type="KnowledgeQA", source="local", is_builtin=True)
        ModelConfig.objects.create(id=f"builtin-local-embedding-{tenant.id}", tenant=tenant, name="stable-hash", display_name="Stable hash embedding", type="Embedding", source="local", is_builtin=True)
        response = self.client.post("/api/v1/auth/auto-setup", content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ModelConfig.objects.filter(id__startswith="builtin-local-").exists())

        response = self.client.get("/api/v1/models", **self.headers)
        payload = response.json()["data"]
        self.assertFalse(any(item["id"].startswith("builtin-local-") for item in payload["items"]))
        self.assertEqual(payload["total"], 4)

    def test_weknora_knowledge_contract_filters_process_config_stats_batch_and_move(self):
        kb_id = self.client.post(
            "/api/v1/knowledge-bases",
            data=json.dumps({"name": "契约补洞库"}),
            content_type="application/json",
            **self.headers,
        ).json()["data"]["id"]
        target_kb_id = self.client.post(
            "/api/v1/knowledge-bases",
            data=json.dumps({"name": "迁移目标库"}),
            content_type="application/json",
            **self.headers,
        ).json()["data"]["id"]

        process_config = {"chunking_config": {"chunk_size": 128, "chunk_overlap": 0}, "graph_enabled": True}
        flow_content = "流程手册内容。" * 80
        flow_doc = self.upload_knowledge(kb_id, "流程手册.txt", flow_content, tag_id="tag-a", process_config=process_config)
        self.assertEqual(flow_doc["metadata"]["process_config"], process_config)
        self.assertEqual(flow_doc["metadata"]["process_overrides"], process_config)
        self.assertGreater(Chunk.objects.filter(knowledge_id=flow_doc["id"]).count(), 1)

        site_doc = self.upload_knowledge(kb_id, "站点资料.md", "站点资料内容", tag_id="tag-b", process_config={"parser_engine": "plain"})
        self.assertEqual(site_doc["metadata"]["process_config"], {"parser_engine": "plain"})

        file_knowledge = self.upload_knowledge(kb_id, "contract.py", "print('contract')", tag_id="tag-file", process_config={"file_mode": "fast"})
        self.assertEqual(file_knowledge["metadata"]["process_config"], {"file_mode": "fast"})

        duplicate_response = self.client.post(
            f"/api/v1/knowledge-bases/{kb_id}/knowledge/file",
            data={"file": SimpleUploadedFile("contract.py", b"print('contract')", content_type="text/plain")},
            **self.headers,
        )
        self.assertEqual(duplicate_response.status_code, 200)
        self.assertTrue(duplicate_response.json()["data"]["deduplicated"])
        self.assertEqual(duplicate_response.json()["data"]["knowledge"]["id"], file_knowledge["id"])
        self.assertEqual(Knowledge.objects.filter(knowledge_base_id=kb_id, file_name="contract.py", deleted_at__isnull=True).count(), 1)

        response = self.client.get(f"/api/v1/knowledge-bases/{kb_id}/knowledge?keyword=流程&tag_id=tag-a&page=1&page_size=1", **self.headers)
        data = response.json()["data"]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["page_size"], 1)
        self.assertEqual(data["items"][0]["id"], flow_doc["id"])

        response = self.client.get(f"/api/v1/knowledge-bases/{kb_id}/knowledge?source=file&file_type=md", **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["total"], 1)
        self.assertEqual(response.json()["data"]["items"][0]["id"], site_doc["id"])

        response = self.client.get("/api/v1/knowledge/search?keyword=站点&source=file&file_type=md&offset=0&limit=2", **self.headers)
        data = response.json()["data"]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["id"], site_doc["id"])
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["page_size"], 2)

        response = self.client.get(f"/api/v1/knowledge-bases/{kb_id}/knowledge/stats", **self.headers)
        stats = response.json()["data"]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(stats["knowledge_count"], 3)
        self.assertEqual(stats["completed"], 3)
        self.assertEqual(stats["processing"], 0)
        self.assertGreaterEqual(stats["chunk_count"], 3)

        response = self.client.post(
            f"/api/v1/knowledge/{flow_doc['id']}/reparse",
            data=json.dumps({"process_config": {"chunking_config": {"chunk_size": 384}}}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["knowledge"]["metadata"]["process_config"], {"chunking_config": {"chunk_size": 384}})
        self.assertEqual(response.json()["data"]["knowledge"]["metadata"]["process_overrides"], {"chunking_config": {"chunk_size": 384}})

        with patch("personal_knowledge_base.views.delete_knowledge_graph") as delete_graph, patch("personal_knowledge_base.views.rebuild_knowledge_graph") as rebuild_graph:
            response = self.client.post(
                "/api/v1/knowledge/move",
                data=json.dumps({"source_kb_id": kb_id, "target_kb_id": target_kb_id, "knowledge_ids": [flow_doc["id"]], "mode": "reuse_vectors"}),
                content_type="application/json",
                **self.headers,
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(delete_graph.called)
        self.assertTrue(rebuild_graph.called)
        self.assertEqual(response.json()["data"]["source_kb_id"], kb_id)
        self.assertEqual(response.json()["data"]["target_kb_id"], target_kb_id)
        self.assertEqual(response.json()["data"]["knowledge_count"], 1)
        response = self.client.get(f"/api/v1/knowledge/{flow_doc['id']}", **self.headers)
        self.assertEqual(response.json()["data"]["knowledge_base_id"], target_kb_id)

        response = self.client.post(
            "/api/v1/knowledge/batch-delete",
            data=json.dumps({"kb_id": kb_id, "ids": [site_doc["id"], file_knowledge["id"]]}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["deleted_count"], 2)
        self.assertEqual(response.json()["data"]["kb_id"], kb_id)
        response = self.client.get(f"/api/v1/knowledge-bases/{kb_id}/knowledge/stats", **self.headers)
        self.assertEqual(response.json()["data"]["knowledge_count"], 0)

    def test_manual_and_url_knowledge_ingestion_routes_are_removed(self):
        kb_id = self.client.post(
            "/api/v1/knowledge-bases",
            data=json.dumps({"name": "文件-only"}),
            content_type="application/json",
            **self.headers,
        ).json()["data"]["id"]

        response = self.client.post(
            f"/api/v1/knowledge-bases/{kb_id}/knowledge/manual",
            data=json.dumps({"title": "手工", "content": "内容"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 404)

        response = self.client.post(
            f"/api/v1/knowledge-bases/{kb_id}/knowledge/url",
            data=json.dumps({"title": "URL", "url": "https://example.test"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 404)

        response = self.client.put(
            "/api/v1/knowledge/manual/not-found",
            data=json.dumps({"title": "旧手工"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 404)

    def test_manual_url_cleanup_migration_deletes_legacy_rows(self):
        tenant = Tenant.objects.first()
        kb = KnowledgeBase.objects.create(tenant=tenant, name="遗留清理库")
        manual = Knowledge.objects.create(tenant=tenant, knowledge_base=kb, type="manual", title="手工", source="manual")
        url = Knowledge.objects.create(tenant=tenant, knowledge_base=kb, type="url", title="URL", source="https://example.test")
        file_item = Knowledge.objects.create(tenant=tenant, knowledge_base=kb, type="file", title="文件", source="file.txt")
        Chunk.objects.create(tenant=tenant, knowledge_base=kb, knowledge=manual, content="manual chunk", chunk_index=0)
        Chunk.objects.create(tenant=tenant, knowledge_base=kb, knowledge=url, content="url chunk", chunk_index=0)
        Chunk.objects.create(tenant=tenant, knowledge_base=kb, knowledge=file_item, content="file chunk", chunk_index=0)

        migration = import_module("personal_knowledge_base.migrations.0004_remove_manual_url_knowledge")
        schema_editor = type("SchemaEditor", (), {"connection": connection})()
        migration.cleanup_manual_url_knowledge(apps, schema_editor)

        self.assertFalse(Knowledge.objects.filter(id__in=[manual.id, url.id]).exists())
        self.assertFalse(Chunk.objects.filter(knowledge_id__in=[manual.id, url.id]).exists())
        self.assertTrue(Knowledge.objects.filter(id=file_item.id).exists())
        self.assertTrue(Chunk.objects.filter(knowledge_id=file_item.id).exists())

    def test_wiki_graph_overview_ego_types_and_search_contract(self):
        tenant = Tenant.objects.first()
        kb = KnowledgeBase.objects.create(tenant=tenant, name="Wiki 图谱库")
        pages = [
            ("summary/root", "Root", "summary", ["entity/a", "concept/b"]),
            ("entity/a", "Entity A", "entity", ["concept/b"]),
            ("concept/b", "Concept B", "concept", ["synthesis/c"]),
            ("synthesis/c", "Synthesis C", "synthesis", []),
            ("comparison/d", "Comparison D", "comparison", ["summary/root"]),
        ]
        for slug, title, page_type, refs in pages:
            WikiPage.objects.create(tenant=tenant, knowledge_base=kb, slug=slug, title=title, page_type=page_type, content=f"{title} body", out_links=refs)

        response = self.client.get(f"/api/v1/knowledge-bases/{kb.id}/wiki/graph?mode=overview&limit=2", **self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["meta"]["mode"], "overview")
        self.assertEqual(data["meta"]["returned"], 2)
        self.assertTrue(data["meta"]["truncated"])
        self.assertGreaterEqual(data["nodes"][0]["link_count"], data["nodes"][1]["link_count"])
        self.assertIn("link_count", data["nodes"][0])

        response = self.client.get(f"/api/v1/knowledge-bases/{kb.id}/wiki/graph?mode=ego&center=entity/a&depth=1&limit=10", **self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        slugs = {node["slug"] for node in data["nodes"]}
        self.assertEqual(data["meta"]["mode"], "ego")
        self.assertEqual(data["meta"]["center"], "entity/a")
        self.assertEqual(slugs, {"summary/root", "entity/a", "concept/b"})
        self.assertEqual({(edge["source"], edge["target"]) for edge in data["edges"]}, {("summary/root", "entity/a"), ("entity/a", "concept/b"), ("summary/root", "concept/b")})

        response = self.client.get(f"/api/v1/knowledge-bases/{kb.id}/wiki/graph?types=entity,concept&limit=10", **self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual({node["page_type"] for node in data["nodes"]}, {"entity", "concept"})
        self.assertEqual(data["edges"], [{"source": "entity/a", "target": "concept/b"}])

        response = self.client.get(f"/api/v1/knowledge-bases/{kb.id}/wiki/graph?mode=ego", **self.headers)
        self.assertEqual(response.status_code, 400)

        response = self.client.get(f"/api/v1/knowledge-bases/{kb.id}/wiki/search?q=Entity&limit=1", **self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["items"], data["pages"])
        self.assertEqual(data["items"][0]["slug"], "entity/a")

        response = self.client.get(f"/api/v1/knowledge-bases/{kb.id}/wiki/stats", **self.headers)
        self.assertEqual(response.status_code, 200)
        stats = response.json()["data"]
        self.assertEqual(stats["total_links"], 5)
        self.assertEqual(stats["orphan_count"], 0)

    def test_removed_data_source_types_do_not_expose_url_ingestion(self):
        response = self.client.get("/api/v1/data-sources/types", **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["items"], [])

    def test_wiki_enabled_upload_generates_pages_and_graph_links(self):
        response = self.client.post(
            "/api/v1/knowledge-bases",
            data=json.dumps({
                "name": "自动 Wiki 库",
                "indexing_strategy": {
                    "vector_enabled": True,
                    "keyword_enabled": True,
                    "wiki_enabled": True,
                    "graph_enabled": False,
                },
            }),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 201)
        kb_id = response.json()["data"]["id"]
        knowledge = self.upload_knowledge(kb_id, "Django 架构.md", "Django 使用 ORM 管理 SQLite 数据库。Django 支持 MTV 架构。")
        detail = self.client.get(f"/api/v1/knowledge/{knowledge['id']}", **self.headers).json()["data"]
        self.assertGreaterEqual(detail["metadata"]["wiki"]["pages"], 2)
        self.assertGreaterEqual(detail["metadata"]["wiki"]["links"], 1)

        response = self.client.get(f"/api/v1/knowledge-bases/{kb_id}/wiki/pages", **self.headers)
        self.assertEqual(response.status_code, 200)
        pages = response.json()["data"]["items"]
        self.assertTrue(any(page["page_type"] == "summary" for page in pages))
        self.assertTrue(any(page["page_type"] == "entity" for page in pages))
        entity_pages = [page for page in pages if page["page_type"] in {"entity", "concept"}]
        self.assertTrue(any(page["chunk_refs"] for page in entity_pages))
        self.assertTrue(any(ref.get("knowledge_id") == knowledge["id"] for page in entity_pages for ref in page["source_refs"]))
        self.assertTrue(any(page["out_links"] for page in pages if page["page_type"] == "summary"))
        self.assertEqual(WikiPendingOp.objects.filter(scope_id=kb_id).count(), 0)

        response = self.client.get(f"/api/v1/knowledge-bases/{kb_id}/wiki/stats", **self.headers)
        stats = response.json()["data"]
        self.assertGreaterEqual(stats["total_links"], 1)

        response = self.client.get(f"/api/v1/knowledge-bases/{kb_id}/wiki/graph?mode=overview&limit=20", **self.headers)
        graph = response.json()["data"]
        self.assertGreaterEqual(len(graph["nodes"]), 2)
        self.assertGreaterEqual(len(graph["edges"]), 1)

        response = self.client.delete(f"/api/v1/knowledge/{knowledge['id']}", **self.headers)
        self.assertEqual(response.status_code, 200)
        remaining_refs = [
            ref
            for page in WikiPage.objects.filter(knowledge_base_id=kb_id)
            for ref in (page.source_refs or [])
            if isinstance(ref, dict)
        ]
        self.assertFalse(any(ref.get("knowledge_id") == knowledge["id"] for ref in remaining_refs))
        self.assertEqual(WikiPendingOp.objects.filter(scope_id=kb_id).count(), 0)

    def test_preview_is_inline_and_download_is_attachment(self):
        kb_id = self.client.post(
            "/api/v1/knowledge-bases",
            data=json.dumps({"name": "预览下载库"}),
            content_type="application/json",
            **self.headers,
        ).json()["data"]["id"]
        knowledge = self.upload_knowledge(kb_id, "preview.txt", "预览内容")

        preview = self.client.get(f"/api/v1/knowledge/{knowledge['id']}/preview", **self.headers)
        self.assertEqual(preview.status_code, 200)
        self.assertIn("inline", preview["Content-Disposition"])

        download = self.client.get(f"/api/v1/knowledge/{knowledge['id']}/download", **self.headers)
        self.assertEqual(download.status_code, 200)
        self.assertIn("attachment", download["Content-Disposition"])
