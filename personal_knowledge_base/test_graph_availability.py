from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from neo4j.exceptions import ServiceUnavailable, SessionExpired

from .authentication import issue_tokens
from .graph_rag import GraphNamespace, Neo4jGraphRepository, delete_knowledge_graph, graph_search_results
from .models import Chunk, Knowledge, KnowledgeBase, Tenant, User
from .serializers import kb_dict


CONFIG = {"enabled": True, "uri": "bolt://localhost:7687", "username": "neo4j", "password": "fixture"}


class GraphAvailabilityTests(SimpleTestCase):
    def test_optional_graph_connection_does_not_retry_for_thirty_seconds(self):
        repository = Neo4jGraphRepository()
        with patch("personal_knowledge_base.neo4j_connection.neo4j_configuration", return_value=CONFIG.copy()), patch(
            "neo4j.GraphDatabase.driver"
        ) as factory:
            self.assertIs(repository.driver, factory.return_value)
        self.assertEqual(factory.call_args.kwargs.get("max_transaction_retry_time"), 0)

    def test_connection_outage_propagates_for_strict_graph_cleanup(self):
        for error in (ServiceUnavailable("offline"), SessionExpired("expired")):
            with self.subTest(error=type(error).__name__):
                repository = Neo4jGraphRepository()
                driver = MagicMock()
                driver.session.return_value.__enter__.return_value.execute_write.side_effect = error
                with patch.object(Neo4jGraphRepository, "driver", new=property(lambda _: driver)), self.assertRaises(type(error)):
                    repository.delete_graph([GraphNamespace("kb", "doc")])

    def test_healthy_cleanup_keeps_all_namespaces_and_programming_errors_are_not_hidden(self):
        repository = Neo4jGraphRepository()
        driver = MagicMock()
        session = driver.session.return_value.__enter__.return_value
        with patch.object(Neo4jGraphRepository, "driver", new=property(lambda _: driver)):
            repository.delete_graph([GraphNamespace("kb", "doc1"), GraphNamespace("kb", "doc2")])
            self.assertEqual(session.execute_write.call_count, 2)
            session.execute_write.side_effect = ValueError("bad query")
            with self.assertRaises(ValueError):
                repository.delete_graph([GraphNamespace("kb", "doc1")])


class KnowledgeDeletionAvailabilityTests(TestCase):
    @override_settings(NEO4J_ENABLE=True)
    def test_legacy_purge_stops_before_local_deletion_when_graph_is_offline(self):
        from .legacy_cleanup import purge_legacy_knowledge

        tenant = Tenant.objects.create(name="strict purge", api_key="strict-purge")
        kb = KnowledgeBase.objects.create(tenant=tenant, name="fixture")
        doc = Knowledge.objects.create(tenant=tenant, knowledge_base=kb, type="file", title="fixture")
        chunk = Chunk.objects.create(tenant=tenant, knowledge_base=kb, knowledge=doc, content="fixture", chunk_index=0)
        driver = MagicMock()
        driver.session.return_value.__enter__.return_value.execute_write.side_effect = ServiceUnavailable("offline")
        with patch.object(Neo4jGraphRepository, "driver", new=property(lambda _: driver)), self.assertRaises(ServiceUnavailable):
            purge_legacy_knowledge()
        self.assertTrue(Knowledge.objects.filter(id=doc.id).exists())
        self.assertTrue(Chunk.objects.filter(id=chunk.id).exists())

    def test_move_does_not_reassign_document_or_chunks_when_graph_cleanup_fails(self):
        tenant = Tenant.objects.create(name="strict move", api_key="strict-move")
        user = User.objects.create(username="move", email="move@fixture.invalid", tenant=tenant, password_hash="unused")
        token, _ = issue_tokens(user)
        source = KnowledgeBase.objects.create(tenant=tenant, name="source")
        target = KnowledgeBase.objects.create(tenant=tenant, name="target")
        doc = Knowledge.objects.create(tenant=tenant, knowledge_base=source, type="file", title="fixture")
        chunk = Chunk.objects.create(tenant=tenant, knowledge_base=source, knowledge=doc, content="fixture", chunk_index=0)
        driver = MagicMock()
        driver.session.return_value.__enter__.return_value.execute_write.side_effect = ServiceUnavailable("offline")
        with patch.object(Neo4jGraphRepository, "driver", new=property(lambda _: driver)), self.assertRaises(ServiceUnavailable):
            self.client.post(f"/api/v1/knowledge-bases/{source.id}/knowledge/move", {"ids": [doc.id], "target_kb_id": target.id}, content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}")
        doc.refresh_from_db()
        chunk.refresh_from_db()
        self.assertEqual(doc.knowledge_base_id, source.id)
        self.assertEqual(chunk.knowledge_base_id, source.id)

    def test_live_document_graph_cleanup_remains_strict(self):
        tenant = Tenant.objects.create(name="strict cleanup", api_key="strict-cleanup")
        kb = KnowledgeBase.objects.create(tenant=tenant, name="fixture")
        doc = Knowledge.objects.create(tenant=tenant, knowledge_base=kb, type="file", title="fixture")
        with patch("personal_knowledge_base.graph_rag.graph_repository.delete_graph", side_effect=ServiceUnavailable("offline")):
            with self.assertRaises(ServiceUnavailable):
                delete_knowledge_graph(doc)

    def test_graph_search_ignores_chunks_moved_out_of_requested_library_and_retired_documents(self):
        tenant = Tenant.objects.create(name="search scope", api_key="search-scope")
        source = KnowledgeBase.objects.create(tenant=tenant, name="source", indexing_strategy={"graph_enabled": True})
        target = KnowledgeBase.objects.create(tenant=tenant, name="target")
        live = Knowledge.objects.create(tenant=tenant, knowledge_base=source, type="file", title="live")
        retired = Knowledge.objects.create(tenant=tenant, knowledge_base=source, type="file", title="retired", deleted_at=timezone.now())
        moved = Knowledge.objects.create(tenant=tenant, knowledge_base=target, type="file", title="moved")
        chunks = [Chunk.objects.create(tenant=tenant, knowledge_base=doc.knowledge_base, knowledge=doc, content=doc.title, chunk_index=0) for doc in (live, retired, moved)]
        graph = {"node": [{"name": "fixture", "chunks": [chunk.id for chunk in chunks]}]}
        with patch.object(Neo4jGraphRepository, "available", new=property(lambda _: True)), patch(
            "personal_knowledge_base.graph_rag.extract_query_entities", return_value=["fixture"]
        ), patch("personal_knowledge_base.graph_rag.graph_repository.search_node", return_value=graph):
            results = graph_search_results(tenant.id, [source.id], "fixture")
        self.assertEqual([item["chunk_id"] for item in results], [chunks[0].id])

    def test_statistics_ignore_chunks_and_processing_states_from_deleted_documents(self):
        tenant = Tenant.objects.create(name="count fixture", api_key="count-fixture")
        kb = KnowledgeBase.objects.create(tenant=tenant, name="fixture")
        live = Knowledge.objects.create(tenant=tenant, knowledge_base=kb, type="file", title="live", parse_status="completed")
        retired = Knowledge.objects.create(tenant=tenant, knowledge_base=kb, type="file", title="retired", parse_status="processing", deleted_at=timezone.now())
        for doc in (live, retired):
            Chunk.objects.create(tenant=tenant, knowledge_base=kb, knowledge=doc, content="body", chunk_type="text", chunk_index=0)
            Chunk.objects.create(tenant=tenant, knowledge_base=kb, knowledge=doc, content="parent", chunk_type="parent", chunk_index=1)
        data = kb_dict(kb)
        self.assertEqual(data["knowledge_count"], 1)
        self.assertEqual(data["chunk_count"], 1)
        self.assertEqual(data["total_chunk_count"], 2)
        self.assertEqual(data["processing_count"], 0)

    def test_document_and_chunks_are_deleted_when_neo4j_is_offline(self):
        tenant = Tenant.objects.create(name="graph outage fixture", api_key="graph-outage-fixture")
        user = User.objects.create(username="outage", email="outage@fixture.invalid", tenant=tenant, password_hash="unused")
        token, _ = issue_tokens(user)
        kb = KnowledgeBase.objects.create(tenant=tenant, name="fixture", indexing_strategy={"graph_enabled": False})
        doc = Knowledge.objects.create(tenant=tenant, knowledge_base=kb, type="file", title="fixture", parse_status="completed")
        Chunk.objects.create(tenant=tenant, knowledge_base=kb, knowledge=doc, content="fixture", chunk_index=0)
        driver = MagicMock()
        driver.session.return_value.__enter__.return_value.execute_write.side_effect = ServiceUnavailable("offline")
        with patch.object(Neo4jGraphRepository, "driver", new=property(lambda _: driver)):
            response = self.client.delete(f"/api/v1/knowledge/{doc.id}", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(response.status_code, 200)
        doc.refresh_from_db()
        self.assertIsNotNone(doc.deleted_at)
        self.assertFalse(Chunk.objects.filter(knowledge=doc).exists())

    def test_cleanup_preserves_inconsistent_chunks_owned_by_other_tenants(self):
        from knowledge.views import delete_knowledge_content, retire_knowledge_for_delete

        tenant = Tenant.objects.create(name="owner", api_key="owner-fixture")
        other = Tenant.objects.create(name="other", api_key="other-fixture")
        kb = KnowledgeBase.objects.create(tenant=tenant, name="fixture")
        doc = Knowledge.objects.create(tenant=tenant, knowledge_base=kb, type="file", title="fixture")
        owned = Chunk.objects.create(tenant=tenant, knowledge_base=kb, knowledge=doc, content="owned", chunk_index=0)
        foreign = Chunk.objects.create(tenant=other, knowledge_base=kb, knowledge=doc, content="foreign", chunk_index=1)
        with patch("knowledge.views.delete_knowledge_graph"), patch("knowledge.views.delete_chunk_index") as delete_index:
            retire_knowledge_for_delete(doc)
            delete_knowledge_content(doc)
        delete_index.assert_called_once_with(owned.id, owned.seq_id)
        self.assertFalse(Chunk.objects.filter(id=owned.id).exists())
        self.assertTrue(Chunk.objects.filter(id=foreign.id).exists())
