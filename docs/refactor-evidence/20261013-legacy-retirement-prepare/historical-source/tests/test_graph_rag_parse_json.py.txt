import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()


def assert_equal(actual, expected, message):
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def assert_true(value, message):
    if not value:
        raise AssertionError(message)


def test_fenced_json_array_parses_nodes_and_relations():
    from personal_knowledge_base.graph_rag import parse_graph_json

    graph = parse_graph_json(
        """```json
[
  {"entity": "Pyramid filter"},
  {"entity": "1D Wavelets"},
  {"entity1": "Pyramid filter", "entity2": "1D Wavelets", "relation": "uses", "strength": 3}
]
```"""
    )

    assert_equal([node["name"] for node in graph["node"]], ["Pyramid filter", "1D Wavelets"], "fenced array nodes")
    assert_equal(len(graph["relation"]), 1, "fenced array relation count")
    assert_equal(graph["relation"][0]["type"], "uses", "fenced array relation type")


def test_bare_json_array_parses_nodes_and_relations():
    from personal_knowledge_base.graph_rag import parse_graph_json

    graph = parse_graph_json(
        '[{"entity":"Motion magnification"},{"entity1":"Motion magnification","entity2":"Video","relation":"describes"}]'
    )

    assert_equal([node["name"] for node in graph["node"]], ["Motion magnification", "Video"], "bare array nodes")
    assert_equal(len(graph["relation"]), 1, "bare array relation count")


def test_object_format_still_parses():
    from personal_knowledge_base.graph_rag import parse_graph_json

    graph = parse_graph_json(
        '{"node":[{"name":"Neo4j","attributes":["graph db"]}],"relation":[{"node1":"Neo4j","node2":"GraphRAG","type":"uses"}]}'
    )

    assert_equal([node["name"] for node in graph["node"]], ["Neo4j", "GraphRAG"], "object nodes")
    assert_equal(len(graph["relation"]), 1, "object relation count")


def test_invalid_output_returns_empty_graph():
    from personal_knowledge_base.graph_rag import parse_graph_json

    graph = parse_graph_json("not json at all")

    assert_equal(graph, {"node": [], "relation": []}, "invalid output fallback")


def main():
    test_fenced_json_array_parses_nodes_and_relations()
    test_bare_json_array_parses_nodes_and_relations()
    test_object_format_still_parses()
    test_invalid_output_returns_empty_graph()
    print("test_graph_rag_parse_json: OK")


if __name__ == "__main__":
    main()
