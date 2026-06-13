from pathlib import Path
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.db import connection
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import NoReverseMatch, reverse

from accounts.models import User
from drive import services as drive_services
from .models import KBChunk, KBDocument, KnowledgeBase, WikiBuildJob, WikiLink, WikiPage
from . import services, wiki_services
from .sqlite_search import load_sqlite_vec


@override_settings(EMBEDDING_API_KEY="", LLM_API_KEY="", RERANK_API_KEY="")
class KnowledgeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="StrongPass123!")
        self.client.force_login(self.user)

    def test_ingest_text_and_query(self):
        kb = KnowledgeBase.objects.create(user=self.user, name="产品资料")
        response = self.client.post(
            reverse("knowledge:ingest", args=[kb.id]),
            {"text": "Django 单体应用包含文件管理、知识库和智能问答。"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(KBChunk.objects.filter(kb=kb).exists())
        chunk = KBChunk.objects.get(kb=kb)
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM knowledge_kbchunk_vec WHERE chunk_id = %s", [chunk.id])
            self.assertEqual(cursor.fetchone()[0], 1)
            cursor.execute("SELECT count(*) FROM knowledge_kbchunk_fts WHERE rowid = %s", [chunk.id])
            self.assertEqual(cursor.fetchone()[0], 1)
        response = self.client.get(reverse("knowledge:index"), {"kb": kb.id})
        self.assertContains(response, "去 AI 助手提问")
        self.assertContains(response, f"/assistant/?kb={kb.id}")

    def test_knowledge_page_has_quick_kb_switcher_for_ingest(self):
        kb1 = KnowledgeBase.objects.create(user=self.user, name="产品资料")
        kb2 = KnowledgeBase.objects.create(user=self.user, name="会议资料")

        response = self.client.get(reverse("knowledge:index"), {"kb": kb1.id})

        self.assertContains(response, "当前添加到")
        self.assertContains(response, 'class="kb-switcher"', html=False)
        self.assertContains(response, 'data-autosubmit', html=False)
        self.assertContains(response, f'<option value="{kb1.id}" selected>产品资料', html=False)
        self.assertContains(response, f'<option value="{kb2.id}"', html=False)
        self.assertContains(response, reverse("knowledge:ingest", args=[kb1.id]))

    def test_auto_submit_forms_script_exists(self):
        js = Path(settings.BASE_DIR / "static/js/app.js").read_text(encoding="utf-8")

        self.assertIn("function initAutoSubmitForms", js)
        self.assertIn("form[data-autosubmit]", js)
        self.assertIn("form.requestSubmit()", js)

    def test_sqlite_vec_reload_handles_recreated_raw_connection(self):
        class FakeDjangoConnection:
            vendor = "sqlite"

            def __init__(self):
                self.connection = sqlite3.connect(":memory:")

            def ensure_connection(self):
                if self.connection is None:
                    self.connection = sqlite3.connect(":memory:")

        fake = FakeDjangoConnection()
        try:
            load_sqlite_vec(fake)
            fake._sqlite_vec_loaded = True
            fake.connection.close()
            fake.connection = sqlite3.connect(":memory:")

            load_sqlite_vec(fake)

            self.assertEqual(fake._sqlite_vec_loaded_connection_id, id(fake.connection))
            fake.connection.execute("CREATE VIRTUAL TABLE vec_check USING vec0(id integer primary key, embedding float[4])")
        finally:
            fake.connection.close()

    def test_txt_file_ingest_marks_ready_and_indexes(self):
        kb = KnowledgeBase.objects.create(user=self.user, name="产品资料")
        user_file = drive_services.save_uploaded_file(
            self.user,
            SimpleUploadedFile("intro.txt", b"Django RAG uses LangChain loaders.", content_type="text/plain"),
        )

        response = self.client.post(reverse("knowledge:ingest", args=[kb.id]), {"file_ids": [str(user_file.id)]})

        self.assertEqual(response.status_code, 302)
        doc = KBDocument.objects.get(kb=kb, user_file=user_file)
        self.assertEqual(doc.status, KBDocument.STATUS_READY)
        self.assertGreater(doc.chunk_count, 0)
        self.assertTrue(KBChunk.objects.filter(document=doc).exists())
        response = self.client.get(reverse("knowledge:index"), {"kb": kb.id})
        self.assertContains(response, "已入库")

    def test_unsupported_file_is_marked_without_vector_rows(self):
        kb = KnowledgeBase.objects.create(user=self.user, name="产品资料")
        user_file = drive_services.save_uploaded_file(
            self.user,
            SimpleUploadedFile("archive.bin", b"\x00\x01\x02", content_type="application/octet-stream"),
        )

        response = self.client.post(reverse("knowledge:ingest", args=[kb.id]), {"file_ids": [str(user_file.id)]})

        self.assertEqual(response.status_code, 302)
        doc = KBDocument.objects.get(kb=kb, user_file=user_file)
        self.assertEqual(doc.status, KBDocument.STATUS_UNSUPPORTED)
        self.assertEqual(doc.chunk_count, 0)
        self.assertFalse(KBChunk.objects.filter(document=doc).exists())
        response = self.client.get(reverse("knowledge:index"), {"kb": kb.id})
        self.assertContains(response, "不支持")

    def test_reingesting_same_file_replaces_existing_document(self):
        kb = KnowledgeBase.objects.create(user=self.user, name="产品资料")
        user_file = drive_services.save_uploaded_file(
            self.user,
            SimpleUploadedFile("intro.md", b"# Title\nRepeated import should replace old chunks.", content_type="text/markdown"),
        )

        services.ingest_user_file(kb, user_file)
        first_doc_id = KBDocument.objects.get(kb=kb, user_file=user_file).id
        services.ingest_user_file(kb, user_file)

        docs = KBDocument.objects.filter(kb=kb, user_file=user_file)
        self.assertEqual(docs.count(), 1)
        self.assertNotEqual(docs.get().id, first_doc_id)
        self.assertEqual(kb.documents.filter(status=KBDocument.STATUS_READY).count(), 1)

    def test_fts_trigram_and_delete_cleanup(self):
        kb = KnowledgeBase.objects.create(user=self.user, name="产品资料")
        doc = services.ingest_text(kb, "text", "manual", "手动文本", "知识库可以检索中文片段和文件管理能力。")
        chunk = KBChunk.objects.get(document=doc)

        fts_hits = services.fts_candidates(kb, "中文片段", 6)
        self.assertEqual(fts_hits[0][0], chunk.id)

        hits = services.search(kb, "怎么检索中文片段", top_k=6)
        self.assertTrue(any(hit_chunk.id == chunk.id for _, hit_chunk in hits))

        doc.delete()
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM knowledge_kbchunk_vec WHERE chunk_id = %s", [chunk.id])
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute("SELECT count(*) FROM knowledge_kbchunk_fts WHERE rowid = %s", [chunk.id])
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_knowledge_page_does_not_expose_mindmap(self):
        kb = KnowledgeBase.objects.create(user=self.user, name="产品资料")
        response = self.client.get(reverse("knowledge:index"), {"kb": kb.id})

        self.assertNotContains(response, "思维导图")
        self.assertNotContains(response, "mindmap")
        self.assertNotContains(response, "向知识库提问")
        with self.assertRaises(NoReverseMatch):
            reverse("knowledge:mindmap", args=[kb.id])
        with self.assertRaises(NoReverseMatch):
            reverse("knowledge:query", args=[kb.id])

    def _fake_wiki_openai(self):
        class FakeChatCompletions:
            def create(self, **kwargs):
                prompt = kwargs["messages"][1]["content"]
                if "source 页面摘要" in prompt:
                    content = (
                        "## Topic Summary\n"
                        "当前知识库整理了 Django、RAG 和 Wiki 的关系。\n\n"
                        "## Major Sources\n"
                        "- [[手动文本]]\n\n"
                        "## Key Conclusions\n"
                        "- Wiki 适合沉淀结构化知识。\n\n"
                        "## Gaps\n"
                        "- 还缺少运行指标。"
                    )
                else:
                    content = (
                        "## Summary\n"
                        "手动文本说明 Django RAG 可以生成 Wiki 页面。\n\n"
                        "## Key Points\n"
                        "- Wiki source 页面来自已入库文档。\n"
                        "- 检索会同时使用 Wiki 和 chunk。\n\n"
                        "## Useful Quotes\n"
                        "- Django RAG uses Wiki.\n\n"
                        "## Connections\n"
                        "- [[MissingConcept]]\n\n"
                        "## Open Questions\n"
                        "- 是否需要图谱。"
                    )
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

        class FakeOpenAI:
            def __init__(self, **kwargs):
                self.chat = SimpleNamespace(completions=FakeChatCompletions())

        return FakeOpenAI

    @override_settings(LLM_API_KEY="test-key", LLM_BASE_URL="https://example.com/v1", LLM_MODEL="test-model")
    def test_build_wiki_generates_source_overview_and_indexes(self):
        kb = KnowledgeBase.objects.create(user=self.user, name="产品资料")
        doc = services.ingest_text(kb, "text", "manual", "手动文本", "Django RAG uses Wiki pages.")

        with patch("knowledge.wiki_services.OpenAI", self._fake_wiki_openai()):
            job = wiki_services.build_wiki(kb)

        self.assertEqual(job.status, WikiBuildJob.STATUS_SUCCESS)
        source = WikiPage.objects.get(kb=kb, page_type=WikiPage.TYPE_SOURCE, source_document=doc)
        overview = WikiPage.objects.get(kb=kb, page_type=WikiPage.TYPE_OVERVIEW)
        self.assertEqual(source.status, WikiPage.STATUS_READY)
        self.assertEqual(overview.status, WikiPage.STATUS_READY)
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM knowledge_wikipage_vec WHERE page_id = %s", [source.id])
            self.assertEqual(cursor.fetchone()[0], 1)
            cursor.execute("SELECT count(*) FROM knowledge_wikipage_fts WHERE rowid = %s", [source.id])
            self.assertEqual(cursor.fetchone()[0], 1)
        self.assertTrue(WikiLink.objects.filter(source_page=source, target_title="MissingConcept").exists())
        health = wiki_services.wiki_health(kb)
        self.assertFalse(health["missing_overview"])
        self.assertTrue(health["broken_links"])

        response = self.client.get(reverse("knowledge:index"), {"kb": kb.id})
        self.assertContains(response, "Wiki")
        self.assertContains(response, "打开总览")
        self.assertContains(response, "MissingConcept")

    @override_settings(LLM_API_KEY="test-key", LLM_BASE_URL="https://example.com/v1", LLM_MODEL="test-model")
    def test_build_wiki_refresh_does_not_duplicate_pages(self):
        kb = KnowledgeBase.objects.create(user=self.user, name="产品资料")
        services.ingest_text(kb, "text", "manual", "手动文本", "重复生成不应该产生重复 Wiki 页面。")

        with patch("knowledge.wiki_services.OpenAI", self._fake_wiki_openai()):
            wiki_services.build_wiki(kb)
            wiki_services.build_wiki(kb)

        self.assertEqual(WikiPage.objects.filter(kb=kb, page_type=WikiPage.TYPE_SOURCE).count(), 1)
        self.assertEqual(WikiPage.objects.filter(kb=kb, page_type=WikiPage.TYPE_OVERVIEW).count(), 1)

    @override_settings(LLM_API_KEY="")
    def test_build_wiki_without_llm_key_fails_visibly(self):
        kb = KnowledgeBase.objects.create(user=self.user, name="产品资料")
        services.ingest_text(kb, "text", "manual", "手动文本", "Wiki 生成需要 LLM。")

        job = wiki_services.build_wiki(kb)

        self.assertEqual(job.status, WikiBuildJob.STATUS_FAILED)
        self.assertIn("LLM_API_KEY", job.error_message)
        self.assertFalse(WikiPage.objects.filter(kb=kb).exists())

    @override_settings(LLM_API_KEY="test-key", LLM_BASE_URL="https://example.com/v1", LLM_MODEL="test-model")
    def test_deleting_document_marks_source_wiki_page_stale(self):
        kb = KnowledgeBase.objects.create(user=self.user, name="产品资料")
        doc = services.ingest_text(kb, "text", "manual", "手动文本", "删除文档后 Wiki 应标记过期。")

        with patch("knowledge.wiki_services.OpenAI", self._fake_wiki_openai()):
            wiki_services.build_wiki(kb)
        page = WikiPage.objects.get(kb=kb, page_type=WikiPage.TYPE_SOURCE)

        doc.delete()
        page.refresh_from_db()

        self.assertEqual(page.status, WikiPage.STATUS_STALE)
        self.assertIsNone(page.source_document)

    @override_settings(LLM_API_KEY="test-key", LLM_BASE_URL="https://example.com/v1", LLM_MODEL="test-model")
    def test_wiki_page_view_renders_markdown_and_enforces_owner(self):
        kb = KnowledgeBase.objects.create(user=self.user, name="产品资料")
        services.ingest_text(kb, "text", "manual", "手动文本", "Wiki 页面可以渲染 Markdown。")

        with patch("knowledge.wiki_services.OpenAI", self._fake_wiki_openai()):
            wiki_services.build_wiki(kb)
        page = WikiPage.objects.get(kb=kb, page_type=WikiPage.TYPE_SOURCE)

        response = self.client.get(reverse("knowledge:wiki_page", args=[kb.id, page.slug]))
        self.assertContains(response, "<h2>Summary</h2>", html=True)
        self.assertContains(response, "MissingConcept")

        other = User.objects.create_user(username="bob", password="StrongPass123!")
        other_kb = KnowledgeBase.objects.create(user=other, name="私有资料")
        other_page = WikiPage.objects.create(
            kb=other_kb,
            page_type=WikiPage.TYPE_OVERVIEW,
            slug="overview",
            title="私有总览",
            content="## Summary\nsecret",
            status=WikiPage.STATUS_READY,
        )
        response = self.client.get(reverse("knowledge:wiki_page", args=[other_kb.id, other_page.slug]))
        self.assertEqual(response.status_code, 404)

    @override_settings(LLM_API_KEY="test-key", LLM_BASE_URL="https://example.com/v1", LLM_MODEL="test-model")
    def test_query_rewrite_uses_llm_json(self):
        class FakeChatCompletions:
            def create(self, **kwargs):
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content='{"queries":["中文检索", "文件管理"]}'))]
                )

        class FakeOpenAI:
            def __init__(self, **kwargs):
                self.chat = SimpleNamespace(completions=FakeChatCompletions())

        with patch("knowledge.services.OpenAI", FakeOpenAI):
            self.assertEqual(services.rewrite_rag_queries("怎么查资料"), ["中文检索", "文件管理"])

    @override_settings(RERANK_API_KEY="test-key", RERANK_MODEL="qwen3-vl-rerank")
    def test_rerank_orders_candidates_by_relevance_score(self):
        kb = KnowledgeBase.objects.create(user=self.user, name="产品资料")
        doc1 = services.ingest_text(kb, "text", "manual", "文档一", "第一段讲文件上传。")
        doc2 = services.ingest_text(kb, "text", "manual", "文档二", "第二段讲向量检索。")
        chunk1 = KBChunk.objects.get(document=doc1)
        chunk2 = KBChunk.objects.get(document=doc2)

        fake_response = SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "output": {
                    "results": [
                        {"index": 1, "relevance_score": 0.95},
                        {"index": 0, "relevance_score": 0.12},
                    ]
                }
            },
        )

        with patch("knowledge.services.vector_candidates", return_value=[(chunk1.id, 0.1), (chunk2.id, 0.2)]), patch(
            "knowledge.services.fts_candidates", return_value=[]
        ), patch("knowledge.services.httpx.Client") as client_class:
            client = client_class.return_value.__enter__.return_value
            client.post.return_value = fake_response
            hits = services.search(kb, "怎么做向量检索", top_k=2)

        self.assertEqual(hits[0].chunk.id, chunk2.id)
        self.assertEqual(hits[0].rerank_score, 0.95)

    @override_settings(RERANK_API_KEY="test-key", RERANK_MODEL="qwen3-vl-rerank")
    def test_rerank_failure_keeps_fused_order(self):
        kb = KnowledgeBase.objects.create(user=self.user, name="产品资料")
        doc1 = services.ingest_text(kb, "text", "manual", "文档一", "第一段讲文件上传。")
        doc2 = services.ingest_text(kb, "text", "manual", "文档二", "第二段讲向量检索。")
        chunk1 = KBChunk.objects.get(document=doc1)
        chunk2 = KBChunk.objects.get(document=doc2)

        with patch("knowledge.services.vector_candidates", return_value=[(chunk1.id, 0.1), (chunk2.id, 0.2)]), patch(
            "knowledge.services.fts_candidates", return_value=[]
        ), patch("knowledge.services.httpx.Client") as client_class:
            client_class.return_value.__enter__.return_value.post.side_effect = RuntimeError("down")
            hits = services.search(kb, "怎么做向量检索", top_k=2)

        self.assertEqual(hits[0].chunk.id, chunk1.id)

    # Create your tests here.
