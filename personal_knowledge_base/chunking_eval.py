"""Deterministic, source-span chunking evaluation without production index writes."""

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Mapping

from django.core.files.storage import default_storage

from .chunking import ChunkDraft, ChunkingConfig, split_document
from .chunking.structural import build_atomic_units
from .document_parsing import parse_document
from .document_processing import semantic_chunking_inputs, split_text
from .model_providers import active_embedding_config
from .models import Knowledge
from .search import token_set


DATASET_DIR = Path(__file__).parent / "eval_datasets"
DEFAULT_STRATEGIES = (
    "fixed_window",
    "recursive",
    "auto_parent_child",
    "semantic_parent_child",
)
REQUIRED_STRATEGIES = frozenset(DEFAULT_STRATEGIES)
_UNVERIFIED_STATUSES = frozenset({"template", "unverified", "insufficient"})
_EPSILON = 1e-12


@dataclass(frozen=True, slots=True)
class SourceEvidence:
    """Stable relevance annotation for a source range, independent of chunk IDs."""

    knowledge_id: str
    source_start: int
    source_end: int
    answer_evidence: str = ""


@dataclass(slots=True)
class _LoadedDocument:
    knowledge: Knowledge
    source: str
    parsed: object
    version: str


@dataclass(slots=True)
class _EvaluationChunk:
    knowledge_id: str
    start_at: int
    end_at: int
    search_content: str
    context_content: str
    context_start_at: int
    context_end_at: int
    context_header: str


class _UnverifiedEvaluation(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def overlaps_evidence(candidate: Mapping, evidence: SourceEvidence) -> bool:
    """Whether a returned source range overlaps stable annotated evidence."""
    if str(candidate.get("knowledge_id") or "") != evidence.knowledge_id:
        return False
    start = candidate.get("start_at", candidate.get("source_start"))
    end = candidate.get("end_at", candidate.get("source_end"))
    if isinstance(start, bool) or isinstance(end, bool):
        return False
    if not isinstance(start, int) or not isinstance(end, int) or end <= start:
        return False
    return start < evidence.source_end and end > evidence.source_start


def load_chunking_dataset(name: str = "chunking_v1") -> tuple[list[dict], str]:
    """Load a versioned chunking dataset and its declared verification status."""
    path = DATASET_DIR / f"{name}.json"
    if not path.exists():
        return [], "unverified"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [], "unverified"
    if isinstance(payload, list):
        return payload, ""
    if isinstance(payload, Mapping):
        entries = payload.get("entries")
        return entries if isinstance(entries, list) else [], str(payload.get("dataset_status") or "")
    return [], "unverified"


def _reason(code: str, message: str) -> dict:
    return {"code": str(code), "message": str(message)}


def _unverified_result(*reasons: tuple[str, str], strategies: tuple[str, ...] = DEFAULT_STRATEGIES) -> dict:
    rendered = [_reason(code, message) for code, message in reasons]
    return {
        "dataset_status": "unverified",
        "message": rendered[0]["message"] if rendered else "evaluation dataset is unverified",
        "reasons": rendered,
        "pass": False,
        "strategies": {strategy: _empty_metrics() for strategy in strategies},
        "gates": evaluate_release_gates({}),
    }


def _empty_metrics() -> dict:
    return {
        "mrr_at_10": 0.0,
        "recall_at_20": 0.0,
        "context_precision": 0.0,
        "average_returned_context_characters": 0.0,
        "chunk_count": 0,
        "searchable_chunk_count": 0,
        "index_bytes": 0,
        "processing_duration_ms": 0.0,
        "questions": 0,
        "per_question": [],
    }


def _is_placeholder(value) -> bool:
    return isinstance(value, str) and value.strip().startswith("<") and value.strip().endswith(">")


def _strict_span(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _parse_dataset(dataset: object, declared_status: str = "") -> list[dict]:
    if str(declared_status).lower() in _UNVERIFIED_STATUSES:
        raise _UnverifiedEvaluation("template_dataset", "dataset is explicitly marked unverified")
    if not isinstance(dataset, list) or not dataset:
        raise _UnverifiedEvaluation("insufficient_dataset", "dataset must contain at least one annotated query")

    parsed = []
    for entry_index, entry in enumerate(dataset):
        if not isinstance(entry, Mapping):
            raise _UnverifiedEvaluation("malformed_dataset", f"entry {entry_index} must be an object")
        if str(entry.get("annotation_status") or "").lower() in _UNVERIFIED_STATUSES:
            raise _UnverifiedEvaluation("template_dataset", f"entry {entry_index} is marked unverified")
        query = entry.get("query")
        documents = entry.get("documents")
        evidence_rows = entry.get("evidence")
        if not isinstance(query, str) or not query.strip():
            raise _UnverifiedEvaluation("malformed_dataset", f"entry {entry_index} has no query")
        if not isinstance(documents, list) or not documents:
            raise _UnverifiedEvaluation("insufficient_dataset", f"entry {entry_index} has no versioned documents")
        if not isinstance(evidence_rows, list) or not evidence_rows:
            raise _UnverifiedEvaluation("insufficient_dataset", f"entry {entry_index} has no source-span evidence")

        versions = {}
        for row in documents:
            if not isinstance(row, Mapping):
                raise _UnverifiedEvaluation("malformed_dataset", f"entry {entry_index} has an invalid document")
            knowledge_id = row.get("knowledge_id")
            version = row.get("version")
            if not isinstance(knowledge_id, str) or not knowledge_id.strip() or _is_placeholder(knowledge_id):
                raise _UnverifiedEvaluation("template_dataset", f"entry {entry_index} has a placeholder knowledge_id")
            if not isinstance(version, str) or not version.strip() or _is_placeholder(version):
                raise _UnverifiedEvaluation("template_dataset", f"entry {entry_index} has a placeholder document version")
            previous = versions.setdefault(knowledge_id, version)
            if previous != version:
                raise _UnverifiedEvaluation("malformed_dataset", f"entry {entry_index} repeats a document with different versions")

        evidence = []
        for row in evidence_rows:
            if not isinstance(row, Mapping):
                raise _UnverifiedEvaluation("malformed_dataset", f"entry {entry_index} has invalid evidence")
            knowledge_id = row.get("knowledge_id")
            start = _strict_span(row.get("source_start"))
            end = _strict_span(row.get("source_end"))
            answer_evidence = row.get("answer_evidence", "")
            if not isinstance(knowledge_id, str) or knowledge_id not in versions or _is_placeholder(knowledge_id):
                raise _UnverifiedEvaluation("malformed_dataset", f"entry {entry_index} evidence does not reference a versioned document")
            if start is None or end is None or start < 0 or end <= start:
                raise _UnverifiedEvaluation("malformed_dataset", f"entry {entry_index} has an invalid source span")
            if not isinstance(answer_evidence, str):
                raise _UnverifiedEvaluation("malformed_dataset", f"entry {entry_index} answer_evidence must be text")
            evidence.append(SourceEvidence(knowledge_id, start, end, answer_evidence))
        parsed.append({"query": query.strip(), "versions": versions, "evidence": evidence})
    return parsed


def _load_documents(tenant_id: int, entries: list[dict]) -> dict[str, _LoadedDocument]:
    versions = {}
    for entry in entries:
        for knowledge_id, version in entry["versions"].items():
            prior = versions.setdefault(knowledge_id, version)
            if prior != version:
                raise _UnverifiedEvaluation("version_mismatch", "one document has conflicting dataset versions")

    documents = Knowledge.objects.filter(tenant_id=tenant_id, id__in=versions).select_related("tenant")
    by_id = {knowledge.id: knowledge for knowledge in documents}
    missing = sorted(set(versions) - set(by_id))
    if missing:
        raise _UnverifiedEvaluation("unavailable_document", "one or more annotated documents are unavailable to this tenant")

    loaded = {}
    for knowledge_id, expected_version in versions.items():
        knowledge = by_id[knowledge_id]
        if knowledge.type != "file" or not knowledge.file_path:
            raise _UnverifiedEvaluation("unavailable_document", f"document {knowledge_id} has no evaluable source file")
        try:
            with default_storage.open(knowledge.file_path, "rb") as handle:
                data = handle.read()
            actual_version = knowledge.file_hash or hashlib.sha256(data).hexdigest()
            if expected_version != actual_version:
                raise _UnverifiedEvaluation("version_mismatch", f"document {knowledge_id} no longer matches its dataset version")
            process_config = (knowledge.metadata or {}).get("process_config") or {}
            parsed = parse_document(
                knowledge.file_name or knowledge.title,
                data,
                engine=str(process_config.get("parser_engine") or "builtin"),
            )
            source, units = build_atomic_units(parsed)
        except _UnverifiedEvaluation:
            raise
        except Exception as exc:
            raise _UnverifiedEvaluation("unavailable_document", f"document {knowledge_id} could not be parsed: {exc}") from exc
        if not source or not units:
            raise _UnverifiedEvaluation("insufficient_document", f"document {knowledge_id} has no evaluable text")
        loaded[knowledge_id] = _LoadedDocument(knowledge, source, parsed, actual_version)

    for entry in entries:
        for evidence in entry["evidence"]:
            source = loaded[evidence.knowledge_id].source
            if evidence.source_end > len(source):
                raise _UnverifiedEvaluation("malformed_dataset", "source-span evidence exceeds the versioned document length")
    return loaded


def _fixed_window_chunks(document: _LoadedDocument) -> tuple[list[ChunkDraft], list[ChunkDraft]]:
    config = {"chunk_size": 512, "chunk_overlap": 80}
    children = [
        ChunkDraft(content=content, context_header=document.knowledge.title, start_at=start, end_at=end)
        for start, end, content in split_text(document.source, config)
    ]
    return [], children


def _strategy_chunks(strategy: str, document: _LoadedDocument) -> tuple[list[ChunkDraft], list[ChunkDraft]]:
    if strategy == "fixed_window":
        return _fixed_window_chunks(document)
    if strategy == "recursive":
        config = ChunkingConfig(strategy="recursive", enable_parent_child=False, chunk_size=512, chunk_overlap=80)
        result = split_document(document.parsed, config, title=document.knowledge.title)
    elif strategy == "auto_parent_child":
        config = ChunkingConfig(strategy="auto", enable_parent_child=True)
        result = split_document(document.parsed, config, title=document.knowledge.title)
    elif strategy == "semantic_parent_child":
        config = ChunkingConfig(strategy="semantic", enable_parent_child=True)
        if not active_embedding_config(document.knowledge.tenant, document.knowledge.embedding_model_id):
            raise _UnverifiedEvaluation("model_unavailable", "semantic parent-child evaluation requires an available embedding model")
        result = split_document(
            document.parsed,
            config,
            title=document.knowledge.title,
            **semantic_chunking_inputs(document.knowledge, config),
        )
        if result.diagnostics.selected_strategy != "semantic":
            reason = (result.diagnostics.fallback_chain or [{"reason": "semantic output unavailable"}])[-1]["reason"]
            raise _UnverifiedEvaluation("model_unavailable", f"semantic parent-child evaluation is unavailable: {reason}")
    else:
        raise _UnverifiedEvaluation("malformed_strategy", f"unsupported strategy: {strategy}")
    return result.parents, result.children


def _evaluation_chunks(document: _LoadedDocument, parents: list[ChunkDraft], children: list[ChunkDraft]) -> list[_EvaluationChunk]:
    result = []
    for child in children:
        parent = parents[child.context_parent_index] if child.context_parent_index is not None else child
        result.append(
            _EvaluationChunk(
                knowledge_id=document.knowledge.id,
                start_at=child.start_at,
                end_at=child.end_at,
                search_content=child.content,
                context_content=parent.content,
                context_start_at=parent.start_at,
                context_end_at=parent.end_at,
                context_header=parent.context_header,
            )
        )
    return result


def _rank(query: str, chunks: list[_EvaluationChunk]) -> list[_EvaluationChunk]:
    terms = token_set(query)

    def score(chunk: _EvaluationChunk) -> int:
        content = chunk.search_content.lower()
        return sum(content.count(term) * max(1, len(term)) for term in terms)

    return sorted(
        chunks,
        key=lambda chunk: (-score(chunk), chunk.knowledge_id, chunk.start_at, chunk.end_at),
    )


def _matches(candidate: Mapping, evidence: list[SourceEvidence]) -> list[int]:
    return [index for index, item in enumerate(evidence) if overlaps_evidence(candidate, item)]


def _metrics_for_query(ranked: list[_EvaluationChunk], evidence: list[SourceEvidence]) -> dict:
    returned = ranked[:20]
    retrieved_evidence = set()
    mrr = 0.0
    relevant_contexts = 0
    for rank, chunk in enumerate(returned, start=1):
        matches = _matches(
            {"knowledge_id": chunk.knowledge_id, "start_at": chunk.start_at, "end_at": chunk.end_at},
            evidence,
        )
        retrieved_evidence.update(matches)
        if matches and rank <= 10 and not mrr:
            mrr = 1.0 / rank
        if _matches(
            {"knowledge_id": chunk.knowledge_id, "start_at": chunk.context_start_at, "end_at": chunk.context_end_at},
            evidence,
        ):
            relevant_contexts += 1
    return {
        "mrr_at_10": mrr,
        "recall_at_20": len(retrieved_evidence) / len(evidence),
        "context_precision": relevant_contexts / len(returned) if returned else 0.0,
        "returned_context_characters": sum(len(chunk.context_content) for chunk in returned),
        "returned": len(returned),
    }


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _finite_metric(metrics: Mapping, key: str) -> float | None:
    value = metrics.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _relative_improvement(candidate: float | None, baseline: float | None) -> float | None:
    if candidate is None or baseline is None or baseline <= 0:
        return None
    return (candidate - baseline) / baseline * 100.0


def evaluate_release_gates(strategy_metrics: Mapping[str, Mapping]) -> dict:
    """Apply the documented Auto and Semantic promotion rules with safe zero handling."""
    baseline = strategy_metrics.get("fixed_window", {})
    auto = strategy_metrics.get("auto_parent_child", {})
    semantic = strategy_metrics.get("semantic_parent_child", {})
    baseline_mrr = _finite_metric(baseline, "mrr_at_10")
    auto_mrr = _finite_metric(auto, "mrr_at_10")
    semantic_mrr = _finite_metric(semantic, "mrr_at_10")
    auto_delta = _relative_improvement(auto_mrr, baseline_mrr)
    semantic_delta = _relative_improvement(semantic_mrr, auto_mrr)
    baseline_recall = _finite_metric(baseline, "recall_at_20")
    auto_recall = _finite_metric(auto, "recall_at_20")
    semantic_recall = _finite_metric(semantic, "recall_at_20")
    baseline_precision = _finite_metric(baseline, "context_precision")
    auto_precision = _finite_metric(auto, "context_precision")
    auto_duration = _finite_metric(auto, "processing_duration_ms")
    semantic_duration = _finite_metric(semantic, "processing_duration_ms")
    auto_index_bytes = _finite_metric(auto, "index_bytes")
    semantic_index_bytes = _finite_metric(semantic, "index_bytes")

    auto_pass = bool(
        auto_delta is not None
        and auto_delta >= 5.0 - _EPSILON
        and auto_recall is not None
        and baseline_recall is not None
        and auto_recall >= baseline_recall
        and auto_precision is not None
        and baseline_precision is not None
        and auto_precision >= baseline_precision
    )
    semantic_eligible = bool(
        semantic_delta is not None
        and semantic_delta >= 3.0 - _EPSILON
        and semantic_recall is not None
        and auto_recall is not None
        and semantic_recall >= auto_recall
        and semantic_duration is not None
        and auto_duration is not None
        and semantic_duration <= auto_duration * 2
        and semantic_index_bytes is not None
        and auto_index_bytes is not None
        and semantic_index_bytes <= auto_index_bytes * 2
    )
    return {
        "auto_parent_child": {
            "mrr_relative_improvement_pct": auto_delta,
            "pass": auto_pass,
        },
        "semantic_parent_child": {
            "mrr_relative_improvement_over_auto_pct": semantic_delta,
            "promotion_eligible": semantic_eligible,
        },
    }


def _evaluate_strategy(strategy: str, documents: Mapping[str, _LoadedDocument], entries: list[dict]) -> dict:
    started = perf_counter()
    indexed: dict[str, list[_EvaluationChunk]] = {}
    all_chunks: list[_EvaluationChunk] = []
    chunk_count = 0
    for knowledge_id, document in documents.items():
        parents, children = _strategy_chunks(strategy, document)
        candidates = _evaluation_chunks(document, parents, children)
        if not candidates:
            raise _UnverifiedEvaluation("insufficient_document", f"document {knowledge_id} produced no searchable chunks")
        indexed[knowledge_id] = candidates
        all_chunks.extend(candidates)
        chunk_count += len(parents) + len(children)

    processing_duration_ms = (perf_counter() - started) * 1000.0
    index_bytes = len(
        json.dumps(
            [
                {
                    "knowledge_id": chunk.knowledge_id,
                    "start_at": chunk.start_at,
                    "end_at": chunk.end_at,
                    "content": chunk.search_content,
                    "context_header": chunk.context_header,
                }
                for chunk in all_chunks
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    per_question = []
    for entry in entries:
        candidates = [chunk for knowledge_id in entry["versions"] for chunk in indexed[knowledge_id]]
        query_metrics = _metrics_for_query(_rank(entry["query"], candidates), entry["evidence"])
        per_question.append({"query": entry["query"], **query_metrics})
    return {
        "mrr_at_10": _mean([item["mrr_at_10"] for item in per_question]),
        "recall_at_20": _mean([item["recall_at_20"] for item in per_question]),
        "context_precision": _mean([item["context_precision"] for item in per_question]),
        "average_returned_context_characters": _mean([item["returned_context_characters"] for item in per_question]),
        "chunk_count": chunk_count,
        "searchable_chunk_count": len(all_chunks),
        "index_bytes": index_bytes,
        "processing_duration_ms": processing_duration_ms,
        "questions": len(per_question),
        "per_question": per_question,
    }


def run_chunking_comparison(
    tenant_id: int,
    dataset: list[dict] | None = None,
    strategies: list[str] | tuple[str, ...] | None = None,
) -> dict:
    """Compare isolated chunking strategies against stable, tenant-scoped source evidence."""
    declared_status = ""
    if dataset is None:
        dataset, declared_status = load_chunking_dataset()
    selected = tuple(str(strategy) for strategy in (DEFAULT_STRATEGIES if strategies is None else strategies))
    if not selected:
        return _unverified_result(("insufficient_strategies", "comparison requires all four release-gate strategies"), strategies=selected)
    if len(set(selected)) != len(selected) or any(strategy not in REQUIRED_STRATEGIES for strategy in selected):
        return _unverified_result(("malformed_strategy", "strategies must be unique supported chunking strategies"), strategies=selected or DEFAULT_STRATEGIES)
    if set(selected) != REQUIRED_STRATEGIES:
        return _unverified_result(("insufficient_strategies", "comparison requires all four release-gate strategies"), strategies=selected)
    try:
        entries = _parse_dataset(dataset, declared_status)
        documents = _load_documents(tenant_id, entries)
        metrics = {strategy: _evaluate_strategy(strategy, documents, entries) for strategy in selected}
    except _UnverifiedEvaluation as exc:
        return _unverified_result((exc.code, exc.message), strategies=selected)
    gates = evaluate_release_gates(metrics)
    return {
        "dataset_status": "verified",
        "pass": gates["auto_parent_child"]["pass"],
        "strategies": metrics,
        "gates": gates,
        "documents": [
            {"knowledge_id": knowledge_id, "version": document.version}
            for knowledge_id, document in sorted(documents.items())
        ],
    }
