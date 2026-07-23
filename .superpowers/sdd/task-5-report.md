# Task 5 Report: Adaptive Parent-Child Processing and Child-Only Indexing

## Scope

Implemented Task 5 from base commit `9e0b0cf` on `main`. The unrelated untracked plan at `docs/superpowers/plans/2026-07-23-adaptive-parent-child-chunking.md` was not changed.

## RED Evidence

Command:

```text
python manage.py test personal_knowledge_base.test_parent_child_processing personal_knowledge_base.test_multimodal_processing -v 2
```

Result: exit `1`; 21 tests ran with 3 failures and 5 errors.

- `Chunk.embedding_content()` was missing.
- Main processing persisted only flat text chunks, so no `parent_text` chunks existed.
- A direct `index_chunk(parent_text)` call inserted an FTS5 row.
- Multimodal processing still wrote the read-only compatibility property `parent_chunk_id` and raised `AttributeError`.

Additional RED regression:

```text
python manage.py test personal_knowledge_base.test_parent_child_processing.ParentChildProcessingTests.test_vector_rebuild_excludes_parents_and_embeds_contextual_children -v 2
```

Result: exit `1`; vector rebuild supplied `['parent context', 'child body']` to embeddings instead of only the contextual child content.

## Changed Behavior

- `persist_chunking_result(knowledge, result)` bulk-creates all `parent_text` chunks before child `text` chunks. Child `context_parent_id` maps from each draft's `context_parent_index`; raw content and absolute offsets remain unchanged; structural chunks use `parent-child-v1`.
- Main file processing now normalizes `ChunkingConfig`, calls `split_document`, records diagnostics in the chunking stage output and `Knowledge.metadata['chunking_diagnostics']`, and retains legacy flat helpers for their existing callers.
- `Chunk.embedding_content()` returns the context header, a blank line, and raw content when a header exists. FTS5, immediate vector indexing, and vector rebuilds use that content while FTS5 retains `Knowledge.title` in its title field.
- `parent_text` chunks are disabled, excluded from neighbor links, searchable-content aggregation, graph input, retrieval hydration, and vector rebuild. `index_chunk(parent_text)` returns before either FTS5 or sqlite-vec write.
- Image OCR/caption chunks use `media_parent_id` for an image container and `anchor_chunk_id` for the nearest text child. Image-only documents create a container with a null anchor. The nearest-anchor routine receives text children only.

## Indexing Assertions

`test_direct_parent_indexing_creates_no_fts_or_vector_rows` executes a direct parent index request and queries both index tables: `chunks_fts` count is `0` and `chunk_embeddings_vec` count is `0` for that parent.

`test_vector_rebuild_excludes_parents_and_embeds_contextual_children` verifies rebuild embeds only `Installation Guide > Install\n\nchild body`; it does not include the parent.

## GREEN Evidence

```text
python manage.py test personal_knowledge_base.test_parent_child_processing personal_knowledge_base.test_multimodal_processing personal_knowledge_base.test_hybrid_rrf -v 2
```

Result: exit `0`; 26 tests ran, all passed.

```text
python manage.py test personal_knowledge_base.test_adaptive_chunking personal_knowledge_base.test_chunking_config -v 2
```

Result: exit `0`; 26 tests ran, all passed.

```text
python manage.py makemigrations --check
```

Result: exit `0`; `No changes detected`.

## Diagnostics Evidence

`test_only_children_are_indexed` asserts that processing persists `Knowledge.metadata['chunking_diagnostics']`; the processing span stage output includes the same `result.diagnostics.as_dict()` value under `diagnostics`.

## Commit

Implementation commit SHA: `92d76fecdc21558a5a7b33999c20aec2eaa405f2`

## Concerns

None. Vector warnings in tests are expected because those fixtures intentionally have no embedding model configured; FTS behavior remains available.

## Review Remediation

### Findings, Root Causes, and Fixes

- **Critical 1 and Minor parent-index validation:** `persist_chunking_result()` indexed the parent list while constructing children, after the parent `bulk_create`, so negative indices were accepted by Python and invalid types or upper bounds failed after writes. `validate_context_parent_indices()` now requires a non-boolean integer in `0 <= index < parent_count` before persistence. The helper wraps both bulk creates in `transaction.atomic()`, and `process_knowledge()` validates and creates search tables before an outer transaction covering old index deletion, old chunk deletion, and new hierarchy persistence.
- **Critical 2 durable child-only indexing:** `index_chunk()` returned before deleting stale parent rows, while rebuild selected every enabled non-parent chunk and never pruned physical rows. Searchability is now restricted to enabled `text`, `image_ocr`, and `image_caption` chunks belonging to active Knowledge and KnowledgeBase rows. Direct indexing deletes prior FTS/vector rows before an ineligible return. Rebuild derives authoritative chunk IDs/rowids, prunes stale FTS and sqlite-vec rows for parents, disabled chunks, containers, soft-deleted knowledge, and deleted/orphaned rows, then embeds only eligible chunks. The existing pre-batch and in-loop cancellation returns and all-batch failure behavior remain intact.
- **Critical 3 media anchoring and coverage:** child drafts inherited only strategy metadata and persistence copied parent-wide block coverage, so all children appeared to cover the same blocks and list order could select a following child. Child metadata is now regenerated from atomic units intersecting each exact `[start_at, end_at)` range. Anchor selection uses the greatest covered block position not after the image, then source end, chunk order, and ID for deterministic selection; image containers and OCR/caption chunks share that anchor.
- **Important 1 retrieval hydration:** `_hydrate_candidates()` emitted the legacy `parent_chunk_id` compatibility property. The ambiguous field is removed; Task 6 parent hydration is not introduced here.
- **Important 3 production layout behavior:** adaptive chunking ignored parsed image positions, allowing PDF/DOC/PPT layout groups to cross media and leaving production behavior untested. Atomic units now carry a zero-width media boundary marker used by structural and recursive grouping without changing canonical source text or offsets. Production `process_knowledge()` tests verify page order, image boundaries, preceding-child anchors, and retention of short PDF labels.
- **Important 2:** intentionally not changed. Hierarchy-safe edit/disable/delete behavior remains owned by approved Task 6.

### RED Evidence

Command:

```text
python manage.py test personal_knowledge_base.test_parent_child_processing.ParentChildProcessingTests.test_invalid_parent_indices_are_rejected_before_any_write personal_knowledge_base.test_parent_child_processing.ParentChildProcessingTests.test_persist_chunking_result_rolls_back_parents_when_child_insert_fails personal_knowledge_base.test_parent_child_processing.ParentChildProcessingTests.test_processing_replacement_rolls_back_old_chunks_and_indexes personal_knowledge_base.test_parent_child_processing.ParentChildProcessingTests.test_direct_parent_indexing_creates_no_fts_or_vector_rows personal_knowledge_base.test_parent_child_processing.ParentChildProcessingTests.test_vector_rebuild_excludes_parents_and_embeds_contextual_children personal_knowledge_base.test_hybrid_rrf.HybridSearchExTests.test_hydration_does_not_emit_ambiguous_parent_chunk_id personal_knowledge_base.test_adaptive_chunking.AdaptiveChunkingTests.test_layout_image_is_a_hard_boundary_with_child_specific_coverage personal_knowledge_base.test_multimodal_processing.MultimodalProcessingTests.test_process_knowledge_anchors_inline_media_to_greatest_preceding_child personal_knowledge_base.test_multimodal_processing.MultimodalProcessingTests.test_process_knowledge_preserves_pdf_layout_boundaries_and_short_labels -v 2
```

Result: exit `1`; 9 tests ran with 10 failures and 2 errors across subtests. The run demonstrated negative/string/bool parent-index acceptance or late failure, non-atomic bulk persistence and replacement, stale parent index rows, non-searchable rebuild input and unpruned rows, ambiguous hydration output, missing child block coverage, following-child media anchors, and layout groups crossing parsed images.

### GREEN Evidence

Focused atomic command: 3 tests ran, all passed.

```text
python manage.py test personal_knowledge_base.test_parent_child_processing.ParentChildProcessingTests.test_invalid_parent_indices_are_rejected_before_any_write personal_knowledge_base.test_parent_child_processing.ParentChildProcessingTests.test_persist_chunking_result_rolls_back_parents_when_child_insert_fails personal_knowledge_base.test_parent_child_processing.ParentChildProcessingTests.test_processing_replacement_rolls_back_old_chunks_and_indexes -v 2
```

Focused index/hydration command: 3 tests ran, all passed.

```text
python manage.py test personal_knowledge_base.test_parent_child_processing.ParentChildProcessingTests.test_direct_parent_indexing_creates_no_fts_or_vector_rows personal_knowledge_base.test_parent_child_processing.ParentChildProcessingTests.test_vector_rebuild_excludes_parents_and_embeds_contextual_children personal_knowledge_base.test_hybrid_rrf.HybridSearchExTests.test_hydration_does_not_emit_ambiguous_parent_chunk_id -v 2
```

Required command:

```text
python manage.py test personal_knowledge_base.test_parent_child_processing personal_knowledge_base.test_multimodal_processing personal_knowledge_base.test_hybrid_rrf personal_knowledge_base.test_adaptive_chunking -v 2
```

Result: exit `0`; 48 tests ran, all passed.

```text
python manage.py makemigrations --check
```

Result: exit `0`; `No changes detected`.

### Changed Files

- `personal_knowledge_base/document_processing.py`
- `personal_knowledge_base/search.py`
- `personal_knowledge_base/multimodal.py`
- `personal_knowledge_base/chunking/structural.py`
- `personal_knowledge_base/chunking/recursive.py`
- `personal_knowledge_base/chunking/service.py`
- `personal_knowledge_base/test_parent_child_processing.py`
- `personal_knowledge_base/test_multimodal_processing.py`
- `personal_knowledge_base/test_hybrid_rrf.py`
- `personal_knowledge_base/test_adaptive_chunking.py`
- `.superpowers/sdd/task-5-report.md`

### Remaining Concerns

External image storage deletion cannot participate in Django database transactions. The required old/new chunk and physical index replacement is transactional; hierarchy-aware mutation endpoints remain explicitly deferred to Task 6. Expected no-embedding-model warnings remain in fixtures that exercise FTS fallback.
