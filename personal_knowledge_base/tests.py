import json
import time
from importlib import import_module
from unittest.mock import PropertyMock, patch

from django.apps import apps
from django.conf import settings
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.http import Http404
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import Resolver404, resolve
from django.utils import timezone

from .model_usage import usage_from_response
from .models import Chunk, Knowledge, KnowledgeBase, KnowledgeTag, Message, ModelConfig, ModelUsage, Session, TaskRecord, Tenant, WikiPage, WikiPendingOp
from .serializers import chunk_dict


class ChunkSerializerTests(TestCase):
    def test_chunk_dict_exposes_hierarchy_relationships(self):
        tenant = Tenant.objects.create(name="chunk-serializer-tenant", api_key="chunk-serializer-tenant")
        knowledge_base = KnowledgeBase.objects.create(tenant=tenant, name="chunk-serializer-kb")
        knowledge = Knowledge.objects.create(
            tenant=tenant,
            knowledge_base=knowledge_base,
            type="file",
            title="chunk-serializer.txt",
            source="chunk-serializer.txt",
        )
        chunk = Chunk.objects.create(
            tenant=tenant,
            knowledge_base=knowledge_base,
            knowledge=knowledge,
            content="chunk content",
            chunk_index=0,
            context_header="Guide > Install",
            context_parent_id="parent-text-chunk-id-000000000000001",
            media_parent_id="image-container-id-00000000000000001",
            anchor_chunk_id="text-child-chunk-id-00000000000000001",
            chunking_version="adaptive-v1",
        )

        data = chunk_dict(chunk)

        self.assertEqual(data["context_header"], "Guide > Install")
        self.assertEqual(data["context_parent_id"], "parent-text-chunk-id-000000000000001")
        self.assertEqual(data["media_parent_id"], "image-container-id-00000000000000001")
        self.assertEqual(data["anchor_chunk_id"], "text-child-chunk-id-00000000000000001")
        self.assertEqual(data["chunking_version"], "adaptive-v1")
        self.assertNotIn("parent_chunk_id", data)


@override_settings(ALLOW_AUTO_SETUP=True)
class KnowledgeApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        response = self.client.post("/api/v1/auth/auto-setup", content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {response.json()['data']['token']}"}
        self.kb_id = self.client.post(
            "/api/v1/knowledge-bases",
            data=json.dumps({"name": "Upload validation"}),
            content_type="application/json",
            **self.headers,
        ).json()["data"]["id"]

    def upload_file(self, name, content):
        return self.client.post(
            f"/api/v1/knowledge-bases/{self.kb_id}/knowledge/file",
            data={"file": SimpleUploadedFile(name, content, content_type="application/octet-stream")},
            **self.headers,
        )

    def test_unsupported_file_type(self):
        with patch("knowledge.views.default_storage.save", return_value="must-not-be-saved") as save_file, patch("knowledge.views.enqueue") as enqueue_task:
            enqueue_task.return_value.id = "must-not-be-created"
            response = self.upload_file("archive.epub", b"not-an-ebook")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "unsupported_file_type")
        self.assertEqual(Knowledge.objects.count(), 0)
        save_file.assert_not_called()
        enqueue_task.assert_not_called()


@override_settings(
    ALLOW_AUTO_SETUP=True,
    LLM_CHAT_API_KEY="",
    LLM_USE_ENV_CHAT=False,
    LLM_USE_ENV_SUMMARY=False,
    LLM_USE_ENV_TITLE=False,
    LLM_USE_ENV_QUESTION=False,
    LLM_USE_ENV_EXTRACT=False,
    LLM_USE_ENV_EMBEDDING=False,
    LLM_USE_ENV_RERANK=False,
    LLM_USE_ENV_VLM=False,
)
class PersonalKnowledgeBaseCoreFlowTests(TestCase):
    def setUp(self):
        self.client = Client()
        response = self.client.post("/api/v1/auth/auto-setup", content_type="application/json")
        self.assertEqual(response.status_code, 201)
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

    def test_route_cleanup_uses_split_apps_and_removes_old_wiki_aliases(self):
        expected_modules = {
            "/api/v1/auth/login": "accounts.views",
            "/api/v1/knowledge-bases": "knowledge.views",
            "/api/v1/knowledge-search": "knowledge.views",
            "/api/v1/sessions": "chat.views",
            "/api/v1/models": "models_config.views",
            "/api/v1/knowledge-bases/demo-kb/wiki/graph": "wiki.views",
            "/api/v1/knowledge-bases/demo-kb/wiki/move-page": "agent.views",
            "/api/v1/tenants/1/invitations": "personal_knowledge_base.views",
            "/api/v1/me/invitations": "personal_knowledge_base.views",
            "/api/v1/system/info": "personal_knowledge_base.views",
        }
        for path, module in expected_modules.items():
            self.assertEqual(resolve(path).func.__module__, module, path)

        deprecated_aliases = [
            "/api/v1/knowledgebase/demo-kb/wiki/pages",
            "/api/v1/knowledgebase/demo-kb/wiki/graph",
            "/api/v1/knowledgebase/demo-kb/wiki/move-page",
        ]
        for path in deprecated_aliases:
            with self.assertRaises(Resolver404, msg=path):
                resolve(path)

    def test_invalid_pagination_params_fall_back_to_defaults(self):
        response = self.client.post(
            "/api/v1/sessions",
            data=json.dumps({"title": "分页容错"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 201)
        session_id = response.json()["data"]["id"]

        response = self.client.get("/api/v1/knowledge-bases?page_size=bad&page=bad", **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["page"], 1)
        self.assertEqual(response.json()["data"]["page_size"], 20)

        response = self.client.get("/api/v1/knowledge-bases?limit=bad&offset=bad", **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["page"], 1)
        self.assertEqual(response.json()["data"]["page_size"], 20)

        response = self.client.get(f"/api/v1/messages/{session_id}/load?limit=bad", **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["items"], [])

    def test_invalid_search_topk_falls_back_to_default(self):
        response = self.client.post(
            "/api/v1/knowledge-bases",
            data=json.dumps({"name": "搜索容错库"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 201)
        kb_id = response.json()["data"]["id"]

        response = self.client.post(
            f"/api/v1/knowledge-bases/{kb_id}/hybrid-search",
            data=json.dumps({"query": "测试", "top_k": "bad"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            "/api/v1/knowledge-search",
            data=json.dumps({"query": "测试", "top_k": "bad"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 200)

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
        if settings.LLM_CHAT_API_KEY:
            self.assertNotIn(settings.LLM_CHAT_API_KEY, body)
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

    @patch("chat.views.delete_session_memory")
    def test_session_delete_matches_reference_contract(self, delete_session_memory):
        response = self.client.post("/api/v1/sessions", data=json.dumps({"title": "待删除对话"}), content_type="application/json", **self.headers)
        self.assertEqual(response.status_code, 201)
        session_id = response.json()["data"]["id"]
        response = self.client.delete(f"/api/v1/sessions/{session_id}", **self.headers)
        self.assertEqual(response.status_code, 200)
        delete_session_memory.assert_called_once_with(session_id)
        response = self.client.get("/api/v1/sessions", **self.headers)
        ids = {item["id"] for item in response.json()["data"]["items"]}
        self.assertNotIn(session_id, ids)

    @patch("chat.views.delete_session_memory")
    def test_session_batch_delete_cleans_neo4j_memory(self, delete_session_memory):
        first = self.client.post("/api/v1/sessions", data=json.dumps({"title": "批量删除一"}), content_type="application/json", **self.headers).json()["data"]
        second = self.client.post("/api/v1/sessions", data=json.dumps({"title": "批量删除二"}), content_type="application/json", **self.headers).json()["data"]

        response = self.client.delete(
            "/api/v1/sessions",
            data=json.dumps({"ids": [first["id"], second["id"]]}),
            content_type="application/json",
            **self.headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual({call.args[0] for call in delete_session_memory.call_args_list}, {first["id"], second["id"]})

    @patch("chat.views.delete_session_memory")
    def test_session_delete_all_cleans_neo4j_memory_for_tenant_sessions(self, delete_session_memory):
        first = self.client.post("/api/v1/sessions", data=json.dumps({"title": "全部删除一"}), content_type="application/json", **self.headers).json()["data"]
        second = self.client.post("/api/v1/sessions", data=json.dumps({"title": "全部删除二"}), content_type="application/json", **self.headers).json()["data"]

        response = self.client.delete(
            "/api/v1/sessions",
            data=json.dumps({"delete_all": True}),
            content_type="application/json",
            **self.headers,
        )

        self.assertEqual(response.status_code, 200)
        cleaned_ids = {call.args[0] for call in delete_session_memory.call_args_list}
        self.assertTrue({first["id"], second["id"]}.issubset(cleaned_ids))

    @patch("chat.views.delete_session_memory")
    def test_session_messages_clear_cleans_neo4j_memory(self, delete_session_memory):
        session = Session.objects.create(tenant=Tenant.objects.first(), title="清空消息")

        response = self.client.delete(f"/api/v1/sessions/{session.id}/messages", **self.headers)

        self.assertEqual(response.status_code, 200)
        delete_session_memory.assert_called_once_with(session.id)

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

    def test_chat_request_id_is_idempotent_within_session(self):
        tenant = Tenant.objects.first()
        session = Session.objects.create(tenant=tenant, title="幂等测试")
        request_id = "fixed-request-id"
        Message.objects.create(session=session, request_id=request_id, role="user", content="你好", is_completed=True)
        assistant = Message.objects.create(session=session, request_id=request_id, role="assistant", content="已有回答", is_completed=True)

        response = self.client.post(
            f"/api/v1/knowledge-chat/{session.id}",
            data=json.dumps({"query": "你好"}),
            content_type="application/json",
            HTTP_X_REQUEST_ID=request_id,
            **self.headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["idempotent"])
        self.assertEqual(response.json()["data"]["message"]["id"], assistant.id)
        self.assertEqual(Message.objects.filter(session=session, request_id=request_id).count(), 2)

    def test_session_state_normalizes_summary_and_dirty_config(self):
        response = self.client.post(
            "/api/v1/sessions",
            data=json.dumps({"title": "脏配置", "agent_config": "invalid-config-value"}),
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
                    "summary_model_id": "summary-model",
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
        self.assertEqual(state["summary_model_id"], "summary-model")
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

    def test_chunking_config_reindex_state_contract(self):
        effective_config = {
            "strategy": "heading",
            "chunk_size": 512,
            "chunk_overlap": 0,
            "enable_parent_child": True,
            "parent_chunk_size": 2048,
            "child_chunk_size": 384,
            "child_chunk_overlap": 0,
            "token_limit": 0,
            "semantic_window_size": 3,
            "semantic_breakpoint_percentile": 90.0,
        }
        response = self.client.post(
            "/api/v1/knowledge-bases",
            data=json.dumps({"name": "Chunking state", "chunking_config": effective_config}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 201)
        kb_id = response.json()["data"]["id"]
        kb = KnowledgeBase.objects.get(id=kb_id)
        self.assertEqual(response.json()["data"]["chunking_config"], effective_config)

        knowledge = Knowledge.objects.create(
            tenant=kb.tenant,
            knowledge_base=kb,
            type="file",
            title="processed.txt",
            source="processed.txt",
            parse_status="completed",
            processed_at=timezone.now(),
            metadata={
                "effective_chunking_config": effective_config,
                "chunking_diagnostics": {"requested_strategy": "heading", "selected_strategy": "heading"},
            },
        )
        initial = self.client.get(f"/api/v1/knowledge-bases/{kb_id}", **self.headers).json()["data"]
        self.assertFalse(initial["needs_reindex"])
        self.assertEqual(initial["last_effective_strategy"], "heading")

        requested_config = {
            "strategy": "semantic",
            "chunk_size": 640,
            "chunk_overlap": 0,
            "enable_parent_child": True,
            "parent_chunk_size": 2304,
            "child_chunk_size": 320,
            "child_chunk_overlap": 0,
            "token_limit": 0,
            "semantic_window_size": 5,
            "semantic_breakpoint_percentile": 92.5,
        }
        response = self.client.put(
            f"/api/v1/knowledge-bases/{kb_id}",
            data=json.dumps({"chunking_config": requested_config}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        pending = response.json()["data"]
        self.assertEqual(pending["chunking_config"], requested_config)
        self.assertTrue(pending["needs_reindex"])
        self.assertEqual(pending["last_effective_strategy"], "heading")

        metadata = dict(knowledge.metadata)
        metadata["process_config"] = {"chunking_config": requested_config}
        knowledge.metadata = metadata
        knowledge.parse_status = "processing"
        knowledge.save(update_fields=["metadata", "parse_status", "updated_at"])
        processing = self.client.get(f"/api/v1/knowledge-bases/{kb_id}", **self.headers).json()["data"]
        self.assertTrue(processing["needs_reindex"])
        self.assertEqual(processing["last_effective_strategy"], "heading")

        metadata["effective_chunking_config"] = requested_config
        metadata["chunking_diagnostics"] = {"requested_strategy": "semantic", "selected_strategy": "semantic"}
        knowledge.metadata = metadata
        knowledge.parse_status = "completed"
        knowledge.processed_at = timezone.now()
        knowledge.save(update_fields=["metadata", "parse_status", "processed_at", "updated_at"])
        completed = self.client.get(f"/api/v1/knowledge-bases/{kb_id}", **self.headers).json()["data"]
        self.assertFalse(completed["needs_reindex"])
        self.assertEqual(completed["last_effective_strategy"], "semantic")

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
        def entity_batch(chunks, *_args, **_kwargs):
            return [{"node": [{**node, "chunks": [chunk.id]} for node in entity_payload["node"]], "relation": []} for chunk in chunks]

        with patch("personal_knowledge_base.graph_rag.Neo4jGraphRepository.available", new_callable=PropertyMock, return_value=True), patch("personal_knowledge_base.graph_rag.graph_repository.add_graph") as add_graph, patch("personal_knowledge_base.graph_rag.graph_repository.delete_graph") as delete_graph, patch("personal_knowledge_base.graph_rag.extract_entities_for_batch", side_effect=entity_batch) as extract_entities, patch("personal_knowledge_base.graph_rag.extract_relationships_for_batch", return_value=relation_payload) as extract_relations:
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

    @override_settings(NEO4J_ENABLE=False)
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
        self.assertEqual({item["stage"] for item in warnings}, {"graph", "summary", "questions", "metadata", "wiki"})
        self.assertEqual(detail["metadata"]["generated_questions"], [])
        self.assertEqual(detail["metadata"]["extracted_metadata"], {})

    def test_delete_knowledge_removes_backend_processing_task(self):
        kb_id = self.client.post(
            "/api/v1/knowledge-bases",
            data=json.dumps({"name": "删除任务测试库"}),
            content_type="application/json",
            **self.headers,
        ).json()["data"]["id"]
        knowledge_base = KnowledgeBase.objects.get(id=kb_id)
        knowledge = Knowledge.objects.create(
            tenant=knowledge_base.tenant,
            knowledge_base_id=kb_id,
            type="file",
            title="deleting.txt",
            file_name="deleting.txt",
            parse_status="processing",
        )
        task = TaskRecord.objects.create(
            task_type="process_knowledge",
            status="running",
            payload={"knowledge_id": knowledge.id, "_worker_token": "owner"},
        )
        cache.set(f"task:{task.id}", {"status": "running"}, timeout=86400)

        response = self.client.delete(f"/api/v1/knowledge/{knowledge.id}", **self.headers)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(TaskRecord.objects.filter(id=task.id).exists())
        self.assertIsNone(cache.get(f"task:{task.id}"))
        knowledge.refresh_from_db()
        self.assertEqual(knowledge.parse_status, "cancelled")
        self.assertIsNotNone(knowledge.deleted_at)

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

    def test_model_usage_cache_series_contract(self):
        tenant = Tenant.objects.get(id=1)
        now = timezone.now().replace(minute=20, second=0, microsecond=0)
        old = now - timezone.timedelta(hours=1)
        records = [
            ("chat-a", "deepseek-v4", old, 100, 40, 140),
            ("chat-a", "deepseek-v4", now, 300, 150, 420),
            ("chat-b", "qwen-plus", now, 200, 50, 260),
        ]
        for model_id, model_name, created_at, prompt_tokens, cached_tokens, total_tokens in records:
            usage = ModelUsage.objects.create(
                tenant=tenant,
                model_id=model_id,
                model_name=model_name,
                model_type="chat",
                provider="openai",
                scenario="agent_reasoning",
                prompt_tokens=prompt_tokens,
                completion_tokens=total_tokens - prompt_tokens,
                total_tokens=total_tokens,
                cached_tokens=cached_tokens,
            )
            ModelUsage.objects.filter(id=usage.id).update(created_at=created_at)

        response = self.client.get("/api/v1/models/usage?range=1&granularity=hour", **self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["cache"]["prompt_rate"], 0.4)
        self.assertEqual(data["cache"]["total_rate"], 0.2927)
        self.assertEqual(data["cache_series"]["granularity"], "hour")
        self.assertGreaterEqual(len(data["cache_series"]["buckets"]), 2)
        models = data["cache_series"]["models"]
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0]["model_key"], "group:chat")
        self.assertEqual(models[0]["model_name"], "对话")
        self.assertEqual(models[0]["model_group"], "chat")
        self.assertEqual(models[0]["cache_hit_rate"], 0.4)
        self.assertEqual(models[0]["cache_total_rate"], 0.2927)
        points = models[0]["points"]
        self.assertEqual(len(points), len(data["cache_series"]["buckets"]))
        self.assertTrue(any(point["prompt_tokens"] == 0 and point["cache_hit_rate"] == 0 for point in points))

        response = self.client.get("/api/v1/models/usage?range=1&granularity=15m", **self.headers)
        self.assertEqual(response.json()["data"]["cache_series"]["granularity"], "15m")

    def test_model_usage_cache_series_merges_same_provider_model_name(self):
        tenant = Tenant.objects.get(id=1)
        for model_id, scenario, prompt_tokens in [
            ("env-aliyun-bailian-chat", "chat", 100),
            ("env-aliyun-bailian-summary", "summary", 200),
            ("env-aliyun-bailian-extract", "graph_entity_extract", 300),
            ("env-aliyun-bailian-question", "question", 400),
        ]:
            ModelUsage.objects.create(
                tenant=tenant,
                model_id=model_id,
                model_name="qwen3.6-flash",
                model_type=scenario,
                provider="aliyun-bailian",
                scenario=scenario,
                prompt_tokens=prompt_tokens,
                total_tokens=prompt_tokens + 10,
                cached_tokens=prompt_tokens // 2,
            )

        response = self.client.get("/api/v1/models/usage?range=7&granularity=day", **self.headers)
        self.assertEqual(response.status_code, 200)
        models = response.json()["data"]["cache_series"]["models"]
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0]["model_name"], "对话")
        self.assertEqual(models[0]["model_key"], "group:chat")
        self.assertEqual(models[0]["prompt_tokens"], 100)
        self.assertEqual(models[0]["cache_hit_rate"], 0.5)

    def test_model_usage_cache_series_only_uses_frontend_model_groups(self):
        tenant = Tenant.objects.get(id=1)
        records = [
            ("chat-model", "qwen-chat", "chat", 100, 50),
            ("embedding-model", "text-embedding-v4", "Embedding", 200, 100),
            ("rerank-model", "qwen-rerank", "Rerank", 300, 150),
            ("vision-model", "qwen-vl", "VLLM", 400, 200),
            ("summary-model", "qwen-summary", "summary", 500, 500),
            ("title-model", "qwen-title", "title", 600, 600),
            ("question-model", "qwen-question", "question", 700, 700),
            ("extract-model", "qwen-extract", "extract", 800, 800),
        ]
        for model_id, model_name, model_type, prompt_tokens, cached_tokens in records:
            ModelUsage.objects.create(
                tenant=tenant,
                model_id=model_id,
                model_name=model_name,
                model_type=model_type,
                provider="aliyun-bailian",
                scenario=model_type,
                prompt_tokens=prompt_tokens,
                total_tokens=prompt_tokens + 20,
                cached_tokens=cached_tokens,
            )

        response = self.client.get("/api/v1/models/usage?range=7&granularity=day", **self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        models = data["cache_series"]["models"]
        self.assertEqual(data["cache"]["prompt_rate"], 0.5)
        self.assertEqual({item["model_group"] for item in models}, {"chat", "embedding", "rerank", "vlm"})
        self.assertEqual([item["model_name"] for item in models], ["对话", "Embedding", "ReRank", "视觉"])
        self.assertNotIn("qwen-summary", {item["model_name"] for item in models})

    def test_usage_from_response_reads_cached_tokens_variants(self):
        nested = usage_from_response({
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "prompt_tokens_details": {"cached_tokens": 35},
            }
        })
        self.assertEqual(nested["cached_tokens"], 35)
        top_level = usage_from_response({
            "usage": {
                "input_tokens": 90,
                "output_tokens": 10,
                "cached_tokens": 27,
            }
        })
        self.assertEqual(top_level["prompt_tokens"], 90)
        self.assertEqual(top_level["cached_tokens"], 27)

    def test_record_model_usage_skips_internal_text_roles(self):
        from .model_usage import record_model_usage

        tenant = Tenant.objects.get(id=1)
        for role in ["summary", "title", "question", "extract"]:
            record_model_usage(
                tenant,
                model_id=f"env-aliyun-bailian-{role}",
                model_name="qwen3.6-flash",
                model_type=role,
                provider="aliyun-bailian",
                scenario=role,
                prompt_tokens=100,
                total_tokens=120,
                cached_tokens=60,
            )
        record_model_usage(
            tenant,
            model_id="env-aliyun-bailian-chat",
            model_name="qwen3.6-flash",
            model_type="chat",
            provider="aliyun-bailian",
            scenario="chat",
            prompt_tokens=100,
            total_tokens=120,
            cached_tokens=60,
        )

        self.assertEqual(ModelUsage.objects.count(), 1)
        self.assertEqual(ModelUsage.objects.get().model_type, "chat")

    def test_chat_completion_raw_records_provider_cached_usage(self):
        from .model_providers import chat_completion_raw

        tenant = Tenant.objects.get(id=1)
        ModelConfig.objects.create(
            id="deepseek-chat",
            tenant=tenant,
            name="deepseek-v4",
            display_name="DeepSeek V4",
            type="KnowledgeQA",
            source="deepseek",
            parameters={"base_url": "https://example.test/v1", "api_key": "sk-test", "model": "deepseek-v4"},
            is_default=True,
        )

        with patch("personal_knowledge_base.model_providers.openai_compatible_chat_raw") as raw:
            raw.return_value = {
                "choices": [{"message": {"content": "ok", "tool_calls": []}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 1200,
                    "completion_tokens": 80,
                    "total_tokens": 1280,
                    "prompt_tokens_details": {"cached_tokens": 900},
                },
            }
            result = chat_completion_raw(
                tenant,
                [{"role": "user", "content": "hello"}],
                model_id="deepseek-chat",
                tools=[{"type": "function", "function": {"name": "search", "description": "", "parameters": {}}}],
            )

        self.assertEqual(result["content"], "ok")
        usage = ModelUsage.objects.filter(model_id="deepseek-chat", scenario="agent_reasoning").latest("created_at")
        self.assertEqual(usage.prompt_tokens, 1200)
        self.assertEqual(usage.cached_tokens, 900)
        self.assertEqual(usage.total_tokens, 1280)

    def test_trace_llm_call_does_not_create_zero_token_usage_record(self):
        from .observability import TraceContext, trace_llm_call

        tenant = Tenant.objects.get(id=1)
        trace = TraceContext(metadata={"tenant_id": tenant.id})
        with trace_llm_call(trace, model="deepseek-v4", messages=[{"role": "user", "content": "hello"}]) as span:
            span["content"] = "ok"

        self.assertFalse(ModelUsage.objects.filter(provider="agent", scenario="agent_reasoning", total_tokens=0).exists())

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
        chunk_id = next(
            item["id"] for item in response.json()["data"]["items"] if item["chunk_type"] == "text"
        )

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

    def test_models_use_primary_type_contract(self):
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
        chat_alias_items = response.json()["data"]["items"]
        self.assertEqual({item["id"] for item in chat_alias_items}, {item["id"] for item in knowledgeqa_items})

        response = self.client.post(
            "/api/v1/models",
            data=json.dumps(
                {
                    "id": "knowledge-type-chat",
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

    def test_audio_video_uploads_are_rejected_before_storage_or_task_creation(self):
        kb_id = self.client.post(
            "/api/v1/knowledge-bases",
            data=json.dumps({"name": "仅文档与图片"}),
            content_type="application/json",
            **self.headers,
        ).json()["data"]["id"]
        removed_extensions = ["mp3", "wav", "m4a", "aac", "ogg", "flac", "mp4", "mov", "avi", "mkv", "webm"]

        with patch("knowledge.views.default_storage.save", return_value="must-not-be-saved") as save_file, patch("knowledge.views.enqueue") as enqueue_task:
            enqueue_task.return_value.id = "must-not-be-created"
            for extension in removed_extensions:
                with self.subTest(extension=extension):
                    response = self.client.post(
                        f"/api/v1/knowledge-bases/{kb_id}/knowledge/file",
                        data={"file": SimpleUploadedFile(f"sample.{extension}", b"binary", content_type="application/octet-stream")},
                        **self.headers,
                    )
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response.json()["error"]["code"], "unsupported_file_type")

        save_file.assert_not_called()
        enqueue_task.assert_not_called()
        self.assertFalse(Knowledge.objects.filter(knowledge_base_id=kb_id).exists())

    def test_image_upload_remains_supported(self):
        kb_id = self.client.post(
            "/api/v1/knowledge-bases",
            data=json.dumps({"name": "图片保留库"}),
            content_type="application/json",
            **self.headers,
        ).json()["data"]["id"]

        with patch("knowledge.views.default_storage.save", return_value="tenant/diagram.png"), patch("knowledge.views.enqueue") as enqueue_task:
            enqueue_task.return_value.id = "image-task"
            response = self.client.post(
                f"/api/v1/knowledge-bases/{kb_id}/knowledge/file",
                data={"file": SimpleUploadedFile("diagram.PNG", b"image", content_type="image/png")},
                **self.headers,
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["data"]["knowledge"]["file_type"], "png")
        enqueue_task.assert_called_once()

    def test_asr_model_and_check_endpoint_are_retired(self):
        response = self.client.get("/api/v1/system/info", **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("asr", response.json()["data"]["bailian"]["roles"])

        response = self.client.get("/api/v1/models/providers", **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(all("asr" not in provider["types"] for provider in response.json()["data"]["items"]))

        response = self.client.post(
            "/api/v1/models",
            data=json.dumps({"name": "removed-asr", "type": "ASR", "source": "openai"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "unsupported_model_type")

        response = self.client.get("/api/v1/initialization/asr/check", **self.headers)
        self.assertEqual(response.status_code, 404)

    def test_knowledge_contract_filters_process_config_stats_batch_and_move(self):
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
        kb = KnowledgeBase.objects.get(id=kb_id)
        for tag_id in ["tag-a", "tag-b", "tag-file"]:
            KnowledgeTag.objects.create(id=tag_id, tenant=kb.tenant, knowledge_base=kb, name=tag_id)

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

        with patch("knowledge.views.delete_knowledge_graph") as delete_graph, patch("knowledge.views.rebuild_knowledge_graph") as rebuild_graph:
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
            data=json.dumps({"title": "手工"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 404)

    def test_manual_url_cleanup_migration_deletes_removed_type_rows(self):
        tenant = Tenant.objects.first()
        kb = KnowledgeBase.objects.create(tenant=tenant, name="清理库")
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

    def test_audio_video_cleanup_migration_removes_media_and_asr_data_only(self):
        migration_path = settings.BASE_DIR / "personal_knowledge_base" / "migrations" / "0012_remove_audio_video_support.py"
        self.assertTrue(migration_path.exists(), "audio/video cleanup migration must exist")

        tenant = Tenant.objects.first()
        kb = KnowledgeBase.objects.create(tenant=tenant, name="媒体清理库")
        audio = Knowledge.objects.create(tenant=tenant, knowledge_base=kb, type="file", title="录音", file_name="record.MP3", file_type="MP3", file_path="tenant/audio.mp3")
        video = Knowledge.objects.create(tenant=tenant, knowledge_base=kb, type="file", title="视频", file_name="clip.WEBM", file_type="", file_path="tenant/clip.webm")
        text = Knowledge.objects.create(tenant=tenant, knowledge_base=kb, type="file", title="文档", file_name="notes.txt", file_type="txt", file_path="tenant/notes.txt")
        image = Knowledge.objects.create(tenant=tenant, knowledge_base=kb, type="file", title="图片", file_name="diagram.png", file_type="png", file_path="tenant/diagram.png")
        Chunk.objects.create(tenant=tenant, knowledge_base=kb, knowledge=audio, content="audio", chunk_index=0)
        Chunk.objects.create(tenant=tenant, knowledge_base=kb, knowledge=video, content="video", chunk_index=0)
        Chunk.objects.create(tenant=tenant, knowledge_base=kb, knowledge=text, content="text", chunk_index=0)
        Chunk.objects.create(tenant=tenant, knowledge_base=kb, knowledge=image, content="image", chunk_index=0)
        ModelConfig.objects.create(id="legacy-asr", tenant=tenant, name="legacy", type="ASR", source="openai")
        ModelUsage.objects.create(tenant=tenant, model_id="env-legacy-asr", model_name="legacy", model_type="asr", scenario="asr")

        migration = import_module("personal_knowledge_base.migrations.0012_remove_audio_video_support")
        schema_editor = type("SchemaEditor", (), {"connection": connection})()
        with patch.object(migration.default_storage, "delete") as delete_file:
            migration.remove_audio_video_data(apps, schema_editor)

        self.assertFalse(Knowledge.objects.filter(id__in=[audio.id, video.id]).exists())
        self.assertFalse(Chunk.objects.filter(knowledge_id__in=[audio.id, video.id]).exists())
        self.assertEqual(Knowledge.objects.filter(id__in=[text.id, image.id]).count(), 2)
        self.assertEqual(Chunk.objects.filter(knowledge_id__in=[text.id, image.id]).count(), 2)
        self.assertEqual({call.args[0] for call in delete_file.call_args_list}, {"tenant/audio.mp3", "tenant/clip.webm"})
        self.assertFalse(ModelConfig.objects.filter(id="legacy-asr").exists())
        self.assertFalse(ModelUsage.objects.filter(model_id="env-legacy-asr").exists())

    def test_wiki_graph_overview_ego_types_and_search_contract(self):
        tenant = Tenant.objects.first()
        kb = KnowledgeBase.objects.create(tenant=tenant, name="Wiki 图谱库")
        WikiPage.objects.create(
            tenant=tenant,
            knowledge_base=kb,
            slug="index",
            title="Wiki 目录",
            page_type="index",
            summary="自动生成的 Wiki 页面索引。",
            content="Root links",
            out_links=["summary/root", "entity/a"],
        )
        pages = [
            ("summary/root", "Root", "summary", ["entity/a", "concept/b", "page/extra"]),
            ("entity/a", "Entity A", "entity", ["concept/b"]),
            ("concept/b", "Concept B", "concept", ["page/extra"]),
            ("page/extra", "Extra Page", "page", ["summary/root"]),
        ]
        for slug, title, page_type, refs in pages:
            WikiPage.objects.create(tenant=tenant, knowledge_base=kb, slug=slug, title=title, page_type=page_type, content=f"{title} body", out_links=refs)

        response = self.client.get(f"/api/v1/knowledge-bases/{kb.id}/wiki/graph?mode=overview&limit=2", **self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["meta"]["mode"], "overview")
        self.assertEqual(data["meta"]["returned"], 2)
        self.assertTrue(data["meta"]["truncated"])
        self.assertNotIn("index", {node["slug"] for node in data["nodes"]})
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

        response = self.client.get(f"/api/v1/knowledge-bases/{kb.id}/wiki/pages", **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("index", {page["slug"] for page in response.json()["data"]["items"]})

        response = self.client.get(f"/api/v1/knowledge-bases/{kb.id}/wiki/index", **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("index", {page["slug"] for page in response.json()["data"]["items"]})
        self.assertNotIn("index", {group["type"] for group in response.json()["data"]["groups"]})

        response = self.client.get(f"/api/v1/knowledge-bases/{kb.id}/wiki/search?q=Wiki&limit=10", **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("index", {page["slug"] for page in response.json()["data"]["items"]})

        response = self.client.get(f"/api/v1/knowledge-bases/{kb.id}/wiki/pages/index", **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["slug"], "index")

        response = self.client.get(f"/api/v1/knowledge-bases/{kb.id}/wiki/stats", **self.headers)
        self.assertEqual(response.status_code, 200)
        stats = response.json()["data"]
        self.assertEqual(stats["total_links"], 6)
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


@override_settings(
    ALLOW_AUTO_SETUP=True,
    LLM_USE_ENV_EMBEDDING=False,
    LLM_USE_ENV_RERANK=False,
)
class ChunkHierarchyMutationTests(TestCase):
    def setUp(self):
        self.client = Client()
        response = self.client.post("/api/v1/auth/auto-setup", content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {response.json()['data']['token']}"}
        self.tenant = Tenant.objects.first()
        self.kb = KnowledgeBase.objects.create(tenant=self.tenant, name="hierarchy-mutations")
        self.knowledge = Knowledge.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            type="file",
            title="Hierarchy",
            source="hierarchy.txt",
        )
        self.parent = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.knowledge,
            content="abcdefghij",
            chunk_index=0,
            chunk_type="parent_text",
            is_enabled=False,
            start_at=0,
            end_at=10,
        )
        self.child = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.knowledge,
            content="cdef",
            chunk_index=1,
            context_parent_id=self.parent.id,
            start_at=2,
            end_at=6,
            seq_id=9201,
        )

    def seed_physical_index(self, chunk, text=None):
        from .search import ensure_search_tables, pack_embedding

        ensure_search_tables()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM chunks_fts WHERE chunk_id = %s", [chunk.id])
            cursor.execute("DELETE FROM chunk_embeddings_vec WHERE rowid = %s", [chunk.seq_id])
            cursor.execute(
                "INSERT INTO chunks_fts(chunk_id, tenant_id, knowledge_base_id, knowledge_id, title, content) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                [chunk.id, self.tenant.id, self.kb.id, self.knowledge.id, self.knowledge.title, text or chunk.content],
            )
            cursor.execute(
                "INSERT INTO chunk_embeddings_vec(rowid, embedding) VALUES (%s, %s)",
                [chunk.seq_id, pack_embedding([0.1] * settings.LLM_EMBEDDING_DIM)],
            )

    def index_counts(self, chunk):
        with connection.cursor() as cursor:
            fts = cursor.execute("SELECT COUNT(*) FROM chunks_fts WHERE chunk_id = %s", [chunk.id]).fetchone()[0]
            vector = cursor.execute(
                "SELECT COUNT(*) FROM chunk_embeddings_vec WHERE rowid = %s", [chunk.seq_id]
            ).fetchone()[0]
        return fts, vector

    def test_parent_and_image_container_mutations_are_rejected_with_stable_errors(self):
        container = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.knowledge,
            content="[image]",
            chunk_index=2,
            chunk_type="image_container",
            is_enabled=False,
        )
        cases = [
            ("put", self.parent.id, "chunk_parent_read_only"),
            ("delete", self.parent.id, "chunk_parent_read_only"),
            ("put", container.id, "chunk_container_read_only"),
            ("delete", container.id, "chunk_container_read_only"),
        ]
        for method, chunk_id, code in cases:
            with self.subTest(method=method, code=code):
                response = getattr(self.client, method)(
                    f"/api/v1/chunks/{self.knowledge.id}/{chunk_id}",
                    data=json.dumps({"content": "forbidden"}),
                    content_type="application/json",
                    **self.headers,
                )
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json()["error"]["code"], code)
                self.assertTrue(Chunk.objects.filter(id=chunk_id).exists())

    def test_legacy_personal_view_uses_same_read_only_policy(self):
        from . import views as personal_views

        factory = RequestFactory()
        for method in ("put", "delete"):
            with self.subTest(method=method):
                request = getattr(factory, method)(
                    f"/legacy/chunks/{self.knowledge.id}/{self.parent.id}",
                    data=json.dumps({"content": "forbidden"}),
                    content_type="application/json",
                    **self.headers,
                )
                response = personal_views.chunks_collection(
                    request, knowledge_id=self.knowledge.id, chunk_id=self.parent.id
                )
                self.assertEqual(response.status_code, 409)
                self.assertEqual(json.loads(response.content)["error"]["code"], "chunk_parent_read_only")

    def test_text_child_edit_preserves_hierarchy_and_reindexes_overlay_content(self):
        from .parent_context import resolve_parent_context

        self.seed_physical_index(self.child, "old indexed content")
        with (
            patch(
                "personal_knowledge_base.model_providers.embedding",
                return_value=[[0.25] * settings.LLM_EMBEDDING_DIM],
            ),
            patch("personal_knowledge_base.model_providers.embedding_signature", return_value="test:dim"),
        ):
            response = self.client.put(
                f"/api/v1/chunks/{self.knowledge.id}/{self.child.id}",
                data=json.dumps({"content": "EDIT", "metadata": {"edited": True}}),
                content_type="application/json",
                **self.headers,
            )

        self.assertEqual(response.status_code, 200)
        self.child.refresh_from_db()
        self.assertEqual((self.child.start_at, self.child.end_at), (2, 6))
        self.assertEqual(self.child.context_parent_id, self.parent.id)
        self.assertEqual(self.index_counts(self.child), (1, 1))
        with connection.cursor() as cursor:
            indexed = cursor.execute(
                "SELECT content FROM chunks_fts WHERE chunk_id = %s", [self.child.id]
            ).fetchone()[0]
        self.assertIn("EDIT", indexed)
        resolved = resolve_parent_context(
            [
                {
                    "chunk_id": self.child.id,
                    "id": self.child.id,
                    "content": self.child.content,
                    "chunk_type": "text",
                    "retrieval_path": "document",
                    "knowledge_id": self.knowledge.id,
                    "knowledge_base_id": self.kb.id,
                    "score": 1.0,
                }
            ],
            tenant_id=self.tenant.id,
            max_context_chars=100,
        )
        self.assertEqual(resolved[0]["content"], "abEDITghij")

    def test_disabling_only_text_child_removes_indexes_parent_and_media_anchor(self):
        self.seed_physical_index(self.child)
        media = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.knowledge,
            content="caption",
            chunk_index=3,
            chunk_type="image_caption",
            anchor_chunk_id=self.child.id,
        )

        response = self.client.put(
            f"/api/v1/chunks/{self.knowledge.id}/{self.child.id}",
            data=json.dumps({"is_enabled": False}),
            content_type="application/json",
            **self.headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.index_counts(self.child), (0, 0))
        self.assertFalse(Chunk.objects.filter(id=self.parent.id).exists())
        self.child.refresh_from_db()
        media.refresh_from_db()
        self.assertIsNone(self.child.context_parent_id)
        self.assertIsNone(media.anchor_chunk_id)

    def test_deleting_last_enabled_text_child_repairs_disabled_sibling_and_anchor(self):
        disabled_sibling = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.knowledge,
            content="disabled",
            chunk_index=2,
            context_parent_id=self.parent.id,
            is_enabled=False,
        )
        media = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.knowledge,
            content="ocr",
            chunk_index=3,
            chunk_type="image_ocr",
            anchor_chunk_id=self.child.id,
        )
        self.seed_physical_index(self.child)

        response = self.client.delete(f"/api/v1/chunks/by-id/{self.child.id}", **self.headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.index_counts(self.child), (0, 0))
        self.assertFalse(Chunk.objects.filter(id=self.parent.id).exists())
        disabled_sibling.refresh_from_db()
        media.refresh_from_db()
        self.assertIsNone(disabled_sibling.context_parent_id)
        self.assertIsNone(media.anchor_chunk_id)

    def test_media_disable_reenable_preserves_valid_text_anchor(self):
        for index, chunk_type in enumerate(("image_ocr", "image_caption"), start=10):
            with self.subTest(chunk_type=chunk_type):
                anchor = Chunk.objects.create(
                    tenant=self.tenant,
                    knowledge_base=self.kb,
                    knowledge=self.knowledge,
                    content=f"anchor-{chunk_type}",
                    chunk_index=index * 2,
                )
                media = Chunk.objects.create(
                    tenant=self.tenant,
                    knowledge_base=self.kb,
                    knowledge=self.knowledge,
                    content=f"media-{chunk_type}",
                    chunk_index=index * 2 + 1,
                    chunk_type=chunk_type,
                    anchor_chunk_id=anchor.id,
                )

                disabled = self.client.put(
                    f"/api/v1/chunks/{self.knowledge.id}/{media.id}",
                    data=json.dumps({"is_enabled": False}),
                    content_type="application/json",
                    **self.headers,
                )
                self.assertEqual(disabled.status_code, 200)
                media.refresh_from_db()
                self.assertEqual(media.anchor_chunk_id, anchor.id)

                enabled = self.client.patch(
                    f"/api/v1/chunks/by-id/{media.id}",
                    data=json.dumps({"is_enabled": True}),
                    content_type="application/json",
                    **self.headers,
                )
                self.assertEqual(enabled.status_code, 200)
                media.refresh_from_db()
                self.assertEqual(media.anchor_chunk_id, anchor.id)

    def test_media_reenable_clears_saved_anchor_that_became_disabled_or_deleted(self):
        cases = (("image_ocr", "disabled"), ("image_caption", "deleted"))
        for index, (chunk_type, target_state) in enumerate(cases, start=20):
            with self.subTest(chunk_type=chunk_type, target_state=target_state):
                anchor = Chunk.objects.create(
                    tenant=self.tenant,
                    knowledge_base=self.kb,
                    knowledge=self.knowledge,
                    content=f"stale-anchor-{target_state}",
                    chunk_index=index * 2,
                )
                media = Chunk.objects.create(
                    tenant=self.tenant,
                    knowledge_base=self.kb,
                    knowledge=self.knowledge,
                    content=f"stale-media-{target_state}",
                    chunk_index=index * 2 + 1,
                    chunk_type=chunk_type,
                    anchor_chunk_id=anchor.id,
                )

                disabled = self.client.put(
                    f"/api/v1/chunks/{self.knowledge.id}/{media.id}",
                    data=json.dumps({"is_enabled": False}),
                    content_type="application/json",
                    **self.headers,
                )
                self.assertEqual(disabled.status_code, 200)
                media.refresh_from_db()
                self.assertEqual(media.anchor_chunk_id, anchor.id)

                if target_state == "disabled":
                    Chunk.objects.filter(id=anchor.id).update(is_enabled=False)
                else:
                    Chunk.objects.filter(id=anchor.id).update(deleted_at=timezone.now())

                enabled = self.client.patch(
                    f"/api/v1/chunks/by-id/{media.id}",
                    data=json.dumps({"is_enabled": True}),
                    content_type="application/json",
                    **self.headers,
                )
                self.assertEqual(enabled.status_code, 200)
                media.refresh_from_db()
                self.assertIsNone(media.anchor_chunk_id)

    def test_media_disable_and_delete_keep_container_lifecycle_coherent(self):
        container = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.knowledge,
            content="[image]",
            chunk_index=2,
            chunk_type="image_container",
            is_enabled=False,
        )
        ocr = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.knowledge,
            content="ocr",
            chunk_index=3,
            chunk_type="image_ocr",
            media_parent_id=container.id,
            seq_id=9301,
        )
        caption = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.knowledge,
            content="caption",
            chunk_index=4,
            chunk_type="image_caption",
            media_parent_id=container.id,
            seq_id=9302,
        )
        self.seed_physical_index(ocr)
        self.seed_physical_index(caption)

        response = self.client.put(
            f"/api/v1/chunks/{self.knowledge.id}/{ocr.id}",
            data=json.dumps({"is_enabled": False}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.index_counts(ocr), (0, 0))
        self.assertTrue(Chunk.objects.filter(id=container.id).exists())

        response = self.client.delete(f"/api/v1/chunks/by-id/{caption.id}", **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.index_counts(caption), (0, 0))
        self.assertFalse(Chunk.objects.filter(id=container.id).exists())
        ocr.refresh_from_db()
        self.assertIsNone(ocr.media_parent_id)

    def test_hierarchy_and_indexes_roll_back_together_when_cleanup_fails(self):
        previous = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.knowledge,
            content="previous",
            chunk_index=-1,
            next_chunk_id=self.child.id,
            relation_chunks=[self.child.id],
        )
        following = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.knowledge,
            content="following",
            chunk_index=2,
            pre_chunk_id=self.child.id,
            indirect_relation_chunks=[self.child.id],
        )
        self.child.pre_chunk_id = previous.id
        self.child.next_chunk_id = following.id
        self.child.relation_chunks = [previous.id]
        self.child.indirect_relation_chunks = [following.id]
        self.child.save(
            update_fields=[
                "pre_chunk_id",
                "next_chunk_id",
                "relation_chunks",
                "indirect_relation_chunks",
                "updated_at",
            ]
        )
        media = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.knowledge,
            content="caption",
            chunk_index=3,
            chunk_type="image_caption",
            anchor_chunk_id=self.child.id,
        )
        self.seed_physical_index(self.child)

        with (
            patch(
                "personal_knowledge_base.chunk_mutations._cleanup_text_parent",
                side_effect=RuntimeError("injected cleanup failure"),
            ),
            patch("personal_knowledge_base.graph_rag.delete_knowledge_graph") as delete_graph,
            self.captureOnCommitCallbacks(execute=True) as callbacks,
        ):
            with self.assertRaisesRegex(RuntimeError, "injected cleanup failure"):
                self.client.delete(f"/api/v1/chunks/by-id/{self.child.id}", **self.headers)

        self.assertTrue(Chunk.objects.filter(id=self.child.id).exists())
        self.assertEqual(callbacks, [])
        delete_graph.assert_not_called()
        media.refresh_from_db()
        previous.refresh_from_db()
        following.refresh_from_db()
        self.child.refresh_from_db()
        self.assertEqual(media.anchor_chunk_id, self.child.id)
        self.assertEqual(previous.next_chunk_id, self.child.id)
        self.assertEqual(previous.relation_chunks, [self.child.id])
        self.assertEqual(following.pre_chunk_id, self.child.id)
        self.assertEqual(following.indirect_relation_chunks, [self.child.id])
        self.assertEqual(self.child.relation_chunks, [previous.id])
        self.assertEqual(self.index_counts(self.child), (1, 1))

    def test_disable_and_reenable_repairs_navigation_relationships_and_real_indexes(self):
        previous = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.knowledge,
            content="previous",
            chunk_index=-1,
            next_chunk_id=self.child.id,
            relation_chunks=[self.child.id, "unrelated"],
        )
        following = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.knowledge,
            content="following",
            chunk_index=2,
            pre_chunk_id=self.child.id,
            indirect_relation_chunks=[self.child.id],
        )
        self.child.pre_chunk_id = previous.id
        self.child.next_chunk_id = following.id
        self.child.relation_chunks = [previous.id]
        self.child.indirect_relation_chunks = [following.id]
        self.child.save(
            update_fields=[
                "pre_chunk_id",
                "next_chunk_id",
                "relation_chunks",
                "indirect_relation_chunks",
                "updated_at",
            ]
        )
        self.seed_physical_index(self.child)

        disabled = self.client.put(
            f"/api/v1/chunks/{self.knowledge.id}/{self.child.id}",
            data=json.dumps({"is_enabled": False}),
            content_type="application/json",
            **self.headers,
        )

        self.assertEqual(disabled.status_code, 200)
        previous.refresh_from_db()
        following.refresh_from_db()
        self.child.refresh_from_db()
        self.assertEqual(self.index_counts(self.child), (0, 0))
        self.assertEqual(previous.next_chunk_id, following.id)
        self.assertEqual(previous.relation_chunks, ["unrelated"])
        self.assertEqual(following.pre_chunk_id, previous.id)
        self.assertEqual(following.indirect_relation_chunks, [])
        self.assertEqual(self.child.pre_chunk_id, "")
        self.assertEqual(self.child.next_chunk_id, "")
        self.assertEqual(self.child.relation_chunks, [])
        self.assertEqual(self.child.indirect_relation_chunks, [])

        with (
            patch(
                "personal_knowledge_base.model_providers.embedding",
                return_value=[[0.2] * settings.LLM_EMBEDDING_DIM],
            ),
            patch("personal_knowledge_base.model_providers.embedding_signature", return_value="test:dim"),
        ):
            enabled = self.client.patch(
                f"/api/v1/chunks/by-id/{self.child.id}",
                data=json.dumps({"is_enabled": True}),
                content_type="application/json",
                **self.headers,
            )

        self.assertEqual(enabled.status_code, 200)
        previous.refresh_from_db()
        following.refresh_from_db()
        self.child.refresh_from_db()
        self.assertEqual(self.index_counts(self.child), (1, 1))
        self.assertEqual(previous.next_chunk_id, self.child.id)
        self.assertEqual(self.child.pre_chunk_id, previous.id)
        self.assertEqual(self.child.next_chunk_id, following.id)
        self.assertEqual(following.pre_chunk_id, self.child.id)

    def test_hard_delete_removes_relationship_ids_and_relinks_neighbors(self):
        previous = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.knowledge,
            content="previous",
            chunk_index=-1,
            next_chunk_id=self.child.id,
            relation_chunks=[self.child.id],
        )
        following = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.knowledge,
            content="following",
            chunk_index=2,
            pre_chunk_id=self.child.id,
            relation_chunks=[self.child.id],
            indirect_relation_chunks=[self.child.id],
        )
        self.seed_physical_index(self.child)

        response = self.client.delete(f"/api/v1/chunks/by-id/{self.child.id}", **self.headers)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Chunk.objects.filter(id=self.child.id).exists())
        previous.refresh_from_db()
        following.refresh_from_db()
        self.assertEqual(previous.next_chunk_id, following.id)
        self.assertEqual(previous.relation_chunks, [])
        self.assertEqual(following.pre_chunk_id, previous.id)
        self.assertEqual(following.relation_chunks, [])
        self.assertEqual(following.indirect_relation_chunks, [])
        self.assertEqual(self.index_counts(self.child), (0, 0))

    def test_graph_invalidation_runs_only_after_commit_for_content_state_and_delete(self):
        from personal_knowledge_base import graph_rag

        mutable_chunks = []
        for index in range(3):
            mutable_chunks.append(
                Chunk.objects.create(
                    tenant=self.tenant,
                    knowledge_base=self.kb,
                    knowledge=self.knowledge,
                    content=f"mutable-{index}",
                    chunk_index=10 + index,
                )
            )

        cases = [
            (
                "put",
                f"/api/v1/chunks/{self.knowledge.id}/{mutable_chunks[0].id}",
                {"content": "edited content"},
            ),
            (
                "patch",
                f"/api/v1/chunks/by-id/{mutable_chunks[1].id}",
                {"is_enabled": False},
            ),
            ("delete", f"/api/v1/chunks/by-id/{mutable_chunks[2].id}", None),
        ]
        for method, url, payload in cases:
            with self.subTest(method=method):
                kwargs = {**self.headers}
                if payload is not None:
                    kwargs.update(data=json.dumps(payload), content_type="application/json")
                with (
                    patch.object(graph_rag, "delete_knowledge_graph") as delete_graph,
                    patch("knowledge.views.delete_knowledge_graph") as view_delete_graph,
                    self.captureOnCommitCallbacks(execute=True),
                ):
                    response = getattr(self.client, method)(url, **kwargs)
                    self.assertEqual(response.status_code, 200)
                    delete_graph.assert_not_called()
                    view_delete_graph.assert_not_called()
                delete_graph.assert_called_once()

    def test_graph_invalidation_failure_is_logged_without_rolling_back_content_edit(self):
        from personal_knowledge_base import graph_rag

        with (
            patch.object(graph_rag, "delete_knowledge_graph", side_effect=RuntimeError("graph unavailable")),
            self.assertLogs("personal_knowledge_base.chunk_mutations", level="ERROR"),
            self.captureOnCommitCallbacks(execute=True),
        ):
            response = self.client.put(
                f"/api/v1/chunks/{self.knowledge.id}/{self.child.id}",
                data=json.dumps({"content": "committed despite graph failure"}),
                content_type="application/json",
                **self.headers,
            )

        self.assertEqual(response.status_code, 200)
        self.child.refresh_from_db()
        self.assertEqual(self.child.content, "committed despite graph failure")

    def test_both_chunk_handlers_share_route_shape_and_method_semantics(self):
        from . import views as personal_views

        factory = RequestFactory()

        def personal_call(method, route_shape, chunk, payload=None):
            request = factory.generic(
                method.upper(),
                f"/legacy/{route_shape}/{chunk.id}",
                data=json.dumps(payload) if payload is not None else "",
                content_type="application/json",
                **self.headers,
            )
            kwargs = {"chunk_id": chunk.id}
            if route_shape == "scoped":
                kwargs["knowledge_id"] = chunk.knowledge_id
            return personal_views.chunks_collection(request, **kwargs)

        def mounted_call(method, route_shape, chunk, payload=None):
            if route_shape == "scoped":
                url = f"/api/v1/chunks/{chunk.knowledge_id}/{chunk.id}"
            else:
                url = f"/api/v1/chunks/by-id/{chunk.id}"
            kwargs = {**self.headers}
            if payload is not None:
                kwargs.update(data=json.dumps(payload), content_type="application/json")
            return getattr(self.client, method)(url, **kwargs)

        for family, call in (("mounted", mounted_call), ("personal", personal_call)):
            for route_shape in ("scoped", "by-id"):
                with self.subTest(family=family, route_shape=route_shape):
                    chunk = Chunk.objects.create(
                        tenant=self.tenant,
                        knowledge_base=self.kb,
                        knowledge=self.knowledge,
                        content=f"{family}-{route_shape}",
                        chunk_index=100 + Chunk.objects.count(),
                    )
                    self.assertEqual(call("get", route_shape, chunk).status_code, 200)
                    self.assertEqual(
                        call("put", route_shape, chunk, {"content": "put-value"}).status_code,
                        200,
                    )
                    self.assertEqual(
                        call("patch", route_shape, chunk, {"content": "patch-value"}).status_code,
                        200,
                    )
                    chunk.refresh_from_db()
                    self.assertEqual(chunk.content, "patch-value")
                    self.assertEqual(
                        call("post", route_shape, chunk, {"content": "must-not-save"}).status_code,
                        405,
                    )
                    chunk.refresh_from_db()
                    self.assertEqual(chunk.content, "patch-value")

    def test_both_chunk_handlers_reject_deleted_or_inconsistent_ancestry(self):
        from . import views as personal_views

        factory = RequestFactory()
        deleted_knowledge = Knowledge.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            type="file",
            title="deleted",
            source="deleted.txt",
            deleted_at=timezone.now(),
        )
        deleted_knowledge_chunk = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=deleted_knowledge,
            content="deleted knowledge content",
            chunk_index=200,
        )
        deleted_kb = KnowledgeBase.objects.create(
            tenant=self.tenant,
            name="deleted-kb",
            deleted_at=timezone.now(),
        )
        deleted_kb_knowledge = Knowledge.objects.create(
            tenant=self.tenant,
            knowledge_base=deleted_kb,
            type="file",
            title="deleted kb knowledge",
            source="deleted-kb.txt",
        )
        deleted_kb_chunk = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=deleted_kb,
            knowledge=deleted_kb_knowledge,
            content="deleted kb content",
            chunk_index=201,
        )
        other_kb = KnowledgeBase.objects.create(tenant=self.tenant, name="other-kb")
        inconsistent_chunk = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=other_kb,
            knowledge=self.knowledge,
            content="inconsistent ancestry",
            chunk_index=202,
        )

        for chunk in (deleted_knowledge_chunk, deleted_kb_chunk, inconsistent_chunk):
            for route_shape in ("scoped", "by-id"):
                with self.subTest(chunk=chunk.id, route_shape=route_shape, family="mounted"):
                    url = (
                        f"/api/v1/chunks/{chunk.knowledge_id}/{chunk.id}"
                        if route_shape == "scoped"
                        else f"/api/v1/chunks/by-id/{chunk.id}"
                    )
                    self.assertEqual(self.client.get(url, **self.headers).status_code, 404)
                with self.subTest(chunk=chunk.id, route_shape=route_shape, family="personal"):
                    request = factory.get(f"/legacy/{route_shape}/{chunk.id}", **self.headers)
                    kwargs = {"chunk_id": chunk.id}
                    if route_shape == "scoped":
                        kwargs["knowledge_id"] = chunk.knowledge_id
                    with self.assertRaises(Http404):
                        personal_views.chunks_collection(request, **kwargs)

    def test_both_chunk_collections_exclude_inconsistent_same_tenant_kb_ancestry(self):
        from . import views as personal_views

        other_kb = KnowledgeBase.objects.create(tenant=self.tenant, name="collection-other-kb")
        inconsistent = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=other_kb,
            knowledge=self.knowledge,
            content="inconsistent collection ancestry",
            chunk_index=300,
        )
        factory = RequestFactory()

        mounted = self.client.get(f"/api/v1/chunks/{self.knowledge.id}", **self.headers)
        personal_request = factory.get(
            f"/legacy/chunks/{self.knowledge.id}",
            **self.headers,
        )
        personal = personal_views.chunks_collection(
            personal_request,
            knowledge_id=self.knowledge.id,
        )

        for family, response_data in (
            ("mounted", mounted.json()),
            ("personal", json.loads(personal.content)),
        ):
            with self.subTest(family=family):
                ids = {item["id"] for item in response_data["data"]["items"]}
                self.assertIn(self.child.id, ids)
                self.assertNotIn(inconsistent.id, ids)
