#!/usr/bin/env python3
"""Measure and extrapolate Open RAG Benchmark runtime without tenant writes.

The upstream Open RAG corpus contains parsed JSON extracted from 1,000 arXiv
PDFs.  This script measures the runtime of this repository's download/index,
retrieval, embedding, and optional RAGAs paths; it does not measure PDF parsing
because the current public-dataset flow never parses source PDFs locally.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Iterable


def estimate_duration(sample_seconds: float, sample_count: int, total_count: int, concurrency: int = 1) -> dict:
    """Linearly extrapolate work that has a stable per-item cost."""
    if sample_count <= 0 or total_count <= 0:
        return {"seconds": None, "sample_per_item_seconds": None, "concurrency": max(1, concurrency)}
    workers = max(1, int(concurrency))
    per_item = float(sample_seconds) / int(sample_count)
    return {
        "seconds": round(per_item * int(total_count) / workers, 3),
        "sample_per_item_seconds": round(per_item, 6),
        "concurrency": workers,
    }


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "not_measured"
    seconds = round(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _configure_django() -> None:
    root = str(repository_root())
    if root not in sys.path:
        sys.path.insert(0, root)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()


def _section_rows(spec) -> list[tuple[str, str, str]]:
    from personal_knowledge_base.open_rag_benchmark import _load_corpus_documents, _section_content

    rows = []
    for document in _load_corpus_documents(spec):
        document_id = str(document["id"])
        for section in document["sections"]:
            section = section if isinstance(section, dict) else {}
            content = _section_content(section)
            if content:
                rows.append((document_id, str(section.get("section_id", "")), content))
    return rows


def _split_for_embedding(text: str, max_chars: int) -> Iterable[str]:
    """Model the required maximum-input guard without modifying stored corpus data."""
    for start in range(0, len(text), max_chars):
        yield text[start:start + max_chars]


def sample_by_length_quantiles(values: list[str], sample_size: int) -> list[str]:
    """Sample across input-length quantiles so latency is not biased low."""
    ordered = sorted(values, key=len)
    if not ordered or sample_size <= 0:
        return []
    if len(ordered) <= sample_size:
        return ordered
    if sample_size == 1:
        return [ordered[len(ordered) // 2]]
    return [ordered[index * (len(ordered) - 1) // (sample_size - 1)] for index in range(sample_size)]


def _measure_fts_build(rows: list[tuple[str, str, str]]) -> dict:
    started = time.perf_counter()
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE TABLE sections (id INTEGER PRIMARY KEY, doc_id TEXT, section_id TEXT, content TEXT NOT NULL)")
        connection.execute("CREATE VIRTUAL TABLE section_fts USING fts5(content, content='sections', content_rowid='id')")
        connection.executemany(
            "INSERT INTO sections(id, doc_id, section_id, content) VALUES (?, ?, ?, ?)",
            [(index, document_id, section_id, content) for index, (document_id, section_id, content) in enumerate(rows, start=1)],
        )
        connection.execute("INSERT INTO section_fts(section_fts) VALUES ('rebuild')")
        sections = connection.execute("SELECT COUNT(*) FROM sections").fetchone()[0]
    finally:
        connection.close()
    elapsed = time.perf_counter() - started
    return {"seconds": round(elapsed, 6), "sections": sections}


def _measure_fts_queries(spec, query_sample_size: int, seed: int) -> dict:
    from personal_knowledge_base.open_rag_benchmark import _index_path, _tokens, sample_open_rag_questions

    rows = sample_open_rag_questions(spec, query_sample_size, seed)
    connection = sqlite3.connect(_index_path(spec))
    started = time.perf_counter()
    result_counts = []
    try:
        for row in rows:
            terms = sorted(_tokens(row["query"]))
            match = " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms) or '""'
            result_counts.append(connection.execute("SELECT rowid FROM section_fts WHERE section_fts MATCH ? LIMIT 20", (match,)).fetchall())
    finally:
        connection.close()
    elapsed = time.perf_counter() - started
    return {"seconds": round(elapsed, 6), "queries": len(rows), "average_results": round(sum(len(values) for values in result_counts) / max(1, len(rows)), 3)}


def _measure_embeddings(inputs: list[str], config: dict, batch_size: int) -> dict:
    from personal_knowledge_base.model_providers import openai_compatible_embedding

    started = time.perf_counter()
    output_count = 0
    for start in range(0, len(inputs), batch_size):
        vectors = openai_compatible_embedding(
            config["base_url"], config["api_key"], config["model"], inputs[start:start + batch_size], timeout=config.get("timeout") or 60
        )
        output_count += len(vectors)
    elapsed = time.perf_counter() - started
    return {
        "seconds": round(elapsed, 6),
        "inputs": len(inputs),
        "vectors": output_count,
        "batch_size": batch_size,
        "average_input_chars": round(sum(map(len, inputs)) / max(1, len(inputs)), 2),
    }


def _measure_rag(spec, sample_size: int, seed: int, model_id: str) -> dict:
    from personal_knowledge_base.open_rag_benchmark import run_open_rag_evaluation

    started = time.perf_counter()
    result = run_open_rag_evaluation(None, spec, sample_size=sample_size, seed=seed, eval_llm_model=model_id)
    elapsed = time.perf_counter() - started
    return {
        "seconds": round(elapsed, 6),
        "questions": result["total_questions"],
        "verified": result["verified"],
        "reasons": result["reasons"],
    }


def _attach_estimate(measurement: dict, total: int, concurrency: int) -> dict:
    result = dict(measurement)
    estimate = estimate_duration(measurement.get("seconds", 0), measurement.get("inputs", measurement.get("queries", measurement.get("questions", 0))), total, concurrency)
    result["estimated_full_run"] = {**estimate, "human_duration": _format_duration(estimate["seconds"])}
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query-sample-size", type=int, default=20, help="FTS query sample size, capped at the 3,045-question corpus size.")
    parser.add_argument("--seed", type=int, default=20260819)
    parser.add_argument("--max-embedding-chars", type=int, default=20000, help="Maximum characters per synthetic embedding input.")
    parser.add_argument("--embedding-sample-units", type=int, default=5, help="Number of bounded embedding inputs to measure.")
    parser.add_argument("--embedding-batch-size", type=int, default=1, help="Embedding request batch size; one is safest while diagnosing provider limits.")
    parser.add_argument("--include-embedding", action="store_true", help="Call the configured embedding provider for the sample.")
    parser.add_argument("--include-rag", action="store_true", help="Call retrieval, answer generation, and Ragas for a small sample.")
    parser.add_argument("--rag-sample-size", type=int, default=1, help="RAGAs sample size when --include-rag is set.")
    parser.add_argument("--embedding-concurrency", type=int, default=1)
    parser.add_argument("--query-concurrency", type=int, default=1)
    parser.add_argument("--rag-concurrency", type=int, default=1)
    parser.add_argument("--eval-llm-model", default="", help="Optional configured evaluation chat model ID.")
    parser.add_argument("--output", type=Path, help="Optional JSON report path. No report is written when omitted.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.max_embedding_chars < 1000 or args.embedding_batch_size < 1:
        raise SystemExit("max embedding chars must be at least 1000 and batch size must be positive")
    _configure_django()

    from personal_knowledge_base.eval_dataset_registry import get_dataset_spec
    from personal_knowledge_base.open_rag_benchmark import MAX_SAMPLE_SIZE, open_dataset_status

    spec = get_dataset_spec("open_rag_benchmark", "arxiv-v1")
    status = open_dataset_status(spec)
    if not status["ready"]:
        raise SystemExit(f"Open RAG dataset is not ready: {status['status']}")
    rows = _section_rows(spec)
    embedding_units = [unit for _doc_id, _section_id, content in rows for unit in _split_for_embedding(content, args.max_embedding_chars)]
    report = {
        "dataset": {
            "id": spec.dataset_id,
            "version": spec.version,
            "documents": spec.expected_documents,
            "queries": spec.expected_queries,
            "representation": "1,000 parsed PDF JSON documents; local public-dataset flow does not parse PDFs",
        },
        "constraints": {
            "api_sample_limit": MAX_SAMPLE_SIZE,
            "full_3045_question_run_supported_by_current_api": True,
            "note": "The unified background evaluation task can process the full corpus; this script measures bounded samples and extrapolates provider work.",
        },
        "corpus": {
            "sections": len(rows),
            "content_characters": sum(len(content) for _doc_id, _section_id, content in rows),
            "largest_section_characters": max(len(content) for _doc_id, _section_id, content in rows),
            "embedding_units_at_max_chars": len(embedding_units),
            "max_embedding_chars": args.max_embedding_chars,
        },
        "measurements": {"fts_index_build": _measure_fts_build(rows)},
    }
    query_measurement = _measure_fts_queries(spec, min(max(1, args.query_sample_size), MAX_SAMPLE_SIZE), args.seed)
    report["measurements"]["fts_retrieval"] = _attach_estimate(query_measurement, spec.expected_queries, args.query_concurrency)

    if args.include_embedding:
        from personal_knowledge_base.model_providers import active_embedding_config

        config = active_embedding_config(None)
        if not config:
            report["measurements"]["embedding"] = {"status": "not_configured"}
        else:
            sample = sample_by_length_quantiles(embedding_units, args.embedding_sample_units)
            try:
                measurement = _measure_embeddings(sample, config, args.embedding_batch_size)
                report["measurements"]["embedding"] = _attach_estimate(measurement, len(embedding_units), args.embedding_concurrency)
                report["measurements"]["embedding"]["model"] = config["model"]
            except Exception as exc:
                report["measurements"]["embedding"] = {"status": "failed", "error_type": type(exc).__name__, "message": str(exc)}
    else:
        report["measurements"]["embedding"] = {"status": "skipped", "hint": "Pass --include-embedding to measure configured provider throughput."}

    if args.include_rag:
        try:
            measurement = _measure_rag(spec, min(max(1, args.rag_sample_size), MAX_SAMPLE_SIZE), args.seed, args.eval_llm_model)
            report["measurements"]["ragas_end_to_end"] = _attach_estimate(measurement, spec.expected_queries, args.rag_concurrency)
        except Exception as exc:
            report["measurements"]["ragas_end_to_end"] = {"status": "failed", "error_type": type(exc).__name__, "message": str(exc)}
    else:
        report["measurements"]["ragas_end_to_end"] = {"status": "skipped", "hint": "Pass --include-rag to measure LLM generation plus Ragas judging."}

    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
