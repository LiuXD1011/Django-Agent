import json
import math
import re
from dataclasses import dataclass
from typing import Iterable

from django.conf import settings

from .model_providers import role_completion
from .models import Chunk, Knowledge, KnowledgeBase


DEFAULT_EXTRACT_CONFIG = {
    "enabled": True,
    "text": "从知识片段中抽取核心实体和实体关系，用于 GraphRAG 检索增强。",
    "tags": ["related_to", "part_of", "depends_on", "uses", "causes", "describes"],
    "nodes": [
        {"name": "Entity", "attributes": ["name", "description"]},
        {"name": "Concept", "attributes": ["name", "description"]},
    ],
    "relations": [
        {"node1": "Entity", "node2": "Entity", "type": "related_to"},
        {"node1": "Entity", "node2": "Concept", "type": "describes"},
    ],
}

DEFAULT_RELATION_BATCH_SIZE = 5
DIRECT_RELATION_LIMIT = 8
INDIRECT_RELATION_LIMIT = 8


@dataclass(frozen=True)
class GraphNamespace:
    knowledge_base_id: str = ""
    knowledge_id: str = ""

    def labels(self) -> list[str]:
        return [value for value in [self.knowledge_base_id, self.knowledge_id] if value]


def bool_value(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "on", "enabled"}


def graph_enabled(kb: KnowledgeBase, process_config: dict | None = None) -> bool:
    process_config = process_config or {}
    strategy = kb.indexing_strategy or {}
    override = process_config.get("graph_enabled")
    return bool_value(override, bool_value(strategy.get("graph_enabled"), False))


def effective_extract_config(kb: KnowledgeBase, process_config: dict | None = None) -> dict:
    process_config = process_config or {}
    base = dict(DEFAULT_EXTRACT_CONFIG)
    if isinstance(kb.extract_config, dict):
        base.update(kb.extract_config)
    override = process_config.get("extract_config") or process_config.get("extractConfig")
    if isinstance(override, dict):
        base.update(override)
    if "graph_enabled" in process_config:
        base["enabled"] = bool_value(process_config.get("graph_enabled"), base.get("enabled"))
    return base


def validate_extract_config(config):
    if config is None:
        return None
    if not isinstance(config, dict):
        return "extract_config must be an object"
    if not bool_value(config.get("enabled"), False):
        return None
    if not str(config.get("text") or "").strip():
        return "extract_config.text is required when graph is enabled"
    tags = config.get("tags") or []
    if not isinstance(tags, list) or not [x for x in tags if str(x).strip()]:
        return "extract_config.tags is required when graph is enabled"
    nodes = config.get("nodes") or []
    if not isinstance(nodes, list) or not nodes:
        return "extract_config.nodes is required when graph is enabled"
    node_names = set()
    for index, node in enumerate(nodes):
        if not isinstance(node, dict) or not str(node.get("name") or "").strip():
            return f"extract_config.nodes[{index}].name is required"
        name = str(node["name"]).strip()
        if name in node_names:
            return f"duplicate extract_config node: {name}"
        node_names.add(name)
    relations = config.get("relations") or []
    if not isinstance(relations, list) or not relations:
        return "extract_config.relations is required when graph is enabled"
    for index, relation in enumerate(relations):
        if not isinstance(relation, dict):
            return f"extract_config.relations[{index}] must be an object"
        if not str(relation.get("node1") or "").strip():
            return f"extract_config.relations[{index}].node1 is required"
        if not str(relation.get("node2") or "").strip():
            return f"extract_config.relations[{index}].node2 is required"
        if not str(relation.get("type") or "").strip():
            return f"extract_config.relations[{index}].type is required"
        if relation["node1"] not in node_names:
            return f"relation references non-existent node1: {relation['node1']}"
        if relation["node2"] not in node_names:
            return f"relation references non-existent node2: {relation['node2']}"
    return None


class Neo4jGraphRepository:
    node_prefix = "ENTITY"

    def __init__(self):
        self._driver = None

    @property
    def enabled(self):
        return bool_value(getattr(settings, "NEO4J_ENABLE", False), False)

    @property
    def available(self):
        return self.enabled and self.driver is not None

    @property
    def driver(self):
        if not self.enabled:
            return None
        if self._driver is not None:
            return self._driver
        try:
            from neo4j import GraphDatabase
        except Exception:
            return None
        try:
            self._driver = GraphDatabase.driver(
                settings.NEO4J_URI,
                auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
            )
        except Exception:
            self._driver = None
        return self._driver

    def labels(self, namespace: GraphNamespace) -> list[str]:
        return [self.node_prefix + re.sub(r"[^A-Za-z0-9_]", "_", label) for label in namespace.labels()]

    def label_expr(self, namespace: GraphNamespace) -> str:
        return ":".join(self.labels(namespace))

    def add_graph(self, namespace: GraphNamespace, graphs: Iterable[dict]):
        if not self.available:
            return
        label_expr = self.label_expr(namespace)
        with self.driver.session() as session:
            for graph in graphs:
                nodes = graph.get("node") or graph.get("nodes") or []
                relations = graph.get("relation") or graph.get("relations") or []
                session.execute_write(self._add_nodes, label_expr, namespace.knowledge_id, nodes)
                session.execute_write(self._add_relations, label_expr, namespace.knowledge_id, relations)

    @staticmethod
    def _add_nodes(tx, label_expr, knowledge_id, nodes):
        for node in nodes:
            name = node.get("name") or node.get("title")
            if not name:
                continue
            chunks = node.get("chunks") or []
            attributes = node.get("attributes") or []
            tx.run(
                f"""
                MERGE (n:{label_expr} {{name: $name, kg: $knowledge_id}})
                SET n.attributes = $attributes
                SET n.chunks = apoc.coll.toSet(coalesce(n.chunks, []) + $chunks)
                """,
                name=name,
                knowledge_id=knowledge_id,
                attributes=attributes,
                chunks=chunks,
            )

    @staticmethod
    def _add_relations(tx, label_expr, knowledge_id, relations):
        for relation in relations:
            source = relation.get("node1") or relation.get("source")
            target = relation.get("node2") or relation.get("target")
            rel_type = re.sub(r"[^A-Za-z0-9_]", "_", relation.get("type") or "related_to")
            if not source or not target:
                continue
            tx.run(
                f"""
                MERGE (s:{label_expr} {{name: $source, kg: $knowledge_id}})
                MERGE (t:{label_expr} {{name: $target, kg: $knowledge_id}})
                MERGE (s)-[r:{rel_type}]->(t)
                """,
                source=source,
                target=target,
                knowledge_id=knowledge_id,
            )

    def delete_graph(self, namespaces: Iterable[GraphNamespace]):
        if not self.available:
            return
        with self.driver.session() as session:
            for namespace in namespaces:
                label_expr = self.label_expr(namespace)
                session.execute_write(self._delete_namespace, label_expr, namespace.knowledge_id)

    @staticmethod
    def _delete_namespace(tx, label_expr, knowledge_id):
        tx.run(f"MATCH (n:{label_expr} {{kg: $knowledge_id}}) DETACH DELETE n", knowledge_id=knowledge_id)

    def search_node(self, namespace: GraphNamespace, nodes: list[str]) -> dict:
        if not self.available or not nodes:
            return {"node": [], "relation": []}
        label_expr = self.label_expr(namespace)
        with self.driver.session() as session:
            return session.execute_read(self._search_node, label_expr, nodes)

    @staticmethod
    def _search_node(tx, label_expr, nodes):
        result = tx.run(
            f"""
            MATCH (n:{label_expr})-[r]-(m:{label_expr})
            WHERE ANY(nodeText IN $nodes WHERE toLower(n.name) CONTAINS toLower(nodeText))
            RETURN n, r, m
            LIMIT 200
            """,
            nodes=nodes,
        )
        graph = {"node": [], "relation": []}
        seen = set()
        for record in result:
            source = record["n"]
            target = record["m"]
            rel = record["r"]
            for item in [source, target]:
                name = item.get("name")
                if name and name not in seen:
                    seen.add(name)
                    graph["node"].append(
                        {
                            "name": name,
                            "chunks": list(item.get("chunks") or []),
                            "attributes": list(item.get("attributes") or []),
                        }
                    )
            graph["relation"].append({"node1": source.get("name"), "node2": target.get("name"), "type": rel.type})
        return graph


graph_repository = Neo4jGraphRepository()


def graph_database_engine():
    return "Neo4j" if graph_repository.available else ""


def neo4j_configured():
    return graph_repository.available


def graph_rag_enabled():
    return graph_repository.enabled


def extract_graph_from_text(text: str, extract_config: dict, chunk_id: str = "", tenant=None) -> dict:
    if not text.strip():
        return {"node": [], "relation": []}
    graph = extract_entities_from_text(text, extract_config, chunk_id, tenant=tenant)
    relation_graph = extract_relationships_for_batch(text, graph["node"], extract_config, tenant=tenant)
    graph["relation"] = relation_graph["relation"]
    return rebuild_graph(graph)


def extract_entities_from_text(text: str, extract_config: dict, chunk_id: str = "", tenant=None) -> dict:
    if not text.strip():
        return {"node": [], "relation": []}
    prompt = f"""
{render_graph_prompt_description(extract_config)}

# Examples
{render_graph_examples(extract_config)}

# Question
Q: {text[:6000]}
A:
""".strip()
    raw = role_completion("extract", prompt, "", 6000, tenant=tenant, scenario="graph_entity_extract")
    graph = parse_graph_json(raw)
    for node in graph["node"]:
        node["chunks"] = [chunk_id] if chunk_id else node.get("chunks", [])
    return rebuild_graph({"node": graph["node"], "relation": []})


def extract_relationships_for_batch(text: str, nodes: list[dict], extract_config: dict, tenant=None) -> dict:
    if len(nodes) < 2 or not text.strip():
        return {"node": nodes, "relation": []}
    entity_json = json.dumps(nodes, ensure_ascii=False)
    prompt = f"""
{render_graph_prompt_description(extract_config)}

Allowed relation types: {json.dumps(extract_config.get('tags') or [], ensure_ascii=False)}
Allowed relation schema: {json.dumps(extract_config.get('relations') or [], ensure_ascii=False)}

Return strict JSON only as a list of relation objects:
[
  {{"entity1":"...", "entity2":"...", "relation":"...", "strength": 1}}
]

Entities:
{entity_json}

Text:
{text[:8000]}
""".strip()
    graph = parse_graph_json(role_completion("extract", prompt, "", 6000, tenant=tenant, scenario="graph_relation_extract"))
    return rebuild_graph({"node": nodes, "relation": graph["relation"]})


def build_graph_for_chunks(chunks: list[Chunk], extract_config: dict, tenant=None) -> list[dict]:
    chunk_graphs = []
    chunk_entities = []
    entity_by_name: dict[str, dict] = {}
    for chunk in chunks:
        graph = extract_entities_from_text(chunk.content, extract_config, chunk.id, tenant=tenant)
        for node in graph["node"]:
            if not node.get("chunks"):
                node["chunks"] = [chunk.id]
        chunk_graphs.append(graph)
        chunk_entities.append(graph["node"])
        for node in graph["node"]:
            name = node.get("name")
            if not name:
                continue
            existing = entity_by_name.get(name)
            if not existing:
                entity_by_name[name] = {**node, "chunks": list(node.get("chunks") or []), "frequency": len(node.get("chunks") or []) or 1}
            else:
                existing["chunks"] = list(dict.fromkeys([*existing.get("chunks", []), *(node.get("chunks") or [])]))
                existing["attributes"] = list(dict.fromkeys([*existing.get("attributes", []), *(node.get("attributes") or [])]))
                existing["frequency"] = int(existing.get("frequency") or 1) + 1

    relation_graphs = []
    relationships: dict[tuple[str, str], dict] = {}
    for start in range(0, len(chunks), DEFAULT_RELATION_BATCH_SIZE):
        batch_chunks = chunks[start : start + DEFAULT_RELATION_BATCH_SIZE]
        batch_nodes = []
        for nodes in chunk_entities[start : start + DEFAULT_RELATION_BATCH_SIZE]:
            batch_nodes.extend(nodes)
        batch_nodes = normalize_graph_nodes(batch_nodes)
        if len(batch_nodes) < 2:
            continue
        content = merge_chunk_contents(batch_chunks)
        graph = extract_relationships_for_batch(content, batch_nodes, extract_config, tenant=tenant)
        relation_graphs.append(graph)
        for relation in graph["relation"]:
            source = relation.get("node1")
            target = relation.get("node2")
            if not source or not target:
                continue
            key = (source, target)
            chunk_ids = relation_chunk_ids(source, target, entity_by_name)
            if not chunk_ids:
                continue
            if key not in relationships:
                relationships[key] = {**relation, "chunks": chunk_ids, "strength": int(relation.get("strength") or 1)}
            else:
                existing = relationships[key]
                existing["chunks"] = list(dict.fromkeys([*existing.get("chunks", []), *chunk_ids]))
                existing["strength"] = max(int(existing.get("strength") or 1), int(relation.get("strength") or 1))

    weighted_relations = weight_relationships(entity_by_name, relationships)
    full_graph = {"node": list(entity_by_name.values()), "relation": list(weighted_relations.values())}
    build_chunk_relation_graph(chunks, [full_graph])
    return [full_graph] if full_graph["node"] or full_graph["relation"] else chunk_graphs


def render_graph_prompt_description(extract_config: dict) -> str:
    tags = json.dumps(extract_config.get("tags") or [], ensure_ascii=False)
    text = extract_config.get("text") or DEFAULT_EXTRACT_CONFIG["text"]
    return text.replace("%s", tags) if "%s" in text else f"{text}\nAllowed relationship types: {tags}"


def render_graph_examples(extract_config: dict) -> str:
    examples = extract_config.get("examples")
    if not examples:
        examples = [{"text": extract_config.get("text", ""), "node": extract_config.get("nodes") or [], "relation": extract_config.get("relations") or []}]
    lines = []
    for example in examples[:3]:
        lines.append(f"Q: {example.get('text') or ''}")
        lines.append(f"A: {format_graph_example(example)}")
    return "\n".join(lines)


def format_graph_example(example: dict) -> str:
    items = []
    for node in example.get("node") or []:
        item = {"entity": node.get("name") or node.get("title") or "Entity"}
        attrs = node.get("attributes") or []
        if attrs:
            item["entity_attributes"] = attrs
        items.append(item)
    for relation in example.get("relation") or []:
        items.append(
            {
                "entity1": relation.get("node1") or relation.get("source") or "Entity1",
                "entity2": relation.get("node2") or relation.get("target") or "Entity2",
                "relation": relation.get("type") or "related_to",
            }
        )
    return "```json\n" + json.dumps(items, ensure_ascii=False, indent=2) + "\n```"


def merge_chunk_contents(chunks: list[Chunk]) -> str:
    text = ""
    for chunk in chunks:
        content = chunk.content or ""
        if not text:
            text = content
            continue
        overlap = 0
        max_overlap = min(len(text), len(content), 200)
        for size in range(max_overlap, 0, -1):
            if text.endswith(content[:size]):
                overlap = size
                break
        text += content[overlap:]
    return text


def extract_query_entities(query: str) -> list[str]:
    prompt = f"""
Extract the key entity names from the user query. Return strict JSON only:
{{"node":[{{"name":"entity name"}}], "relation":[]}}

Query:
{query}
""".strip()
    graph = parse_graph_json(role_completion("extract", prompt, "", 2000, scenario="graph_query_extract"))
    return [node["name"] for node in graph["node"] if node.get("name")]


def parse_graph_json(raw: str) -> dict:
    if not raw:
        return {"node": [], "relation": []}
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S | re.I)
    if fenced:
        text = fenced.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        payload = json.loads(text)
    except Exception:
        return {"node": [], "relation": []}
    if isinstance(payload, list):
        nodes = []
        relations = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            if item.get("entity") or item.get("name") or item.get("title"):
                nodes.append(
                    {
                        "name": item.get("entity") or item.get("name") or item.get("title"),
                        "attributes": item.get("entity_attributes") or item.get("attributes") or [],
                    }
                )
            if item.get("entity1") or item.get("entity2"):
                relations.append(
                    {
                        "node1": item.get("entity1"),
                        "node2": item.get("entity2"),
                        "type": item.get("relation") or item.get("type") or "related_to",
                        "strength": item.get("strength") or 1,
                    }
                )
        return rebuild_graph({"node": normalize_graph_nodes(nodes), "relation": normalize_graph_relations(relations)})
    if not isinstance(payload, dict):
        return {"node": [], "relation": []}
    nodes = payload.get("node") or payload.get("nodes") or []
    relations = payload.get("relation") or payload.get("relations") or []
    return rebuild_graph({"node": normalize_graph_nodes(nodes), "relation": normalize_graph_relations(relations)})


def normalize_graph_nodes(nodes) -> list[dict]:
    result = []
    seen = set()
    if not isinstance(nodes, list):
        return result
    for node in nodes:
        if isinstance(node, str):
            node = {"name": node}
        if not isinstance(node, dict):
            continue
        name = str(node.get("name") or node.get("title") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        attributes = node.get("attributes") or node.get("entity_attributes") or []
        if isinstance(attributes, str):
            attributes = [attributes]
        result.append({"name": name, "attributes": [str(x) for x in attributes if str(x).strip()], "chunks": node.get("chunks") or []})
    return result


def normalize_graph_relations(relations) -> list[dict]:
    result = []
    if not isinstance(relations, list):
        return result
    for relation in relations:
        if not isinstance(relation, dict):
            continue
        source = str(relation.get("node1") or relation.get("source") or "").strip()
        target = str(relation.get("node2") or relation.get("target") or "").strip()
        rel_type = str(relation.get("type") or relation.get("relation") or relation.get("description") or "related_to").strip()
        if source and target:
            strength = relation.get("strength") or relation.get("weight") or 1
            try:
                strength = int(float(strength))
            except Exception:
                strength = 1
            result.append({"node1": source, "node2": target, "type": rel_type, "strength": max(1, min(strength, 10))})
    return result


def rebuild_graph(graph: dict) -> dict:
    node_map = {node["name"]: node for node in normalize_graph_nodes(graph.get("node") or [])}
    relations = []
    seen = set()
    for relation in normalize_graph_relations(graph.get("relation") or []):
        if relation["node1"] == relation["node2"]:
            continue
        for key in ["node1", "node2"]:
            if relation[key] not in node_map:
                node_map[relation[key]] = {"name": relation[key], "attributes": [], "chunks": []}
        rel_key = (relation["node1"], relation["node2"], relation["type"])
        if rel_key in seen:
            continue
        seen.add(rel_key)
        relations.append(relation)
    return {"node": list(node_map.values()), "relation": relations}


def relation_chunk_ids(source: str, target: str, entities: dict[str, dict]) -> list[str]:
    ids = []
    for name in [source, target]:
        ids.extend(entities.get(name, {}).get("chunks") or [])
    return list(dict.fromkeys(ids))


def weight_relationships(entities: dict[str, dict], relationships: dict[tuple[str, str], dict]) -> dict[tuple[str, str], dict]:
    total_entity_occurrences = sum(max(len(entity.get("chunks") or []), 1) for entity in entities.values())
    total_relation_occurrences = sum(max(len(rel.get("chunks") or []), 1) for rel in relationships.values())
    if not total_entity_occurrences or not total_relation_occurrences:
        return relationships
    pmi_values = {}
    max_pmi = 0.0
    max_strength = 1
    for key, relation in relationships.items():
        source, target = key
        source_freq = max(len(entities.get(source, {}).get("chunks") or []), 1)
        target_freq = max(len(entities.get(target, {}).get("chunks") or []), 1)
        rel_freq = max(len(relation.get("chunks") or []), 1)
        source_prob = source_freq / total_entity_occurrences
        target_prob = target_freq / total_entity_occurrences
        rel_prob = rel_freq / total_relation_occurrences
        pmi = max(math.log2(rel_prob / (source_prob * target_prob)), 0) if source_prob and target_prob else 0
        pmi_values[key] = pmi
        max_pmi = max(max_pmi, pmi)
        max_strength = max(max_strength, int(relation.get("strength") or 1))
    for key, relation in relationships.items():
        normalized_pmi = pmi_values[key] / max_pmi if max_pmi else 0
        normalized_strength = int(relation.get("strength") or 1) / max_strength
        relation["weight"] = 1.0 + 9.0 * (normalized_pmi * 0.6 + normalized_strength * 0.4)
        relation["combined_degree"] = entity_degree(key[0], relationships) + entity_degree(key[1], relationships)
    return relationships


def entity_degree(name: str, relationships: dict[tuple[str, str], dict]) -> int:
    return sum(1 for source, target in relationships if source == name or target == name)


def build_chunk_relation_graph(chunks: list[Chunk], graphs: list[dict]):
    entity_chunks: dict[str, set[str]] = {}
    relation_edges: list[tuple[str, str, float, int]] = []
    for graph in graphs:
        for node in graph.get("node", []):
            name = node.get("name")
            if not name:
                continue
            entity_chunks.setdefault(name, set()).update(node.get("chunks") or [])
        for relation in graph.get("relation", []):
            source = relation.get("node1")
            target = relation.get("node2")
            if source and target:
                relation_edges.append((source, target, float(relation.get("weight") or 1.0), int(relation.get("combined_degree") or relation.get("strength") or 1)))

    chunk_graph: dict[str, dict[str, dict]] = {}
    for source, target, weight, degree in relation_edges:
        source_chunks = entity_chunks.get(source, set())
        target_chunks = entity_chunks.get(target, set())
        for source_chunk in source_chunks:
            for target_chunk in target_chunks:
                if source_chunk == target_chunk:
                    continue
                chunk_graph.setdefault(source_chunk, {})[target_chunk] = {"weight": weight, "degree": degree}
                chunk_graph.setdefault(target_chunk, {})[source_chunk] = {"weight": weight, "degree": degree}

    for chunk in chunks:
        direct = sorted_related_chunks(chunk_graph.get(chunk.id, {}), 8)
        indirect = sorted_indirect_chunks(chunk.id, chunk_graph, 8)
        chunk.relation_chunks = direct
        chunk.indirect_relation_chunks = indirect
        chunk.save(update_fields=["relation_chunks", "indirect_relation_chunks", "updated_at"])


def sorted_related_chunks(relations: dict[str, dict], top_k: int) -> list[str]:
    items = sorted(
        relations.items(),
        key=lambda item: (float(item[1].get("weight", 0)), int(item[1].get("degree", 0))),
        reverse=True,
    )
    return [chunk_id for chunk_id, _ in items[:top_k]]


def sorted_indirect_chunks(chunk_id: str, chunk_graph: dict[str, dict[str, dict]], top_k: int) -> list[str]:
    direct = set(chunk_graph.get(chunk_id, {}).keys())
    indirect = {}
    for direct_id in direct:
        direct_rel = chunk_graph.get(chunk_id, {}).get(direct_id) or {}
        for second_id, second_rel in chunk_graph.get(direct_id, {}).items():
            if second_id == chunk_id or second_id in direct:
                continue
            weight = float(direct_rel.get("weight", 1)) * float(second_rel.get("weight", 1)) * 0.5
            degree = max(int(direct_rel.get("degree", 0)), int(second_rel.get("degree", 0)))
            current = indirect.get(second_id)
            if not current or weight > current["weight"]:
                indirect[second_id] = {"weight": weight, "degree": degree}
    return sorted_related_chunks(indirect, top_k)


def graph_search_results(tenant_id: int, kb_ids: list[str], query: str, seen_chunk_ids: set[str] | None = None, top_k: int = 10) -> list[dict]:
    seen_chunk_ids = seen_chunk_ids or set()
    kbs = KnowledgeBase.objects.filter(tenant_id=tenant_id, id__in=kb_ids, deleted_at__isnull=True)
    kbs = [kb for kb in kbs if graph_enabled(kb)]
    if not kbs or not graph_repository.available:
        return []
    entities = extract_query_entities(query)
    if not entities:
        return []
    results = []
    chunk_ids = []
    for kb in kbs:
        graph = graph_repository.search_node(GraphNamespace(knowledge_base_id=kb.id), entities)
        for node in graph.get("node", []):
            for chunk_id in node.get("chunks") or []:
                if chunk_id not in seen_chunk_ids:
                    seen_chunk_ids.add(chunk_id)
                    chunk_ids.append(chunk_id)
    if not chunk_ids:
        return []
    chunks = Chunk.objects.filter(id__in=chunk_ids, tenant_id=tenant_id, is_enabled=True).select_related("knowledge", "knowledge_base")
    chunk_map = {chunk.id: chunk for chunk in chunks}
    for chunk_id in chunk_ids:
        chunk = chunk_map.get(chunk_id)
        if not chunk:
            continue
        results.append(chunk_to_graph_result(chunk))
        if len(results) >= top_k:
            break
    return results


def chunk_to_graph_result(chunk: Chunk) -> dict:
    return {
        "chunk_id": chunk.id,
        "id": chunk.id,
        "content": chunk.content,
        "score": 1.0,
        "match_type": "graph",
        "knowledge_id": chunk.knowledge_id,
        "knowledge_base_id": chunk.knowledge_base_id,
        "knowledge_title": chunk.knowledge.title,
        "knowledge_base_name": chunk.knowledge_base.name,
        "metadata": chunk.metadata or {},
    }


def expand_relation_context(results: list[dict], tenant_id: int, limit: int = 3) -> list[dict]:
    seen = {item.get("chunk_id") or item.get("id") for item in results}
    extra_ids = []
    source_chunks = Chunk.objects.filter(id__in=[x for x in seen if x], tenant_id=tenant_id)
    for chunk in source_chunks:
        for chunk_id in (chunk.relation_chunks or []) + (chunk.indirect_relation_chunks or []):
            if chunk_id not in seen:
                seen.add(chunk_id)
                extra_ids.append(chunk_id)
            if len(extra_ids) >= limit:
                break
        if len(extra_ids) >= limit:
            break
    extras = Chunk.objects.filter(id__in=extra_ids, tenant_id=tenant_id, is_enabled=True).select_related("knowledge", "knowledge_base")
    by_id = {chunk.id: chunk for chunk in extras}
    return [chunk_to_graph_result(by_id[chunk_id]) for chunk_id in extra_ids if chunk_id in by_id]


def delete_knowledge_graph(knowledge: Knowledge):
    graph_repository.delete_graph(
        [
            GraphNamespace(knowledge_base_id=knowledge.knowledge_base_id, knowledge_id=knowledge.id),
        ]
    )


def delete_kb_graph(kb: KnowledgeBase):
    namespaces = [
        GraphNamespace(knowledge_base_id=kb.id, knowledge_id=knowledge_id)
        for knowledge_id in Knowledge.objects.filter(knowledge_base=kb).values_list("id", flat=True)
    ]
    if namespaces:
        graph_repository.delete_graph(namespaces)
