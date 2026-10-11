import type { SearchIndex } from './search-index.js';
import type { SearchScope, SearchHit, SearchOptions, SearchResult } from './types.js';
import { RetrievalError, bounded, cancelled, pack } from './internal.js';

export interface FusedRank { chunk_id: string; keyword_rank: number | null; vector_rank: number | null; rrf_score: number; match_sources: string[] }
export function rrfFuse(keyword: string[], vector: string[], k = 60): FusedRank[] {
  bounded(k, 60, 1, 10000);
  const fused = new Map<string, FusedRank>();
  for (const [source, ranked] of [['keyword', keyword], ['vector', vector]] as const) {
    [...new Set(ranked)].forEach((id, index) => {
      const entry = fused.get(id) ?? { chunk_id: id, keyword_rank: null, vector_rank: null, rrf_score: 0, match_sources: [] };
      if (source === 'keyword') entry.keyword_rank = index + 1; else entry.vector_rank = index + 1;
      entry.rrf_score += 1 / (k + index + 1); entry.match_sources.push(source); fused.set(id, entry);
    });
  }
  return [...fused.values()].sort((a, b) => b.rrf_score - a.rrf_score || Math.min(a.keyword_rank ?? Infinity, a.vector_rank ?? Infinity) - Math.min(b.keyword_rank ?? Infinity, b.vector_rank ?? Infinity) || a.chunk_id.localeCompare(b.chunk_id));
}
function threshold(value: number | undefined): number {
  const n = value ?? 0;
  if (typeof n !== 'number' || !Number.isFinite(n) || n < 0 || n > 1) throw new RetrievalError('invalid_threshold', 'Retrieval threshold must be a finite value between zero and one');
  return n;
}
/** Preserve retrieval_config.filter_ranked_by_threshold, including its inclusive boundary. */
function filterRanked(rows: SearchHit[], minimum: number, field: 'keyword_stage_rank_score' | 'vector_stage_rank_score' | 'rerank_stage_rank_score'): SearchHit[] {
  return rows.map((row, index) => ({ ...row, [field]: (rows.length - index) / rows.length })).filter(row => row[field]! >= minimum);
}

export class RetrievalService {
  constructor(readonly index: SearchIndex) {}
  async search(scope: SearchScope, query: string, options: SearchOptions = {}): Promise<SearchResult> {
    cancelled(options.signal);
    const strategy = options.strategy ?? 'hybrid';
    if (!['keyword', 'vector', 'hybrid'].includes(strategy)) throw new RetrievalError('invalid_strategy', 'Retrieval strategy must be keyword, vector or hybrid');
    if (typeof query !== 'string') throw new RetrievalError('invalid_query', 'Retrieval query must be text');
    if (options.deferContext !== undefined && typeof options.deferContext !== 'boolean') throw new RetrievalError('invalid_context_mode', 'Deferred context must be a boolean');
    const thresholds = { keyword: threshold(options.keywordThreshold), vector: threshold(options.vectorThreshold), rerank: threshold(options.rerankThreshold) };
    const top = bounded(options.topK, 10, 1, 200), keywordN = bounded(options.keywordTopK, top * 4), vectorN = bounded(options.vectorTopK, top * 4), rerankN = bounded(options.rerankTopK, top * 4), k = bounded(options.rrfK, 60, 1, 10000);
    const words = query.match(/[\p{L}\p{N}_]+/gu) ?? [];
    const bm25 = Array.from(query.trim()).length >= 3 && words.some(word => Array.from(word).length >= 3) && words.every(word => Array.from(word).length >= 3);
    const meta: SearchResult['meta'] = { degraded: false, degradations: [], candidate_counts: { keyword: 0, vector: 0, fused: 0, rerank_input: 0 }, usage: {}, strategy, effective_strategy: 'none', threshold_metric: 'normalized_stage_rank', thresholds, score_metrics: { keyword: bm25 ? 'fts5_bm25' : 'scoped_like', vector: 'l2_distance', rerank: 'provider_relevance_score' }, filtered_counts: { keyword: 0, vector: 0, rerank: 0 } };
    const degrade = (stage: string, reason: string) => { meta.degraded = true; meta.degradations.push({ stage, reason }); };
    // Explicit [] is a cancellation of the knowledge selection, before any provider work.
    if (scope.knowledgeBaseIds?.length === 0) return { results: [], meta };
    const useKeyword = strategy !== 'vector' && keywordN > 0 && !!query.trim(), useVector = strategy !== 'keyword' && vectorN > 0 && !!query.trim();
    const keywordRaw = useKeyword ? this.index.keyword(scope, query, keywordN) : [];
    let vectorRaw: SearchHit[] = [], vectorSucceeded = false;
    if (useVector) {
      if (!options.embedding) degrade('vector', 'embedding_model_not_configured');
      else try {
        if (this.index.embeddingModelIds(scope).length > 1) throw new RetrievalError('mixed_embedding_spaces', 'Scope pins different embedding models');
        this.index.checkSpace(scope, options.embedding, { verifyFingerprints: true });
        if (this.index.db.sqlite.inTransaction) throw new RetrievalError('network_in_transaction', 'Embedding must run outside a transaction');
        const embedded = await options.embedding.runtime.embed([query], { signal: options.signal }); cancelled(options.signal);
        // A provider response is a usage fact even if the returned vector fails validation.
        meta.usage.embedding = embedded.usage;
        if (embedded.vectors.length !== 1) throw new RetrievalError('embedding_count_mismatch', 'Query embedding count does not match');
        pack(embedded.vectors[0]!, options.embedding.dimension);
        vectorRaw = this.index.vector(scope, embedded.vectors[0]!, options.embedding, vectorN); vectorSucceeded = true;
      } catch (error) { cancelled(options.signal); degrade('vector', error instanceof RetrievalError ? error.code : 'embedding_call_failed'); }
    }
    meta.effective_strategy = useKeyword && vectorSucceeded ? 'hybrid' : useKeyword ? 'keyword' : vectorSucceeded ? 'vector' : 'none';
    const keyword = filterRanked(keywordRaw, thresholds.keyword, 'keyword_stage_rank_score'), vector = filterRanked(vectorRaw, thresholds.vector, 'vector_stage_rank_score');
    meta.filtered_counts.keyword = keywordRaw.length - keyword.length; meta.filtered_counts.vector = vectorRaw.length - vector.length;
    meta.candidate_counts.keyword = keyword.length; meta.candidate_counts.vector = vector.length;
    const keywordById = new Map(keyword.map(row => [row.chunk_id, row])), vectorById = new Map(vector.map(row => [row.chunk_id, row]));
    const fused = rrfFuse(keyword.map(row => row.chunk_id), vector.map(row => row.chunk_id), k);
    meta.candidate_counts.fused = fused.length;
    let candidates: SearchHit[] = fused.flatMap(entry => {
      const row = this.index.hydrate(scope, entry.chunk_id), keywordHit = keywordById.get(entry.chunk_id), vectorHit = vectorById.get(entry.chunk_id);
      return row ? [{ ...row, ...entry, score: entry.rrf_score, ...(keywordHit ? { keyword_stage_rank_score: keywordHit.keyword_stage_rank_score } : {}), ...(vectorHit ? { distance: vectorHit.distance, vector_stage_rank_score: vectorHit.vector_stage_rank_score } : {}) }] : [];
    });
    if (rerankN && candidates.length) {
      if (!options.reranker) degrade('rerank', 'rerank_model_not_configured');
      else try {
        if (this.index.db.sqlite.inTransaction) throw new RetrievalError('network_in_transaction', 'Rerank must run outside a transaction');
        const input = candidates.slice(0, rerankN); meta.candidate_counts.rerank_input = input.length;
        const result = await options.reranker.rerank(query, input.map(row => row.content), { signal: options.signal }); cancelled(options.signal);
        meta.usage.rerank = result.usage;
        const seen = new Set<number>();
        const ranked = result.results.map(item => {
          if (!Number.isInteger(item.index) || item.index < 0 || item.index >= input.length || seen.has(item.index) || !Number.isFinite(item.relevance_score)) throw new RetrievalError('rerank_result_invalid', 'Rerank indices or scores are invalid');
          seen.add(item.index); return { ...input[item.index]!, score: item.relevance_score, rerank_score: item.relevance_score };
        });
        if (seen.size !== input.length) throw new RetrievalError('rerank_result_incomplete', 'Rerank did not return every candidate');
        const filtered = filterRanked(ranked, thresholds.rerank, 'rerank_stage_rank_score'); meta.filtered_counts.rerank = ranked.length - filtered.length;
        // Legacy contract filters the scored cohort only; untouched tail keeps its RRF order.
        candidates = [...filtered, ...candidates.slice(input.length)];
      } catch (error) { cancelled(options.signal); degrade('rerank', error instanceof RetrievalError ? error.code : 'rerank_call_failed'); }
    }
    cancelled(options.signal);
    // Refresh enablement/scope and source text after every network wait, preserving only actual ranking facts.
    candidates = candidates.flatMap(row => { const fresh = this.index.hydrate(scope, row.chunk_id); return fresh ? [{ ...fresh, score: row.score, rrf_score: row.rrf_score, rerank_score: row.rerank_score, keyword_rank: row.keyword_rank, vector_rank: row.vector_rank, match_sources: row.match_sources, ...(row.distance !== undefined ? { distance: row.distance } : {}), ...(row.keyword_stage_rank_score !== undefined ? { keyword_stage_rank_score: row.keyword_stage_rank_score } : {}), ...(row.vector_stage_rank_score !== undefined ? { vector_stage_rank_score: row.vector_stage_rank_score } : {}), ...(row.rerank_stage_rank_score !== undefined ? { rerank_stage_rank_score: row.rerank_stage_rank_score } : {}) }] : []; });
    const ordered = candidates.map((row, index) => ({ ...row, final_rank: index + 1 }));
    return { results: options.deferContext === true ? ordered : this.index.resolveParents(scope, ordered, options.maxContextChars ?? 4096).slice(0, top), meta };
  }
}
