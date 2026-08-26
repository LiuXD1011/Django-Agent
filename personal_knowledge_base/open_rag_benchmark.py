"""Read-only runtime loader and evaluator for Open RAG Benchmark.

The corpus is deliberately kept outside Django's tenant tables.  The prepared
SQLite file is a cache artifact keyed by the pinned upstream revision.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import re
import sqlite3
import time
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.cache import cache
from django.db import close_old_connections

from .eval_dataset_registry import DatasetSpec

logger = logging.getLogger(__name__)

CORE_FILES = ("queries.json", "qrels.json", "answers.json", "pdf_urls.json")
TASK_TYPE = "prepare_open_rag_dataset"
EVALUATION_TASK_TYPE = "open_rag_evaluation"
MAX_SAMPLE_SIZE = 3045
EVALUATION_INDEX_ALGORITHM_VERSION = "evaluation-index-v2"
# Providers can rate-limit concurrent rerank calls; enable higher concurrency
# only after measuring the configured provider rather than assuming it helps.
RETRIEVAL_WORKERS = 1
EMBEDDING_INPUT_MAX_CHARS = 8_000
EMBEDDING_BATCH_MAX_CHARS = 32_000
EMBEDDING_FRAGMENT_OVERLAP = 200
EMBEDDING_RATE_LIMIT_RETRIES = 4
EMBEDDING_RATE_LIMIT_DELAY_SECONDS = 5.0
EMBEDDING_RATE_LIMIT_MAX_DELAY_SECONDS = 60.0
_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)
_STATE_TTL = 7 * 24 * 60 * 60
_RETRIEVAL_STRATEGIES = frozenset({"keyword", "vector", "hybrid"})


class OpenRagDatasetError(RuntimeError):
    pass


def _state_path(spec: DatasetSpec) -> Path:
    return spec.cache_path / "state.json"


def _index_path(spec: DatasetSpec) -> Path:
    return spec.cache_path / "index.sqlite3"


def _embedding_checkpoint_path(spec: DatasetSpec) -> Path:
    return spec.cache_path / "embedding-checkpoint.sqlite3"


def _state_cache_key(spec: DatasetSpec) -> str:
    return f"open-rag:{spec.cache_dataset_id}:{spec.version}"


@contextmanager
def open_rag_prepare_lock(spec: DatasetSpec, *, blocking: bool):
    """Serialize task creation and cache mutation across local worker processes."""
    import fcntl

    spec.cache_path.mkdir(parents=True, exist_ok=True)
    handle = (spec.cache_path / ".prepare.lock").open("a+")
    acquired = False
    try:
        flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
        try:
            fcntl.flock(handle.fileno(), flags)
            acquired = True
        except BlockingIOError:
            pass
        yield acquired
    finally:
        if acquired:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _set_state(spec: DatasetSpec, **values) -> dict:
    current = {}
    if _state_path(spec).exists():
        try:
            current = _read_json(_state_path(spec))
        except (OSError, ValueError):
            current = {}
    current.update(values)
    _write_json(_state_path(spec), current)
    cache.set(_state_cache_key(spec), current, timeout=_STATE_TTL)
    return current


def mark_open_dataset_queued(spec: DatasetSpec) -> dict:
    return _set_state(
        spec,
        status="queued",
        progress=0,
        revision=spec.revision,
        manifest_sha256=spec.artifact_manifest_sha256,
        error="",
        message="",
    )


def _index_fingerprint(path: Path) -> dict:
    stat = path.stat()
    return {"index_size": stat.st_size, "index_mtime_ns": stat.st_mtime_ns}


def _full_integrity_check(path: Path) -> bool:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    finally:
        connection.close()


def _cache_artifacts_verified(spec: DatasetSpec) -> bool:
    try:
        if not _index_path(spec).is_file():
            return False
        for name in CORE_FILES:
            path = spec.cache_path / name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != spec.files[name]:
                return False
        connection = sqlite3.connect(f"file:{_index_path(spec)}?mode=ro", uri=True)
        try:
            metadata = dict(connection.execute("SELECT key, value FROM metadata").fetchall())
            vector_table_exists = bool(connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'section_vectors'"
            ).fetchone())
        finally:
            connection.close()
        state = _read_json(_state_path(spec)) if _state_path(spec).is_file() else {}
        fingerprint = _index_fingerprint(_index_path(spec))
        integrity_verified = (
            state.get("index_integrity") == "ok"
            and state.get("index_size") == fingerprint["index_size"]
            and state.get("index_mtime_ns") == fingerprint["index_mtime_ns"]
        )
        if not integrity_verified:
            if not _full_integrity_check(_index_path(spec)):
                return False
            _set_state(spec, index_integrity="ok", **fingerprint)
        from .model_providers import active_embedding_config

        embedding_config = active_embedding_config(None)
        vector_ready = True
        if embedding_config:
            expected_signature = (
                f"{embedding_config.get('model', '')}:"
                f"{int(embedding_config.get('dimension') or 0)}"
            )
            vector_ready = (
                metadata.get("vector_status") == "ready"
                and metadata.get("embedding_signature") == expected_signature
                and vector_table_exists
            )
        return (
            metadata.get("revision") == spec.revision
            and metadata.get("manifest_sha256") == spec.artifact_manifest_sha256
            and vector_ready
        )
    except (OSError, sqlite3.Error, ValueError):
        return False


def _task_matches_shared_artifacts(spec: DatasetSpec, payload) -> bool:
    payload = payload if isinstance(payload, dict) else {}
    return (
        payload.get("dataset_id") in {
            "open_rag_benchmark",
            "open_rag_benchmark_180",
            "open_rag_benchmark_100",
            "open_rag_benchmark_full",
        }
        and payload.get("dataset_version") == spec.version
    )


def _active_task(spec: DatasetSpec):
    from .models import TaskRecord

    records = TaskRecord.objects.filter(
        task_type=TASK_TYPE,
        status__in=("pending", "running"),
    ).only("id", "status", "progress", "payload", "error_message", "created_at", "updated_at").order_by("-created_at")
    for record in records:
        if _task_matches_shared_artifacts(spec, record.payload):
            return record
    return None


def _latest_task(spec: DatasetSpec):
    from .models import TaskRecord

    records = TaskRecord.objects.filter(task_type=TASK_TYPE).only(
        "id", "status", "progress", "payload", "error_message", "created_at", "updated_at"
    ).order_by("-created_at")
    for record in records:
        if _task_matches_shared_artifacts(spec, record.payload):
            return record
    return None


def open_dataset_status(spec: DatasetSpec) -> dict:
    state = cache.get(_state_cache_key(spec))
    if not isinstance(state, dict) and _state_path(spec).exists():
        try:
            state = _read_json(_state_path(spec))
        except (OSError, ValueError):
            state = {}
    state = state if isinstance(state, dict) else {}
    try:
        active = _active_task(spec)
        latest = _latest_task(spec)
    except Exception:
        # Status polling must still work in management commands and degraded workers.
        active = None
        latest = None
    verified = _cache_artifacts_verified(spec)
    vector_ready = False
    if verified:
        try:
            connection = sqlite3.connect(f"file:{_index_path(spec)}?mode=ro", uri=True)
            metadata = dict(connection.execute("SELECT key, value FROM metadata").fetchall())
            vector_ready = (
                metadata.get("vector_status") == "ready"
                and bool(connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'section_vectors'"
                ).fetchone())
            )
            connection.close()
        except sqlite3.Error:
            vector_ready = False
    if verified:
        status = "ready"
    elif active:
        active_status = str(state.get("status") or "")
        status = active_status if active_status in {"queued", "downloading", "indexing"} else ("queued" if active.status == "pending" else "downloading")
    elif latest and latest.status == "failed" and "unsupported task type" not in str(latest.error_message or ""):
        status = "failed"
    else:
        state_status = str(state.get("status") or "")
        status = "stale" if state_status == "ready" else state_status or "not_ready"
    return {
        "status": status,
        "ready": verified,
        "progress": 1.0 if verified else float(state.get("progress", 0)),
        "task_id": "" if verified else (
            str(active.id) if active else str(state.get("task_id") or "")
        ),
        "message": "" if verified else str(state.get("message") or ""),
        "error": "" if verified else str(state.get("error") or (latest.error_message if latest and latest.status == "failed" else "")),
        "verified": verified,
        "capabilities": {"keyword": verified, "vector": vector_ready, "hybrid": verified and vector_ready},
    }


def dataset_metadata(spec: DatasetSpec) -> dict:
    status = open_dataset_status(spec)
    return {
        "id": spec.dataset_id,
        "version": spec.version,
        "label": spec.label,
        "count": spec.expected_queries,
        "documents": spec.expected_documents,
        "license": spec.license,
        "source_url": spec.source_url,
        "ready": bool(status.get("ready")),
        "verified": bool(status.get("verified")),
        "status": status.get("status", "not_ready"),
        "progress": float(status.get("progress", 0)),
        "task_id": str(status.get("task_id") or ""),
        "message": status.get("message", ""),
        "error": status.get("error", ""),
        "capabilities": status.get("capabilities", {}),
        "provenance": {
            "manifest_sha256": spec.sha256,
            "artifact_manifest_sha256": spec.artifact_manifest_sha256,
            "revision": spec.revision,
            "corpus_tree_oid": spec.corpus_tree_oid,
            "core_files": dict(spec.files),
        },
    }


def _request_json(url: str):
    request = Request(url, headers={"User-Agent": "Django-Agent/OpenRAGEvaluator"})
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _git_blob_oid(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def _download(url: str, path: Path, expected_sha256: str = "", expected_git_oid: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    digest = hashlib.sha256()
    request = Request(url, headers={"User-Agent": "Django-Agent/OpenRAGEvaluator"})
    with urlopen(request, timeout=120) as response, temporary.open("wb") as output:
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
            output.write(block)
    actual = digest.hexdigest()
    if expected_sha256 and actual != expected_sha256:
        temporary.unlink(missing_ok=True)
        raise OpenRagDatasetError(f"checksum mismatch for {path.name}")
    if expected_git_oid and _git_blob_oid(temporary) != expected_git_oid:
        temporary.unlink(missing_ok=True)
        raise OpenRagDatasetError(f"Git blob checksum mismatch for {path.name}")
    temporary.replace(path)


def _corpus_files(spec: DatasetSpec) -> list[tuple[str, str]]:
    tree_url = f"https://huggingface.co/api/datasets/{spec.repository}/tree/{spec.revision}"
    base_entries = _request_json(f"{tree_url}/{spec.base_path}?recursive=false")
    corpus_entry = next(
        (
            item for item in base_entries
            if item.get("type") == "directory" and item.get("path") == f"{spec.base_path}/corpus"
        ),
        None,
    )
    if not corpus_entry or corpus_entry.get("oid") != spec.corpus_tree_oid:
        raise OpenRagDatasetError("Open RAG corpus tree hash mismatch")
    payload = _request_json(f"{tree_url}/{spec.base_path}/corpus?recursive=false")
    files = sorted(
        (item["path"], item["oid"])
        for item in payload
        if item.get("type") == "file"
        and item.get("path", "").startswith(f"{spec.base_path}/corpus/")
        and item.get("path", "").endswith(".json")
        and item.get("oid")
    )
    if len(files) != spec.expected_documents:
        raise OpenRagDatasetError(f"expected {spec.expected_documents} corpus documents, got {len(files)}")
    return files


def _update_task_progress(spec: DatasetSpec, progress: float) -> None:
    try:
        task = _active_task(spec)
        if task:
            task.progress = progress
            task.save(update_fields=["progress", "updated_at"])
    except Exception:
        logger.debug("Unable to update Open RAG task progress", exc_info=True)


def _section_content(section: dict) -> str:
    pieces = [str(section.get("text") or "").strip()]
    tables = section.get("tables") or {}
    if isinstance(tables, str):
        try:
            tables = json.loads(tables)
        except ValueError:
            tables = {"table": tables}
    if isinstance(tables, dict):
        pieces.extend(str(value).strip() for value in tables.values() if str(value).strip())
    images = section.get("images") or {}
    if isinstance(images, dict) and images:
        pieces.append("[embedded images: " + ", ".join(sorted(map(str, images))) + "]")
    return "\n\n".join(piece for piece in pieces if piece)


def _load_corpus_documents(spec: DatasetSpec) -> list[dict]:
    corpus = spec.cache_path / "corpus"
    documents = []
    for path in sorted(corpus.glob("*.json")):
        payload = _read_json(path)
        if not isinstance(payload, dict) or not payload.get("id") or not isinstance(payload.get("sections"), list):
            raise OpenRagDatasetError(f"invalid corpus document: {path.name}")
        documents.append(payload)
    if len(documents) != spec.expected_documents:
        raise OpenRagDatasetError(f"expected {spec.expected_documents} corpus documents, got {len(documents)}")
    return documents


def _load_sqlite_vec(conn):
    try:
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True, ""
    except Exception as exc:
        try:
            conn.enable_load_extension(False)
        except Exception:
            pass
        return False, f"sqlite_vec_unavailable:{type(exc).__name__}"


def _embedding_fragments(text: str, max_chars: int) -> list[str]:
    value = str(text or "").strip()
    if not value:
        return []
    if len(value) <= max_chars:
        return [value]
    fragments = []
    start = 0
    while start < len(value):
        end = min(start + max_chars, len(value))
        if end < len(value):
            minimum_boundary = start + max_chars // 2
            candidates = [
                value.rfind("\n\n", minimum_boundary, end),
                value.rfind("\n", minimum_boundary, end),
                value.rfind(". ", minimum_boundary, end),
                value.rfind(" ", minimum_boundary, end),
            ]
            boundary = max(candidates)
            if boundary >= minimum_boundary:
                end = boundary + (2 if value[boundary:boundary + 2] in {"\n\n", ". "} else 1)
        fragment = value[start:end].strip()
        if fragment:
            fragments.append(fragment)
        if end >= len(value):
            break
        start = max(end - min(EMBEDDING_FRAGMENT_OVERLAP, max_chars // 8), start + 1)
    return fragments


def _is_rate_limited(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    message = str(exc).lower()
    return status_code == 429 or "rate limit" in message or "tpm limit" in message


def _retry_after_seconds(exc: Exception) -> float | None:
    headers = getattr(getattr(exc, "response", None), "headers", None) or getattr(exc, "headers", None)
    value = headers.get("Retry-After") if hasattr(headers, "get") else None
    if value is None:
        value = getattr(exc, "retry_after", None)
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(str(value))
            return max(0.0, retry_at.timestamp() - time.time())
        except (TypeError, ValueError, OverflowError):
            return None


def _request_embedding_batch(tenant, texts: list[str], config: dict) -> list[list[float]]:
    from .model_providers import embedding

    retries = max(0, min(int(config.get("rate_limit_retries") or EMBEDDING_RATE_LIMIT_RETRIES), 8))
    initial_delay = max(
        0.0,
        min(float(config.get("rate_limit_delay_seconds") or EMBEDDING_RATE_LIMIT_DELAY_SECONDS), 300.0),
    )
    for attempt in range(retries + 1):
        try:
            return embedding(tenant, texts)
        except Exception as exc:
            if not _is_rate_limited(exc) or attempt >= retries:
                raise
            retry_after = _retry_after_seconds(exc)
            delay = retry_after if retry_after is not None else initial_delay * (2 ** attempt)
            delay = min(EMBEDDING_RATE_LIMIT_MAX_DELAY_SECONDS, delay)
            time.sleep(delay)
    raise OpenRagDatasetError("embedding request retry loop ended unexpectedly")


def _embed_batches(tenant, texts: list[str], config: dict, progress_callback=None) -> list[list[float]]:
    batch_size = max(1, min(int(config.get("batch_size") or 32), 256))
    max_input_chars = max(512, min(int(config.get("max_input_chars") or EMBEDDING_INPUT_MAX_CHARS), 32_000))
    max_batch_chars = max(
        max_input_chars,
        min(int(config.get("max_batch_chars") or EMBEDDING_BATCH_MAX_CHARS), 256_000),
    )
    flattened = [
        (text_index, fragment)
        for text_index, value in enumerate(texts)
        for fragment in _embedding_fragments(value, max_input_chars)
    ]
    accumulated: list[list[float] | None] = [None] * len(texts)
    counts = [0] * len(texts)
    embedded_fragments = 0

    def flush(batch: list[tuple[int, str]]) -> None:
        nonlocal embedded_fragments
        if not batch:
            return
        batch_vectors = _request_embedding_batch(
            tenant,
            [fragment for _text_index, fragment in batch],
            config,
        )
        for (text_index, _fragment), vector in zip(batch, batch_vectors, strict=True):
            if accumulated[text_index] is None:
                accumulated[text_index] = [float(value) for value in vector]
            else:
                if len(accumulated[text_index]) != len(vector):
                    raise OpenRagDatasetError("embedding fragment dimension mismatch")
                for index, value in enumerate(vector):
                    accumulated[text_index][index] += float(value)
            counts[text_index] += 1
        embedded_fragments += len(batch)
        if progress_callback:
            progress_callback(embedded_fragments / max(len(flattened), 1))

    batch: list[tuple[int, str]] = []
    batch_chars = 0
    for item in flattened:
        item_chars = len(item[1])
        if batch and (len(batch) >= batch_size or batch_chars + item_chars > max_batch_chars):
            flush(batch)
            batch = []
            batch_chars = 0
        batch.append(item)
        batch_chars += item_chars
    flush(batch)

    vectors = []
    for total, count in zip(accumulated, counts, strict=True):
        if total is None or count == 0:
            raise OpenRagDatasetError("empty section cannot be embedded")
        vectors.append([value / count for value in total])
    return vectors


def _embedding_signature(config: dict) -> str:
    return f"{config.get('model', '')}:{int(config.get('dimension') or 0)}"


def _section_content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _load_or_embed_section_vectors(
    spec: DatasetSpec,
    section_texts: list[tuple[int, str]],
    config: dict,
    progress_callback=None,
) -> list[list[float]]:
    """Resume section embeddings from a durable model/content-addressed cache."""
    spec.cache_path.mkdir(parents=True, exist_ok=True)
    signature = _embedding_signature(config)
    checkpoint = sqlite3.connect(_embedding_checkpoint_path(spec))
    checkpoint.execute(
        "CREATE TABLE IF NOT EXISTS embeddings ("
        "model_signature TEXT NOT NULL, content_hash TEXT NOT NULL, dimension INTEGER NOT NULL, "
        "embedding TEXT NOT NULL, updated_at REAL NOT NULL, "
        "PRIMARY KEY (model_signature, content_hash))"
    )
    checkpoint.commit()
    content_by_hash: dict[str, str] = {}
    ordered_hashes = []
    for _row_id, content in section_texts:
        content_hash = _section_content_hash(content)
        ordered_hashes.append(content_hash)
        content_by_hash.setdefault(content_hash, content)

    cached = {}
    if content_by_hash:
        placeholders = ",".join("?" for _ in content_by_hash)
        rows = checkpoint.execute(
            f"SELECT content_hash, dimension, embedding FROM embeddings "
            f"WHERE model_signature = ? AND content_hash IN ({placeholders})",
            (signature, *content_by_hash),
        ).fetchall()
        for content_hash, dimension, payload in rows:
            try:
                vector = [float(value) for value in json.loads(payload)]
            except (TypeError, ValueError):
                continue
            if vector and len(vector) == int(dimension):
                cached[content_hash] = vector

    missing = [(content_hash, content) for content_hash, content in content_by_hash.items() if content_hash not in cached]
    batch_size = max(1, min(int(config.get("checkpoint_batch_size") or config.get("batch_size") or 32), 256))
    completed = len(content_by_hash) - len(missing)
    total = len(content_by_hash)
    if progress_callback:
        progress_callback(completed / total if total else 1.0)
    try:
        for start in range(0, len(missing), batch_size):
            batch = missing[start:start + batch_size]
            vectors = _embed_batches(None, [content for _content_hash, content in batch], config)
            if len(vectors) != len(batch):
                raise OpenRagDatasetError("embedding checkpoint batch size mismatch")
            for (content_hash, _content), vector in zip(batch, vectors, strict=True):
                normalized = [float(value) for value in vector]
                expected_dimension = int(config.get("dimension") or 0)
                if not normalized or (expected_dimension and len(normalized) != expected_dimension):
                    raise OpenRagDatasetError("embedding checkpoint dimension mismatch")
                checkpoint.execute(
                    "INSERT OR REPLACE INTO embeddings "
                    "(model_signature, content_hash, dimension, embedding, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (signature, content_hash, len(normalized), json.dumps(normalized), time.time()),
                )
                cached[content_hash] = normalized
            checkpoint.commit()
            completed += len(batch)
            if progress_callback:
                progress_callback(completed / total if total else 1.0)
    finally:
        checkpoint.close()
    return [cached[content_hash] for content_hash in ordered_hashes]


def _update_indexing_progress(spec: DatasetSpec, completed_fraction: float) -> None:
    progress = 0.82 + 0.17 * max(0.0, min(float(completed_fraction), 1.0))
    _set_state(
        spec,
        status="indexing",
        progress=progress,
        revision=spec.revision,
        manifest_sha256=spec.artifact_manifest_sha256,
        error="",
    )
    _update_task_progress(spec, progress)


def _build_index(spec: DatasetSpec, tenant_id: str = "") -> dict:
    path = _index_path(spec)
    temporary = path.with_suffix(".sqlite3.part")
    temporary.unlink(missing_ok=True)
    conn = sqlite3.connect(temporary)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE sections (id INTEGER PRIMARY KEY, doc_id TEXT, section_id TEXT, title TEXT, content TEXT NOT NULL)")
    conn.execute("CREATE VIRTUAL TABLE section_fts USING fts5(title, content, content='sections', content_rowid='id')")
    row_id = 1
    section_texts = []
    for document in _load_corpus_documents(spec):
        for section in document["sections"]:
            content = _section_content(section if isinstance(section, dict) else {})
            if not content:
                continue
            conn.execute(
                "INSERT INTO sections(id, doc_id, section_id, title, content) VALUES (?, ?, ?, ?, ?)",
                (row_id, str(document["id"]), str(section.get("section_id", row_id - 1)), str(document.get("title") or ""), content),
            )
            section_texts.append((row_id, content))
            row_id += 1
    conn.execute("INSERT INTO section_fts(section_fts) VALUES ('rebuild')")
    conn.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute(
        "INSERT INTO metadata(key, value) VALUES ('revision', ?), ('manifest_sha256', ?)",
        (spec.revision, spec.artifact_manifest_sha256),
    )
    vector_status = "unavailable"
    vector_reason = "embedding_not_configured"
    try:
        from .model_providers import active_embedding_config

        config = active_embedding_config(None)
        if config:
            vectors = _load_or_embed_section_vectors(spec, section_texts, config, lambda value: _update_indexing_progress(spec, value))
            dimension = len(vectors[0]) if vectors else 0
            if dimension:
                loaded, load_reason = _load_sqlite_vec(conn)
                if not loaded:
                    raise OpenRagDatasetError(load_reason)
                else:
                    conn.execute(
                        f"CREATE VIRTUAL TABLE section_vectors USING vec0(section_row_id integer primary key, embedding float[{dimension}])"
                    )
                    conn.executemany(
                        "INSERT INTO section_vectors(section_row_id, embedding) VALUES (?, ?)",
                        [(row_id, json.dumps(vector)) for (row_id, _content), vector in zip(section_texts, vectors, strict=True)],
                    )
                    conn.execute(
                        "INSERT INTO metadata(key, value) VALUES ('embedding_signature', ?), ('embedding_dimension', ?)",
                        (_embedding_signature({**config, "dimension": dimension}), str(dimension)),
                    )
                    vector_status = "ready"
                    vector_reason = ""
        else:
            vector_reason = "embedding_not_configured"
    except Exception as exc:
        logger.warning("Open RAG vector index build failed", exc_info=True)
        conn.rollback()
        conn.close()
        temporary.unlink(missing_ok=True)
        message = "Open RAG embedding rate limit reached" if _is_rate_limited(exc) else "Open RAG embedding index build failed"
        raise OpenRagDatasetError(message) from exc
    conn.execute("INSERT INTO metadata(key, value) VALUES ('vector_status', ?), ('vector_reason', ?)", (vector_status, vector_reason))
    conn.commit()
    conn.close()
    if not _full_integrity_check(temporary):
        temporary.unlink(missing_ok=True)
        raise OpenRagDatasetError("Open RAG index integrity check failed")
    temporary.replace(path)
    return {"index_integrity": "ok", **_index_fingerprint(path)}


def _reconcile_pending_prepare_tasks(spec: DatasetSpec) -> None:
    try:
        from django.utils import timezone

        from .models import TaskRecord

        result = {
            "status": "ready",
            "ready": True,
            "documents": spec.expected_documents,
            "queries": spec.artifact_expected_queries,
        }
        records = TaskRecord.objects.filter(task_type=TASK_TYPE, status="pending").only("id", "payload")
        for record in records:
            if _task_matches_shared_artifacts(spec, record.payload):
                TaskRecord.objects.filter(id=record.id, status="pending").update(
                    status="completed",
                    progress=1,
                    result=result,
                    error_message="",
                    updated_at=timezone.now(),
                )
    except Exception:
        logger.debug("Unable to reconcile stale Open RAG prepare tasks", exc_info=True)


def _ready_result(spec: DatasetSpec) -> dict:
    return {
        "status": "ready",
        "ready": True,
        "documents": spec.expected_documents,
        "queries": spec.expected_queries,
    }


def prepare_open_rag_dataset(spec: DatasetSpec, tenant_id: str = "", lock_already_held: bool = False) -> dict:
    """Download and build the global read-only index for a pinned dataset."""
    if not lock_already_held:
        with open_rag_prepare_lock(spec, blocking=True):
            return prepare_open_rag_dataset(spec, tenant_id, lock_already_held=True)
    root = spec.cache_path
    root.mkdir(parents=True, exist_ok=True)
    if _cache_artifacts_verified(spec):
        _set_state(
            spec,
            status="ready",
            progress=1,
            revision=spec.revision,
            manifest_sha256=spec.artifact_manifest_sha256,
            documents=spec.expected_documents,
            queries=spec.artifact_expected_queries,
            error="",
            message="",
        )
        _reconcile_pending_prepare_tasks(spec)
        return _ready_result(spec)
    _set_state(
        spec,
        status="downloading",
        progress=0.05,
        revision=spec.revision,
        manifest_sha256=spec.artifact_manifest_sha256,
        error="",
    )
    try:
        for index, name in enumerate(CORE_FILES, start=1):
            target = root / name
            if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != spec.files[name]:
                url = f"https://huggingface.co/datasets/{spec.repository}/resolve/{spec.revision}/{spec.base_path}/{name}"
                _download(url, target, spec.files[name])
            _set_state(spec, status="downloading", progress=0.05 + index * 0.04)
        files = _corpus_files(spec)
        corpus_root = root / "corpus"
        corpus_root.mkdir(parents=True, exist_ok=True)

        def fetch(file_entry):
            relative, expected_oid = file_entry
            filename = relative.rsplit("/", 1)[-1]
            target = corpus_root / filename
            if not target.exists() or _git_blob_oid(target) != expected_oid:
                _download(
                    f"https://huggingface.co/datasets/{spec.repository}/resolve/{spec.revision}/{relative}",
                    target,
                    expected_git_oid=expected_oid,
                )

        with ThreadPoolExecutor(max_workers=8) as executor:
            for index, _ in enumerate(executor.map(fetch, files), start=1):
                if index == len(files) or index % 25 == 0:
                    _set_state(spec, status="downloading", progress=0.22 + 0.58 * index / len(files))
        _set_state(spec, status="indexing", progress=0.82)
        index_state = _build_index(spec, tenant_id)
        _set_state(
            spec,
            status="ready",
            progress=1,
            documents=len(files),
            queries=spec.artifact_expected_queries,
            **index_state,
        )
        _reconcile_pending_prepare_tasks(spec)
        return _ready_result(spec)
    except Exception as exc:
        logger.exception("Open RAG dataset preparation failed")
        _set_state(spec, status="failed", progress=0, error=str(exc), message="Open RAG dataset preparation failed")
        raise
    finally:
        close_old_connections()


def _payloads(spec: DatasetSpec) -> tuple[dict, dict, dict]:
    if not open_dataset_status(spec)["ready"]:
        raise OpenRagDatasetError("Open RAG dataset is not ready")
    queries = _read_json(spec.cache_path / "queries.json")
    qrels = _read_json(spec.cache_path / "qrels.json")
    answers = _read_json(spec.cache_path / "answers.json")
    if not all(isinstance(value, dict) for value in (queries, qrels, answers)):
        raise OpenRagDatasetError("Open RAG core files are malformed")
    expected = spec.artifact_expected_queries
    if len(queries) != expected or len(qrels) != expected or len(answers) != expected:
        raise OpenRagDatasetError("Open RAG core file count mismatch")
    if spec.query_ids:
        available_ids = sorted(set(queries) & set(qrels) & set(answers))
        random.Random(int(spec.selection_seed or 0)).shuffle(available_ids)
        if tuple(available_ids[:len(spec.query_ids)]) != spec.query_ids:
            raise OpenRagDatasetError("Open RAG immutable subset manifest mismatch")
    return queries, qrels, answers


def sample_open_rag_questions(spec: DatasetSpec, sample_size: int = 20, seed: int = 0) -> list[dict]:
    queries, qrels, answers = _payloads(spec)
    size = max(1, min(int(sample_size or 20), MAX_SAMPLE_SIZE, spec.expected_queries))
    ids = list(spec.query_ids) if spec.query_ids else sorted(set(queries) & set(qrels) & set(answers))
    random.Random(int(seed)).shuffle(ids)
    selected = ids[:size]
    return [
        {
            "query_id": query_id,
            "query": queries[query_id].get("query", ""),
            "type": queries[query_id].get("type", ""),
            "source": queries[query_id].get("source", ""),
            "answer": answers[query_id],
            "qrel": qrels[query_id],
        }
        for query_id in selected
    ]


def _tokens(value: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(value or "") if len(token) > 1}


def _retrieval_strategy(value: str) -> str:
    strategy = str(value or "hybrid").lower()
    if strategy not in _RETRIEVAL_STRATEGIES:
        raise OpenRagDatasetError(f"unsupported Open RAG retrieval strategy: {strategy}")
    return strategy


def _query_embeddings(tenant, spec: DatasetSpec, queries: list[str], retrieval_strategy: str, progress_callback=None) -> list[list[float] | None]:
    """Embed a query batch once so retrieval and answer generation can share it."""
    strategy = _retrieval_strategy(retrieval_strategy)
    if strategy == "keyword":
        return [None] * len(queries)
    from .model_providers import active_embedding_config

    config = active_embedding_config(None)
    if not config:
        return [None] * len(queries)
    return _embed_batches(None, queries, config, progress_callback=progress_callback)


def search_open_rag(
    tenant,
    spec: DatasetSpec,
    query: str,
    top_k: int = 20,
    *,
    retrieval_strategy: str = "hybrid",
    query_vector: list[float] | None = None,
    rerank_enabled: bool = True,
) -> tuple[list[dict], dict]:
    strategy = _retrieval_strategy(retrieval_strategy)
    if not open_dataset_status(spec)["ready"]:
        raise OpenRagDatasetError("Open RAG dataset is not ready")
    conn = sqlite3.connect(_index_path(spec))
    keyword = []
    if strategy in {"keyword", "hybrid"}:
        terms = sorted(_tokens(query))
        match = " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms) or '""'
        keyword = conn.execute(
            "SELECT s.id, s.doc_id, s.section_id, s.title, s.content, bm25(section_fts) AS score "
            "FROM section_fts JOIN sections s ON s.id = section_fts.rowid WHERE section_fts MATCH ? ORDER BY score LIMIT ?",
            (match, max(top_k * 4, 40)),
        ).fetchall()
    vector = []
    vector_reason = ""
    if strategy in {"vector", "hybrid"}:
        try:
            from .model_providers import active_embedding_config, embedding

            config = active_embedding_config(None)
            has_vector_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'section_vectors'"
            ).fetchone()
            if config and has_vector_table:
                signature_row = conn.execute(
                    "SELECT value FROM metadata WHERE key = 'embedding_signature'"
                ).fetchone()
                expected_signature = f"{config.get('model', '')}:{int(config.get('dimension') or 0)}"
                if not signature_row or signature_row[0] != expected_signature:
                    vector_reason = "vector_index_model_mismatch"
                else:
                    loaded, load_reason = _load_sqlite_vec(conn)
                    if not loaded:
                        vector_reason = load_reason
                    else:
                        vector_query = query_vector if query_vector is not None else embedding(None, [query])[0]
                        vector = conn.execute(
                            "SELECT section_row_id, distance FROM section_vectors WHERE embedding MATCH ? AND k = ?",
                            (json.dumps(vector_query), max(top_k * 4, 40)),
                        ).fetchall()
            elif not config:
                vector_reason = "embedding_not_configured"
            else:
                vector_reason = "vector_index_unavailable"
        except Exception as exc:
            vector_reason = f"vector_search_failed:{type(exc).__name__}"
    conn.close()
    rows = {
        int(row[0]): {"id": int(row[0]), "doc_id": row[1], "section_id": str(row[2]), "title": row[3], "content": row[4], "score": 0.0}
        for row in keyword
    }
    keyword_ids = [int(row[0]) for row in keyword]
    vector_ids = [int(row[0]) for row in vector]
    if vector_ids:
        missing = [row_id for row_id in vector_ids if row_id not in rows]
        if missing:
            placeholders = ",".join("?" for _ in missing)
            vector_conn = sqlite3.connect(_index_path(spec))
            for row in vector_conn.execute(
                f"SELECT id, doc_id, section_id, title, content FROM sections WHERE id IN ({placeholders})", missing
            ).fetchall():
                rows[int(row[0])] = {"id": int(row[0]), "doc_id": row[1], "section_id": str(row[2]), "title": row[3], "content": row[4], "score": 0.0}
            vector_conn.close()
    if strategy in {"keyword", "hybrid"}:
        for rank, row_id in enumerate(keyword_ids, start=1):
            rows[row_id]["score"] += 1.0 / (60 + rank)
    if strategy in {"vector", "hybrid"}:
        for rank, row_id in enumerate(vector_ids, start=1):
            rows[row_id]["score"] += 1.0 / (60 + rank)
    meta = {
        "degradations": [],
        "keyword_candidates": len(keyword_ids),
        "vector_candidates": len(vector_ids),
        "rerank_model": "",
        "retrieval_strategy": strategy,
        "rrf_k": int(getattr(settings, "SEARCH_RRF_K", 60)),
        "candidate_limits": {"keyword": max(top_k * 4, 40), "vector": max(top_k * 4, 40), "rerank_input": max(top_k * 2, 40)},
        "vector_distance_metric": "l2",
        "index_scope": "prepared_full_corpus",
    }
    if strategy in {"keyword", "hybrid"} and not keyword_ids:
        meta["degradations"].append("keyword_no_match")
    if vector_reason:
        meta["degradations"].append(vector_reason)
    fused = sorted(rows.values(), key=lambda item: (-item["score"], item["id"]))
    if not rerank_enabled:
        meta["rerank_model"] = "disabled"
        return fused[:top_k], meta
    try:
        from .model_providers import active_rerank_config, rerank

        if active_rerank_config(tenant):
            # 生产语义：重排输入 2×top_k、不截断返回，未重排尾部按原顺序接回后再取 top_k
            reranked = rerank(query, fused[:40], top_k=None, tenant=tenant) + fused[40:]
            for item in reranked:
                item["score"] = float(item.get("rerank_score", item.get("score", 0)))
            meta["rerank_model"] = active_rerank_config(tenant)["model"]
            return reranked[:top_k], meta
        meta["degradations"].append("rerank_unavailable")
    except Exception as exc:
        meta["degradations"].append(f"rerank_failed:{type(exc).__name__}")
    return fused[:top_k], meta


def _retrieval_metrics(results: list[dict], qrel: dict) -> tuple[float, float, float]:
    relevant = (str(qrel.get("doc_id")), str(qrel.get("section_id")))
    ranks = [index for index, row in enumerate(results, start=1) if (str(row["doc_id"]), str(row["section_id"])) == relevant]
    hit = float(any(rank <= 10 for rank in ranks))
    mrr = 1.0 / ranks[0] if ranks and ranks[0] <= 10 else 0.0
    recall = float(any(rank <= 20 for rank in ranks))
    return hit, mrr, recall


def retrieve_open_rag_questions(
    tenant,
    spec: DatasetSpec,
    rows: list[dict],
    *,
    retrieval_strategy: str = "hybrid",
    top_k: int = 20,
    rerank_enabled: bool = True,
    cancel_callback=None,
    progress_callback=None,
    existing_results: dict[str, tuple[list[dict], dict]] | None = None,
) -> dict[str, tuple[list[dict], dict]]:
    """Return reusable Top-K results keyed by query id for one fixed sample."""
    strategy = _retrieval_strategy(retrieval_strategy)
    retrieved = dict(existing_results or {})
    pending_rows = [row for row in rows if row["query_id"] not in retrieved]
    total = len(rows) or 1
    if progress_callback:
        vectors = _query_embeddings(
            tenant, spec, [row["query"] for row in pending_rows], strategy,
            progress_callback=lambda ratio: progress_callback(max(1, int(ratio * 10)), total, retrieved),
        )
    else:
        vectors = _query_embeddings(tenant, spec, [row["query"] for row in pending_rows], strategy)
    completed = len(rows) - len(pending_rows)

    def retrieve_one(row, vector):
        try:
            if cancel_callback:
                cancel_callback()
            return row["query_id"], search_open_rag(
                tenant,
                spec,
                row["query"],
                top_k,
                retrieval_strategy=strategy,
                query_vector=vector,
                rerank_enabled=rerank_enabled,
            )
        finally:
            close_old_connections()

    # Search opens independent read-only SQLite connections. Keep concurrency
    # bounded because rerank and model-rate-limit calls are shared resources.
    worker_count = min(RETRIEVAL_WORKERS, max(1, len(pending_rows)))
    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="open-rag-retrieval") as executor:
        for batch_start in range(0, len(pending_rows), worker_count):
            batch = list(zip(
                pending_rows[batch_start:batch_start + worker_count],
                vectors[batch_start:batch_start + worker_count],
                strict=True,
            ))
            futures = [executor.submit(retrieve_one, row, vector) for row, vector in batch]
            for future in futures:
                query_id, result = future.result()
                retrieved[query_id] = result
                completed += 1
                if progress_callback and (completed % 20 == 0 or completed == len(rows)):
                    progress_callback(completed, total, retrieved)
    return retrieved


def run_open_rag_retrieval(
    tenant,
    spec: DatasetSpec,
    sample_size: int = 20,
    seed: int = 0,
    retrieval_strategy: str = "hybrid",
    retrieved_results: dict[str, tuple[list[dict], dict]] | None = None,
    rerank_enabled: bool = True,
) -> dict:
    rows = sample_open_rag_questions(spec, sample_size, seed)
    strategy = _retrieval_strategy(retrieval_strategy)
    retrieved = retrieved_results if retrieved_results is not None else retrieve_open_rag_questions(
        tenant,
        spec,
        rows,
        retrieval_strategy=strategy,
        top_k=20,
        rerank_enabled=rerank_enabled,
    )
    per_question = []
    degradations = []
    valid_rows = []
    for row in rows:
        results, meta = retrieved[row["query_id"]]
        row_degradations = [value for value in meta["degradations"] if value != "keyword_no_match"]
        degradations.extend(row_degradations)
        hit, mrr, recall = _retrieval_metrics(results, row["qrel"])
        item = {"query_id": row["query_id"], "query": row["query"], "hit_at_10": hit, "mrr_at_10": mrr, "recall_at_20": recall, "valid": True}
        if row_degradations:
            item["degradations"] = row_degradations
        valid_rows.append(item)
        per_question.append(item)
    count = len(valid_rows) or 1
    coverage = len(valid_rows) / len(per_question) if per_question else 0.0
    verification_status = "verified" if bool(valid_rows) and not degradations else ("degraded" if valid_rows else "unverified")
    return {
        "dataset_status": "verified" if verification_status == "verified" else "unverified",
        "verification_status": verification_status,
        "verified": verification_status == "verified",
        "dataset_id": spec.dataset_id,
        "dataset_version": spec.version,
        "hit_at_10_new": None if not valid_rows else sum(row["hit_at_10"] for row in valid_rows) / count,
        "mrr_new": None if not valid_rows else sum(row["mrr_at_10"] for row in valid_rows) / count,
        "recall_new": None if not valid_rows else sum(row["recall_at_20"] for row in valid_rows) / count,
        "questions": len(per_question),
        "failed_questions": len(per_question) - len(valid_rows),
        "valid_coverage": coverage,
        "per_question": per_question,
        "reasons": [{"code": "pipeline_degraded", "message": value} for value in sorted(set(degradations))],
        "pipeline": {
            "retriever": {"keyword": "fts5_bm25", "vector": "sqlite_vec", "hybrid": "fts5_bm25_sqlite_vec_rrf"}[strategy],
            "retrieval_strategy": strategy,
            "rerank_model": "configured" if not degradations else "unavailable",
            "requested": {"retrieval_strategy": strategy, "rerank_enabled": bool(rerank_enabled)},
            "effective": {"retrieval_strategy": strategy, "rerank_enabled": bool(rerank_enabled and not degradations)},
        },
    }


def _public_document_map(spec: DatasetSpec, document_ids: set[str] | None = None) -> dict[str, dict]:
    """Load source documents for an isolated evaluation index.

    ``document_ids`` is retained for the old qrel-only helper contract.  The
    new evaluation pipeline passes ``None`` and deliberately loads every
    corpus document, so a production Top-20 can never determine the corpus
    available to a comparison strategy.
    """
    documents = {}
    connection = sqlite3.connect(_index_path(spec))
    if document_ids is None:
        rows = connection.execute(
            "SELECT doc_id, section_id, title, content FROM sections ORDER BY doc_id, id"
        ).fetchall()
    elif not document_ids:
        connection.close()
        return documents
    else:
        placeholders = ",".join("?" for _ in document_ids)
        rows = connection.execute(
            f"SELECT doc_id, section_id, title, content FROM sections "
            f"WHERE doc_id IN ({placeholders}) ORDER BY doc_id, id",
            sorted(document_ids),
        ).fetchall()
    connection.close()
    grouped = {}
    for doc_id, section_id, title, content in rows:
        grouped.setdefault(str(doc_id), {"id": str(doc_id), "title": str(title or ""), "sections": []})[
            "sections"
        ].append({"section_id": str(section_id), "text": str(content or "")})
    for document in grouped.values():
        source_parts = []
        section_blocks = []
        sections = {}
        cursor = 0
        for index, raw_section in enumerate(document.get("sections") or []):
            section = raw_section if isinstance(raw_section, dict) else {}
            content = _section_content(section)
            if not content:
                continue
            if source_parts:
                cursor += 2
                source_parts.append("\n\n")
            start = cursor
            source_parts.append(content)
            cursor += len(content)
            sections[str(section.get("section_id", index))] = (start, cursor)
            section_blocks.append(content)
        documents[str(document["id"])] = {
            "id": str(document["id"]),
            "title": str(document.get("title") or ""),
            "source": "".join(source_parts),
            "sections": sections,
            "section_blocks": section_blocks,
        }
    return documents


def _draft_payload(draft, parents) -> dict:
    parent_index = getattr(draft, "context_parent_index", None)
    parent = parents[parent_index] if parent_index is not None and 0 <= parent_index < len(parents) else draft
    return {
        "start": draft.start_at,
        "end": draft.end_at,
        "context_start": parent.start_at,
        "context_end": parent.end_at,
        "content": draft.content,
    }


_PUBLIC_PRODUCTION_STRATEGY_ALIASES = {
    "recursive": "recursive",
    "auto_parent_child": "auto",
    "semantic_parent_child": "semantic",
    "heading": "heading",
    "layout": "layout",
    "record": "record",
}


def _public_chunks(document: dict, strategy: str, tenant=None) -> list[dict]:
    """公开数据集分块：与租户评测同源——生产策略统一走生产 split_document
    （父子块开启、生产默认参数），fixed_window 为门禁基线（非生产策略）。"""
    source = document["source"]
    if not source:
        return []
    if strategy == "fixed_window":
        from .document_processing import split_text

        return [
            {"start": start, "end": end, "context_start": start, "context_end": end, "content": content}
            for start, end, content in split_text(source, {"chunk_size": 512, "chunk_overlap": 80})
        ]
    production_strategy = _PUBLIC_PRODUCTION_STRATEGY_ALIASES.get(strategy)
    if production_strategy is None:
        return []
    from .chunking.config import ChunkingConfig
    from .chunking.service import split_document
    from .document_parsing.types import ParsedDocument, TextBlock
    from .model_providers import active_embedding_config, embedding

    config = active_embedding_config(tenant)
    parsed = ParsedDocument(text_blocks=[
        TextBlock(text=content, block_index=index, block_type="paragraph")
        for index, content in enumerate(document.get("section_blocks") or [source])
    ])
    semantic_options = {}
    if production_strategy == "semantic":
        semantic_options = {
            "semantic_embed": (lambda texts: embedding(tenant, texts)) if config else None,
            "semantic_model_signature": f"{config.get('model', '')}:{config.get('dimension', '')}" if config else "",
            "semantic_setup_error": "semantic_embedding_unavailable" if not config else "",
        }
    result = split_document(
        parsed,
        ChunkingConfig(strategy=production_strategy, enable_parent_child=True),
        title=document.get("title", ""),
        **semantic_options,
    )
    return [_draft_payload(draft, result.parents) for draft in result.children]


def _rank_public_chunks(chunks: list[dict], query: str) -> list[dict]:
    query_tokens = _tokens(query)
    ranked = []
    for chunk in chunks:
        content_tokens = _tokens(chunk["content"])
        score = len(query_tokens & content_tokens)
        if score:
            ranked.append((score, chunk))
    ranked.sort(key=lambda item: (-item[0], item[1]["start"], item[1]["end"]))
    return [chunk for _score, chunk in ranked]


def _build_public_chunk_index(chunks_by_document: dict[str, list[dict]]) -> dict:
    """Build a transient FTS5/BM25 index for one chunking strategy."""
    chunks = []
    chunks_by_doc = {}
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE VIRTUAL TABLE chunks_fts USING fts5(content)")
    for document_chunks in chunks_by_document.values():
        for chunk in document_chunks:
            chunks.append(chunk)
            chunks_by_doc.setdefault(str(chunk.get("doc_id") or ""), []).append(chunk)
            connection.execute(
                "INSERT INTO chunks_fts(rowid, content) VALUES (?, ?)",
                (len(chunks), chunk["content"]),
            )
    connection.commit()
    return {"chunks": chunks, "chunks_by_doc": chunks_by_doc, "connection": connection}


_ISOLATED_INDEX_CACHE: dict[tuple, dict] = {}


def _isolated_index_key(spec: DatasetSpec, strategy: str, retrieval_strategy: str, rerank_enabled: bool, tenant) -> tuple:
    from .model_providers import active_embedding_config, active_rerank_config

    embedding_config = active_embedding_config(tenant) if retrieval_strategy in {"vector", "hybrid"} or strategy == "semantic_parent_child" else None
    rerank_config = active_rerank_config(tenant) if rerank_enabled else None
    return (
        EVALUATION_INDEX_ALGORITHM_VERSION,
        spec.sha256,
        spec.version,
        str(strategy),
        str(retrieval_strategy),
        bool(rerank_enabled),
        int(getattr(settings, "SEARCH_RRF_K", 60)),
        str((embedding_config or {}).get("model_id") or (embedding_config or {}).get("model") or ""),
        str((rerank_config or {}).get("model_id") or (rerank_config or {}).get("model") or ""),
    )


def _build_isolated_strategy_index(
    tenant,
    spec: DatasetSpec,
    strategy: str,
    *,
    retrieval_strategy: str = "hybrid",
    rerank_enabled: bool = True,
    cancel_callback=None,
    progress_callback=None,
) -> dict:
    """Build one complete-corpus, strategy-specific read-only index."""
    strategy = str(strategy)
    retrieval_strategy = _retrieval_strategy(retrieval_strategy)
    key = _isolated_index_key(spec, strategy, retrieval_strategy, rerank_enabled, tenant)
    cached = _ISOLATED_INDEX_CACHE.get(key)
    if cached is not None:
        return cached
    started = time.perf_counter()
    documents = _public_document_map(spec, None)
    chunks_by_document = {}
    reasons = []
    ordered_documents = list(documents.items())
    for document_index, (document_id, document) in enumerate(ordered_documents, start=1):
        if cancel_callback:
            cancel_callback()
        try:
            chunks = _public_chunks(document, strategy, tenant)
            section_spans = document.get("sections") or {}
            normalized = []
            for chunk in chunks:
                item = {**chunk, "doc_id": str(document_id)}
                item.setdefault("id", f"{document_id}:{item.get('start', 0)}:{item.get('end', 0)}")
                section_id = ""
                for candidate_section, span in section_spans.items():
                    if item.get("context_start", item.get("start", 0)) < span[1] and item.get("context_end", item.get("end", 0)) > span[0]:
                        section_id = str(candidate_section)
                        break
                item["section_id"] = section_id
                normalized.append(item)
            chunks_by_document[str(document_id)] = normalized
        except Exception as exc:
            logger.warning("Open RAG isolated %s chunking failed for %s", strategy, document_id, exc_info=True)
            chunks_by_document[str(document_id)] = []
            reasons.append(f"{strategy}_failed:{type(exc).__name__}")
        if progress_callback:
            progress_callback(document_index / max(len(ordered_documents), 1), 1, 1, 1)
    index = _build_public_chunk_index(chunks_by_document)
    if strategy == "semantic_parent_child":
        from .model_providers import active_embedding_config

        if not active_embedding_config(tenant):
            reasons.append("semantic_model_required")
    index["strategy"] = strategy
    index["documents"] = documents
    index["reasons"] = sorted(set(reasons))
    index["index_bytes"] = sum(len(str(item.get("content") or "").encode("utf-8")) for item in index.get("chunks", []))
    index["build_duration_ms"] = (time.perf_counter() - started) * 1000.0
    index["vector_by_row"] = {}
    if retrieval_strategy in {"vector", "hybrid"}:
        from .model_providers import active_embedding_config

        embedding_config = active_embedding_config(tenant)
        if not embedding_config:
            index["reasons"].append("embedding_model_required")
        elif index["chunks"]:
            try:
                vectors = _embed_batches(tenant, [item["content"] for item in index["chunks"]], embedding_config)
                index["vector_by_row"] = {
                    row_id: vector for row_id, vector in zip(range(1, len(vectors) + 1), vectors, strict=True)
                }
            except Exception as exc:
                logger.warning("Open RAG isolated %s vector index failed", strategy, exc_info=True)
                index["reasons"].append(f"vector_index_failed:{type(exc).__name__}")
    _ISOLATED_INDEX_CACHE[key] = index
    return index


def _search_isolated_strategy_index(
    tenant,
    index: dict,
    query: str,
    *,
    retrieval_strategy: str = "hybrid",
    top_k: int = 20,
    rerank_enabled: bool = True,
    query_vector: list[float] | None = None,
) -> tuple[list[dict], dict]:
    """Search one isolated index with the production BM25/RRF/Rerank contract."""
    from .search import shared_rank_candidates

    strategy = _retrieval_strategy(retrieval_strategy)
    terms = sorted(_tokens(query))
    match = " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms) or '""'
    keyword_candidates = []
    if strategy in {"keyword", "hybrid"} and terms:
        for row_id, score in index["connection"].execute(
            "SELECT rowid, bm25(chunks_fts) AS score FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY score, rowid LIMIT ?",
            (match, max(top_k * 4, 40)),
        ).fetchall():
            chunk = index["chunks"][int(row_id) - 1]
            keyword_candidates.append({**chunk, "id": str(row_id), "score": float(score)})
    vector_candidates = []
    vector_reason = ""
    if strategy in {"vector", "hybrid"}:
        if index.get("reasons"):
            vector_reason = str(index["reasons"][0])
        else:
            try:
                from .model_providers import active_embedding_config

                config = active_embedding_config(tenant)
                if query_vector is None:
                    query_vector = _embed_batches(tenant, [query], config)[0]
                def distance(vector):
                    return sum((float(left) - float(right)) ** 2 for left, right in zip(query_vector, vector, strict=False))
                ranked_rows = sorted(index.get("vector_by_row", {}).items(), key=lambda item: (distance(item[1]), item[0]))[:max(top_k * 4, 40)]
                for row_id, vector in ranked_rows:
                    chunk = index["chunks"][int(row_id) - 1]
                    vector_candidates.append({**chunk, "id": str(row_id), "score": -distance(vector)})
            except Exception as exc:
                vector_reason = f"vector_search_failed:{type(exc).__name__}"
    fused = shared_rank_candidates(keyword_candidates, vector_candidates)
    meta = {
        "degradations": list(index.get("reasons") or []),
        "keyword_candidates": len(keyword_candidates),
        "vector_candidates": len(vector_candidates),
        "retrieval_strategy": strategy,
        "effective_retrieval_strategy": strategy,
        "rerank_model": "disabled" if not rerank_enabled else "",
        "index_scope": "full_corpus",
        "index_strategy": index.get("strategy", ""),
    }
    if vector_reason and vector_reason not in meta["degradations"]:
        meta["degradations"].append(vector_reason)
    if rerank_enabled:
        from .model_providers import active_rerank_config, rerank

        rerank_config = active_rerank_config(tenant)
        if not rerank_config:
            meta["degradations"].append("rerank_model_required")
        elif fused:
            try:
                reranked = rerank(query, fused[: max(top_k * 2, 40)], top_k=None, tenant=tenant)
                fused = reranked + fused[max(top_k * 2, 40):]
                meta["rerank_model"] = rerank_config.get("model", "")
            except Exception as exc:
                meta["degradations"].append(f"rerank_failed:{type(exc).__name__}")
                meta["rerank_effective"] = False
    meta.setdefault("rerank_requested", bool(rerank_enabled))
    meta.setdefault(
        "rerank_effective",
        bool(rerank_enabled and not any("rerank" in str(reason).lower() for reason in meta.get("degradations") or [])),
    )
    deduplicated = []
    seen_contexts = set()
    for item in fused:
        context_key = (
            str(item.get("doc_id") or ""),
            int(item.get("context_start", item.get("start", 0)) or 0),
            int(item.get("context_end", item.get("end", 0)) or 0),
        )
        if context_key in seen_contexts:
            continue
        seen_contexts.add(context_key)
        deduplicated.append(item)
    return deduplicated[:top_k], meta


def run_open_rag_strategy_retrieval(
    tenant,
    spec: DatasetSpec,
    strategy: str,
    sample_size: int = 20,
    seed: int = 0,
    *,
    retrieval_strategy: str = "hybrid",
    rerank_enabled: bool = True,
    cancel_callback=None,
    progress_callback=None,
) -> dict:
    """Retrieve the same questions independently from one strategy index."""
    rows = sample_open_rag_questions(spec, sample_size, seed)
    index = _build_isolated_strategy_index(
        tenant,
        spec,
        strategy,
        retrieval_strategy=retrieval_strategy,
        rerank_enabled=rerank_enabled,
        cancel_callback=cancel_callback,
        progress_callback=progress_callback,
    )
    retrieved = {}
    for position, row in enumerate(rows, start=1):
        if cancel_callback:
            cancel_callback()
        results, meta = _search_isolated_strategy_index(
            tenant,
            index,
            row["query"],
            retrieval_strategy=retrieval_strategy,
            top_k=20,
            rerank_enabled=rerank_enabled,
        )
        retrieved[row["query_id"]] = (results, meta)
        if progress_callback:
            progress_callback(position / max(len(rows), 1), 1, 1, 1)
    return {
        "strategy": str(strategy),
        "retrieved_results": retrieved,
        "documents": len(index.get("documents") or {}),
        "chunk_count": len(index.get("chunks") or []),
        "index_bytes": int(index.get("index_bytes") or 0),
        "build_duration_ms": float(index.get("build_duration_ms") or 0),
        "reasons": sorted(set(index.get("reasons") or [])),
        "index_scope": "full_corpus",
        "index_algorithm_version": EVALUATION_INDEX_ALGORITHM_VERSION,
    }


def _rank_public_chunk_index(index: dict, query: str) -> list[dict]:
    terms = sorted(_tokens(query))
    match = " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms) or '""'
    rows = index["connection"].execute(
        "SELECT rowid, bm25(chunks_fts) AS score FROM chunks_fts "
        "WHERE chunks_fts MATCH ? ORDER BY score, rowid",
        (match,),
    ).fetchall()
    return [index["chunks"][int(row_id) - 1] for row_id, _score in rows]


def _rank_public_chunks_from_retrieval(index: dict, document: dict, results: list[dict]) -> list[dict]:
    """Map the complete production ranking onto strategy chunks.

    ``document`` may be one document for the small helper contract, or a
    document map when evaluating a production Top-20. Keeping the original
    result order prevents a lower-ranked distractor from becoming rank 1
    after filtering to the qrel document.
    """
    chunks = index["chunks"]
    chunks_by_doc = index.get("chunks_by_doc")
    if chunks_by_doc is None:
        chunks_by_doc = {}
        for chunk in chunks:
            chunks_by_doc.setdefault(str(chunk.get("doc_id") or ""), []).append(chunk)
    if "sections" in document:
        documents = {str(document.get("id")): document}
    else:
        documents = {str(key): value for key, value in (document or {}).items()}
    ranked = []
    seen = set()
    for result in results:
        document_id = str(result.get("doc_id") or "")
        selected_document = documents.get(document_id)
        section_span = (selected_document or {}).get("sections", {}).get(str(result.get("section_id")))
        if not selected_document or not section_span:
            continue
        for chunk in chunks_by_doc.get(document_id, ()):
            key = (chunk["doc_id"], chunk["start"], chunk["end"], chunk["context_start"], chunk["context_end"])
            if key in seen:
                continue
            if chunk["context_start"] < section_span[1] and chunk["context_end"] > section_span[0]:
                seen.add(key)
                ranked.append(chunk)
    return ranked


def run_open_rag_chunking(
    tenant,
    spec: DatasetSpec,
    sample_size: int = 20,
    seed: int = 0,
    strategies=None,
    retrieved_results: dict | None = None,
    cancel_callback=None,
    progress_callback=None,
    *,
    isolated_full_corpus: bool = False,
    primary_strategy: str | None = None,
    strategy_retrievals: dict[str, dict] | None = None,
    retrieval_strategy: str = "hybrid",
    rerank_enabled: bool = True,
) -> dict:
    selected = tuple(str(value) for value in (strategies or ("fixed_window", "recursive", "auto_parent_child", "semantic_parent_child")))
    # Supplying the new primary/comparison contract opts into the complete
    # corpus isolated-index path; old callers without it retain their
    # one-release compatibility behavior.
    isolated_full_corpus = bool(isolated_full_corpus or primary_strategy is not None or strategy_retrievals is not None)
    allowed = {"fixed_window", "recursive", "auto_parent_child", "semantic_parent_child", "heading", "layout", "record"}
    if not selected or not set(selected).issubset(allowed) or len(selected) != len(set(selected)):
        empty = {name: {"mrr_at_10": None, "recall_at_20": None, "context_precision": None, "questions": 0, "per_question": [], "verification_status": "unverified", "verified": False} for name in selected}
        return {"dataset_status": "unverified", "verification_status": "unverified", "verified": False, "strategies": empty, "reasons": [{"code": "malformed_strategy", "message": "at least one unique supported chunking strategy is required"}]}
    rows = sample_open_rag_questions(spec, sample_size, seed)

    if isolated_full_corpus:
        """Evaluate every requested strategy against its own complete index."""
        strategy_retrievals = strategy_retrievals if isinstance(strategy_retrievals, dict) else {}
        output = {}
        all_reasons = []
        for strategy_index, strategy in enumerate(selected, start=1):
            if cancel_callback:
                cancel_callback()
            retrieval_payload = strategy_retrievals.get(strategy)
            if not isinstance(retrieval_payload, dict) or not isinstance(retrieval_payload.get("retrieved_results"), dict):
                retrieval_payload = run_open_rag_strategy_retrieval(
                    tenant,
                    spec,
                    strategy,
                    sample_size,
                    seed,
                    retrieval_strategy=retrieval_strategy,
                    rerank_enabled=rerank_enabled,
                    cancel_callback=cancel_callback,
                    progress_callback=progress_callback,
                )
            retrieved = retrieval_payload.get("retrieved_results") or {}
            reasons = list(retrieval_payload.get("reasons") or [])
            per_question = []
            for row in rows:
                if cancel_callback:
                    cancel_callback()
                raw = retrieved.get(row["query_id"])
                if not isinstance(raw, (list, tuple)) or len(raw) != 2:
                    reasons.append("retrieval_missing")
                    per_question.append({"query_id": row["query_id"], "mrr_at_10": None, "recall_at_20": None, "context_precision": None})
                    continue
                ranked, meta = raw
                reasons.extend(str(value) for value in (meta or {}).get("degradations", []))
                hit, mrr, recall = _retrieval_metrics(ranked or [], row["qrel"])
                relevant = [item for item in (ranked or []) if str(item.get("doc_id")) == str(row["qrel"].get("doc_id")) and str(item.get("section_id")) == str(row["qrel"].get("section_id"))]
                per_question.append({
                    "query_id": row["query_id"],
                    "mrr_at_10": mrr,
                    "recall_at_20": recall,
                    "context_precision": len(relevant) / len(ranked[:20]) if ranked else 0.0,
                    "hit_at_10": hit,
                    "returned_chunk_count": min(len(ranked or []), 20),
                    "returned_context_characters": sum(len(str(item.get("content") or "")) for item in (ranked or [])[:5]),
                })
            failed = sum(item["mrr_at_10"] is None for item in per_question)
            reasons = sorted(set(reasons))
            status = "verified" if not reasons and not failed and per_question else ("degraded" if per_question and not failed else "unverified")
            count = len(per_question) or 1
            valid = [item for item in per_question if item["mrr_at_10"] is not None]
            output[strategy] = {
                "mrr_at_10": sum(item["mrr_at_10"] for item in valid) / max(len(valid), 1) if valid else None,
                "recall_at_20": sum(item["recall_at_20"] for item in valid) / max(len(valid), 1) if valid else None,
                "context_precision": sum(item["context_precision"] for item in valid) / max(len(valid), 1) if valid else None,
                "chunk_count": int(retrieval_payload.get("chunk_count") or 0),
                "searchable_chunk_count": int(retrieval_payload.get("chunk_count") or 0),
                "questions": len(per_question),
                "failed_questions": failed,
                "valid_coverage": len(valid) / count,
                "per_question": per_question,
                "verification_status": status,
                "verified": status == "verified",
                "reasons": [{"code": "isolated_pipeline", "message": reason} for reason in reasons],
                "requested_pipeline": {"retrieval_strategy": retrieval_strategy, "rerank_enabled": bool(rerank_enabled)},
                "effective_pipeline": {"retrieval_strategy": retrieval_strategy, "rerank_enabled": bool(rerank_enabled), "index_scope": "full_corpus", "index_strategy": strategy},
                "retrieval_pipeline": "isolated_strategy_index",
                "resources": {
                    "chunk_count": int(retrieval_payload.get("chunk_count") or 0),
                    "index_bytes": int(retrieval_payload.get("index_bytes") or 0),
                    "build_duration_ms": float(retrieval_payload.get("build_duration_ms") or 0),
                    "index_scope": "full_corpus",
                },
            }
            all_reasons.extend(f"{strategy}:{reason}" for reason in reasons)
            if progress_callback:
                progress_callback(1, 1, strategy_index, len(selected))
        primary = primary_strategy or selected[0]
        comparisons = {strategy: value for strategy, value in output.items() if strategy != primary}
        primary_metrics = output.get(primary, {})
        any_usable = any(float(item.get("valid_coverage") or 0) > 0 for item in output.values())
        isolated_status = "verified" if not all_reasons and output else ("degraded" if any_usable else "unverified")
        return {
            "dataset_status": "verified" if isolated_status == "verified" else "unverified",
            "verification_status": isolated_status,
            "verified": bool(output) and not all_reasons,
            "primary_strategy": primary,
            "primary": primary_metrics,
            "comparisons": comparisons,
            "strategies": output,
            "reasons": [{"code": "isolated_pipeline", "message": reason} for reason in sorted(set(all_reasons))],
        }
    qrel_document_ids = {str(row["qrel"].get("doc_id")) for row in rows}
    if retrieved_results:
        for raw in retrieved_results.values():
            production_rows = raw[0] if isinstance(raw, (list, tuple)) and len(raw) == 2 else raw
            for result in production_rows or []:
                if isinstance(result, dict) and result.get("doc_id"):
                    qrel_document_ids.add(str(result["doc_id"]))
    documents = _public_document_map(spec, qrel_document_ids)
    missing_documents = qrel_document_ids - set(documents)
    try:
        from .model_providers import active_embedding_config

        semantic_available = bool(active_embedding_config(tenant))
    except Exception:
        semantic_available = False
    output = {}
    all_reasons = []
    for strategy_index, strategy in enumerate(selected, start=1):
        if cancel_callback:
            cancel_callback()
        reasons = []
        if missing_documents:
            reasons.append("missing_public_document")
        if strategy == "semantic_parent_child" and not semantic_available:
            reasons.append("semantic_embedding_unavailable")
        chunks_by_document = {}
        for document_index, (document_id, document) in enumerate(documents.items(), start=1):
            if cancel_callback:
                cancel_callback()
            try:
                chunks_by_document[document_id] = [
                    {**chunk, "doc_id": document_id}
                    for chunk in _public_chunks(document, strategy, tenant)
                ]
            except Exception as exc:
                logger.warning("Open RAG %s chunking failed for %s", strategy, document_id, exc_info=True)
                chunks_by_document[document_id] = []
                reasons.append(f"{strategy}_failed:{type(exc).__name__}")
            if progress_callback:
                progress_callback(
                    0.7 * document_index / max(len(documents), 1),
                    1,
                    strategy_index,
                    len(selected),
                )
        chunk_index = _build_public_chunk_index(chunks_by_document)
        per_question = []
        for row in rows:
            if cancel_callback:
                cancel_callback()
            document = documents.get(str(row["qrel"].get("doc_id")), {"source": "", "sections": {}})
            if retrieved_results is not None and row["query_id"] in retrieved_results:
                production_rows, _meta = retrieved_results[row["query_id"]]
                ranked = _rank_public_chunks_from_retrieval(chunk_index, documents, production_rows)[:20]
            else:
                ranked = _rank_public_chunk_index(chunk_index, row["query"])[:20]
            section_span = document.get("sections", {}).get(str(row["qrel"].get("section_id")))
            relevant = bool(section_span)
            if not relevant:
                reasons.append("missing_qrel_section")
            matches = [
                chunk for chunk in ranked
                if relevant
                and chunk["doc_id"] == str(row["qrel"].get("doc_id"))
                and chunk["context_start"] < section_span[1]
                and chunk["context_end"] > section_span[0]
            ]
            ranks = [index for index, chunk in enumerate(ranked, start=1) if chunk in matches]
            per_question.append({
                "query_id": row["query_id"],
                "mrr_at_10": 1.0 / ranks[0] if ranks and ranks[0] <= 10 else 0.0,
                "recall_at_20": 1.0 if matches else 0.0,
                "context_precision": len(matches) / len(ranked) if ranked else 0.0,
            })
            if progress_callback:
                progress_callback(
                    0.7 + 0.3 * len(per_question) / max(len(rows), 1),
                    1,
                    strategy_index,
                    len(selected),
                )
        count = len(per_question) or 1
        reasons = sorted(set(reasons))
        if reasons:
            for item in per_question:
                item.update({"mrr_at_10": None, "recall_at_20": None, "context_precision": None})
        output[strategy] = {
            "mrr_at_10": None if reasons else sum(item["mrr_at_10"] for item in per_question) / count,
            "recall_at_20": None if reasons else sum(item["recall_at_20"] for item in per_question) / count,
            "context_precision": None if reasons else sum(item["context_precision"] for item in per_question) / count,
            "chunk_count": len(chunk_index["chunks"]),
            "searchable_chunk_count": len(chunk_index["chunks"]),
            "questions": len(per_question),
            "per_question": per_question,
            "reasons": [{"code": "chunking_degraded", "message": reason} for reason in reasons],
            "retrieval_pipeline": "shared_production_top20" if retrieved_results is not None else "fts5_bm25",
        }
        chunk_index["connection"].close()
        all_reasons.extend(f"{strategy}:{reason}" for reason in reasons)
    return {
        "dataset_status": "verified" if not all_reasons else "unverified",
        "verified": bool(rows) and not all_reasons,
        "strategies": output,
        "reasons": [{"code": "chunking_degraded", "message": reason} for reason in sorted(set(all_reasons))],
    }


def _hydrate_open_rag_retrieved(spec: DatasetSpec, retrieved: dict) -> dict:
    missing_ids = set()
    for raw in (retrieved or {}).values():
        for item in ((raw[0] if isinstance(raw, (list, tuple)) and len(raw) == 2 else []) or []):
            if not isinstance(item, dict) or item.get("id") is None or "content" in item:
                continue
            try:
                missing_ids.add(int(item["id"]))
            except (TypeError, ValueError):
                # Strategy-isolated chunk IDs are not rows in the public
                # section index; the orchestrator rebuilds that strategy
                # index before resuming answer generation.
                continue
    sections = {}
    if missing_ids:
        placeholders = ",".join("?" for _ in missing_ids)
        connection = sqlite3.connect(_index_path(spec))
        sections = {
            int(row[0]): {"doc_id": row[1], "section_id": str(row[2]), "title": row[3], "content": row[4]}
            for row in connection.execute(
                f"SELECT id, doc_id, section_id, title, content FROM sections WHERE id IN ({placeholders})",
                list(missing_ids),
            )
        }
        connection.close()
    for raw in (retrieved or {}).values():
        if not isinstance(raw, (list, tuple)) or len(raw) != 2:
            continue
        for item in raw[0] or []:
            if isinstance(item, dict) and "content" not in item and item.get("id") is not None:
                item.update(sections.get(int(item["id"]), {}))
    return retrieved


def _bounded_contexts(
    results: list[dict],
    *,
    max_contexts: int = 5,
    per_context_chars: int = 2000,
    total_chars: int = 6000,
) -> list[str]:
    contexts = []
    remaining = max(0, int(total_chars))
    for item in results[:max(0, int(max_contexts))]:
        if remaining <= 0:
            break
        content = str(item.get("content") or "")[:min(per_context_chars, remaining)]
        if content:
            contexts.append(content)
            remaining -= len(content)
    return contexts


def generate_open_rag_answers(
    tenant,
    spec: DatasetSpec,
    sample_size: int = 20,
    seed: int = 0,
    eval_llm_model: str = "",
    retrieval_strategy: str = "hybrid",
    retrieved_results: dict[str, tuple[list[dict], dict]] | None = None,
    answer_model_id: str | None = None,
    rerank_enabled: bool = True,
    cancel_callback=None,
    progress_callback=None,
    existing_details: list[dict] | None = None,
) -> dict:
    from .model_providers import chat_completion

    rows = sample_open_rag_questions(spec, sample_size, seed)
    strategy = _retrieval_strategy(retrieval_strategy)
    retrieved = retrieved_results if retrieved_results is not None else retrieve_open_rag_questions(
        tenant,
        spec,
        rows,
        retrieval_strategy=strategy,
        top_k=20,
        rerank_enabled=rerank_enabled,
    )
    retrieved = _hydrate_open_rag_retrieved(spec, retrieved)
    details_by_id = {
        str(detail.get("query_id")): detail
        for detail in (existing_details or [])
        if isinstance(detail, dict) and detail.get("query_id")
    }
    degradations = []
    model_id = eval_llm_model if answer_model_id is None else answer_model_id

    for row in rows:
        existing = details_by_id.get(row["query_id"])
        if not existing or not existing.get("valid", True):
            continue
        results, _meta = retrieved[row["query_id"]]
        existing.setdefault("question", row["query"])
        existing.setdefault("ground_truth", str(row["answer"]))
        existing.setdefault("contexts", _bounded_contexts(results))

    def generate(row):
        if cancel_callback:
            cancel_callback()
        results, meta = retrieved[row["query_id"]]
        contexts = _bounded_contexts(results)
        context_text = "\n\n".join(contexts) or "没有找到相关信息"
        try:
            answer = chat_completion(
                tenant,
                [{"role": "system", "content": "根据给定论文上下文回答问题。"}, {"role": "user", "content": f"上下文：\n{context_text}\n\n问题：{row['query']}"}],
                model_id,
                max_tokens=1024,
                enable_thinking=False,
            )
            if not str(answer or "").strip():
                raise ValueError("Empty model response")
            return {"question": row["query"], "answer": answer, "contexts": contexts, "ground_truth": str(row["answer"]), "query_id": row["query_id"], "valid": True}, meta["degradations"]
        except Exception as exc:
            logger.warning("Open RAG answer generation failed for %s", row["query_id"], exc_info=True)
            return {"question": row["query"], "answer": "", "contexts": contexts, "ground_truth": str(row["answer"]), "query_id": row["query_id"], "valid": False, "error": f"answer_generation_failed:{type(exc).__name__}"}, [f"answer_generation_failed:{type(exc).__name__}"]

    pending_rows = [
        row for row in rows
        if row["query_id"] not in details_by_id
        or not details_by_id[row["query_id"]].get("valid", True)
    ]
    total = len(rows) or 1
    completed = sum(
        1 for row in rows
        if details_by_id.get(row["query_id"], {}).get("valid", False)
    )
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="open-rag-answer") as executor:
        for index, (detail, row_degradations) in enumerate(executor.map(generate, pending_rows), start=completed + 1):
            details_by_id[str(detail["query_id"])] = detail
            degradations.extend(row_degradations)
            if progress_callback and (index % 10 == 0 or index == len(rows)):
                ordered_partial = [details_by_id[row["query_id"]] for row in rows if row["query_id"] in details_by_id]
                progress_callback(index, total, ordered_partial)
    details = [details_by_id[row["query_id"]] for row in rows if row["query_id"] in details_by_id]
    valid_details = [detail for detail in details if detail.get("valid")]
    answer_status = "verified" if bool(valid_details) and len(valid_details) == len(details) and not degradations else ("degraded" if valid_details else "unverified")
    return {
        "dataset_status": "verified" if answer_status == "verified" else "unverified",
        "verification_status": answer_status,
        "verified": answer_status == "verified",
        "dataset_id": spec.dataset_id,
        "dataset_version": spec.version,
        "total_questions": len(details),
        "failed_questions": len(details) - len(valid_details),
        "valid_coverage": len(valid_details) / len(details) if details else 0.0,
        "details": details,
        "degradations": sorted(set(degradations)),
        "retrieved_results": retrieved,
        "pipeline": {"retrieval_strategy": strategy, "retrieval_top_k": 20, "answer_context_top_k": 5},
    }


def run_open_rag_evaluation(
    tenant,
    spec: DatasetSpec,
    sample_size: int = 20,
    seed: int = 0,
    eval_llm_model: str = "",
    retrieval_strategy: str = "hybrid",
    retrieved_results: dict[str, tuple[list[dict], dict]] | None = None,
    answer_result: dict | None = None,
    judge_model_id: str | None = None,
    progress_callback=None,
    cancel_callback=None,
    existing_scores: list[dict] | None = None,
) -> dict:
    from .ragas_adapter import RagasAdapterError, evaluate_dataset

    strategy = _retrieval_strategy(retrieval_strategy)
    answer_result = answer_result or generate_open_rag_answers(
        tenant, spec, sample_size, seed, eval_llm_model, retrieval_strategy, retrieved_results
    )
    saved_details = list(answer_result.get("details") or [])
    required_fields = {"question", "contexts", "ground_truth"}
    if not saved_details or any(not required_fields.issubset(detail) for detail in saved_details):
        saved_degradations = set(answer_result.get("degradations") or [])
        answer_result = generate_open_rag_answers(
            tenant=tenant,
            spec=spec,
            sample_size=sample_size,
            seed=seed,
            retrieval_strategy=strategy,
            retrieved_results=retrieved_results,
            existing_details=saved_details,
        )
        answer_result["degradations"] = sorted(
            saved_degradations | set(answer_result.get("degradations") or [])
        )
        if answer_result["degradations"]:
            answer_result["dataset_status"] = "unverified"
            answer_result["verified"] = False
    details = [detail for detail in (answer_result.get("details") or []) if detail.get("valid", True)]
    degradations = list(answer_result.get("degradations") or [])
    try:
        scores = evaluate_dataset(
            details,
            tenant,
            eval_llm_model if judge_model_id is None else judge_model_id,
            progress_callback=progress_callback,
            cancel_callback=cancel_callback,
            existing_scores=existing_scores,
        )
    except RagasAdapterError:
        raise
    from .ragas_adapter import is_usable_ragas_score

    valid_scores = []
    for detail, score in zip(details, scores, strict=True):
        if is_usable_ragas_score(score):
            detail.update(score)
            detail["ragas_valid"] = True
            valid_scores.append(score)
        else:
            detail["ragas_valid"] = False
            detail["ragas_error"] = str(score.get("error") or "ragas_score_invalid") if isinstance(score, dict) else "ragas_score_invalid"
        detail.pop("contexts", None)
        detail["answer"] = detail["answer"][:500]
    count = len(valid_scores) or 1
    expected_total = int(answer_result.get("total_questions") or len(scores) or 0)
    failed_questions = max(0, expected_total - len(valid_scores))
    if failed_questions:
        degradations.append(f"ragas_question_failed:{failed_questions}")
    ragas_status = "verified" if bool(valid_scores) and len(valid_scores) == expected_total and not degradations else ("degraded" if valid_scores else "unverified")
    return {
        "dataset_status": "verified" if ragas_status == "verified" else "unverified",
        "verification_status": ragas_status,
        "verified": ragas_status == "verified",
        "dataset_id": spec.dataset_id,
        "dataset_version": spec.version,
        "faithfulness": None if not valid_scores else sum(row["faithfulness"] for row in valid_scores) / count,
        "answer_relevancy": None if not valid_scores else sum(row["answer_relevancy"] for row in valid_scores) / count,
        "context_precision": None if not valid_scores else sum(row["context_precision"] for row in valid_scores) / count,
        "total_questions": expected_total,
        "failed_questions": failed_questions,
        "valid_coverage": len(valid_scores) / max(expected_total, 1),
        "details": details,
        "reasons": [{"code": "pipeline_degraded", "message": value} for value in sorted(set(degradations))],
        "pipeline": {"retrieval_strategy": strategy, "retrieval_top_k": 20, "answer_context_top_k": 5},
    }
