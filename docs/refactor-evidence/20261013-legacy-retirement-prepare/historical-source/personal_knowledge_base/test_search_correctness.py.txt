"""W03 检索正确性与投影/事务修复回归（审计 F03–F07）。

- F03：向量召回不得因其他租户/知识库候选挤占而漏召回；窗口扩到全表后
  范围过滤结果为精确近邻。
- F04：单知识库检索沿用该库钉住的 embedding 模型；混合空间显式降级。
- F05：部分批次失败的向量重建不得标记 ready。
- F06：无终结事件的轨迹不得覆盖既有消息；投影切换失败保留原记录。
- F07：chunk 更新的索引（含模型网络）必须在数据库事务之外执行。
"""
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings

from . import event_log
from .chunk_mutations import update_chunk
from .event_log import append_event, rebuild_projection
from .models import Chunk, Knowledge, KnowledgeBase, Message, Session, SessionEvent, Tenant, User
from .search import (
    _vector_ranked,
    _vector_recall,
    ensure_search_tables,
    get_vector_index_state,
    hybrid_search_ex,
    mark_vector_index_ready,
    pack_embedding,
    rebuild_vector_index,
)


def _vec(value: float) -> list[float]:
    v = [0.0] * settings.LLM_EMBEDDING_DIM
    v[0] = value
    return v


class VectorRecallScopeTests(TestCase):
    def setUp(self):
        cache.clear()
        ensure_search_tables()
        # 启动期后台线程可能与测试进程竞写索引状态（F13/W04 范畴）；
        # 本类只关注检索逻辑，显式声明 ready 基线。
        mark_vector_index_ready("")
        self.tenant = Tenant.objects.create(name="scope", api_key="scope-key")
        self.other = Tenant.objects.create(name="other", api_key="other-key")
        self.kb = KnowledgeBase.objects.create(tenant=self.tenant, name="scope-kb")

    def _add_vec_chunk(self, tenant, kb, distance_value, seq_id):
        knowledge = Knowledge.objects.create(tenant=tenant, knowledge_base=kb, title=f"t-{seq_id}")
        chunk = Chunk.objects.create(
            tenant=tenant, knowledge_base=kb, knowledge=knowledge,
            content=f"content-{seq_id}", chunk_index=0, seq_id=seq_id,
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO chunk_embeddings_vec(rowid, embedding) VALUES (%s, %s)",
                [seq_id, pack_embedding(_vec(distance_value))],
            )
        return chunk

    def test_out_of_scope_candidates_never_crowd_out_scope_results(self):
        # 其他租户 70 个更近的候选占满初始窗口；范围内唯一目标距离更远。
        other_kb = KnowledgeBase.objects.create(tenant=self.other, name="other-kb")
        for index in range(70):
            self._add_vec_chunk(self.other, other_kb, 0.99 - index * 0.001, 9000 + index)
        target = self._add_vec_chunk(self.tenant, self.kb, 0.9, 9100)

        with patch("personal_knowledge_base.model_providers.embedding", return_value=[_vec(1.0)]):
            ranked = _vector_ranked(self.tenant.id, {str(self.kb.id)}, "query", 1, self.tenant)
        self.assertEqual(ranked, [target.id])

    def test_single_kb_pins_its_embedding_model_for_queries(self):
        self.kb.embedding_model_id = "model-a"
        self.kb.save(update_fields=["embedding_model_id", "updated_at"])
        knowledge = Knowledge.objects.create(
            tenant=self.tenant, knowledge_base=self.kb, title="pinned",
        )
        chunk = Chunk.objects.create(
            tenant=self.tenant, knowledge_base=self.kb, knowledge=knowledge,
            content="pinned content", chunk_index=0, seq_id=9200,
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO chunk_embeddings_vec(rowid, embedding) VALUES (%s, %s)",
                [9200, pack_embedding(_vec(0.5))],
            )
        meta = {"degradations": []}
        with patch("personal_knowledge_base.model_providers.active_embedding_config",
                   return_value={"model": "model-a"}) as cfg, \
             patch("personal_knowledge_base.model_providers.embedding",
                   return_value=[_vec(1.0)]) as embedding_call:
            ranked = _vector_recall(self.tenant.id, {str(self.kb.id)}, "query", 5, self.tenant, meta)
        self.assertEqual(ranked, [chunk.id], meta)
        # 查询 embedding 与索引使用同一空间（模型 id 透传）。
        self.assertEqual(embedding_call.call_args.args[2], "model-a")
        self.assertEqual(cfg.call_args.args[1], "model-a")

    def test_mixed_embedding_spaces_degrade_instead_of_cross_space_compare(self):
        KnowledgeBase.objects.create(tenant=self.tenant, name="kb-b", embedding_model_id="model-a")
        kb_b = KnowledgeBase.objects.get(tenant=self.tenant, name="kb-b")
        meta = {"degradations": []}
        with patch("personal_knowledge_base.model_providers.embedding") as embedding_call:
            ranked = _vector_recall(
                self.tenant.id, {str(self.kb.id), str(kb_b.id)}, "query", 5, self.tenant, meta,
            )
        self.assertEqual(ranked, [], meta)
        embedding_call.assert_not_called()
        self.assertTrue(any(d["stage"] == "vector" and "mixed_embedding_spaces" in d["reason"]
                            for d in meta["degradations"]))


@override_settings(VECTOR_REINDEX_BATCH_SIZE=1)
class RebuildIntegrityTests(TestCase):
    def setUp(self):
        cache.clear()
        ensure_search_tables()
        self.tenant = Tenant.objects.create(name="rebuild", api_key="rebuild-key")
        kb = KnowledgeBase.objects.create(tenant=self.tenant, name="rebuild-kb")
        knowledge = Knowledge.objects.create(tenant=self.tenant, knowledge_base=kb, title="rebuild-doc")
        self.chunks = [
            Chunk.objects.create(tenant=self.tenant, knowledge_base=kb, knowledge=knowledge,
                                 content=f"chunk-{i}", chunk_index=i, seq_id=9300 + i)
            for i in range(2)
        ]

    def test_partial_batch_failure_never_marks_ready(self):
        vectors = [[0.0] * settings.LLM_EMBEDDING_DIM]
        with patch("personal_knowledge_base.model_providers.embedding",
                   side_effect=[RuntimeError("batch 1 down"), vectors]):
            result = rebuild_vector_index()
        self.assertEqual(result["indexed"], 1)
        self.assertEqual(result["errors"], 1)
        self.assertEqual(get_vector_index_state()["status"], "needs_rebuild")
        self.assertEqual(get_vector_index_state()["reason"], "partial_batch_failures")

    def test_full_success_marks_ready(self):
        vectors = [[0.0] * settings.LLM_EMBEDDING_DIM]
        with patch("personal_knowledge_base.model_providers.embedding", return_value=vectors):
            result = rebuild_vector_index()
        self.assertEqual(result["errors"], 0)
        self.assertEqual(get_vector_index_state()["status"], "ready")


class ProjectionRebuildSafetyTests(TestCase):
    def setUp(self):
        cache.clear()
        self.tenant = Tenant.objects.create(name="projection", api_key="projection-key")
        self.user = User.objects.create(username="projection-u", email="p@x.invalid",
                                        password_hash="x", tenant=self.tenant)
        self.session = Session.objects.create(tenant=self.tenant, user_id=self.user.id)

    def _emit_turn(self, request_id, with_terminal=True, content="最终回答"):
        append_event(self.session, request_id, event_log.TURN_USER_MESSAGE, {"content": "问题"})
        if with_terminal:
            append_event(self.session, request_id, event_log.TURN_COMPLETED, {"content": content})

    def test_incomplete_trajectory_never_overwrites_existing_message(self):
        append_event(self.session, "req-1", event_log.TURN_USER_MESSAGE, {"content": "问题"})
        Message.objects.create(
            session_id=self.session.id, request_id="req-1", role="assistant",
            content="既有完整回答", is_completed=True,
        )
        stats = rebuild_projection(self.session.id)
        self.assertEqual(stats["turns_skipped_incomplete"], 1)
        assistant = Message.objects.filter(session_id=self.session.id, role="assistant").first()
        self.assertEqual(assistant.content, "既有完整回答")
        self.assertTrue(assistant.is_completed)

    def test_terminal_trajectory_replaces_projection_atomically(self):
        self._emit_turn("req-2")
        Message.objects.create(
            session_id=self.session.id, request_id="req-2", role="assistant",
            content="旧内容", is_completed=True,
        )
        stats = rebuild_projection(self.session.id)
        self.assertEqual(stats["turns_rebuilt"], 1)
        assistant = Message.objects.filter(session_id=self.session.id, request_id="req-2", role="assistant").first()
        self.assertEqual(assistant.content, "最终回答")

    def test_failed_projection_switch_preserves_original_message(self):
        self._emit_turn("req-3")
        Message.objects.create(
            session_id=self.session.id, request_id="req-3", role="assistant",
            content="原记录", is_completed=True,
        )
        with patch("personal_knowledge_base.event_log.Message.objects.create",
                   side_effect=RuntimeError("projection write failed")):
            with self.assertRaises(RuntimeError):
                rebuild_projection(self.session.id)
        assistant = Message.objects.filter(session_id=self.session.id, request_id="req-3", role="assistant").first()
        self.assertIsNotNone(assistant)
        self.assertEqual(assistant.content, "原记录")


class ChunkUpdateTransactionBoundaryTests(TransactionTestCase):
    def setUp(self):
        cache.clear()
        self.tenant = Tenant.objects.create(name="mutation", api_key="mutation-key")
        kb = KnowledgeBase.objects.create(tenant=self.tenant, name="mutation-kb")
        knowledge = Knowledge.objects.create(tenant=self.tenant, knowledge_base=kb, title="mutation-doc")
        self.chunk = Chunk.objects.create(
            tenant=self.tenant, knowledge_base=kb, knowledge=knowledge,
            content="旧内容", chunk_index=0,
        )

    def test_index_runs_outside_database_transaction(self):
        observed = {}

        def spy_index(chunk, **kwargs):
            observed["in_atomic_block"] = connection.in_atomic_block

        with patch("personal_knowledge_base.chunk_mutations.index_chunk", side_effect=spy_index):
            updated = update_chunk(self.chunk, {"content": "新内容"})
        self.assertTrue(observed["in_atomic_block"] is False)
        self.assertEqual(updated.content, "新内容")
