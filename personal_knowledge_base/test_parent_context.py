from django.test import TestCase

from .models import Chunk, Knowledge, KnowledgeBase, Tenant
from .parent_context import resolve_parent_context


class ParentContextTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="context", api_key="context-key")
        self.kb = KnowledgeBase.objects.create(tenant=self.tenant, name="context-kb")
        self.knowledge = Knowledge.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            type="file",
            title="Context guide",
            source="guide.txt",
            metadata={"chunking_diagnostics": {"selected_strategy": "layout"}},
        )
        self.parent = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.knowledge,
            content="0123456789ABCDEFGHIJ",
            chunk_index=0,
            chunk_type="parent_text",
            is_enabled=False,
            start_at=100,
            end_at=120,
        )
        self.child_a = self.create_child("234567", 102, 108, 1)
        self.child_b = self.create_child("ABCDEF", 110, 116, 2)

    def create_child(self, content, start_at, end_at, chunk_index, **overrides):
        values = {
            "tenant": self.tenant,
            "knowledge_base": self.kb,
            "knowledge": self.knowledge,
            "content": content,
            "chunk_index": chunk_index,
            "chunk_type": "text",
            "context_parent_id": self.parent.id,
            "start_at": start_at,
            "end_at": end_at,
        }
        values.update(overrides)
        return Chunk.objects.create(**values)

    def hit(self, chunk, score, **overrides):
        item = {
            "chunk_id": chunk.id,
            "id": chunk.id,
            "content": chunk.content,
            "score": score,
            "rerank_score": score,
            "retrieval_path": "document",
            "chunk_type": chunk.chunk_type,
            "knowledge_id": chunk.knowledge_id,
            "knowledge_base_id": chunk.knowledge_base_id,
        }
        item.update(overrides)
        return item

    def test_siblings_collapse_to_one_parent_result(self):
        resolved = resolve_parent_context(
            [self.hit(self.child_a, 0.9), self.hit(self.child_b, 0.8)],
            tenant_id=self.tenant.id,
            max_context_chars=4096,
        )

        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["chunk_id"], self.child_a.id)
        self.assertEqual(resolved[0]["parent_chunk_id"], self.parent.id)
        self.assertEqual(resolved[0]["matched_child_ids"], [self.child_a.id, self.child_b.id])
        self.assertEqual(
            [(item["start_at"], item["end_at"]) for item in resolved[0]["matched_ranges"]],
            [(102, 108), (110, 116)],
        )
        self.assertEqual(resolved[0]["score"], 0.9)
        self.assertEqual(resolved[0]["selected_strategy"], "layout")
        self.assertEqual(resolved[0]["content"], self.parent.content)

    def test_group_order_is_first_seen_while_group_score_is_highest(self):
        flat = self.create_child("flat", 0, 4, 3, context_parent_id=None)

        resolved = resolve_parent_context(
            [self.hit(self.child_a, 0.4), self.hit(flat, 0.7), self.hit(self.child_b, 0.9)],
            tenant_id=self.tenant.id,
            max_context_chars=4096,
        )

        self.assertEqual([item["chunk_id"] for item in resolved], [self.child_a.id, flat.id])
        self.assertEqual(resolved[0]["score"], 0.9)
        self.assertEqual(resolved[0]["chunk_id"], self.child_a.id)

    def test_missing_and_wrong_scope_parents_fall_back_to_child(self):
        other_tenant = Tenant.objects.create(name="other", api_key="other-key")
        other_kb = KnowledgeBase.objects.create(tenant=other_tenant, name="other-kb")
        other_knowledge = Knowledge.objects.create(
            tenant=other_tenant, knowledge_base=other_kb, type="file", title="Other", source="other.txt"
        )
        wrong_tenant_parent = Chunk.objects.create(
            tenant=other_tenant,
            knowledge_base=other_kb,
            knowledge=other_knowledge,
            content="secret parent",
            chunk_index=0,
            chunk_type="parent_text",
            is_enabled=False,
        )
        same_tenant_other_knowledge = Knowledge.objects.create(
            tenant=self.tenant, knowledge_base=self.kb, type="file", title="Other local", source="other-local.txt"
        )
        wrong_knowledge_parent = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=same_tenant_other_knowledge,
            content="wrong knowledge parent",
            chunk_index=0,
            chunk_type="parent_text",
            is_enabled=False,
        )

        cases = [
            ("missing-parent-id", "missing_parent"),
            (wrong_tenant_parent.id, "missing_parent"),
            (wrong_knowledge_parent.id, "parent_scope_mismatch"),
        ]
        for parent_id, reason in cases:
            with self.subTest(reason=reason, parent_id=parent_id):
                self.child_a.context_parent_id = parent_id
                self.child_a.save(update_fields=["context_parent_id", "updated_at"])
                resolved = resolve_parent_context(
                    [self.hit(self.child_a, 0.9)], tenant_id=self.tenant.id, max_context_chars=4096
                )
                self.assertEqual(resolved[0]["content"], self.child_a.content)
                self.assertEqual(resolved[0]["context_fallback"], reason)
                self.assertNotIn("parent_chunk_id", resolved[0])

    def test_parent_lookup_accepts_intentionally_disabled_parent(self):
        self.assertFalse(self.parent.is_enabled)

        resolved = resolve_parent_context(
            [self.hit(self.child_a, 0.9)], tenant_id=self.tenant.id, max_context_chars=4096
        )

        self.assertEqual(resolved[0]["parent_chunk_id"], self.parent.id)

    def test_missing_parent_fallback_respects_context_cap(self):
        self.child_a.content = "fallback-evidence-" * 4
        self.child_a.context_parent_id = "missing-parent-id"
        self.child_a.save(update_fields=["content", "context_parent_id", "updated_at"])

        resolved = resolve_parent_context(
            [self.hit(self.child_a, 0.9)], tenant_id=self.tenant.id, max_context_chars=12
        )[0]

        self.assertEqual(len(resolved["content"]), 12)
        self.assertTrue(resolved["context_window"]["clipped"])
        self.assertTrue(resolved["matched_ranges"][0]["clipped"])

    def test_enabled_unmatched_sibling_edit_overlays_parent_without_mutating_raw_storage(self):
        self.child_b.content = "EDITED"
        self.child_b.save(update_fields=["content", "updated_at"])

        resolved = resolve_parent_context(
            [self.hit(self.child_a, 0.9)], tenant_id=self.tenant.id, max_context_chars=4096
        )

        self.assertEqual(resolved[0]["content"], "0123456789EDITEDGHIJ")
        self.assertEqual(resolved[0]["applied_edit_child_ids"], [self.child_b.id])
        self.parent.refresh_from_db()
        self.assertEqual(self.parent.content, "0123456789ABCDEFGHIJ")

    def test_overlapping_edits_are_applied_deterministically_without_unchanged_window_duplication(self):
        self.parent.content = "abcdefghij"
        self.parent.start_at = 0
        self.parent.end_at = 10
        self.parent.save(update_fields=["content", "start_at", "end_at", "updated_at"])
        self.child_a.content = "abcdef"
        self.child_a.start_at = 0
        self.child_a.end_at = 6
        self.child_a.save(update_fields=["content", "start_at", "end_at", "updated_at"])
        edit_a = self.create_child("EDIT-A", 2, 6, 4)
        edit_b = self.create_child("EDIT-B", 4, 8, 5)

        first = resolve_parent_context(
            [self.hit(self.child_a, 0.9)], tenant_id=self.tenant.id, max_context_chars=4096
        )
        second = resolve_parent_context(
            [self.hit(self.child_a, 0.9)], tenant_id=self.tenant.id, max_context_chars=4096
        )

        self.assertEqual(first[0]["content"], "abEDIT-AEDIT-Bij")
        self.assertEqual(first[0]["applied_edit_child_ids"], [edit_a.id, edit_b.id])
        self.assertEqual(first, second)

    def test_context_cap_keeps_highest_ranked_evidence_visible_and_explains_clipping(self):
        self.parent.content = "x" * 40 + "EVIDENCE" + "y" * 40
        self.parent.start_at = 0
        self.parent.end_at = len(self.parent.content)
        self.parent.save(update_fields=["content", "start_at", "end_at", "updated_at"])
        self.child_a.content = "EVIDENCE"
        self.child_a.start_at = 40
        self.child_a.end_at = 48
        self.child_a.save(update_fields=["content", "start_at", "end_at", "updated_at"])

        resolved = resolve_parent_context(
            [self.hit(self.child_a, 0.9)], tenant_id=self.tenant.id, max_context_chars=20
        )[0]

        self.assertEqual(len(resolved["content"]), 20)
        self.assertIn("EVIDENCE", resolved["content"])
        self.assertTrue(resolved["context_window"]["clipped"])
        self.assertEqual(resolved["context_window"]["max_context_chars"], 20)
        self.assertTrue(resolved["matched_ranges"][0]["visible"])
        self.assertFalse(resolved["matched_ranges"][0]["clipped"])

    def test_flat_media_graph_and_already_resolved_results_are_unchanged(self):
        flat = self.create_child("flat", 0, 4, 3, context_parent_id=None)
        media = self.create_child("ocr", 0, 3, 4, chunk_type="image_ocr", context_parent_id=None)
        graph = {"chunk_id": "graph-1", "content": "graph", "retrieval_path": "graph", "score": 0.4}
        already_resolved = {
            **self.hit(self.child_a, 0.9),
            "parent_chunk_id": self.parent.id,
            "matched_child_ids": [self.child_a.id],
        }
        inputs = [self.hit(flat, 0.8), self.hit(media, 0.7), graph, already_resolved]

        resolved = resolve_parent_context(inputs, tenant_id=self.tenant.id, max_context_chars=4096)

        self.assertEqual(resolved, inputs)
