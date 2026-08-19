import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


def main():
    import django

    django.setup()

    from django.conf import settings

    from personal_knowledge_base.graph_rag import (
        effective_extract_config,
        graph_enabled,
        graph_repository,
        parse_graph_json,
        render_graph_examples,
        render_graph_prompt_description,
    )
    from personal_knowledge_base.model_providers import role_completion
    from personal_knowledge_base.models import Chunk, Knowledge, KnowledgeBase, KnowledgeProcessingSpan

    lines = []
    lines.append("=== Neo4j / GraphRAG configuration ===")
    lines.append(f"NEO4J_ENABLE={settings.NEO4J_ENABLE}")
    lines.append(f"NEO4J_URI={settings.NEO4J_URI}")
    lines.append(f"graph_repository.enabled={graph_repository.enabled}")
    lines.append(f"graph_repository.available={graph_repository.available}")

    lines.append("\n=== Django knowledge base graph flags ===")
    for kb in KnowledgeBase.objects.filter(deleted_at__isnull=True, is_temporary=False).order_by("created_at"):
        lines.append(f"KB {kb.id} {kb.name}")
        lines.append(f"  indexing_strategy={json.dumps(kb.indexing_strategy or {}, ensure_ascii=False)}")
        lines.append(f"  extract_config.enabled={(kb.extract_config or {}).get('enabled')}")
        lines.append(f"  graph_enabled(kb)={graph_enabled(kb)}")

    lines.append("\n=== Processed document graph metadata ===")
    for knowledge in Knowledge.objects.filter(deleted_at__isnull=True).order_by("created_at"):
        metadata = knowledge.metadata or {}
        lines.append(f"Knowledge {knowledge.id} {knowledge.title[:80]}")
        lines.append(f"  parse_status={knowledge.parse_status}")
        lines.append(f"  process_config={json.dumps(metadata.get('process_config') or {}, ensure_ascii=False)}")
        lines.append(f"  metadata.graph={json.dumps(metadata.get('graph') or {}, ensure_ascii=False)}")
        lines.append(f"  warnings={json.dumps(metadata.get('processing_warnings') or [], ensure_ascii=False)}")

    lines.append("\n=== Multimodal graph extraction spans ===")
    for span in KnowledgeProcessingSpan.objects.filter(name="multimodal").order_by("-started_at")[:20]:
        lines.append(
            f"Span knowledge={span.knowledge_id} status={span.status} "
            f"output={json.dumps(span.output_data or {}, ensure_ascii=False)} "
            f"error={span.error_message or ''}"
        )

    lines.append("\n=== Neo4j labels and relationship types ===")
    if graph_repository.available:
        with graph_repository.driver.session() as session:
            labels = session.run("CALL db.labels() YIELD label RETURN collect(label) AS labels").single()["labels"]
            rels = session.run("CALL db.relationshipTypes() YIELD relationshipType RETURN collect(relationshipType) AS rels").single()["rels"]
            entity_labels = session.run(
                "CALL db.labels() YIELD label WHERE label STARTS WITH 'ENTITY' RETURN collect(label) AS labels"
            ).single()["labels"]
        lines.append(f"labels={labels}")
        lines.append(f"relationship_types={rels}")
        lines.append(f"ENTITY_labels={entity_labels}")

    lines.append("\n=== One real chunk extraction probe ===")
    chunk = Chunk.objects.filter(deleted_at__isnull=True, content__gt="").select_related("knowledge", "knowledge_base").first()
    if chunk:
        kb = chunk.knowledge_base
        extract_config = effective_extract_config(kb, (chunk.knowledge.metadata or {}).get("process_config") or {})
        prompt = f"""
{render_graph_prompt_description(extract_config)}

# Examples
{render_graph_examples(extract_config)}

# Question
Q: {chunk.content[:6000]}
A:
""".strip()
        raw = role_completion(
            "extract",
            prompt,
            "",
            6000,
            tenant=chunk.tenant,
            scenario="debug_graph_entity_extract",
        )
        parsed = parse_graph_json(raw)
        lines.append(f"chunk_id={chunk.id}")
        lines.append(f"chunk_content_sample={chunk.content[:300].replace(chr(10), ' ')}")
        lines.append(f"raw_output={raw[:2000]}")
        lines.append(f"parsed_node_count={len(parsed.get('node') or [])}")
        lines.append(f"parsed_relation_count={len(parsed.get('relation') or [])}")
        lines.append(f"parsed={json.dumps(parsed, ensure_ascii=False)[:2000]}")
    else:
        lines.append("No chunk found")

    result_path = ROOT / "tests" / "current_graph_rag_debug_result.txt"
    result_path.write_text("\n".join(lines), encoding="utf-8")
    print(result_path)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
