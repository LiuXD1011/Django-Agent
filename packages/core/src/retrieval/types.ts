import type { JsonObject, ModelUsage } from '../contracts.js';
import type { ModelRuntime } from '../models/runtime.js';
export interface SearchScope { tenantId: string | number | bigint; knowledgeBaseIds?: string[]; }
export type RetrievalStrategy = 'keyword' | 'vector' | 'hybrid';
export interface EmbeddingBinding { signature: string; dimension: number; modelId?: string; runtime: Pick<ModelRuntime, 'embed'>; }
export type SyncPublish = (write: () => void) => void;
export interface IndexOptions { signal?: AbortSignal; publish?: SyncPublish; batchSize?: number; onUsage?: (usage: ModelUsage) => void | Promise<void>; }
export interface VectorState { id: string; tenant_id: string; knowledge_base_id: string; model_signature: string; dimension: number; generation: string; status: string; }
export interface MatchedRange { child_id: string; start_at: number; end_at: number; rendered_start_at: number; rendered_end_at: number; context_start_at: number | null; context_end_at: number | null; visible: boolean; clipped: boolean; }
export interface SearchHit {
  id: string; chunk_id: string; seq_id: string; content: string; score: number; rrf_score: number; keyword_rank: number | null; vector_rank: number | null;
  rerank_score: number | null; match_sources: string[]; retrieval_path: 'document'; knowledge_id: string; knowledge_base_id: string;
  knowledge_title: string; knowledge_description: string; knowledge_base_name: string; chunk_type: string; context_parent_id: string | null;
  image_info: JsonObject | null; metadata: JsonObject; distance?: number; final_rank?: number; parent_chunk_id?: string;
  matched_child_ids?: string[]; matched_ranges?: MatchedRange[]; matched_child_provenance?: JsonObject[];
  context_fallback?: string; context_window?: JsonObject; selected_strategy?: string; applied_edit_child_ids?: string[];
  keyword_stage_rank_score?: number; vector_stage_rank_score?: number; rerank_stage_rank_score?: number;
}
export interface SearchOptions {
  topK?: number; keywordTopK?: number; vectorTopK?: number; rerankTopK?: number; rrfK?: number; embedding?: EmbeddingBinding;
  reranker?: Pick<ModelRuntime, 'rerank'>; signal?: AbortSignal; maxContextChars?: number;
  strategy?: RetrievalStrategy;
  /** Trusted core orchestration only: keep budgeted raw candidates for Chat expansion before final context selection. */
  deferContext?: boolean;
  /** Legacy stage-relative rank cutoff: (candidate count - rank + 1) / candidate count.
   * These values are neither BM25/cosine probabilities nor raw rerank score cutoffs. */
  keywordThreshold?: number; vectorThreshold?: number; rerankThreshold?: number;
}
export interface SearchResult { results: SearchHit[]; meta: {
  degraded: boolean; degradations: Array<{ stage: string; reason: string }>;
  candidate_counts: { keyword: number; vector: number; fused: number; rerank_input: number };
  usage: { embedding?: ModelUsage; rerank?: ModelUsage };
  strategy: RetrievalStrategy; effective_strategy: RetrievalStrategy | 'none';
  threshold_metric: 'normalized_stage_rank'; thresholds: { keyword: number; vector: number; rerank: number };
  score_metrics: { keyword: 'fts5_bm25' | 'scoped_like'; vector: 'l2_distance'; rerank: 'provider_relevance_score' };
  filtered_counts: { keyword: number; vector: number; rerank: number };
}; }
