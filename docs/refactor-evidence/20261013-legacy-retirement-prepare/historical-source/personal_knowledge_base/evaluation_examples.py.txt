"""Project filtered judge scores back onto their original evaluation rows."""
from collections import Counter

from .ragas_adapter import METRIC_NAMES, is_usable_ragas_score


def original_example_id(value, index):
    return str(value) if value is not None and str(value) else f"row-{index}"


def tenant_example_rows(entries, answers):
    rows = []
    for index, entry in enumerate(entries):
        saved = answers.get(str(entry.get("id")))
        rows.append({
            **(saved or {"valid": False, "error": "answer_missing"}),
            "example_id": original_example_id(entry.get("id"), index),
            "row_index": index,
            "answer_recorded": isinstance(saved, dict),
        })
    return rows


def open_example_rows(details, original_rows=None):
    if original_rows is not None:
        by_id = {str(row.get("query_id")): row for row in details or [] if isinstance(row, dict)}
        return [{
            **by_id.get(str(row.get("query_id")), {"valid": False, "error": "answer_missing"}),
            "example_id": original_example_id(row.get("query_id"), index),
            "row_index": index,
            "answer_recorded": str(row.get("query_id")) in by_id,
        } for index, row in enumerate(original_rows)]
    return [{
        **detail,
        "example_id": original_example_id(detail.get("query_id"), index),
        "row_index": index,
        "answer_recorded": True,
    } for index, detail in enumerate(details or []) if isinstance(detail, dict)]


def judge_example_ids(rows, expected_total=None):
    """Historical positional scores are safe only with a complete input record."""
    if (expected_total is not None and len(rows) != expected_total) or any(not row.get("answer_recorded") for row in rows):
        return None
    return [row["example_id"] for row in rows if row.get("valid", True)]


def align_checkpoint_scores(scores, saved_ids, current_ids):
    """Reuse positional adapter slots only after a reliable identity join.

    Ambiguous saved work must remain unmatched; discarding it into empty
    adapter slots would silently schedule extra model calls to repair identity.
    """
    scores = list(scores or [])
    if not any(scores):
        return [], None
    if not isinstance(saved_ids, (list, tuple)) or not isinstance(current_ids, (list, tuple)):
        return None, "checkpoint_score_identity_unmatched"
    saved_ids = [str(value) for value in saved_ids]
    current_ids = [str(value) for value in current_ids]
    if (len(scores) > len(saved_ids) or len(set(saved_ids)) != len(saved_ids)
            or len(set(current_ids)) != len(current_ids)
            or any(value not in current_ids for value, item in zip(saved_ids, scores) if item)):
        return None, "checkpoint_score_identity_unmatched"
    by_id = dict(zip(saved_ids, scores))
    return [by_id.get(value, {}) for value in current_ids], None


def build_evaluation_examples(rows, scores, score_ids):
    scores = list(scores or [])
    counts = Counter(score_ids or [])
    score_by_id = {
        str(example_id): item
        for example_id, item in zip(score_ids or [], scores)
        if counts[example_id] == 1
    } if score_ids is not None and len(scores) <= len(score_ids) else {}
    examples = []
    for row in rows:
        example = {"example_id": row["example_id"], "row_index": row["row_index"], "valid": False}
        item = score_by_id.get(row["example_id"])
        if not row.get("valid", True):
            example["error"] = str(row.get("error") or "answer_generation_failed")
        elif item is None:
            example["error"] = "ragas_score_unmatched" if scores else "ragas_score_missing"
        elif isinstance(item, dict) and item.get("valid", True) and is_usable_ragas_score(item):
            example.update({metric: item[metric] for metric in METRIC_NAMES})
            example["valid"] = True
        else:
            example["error"] = str(item.get("error") or "ragas_score_invalid") if isinstance(item, dict) else "ragas_score_invalid"
        examples.append(example)
    return examples


def open_judge_projection(result):
    """The evaluator mutates and filters details; use its returned query IDs."""
    details = (result or {}).get("details")
    if not isinstance(details, list) or any("ragas_valid" not in row for row in details):
        return None
    return (
        [str(row.get("query_id")) if row.get("query_id") else None for row in details],
        [{**{metric: row[metric] for metric in METRIC_NAMES if metric in row},
          **({"valid": False, "error": row.get("error") or "ragas_score_invalid"} if not row.get("valid", True) else {})}
         if row.get("ragas_valid") else {"valid": False, "error": row.get("ragas_error") or "ragas_score_invalid"}
         for row in details],
    )
