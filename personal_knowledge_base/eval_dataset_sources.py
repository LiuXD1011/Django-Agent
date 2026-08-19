"""Download and deterministically normalize public evaluation dataset subsets."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

from .eval_dataset_registry import DatasetSpec, get_dataset_spec


def load_dataset_payload(spec: DatasetSpec, *, download: bool = False, cache_dir: str | Path | None = None):
    """Load a registered fixture or a checksum-verified cached source payload.

    Large upstream corpora are never fetched implicitly. Callers opt in with
    ``download=True``; the resulting bytes must match the registered checksum.
    """
    cache_path = Path(cache_dir) / spec.dataset_id / f"{spec.version}.json" if cache_dir else spec.cache_path
    if cache_path.exists():
        raw = cache_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != spec.sha256:
            raise ValueError(f"cached dataset checksum mismatch: {spec.dataset_id}@{spec.version}")
        return json.loads(raw.decode("utf-8"))
    if download:
        with urlopen(spec.source_url, timeout=30) as response:
            raw = response.read()
        if hashlib.sha256(raw).hexdigest() != spec.sha256:
            raise ValueError(f"downloaded dataset checksum mismatch: {spec.dataset_id}@{spec.version}")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(raw)
        return json.loads(raw.decode("utf-8"))
    return json.loads(spec.fixture_path.read_text(encoding="utf-8"))


def load_normalized_dataset(dataset_id: str, version: str = "v1", **kwargs) -> list[dict]:
    spec = get_dataset_spec(dataset_id, version)
    return normalize_dataset_records(spec.dataset_id, spec.version, load_dataset_payload(spec, **kwargs))


def _record(dataset_id: str, version: str, *, question="", reference_answer="", documents=None, evidence=None, question_type="", status="ready", source_id="") -> dict:
    return {
        "dataset_id": dataset_id,
        "dataset_version": version,
        "source_id": source_id,
        "question": question,
        "reference_answer": reference_answer,
        "documents": documents or [],
        "evidence": evidence or [],
        "question_type": question_type,
        "status": status,
    }


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _document(document_id: str, title: str, text: str) -> dict:
    return {"document_id": document_id, "title": title, "text": text}


def _evidence(document_id: str, text: str, start: int, end: int) -> dict:
    return {
        "document_id": document_id,
        "source_start": start,
        "source_end": end,
        "text": text[start:end],
    }


def _stable_id(prefix: str, value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return f"{prefix}-{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:16]}"


def normalize_dataset_records(dataset_id: str, version: str, payload) -> list[dict]:
    dataset_id = str(dataset_id or "").strip().lower()
    if dataset_id == "ragas":
        return _normalize_ragas(version, payload)
    if dataset_id == "squad":
        return _normalize_squad(version, payload)
    if dataset_id == "hotpotqa":
        return _normalize_hotpotqa(version, payload)
    get_dataset_spec(dataset_id, version)
    raise AssertionError("registered dataset has no normalizer")


def _dedupe_status(dataset_id: str, version: str, source_id: str, seen: set[str]) -> str | None:
    if not source_id:
        return "skipped_empty_id"
    if source_id in seen:
        return "skipped_duplicate"
    seen.add(source_id)
    return None


def _normalize_ragas(version: str, payload) -> list[dict]:
    rows = payload.get("data", []) if isinstance(payload, dict) else payload
    rows = rows if isinstance(rows, list) else []
    records, seen = [], set()
    for row in rows:
        row = row if isinstance(row, dict) else {}
        question = _text(row.get("question"))
        answer = _text(row.get("ground_truth") or row.get("reference_answer") or row.get("answer"))
        contexts = row.get("contexts") or row.get("retrieved_contexts") or []
        contexts = [_text(value) for value in contexts if _text(value)] if isinstance(contexts, list) else []
        source_id = _text(row.get("id")) or _stable_id("ragas", [question, answer, contexts])
        if not question:
            records.append(_record("ragas", version, reference_answer=answer, question_type="generative", status="skipped_empty_question", source_id=source_id))
            continue
        if not answer or not contexts:
            records.append(_record("ragas", version, question=question, reference_answer=answer, question_type="generative", status="skipped_empty_data", source_id=source_id))
            continue
        duplicate = _dedupe_status("ragas", version, source_id, seen)
        if duplicate:
            records.append(_record("ragas", version, question=question, reference_answer=answer, question_type="generative", status=duplicate, source_id=source_id))
            continue
        documents = [_document(f"ragas:{source_id}:{index}", f"Ragas context {index + 1}", context) for index, context in enumerate(contexts)]
        evidence = [_evidence(document["document_id"], document["text"], 0, len(document["text"])) for document in documents]
        records.append(_record("ragas", version, question=question, reference_answer=answer, documents=documents, evidence=evidence, question_type="generative", source_id=source_id))
    return records


def _normalize_squad(version: str, payload) -> list[dict]:
    articles = payload.get("data", []) if isinstance(payload, dict) else []
    records, seen = [], set()
    for article_index, article in enumerate(articles if isinstance(articles, list) else []):
        article = article if isinstance(article, dict) else {}
        title = _text(article.get("title")) or f"SQuAD article {article_index + 1}"
        paragraphs = article.get("paragraphs") or []
        for paragraph_index, paragraph in enumerate(paragraphs if isinstance(paragraphs, list) else []):
            paragraph = paragraph if isinstance(paragraph, dict) else {}
            context = _text(paragraph.get("context"))
            document_id = f"squad:{article_index}:{paragraph_index}"
            for qa_index, qa in enumerate(paragraph.get("qas") or []):
                qa = qa if isinstance(qa, dict) else {}
                question = _text(qa.get("question"))
                source_id = _text(qa.get("id")) or _stable_id("squad", [article_index, paragraph_index, qa_index, question])
                duplicate = _dedupe_status("squad", version, source_id, seen)
                if duplicate:
                    records.append(_record("squad", version, question=question, question_type="extractive", status=duplicate, source_id=source_id))
                    continue
                answers = qa.get("answers") or []
                answer = answers[0] if isinstance(answers, list) and answers and isinstance(answers[0], dict) else {}
                reference_answer = _text(answer.get("text"))
                if not question:
                    status = "skipped_empty_question"
                elif not context or not reference_answer:
                    status = "skipped_empty_data"
                else:
                    status = "ready"
                documents = [_document(document_id, title, context)] if context else []
                evidence = []
                for item in answers if isinstance(answers, list) else []:
                    if not isinstance(item, dict):
                        continue
                    text = _text(item.get("text"))
                    start = item.get("answer_start")
                    if isinstance(start, bool) or not isinstance(start, int) or not text:
                        continue
                    explicit_end = item.get("answer_end")
                    end = explicit_end if isinstance(explicit_end, int) and not isinstance(explicit_end, bool) else start + len(text)
                    if 0 <= start <= end <= len(context) and context[start:end] == text:
                        span = _evidence(document_id, context, start, end)
                        if span not in evidence:
                            evidence.append(span)
                if status == "ready" and not evidence:
                    status = "skipped_invalid_evidence"
                records.append(_record("squad", version, question=question, reference_answer=reference_answer, documents=documents, evidence=evidence, question_type="extractive", status=status, source_id=source_id))
    return records


def _normalize_hotpotqa(version: str, payload) -> list[dict]:
    rows = payload.get("data", []) if isinstance(payload, dict) else payload
    rows = rows if isinstance(rows, list) else []
    records, seen = [], set()
    for row_index, row in enumerate(rows):
        row = row if isinstance(row, dict) else {}
        question, answer = _text(row.get("question")), _text(row.get("answer"))
        source_id = _text(row.get("_id") or row.get("id")) or _stable_id("hotpotqa", [row_index, question, answer])
        duplicate = _dedupe_status("hotpotqa", version, source_id, seen)
        if duplicate:
            records.append(_record("hotpotqa", version, question=question, reference_answer=answer, question_type="multi_hop", status=duplicate, source_id=source_id))
            continue
        documents, title_occurrences = [], {}
        for context_index, pair in enumerate(row.get("context") or []):
            if not isinstance(pair, list) or len(pair) != 2:
                continue
            title, sentences = _text(pair[0]), pair[1]
            sentences = [_text(sentence) for sentence in sentences if _text(sentence)] if isinstance(sentences, list) else []
            text = "\n".join(sentences)
            if not text:
                continue
            document_id = f"hotpotqa:{source_id}:{context_index}"
            documents.append(_document(document_id, title or f"HotpotQA document {context_index + 1}", text))
            title_occurrences.setdefault(title, []).append((document_id, sentences, text))
        evidence = []
        for fact in row.get("supporting_facts") or []:
            if not isinstance(fact, list) or len(fact) != 2 or not isinstance(fact[1], int):
                continue
            title, sentence_index = _text(fact[0]), fact[1]
            for document_id, sentences, text in title_occurrences.get(title, []):
                if 0 <= sentence_index < len(sentences):
                    start = sum(len(sentence) + 1 for sentence in sentences[:sentence_index])
                    end = start + len(sentences[sentence_index])
                    span = _evidence(document_id, text, start, end)
                    if span not in evidence:
                        evidence.append(span)
        if not question:
            status = "skipped_empty_question"
        elif not answer or not documents:
            status = "skipped_empty_data"
        elif not evidence:
            status = "skipped_invalid_evidence"
        else:
            status = "ready"
        records.append(_record("hotpotqa", version, question=question, reference_answer=answer, documents=documents, evidence=evidence, question_type="multi_hop", status=status, source_id=source_id))
    return records
