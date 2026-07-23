from collections.abc import Mapping
from dataclasses import dataclass
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

VALID_CHUNKING_STRATEGIES = frozenset({"auto", "recursive", "heading", "record", "semantic"})
MIN_CHUNK_SIZE = 128
MAX_CHUNK_SIZE = 32768
MAX_TOKEN_LIMIT = 32768
MAX_SEMANTIC_WINDOW_SIZE = 32


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
        config = cls(
            strategy=str(values.get("strategy", defaults.strategy)),
            chunk_size=int(values.get("chunk_size", defaults.chunk_size)),
            chunk_overlap=int(values["chunk_overlap"]) if "chunk_overlap" in values else defaults.chunk_overlap,
            enable_parent_child=bool(values.get("enable_parent_child", defaults.enable_parent_child)),
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
        for name, value in (
            ("chunk_size", self.chunk_size),
            ("parent_chunk_size", self.parent_chunk_size),
            ("child_chunk_size", self.child_chunk_size),
        ):
            if not MIN_CHUNK_SIZE <= value <= MAX_CHUNK_SIZE:
                raise ValueError(f"{name} must be between {MIN_CHUNK_SIZE} and {MAX_CHUNK_SIZE}")
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
