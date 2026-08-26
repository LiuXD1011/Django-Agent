"""Deterministic, source-span chunking evaluation without production index writes."""

import hashlib
import json
import logging
import math
from dataclasses import dataclass, replace as dataclasses_replace
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
# 生产策略以生产形态参与评测：父子块开启、尺寸继承自知识库 chunking_config
# （未提供时用 ChunkingConfig 生产默认值）。fixed_window 是门禁基线，非生产策略。
PRODUCTION_STRATEGY_ALIASES = {
    "recursive": "recursive",
    "auto_parent_child": "auto",
    "semantic_parent_child": "semantic",
    "heading": "heading",
    "layout": "layout",
    "record": "record",
}
ALLOWED_STRATEGIES = frozenset(DEFAULT_STRATEGIES) | frozenset(PRODUCTION_STRATEGY_ALIASES)
_UNVERIFIED_STATUSES = frozenset({"template", "unverified", "insufficient"})
_EPSILON = 1e-12

logger = logging.getLogger(__name__)


def _embedding_model_id(config: Mapping | None) -> str:
    if not config or config.get("source") == "env":
        return ""
    return str(config.get("model_id") or "")


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


@dataclass(slots=True)
class _LexicalIndex:
    """Deterministic inverted index used directly for ranking and byte accounting."""

    representation: dict
    chunks: tuple[_EvaluationChunk, ...]
    serialized: bytes

    @classmethod
    def build(cls, chunks: list[_EvaluationChunk]):
        ordered = tuple(
            sorted(
                chunks,
                key=lambda chunk: (
                    str(chunk.knowledge_id),
                    chunk.start_at,
                    chunk.end_at,
                    chunk.search_content,
                    chunk.context_start_at,
                    chunk.context_end_at,
                ),
            )
        )
        documents = []
        postings: dict[str, list[list[int]]] = {}
        for document_id, chunk in enumerate(ordered):
            documents.append(
                {
                    "document_id": document_id,
                    "knowledge_id": str(chunk.knowledge_id),
                    "start_at": chunk.start_at,
                    "end_at": chunk.end_at,
                }
            )
            normalized = chunk.search_content.lower()
            for term in sorted(token_set(normalized)):
                frequency = normalized.count(term)
                if frequency > 0:
                    postings.setdefault(term, []).append([document_id, frequency])
        representation = {
            "version": 1,
            "documents": documents,
            "postings": {term: postings[term] for term in sorted(postings)},
        }
        serialized = json.dumps(
            representation,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return cls(representation=representation, chunks=ordered, serialized=serialized)

    @property
    def byte_size(self) -> int:
        return len(self.serialized)

    def query(self, query: str, knowledge_ids) -> list[_EvaluationChunk]:
        allowed = {str(knowledge_id) for knowledge_id in knowledge_ids}
        scores: dict[int, int] = {}
        postings = self.representation["postings"]
        for term in sorted(token_set(query)):
            for document_id, frequency in postings.get(term, []):
                document = self.representation["documents"][document_id]
                if document["knowledge_id"] in allowed:
                    scores[document_id] = scores.get(document_id, 0) + frequency * max(1, len(term))
        ranked_ids = sorted(
            scores,
            key=lambda document_id: (
                -scores[document_id],
                self.representation["documents"][document_id]["knowledge_id"],
                self.representation["documents"][document_id]["start_at"],
                self.representation["documents"][document_id]["end_at"],
                document_id,
            ),
        )
        return [self.chunks[document_id] for document_id in ranked_ids]


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
        "verification_status": "unverified",
        "verified": False,
        "message": rendered[0]["message"] if rendered else "evaluation dataset is unverified",
        "reasons": rendered,
        "pass": False,
        "strategies": {strategy: _empty_metrics() for strategy in strategies},
        "gates": evaluate_release_gates({}),
    }


def _empty_metrics() -> dict:
    return {
        "mrr_at_10": None,
        "recall_at_20": None,
        "context_precision": None,
        "average_returned_context_characters": None,
        "chunk_count": None,
        "searchable_chunk_count": None,
        "index_bytes": None,
        "processing_duration_ms": None,
        "questions": 0,
        "failed_questions": 0,
        "valid_coverage": 0.0,
        "per_question": [],
        "verified": False,
        "verification_status": "unverified",
        "requested_pipeline": {},
        "effective_pipeline": {},
        "reasons": [],
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
            version = row.get("file_hash") or row.get("version")
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
            actual_version = hashlib.sha256(data).hexdigest()
            stored_version = (knowledge.file_hash or "").strip().lower()
            if expected_version != actual_version or stored_version != actual_version:
                raise _UnverifiedEvaluation("version_mismatch", "one or more documents no longer match the dataset version")
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
            logger.exception("chunking evaluation source parsing failed for document %s", knowledge_id)
            raise _UnverifiedEvaluation(
                "unavailable_document",
                "one or more annotated documents could not be parsed",
            ) from exc
        if not source or not units:
            raise _UnverifiedEvaluation("insufficient_document", f"document {knowledge_id} has no evaluable text")
        loaded[knowledge_id] = _LoadedDocument(knowledge, source, parsed, actual_version)

    for entry in entries:
        for evidence in entry["evidence"]:
            source = loaded[evidence.knowledge_id].source
            if evidence.source_end > len(source):
                raise _UnverifiedEvaluation("malformed_dataset", "source-span evidence exceeds the versioned document length")
    return loaded


def _fixed_window_chunks(document: _LoadedDocument, base_config) -> tuple[list[ChunkDraft], list[ChunkDraft]]:
    config = {"chunk_size": base_config.chunk_size, "chunk_overlap": base_config.chunk_overlap}
    children = [
        ChunkDraft(content=content, context_header=document.knowledge.title, start_at=start, end_at=end)
        for start, end, content in split_text(document.source, config)
    ]
    return [], children


def _strategy_chunks(
    strategy: str,
    document: _LoadedDocument,
    *,
    base_config=None,
    semantic_cache=None,
) -> tuple[list[ChunkDraft], list[ChunkDraft]]:
    base = base_config or ChunkingConfig()
    if strategy == "fixed_window":
        return _fixed_window_chunks(document, base)
    production_strategy = PRODUCTION_STRATEGY_ALIASES.get(strategy)
    if production_strategy is None:
        raise _UnverifiedEvaluation("malformed_strategy", f"unsupported strategy: {strategy}")
    config = dataclasses_replace(base, strategy=production_strategy, enable_parent_child=True)
    if strategy == "semantic_parent_child":
        try:
            model_config = active_embedding_config(
                document.knowledge.tenant,
                document.knowledge.embedding_model_id,
            )
        except Exception as exc:
            logger.exception("chunking evaluation semantic model resolution failed")
            raise _UnverifiedEvaluation(
                "model_unavailable",
                "semantic parent-child evaluation requires an available embedding model",
            ) from exc
        if not model_config:
            raise _UnverifiedEvaluation("model_unavailable", "semantic parent-child evaluation requires an available embedding model")
        semantic_options = semantic_chunking_inputs(document.knowledge, config)
        semantic_embed = semantic_options.get("semantic_embed")
        if callable(semantic_embed):
            def evaluation_embed(inputs):
                try:
                    return semantic_embed(inputs)
                except Exception:
                    logger.exception("chunking evaluation semantic embedding provider failed")
                    raise

            semantic_options = {**semantic_options, "semantic_embed": evaluation_embed}
        result = split_document(
            document.parsed,
            config,
            title=document.knowledge.title,
            semantic_cache=semantic_cache,
            **semantic_options,
        )
        if result.diagnostics.selected_strategy != "semantic":
            reason = (result.diagnostics.fallback_chain or [{"reason": "semantic output unavailable"}])[-1]["reason"]
            logger.warning("chunking evaluation semantic strategy unavailable: %s", reason)
            raise _UnverifiedEvaluation(
                "model_unavailable",
                "semantic parent-child evaluation is unavailable",
            )
    else:
        result = split_document(document.parsed, config, title=document.knowledge.title)
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


def _deduplicate_contexts(ranked: list[_EvaluationChunk]) -> list[_EvaluationChunk]:
    deduplicated = []
    seen = set()
    for chunk in ranked:
        context_key = (
            str(chunk.knowledge_id),
            chunk.context_start_at,
            chunk.context_end_at,
        )
        if context_key in seen:
            continue
        seen.add(context_key)
        deduplicated.append(chunk)
    return deduplicated


def _matches(candidate: Mapping, evidence: list[SourceEvidence]) -> list[int]:
    return [index for index, item in enumerate(evidence) if overlaps_evidence(candidate, item)]


def _metrics_for_query(ranked: list[_EvaluationChunk], evidence: list[SourceEvidence]) -> dict:
    returned = _deduplicate_contexts(ranked)[:20]
    retrieved_evidence = set()
    mrr = 0.0
    relevant_contexts = 0
    for rank, chunk in enumerate(returned, start=1):
        matches = _matches(
            {
                "knowledge_id": chunk.knowledge_id,
                "start_at": chunk.context_start_at,
                "end_at": chunk.context_end_at,
            },
            evidence,
        )
        retrieved_evidence.update(matches)
        if matches and rank <= 10 and not mrr:
            mrr = 1.0 / rank
        if matches:
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


def _finite_metric(
    metrics: Mapping,
    key: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    value = metrics.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    normalized = float(value)
    if minimum is not None and normalized < minimum:
        return None
    if maximum is not None and normalized > maximum:
        return None
    return normalized


def _relative_improvement(candidate: float | None, baseline: float | None) -> float | None:
    if candidate is None or baseline is None or baseline <= 0:
        return None
    return (candidate - baseline) / baseline * 100.0


def _guarded_ratio(candidate: float | None, baseline: float | None) -> float | None:
    if candidate is None or candidate < 0 or baseline is None or baseline <= 0:
        return None
    return candidate / baseline


def evaluate_release_gates(strategy_metrics: Mapping[str, Mapping]) -> dict:
    """Apply the documented Auto and Semantic promotion rules with safe zero handling."""
    baseline = strategy_metrics.get("fixed_window", {})
    auto = strategy_metrics.get("auto_parent_child", {})
    semantic = strategy_metrics.get("semantic_parent_child", {})
    baseline_mrr = _finite_metric(baseline, "mrr_at_10", minimum=0.0, maximum=1.0)
    auto_mrr = _finite_metric(auto, "mrr_at_10", minimum=0.0, maximum=1.0)
    semantic_mrr = _finite_metric(semantic, "mrr_at_10", minimum=0.0, maximum=1.0)
    auto_delta = _relative_improvement(auto_mrr, baseline_mrr)
    semantic_delta = _relative_improvement(semantic_mrr, auto_mrr)
    baseline_recall = _finite_metric(baseline, "recall_at_20", minimum=0.0, maximum=1.0)
    auto_recall = _finite_metric(auto, "recall_at_20", minimum=0.0, maximum=1.0)
    semantic_recall = _finite_metric(semantic, "recall_at_20", minimum=0.0, maximum=1.0)
    baseline_precision = _finite_metric(baseline, "context_precision", minimum=0.0, maximum=1.0)
    auto_precision = _finite_metric(auto, "context_precision", minimum=0.0, maximum=1.0)
    semantic_precision = _finite_metric(semantic, "context_precision", minimum=0.0, maximum=1.0)
    auto_duration = _finite_metric(auto, "processing_duration_ms", minimum=0.0)
    semantic_duration = _finite_metric(semantic, "processing_duration_ms", minimum=0.0)
    auto_index_bytes = _finite_metric(auto, "index_bytes", minimum=0.0)
    semantic_index_bytes = _finite_metric(semantic, "index_bytes", minimum=0.0)
    duration_ratio = _guarded_ratio(semantic_duration, auto_duration)
    index_ratio = _guarded_ratio(semantic_index_bytes, auto_index_bytes)

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
        and semantic_precision is not None
        and auto_precision is not None
        and duration_ratio is not None
        and duration_ratio <= 2.0
        and index_ratio is not None
        and index_ratio <= 2.0
    )
    return {
        "auto_parent_child": {
            "mrr_relative_improvement_pct": auto_delta,
            "pass": auto_pass,
        },
        "semantic_parent_child": {
            "mrr_relative_improvement_over_auto_pct": semantic_delta,
            "processing_duration_ratio_over_auto": duration_ratio,
            "index_bytes_ratio_over_auto": index_ratio,
            "promotion_eligible": semantic_eligible,
        },
    }


def _evaluate_strategy(
    strategy: str,
    documents: Mapping[str, _LoadedDocument],
    entries: list[dict],
    *,
    base_config=None,
    semantic_cache=None,
    tenant=None,
    retrieval_strategy: str = "hybrid",
    rerank_enabled: bool = True,
    cancel_callback=None,
    progress_callback=None,
) -> dict:
    def report(ratio: float):
        if progress_callback:
            progress_callback(max(0.0, min(float(ratio), 1.0)), 1.0)

    started = perf_counter()
    all_chunks: list[_EvaluationChunk] = []
    chunk_count = 0
    ordered_documents = sorted(documents.items())
    for document_index, (knowledge_id, document) in enumerate(ordered_documents, start=1):
        if cancel_callback:
            cancel_callback()
        parents, children = _strategy_chunks(
            strategy,
            document,
            base_config=base_config,
            semantic_cache=semantic_cache,
        )
        candidates = _evaluation_chunks(document, parents, children)
        if not candidates:
            raise _UnverifiedEvaluation("insufficient_document", f"document {knowledge_id} produced no searchable chunks")
        all_chunks.extend(candidates)
        chunk_count += len(parents) + len(children)
        report(0.5 * document_index / max(len(ordered_documents), 1))

    index = _LexicalIndex.build(all_chunks)
    chunk_positions = {id(chunk): position for position, chunk in enumerate(index.chunks)}
    requested_retrieval = str(retrieval_strategy or "hybrid").lower()
    requested_rerank_enabled = bool(rerank_enabled)
    if requested_retrieval not in {"keyword", "vector", "hybrid"}:
        raise _UnverifiedEvaluation("malformed_strategy", f"unsupported retrieval strategy: {requested_retrieval}")
    # 与生产一致的降级语义：向路径不可用时 hybrid 退化为关键词检索并记录原因，
    # 而不是把整个评测判为 unverified
    degradations: list[dict] = []
    normalized_retrieval = requested_retrieval
    embedding_config = None
    rerank_model = ""
    if normalized_retrieval in {"vector", "hybrid"}:
        from .model_providers import active_embedding_config

        embedding_config = active_embedding_config(tenant)
        if not embedding_config:
            if normalized_retrieval == "vector":
                raise _UnverifiedEvaluation("model_unavailable", "vector retrieval requires an embedding model")
            degradations.append({"stage": "vector", "reason": "embedding_not_configured"})
            normalized_retrieval = "keyword"
    if rerank_enabled:
        from .model_providers import active_rerank_config

        rerank_config = active_rerank_config(tenant)
        if not rerank_config:
            degradations.append({"stage": "rerank", "reason": "rerank model is not configured"})
            rerank_enabled = False
        else:
            rerank_model = str(rerank_config.get("model") or "")
    processing_duration_ms = (perf_counter() - started) * 1000.0
    per_question = []
    vector_index = None
    query_vectors = {}
    if normalized_retrieval in {"vector", "hybrid"}:
        from .model_providers import embedding

        model_id = _embedding_model_id(embedding_config)
        batch_size = max(1, min(int(embedding_config.get("batch_size") or 32), 64))
        for offset in range(0, len(index.chunks), batch_size):
            if cancel_callback:
                cancel_callback()
            vector_index = vector_index or []
            vector_index.extend(embedding(
                tenant,
                [chunk.search_content for chunk in index.chunks[offset:offset + batch_size]],
                model_id,
            ))
            report(0.5 + 0.2 * min(offset + batch_size, len(index.chunks)) / max(len(index.chunks), 1))
        for offset in range(0, len(entries), batch_size):
            if cancel_callback:
                cancel_callback()
            batch = entries[offset:offset + batch_size]
            vectors = embedding(tenant, [entry["query"] for entry in batch], model_id)
            query_vectors.update({id(entry): vector for entry, vector in zip(batch, vectors, strict=True)})
            report(0.7 + 0.1 * min(offset + batch_size, len(entries)) / max(len(entries), 1))

    for question_index, entry in enumerate(entries, start=1):
        if cancel_callback:
            cancel_callback()
        ranked = index.query(entry["query"], entry["versions"])
        if normalized_retrieval in {"vector", "hybrid"}:
            query_vector = query_vectors[id(entry)]
            vector_distances = {
                chunk_index: sum((float(left) - float(right)) ** 2 for left, right in zip(query_vector, vector, strict=False))
                for chunk_index, vector in enumerate(vector_index or [])
            }
            vector_ids = sorted(vector_distances, key=lambda item: (vector_distances[item], item))
            allowed = {str(value) for value in entry["versions"]}
            if normalized_retrieval == "vector":
                ranked = [index.chunks[item] for item in vector_ids if str(index.chunks[item].knowledge_id) in allowed]
            else:
                from .search import shared_rank_candidates

                lexical_candidates = [
                    {"id": str(chunk_positions[id(item)]), "_chunk": item}
                    for item in ranked
                ]
                vector_candidates = [
                    {"id": str(item), "_chunk": index.chunks[item], "score": -vector_distances[item]}
                    for item in vector_ids
                    if str(index.chunks[item].knowledge_id) in allowed
                ]
                fused = shared_rank_candidates(lexical_candidates, vector_candidates)
                ranked = [item["_chunk"] for item in fused if item.get("_chunk")]
        if rerank_enabled and ranked:
            from .model_providers import rerank

            # 生产语义：rerank 不做 top_k 截断，输入量与生产一致（2×top_k=40），
            # 返回窗口由 _metrics_for_query 的 top-20 统一控制
            try:
                reranked = rerank(
                    entry["query"],
                    [{"id": str(position), "content": chunk.search_content, "_chunk": chunk} for position, chunk in enumerate(ranked[:40])],
                    top_k=None,
                    tenant=tenant,
                )
                ranked = [item["_chunk"] for item in reranked if item.get("_chunk")]
            except Exception as exc:
                # Keep deterministic retrieval metrics, but never call this
                # verified: the requested rerank did not take effect.
                degradations.append({"stage": "rerank", "reason": f"rerank_failed:{type(exc).__name__}"})
                rerank_enabled = False
        query_metrics = _metrics_for_query(ranked, entry["evidence"])
        per_question.append({"query": entry["query"], **query_metrics})
        report(0.8 + 0.2 * question_index / max(len(entries), 1))
    verification_status = "verified" if not degradations and per_question else ("degraded" if per_question else "unverified")
    return {
        "mrr_at_10": _mean([item["mrr_at_10"] for item in per_question]),
        "recall_at_20": _mean([item["recall_at_20"] for item in per_question]),
        "context_precision": _mean([item["context_precision"] for item in per_question]),
        "average_returned_context_characters": _mean([item["returned_context_characters"] for item in per_question]),
        "chunk_count": chunk_count,
        "searchable_chunk_count": len(index.chunks),
        "index_bytes": index.byte_size,
        "processing_duration_ms": processing_duration_ms,
        "questions": len(per_question),
        "failed_questions": 0,
        "valid_coverage": 1.0 if per_question else 0.0,
        "per_question": per_question,
        "retrieval_strategy": requested_retrieval,
        "effective_retrieval_strategy": normalized_retrieval,
        "rerank_enabled": bool(rerank_enabled),
        "requested_pipeline": {"retrieval_strategy": requested_retrieval, "rerank_enabled": requested_rerank_enabled},
        "effective_pipeline": {
            "retrieval_strategy": normalized_retrieval,
            "embedding_model": str((embedding_config or {}).get("model") or ""),
            "rerank": {
                "requested": requested_rerank_enabled,
                "effective": bool(rerank_enabled),
                "status": "enabled" if rerank_enabled else ("disabled" if not requested_rerank_enabled else "degraded"),
                "model": rerank_model,
            },
            "index_scope": "tenant_isolated",
        },
        "verification_status": verification_status,
        "verified": verification_status == "verified",
        "degradations": degradations,
        "reasons": degradations,
    }


def retrieve_chunking_strategy(
    tenant,
    dataset: list[dict],
    strategy: str,
    *,
    knowledge_base_id: str = "",
    retrieval_strategy: str = "hybrid",
    rerank_enabled: bool = True,
    cancel_callback=None,
) -> dict[str, dict]:
    """Retrieve tenant evaluation questions from one isolated strategy index.

    This is the query-producing counterpart to ``run_chunking_comparison``.
    It intentionally never reads production FTS/vector rows, so Answer/Ragas
    for the primary strategy receive the same strategy-specific chunks that
    produced its Retrieval metrics.
    """
    parsed_entries = _parse_dataset(dataset)
    documents = _load_documents(tenant.id, parsed_entries)
    base_config = _tenant_base_chunking_config(tenant, knowledge_base_id)
    all_chunks = []
    for document_id, document in sorted(documents.items()):
        if cancel_callback:
            cancel_callback()
        parents, children = _strategy_chunks(strategy, document, base_config=base_config, semantic_cache={})
        all_chunks.extend(_evaluation_chunks(document, parents, children))
    index = _LexicalIndex.build(all_chunks)
    chunk_positions = {id(chunk): position for position, chunk in enumerate(index.chunks)}
    requested_retrieval = str(retrieval_strategy or "hybrid").lower()
    if requested_retrieval not in {"keyword", "vector", "hybrid"}:
        raise _UnverifiedEvaluation("malformed_strategy", f"unsupported retrieval strategy: {requested_retrieval}")
    requested_rerank = bool(rerank_enabled)
    effective_retrieval = requested_retrieval
    degradations = []
    vector_index = []
    if requested_retrieval in {"vector", "hybrid"}:
        from .model_providers import active_embedding_config, embedding

        embedding_config = active_embedding_config(tenant)
        if not embedding_config:
            if requested_retrieval == "vector":
                raise _UnverifiedEvaluation("model_unavailable", "vector retrieval requires an embedding model")
            degradations.append({"stage": "vector", "reason": "embedding_model_required"})
            effective_retrieval = "keyword"
        else:
            embedding_model_id = _embedding_model_id(embedding_config)
            try:
                vector_index = embedding(tenant, [chunk.search_content for chunk in index.chunks], embedding_model_id)
            except Exception as exc:
                if requested_retrieval == "vector":
                    raise _UnverifiedEvaluation("model_unavailable", "vector retrieval failed") from exc
                degradations.append({"stage": "vector", "reason": f"embedding_failed:{type(exc).__name__}"})
                effective_retrieval = "keyword"
                vector_index = []
    if requested_rerank:
        from .model_providers import active_rerank_config

        if not active_rerank_config(tenant):
            degradations.append({"stage": "rerank", "reason": "rerank_model_required"})
            rerank_enabled = False
    output = {}
    for position, raw_entry in enumerate(dataset):
        if cancel_callback:
            cancel_callback()
        entry = parsed_entries[position]
        ranked = index.query(entry["query"], entry["versions"])
        if effective_retrieval in {"vector", "hybrid"} and vector_index:
            from .model_providers import embedding
            from .search import shared_rank_candidates

            try:
                query_vector = embedding(tenant, [entry["query"]], _embedding_model_id(embedding_config))[0]
            except Exception as exc:
                if requested_retrieval == "vector":
                    raise _UnverifiedEvaluation("model_unavailable", "vector query embedding failed") from exc
                degradations.append({"stage": "vector", "reason": f"query_embedding_failed:{type(exc).__name__}"})
                effective_retrieval = "keyword"
                query_vector = None
            if query_vector is None:
                vector_distances = {}
            else:
                vector_distances = {
                    chunk_index: sum(
                        (float(left) - float(right)) ** 2
                        for left, right in zip(query_vector, vector, strict=False)
                    )
                    for chunk_index, vector in enumerate(vector_index)
                }
            vector_ids = sorted(vector_distances, key=lambda item: (vector_distances[item], item))
            allowed = {str(value) for value in entry["versions"]}
            lexical_candidates = [{"id": str(chunk_positions[id(item)]), "_chunk": item} for item in ranked]
            vector_candidates = [{"id": str(item), "_chunk": index.chunks[item], "score": -vector_distances[item]} for item in vector_ids if str(index.chunks[item].knowledge_id) in allowed]
            fused = shared_rank_candidates(lexical_candidates, vector_candidates)
            ranked = [item["_chunk"] for item in fused if item.get("_chunk")]
        if rerank_enabled and ranked:
            from .model_providers import rerank

            try:
                reranked = rerank(
                    entry["query"],
                    [{"id": str(index.chunks.index(chunk)), "content": chunk.search_content, "_chunk": chunk} for chunk in ranked[:40]],
                    top_k=None,
                    tenant=tenant,
                )
                ranked = [item["_chunk"] for item in reranked if item.get("_chunk")]
            except Exception as exc:
                degradations.append({"stage": "rerank", "reason": f"rerank_failed:{type(exc).__name__}"})
                rerank_enabled = False
        metric = _metrics_for_query(ranked, entry["evidence"])
        rows = [
            {
                "chunk_id": f"evaluation:{chunk.knowledge_id}:{chunk.context_start_at}:{chunk.context_end_at}",
                "knowledge_id": str(chunk.knowledge_id),
                "content": chunk.context_content,
                "start_at": chunk.context_start_at,
                "end_at": chunk.context_end_at,
                "score": max(0.0, 1.0 / max(rank, 1)),
            }
            for rank, chunk in enumerate(_deduplicate_contexts(ranked)[:20], start=1)
        ]
        output[str(raw_entry.get("id") or position)] = {
            "results": rows,
            "meta": {
                "degradations": list(degradations),
                "retrieval_strategy": requested_retrieval,
                "effective_retrieval_strategy": effective_retrieval,
                "rerank_requested": requested_rerank,
                "rerank_effective": bool(rerank_enabled),
                "index_scope": "tenant_isolated",
                "index_strategy": strategy,
            },
            "hit_at_10": float(metric["mrr_at_10"] > 0),
            "mrr_at_10": metric["mrr_at_10"],
            "recall_at_20": metric["recall_at_20"],
            "valid": True,
        }
    return output


def _tenant_base_chunking_config(tenant, knowledge_base_id: str):
    """加载知识库实际生效的分块配置作为各策略的公共基底（对齐生产入库参数）。"""
    from .chunking.config import ChunkingConfig
    from .document_processing import normalized_chunking_config
    from .models import KnowledgeBase

    if not knowledge_base_id:
        return None
    knowledge_base = KnowledgeBase.objects.filter(
        id=knowledge_base_id, tenant=tenant, deleted_at__isnull=True
    ).first()
    if knowledge_base is None:
        return None
    return ChunkingConfig.from_mapping(normalized_chunking_config(knowledge_base.chunking_config, None))


def run_chunking_comparison(
    tenant_id: int,
    dataset: list[dict] | None = None,
    strategies: list[str] | tuple[str, ...] | None = None,
    *,
    tenant=None,
    knowledge_base_id: str = "",
    retrieval_strategy: str = "hybrid",
    rerank_enabled: bool = True,
    cancel_callback=None,
    progress_callback=None,
) -> dict:
    """Compare isolated chunking strategies against stable, tenant-scoped source evidence."""
    declared_status = ""
    if dataset is None:
        dataset, declared_status = load_chunking_dataset()
    selected = tuple(str(strategy) for strategy in (DEFAULT_STRATEGIES if strategies is None else strategies))
    if not selected:
        return _unverified_result(("insufficient_strategies", "at least one supported chunking strategy is required"), strategies=selected)
    if len(set(selected)) != len(selected) or any(strategy not in ALLOWED_STRATEGIES for strategy in selected):
        return _unverified_result(("malformed_strategy", "strategies must be unique supported chunking strategies"), strategies=selected or DEFAULT_STRATEGIES)
    try:
        entries = _parse_dataset(dataset, declared_status)
        documents = _load_documents(tenant_id, entries)
        base_config = _tenant_base_chunking_config(tenant, knowledge_base_id)
        semantic_cache = {}
        metrics = {}
        errors = []
        for strategy_index, strategy in enumerate(selected, start=1):
            try:
                def strategy_progress(done, total, *, _index=strategy_index):
                    if progress_callback:
                        progress_callback(done, total, _index, len(selected))

                metrics[strategy] = _evaluate_strategy(
                    strategy,
                    documents,
                    entries,
                    base_config=base_config,
                    semantic_cache=semantic_cache,
                    tenant=tenant,
                    retrieval_strategy=retrieval_strategy,
                    rerank_enabled=rerank_enabled,
                    cancel_callback=cancel_callback,
                    progress_callback=strategy_progress,
                )
            except _UnverifiedEvaluation as exc:
                metrics[strategy] = {
                    **_empty_metrics(),
                    "reasons": [_reason(exc.code, exc.message)],
                    "retrieval_strategy": str(retrieval_strategy or "hybrid").lower(),
                    "rerank_enabled": bool(rerank_enabled),
                    "requested_pipeline": {"retrieval_strategy": str(retrieval_strategy or "hybrid").lower(), "rerank_enabled": bool(rerank_enabled)},
                    "verification_status": "unverified",
                }
                errors.append((strategy, exc.code))
            except Exception as exc:
                logger.exception("chunking evaluation strategy failed: %s", strategy)
                code = "model_unavailable" if strategy == "semantic_parent_child" else "strategy_failed"
                metrics[strategy] = {
                    **_empty_metrics(),
                    "reasons": [_reason(code, type(exc).__name__)],
                    "retrieval_strategy": str(retrieval_strategy or "hybrid").lower(),
                    "rerank_enabled": bool(rerank_enabled),
                    "requested_pipeline": {"retrieval_strategy": str(retrieval_strategy or "hybrid").lower(), "rerank_enabled": bool(rerank_enabled)},
                    "verification_status": "unverified",
                }
                errors.append((strategy, code))
    except _UnverifiedEvaluation as exc:
        return _unverified_result((exc.code, exc.message), strategies=selected)
    gates = evaluate_release_gates(metrics)
    hard_failures = bool(errors)
    any_usable = any(bool(item.get("questions")) for item in metrics.values())
    all_verified = bool(metrics) and not hard_failures and all(item.get("verified") is True for item in metrics.values())
    verification_status = "verified" if all_verified else ("degraded" if any_usable else "unverified")
    primary_strategy = selected[0] if selected else ""
    comparisons = {strategy: value for strategy, value in metrics.items() if strategy != primary_strategy}
    return {
        "dataset_status": "verified" if verification_status == "verified" else "unverified",
        "verification_status": verification_status,
        "verified": all_verified,
        "primary_strategy": primary_strategy,
        "primary": metrics.get(primary_strategy, {}),
        "comparisons": comparisons,
        "pass": bool(gates.get("auto_parent_child", {}).get("pass")) if "auto_parent_child" in selected else None,
        "strategies": metrics,
        "gates": gates,
        "documents": [
            {"knowledge_id": knowledge_id, "version": document.version}
            for knowledge_id, document in sorted(documents.items())
        ],
        "reasons": [
            _reason(code, f"{strategy} evaluation failed")
            for strategy, code in sorted(set(errors))
        ],
    }
