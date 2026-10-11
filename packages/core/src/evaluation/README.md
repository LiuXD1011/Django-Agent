# Evaluation core service

`new EvaluationService(db, auth, models, index, jobs, options)` uses the actual
`ModelConfigurationService`, `SearchIndex`, and `JobQueue`. Trusted constructor
options select the owned Python executable/worker, optional pure-context answer
hook, public cache/origin/spec fixtures and legacy cache root. They are not HTTP
payload options. Core routes expose the public methods in `index.ts`; they must
never expose checkpoints, invocation ledgers, configurations or arbitrary SQL.

Datasets/testsets support real generation, scoped canonical code-point evidence,
manual/auto/sample review, edits/deletion, approval, immutable publication and
new draft versions. Editing resets review. A tenant run requires at least five
distinct approved, source-current published questions. Legacy manually entered
questions remain unverified. Missing answer/judge/embedding/Ragas (and requested
reranker/vector index) is `needs_configuration`; no key means no claimed success.

`estimate(ctx,input)` and `createRun(ctx,input,requestId?)` accept:

```json
{
  "source": {"type":"tenant_dataset","dataset_id":"published-id","knowledge_base_id":"kb-id"},
  "retrieval_strategy":"hybrid",
  "rerank_enabled":true,
  "primary_chunking_strategy":"stored",
  "comparison_chunking_strategies":["fixed_window","recursive"],
  "answer_model_id":"KnowledgeQA",
  "judge_model_id":"KnowledgeQA"
}
```

For public evaluation use `source.type:"open_dataset"`, a pinned catalog
`dataset_id`, optional `sample_size` (5..variant size) and integer `seed`.
Omitting size evaluates the full selected 180/3045-question variant; the default
seed remains 20260819. Integer-seed shuffle and 10% review sampling reproduce
actual historical CPython Random results. The former `chunking_strategies`
array maps to primary-first/comparison-rest; conflicting explicit fields are
rejected. An explicitly requested dataset version must match publication or the
pinned manifest. Public cache
preparation is independent of tenant business documents/indexes. Use
`queuePrepareOpen(ctx,id,requestId?)` in HTTP routes: it returns a real safe job
without waiting for all downloads. `prepareOpen(ctx,id)` awaits actual completion
for trusted core/test callers. `openStatus` freshly verifies core SHA-256, Git
blob hashes and the complete pinned Git tree identity, not mutable cache state.
The fixed subset remains 180 published IDs; full variant remains 3045 IDs. Old pinned raw artifacts under `legacyCacheRoot/eval-datasets/open_rag_benchmark/<version>` are copied only after pinned verification; original artifacts/indexes are not rewritten. Cache hash verification is memoized only while every file identity/size/nanosecond mtime/ctime remains unchanged; a change requires full checks again. The actual pinned JSON corpus is approximately 742 MB (including encoded images); cache budget is 1 GiB, canonical-text budget 256 MiB.

Tenant `stored` uses its actual production index. Other primary/comparison
strategies create fresh derived SQLite indexes over **all** enabled source
documents; queries are not restricted to ground-truth documents. Production
chunking inherits actual KB settings. Layout/record/auto/semantic require real
persisted parser blocks. Image block indices retain barriers without private
artifact paths. Missing blocks or a production chunker fallback fails explicitly.
No business document/chunk or production vector generation is rewritten.
Semantic/vector/rerank requests use actual configured models and audit each
invocation. Comparisons report retrieval and measured index resources only;
formal Ragas scores belong to the primary strategy. Promotion gates preserve
safe missing/zero denominator handling. Character estimates are identified.

The default answer is an actual `ModelRuntime.complete` over scoped evidence,
without creating dialogue history. Optional `EvaluationAnswer` returns an answer
and actual `ModelUsage`; the service records it once. Each paid dispatch first
persists a fenced invocation identity and input hash. Results are encrypted in a
separate private invocation ledger, avoiding rewriting all prior RPC results on
every call. An external request completed after cancellation/revocation still
has its actual usage audit recorded. Pending/unknown results never replay on
restart: explicit `resume(...,{acknowledge_unknown_paid_request:true})` is
required. Known answers/judge/embedding results are reused. Manual resume refuses
source/model drift. All write transactions finish before provider awaits.

`status`, `active`, `cancel`, `resume`, `history`, `getReport`, `downloadReport`
and `deleteReport` are tenant/auth scoped. Reports contain actual finite metrics,
requested/effective pipelines and source fingerprints, without prompts, answers,
contexts or credentials. Unsupported metrics stay null. Full tenant corpus,
stored chunks and chunk configuration participate in freshness; report deletion
keeps run and usage audits. Legacy `rag_eval_runs` report rows and
`legacyCacheRoot/eval-reports/<tenant>/*.json` remain visible/downloadable with
content/credential sanitization and freshness `unknown`. Deleting a legacy
report creates a new tenant tombstone and does not edit original cache artifacts.
`legacyCacheRoot` is the old **cache directory**, not the Django database root.

`close()` aborts and awaits actual generation, public downloads, executor,
provider-audit finally work and owned helpers before the business DB closes.
Worker protocol/verification details and real/unverified boundaries are in
[`workers/evaluation/README.md`](../../../../workers/evaluation/README.md).


The evaluation page reads the actual bounded request estimate, separates
unestimated corpus indexing work, restores `active_run` or the actual `runs`
array, and follows the new run ID returned after cancelled resume. Unknown paid
results require an explicit duplicate-cost acknowledgement; cancelling that
confirmation sends no retry. Delayed responses from the previous run are fenced
out. Only server-confirmed published/approved entries are usable questions; tenant
restart restoration reloads the immutable published dataset from core.
Actual Ragas sample counts and measured metrics render without manufacturing
missing per-question failure counts. Configuration comparison ignores derived
source provenance and preserves default model-role meaning.
