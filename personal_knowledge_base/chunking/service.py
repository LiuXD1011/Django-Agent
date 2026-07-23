from collections.abc import Callable
from statistics import mean
from time import perf_counter

from .config import ChunkingConfig
from .recursive import UnsplittableTokenLimit, split_recursive_units, split_text_range
from .structural import (
    build_atomic_units,
    draft_metadata_for_range,
    select_auto_strategy,
    split_heading_units,
    split_layout_units,
    split_record_units,
)
from .types import ChunkDiagnostics, ChunkDraft, ChunkingResult
from .validator import ChunkValidationError, validate_drafts, validate_hierarchy


STRATEGIES = {
    "heading": split_heading_units,
    "layout": split_layout_units,
    "record": split_record_units,
    "recursive": split_recursive_units,
}


def _character_token_estimate(value: str) -> int:
    return (len(value) + 3) // 4 if value else 0


def _counter(token_counter) -> tuple[Callable[[str], int], str]:
    if token_counter is None:
        return _character_token_estimate, "character_estimate"
    if callable(token_counter):
        return token_counter, str(getattr(token_counter, "source", "custom"))
    count = getattr(token_counter, "count", None)
    if callable(count):
        return count, str(getattr(token_counter, "source", token_counter.__class__.__name__))
    raise TypeError("token_counter must be callable or expose count(text)")


def _clean_metadata(draft: ChunkDraft) -> None:
    draft.metadata.pop("_protected_ranges", None)


def _hierarchy(
    strategy_name: str,
    units,
    source: str,
    config: ChunkingConfig,
    title: str,
    token_counter: Callable[[str], int],
) -> tuple[list[ChunkDraft], list[ChunkDraft]]:
    strategy = STRATEGIES[strategy_name]
    if not config.enable_parent_child:
        children = strategy(
            units,
            source=source,
            chunk_size=config.chunk_size,
            overlap=config.chunk_overlap,
            title=title,
            token_counter=token_counter,
            token_limit=config.token_limit,
        )
        for child in children:
            child.chunk_type = "text"
            child.metadata = draft_metadata_for_range(
                units,
                child.start_at,
                child.end_at,
                strategy_name,
            )
            _clean_metadata(child)
        return [], children

    parents = strategy(
        units,
        source=source,
        chunk_size=config.parent_chunk_size,
        overlap=0,
        title=title,
        token_counter=token_counter,
        token_limit=config.token_limit,
    )
    children = []
    for parent_index, parent in enumerate(parents):
        protected = parent.metadata.get("_protected_ranges", [])
        parent.chunk_type = "parent_text"
        parent.context_parent_index = None
        child_drafts = split_text_range(
            source,
            parent.start_at,
            parent.end_at,
            chunk_size=config.child_chunk_size,
            overlap=config.child_chunk_overlap,
            context_header=parent.context_header,
            token_counter=token_counter,
            token_limit=config.token_limit,
            extra_protected_ranges=protected,
            metadata={"strategy": strategy_name},
        )
        for child in child_drafts:
            child.context_parent_index = parent_index
            child.chunk_type = "text"
            child.metadata = draft_metadata_for_range(
                units,
                child.start_at,
                child.end_at,
                strategy_name,
            )
            _clean_metadata(child)
        children.extend(child_drafts)
        _clean_metadata(parent)
    return parents, children


def _statistics(drafts: list[ChunkDraft], token_counter: Callable[[str], int]) -> dict:
    char_sizes = [len(draft.content) for draft in drafts]
    token_sizes = [token_counter(draft.content) for draft in drafts]
    if not drafts:
        return {
            "count": 0,
            "total": 0,
            "min": 0,
            "max": 0,
            "average": 0.0,
            "min_chars": 0,
            "max_chars": 0,
            "average_chars": 0.0,
            "min_tokens": 0,
            "max_tokens": 0,
            "average_tokens": 0.0,
        }
    return {
        "count": len(drafts),
        "total": sum(char_sizes),
        "min": min(char_sizes),
        "max": max(char_sizes),
        "average": mean(char_sizes),
        "min_chars": min(char_sizes),
        "max_chars": max(char_sizes),
        "average_chars": mean(char_sizes),
        "min_tokens": min(token_sizes),
        "max_tokens": max(token_sizes),
        "average_tokens": mean(token_sizes),
    }


def split_document(
    parsed,
    config: ChunkingConfig,
    *,
    title: str,
    token_counter=None,
) -> ChunkingResult:
    started = perf_counter()
    counter, counter_source = _counter(token_counter)
    source, units = build_atomic_units(parsed)
    requested = config.strategy
    initial = select_auto_strategy(units) if requested == "auto" else requested
    candidates = [initial]
    if initial != "recursive":
        candidates.append("recursive")
    fallback_chain = []
    last_issues = ["empty_output"]

    for strategy_name in candidates:
        if strategy_name not in STRATEGIES:
            last_issues = ["strategy_unavailable"]
            fallback_chain.append({"strategy": strategy_name, "reason": "strategy_unavailable"})
            continue
        try:
            parents, children = _hierarchy(
                strategy_name,
                units,
                source,
                config,
                title.strip(),
                counter,
            )
            issues = validate_drafts(
                children,
                source,
                target_size=config.child_chunk_size if config.enable_parent_child else config.chunk_size,
                token_counter=counter,
                token_limit=config.token_limit,
            )
            if parents:
                issues.extend(
                    validate_drafts(
                        parents,
                        source,
                        target_size=config.parent_chunk_size,
                        token_counter=counter,
                        token_limit=config.token_limit,
                    )
                )
                issues.extend(validate_hierarchy(parents, children))
            issues = list(dict.fromkeys(issues))
        except UnsplittableTokenLimit as exc:
            parents, children = [], []
            issues = [f"token_limit_exceeded:{exc}"]

        if not issues:
            diagnostics = ChunkDiagnostics(
                requested_strategy=requested,
                selected_strategy=strategy_name,
                fallback_chain=fallback_chain,
                size_statistics={
                    "parents": _statistics(parents, counter),
                    "children": _statistics(children, counter),
                },
                duration=perf_counter() - started,
                token_counter_source=counter_source,
            )
            return ChunkingResult(parents=parents, children=children, diagnostics=diagnostics)

        last_issues = issues
        fallback_chain.append({"strategy": strategy_name, "reason": ";".join(issues)})

    raise ChunkValidationError(last_issues, fallback_chain)
