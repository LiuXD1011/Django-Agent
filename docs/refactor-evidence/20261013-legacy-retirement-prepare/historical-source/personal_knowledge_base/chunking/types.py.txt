from dataclasses import dataclass, field


@dataclass(slots=True)
class ChunkDraft:
    content: str
    context_header: str
    start_at: int
    end_at: int
    chunk_type: str = "text"
    context_parent_index: int | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class ChunkDiagnostics:
    requested_strategy: str
    selected_strategy: str
    fallback_chain: list[dict] = field(default_factory=list)
    size_statistics: dict = field(default_factory=dict)
    duration: float = 0.0
    token_counter_source: str = "character_estimate"

    @property
    def duration_ms(self) -> float:
        return self.duration * 1000

    def as_dict(self) -> dict:
        return {
            "requested_strategy": self.requested_strategy,
            "selected_strategy": self.selected_strategy,
            "fallback_chain": self.fallback_chain,
            "size_statistics": self.size_statistics,
            "duration": self.duration,
            "duration_ms": self.duration_ms,
            "token_counter_source": self.token_counter_source,
        }


@dataclass(slots=True)
class ChunkingResult:
    parents: list[ChunkDraft]
    children: list[ChunkDraft]
    diagnostics: ChunkDiagnostics
