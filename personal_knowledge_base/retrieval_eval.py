"""
检索评估（确定性、仅检索层）

对比 RRF + BGE-Reranker 新管线（hybrid_search_ex）与旧“分数直接相加”基线
（_baseline_score_addition_search）在 MRR@10 / Recall@20 上的差异。
与 rag_eval.py 的 RAGAs 风格 LLM 评判管道相互独立，本模块不调用任何 LLM。
"""

import json
import re
from pathlib import Path

from .search import _baseline_score_addition_search, hybrid_search_ex

_DATASET_DIR = Path(__file__).parent / "eval_datasets"
_EPS = 1e-9


def mrr_at_k(ranked: list[str], relevant: set[str], k: int = 10) -> float:
    """MRR@K：第一个命中相关项的倒数排名；K 内无命中记 0。"""
    for position, chunk_id in enumerate(ranked[:k], start=1):
        if chunk_id in relevant:
            return 1.0 / position
    return 0.0


def recall_at_k(ranked: list[str], relevant: set[str], k: int = 20) -> float:
    """Recall@K：前 K 中命中的相关项占全部相关项的比例；无相关项记 0。"""
    if not relevant:
        return 0.0
    hits = sum(1 for chunk_id in ranked[:k] if chunk_id in relevant)
    return hits / len(relevant)


def load_retrieval_dataset(name: str = "retrieval_v1") -> list[dict]:
    """读取版本化检索评估数据集；每条 {query, kb_ids, relevant_chunk_ids}。"""
    path = _DATASET_DIR / f"{name}.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


# 形如 <chunk-id-1> / <knowledge-base-id> 的占位符：默认数据集未替换为真实标注
_TEMPLATE_LIKE = re.compile(r"<[^>]+>")


def _has_real_annotations(dataset: list[dict]) -> bool:
    """数据集是否含至少一条非空、非占位符的相关标注。"""
    for entry in dataset:
        ids = [str(i).strip() for i in (entry.get("relevant_chunk_ids") or [])]
        ids = [i for i in ids if i]
        if ids and not all(bool(_TEMPLATE_LIKE.fullmatch(i)) for i in ids):
            return True
    return False


def run_retrieval_comparison(
    tenant_id: int,
    dataset: list[dict] | None = None,
    k_mrr: int = 10,
    k_recall: int = 20,
) -> dict:
    """
    对每个评估条目运行新管线与基线，聚合 MRR@k_mrr / Recall@k_recall。
    pass 判据：MRR@10 相对提升 ≥5% 且 Recall@20 不降。

    数据集无真实标注（空或占位符模板）时返回 dataset_status="template"，
    跳过指标计算，避免把“没数据可测”误报为 pass=false。
    """
    dataset = dataset if dataset is not None else load_retrieval_dataset()
    if not dataset or not _has_real_annotations(dataset):
        return {
            "dataset_status": "template",
            "message": "评估数据集为空或仍是占位符模板，请替换为真实 chunk 标注后再运行评估。",
            "mrr_new": 0.0,
            "mrr_baseline": 0.0,
            "recall_new": 0.0,
            "recall_baseline": 0.0,
            "delta_pct": 0.0,
            "pass": False,
            "k_mrr": k_mrr,
            "k_recall": k_recall,
            "questions": len(dataset),
            "per_question": [],
        }
    limit = max(k_mrr, k_recall)
    per_question = []
    new_mrrs: list[float] = []
    base_mrrs: list[float] = []
    new_recalls: list[float] = []
    base_recalls: list[float] = []
    for entry in dataset:
        relevant = set(entry.get("relevant_chunk_ids") or [])
        kb_ids = entry.get("kb_ids") or []
        query = entry.get("query") or ""
        new_results, _meta = hybrid_search_ex(tenant_id, kb_ids, query, top_k=limit)
        new_ids = [r.get("chunk_id") for r in new_results if r.get("chunk_id")]
        base_ids = _baseline_score_addition_search(tenant_id, kb_ids, query, limit=limit)
        mrr_new = mrr_at_k(new_ids, relevant, k_mrr)
        mrr_base = mrr_at_k(base_ids, relevant, k_mrr)
        rec_new = recall_at_k(new_ids, relevant, k_recall)
        rec_base = recall_at_k(base_ids, relevant, k_recall)
        new_mrrs.append(mrr_new)
        base_mrrs.append(mrr_base)
        new_recalls.append(rec_new)
        base_recalls.append(rec_base)
        per_question.append(
            {
                "query": query,
                "mrr_new": mrr_new,
                "mrr_baseline": mrr_base,
                "recall_new": rec_new,
                "recall_baseline": rec_base,
            }
        )

    mrr_new = _mean(new_mrrs)
    mrr_baseline = _mean(base_mrrs)
    recall_new = _mean(new_recalls)
    recall_baseline = _mean(base_recalls)
    delta_pct = (mrr_new - mrr_baseline) / max(mrr_baseline, _EPS) * 100
    passed = delta_pct >= 5.0 and recall_new >= recall_baseline
    return {
        "mrr_new": mrr_new,
        "mrr_baseline": mrr_baseline,
        "recall_new": recall_new,
        "recall_baseline": recall_baseline,
        "delta_pct": delta_pct,
        "pass": passed,
        "k_mrr": k_mrr,
        "k_recall": k_recall,
        "questions": len(per_question),
        "per_question": per_question,
    }


if __name__ == "__main__":  # metric math self-check
    assert mrr_at_k(["a", "b", "c"], {"b"}, 10) == 0.5
    assert mrr_at_k(["a", "b"], {"z"}, 10) == 0.0
    assert recall_at_k(["a", "b", "c"], {"a", "c", "z"}, 3) == 2 / 3
    assert recall_at_k([], {"a"}, 5) == 0.0
    print("retrieval_eval metric self-check OK")
