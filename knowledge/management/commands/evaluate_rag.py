import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from knowledge.models import KBChunk, KnowledgeBase
from knowledge.services import search_with_trace


EXPECTED_FIELDS = ("expected_document_title", "expected_source", "expected_contains")
STAGES = ("vector", "fts", "fusion", "final")


class Command(BaseCommand):
    help = "Evaluate a knowledge base RAG retrieval dataset."

    def add_arguments(self, parser):
        parser.add_argument("--kb", required=True, type=int, help="KnowledgeBase database ID.")
        parser.add_argument("--dataset", required=True, help="Path to a JSONL dataset.")
        parser.add_argument("--top-k", default=6, type=int, help="Number of final hits to evaluate.")
        parser.add_argument(
            "--format",
            choices=("json", "markdown"),
            default="json",
            help="Output format.",
        )
        parser.add_argument("--save-json", default="", help="Optional path to write full JSON results.")

    def handle(self, *args, **options):
        try:
            kb = KnowledgeBase.objects.get(id=options["kb"])
        except KnowledgeBase.DoesNotExist as exc:
            raise CommandError(f"KnowledgeBase id={options['kb']} does not exist.") from exc

        dataset_path = Path(options["dataset"])
        if not dataset_path.exists():
            raise CommandError(f"Dataset does not exist: {dataset_path}")

        cases = list(load_cases(dataset_path))
        if not cases:
            raise CommandError("Dataset is empty.")

        top_k = max(1, int(options["top_k"]))
        results = [evaluate_case(kb, case, index, top_k) for index, case in enumerate(cases, 1)]
        metrics = summarize_metrics(results)
        payload = {
            "kb": {"id": kb.id, "name": kb.name},
            "top_k": top_k,
            "case_count": len(results),
            "hit_at_k": metrics["final"]["hit_at_k"],
            "mrr": metrics["final"]["mrr"],
            "miss_rate": metrics["final"]["miss_rate"],
            "stage_metrics": metrics,
            "rerank_analysis": summarize_rerank(results),
            "results": results,
        }
        payload.update(flatten_stage_metrics(metrics))

        if options["save_json"]:
            save_path = Path(options["save_json"])
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        if options["format"] == "markdown":
            self.stdout.write(render_markdown(payload))
        else:
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))


def load_cases(path):
    with path.open(encoding="utf-8") as file_obj:
        for line_number, line in enumerate(file_obj, 1):
            raw = line.strip()
            if not raw:
                continue
            try:
                case = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise CommandError(f"Invalid JSON on line {line_number}: {exc}") from exc
            question = compact(case.get("question"))
            if not question:
                raise CommandError(f"Line {line_number} is missing question.")
            if not any(compact(case.get(field)) for field in EXPECTED_FIELDS):
                raise CommandError(
                    f"Line {line_number} must include at least one of: {', '.join(EXPECTED_FIELDS)}."
                )
            yield case


def compact(value):
    return " ".join(str(value or "").split())


def hit_matches(hit, case):
    chunk = hit.chunk
    return chunk_matches(chunk, case)


def chunk_matches(chunk, case):
    checks = []
    expected_title = compact(case.get("expected_document_title")).lower()
    expected_source = compact(case.get("expected_source")).lower()
    expected_contains = compact(case.get("expected_contains")).lower()
    if expected_title:
        checks.append(expected_title in compact(chunk.document.title).lower())
    if expected_source:
        checks.append(expected_source in compact(chunk.document.source).lower())
    if expected_contains:
        checks.append(expected_contains in compact(chunk.content).lower())
    return bool(checks) and all(checks)


def rank_trace_candidates(candidates, score_weight=1.0):
    scores = {}
    details = {}
    for item in candidates:
        chunk_id = item.get("chunk_id")
        if chunk_id is None:
            continue
        rank = max(1, int(item.get("rank") or 1))
        scores[chunk_id] = scores.get(chunk_id, 0.0) + (score_weight / rank)
        details.setdefault(chunk_id, []).append(item)
    return [
        {
            "rank": rank,
            "chunk_id": chunk_id,
            "score": round(float(score), 6),
            "details": details.get(chunk_id, []),
        }
        for rank, (chunk_id, score) in enumerate(
            sorted(scores.items(), key=lambda pair: (-pair[1], pair[0])),
            1,
        )
    ]


def normalize_stage_candidates(trace):
    return {
        "vector": rank_trace_candidates(trace.get("vector_candidates", []), score_weight=1.0),
        "fts": rank_trace_candidates(trace.get("fts_candidates", []), score_weight=1.0),
        "fusion": [
            {
                "rank": item.get("rank"),
                "chunk_id": item.get("chunk_id"),
                "score": item.get("score"),
                "source_scores": item.get("source_scores", {}),
                "document_title": item.get("document_title", ""),
                "source": item.get("source", ""),
            }
            for item in trace.get("fusion_candidates", [])
        ],
        "final": [
            {
                "rank": item.get("rank"),
                "chunk_id": item.get("chunk_id"),
                "score": item.get("score"),
                "rerank_score": item.get("rerank_score"),
                "source_scores": item.get("source_scores", {}),
                "document_title": item.get("document_title", ""),
                "source": item.get("source", ""),
            }
            for item in trace.get("final_hits", [])
        ],
    }


def chunk_lookup_for_stages(stages):
    ids = {
        item["chunk_id"]
        for candidates in stages.values()
        for item in candidates
        if item.get("chunk_id") is not None
    }
    if not ids:
        return {}
    return {
        chunk.id: chunk
        for chunk in KBChunk.objects.filter(id__in=ids).select_related("document", "kb")
    }


def annotate_candidates(candidates, chunks, top_k):
    annotated = []
    for rank, item in enumerate(candidates[:top_k], 1):
        chunk = chunks.get(item.get("chunk_id"))
        payload = dict(item)
        payload["rank"] = rank
        payload["document_id"] = chunk.document_id if chunk else None
        payload["document_title"] = chunk.document.title if chunk else item.get("document_title", "")
        payload["source"] = chunk.document.source if chunk else item.get("source", "")
        annotated.append(payload)
    return annotated


def evaluate_stage(candidates, chunks, case, top_k):
    ranked = annotate_candidates(candidates, chunks, top_k)
    matching_rank = None
    for item in ranked:
        chunk = chunks.get(item.get("chunk_id"))
        if chunk and chunk_matches(chunk, case):
            matching_rank = item["rank"]
            break
    return {
        "hit": matching_rank is not None,
        "rank": matching_rank,
        "reciprocal_rank": 0.0 if matching_rank is None else 1.0 / matching_rank,
        "top_hits": ranked,
    }


def evaluate_case(kb, case, index, top_k):
    search_result = search_with_trace(kb, case["question"], top_k=top_k)
    stages = normalize_stage_candidates(search_result["trace"])
    chunks = chunk_lookup_for_stages(stages)
    stage_results = {
        stage: evaluate_stage(stages[stage], chunks, case, top_k)
        for stage in STAGES
    }
    final_result = stage_results["final"]
    fusion_rank = stage_results["fusion"]["rank"]
    final_rank = final_result["rank"]
    if fusion_rank is None or final_rank is None:
        rerank_delta = None
    else:
        rerank_delta = fusion_rank - final_rank

    return {
        "index": index,
        "question": case["question"],
        "expected": {field: case.get(field, "") for field in EXPECTED_FIELDS if case.get(field)},
        "hit": final_result["hit"],
        "rank": final_rank,
        "reciprocal_rank": final_result["reciprocal_rank"],
        "stage_results": stage_results,
        "rerank_rank_delta": rerank_delta,
        "rerank_improved": rerank_delta is not None and rerank_delta > 0,
        "rerank_worsened": rerank_delta is not None and rerank_delta < 0,
        "rewritten_queries": search_result["trace"].get("rewritten_queries", []),
        "trace": search_result["trace"],
        "final_hits": search_result["trace"].get("final_hits", []),
        "fusion_candidates": search_result["trace"].get("fusion_candidates", [])[:10],
        "vector_candidates": stage_results["vector"]["top_hits"],
        "fts_candidates": stage_results["fts"]["top_hits"],
        "rerank": search_result["trace"].get("rerank", {}),
    }


def flatten_stage_metrics(metrics):
    payload = {}
    for stage, values in metrics.items():
        payload[f"{stage}_hit_at_k"] = values["hit_at_k"]
        payload[f"{stage}_hit@k"] = values["hit_at_k"]
        payload[f"{stage}_mrr"] = values["mrr"]
        payload[f"{stage}_miss_rate"] = values["miss_rate"]
    return payload


def summarize_metrics(results):
    metrics = {}
    total = len(results) or 1
    for stage in STAGES:
        stage_items = [item["stage_results"][stage] for item in results]
        hit_count = sum(1 for item in stage_items if item["hit"])
        metrics[stage] = {
            "hit_at_k": hit_count / total,
            "mrr": sum(item["reciprocal_rank"] for item in stage_items) / total,
            "miss_rate": (total - hit_count) / total,
            "hit_count": hit_count,
            "case_count": total,
        }
    return metrics


def summarize_rerank(results):
    comparable = [item for item in results if item["rerank_rank_delta"] is not None]
    improved = sum(1 for item in comparable if item["rerank_improved"])
    worsened = sum(1 for item in comparable if item["rerank_worsened"])
    unchanged = len(comparable) - improved - worsened
    return {
        "comparable_count": len(comparable),
        "improved_count": improved,
        "worsened_count": worsened,
        "unchanged_count": unchanged,
        "improvement_rate": 0.0 if not comparable else improved / len(comparable),
        "average_rank_delta": 0.0
        if not comparable
        else sum(item["rerank_rank_delta"] for item in comparable) / len(comparable),
    }


def render_markdown(payload):
    lines = [
        f"# RAG Evaluation: {payload['kb']['name']}",
        "",
        "## Summary",
        "",
        f"- Top K: {payload['top_k']}",
        f"- Cases: {payload['case_count']}",
        f"- Final Hit@K: {payload['hit_at_k']:.4f}",
        f"- Final MRR: {payload['mrr']:.4f}",
        f"- Final Miss Rate: {payload['miss_rate']:.4f}",
        "",
        "## Stage Comparison",
        "",
        "| Stage | Hit@K | MRR | Miss Rate | Hits/Cases |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for stage in STAGES:
        metrics = payload["stage_metrics"][stage]
        lines.append(
            f"| {stage} | {metrics['hit_at_k']:.4f} | {metrics['mrr']:.4f} | "
            f"{metrics['miss_rate']:.4f} | {metrics['hit_count']}/{metrics['case_count']} |"
        )
    rerank = payload["rerank_analysis"]
    lines.extend(
        [
            "",
            "## Rerank Analysis",
            "",
            f"- Comparable cases: {rerank['comparable_count']}",
            f"- Improved: {rerank['improved_count']}",
            f"- Unchanged: {rerank['unchanged_count']}",
            f"- Worsened: {rerank['worsened_count']}",
            f"- Improvement rate: {rerank['improvement_rate']:.4f}",
            f"- Average rank delta: {rerank['average_rank_delta']:.4f}",
            "",
            "## Failed Cases",
            "",
        ]
    )
    failed = [item for item in payload["results"] if not item["hit"]]
    if not failed:
        lines.append("- none")
    for item in failed:
        lines.append(f"- #{item['index']} {item['question']}")
    lines.extend(
        [
            "",
            "## Case Details",
            "",
        ]
    )
    for item in payload["results"]:
        status = "hit" if item["hit"] else "miss"
        rank = item["rank"] if item["rank"] is not None else "-"
        stages = item["stage_results"]
        lines.extend(
            [
                f"### {item['index']}. {item['question']}",
                "",
                f"- Status: {status}",
                f"- Final rank: {rank}",
                f"- Stage ranks: vector={stages['vector']['rank'] or '-'}, "
                f"fts={stages['fts']['rank'] or '-'}, fusion={stages['fusion']['rank'] or '-'}, "
                f"final={stages['final']['rank'] or '-'}",
                f"- Rerank rank delta: {item['rerank_rank_delta'] if item['rerank_rank_delta'] is not None else '-'}",
                f"- Rewritten queries: {', '.join(item['rewritten_queries']) or '-'}",
                "- Final hits:",
            ]
        )
        if not item["final_hits"]:
            lines.append("  - none")
        for hit in item["final_hits"]:
            rerank = hit["rerank_score"] if hit["rerank_score"] is not None else "-"
            lines.append(
                f"  - #{hit['rank']} chunk={hit['chunk_id']} title={hit['document_title']} "
                f"score={hit['score']} rerank={rerank}"
            )
        lines.append("")
    return "\n".join(lines)
