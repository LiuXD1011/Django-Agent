"""Compatibility boundary for the public evaluation dataset loader.

Public evaluation data is no longer normalized into tenant documents. The only
registered public dataset is prepared by ``open_rag_benchmark`` into a global,
read-only cache and evaluated from that cache.
"""

from __future__ import annotations

from pathlib import Path

from .eval_dataset_registry import DatasetNotFoundError, DatasetSpec


def load_dataset_payload(spec: DatasetSpec, *, download: bool = False, cache_dir: str | Path | None = None):
    """Reject the removed fixture-based import path."""
    raise DatasetNotFoundError(
        f"fixture import is removed for {spec.dataset_id}@{spec.version}; use the Open RAG prepare API"
    )


def load_normalized_dataset(dataset_id: str, version: str = "arxiv-v1", **kwargs):
    raise DatasetNotFoundError(
        f"fixture normalization is removed for {dataset_id}@{version}; use the Open RAG evaluation pipeline"
    )


def normalize_dataset_records(dataset_id: str, version: str, payload):
    raise DatasetNotFoundError(f"legacy public dataset normalizer is removed for {dataset_id}@{version}")
