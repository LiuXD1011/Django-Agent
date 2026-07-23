from collections.abc import Mapping
from dataclasses import asdict

from .chunking.config import ChunkingConfig
from .document_processing import normalized_chunking_config
from .models import Knowledge


ACTIVE_PARSE_STATUSES = {"pending", "processing", "finalizing"}


def normalize_chunking_config(config):
    return asdict(ChunkingConfig.from_mapping(config))


def _selected_strategy(diagnostics):
    if not isinstance(diagnostics, Mapping):
        return None
    selected = diagnostics.get("selected_strategy")
    return str(selected) if selected else None


def prepare_kb_chunking_states(knowledge_bases):
    knowledge_bases = list(knowledge_bases)
    if not knowledge_bases:
        return knowledge_bases

    current_configs = {
        str(kb.id): normalize_chunking_config(kb.chunking_config)
        for kb in knowledge_bases
    }
    states = {
        kb_id: {"needs_reindex": False, "last_effective_strategy": None}
        for kb_id in current_configs
    }
    rows = (
        Knowledge.objects.filter(
            knowledge_base_id__in=current_configs,
            deleted_at__isnull=True,
        )
        .values(
            "knowledge_base_id",
            "parse_status",
            "metadata__effective_chunking_config",
            "metadata__process_config",
            "metadata__chunking_diagnostics",
            "processed_at",
            "updated_at",
        )
        .order_by("knowledge_base_id", "-processed_at", "-updated_at")
    )

    for row in rows:
        kb_id = str(row["knowledge_base_id"])
        current = current_configs[kb_id]
        state = states[kb_id]
        status = row["parse_status"]
        diagnostics = row["metadata__chunking_diagnostics"]
        selected_strategy = _selected_strategy(diagnostics)
        effective_raw = row["metadata__effective_chunking_config"]
        effective = None

        if isinstance(effective_raw, Mapping):
            try:
                effective = normalize_chunking_config(effective_raw)
            except (TypeError, ValueError):
                state["needs_reindex"] = True
        elif status == "completed" and selected_strategy:
            try:
                effective = normalized_chunking_config(current, row["metadata__process_config"])
            except (TypeError, ValueError):
                state["needs_reindex"] = True

        if effective is not None:
            if effective != current:
                state["needs_reindex"] = True
            if state["last_effective_strategy"] is None and selected_strategy:
                state["last_effective_strategy"] = selected_strategy

        if status in ACTIVE_PARSE_STATUSES:
            try:
                requested = normalized_chunking_config(current, row["metadata__process_config"])
            except (TypeError, ValueError):
                state["needs_reindex"] = True
            else:
                if requested != current:
                    state["needs_reindex"] = True

    for kb in knowledge_bases:
        kb._chunking_state = states[str(kb.id)]
    return knowledge_bases


def backfill_completed_effective_chunking_configs(locked_kb):
    current = normalize_chunking_config(locked_kb.chunking_config)
    eligible = (
        Knowledge.objects.select_for_update()
        .filter(
            tenant=locked_kb.tenant,
            knowledge_base=locked_kb,
            deleted_at__isnull=True,
            parse_status="completed",
            metadata__has_key="chunking_diagnostics",
        )
        .exclude(metadata__has_key="effective_chunking_config")
        .only("id", "metadata", "parse_status")
    )
    for item in eligible:
        metadata = item.metadata if isinstance(item.metadata, dict) else {}
        if not _selected_strategy(metadata.get("chunking_diagnostics")):
            continue
        try:
            effective = normalized_chunking_config(current, metadata.get("process_config"))
        except (TypeError, ValueError):
            continue
        item.metadata = {**metadata, "effective_chunking_config": effective}
        item.save(update_fields=["metadata", "updated_at"])
