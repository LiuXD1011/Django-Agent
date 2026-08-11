"""Deterministic retrieval evaluation with versioned source-span annotations."""

import json
import re
from pathlib import Path

from .models import Chunk, Knowledge
from .search import _baseline_score_addition_search, hybrid_search_ex


_DATASET_DIR = Path(__file__).parent / "eval_datasets"
_EPS = 1e-9
_TEMPLATE_LIKE = re.compile(r"<[^>]+>")


def hit_at_k(ranked: list[str], relevant: set[str], k: int = 10) -> float:
    """Hit@K: whether any relevant result appears in the first K positions."""
    return float(any(chunk_id in relevant for chunk_id in ranked[:k]))


def mrr_at_k(ranked: list[str], relevant: set[str], k: int = 10) -> float:
    """MRR@K: reciprocal rank of the first relevant result."""
    for position, chunk_id in enumerate(ranked[:k], start=1):
        if chunk_id in relevant:
            return 1.0 / position
    return 0.0


def recall_at_k(ranked: list[str], relevant: set[str], k: int = 20) -> float:
    """Recall@K: fraction of relevant results present in the first K positions."""
    if not relevant:
        return 0.0
    return len(set(ranked[:k]) & relevant) / len(relevant)


def load_retrieval_dataset(name: str = "retrieval_v2") -> list[dict]:
    """Load a versioned retrieval dataset, returning an empty list when absent."""
    path = _DATASET_DIR / f"{name}.json"
    if not path.exists():
        return []
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, list) else []


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _is_template(value) -> bool:
    return isinstance(value, str) and bool(_TEMPLATE_LIKE.fullmatch(value.strip()))


def _empty_result(dataset_status: str, reasons: list[dict], questions: int = 0) -> dict:
    return {
        "dataset_status": dataset_status,
        "verified": False,
        "dataset_format": "retrieval_v2",
        "reasons": reasons,
        "message": reasons[0]["message"] if reasons else "evaluation dataset is unverified",
        "hit_at_10_new": None,
        "hit_at_10_baseline": None,
        "mrr_new": None,
        "mrr_baseline": None,
        "recall_new": None,
        "recall_baseline": None,
        "delta_pct": None,
        "pass": False,
        "k_hit": 10,
        "k_mrr": 10,
        "k_recall": 20,
        "questions": questions,
        "per_question": [],
    }


def _has_legacy_annotations(dataset: list[dict]) -> bool:
    if not dataset or not all(isinstance(entry, dict) for entry in dataset):
        return False
    for entry in dataset:
        chunk_ids = entry.get("relevant_chunk_ids") or []
        if not isinstance(entry.get("query"), str) or not entry["query"].strip():
            return False
        if not chunk_ids or any(not str(chunk_id).strip() or _is_template(str(chunk_id)) for chunk_id in chunk_ids):
            return False
    return True


def _validate_v2_dataset(tenant_id: int, dataset: list[dict]) -> tuple[list[dict], list[dict]]:
    """Validate immutable document versions and source-span evidence for one tenant."""
    if not isinstance(dataset, list) or not dataset:
        return [], [{"code": "empty_dataset", "message": "evaluation dataset is empty"}]
    document_ids = set()
    for entry in dataset:
        if not isinstance(entry, dict):
            return [], [{"code": "malformed_dataset", "message": "each dataset entry must be an object"}]
        for document in entry.get("documents") or []:
            if isinstance(document, dict) and isinstance(document.get("knowledge_id"), str):
                document_ids.add(document["knowledge_id"])
    if not document_ids or any(_is_template(value) for value in document_ids):
        return [], [{"code": "template_dataset", "message": "dataset contains placeholder document identifiers"}]
    documents = {
        item.id: item
        for item in Knowledge.objects.filter(
            tenant_id=tenant_id,
            id__in=document_ids,
            deleted_at__isnull=True,
            knowledge_base__tenant_id=tenant_id,
            knowledge_base__deleted_at__isnull=True,
        ).select_related("knowledge_base")
    }
    if len(documents) != len(document_ids):
        return [], [{"code": "document_unavailable", "message": "dataset references unavailable documents"}]

    normalized = []
    for position, entry in enumerate(dataset):
        query = entry.get("query")
        declared_documents = entry.get("documents")
        evidence = entry.get("evidence")
        if not isinstance(query, str) or not query.strip():
            return [], [{"code": "malformed_dataset", "message": f"entry {position} has no query"}]
        if not isinstance(declared_documents, list) or not declared_documents:
            return [], [{"code": "malformed_dataset", "message": f"entry {position} has no documents"}]
        if not isinstance(evidence, list) or not evidence:
            return [], [{"code": "malformed_dataset", "message": f"entry {position} has no evidence"}]
        entry_documents = set()
        for document in declared_documents:
            knowledge_id = document.get("knowledge_id") if isinstance(document, dict) else None
            file_hash = document.get("file_hash") if isinstance(document, dict) else None
            if not isinstance(knowledge_id, str) or not isinstance(file_hash, str) or _is_template(knowledge_id) or _is_template(file_hash):
                return [], [{"code": "template_dataset", "message": f"entry {position} has placeholder document metadata"}]
            knowledge = documents.get(knowledge_id)
            if not knowledge or not knowledge.file_hash or knowledge.file_hash != file_hash:
                return [], [{"code": "document_version_mismatch", "message": f"entry {position} document version no longer matches"}]
            entry_documents.add(knowledge_id)
        normalized_evidence = []
        for row in evidence:
            knowledge_id = row.get("knowledge_id") if isinstance(row, dict) else None
            start = row.get("source_start") if isinstance(row, dict) else None
            end = row.get("source_end") if isinstance(row, dict) else None
            if knowledge_id not in entry_documents:
                return [], [{"code": "invalid_evidence", "message": f"entry {position} evidence references an undeclared document"}]
            if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start:
                return [], [{"code": "invalid_evidence", "message": f"entry {position} contains an invalid source span"}]
            normalized_evidence.append({"knowledge_id": knowledge_id, "source_start": start, "source_end": end})
        normalized.append(
            {
                "query": query.strip(),
                "kb_ids": sorted({documents[knowledge_id].knowledge_base_id for knowledge_id in entry_documents}),
                "evidence": normalized_evidence,
            }
        )
    return normalized, []


def _chunk_spans(tenant_id: int, chunk_ids: list[str]) -> list[dict]:
    if not chunk_ids:
        return []
    chunks = {
        chunk.id: chunk
        for chunk in Chunk.objects.filter(
            tenant_id=tenant_id,
            id__in=chunk_ids,
            deleted_at__isnull=True,
            knowledge__tenant_id=tenant_id,
            knowledge__deleted_at__isnull=True,
            knowledge_base__tenant_id=tenant_id,
            knowledge_base__deleted_at__isnull=True,
        )
    }
    return [
        {
            "chunk_id": chunk_id,
            "knowledge_id": chunks[chunk_id].knowledge_id,
            "start_at": chunks[chunk_id].start_at,
            "end_at": chunks[chunk_id].end_at,
        }
        for chunk_id in chunk_ids
        if chunk_id in chunks
    ]


def _span_metrics(ranked: list[dict], evidence: list[dict], k_hit: int, k_mrr: int, k_recall: int) -> tuple[float, float, float]:
    hit = 0.0
    mrr = 0.0
    covered = set()
    for rank, result in enumerate(ranked[: max(k_hit, k_mrr, k_recall)], start=1):
        matching = {
            index
            for index, row in enumerate(evidence)
            if row["knowledge_id"] == result["knowledge_id"]
            and result["start_at"] < row["source_end"]
            and result["end_at"] > row["source_start"]
        }
        if matching and rank <= k_hit:
            hit = 1.0
        if matching and not mrr and rank <= k_mrr:
            mrr = 1.0 / rank
        if rank <= k_recall:
            covered.update(matching)
    return hit, mrr, len(covered) / len(evidence) if evidence else 0.0


def _pipeline_provenance(metas: list[dict]) -> dict:
    def values(key: str) -> list[str]:
        return sorted({str(meta.get(key) or "").strip() for meta in metas if str(meta.get(key) or "").strip()})

    return {
        "rrf_k": sorted({meta.get("rrf_k") for meta in metas if isinstance(meta.get("rrf_k"), int)}),
        "embedding_models": values("embedding_model"),
        "rerank_models": values("rerank_model"),
    }


def _run_v2_comparison(tenant_id: int, dataset: list[dict], k_hit: int, k_mrr: int, k_recall: int) -> dict:
    limit = max(k_hit, k_mrr, k_recall)
    per_question = []
    new_hits: list[float] = []
    baseline_hits: list[float] = []
    new_mrrs: list[float] = []
    baseline_mrrs: list[float] = []
    new_recalls: list[float] = []
    baseline_recalls: list[float] = []
    pipeline_metas: list[dict] = []
    for entry in dataset:
        results, meta = hybrid_search_ex(tenant_id, entry["kb_ids"], entry["query"], top_k=limit)
        pipeline_metas.append(meta)
        new_spans = _chunk_spans(tenant_id, [str(row.get("chunk_id") or "") for row in results])
        baseline_ids = _baseline_score_addition_search(tenant_id, entry["kb_ids"], entry["query"], limit=limit)
        baseline_spans = _chunk_spans(tenant_id, baseline_ids)
        hit_new, mrr_new, recall_new = _span_metrics(new_spans, entry["evidence"], k_hit, k_mrr, k_recall)
        hit_baseline, mrr_baseline, recall_baseline = _span_metrics(baseline_spans, entry["evidence"], k_hit, k_mrr, k_recall)
        new_hits.append(hit_new)
        baseline_hits.append(hit_baseline)
        new_mrrs.append(mrr_new)
        baseline_mrrs.append(mrr_baseline)
        new_recalls.append(recall_new)
        baseline_recalls.append(recall_baseline)
        per_question.append(
            {
                "query": entry["query"],
                "hit_at_10_new": hit_new,
                "hit_at_10_baseline": hit_baseline,
                "mrr_new": mrr_new,
                "mrr_baseline": mrr_baseline,
                "recall_new": recall_new,
                "recall_baseline": recall_baseline,
            }
        )
    result = _comparison_result(
        new_hits, baseline_hits, new_mrrs, baseline_mrrs, new_recalls, baseline_recalls,
        per_question, k_hit, k_mrr, k_recall, dataset_status="verified", verified=True, dataset_format="retrieval_v2", reasons=[],
    )
    result["pipeline"] = _pipeline_provenance(pipeline_metas)
    return result


def _comparison_result(
    new_hits, baseline_hits, new_mrrs, baseline_mrrs, new_recalls, baseline_recalls,
    per_question, k_hit, k_mrr, k_recall, *, dataset_status, verified, dataset_format, reasons,
) -> dict:
    mrr_new = _mean(new_mrrs)
    mrr_baseline = _mean(baseline_mrrs)
    recall_new = _mean(new_recalls)
    recall_baseline = _mean(baseline_recalls)
    delta_pct = (
        (mrr_new - mrr_baseline) / mrr_baseline * 100
        if mrr_baseline > _EPS
        else (100.0 if mrr_new > 0 else 0.0)
    )
    return {
        "dataset_status": dataset_status,
        "dataset_format": dataset_format,
        "verified": verified,
        "reasons": reasons,
        "hit_at_10_new": _mean(new_hits),
        "hit_at_10_baseline": _mean(baseline_hits),
        "mrr_new": mrr_new,
        "mrr_baseline": mrr_baseline,
        "recall_new": recall_new,
        "recall_baseline": recall_baseline,
        "delta_pct": delta_pct,
        "pass": delta_pct >= 5.0 and recall_new >= recall_baseline,
        "k_hit": k_hit,
        "k_mrr": k_mrr,
        "k_recall": k_recall,
        "questions": len(per_question),
        "per_question": per_question,
    }


def _run_legacy_comparison(tenant_id: int, dataset: list[dict], k_hit: int, k_mrr: int, k_recall: int) -> dict:
    limit = max(k_hit, k_mrr, k_recall)
    per_question = []
    new_hits: list[float] = []
    baseline_hits: list[float] = []
    new_mrrs: list[float] = []
    baseline_mrrs: list[float] = []
    new_recalls: list[float] = []
    baseline_recalls: list[float] = []
    pipeline_metas: list[dict] = []
    for entry in dataset:
        relevant = set(entry.get("relevant_chunk_ids") or [])
        kb_ids = entry.get("kb_ids") or []
        query = entry.get("query") or ""
        results, meta = hybrid_search_ex(tenant_id, kb_ids, query, top_k=limit)
        pipeline_metas.append(meta)
        new_ids = [row.get("chunk_id") for row in results if row.get("chunk_id")]
        baseline_ids = _baseline_score_addition_search(tenant_id, kb_ids, query, limit=limit)
        new_hits.append(hit_at_k(new_ids, relevant, k_hit))
        baseline_hits.append(hit_at_k(baseline_ids, relevant, k_hit))
        new_mrrs.append(mrr_at_k(new_ids, relevant, k_mrr))
        baseline_mrrs.append(mrr_at_k(baseline_ids, relevant, k_mrr))
        new_recalls.append(recall_at_k(new_ids, relevant, k_recall))
        baseline_recalls.append(recall_at_k(baseline_ids, relevant, k_recall))
        per_question.append(
            {
                "query": query,
                "hit_at_10_new": new_hits[-1],
                "hit_at_10_baseline": baseline_hits[-1],
                "mrr_new": new_mrrs[-1],
                "mrr_baseline": baseline_mrrs[-1],
                "recall_new": new_recalls[-1],
                "recall_baseline": baseline_recalls[-1],
            }
        )
    result = _comparison_result(
        new_hits, baseline_hits, new_mrrs, baseline_mrrs, new_recalls, baseline_recalls,
        per_question, k_hit, k_mrr, k_recall,
        dataset_status="legacy", verified=False, dataset_format="legacy_chunk_ids",
        reasons=[{"code": "legacy_dataset", "message": "legacy chunk identifiers do not record immutable source versions"}],
    )
    result["pipeline"] = _pipeline_provenance(pipeline_metas)
    return result


def run_retrieval_comparison(
    tenant_id: int,
    dataset: list[dict] | None = None,
    k_hit: int = 10,
    k_mrr: int = 10,
    k_recall: int = 20,
) -> dict:
    """Compare hybrid retrieval against the score-addition baseline."""
    dataset = dataset if dataset is not None else load_retrieval_dataset()
    if any(isinstance(entry, dict) and "documents" in entry for entry in dataset or []):
        normalized, reasons = _validate_v2_dataset(tenant_id, dataset)
        if reasons:
            return _empty_result("template" if reasons[0]["code"] == "template_dataset" else "unverified", reasons, len(dataset or []))
        return _run_v2_comparison(tenant_id, normalized, k_hit, k_mrr, k_recall)
    if not dataset or not _has_legacy_annotations(dataset):
        return _empty_result(
            "template",
            [{"code": "template_dataset", "message": "evaluation dataset is empty or still contains placeholder annotations"}],
            len(dataset or []),
        )
    return _run_legacy_comparison(tenant_id, dataset, k_hit, k_mrr, k_recall)
