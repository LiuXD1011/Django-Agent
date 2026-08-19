"""Versioned registry for small, reproducible evaluation dataset subsets."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings


_DATASET_DIR = Path(__file__).resolve().parent / "eval_datasets"


class DatasetNotFoundError(LookupError):
    """Raised when a requested dataset/version pair is not registered."""


@dataclass(frozen=True)
class DatasetSpec:
    dataset_id: str
    version: str
    source_url: str
    license: str
    sha256: str
    cache_path: Path
    fixture_path: Path


_REGISTRY = {
    ("ragas", "v1"): {
        "source_url": "https://docs.ragas.io/en/stable/getstarted/rag_testset_generation/",
        "license": "Apache-2.0",
        "fixture": "ragas_v1.fixture.json",
    },
    ("squad", "v1"): {
        "source_url": "https://rajpurkar.github.io/SQuAD-explorer/dataset/train-v1.1.json",
        "license": "CC-BY-SA-4.0",
        "fixture": "squad_v1.fixture.json",
    },
    ("hotpotqa", "v1"): {
        "source_url": "https://hotpotqa.github.io/",
        "license": "CC-BY-SA-4.0",
        "fixture": "hotpotqa_v1.fixture.json",
    },
}


def _fixture_checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def get_dataset_spec(dataset_id: str, version: str = "v1") -> DatasetSpec:
    """Return immutable provenance and cache metadata for a registered subset.

    The checksum covers the committed, fixed subset fixture rather than an
    upstream full corpus. This makes the default small evaluation input
    reproducible without checking a large corpus into this repository.
    """
    key = (str(dataset_id or "").strip().lower(), str(version or "").strip())
    source = _REGISTRY.get(key)
    if source is None:
        raise DatasetNotFoundError(f"unknown evaluation dataset: {key[0]}@{key[1]}")
    fixture_path = _DATASET_DIR / source["fixture"]
    return DatasetSpec(
        dataset_id=key[0],
        version=key[1],
        source_url=source["source_url"],
        license=source["license"],
        sha256=_fixture_checksum(fixture_path),
        cache_path=Path(settings.BASE_DIR) / ".cache" / "eval-datasets" / key[0] / f"{key[1]}.json",
        fixture_path=fixture_path,
    )


def registered_dataset_ids() -> tuple[str, ...]:
    return tuple(sorted({dataset_id for dataset_id, _version in _REGISTRY}))
