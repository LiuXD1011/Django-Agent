import json
import os
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


def neo4j_entity_labels(graph_repository):
    if not graph_repository.available:
        return []
    with graph_repository.driver.session() as session:
        record = session.run(
            "CALL db.labels() YIELD label "
            "WHERE label STARTS WITH 'ENTITY' "
            "RETURN collect(label) AS labels"
        ).single()
    return sorted(record["labels"] if record else [])


def neo4j_relationship_types(graph_repository):
    if not graph_repository.available:
        return []
    with graph_repository.driver.session() as session:
        record = session.run(
            "CALL db.relationshipTypes() YIELD relationshipType "
            "RETURN collect(relationshipType) AS types"
        ).single()
    return sorted(record["types"] if record else [])


def update_graph_metadata(knowledge, node_count, relation_count, rebuilt_chunk_count=None, source_chunk_count=None):
    metadata = dict(knowledge.metadata or {})
    graph = dict(metadata.get("graph") or {})
    graph.update(
        {
            "enabled": True,
            "node_count": node_count,
            "relation_count": relation_count,
            "rebuilt_by": "tests/rebuild_current_graph_rag.py",
        }
    )
    if rebuilt_chunk_count is not None and source_chunk_count is not None:
        graph["rebuilt_chunk_count"] = rebuilt_chunk_count
        graph["source_chunk_count"] = source_chunk_count
        graph["sampled_rebuild"] = rebuilt_chunk_count < source_chunk_count
    metadata["graph"] = graph
    knowledge.metadata = metadata
    knowledge.save(update_fields=["metadata", "updated_at"])


def main():
    import django

    django.setup()

    from personal_knowledge_base.document_processing import process_graph
    from personal_knowledge_base.graph_rag import (
        GraphNamespace,
        build_graph_for_chunks,
        delete_knowledge_graph,
        effective_extract_config,
        graph_enabled,
        graph_repository,
    )
    from personal_knowledge_base.models import Chunk, Knowledge

    lines = []
    lines.append("=== Rebuild current GraphRAG document graph ===")
    lines.append(f"graph_repository.available={graph_repository.available}")
    if not graph_repository.available:
        raise AssertionError("Neo4j graph repository is not available")

    candidates = (
        Knowledge.objects.select_related("tenant", "knowledge_base")
        .filter(deleted_at__isnull=True, parse_status="completed", enable_status="enabled")
        .order_by("created_at")
    )
    max_knowledge = int(os.environ.get("GRAPH_RAG_REBUILD_MAX_KNOWLEDGE") or "0")
    max_chunks = int(os.environ.get("GRAPH_RAG_REBUILD_MAX_CHUNKS") or "0")
    rebuilt = []
    seen_knowledge = 0
    for knowledge in candidates:
        process_config = (knowledge.metadata or {}).get("process_config") or {}
        if not graph_enabled(knowledge.knowledge_base, process_config):
            continue
        seen_knowledge += 1
        if max_knowledge and seen_knowledge > max_knowledge:
            break
        chunks = list(
            Chunk.objects.filter(knowledge=knowledge, deleted_at__isnull=True, is_enabled=True)
            .order_by("chunk_index", "created_at")
        )
        if not chunks:
            lines.append(f"SKIP knowledge={knowledge.id} title={knowledge.title!r}: no chunks")
            continue
        original_chunk_count = len(chunks)
        if max_chunks:
            chunks = chunks[:max_chunks]
        progress = (
            f"[{datetime.now().strftime('%H:%M:%S')}] rebuilding knowledge={knowledge.id} "
            f"title={knowledge.title!r} chunks={len(chunks)}/{original_chunk_count}"
        )
        print(progress, flush=True)
        lines.append(progress)
        if max_chunks:
            delete_knowledge_graph(knowledge)
            extract_config = effective_extract_config(knowledge.knowledge_base, process_config)
            graphs = build_graph_for_chunks(chunks, extract_config, tenant=knowledge.tenant)
            if graphs:
                graph_repository.add_graph(
                    GraphNamespace(knowledge_base_id=knowledge.knowledge_base_id, knowledge_id=knowledge.id),
                    graphs,
                )
        else:
            graphs = process_graph(knowledge, chunks)
        node_count = sum(len(graph.get("node") or []) for graph in graphs)
        relation_count = sum(len(graph.get("relation") or []) for graph in graphs)
        update_graph_metadata(knowledge, node_count, relation_count, len(chunks), original_chunk_count)
        rebuilt.append(
            {
                "knowledge_id": knowledge.id,
                "title": knowledge.title,
                "chunk_count": len(chunks),
                "original_chunk_count": original_chunk_count,
                "node_count": node_count,
                "relation_count": relation_count,
            }
        )
        lines.append(
            f"REBUILT knowledge={knowledge.id} title={knowledge.title!r} "
            f"chunks={len(chunks)}/{original_chunk_count} nodes={node_count} relations={relation_count}"
        )
        print(lines[-1], flush=True)

    labels = neo4j_entity_labels(graph_repository)
    relationship_types = neo4j_relationship_types(graph_repository)
    lines.append("\n=== Neo4j after rebuild ===")
    lines.append(f"ENTITY_labels={json.dumps(labels, ensure_ascii=False)}")
    lines.append(f"relationship_types={json.dumps(relationship_types, ensure_ascii=False)}")
    lines.append(f"rebuilt_count={len(rebuilt)}")

    result_path = ROOT / "tests" / "current_graph_rag_rebuild_result.txt"
    result_path.write_text("\n".join(lines), encoding="utf-8")
    print(result_path)
    print("\n".join(lines))

    if not rebuilt:
        raise AssertionError("No graph-enabled completed knowledge was rebuilt")
    if not labels:
        raise AssertionError("No ENTITY labels found in Neo4j after rebuild")


if __name__ == "__main__":
    main()
