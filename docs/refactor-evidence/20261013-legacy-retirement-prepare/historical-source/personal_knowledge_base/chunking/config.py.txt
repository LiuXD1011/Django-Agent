import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path


SUPPORTED_FILE_TYPES = frozenset(
    {
        "pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "md", "markdown", "html", "htm",
        "csv", "json", "txt", "log", "py", "jpg", "jpeg", "png", "gif", "bmp", "tif", "tiff",
        "webp", "svg",
    }
)
UNSUPPORTED_MEDIA_FILE_TYPES = frozenset({"mp3", "wav", "m4a", "aac", "ogg", "flac", "mp4", "mov", "avi", "mkv", "webm"})
UNSUPPORTED_FILE_TYPES = frozenset({"docm", "xlsm", "pptm", "rtf", "epub"}) | UNSUPPORTED_MEDIA_FILE_TYPES

VALID_CHUNKING_STRATEGIES = frozenset({"auto", "recursive", "heading", "layout", "record", "semantic"})
MIN_CHUNK_SIZE = 128
MAX_CHUNK_SIZE = 4096
MIN_PARENT_CHUNK_SIZE = 512
MAX_PARENT_CHUNK_SIZE = 8192
MIN_CHILD_CHUNK_SIZE = 128
MAX_CHILD_CHUNK_SIZE = 2048
MAX_TOKEN_LIMIT = 32768
MAX_SEMANTIC_WINDOW_SIZE = 32

LEGACY_CHUNKING_KEYS = {
    "chunkSize": "chunk_size",
    "chunkOverlap": "chunk_overlap",
    "enableParentChild": "enable_parent_child",
    "parentChunkSize": "parent_chunk_size",
    "childChunkSize": "child_chunk_size",
    "childChunkOverlap": "child_chunk_overlap",
    "tokenLimit": "token_limit",
    "semanticWindowSize": "semantic_window_size",
    "semanticBreakpointPercentile": "semantic_breakpoint_percentile",
}


def validate_upload_extension(name: str) -> str:
    extension = Path(name or "").suffix.lower().lstrip(".")
    if extension not in SUPPORTED_FILE_TYPES:
        raise ValueError(f"unsupported file type: {extension or 'none'}")
    return extension


@dataclass(frozen=True, slots=True)
class ChunkingConfig:
    strategy: str = "auto"
    chunk_size: int = 512
    chunk_overlap: int = 80
    enable_parent_child: bool = True
    parent_chunk_size: int = 2048
    child_chunk_size: int = 384
    child_chunk_overlap: int = 64
    token_limit: int = 0
    semantic_window_size: int = 3
    semantic_breakpoint_percentile: float = 90.0

    @classmethod
    def from_mapping(cls, raw: Mapping | None) -> "ChunkingConfig":
        if raw is not None and not isinstance(raw, Mapping):
            raise ValueError("chunking configuration must be a mapping")
        values = dict(raw or {})
        defaults = cls()
        enable_parent_child = values.get("enable_parent_child", defaults.enable_parent_child)
        if not isinstance(enable_parent_child, bool):
            raise ValueError("enable_parent_child must be a boolean")
        config = cls(
            strategy=str(values.get("strategy", defaults.strategy)),
            chunk_size=int(values.get("chunk_size", defaults.chunk_size)),
            chunk_overlap=int(values["chunk_overlap"]) if "chunk_overlap" in values else defaults.chunk_overlap,
            enable_parent_child=enable_parent_child,
            parent_chunk_size=int(values.get("parent_chunk_size", defaults.parent_chunk_size)),
            child_chunk_size=int(values.get("child_chunk_size", defaults.child_chunk_size)),
            child_chunk_overlap=int(values["child_chunk_overlap"]) if "child_chunk_overlap" in values else defaults.child_chunk_overlap,
            token_limit=int(values["token_limit"]) if "token_limit" in values else defaults.token_limit,
            semantic_window_size=int(values.get("semantic_window_size", defaults.semantic_window_size)),
            semantic_breakpoint_percentile=float(values.get("semantic_breakpoint_percentile", defaults.semantic_breakpoint_percentile)),
        )
        config._validate()
        return config

    def _validate(self):
        if self.strategy not in VALID_CHUNKING_STRATEGIES:
            raise ValueError(f"unsupported chunking strategy: {self.strategy}")
        for name, value, minimum, maximum in (
            ("chunk_size", self.chunk_size, MIN_CHUNK_SIZE, MAX_CHUNK_SIZE),
            ("parent_chunk_size", self.parent_chunk_size, MIN_PARENT_CHUNK_SIZE, MAX_PARENT_CHUNK_SIZE),
            ("child_chunk_size", self.child_chunk_size, MIN_CHILD_CHUNK_SIZE, MAX_CHILD_CHUNK_SIZE),
        ):
            if not minimum <= value <= maximum:
                raise ValueError(f"{name} must be between {minimum} and {maximum}")
        if not 0 <= self.chunk_overlap <= self.chunk_size // 2:
            raise ValueError("chunk_overlap cannot exceed half of chunk_size")
        if not 0 <= self.child_chunk_overlap <= self.child_chunk_size // 2:
            raise ValueError("child_chunk_overlap cannot exceed half of child_chunk_size")
        if self.parent_chunk_size < self.child_chunk_size:
            raise ValueError("parent_chunk_size must be at least child_chunk_size")
        if not 0 <= self.token_limit <= MAX_TOKEN_LIMIT:
            raise ValueError(f"token_limit must be between 0 and {MAX_TOKEN_LIMIT}")
        if not 1 <= self.semantic_window_size <= MAX_SEMANTIC_WINDOW_SIZE:
            raise ValueError(f"semantic_window_size must be between 1 and {MAX_SEMANTIC_WINDOW_SIZE}")
        if not 0 <= self.semantic_breakpoint_percentile <= 100:
            raise ValueError("semantic_breakpoint_percentile must be between 0 and 100")


def _coerce_int(value, default, minimum, maximum):
    if isinstance(value, bool):
        return default, False
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return default, False
    clamped = min(max(number, minimum), maximum)
    return clamped, clamped == number


def _coerce_float(value, default, minimum, maximum):
    if isinstance(value, bool):
        return default, False
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default, False
    if not math.isfinite(number):
        return default, False
    clamped = min(max(number, minimum), maximum)
    return clamped, clamped == number


def _coerce_bool(value, default):
    if isinstance(value, bool):
        return value, True
    if isinstance(value, int) and value in {0, 1}:
        return bool(value), True
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "enabled"}:
            return True, True
        if normalized in {"0", "false", "no", "off", "disabled"}:
            return False, True
    return default, False


def project_persisted_chunking_config(raw) -> tuple[dict, bool]:
    """Project legacy persisted JSON without mutating it or weakening write validation."""
    defaults = asdict(ChunkingConfig())
    if not isinstance(raw, Mapping):
        return defaults, False

    values = dict(raw)
    projected = dict(defaults)
    compatible = True
    used_legacy_key = False
    for legacy_key, current_key in LEGACY_CHUNKING_KEYS.items():
        if legacy_key in values and current_key not in values:
            values[current_key] = values[legacy_key]
            used_legacy_key = True

    if "strategy" in values:
        strategy = values["strategy"]
        if isinstance(strategy, str) and strategy in VALID_CHUNKING_STRATEGIES:
            projected["strategy"] = strategy
        else:
            compatible = False

    integer_ranges = {
        "chunk_size": (MIN_CHUNK_SIZE, MAX_CHUNK_SIZE),
        "parent_chunk_size": (MIN_PARENT_CHUNK_SIZE, MAX_PARENT_CHUNK_SIZE),
        "child_chunk_size": (MIN_CHILD_CHUNK_SIZE, MAX_CHILD_CHUNK_SIZE),
        "token_limit": (0, MAX_TOKEN_LIMIT),
        "semantic_window_size": (1, MAX_SEMANTIC_WINDOW_SIZE),
    }
    for key, (minimum, maximum) in integer_ranges.items():
        if key not in values:
            continue
        projected[key], exact = _coerce_int(values[key], defaults[key], minimum, maximum)
        compatible = compatible and exact

    if "enable_parent_child" in values:
        projected["enable_parent_child"], exact = _coerce_bool(
            values["enable_parent_child"], defaults["enable_parent_child"]
        )
        compatible = compatible and exact

    if "semantic_breakpoint_percentile" in values:
        projected["semantic_breakpoint_percentile"], exact = _coerce_float(
            values["semantic_breakpoint_percentile"],
            defaults["semantic_breakpoint_percentile"],
            0,
            100,
        )
        compatible = compatible and exact

    for overlap_key, size_key in (
        ("chunk_overlap", "chunk_size"),
        ("child_chunk_overlap", "child_chunk_size"),
    ):
        if overlap_key not in values:
            continue
        projected[overlap_key], exact = _coerce_int(
            values[overlap_key],
            defaults[overlap_key],
            0,
            projected[size_key] // 2,
        )
        compatible = compatible and exact

    for overlap_key, size_key in (
        ("chunk_overlap", "chunk_size"),
        ("child_chunk_overlap", "child_chunk_size"),
    ):
        maximum_overlap = projected[size_key] // 2
        if projected[overlap_key] > maximum_overlap:
            projected[overlap_key] = maximum_overlap
            compatible = False

    if projected["parent_chunk_size"] < projected["child_chunk_size"]:
        projected["parent_chunk_size"] = projected["child_chunk_size"]
        compatible = False

    try:
        strictly_normalized = asdict(ChunkingConfig.from_mapping(raw))
    except (TypeError, ValueError, OverflowError):
        compatible = False
    else:
        compatible = compatible and not used_legacy_key and strictly_normalized == projected
    return projected, compatible
