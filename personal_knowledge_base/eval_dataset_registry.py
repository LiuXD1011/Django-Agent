"""Immutable registry for public evaluation datasets."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings


_DATASET_DIR = Path(__file__).resolve().parent / "eval_datasets"
_MANIFEST_NAME = "open_rag_benchmark.manifest.json"
_SUBSET_MANIFEST_NAME = "open_rag_benchmark_180.manifest.json"
_CACHE_DATASET_ID = "open_rag_benchmark"
_FULL_DATASET_ID = "open_rag_benchmark_full"
_SUBSET_DATASET_ID = "open_rag_benchmark_180"
_SUBSET_COMPATIBILITY_ALIAS = "open_rag_benchmark_100"
_COMPATIBILITY_ALIAS = "open_rag_benchmark"


class DatasetNotFoundError(LookupError):
    """Raised when a requested dataset/version pair is not registered."""


@dataclass(frozen=True)
class DatasetSpec:
    dataset_id: str
    version: str
    label: str
    repository: str
    revision: str
    base_path: str
    source_url: str
    license: str
    expected_queries: int
    expected_documents: int
    corpus_tree_oid: str
    files: dict[str, str]
    sha256: str
    artifact_manifest_sha256: str
    artifact_expected_queries: int
    manifest_path: Path
    cache_path: Path
    cache_dataset_id: str
    query_ids: tuple[str, ...] = ()
    selection_seed: int | None = None


def _load_manifest(name: str = _MANIFEST_NAME) -> tuple[dict, Path, str]:
    path = _DATASET_DIR / name
    raw = path.read_bytes()
    return json.loads(raw.decode("utf-8")), path, hashlib.sha256(raw).hexdigest()


def get_dataset_spec(dataset_id: str, version: str = "arxiv-v1") -> DatasetSpec:
    base, base_path, base_digest = _load_manifest()
    subset, subset_path, subset_digest = _load_manifest(_SUBSET_MANIFEST_NAME)
    requested_id = str(dataset_id or "").strip().lower()
    requested_version = str(version or "").strip()
    if requested_version != base["version"] or requested_id not in {
        _SUBSET_DATASET_ID,
        _SUBSET_COMPATIBILITY_ALIAS,
        _FULL_DATASET_ID,
        _COMPATIBILITY_ALIAS,
    }:
        key = (requested_id, requested_version)
        raise DatasetNotFoundError(f"unknown evaluation dataset: {key[0]}@{key[1]}")

    is_subset = requested_id in {_SUBSET_DATASET_ID, _SUBSET_COMPATIBILITY_ALIAS}
    variant = subset if is_subset else base
    variant_path = subset_path if is_subset else base_path
    variant_digest = subset_digest if is_subset else base_digest
    query_ids = tuple(str(value) for value in variant.get("query_ids", ()))
    query_ids_digest = hashlib.sha256(
        json.dumps(query_ids, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if is_subset and (
        variant.get("source_dataset_id") != base["dataset_id"]
        or variant.get("version") != base["version"]
        or len(query_ids) != 180
        or len(set(query_ids)) != 180
        or variant.get("query_ids_sha256") != query_ids_digest
    ):
        raise ValueError("invalid immutable Open RAG 180-question manifest")

    return DatasetSpec(
        dataset_id=_SUBSET_DATASET_ID if is_subset else _FULL_DATASET_ID,
        version=base["version"],
        label=variant["label"] if is_subset else f"{base['label']} (Full)",
        repository=base["repository"],
        revision=base["revision"],
        base_path=base["base_path"],
        source_url=base["source_url"],
        license=base["license"],
        expected_queries=len(query_ids) if is_subset else int(base["expected_queries"]),
        expected_documents=int(base["expected_documents"]),
        corpus_tree_oid=base["corpus_tree_oid"],
        files=dict(base["files"]),
        sha256=variant_digest,
        artifact_manifest_sha256=base_digest,
        artifact_expected_queries=int(base["expected_queries"]),
        manifest_path=variant_path,
        cache_path=Path(settings.BASE_DIR) / ".cache" / "eval-datasets" / _CACHE_DATASET_ID / base["version"],
        cache_dataset_id=_CACHE_DATASET_ID,
        query_ids=query_ids,
        selection_seed=int(variant["selection_seed"]) if is_subset else None,
    )


def registered_dataset_ids() -> tuple[str, ...]:
    return (_SUBSET_DATASET_ID, _FULL_DATASET_ID)


def registered_dataset_specs() -> tuple[DatasetSpec, ...]:
    return tuple(get_dataset_spec(dataset_id, "arxiv-v1") for dataset_id in registered_dataset_ids())
