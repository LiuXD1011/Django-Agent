import { randomUUID } from 'node:crypto';
import { readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import type { AuthContext, JsonObject, ModelConfiguration, ModelUsage } from '../contracts.js';
import type { SearchIndex } from '../retrieval/search-index.js';
import type { EmbeddingBinding, SearchHit, SearchScope } from '../retrieval/types.js';
import { RetrievalService } from '../retrieval/service.js';
import { keywordTerms } from '../retrieval/keyword-query.js';
import { ModelRuntime } from '../models/runtime.js';
import type { ModelConfigurationService } from '../settings/index.js';
import type { EvaluationDatasets } from './datasets.js';
import type { EvaluationStore } from './store.js';
import type { PublicEvaluationDatasets } from './public-datasets.js';
import { corpusFingerprint } from './fingerprint.js';
import { IsolatedEvaluationIndex, evaluationStrategies } from './isolated-index.js';
import { releaseGates } from './release-gates.js';
import { digest, fail, now, object } from './common.js';

const emptyUsage: ModelUsage = { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, cached_tokens: 0, reasoning_tokens: 0 };
/** Deterministic retrieval/source-span comparison. Never calls an answer, judge or Ragas worker. */
export class DeterministicEvaluation {
  constructor(readonly store: EvaluationStore, readonly datasets: EvaluationDatasets, readonly models: ModelConfigurationService, readonly index: SearchIndex, readonly publicDatasets: PublicEvaluationDatasets) {}
  async run(ctx: AuthContext, kind: 'retrieval' | 'chunking', input: JsonObject, requestId: string, signal: AbortSignal): Promise<JsonObject> {
    const db = this.store.db, auth = this.store.auth; auth.assertCan(ctx, 'eval.write'); signal.throwIfAborted();
    const source = object(input.source); let entries: JsonObject[], verified = true;
    let kbId = String(source.knowledge_base_id || input.knowledge_base_id || '');
    const publicId = input.open_dataset_id ?? (['open_dataset', 'public_dataset', 'open_rag_benchmark'].includes(String(source.type)) ? source.dataset_id : undefined);
    const publicSource = publicId ? this.publicDatasets.materialize(ctx, String(publicId), input.sample_size === undefined ? undefined : Number(input.sample_size), Number(input.seed ?? 20260819)) : undefined;
    if (publicSource) {
      if (source.dataset_version !== undefined && source.dataset_version !== publicSource.spec.version) return fail(409, 'dataset_version_mismatch', 'Pinned public dataset version does not match');
      kbId = `public-${digest(publicSource.spec.id).slice(0, 32)}`; entries = publicSource.entries;
    } else if (source.dataset_id || input.dataset_id) {
      const row = this.datasets.row(ctx, String(source.dataset_id || input.dataset_id)), data = object(row.data);
      if (row.status !== 'published' || data.schema_version !== 'evaluation_v2') return fail(422, 'dataset_not_published', 'A published source-evidence dataset is required');
      if (kbId && kbId !== data.knowledge_base_id) return fail(400, 'invalid_configuration', 'Dataset knowledge base does not match');
      if (source.dataset_version !== undefined && String(source.dataset_version) !== String(data.version)) return fail(409, 'dataset_version_mismatch', 'Dataset version does not match');
      kbId = String(data.knowledge_base_id); entries = data.entries as JsonObject[];
      if (!entries.length || entries.some(entry => entry.status !== 'approved' || this.datasets.validation(ctx, entry, kbId).length)) return fail(422, 'unverified_eval_dataset', 'Current approved answers and source evidence are required');
    } else {
      if (!Array.isArray(input.dataset) || !input.dataset.length || input.dataset.length > 100) return fail(422, 'unverified_eval_dataset', 'Provide a published dataset or bounded explicit annotations; placeholder defaults are not evaluable');
      entries = input.dataset.map(raw => {
        const entry = object(raw), query = entry.query ?? entry.question;
        if (typeof query !== 'string' || !query.trim() || Array.from(query).length > 16384) return fail(400, 'invalid_evaluation_input', 'An annotated query is required');
        const ids = Array.isArray(entry.kb_ids) ? entry.kb_ids : [];
        if (!kbId && ids.length === 1) kbId = String(ids[0]);
        if (ids.some(value => value !== kbId)) return fail(400, 'invalid_configuration', 'Explicit annotations must select one knowledge base');
        this.datasets.kb(ctx, kbId);
        if (Array.isArray(entry.relevant_chunk_ids) && kind === 'retrieval') {
          verified = false;
          if (!entry.relevant_chunk_ids.length || entry.relevant_chunk_ids.length > 50) return fail(422, 'unverified_eval_dataset', 'Relevant chunks are required');
          for (const id of entry.relevant_chunk_ids) if (typeof id !== 'string' || !this.index.hydrate({ tenantId: ctx.tenantId, knowledgeBaseIds: [kbId] }, id)) return fail(404, 'evaluation_source_not_found', 'Annotated chunk is unavailable');
          return { ...entry, id: String(entry.id || randomUUID()), question: query };
        }
        if (!Array.isArray(entry.documents) || !entry.documents.length || !Array.isArray(entry.evidence) || !entry.evidence.length || entry.evidence.length > 50) return fail(422, 'unverified_eval_dataset', 'Versioned documents and source spans are required');
        for (const rawEvidence of entry.evidence) {
          const evidence = object(rawEvidence), document = db.read('knowledges', String(evidence.knowledge_id)), version = entry.documents.map(object).find(value => value.knowledge_id === evidence.knowledge_id), metadata = object(document?.metadata), content = metadata.content ?? object(metadata.parser_document).canonical_text;
          if (!document || document.deleted_at !== null || String(document.tenant_id) !== ctx.tenantId || document.knowledge_base_id !== kbId || document.enable_status !== 'enabled') return fail(404, 'evaluation_source_not_found', 'Annotated document is unavailable');
          if (!version || typeof version.file_hash !== 'string' || !version.file_hash || version.file_hash !== document.file_hash) return fail(422, 'unverified_eval_dataset', 'Document version does not match');
          if (typeof content !== 'string' || typeof evidence.source_start !== 'number' || typeof evidence.source_end !== 'number' || !Number.isSafeInteger(evidence.source_start) || !Number.isSafeInteger(evidence.source_end) || evidence.source_start < 0 || evidence.source_end <= evidence.source_start || evidence.source_end > Array.from(content).length || typeof evidence.answer_evidence === 'string' && Array.from(content).slice(evidence.source_start, evidence.source_end).join('') !== evidence.answer_evidence) return fail(422, 'unverified_eval_dataset', 'Source span does not match canonical text');
        }
        return { ...entry, id: String(entry.id || randomUUID()), question: query };
      });
    }
    if (!publicSource) this.datasets.kb(ctx, kbId);
    const strategy = String(input.retrieval_strategy || input.strategy || 'hybrid'), rerank = input.rerank_enabled !== false;
    if (!['keyword', 'vector', 'hybrid'].includes(strategy) || input.rerank_enabled !== undefined && typeof input.rerank_enabled !== 'boolean') return fail(400, 'invalid_configuration', 'Unsupported retrieval configuration');
    const rawStrategies = input.strategies ?? input.chunking_strategies ?? [input.primary_chunking_strategy || 'fixed_window', ...(Array.isArray(input.comparison_chunking_strategies) ? input.comparison_chunking_strategies : ['recursive', 'auto_parent_child', 'semantic_parent_child'])];
    const strategies = kind === 'retrieval' ? [publicSource ? 'fixed_window' : 'stored'] : Array.isArray(rawStrategies) ? rawStrategies : [];
    if (!strategies.length || strategies.length > 7 || new Set(strategies).size !== strategies.length || strategies.some(value => typeof value !== 'string' || value === 'stored' && kind === 'chunking' || !evaluationStrategies.includes(value as typeof evaluationStrategies[number]))) return fail(400, 'invalid_configuration', 'Unique supported isolated strategies are required');
    const configuration = (role: string): ModelConfiguration => { try { const value = this.models.configuration(ctx, role); if (value.type !== role) throw new Error(); new ModelRuntime(value); return value; } catch { return fail(422, 'needs_configuration', `Evaluation needs configuration: ${role}`); } };
    const embeddingConfig = strategy !== 'keyword' || strategies.includes('semantic_parent_child') || strategies.includes('auto_parent_child') ? configuration('Embedding') : undefined;
    const rerankConfig = rerank ? configuration('Rerank') : undefined;
    const dimension = Number(embeddingConfig?.parameters.dimension);
    if (embeddingConfig && (!Number.isSafeInteger(dimension) || dimension < 1 || dimension > 65536)) return fail(422, 'needs_configuration', 'Embedding dimension is required');
    const corpus = publicSource?.fingerprint ?? corpusFingerprint(db, ctx, kbId), datasetId = source.dataset_id ?? input.dataset_id, dataset = datasetId && !publicSource ? this.datasets.row(ctx, String(datasetId)) : undefined;
    const fingerprint: JsonObject = { ...corpus, ...(dataset ? { dataset_id: String(dataset.id), dataset_hash: object(dataset.data).dataset_hash!, dataset_version: object(dataset.data).version! } : {}) }, modelSignatures = [embeddingConfig, rerankConfig].filter(Boolean).map(value => ({ id: value!.id, signature: digest(value) }));
    const check = () => { signal.throwIfAborted(); auth.assertCan(ctx, 'eval.write'); if (!publicSource) this.datasets.kb(ctx, kbId); if ((publicSource ? this.publicDatasets.status(ctx, publicSource.spec.id).ready !== true : digest(corpusFingerprint(db, ctx, kbId)) !== digest(corpus)) || dataset && object(this.datasets.row(ctx, String(dataset.id)).data).dataset_hash !== fingerprint.dataset_hash) return fail(409, 'evaluation_source_changed', 'Evaluation corpus changed'); for (const value of modelSignatures) if (digest(this.models.configuration(ctx, value.id)) !== value.signature) return fail(409, 'evaluation_configuration_changed', 'Evaluation model changed'); };
    if (strategy !== 'keyword' && kind === 'retrieval' && !publicSource && this.index.state({ tenantId: ctx.tenantId, knowledgeBaseIds: [kbId] })[0]?.status !== 'ready') return fail(422, 'needs_configuration', 'Evaluation vector index must be ready');
    const runId = `det-eval-${digest([ctx.tenantId, ctx.userId, kind, requestId])}`, existing = db.read('generic_resources', runId), requestHash = digest(input);
    if (existing) {
      const previous = object(existing.data); if (previous.request_hash !== requestHash) return fail(409, 'evaluation_request_conflict', 'Request identifier belongs to different input');
      if (existing.status === 'completed') return this.store.deterministicDto(ctx, existing);
      return fail(409, 'paid_result_unknown', 'This evaluation attempt stopped or is running; do not automatically replay paid retrieval work');
    }
    db.insert('generic_resources', { id: runId, tenant_id: ctx.tenantId, resource_type: 'rag_eval_deterministic_runs', name: `${kind} evaluation`, status: 'running', data: { request_hash: requestHash, requested_configuration: input, fingerprint, evaluation_type: kind, sample_size: entries.length, report_id: null } });
    const invoke = async <T extends { usage: ModelUsage }>(config: ModelConfiguration, operation: 'embed' | 'rerank', work: (runtime: ModelRuntime) => Promise<T>): Promise<T> => {
      check(); const invocationId = randomUUID(), start = performance.now(); let usage = emptyUsage, success = false;
      const ledger = db.insert('generic_resources', { tenant_id: ctx.tenantId, resource_type: 'rag_eval_invocations', name: 'Deterministic evaluation invocation', status: 'pending', data: { ledger_id: runId, invocation_id: invocationId, operation } });
      try { const result = await work(new ModelRuntime(config)); usage = result.usage; success = true; this.models.recordUsage(ctx, config, usage, { scenario: `evaluation_${operation}`, success: true, durationMs: Math.round(performance.now() - start), invocationId, metadata: { operation } }); check(); db.update('generic_resources', String(ledger.id), { status: 'completed' }); return result; }
      catch (error) { if (!success) this.models.recordUsage(ctx, config, usage, { scenario: `evaluation_${operation}`, success: false, durationMs: Math.round(performance.now() - start), errorCode: signal.aborted ? 'evaluation_cancelled' : 'evaluation_call_failed', invocationId, metadata: { operation, result_unknown: signal.aborted } }); db.update('generic_resources', String(ledger.id), { status: success || signal.aborted ? 'unknown' : 'failed' }); throw error; }
    };
    const bound = (index: SearchIndex): EmbeddingBinding | undefined => embeddingConfig ? { modelId: embeddingConfig.id, dimension, signature: index === this.index ? String(index.state({ tenantId: ctx.tenantId, knowledgeBaseIds: [kbId] })[0]?.model_signature || digest(embeddingConfig)) : digest(embeddingConfig), runtime: { embed: (texts, options) => invoke(embeddingConfig, 'embed', runtime => runtime.embed(texts, { signal: options?.signal ?? signal })) } } : undefined;
    const indices = new Map<string, SearchIndex>([['stored', this.index]]), isolated: IsolatedEvaluationIndex[] = [], diagnostics: JsonObject = {}, scores: JsonObject = {};
    const scope: SearchScope = { tenantId: ctx.tenantId, knowledgeBaseIds: [kbId] };
    try {
      for (const selected of strategies as string[]) {
        check(); if (selected === 'stored') continue;
        const start = performance.now(), binding = bound(this.index);
        const built = await IsolatedEvaluationIndex.build(db, ctx, kbId, selected, { signal, check, documents: publicSource?.documents, embedding: strategy === 'keyword' ? undefined : binding && { ...binding, signature: digest(embeddingConfig) }, semanticDimension: dimension, semanticSignature: embeddingConfig ? digest(embeddingConfig) : '', semanticEmbed: binding ? async texts => (await binding.runtime.embed(texts, { signal })).vectors : undefined });
        isolated.push(built); indices.set(selected, built.index);
        diagnostics[selected] = { ...built.diagnostics, processing_duration_ms: performance.now() - start, index_bytes: readdirSync(built.root).reduce((sum, name) => sum + statSync(join(built.root, name)).size, 0) };
      }
      const baselineRows: JsonObject[] = [];
      for (const selected of strategies as string[]) {
        const index = indices.get(selected)!, rows: JsonObject[] = [];
        for (const entry of entries) {
          check(); const query = String(entry.question), binding = bound(index);
          const result = await new RetrievalService(index).search(scope, query, { strategy: strategy as 'keyword' | 'vector' | 'hybrid', signal, topK: 20, keywordTopK: strategy === 'vector' ? 0 : 80, vectorTopK: strategy === 'keyword' ? 0 : 80, rerankTopK: rerank ? 40 : 0, embedding: strategy === 'keyword' ? undefined : binding, reranker: rerankConfig ? { rerank: (query, documents, options) => invoke(rerankConfig, 'rerank', runtime => runtime.rerank(query, documents, { signal: options?.signal ?? signal })) } : undefined });
          check(); if (result.meta.degraded) return fail(422, 'evaluation_pipeline_degraded', 'Requested retrieval pipeline did not take effect');
          rows.push({ query, ...score(entry, result.results, index) });
          if (kind === 'retrieval') {
            const lexical = strategy === 'vector' ? [] : index.keyword(scope, query, 20), vector = strategy === 'keyword' ? [] : index.vector(scope, (await binding!.runtime.embed([query], { signal })).vectors[0]!, binding!, 20);
            check(); const values = new Map<string, { hit: SearchHit; score: number }>();
            const terms = keywordTerms(query);
            const ftsQuery = terms.map(value => `"${value.replaceAll('"', '""')}"`).join(' OR ');
            const ranks = new Map<string, number>();
            if (ftsQuery && lexical.length) {
              const seqIds = lexical.map(hit => String(index.db.read('chunks', hit.chunk_id)!.seq_id));
              for (const value of index.db.all(`SELECT rowid,bm25(chunks_fts) AS rank FROM chunks_fts WHERE chunks_fts MATCH ? AND rowid IN (${seqIds.map(() => '?').join(',')})`, ftsQuery, ...seqIds)) ranks.set(String(value.rowid), Number(value.rank));
            }
            for (const hit of lexical) values.set(hit.chunk_id, { hit, score: Math.max(0, 10 - Math.abs(ranks.get(String(index.db.read('chunks', hit.chunk_id)!.seq_id)) ?? 0)) });
            for (const hit of vector) { const previous = values.get(hit.chunk_id); values.set(hit.chunk_id, { hit, score: (previous?.score || 0) + 1 / (1 + Number(hit.distance)) }); }
            baselineRows.push(score(entry, [...values.values()].sort((a, b) => b.score - a.score || a.hit.chunk_id.localeCompare(b.hit.chunk_id)).slice(0, 20).map(value => value.hit), index));
          }
        }
        scores[selected] = { ...mean(rows), ...object(diagnostics[selected]), questions: rows.length, per_question: rows, valid_coverage: 1, verification_status: verified ? 'verified' : 'unverified', verified };
      }
      const primaryName = String(strategies[0]), primary = object(scores[primaryName]);
      const metrics: JsonObject = kind === 'chunking' ? { primary_strategy: primaryName, primary, comparisons: Object.fromEntries(Object.entries(scores).filter(([name]) => name !== primaryName)), strategies: scores, gates: releaseGates(scores) } : { ...primary, mrr_new: primary.mrr_at_10!, recall_new: primary.recall_at_20!, hit_at_10_new: primary.hit_at_10!, mrr_baseline: mean(baselineRows).mrr_at_10!, recall_baseline: mean(baselineRows).recall_at_20!, hit_at_10_baseline: mean(baselineRows).hit_at_10!, baseline_pipeline: 'bm25_conversion_plus_vector_similarity', pipeline: { retrieval_strategy: strategy, rerank_enabled: rerank, rrf_k: 60 } };
      metrics.metrics_scope = 'retrieval_and_resources_only'; metrics.full_corpus = true; metrics.samples = entries.length;
      check(); const reportId = randomUUID(), timestamp = now(), report: JsonObject = { schema_version: 'evaluation_report_v2', run_id: runId, run_resource_type: 'rag_eval_deterministic_runs', report_id: reportId, evaluation_type: kind, verification_status: verified ? 'verified' : 'unverified', verified, reasons: verified ? [] : [{ code: 'legacy_dataset', message: 'Chunk identifiers do not declare immutable source versions' }], requested_configuration: input, effective_pipeline: { retrieval_strategy: strategy, rerank_enabled: rerank, strategies, full_corpus: true, metrics_scope: 'retrieval_and_resources_only' }, source_fingerprint: fingerprint, metrics, created_at: timestamp };
      db.transaction(() => { check(); db.insert('generic_resources', { id: reportId, tenant_id: ctx.tenantId, resource_type: 'rag_eval_reports', name: `${kind} evaluation report`, status: report.verification_status, data: report }); const row = db.read('generic_resources', runId)!; db.update('generic_resources', runId, { status: 'completed', updated_at: timestamp, data: { ...object(row.data), ...report } }); });
      return this.store.deterministicDto(ctx, this.store.row(ctx, runId, 'rag_eval_deterministic_runs'));
    } catch (error) { db.update('generic_resources', runId, { status: signal.aborted ? 'cancelled' : 'failed', updated_at: now() }); throw error; }
    finally { await Promise.allSettled(isolated.map(value => value.close())); }
  }
}
function score(entry: JsonObject, hits: SearchHit[], index: SearchIndex): JsonObject {
  const evidence = Array.isArray(entry.evidence) ? entry.evidence.map(object) : [], relevant = Array.isArray(entry.relevant_chunk_ids) ? entry.relevant_chunk_ids : [];
  const matches = (hit: SearchHit, item: JsonObject) => { const chunk = index.db.read('chunks', hit.parent_chunk_id || hit.chunk_id); return hit.knowledge_id === item.knowledge_id && !!chunk && Number(chunk.start_at) < Number(item.source_end) && Number(chunk.end_at) > Number(item.source_start); };
  const good = (hit: SearchHit) => relevant.length ? relevant.includes(hit.chunk_id) : evidence.some(item => matches(hit, item));
  const rank = hits.slice(0, 10).findIndex(good), returned = hits.slice(0, 20);
  return { hit_at_10: rank >= 0 ? 1 : 0, mrr_at_10: rank >= 0 ? 1 / (rank + 1) : 0, recall_at_20: relevant.length ? new Set(returned.filter(good).map(hit => hit.chunk_id)).size / relevant.length : evidence.filter(item => returned.some(hit => matches(hit, item))).length / evidence.length, context_precision: returned.length ? returned.filter(good).length / returned.length : 0 };
}
function mean(rows: JsonObject[]): JsonObject { return Object.fromEntries(['hit_at_10', 'mrr_at_10', 'recall_at_20', 'context_precision'].map(name => [name, rows.length ? rows.reduce((sum, row) => sum + Number(row[name]), 0) / rows.length : null])); }
