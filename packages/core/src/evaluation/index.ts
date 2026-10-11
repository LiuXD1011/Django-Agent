import { randomUUID } from 'node:crypto';
import type { AuthContext, JsonObject } from '../contracts.js';
import type { AuthService } from '../auth/index.js';
import type { CoreDatabase } from '../storage/database.js';
import type { ModelConfigurationService } from '../settings/index.js';
import type { SearchIndex } from '../retrieval/search-index.js';
import type { JobQueue, JobContext } from '../jobs/queue.js';
import { ModelRuntime } from '../models/runtime.js';
import { EvaluationDatasets } from './datasets.js';
import { EvaluationStore } from './store.js';
import { EvaluationExecutor, type EvaluationAnswer } from './executor.js';
import { RagasBridge, type RagasOptions } from './ragas.js';
import { EvaluationGeneration } from './generation.js';
import { PublicEvaluationDatasets, type PublicDatasetOptions } from './public-datasets.js';
import { evaluationStrategies } from './isolated-index.js';
import { corpusFingerprint } from './fingerprint.js';
import { fail, object, digest } from './common.js';
import { DeterministicEvaluation } from './deterministic.js';
export { RagasBridge } from './ragas.js';
export type { RagasOptions, RagasRow } from './ragas.js';
export type { EvaluationAnswer, EvaluationAnswerInput } from './executor.js';
export interface EvaluationOptions extends PublicDatasetOptions { ragas?: RagasOptions; answer?: EvaluationAnswer; legacyCacheRoot?: string }
const registries = new WeakMap<JobQueue, { current: EvaluationService | undefined }>();
export class EvaluationService {
  private readonly datasets: EvaluationDatasets;
  private readonly store: EvaluationStore;
  private readonly bridge?: RagasBridge;
  private readonly executor: EvaluationExecutor;
  private readonly generation: EvaluationGeneration;
  private readonly publicDatasets: PublicEvaluationDatasets;
  private readonly deterministic: DeterministicEvaluation;
  private readonly calls = new Set<Promise<JsonObject>>();
  private readonly controllers = new Set<AbortController>();
  private closed = false;
  constructor(readonly db: CoreDatabase, readonly auth: AuthService, readonly models: ModelConfigurationService, readonly index: SearchIndex, readonly jobs: JobQueue, readonly options: EvaluationOptions = {}) {
    this.datasets = new EvaluationDatasets(db, auth); this.store = new EvaluationStore(db, auth, jobs, options.legacyCacheRoot); this.bridge = options.ragas ? new RagasBridge(options.ragas) : undefined;
    if (!registries.has(jobs)) this.datasets.recoverGeneration();
    this.generation = new EvaluationGeneration(db, auth, models, this.datasets);
    this.publicDatasets = new PublicEvaluationDatasets(db, auth, options);
    this.store.publicFreshness = (ctx, snapshot) => { try { const value = this.publicDatasets.status(ctx, String(snapshot.public_dataset_id)); return value.ready === true && value.manifest_sha256 === snapshot.dataset_hash && value.revision === snapshot.revision; } catch { return false; } };
    this.executor = new EvaluationExecutor(this.store, this.datasets, models, index, this.bridge, options.answer, this.publicDatasets);
    this.deterministic = new DeterministicEvaluation(this.store, this.datasets, models, index, this.publicDatasets);
    const existing = registries.get(jobs);
    if (existing) existing.current = this;
    else { const registry = { current: this as EvaluationService | undefined }; registries.set(jobs, registry); jobs.register('rag_evaluation', async context => { if (!registry.current) return fail(503, 'evaluation_closed', 'Evaluation is closed'); return registry.current.execute(context); }); jobs.register('evaluation_prepare_public', async (context, payload) => { if (!registry.current) return fail(503, 'evaluation_closed', 'Evaluation is closed'); return registry.current.publicDatasets.prepare(object(payload.context) as unknown as AuthContext, String(payload.dataset_id), { signal: context.signal, check: () => { context.publish(() => {}); }, onProgress: value => context.progress(value) }); }); }
  }
  listDatasets(ctx: AuthContext, kind = 'datasets'): JsonObject { return this.datasets.list(ctx, kind); }
  getDataset(ctx: AuthContext, id: string): JsonObject { return this.datasets.dto(this.datasets.row(ctx, id)); }
  createDataset(ctx: AuthContext, input: JsonObject): JsonObject { return this.datasets.create(ctx, input); }
  editEntry(ctx: AuthContext, id: string, entryId: string, patch: JsonObject): JsonObject { return this.datasets.edit(ctx, id, entryId, patch); }
  deleteEntry(ctx: AuthContext, id: string, entryId: string): JsonObject { return this.datasets.delete(ctx, id, entryId); }
  review(ctx: AuthContext, id: string, input: JsonObject): JsonObject { return this.datasets.review(ctx, id, input); }
  publish(ctx: AuthContext, id: string): JsonObject { return this.datasets.publish(ctx, id); }
  newVersion(ctx: AuthContext, id: string): JsonObject { return this.datasets.version(ctx, id); }
  questions(ctx: AuthContext): JsonObject { return this.generation.questions(ctx); }
  addQuestion(ctx: AuthContext, input: JsonObject): JsonObject { return this.generation.add(ctx, input); }
  deleteQuestion(ctx: AuthContext, id: string): JsonObject { return this.generation.delete(ctx, id); }
  openDatasets(ctx: AuthContext): JsonObject { return this.publicDatasets.catalog(ctx); }
  openStatus(ctx: AuthContext, id: string): JsonObject { const status = this.publicDatasets.status(ctx, id); if (status.ready) return status; const spec = this.publicDatasets.spec(id), job = this.jobs.list({ tenantId: ctx.tenantId, userId: ctx.userId }).find(value => value.kind === 'evaluation_prepare_public' && value.payload.dataset_id === spec.id); if (!job) return status; return { ...status, task_id: job.id, status: job.status === 'running' ? 'preparing' : ['queued', 'failed', 'cancelled', 'interrupted'].includes(job.status) ? job.status : status.status!, progress: job.progress, error_code: job.status === 'failed' ? 'public_dataset_prepare_failed' : status.error_code! }; }
  prepareOpen(ctx: AuthContext, id: string): Promise<JsonObject> { return this.publicDatasets.prepare(ctx, id); }
  queuePrepareOpen(ctx: AuthContext, id: string, requestId: string = randomUUID()): JsonObject {
    if (this.closed) return fail(503, 'evaluation_closed', 'Evaluation is closed'); this.auth.assertCan(ctx, 'eval.write'); const spec = this.publicDatasets.spec(id), status = this.publicDatasets.status(ctx, id); if (status.ready) return status;
    const job = this.jobs.create({ scope: { tenantId: ctx.tenantId, userId: ctx.userId }, requestId, kind: 'evaluation_prepare_public', recoveryPolicy: 'safe', payload: { dataset_id: spec.id, context: { tenantId: ctx.tenantId, userId: ctx.userId, deviceId: ctx.deviceId, role: '', isSystemAdmin: false } } }); return { ...status, task_id: job.id, run_id: job.id, status: job.status, progress: job.progress };
  }
  generate(ctx: AuthContext, input: JsonObject, kind = 'testsets', options: { signal?: AbortSignal } = {}): Promise<JsonObject> {
    if (this.closed) return Promise.reject(fail(503, 'evaluation_closed', 'Evaluation is closed'));
    const controller = new AbortController(), abort = () => controller.abort(); this.controllers.add(controller); options.signal?.addEventListener('abort', abort, { once: true }); if (options.signal?.aborted) abort();
    const work = this.generation.generate(ctx, input, controller.signal, kind); this.calls.add(work);
    void work.finally(() => { this.calls.delete(work); this.controllers.delete(controller); options.signal?.removeEventListener('abort', abort); }).catch(() => {}); return work;
  }
  private preflight(ctx: AuthContext, raw: JsonObject): { input: JsonObject; state: JsonObject; estimate: JsonObject } {
    if (this.closed) return fail(503, 'evaluation_closed', 'Evaluation is closed');
    this.auth.assertCan(ctx, 'read'); const source = object(raw.source);
    const seed = Number(raw.seed ?? source.seed ?? 20260819); if (!Number.isSafeInteger(seed)) return fail(400, 'invalid_configuration', 'Selection seed must be a safe integer');
    let kbId: string, entries: JsonObject[], fingerprint: JsonObject, normalizedSource: JsonObject;
    const isPublic = ['open_dataset', 'public_dataset', 'open_rag_benchmark'].includes(String(source.type));
    if (isPublic) {
      const spec = this.publicDatasets.spec(String(source.dataset_id || 'open_rag_benchmark_180'));
      if (source.dataset_version !== undefined && String(source.dataset_version) !== spec.version) return fail(400, 'invalid_configuration', 'Public dataset version does not match the pinned manifest');
      const publicSource = this.publicDatasets.materialize(ctx, spec.id, Number(raw.sample_size ?? source.sample_size ?? spec.expectedQueries), seed);
      kbId = `public-${digest(publicSource.spec.id).slice(0, 32)}`; entries = publicSource.entries; fingerprint = publicSource.fingerprint;
      normalizedSource = { type: 'open_dataset', dataset_id: publicSource.spec.id, dataset_version: publicSource.spec.version, knowledge_base_id: kbId, sample_size: entries.length, seed };
    } else {
      if (source.type !== 'tenant_dataset') return fail(400, 'invalid_configuration', 'A published tenant dataset or pinned public dataset is required');
      const row = this.datasets.row(ctx, String(source.dataset_id || '')), data = object(row.data);
      if (row.status !== 'published' || data.schema_version !== 'evaluation_v2') return fail(422, 'dataset_not_published', 'Dataset must be published before evaluation');
      if (source.dataset_version !== undefined && String(source.dataset_version) !== String(data.version)) return fail(400, 'invalid_configuration', 'Published dataset version does not match');
      kbId = String(source.knowledge_base_id || ''); if (kbId !== data.knowledge_base_id) return fail(400, 'invalid_configuration', 'Dataset knowledge base does not match');
      this.datasets.kb(ctx, kbId); entries = data.entries as JsonObject[];
      if (entries.length < 5 || entries.length > 100 || new Set(entries.map(entry => String(entry.question).trim().toLowerCase())).size < 5 || entries.some(entry => entry.status !== 'approved' || this.datasets.validation(ctx, entry, kbId).length)) return fail(422, 'unverified_eval_dataset', 'Evaluation requires five to one hundred valid approved questions with at least five distinct questions and current source evidence');
      fingerprint = { dataset_id: String(row.id), dataset_hash: data.dataset_hash!, dataset_version: data.version!, ...corpusFingerprint(this.db, ctx, kbId) };
      normalizedSource = { type: 'tenant_dataset', dataset_id: String(row.id), knowledge_base_id: kbId, dataset_version: String(data.version) };
    }
    const strategy = String(raw.retrieval_strategy || 'hybrid'), rerank = raw.rerank_enabled !== false;
    if (!['keyword', 'vector', 'hybrid'].includes(strategy)) return fail(400, 'invalid_configuration', 'Unsupported retrieval strategy');
    if (raw.rerank_enabled !== undefined && typeof raw.rerank_enabled !== 'boolean') return fail(400, 'invalid_configuration', 'Rerank flag must be boolean');
    if (raw.chunking_strategies !== undefined && (!Array.isArray(raw.chunking_strategies) || !raw.chunking_strategies.length || raw.chunking_strategies.some(value => typeof value !== 'string'))) return fail(400, 'invalid_configuration', 'Chunking strategies must be a nonempty string array');
    const legacy = raw.chunking_strategies as string[] | undefined;
    const primary = String(raw.primary_chunking_strategy || legacy?.[0] || (isPublic ? 'auto_parent_child' : 'stored'));
    if (!evaluationStrategies.includes(primary as typeof evaluationStrategies[number]) || isPublic && primary === 'stored') return fail(400, 'invalid_configuration', 'Unsupported primary chunking strategy');
    if (raw.comparison_chunking_strategies !== undefined && !Array.isArray(raw.comparison_chunking_strategies)) return fail(400, 'invalid_configuration', 'Comparison strategies must be an array');
    const comparisons = [...new Set((raw.comparison_chunking_strategies as string[] || legacy?.slice(1) || []).map(String))];
    if (legacy && digest([...new Set(legacy)]) !== digest([...new Set([primary, ...comparisons])])) return fail(400, 'invalid_configuration', 'Legacy and explicit chunking strategies disagree');
    if (comparisons.length > 7 || comparisons.some(value => !evaluationStrategies.includes(value as typeof evaluationStrategies[number]) || isPublic && value === 'stored')) return fail(400, 'invalid_configuration', 'Unsupported comparison chunking strategy');
    const input: JsonObject = { source: normalizedSource, sample_size: entries.length, seed, retrieval_strategy: strategy, rerank_enabled: rerank, primary_chunking_strategy: primary, comparison_chunking_strategies: comparisons, answer_model_id: String(raw.answer_model_id || 'KnowledgeQA'), judge_model_id: String(raw.judge_model_id || 'KnowledgeQA') };
    const missing: string[] = [], configurations: JsonObject = {};
    for (const [label, choice] of [['answer', input.answer_model_id], ['judge', input.judge_model_id], ['embedding', 'Embedding'], ...(rerank ? [['rerank', 'Rerank']] : [])]) {
      try {
        const configuration = this.models.configuration(ctx, String(choice)); new ModelRuntime(configuration);
        if ((label === 'answer' || label === 'judge') && configuration.type !== 'KnowledgeQA' || label === 'embedding' && configuration.type !== 'Embedding' || label === 'rerank' && configuration.type !== 'Rerank') throw new Error('Incorrect model type');
        if (label === 'embedding' && (!Number.isSafeInteger(Number(configuration.parameters.dimension)) || Number(configuration.parameters.dimension) < 1 || Number(configuration.parameters.dimension) > 65536)) throw new Error('Embedding dimension is required');
        configurations[String(label)] = { id: configuration.id, signature: digest(configuration), type: configuration.type };
      } catch { missing.push(String(label)); }
    }
    if (!this.bridge) missing.push('ragas_worker'); if (missing.length) return fail(422, 'needs_configuration', `Evaluation needs configuration: ${missing.join(', ')}`);
    const indexState = this.index.state({ tenantId: ctx.tenantId, knowledgeBaseIds: [kbId] })[0];
    if (strategy !== 'keyword' && [primary, ...comparisons].includes('stored') && (!indexState || indexState.status !== 'ready')) return fail(422, 'needs_configuration', 'Evaluation vector index must be ready');
    if (indexState) object(configurations.embedding).index_signature = indexState.model_signature;
    const effective: JsonObject = { source: input.source!, primary_chunking_strategy: primary, comparison_chunking_strategies: comparisons, full_corpus: true, selection_algorithm: 'python_random_integer_seed_shuffle_v1', seed, comparison_metrics: 'retrieval_and_resources_only', retrieval_strategy: strategy, rerank_enabled: rerank, answer_model_id: object(configurations.answer).id!, judge_model_id: object(configurations.judge).id!, embedding_model_id: object(configurations.embedding).id!, metrics: ['faithfulness', 'answer_relevancy', 'context_precision'], ragas_version: '0.4.3', context_policy: { max_contexts: 5, per_context_codepoints: 2000, total_codepoints: 6000 }, keyword_top_k: strategy === 'vector' ? 0 : 80, vector_top_k: strategy === 'keyword' ? 0 : 80, rerank_top_k: rerank ? 40 : 0, top_k: 20, rrf_k: 60 };
    const retrievalVariants = new Set([primary, ...comparisons]).size;
    const perSample = 1 + 2 + 3 + 2 + 5 + retrievalVariants * ((strategy === 'keyword' ? 0 : 1) + (rerank ? 1 : 0));
    return { input, state: { configurations, fingerprint, effective_pipeline: effective, entries, answers: {} }, estimate: { sample_size: entries.length, source: input.source!, requested_configuration: input, effective_pipeline: effective, estimated_model_requests: { lower_bound: entries.length * (perSample - 4), upper_bound: entries.length * perSample, basis: 'one answer; Ragas three metrics with three relevance generations; up to five retrieved contexts', not_vendor_billing: true, excludes_corpus_index_and_semantic_embedding: primary !== 'stored' || comparisons.some(value => value !== 'stored'), corpus_embedding_requests: strategy === 'keyword' && ![primary, ...comparisons].includes('semantic_parent_child') && ![primary, ...comparisons].includes('auto_parent_child') ? 0 : null }, can_resume: true, recovery_policy: 'manual' } };
  }
  async estimate(ctx: AuthContext, input: JsonObject): Promise<JsonObject> { return this.preflight(ctx, input).estimate; }
  async createRun(ctx: AuthContext, input: JsonObject, requestId: string = randomUUID()): Promise<JsonObject> { this.auth.assertCan(ctx, 'eval.write'); this.preflight(ctx, input); await this.bridge!.capabilities(); this.auth.assertCan(ctx, 'eval.write'); const ready = this.preflight(ctx, input); return this.store.create(ctx, ready.input, ready.state, requestId); }
  createLegacyRun(ctx: AuthContext, input: JsonObject, requestId: string = randomUUID()): Promise<JsonObject> {
    if (input.source) return this.createRun(ctx, input, requestId);
    const id = input.dataset_id ?? input.testset_id;
    const source: JsonObject = input.open_dataset_id ? { type: 'open_dataset', dataset_id: input.open_dataset_id } : { type: 'tenant_dataset', dataset_id: id ?? '', knowledge_base_id: id ? object(this.datasets.row(ctx, String(id)).data).knowledge_base_id! : input.knowledge_base_id ?? '' };
    return this.createRun(ctx, { ...input, source }, requestId);
  }
  runDeterministic(ctx: AuthContext, kind: 'retrieval' | 'chunking', input: JsonObject, requestId: string = randomUUID(), options: { signal?: AbortSignal } = {}): Promise<JsonObject> {
    if (this.closed) return Promise.reject(fail(503, 'evaluation_closed', 'Evaluation is closed'));
    const controller = new AbortController(), abort = () => controller.abort(); this.controllers.add(controller); options.signal?.addEventListener('abort', abort, { once: true }); if (options.signal?.aborted) abort();
    const work = this.deterministic.run(ctx, kind, input, requestId, controller.signal); this.calls.add(work);
    void work.finally(() => { this.calls.delete(work); this.controllers.delete(controller); options.signal?.removeEventListener('abort', abort); }).catch(() => {}); return work;
  }
  private execute(context: JobContext): Promise<JsonObject> {
    const controller = new AbortController(), abort = () => controller.abort(); this.controllers.add(controller); context.signal.addEventListener('abort', abort, { once: true }); if (context.signal.aborted) abort();
    const work = this.executor.execute({ ...context, signal: controller.signal }); this.calls.add(work);
    void work.finally(() => { this.calls.delete(work); this.controllers.delete(controller); context.signal.removeEventListener('abort', abort); }).catch(() => {}); return work;
  }
  status(ctx: AuthContext, runId: string): JsonObject { return this.store.status(ctx, runId); }
  active(ctx: AuthContext): JsonObject { this.auth.assertCan(ctx, 'read'); return { runs: this.jobs.list({ tenantId: ctx.tenantId, userId: ctx.userId }).filter(job => job.kind === 'rag_evaluation' && ['queued', 'running'].includes(job.status)).map(job => this.status(ctx, job.id)) }; }
  cancel(ctx: AuthContext, runId: string): JsonObject { this.auth.assertCan(ctx, 'eval.write'); this.store.row(ctx, runId); const job = this.jobs.get(runId, { tenantId: ctx.tenantId, userId: ctx.userId }); this.jobs.cancelByRequest(job.requestId, job.scope); return this.status(ctx, runId); }
  resume(ctx: AuthContext, runId: string, input: JsonObject = {}): JsonObject {
    this.auth.assertCan(ctx, 'eval.write'); const row = this.store.row(ctx, runId), job = this.jobs.get(runId, { tenantId: ctx.tenantId, userId: ctx.userId });
    if (!['failed', 'interrupted', 'cancelled'].includes(job.status)) return fail(409, 'resume_forbidden', 'Only stopped evaluation runs can be resumed');
    const state = this.store.checkpoint(row), calls = object(state.calls), unknown = this.store.unknown(row, state);
    if (unknown && input.acknowledge_unknown_paid_request !== true) return fail(409, 'paid_result_unknown', 'An earlier paid request outcome is unknown; explicitly acknowledge a possible duplicate charge before manual resume');
    const ready = this.preflight(ctx, object(object(row.data).requested_configuration));
    if (digest(ready.state.fingerprint) !== digest(state.fingerprint) || digest(ready.state.configurations) !== digest(state.configurations)) return fail(409, 'checkpoint_mismatch', 'Evaluation source or model changed; create a new run');
    this.store.acknowledge(row, state);
    state.context = { userId: ctx.userId, tenantId: ctx.tenantId, deviceId: ctx.deviceId, role: '', isSystemAdmin: false }; this.store.save(row, state);
    if (job.status === 'cancelled') {
      const created = this.store.create(ctx, ready.input, state, randomUUID()), next = this.store.row(ctx, String(created.run_id));
      const resumed = this.store.checkpoint(next); resumed.calls = calls; resumed.answers = state.answers!; this.store.save(next, resumed); return { ...created, resume_of: runId };
    }
    this.jobs.retry(runId, job.scope); return this.status(ctx, runId);
  }
  history(ctx: AuthContext): JsonObject { return this.store.history(ctx); }
  getReport(ctx: AuthContext, reportId: string): JsonObject { return this.store.report(ctx, reportId); }
  downloadReport(ctx: AuthContext, reportId: string): { bytes: Buffer; mimeType: string; filename: string } { return this.store.download(ctx, reportId); }
  deleteReport(ctx: AuthContext, reportId: string): JsonObject { return this.store.deleteReport(ctx, reportId); }
  async close(): Promise<void> { this.closed = true; const registry = registries.get(this.jobs); if (registry?.current === this) registry.current = undefined; this.controllers.forEach(controller => controller.abort()); await Promise.all([this.bridge?.close(), this.publicDatasets.close()]); await Promise.allSettled([...this.calls]); }
}
