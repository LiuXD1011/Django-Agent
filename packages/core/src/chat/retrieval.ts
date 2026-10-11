import type { JsonObject } from '../contracts.js';
import { enabled } from '../knowledge/config.js';
import { bounded, joins, RetrievalError, scopeClause, searchable } from '../retrieval/internal.js';
import { RetrievalService } from '../retrieval/service.js';
import type { SearchIndex } from '../retrieval/search-index.js';
import type { SearchHit, SearchOptions } from '../retrieval/types.js';
import { object } from './internal.js';
import type { ChatExecution, ChatHooks, ChatSearchHit, ChatSearchResult } from './types.js';

const tokens = (text: string): Set<string> => new Set((text.toLowerCase().match(/[\p{L}\p{N}_]+/gu) ?? []).filter(t => Array.from(t).length > 1));
const normalize = (text: string): string => text.toLowerCase().trim().replace(/\s+/gu, ' ');
const stopwords = new Set(('的 了 在 是 我 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 没有 看 好 自己 这 他 她 它 们 那 些 什么 怎么 如何 哪 哪个 哪些 为什么 为何 请问 请 帮 想 知道 了解 the a an is are was were be been being have has had do does did will would could should may might can shall to of in for on with at by from as into through during before after above below between and but or not no nor so if then than too very what which who whom this that these those i me my we our you your he him his she her it its they them their').split(' '));
/** Legacy expansion is local text processing; it never calls a model. */
export function expandChatQuery(query: string): string[] {
  const seen = new Set([query.trim().toLowerCase()]), variants: string[] = [];
  const add = (value: string) => { const text = value.trim(), key = text.toLowerCase(); if (text && !seen.has(key)) { variants.push(text); seen.add(key); } };
  const keywords = (query.match(/[\p{L}\p{N}_]+/gu) ?? []).filter(t => !stopwords.has(t.toLowerCase()) && Array.from(t).length > 1);
  if (keywords.length >= 2) add(keywords.join(' '));
  for (const match of query.matchAll(/["「](.+?)["」]/gu)) if (Array.from(match[1]!.trim()).length >= 3) add(match[1]!);
  for (const part of query.split(/[,，;；、。！？!?\s]+/gu)) if (Array.from(part.trim()).length >= 5) add(part);
  const stripped = query.replace(/^(什么是|什么|如何|怎么|怎样|为什么|为何|哪个|哪些|谁|何时|何地|请问|请告诉我|帮我|我想知道|我想了解)/u, '').trim();
  if (Array.from(stripped).length >= 3) add(stripped);
  return variants.slice(0, 5);
}
interface RankedDocument { chunk_id: string; content: string; score: number; final_rank?: number; knowledge_id: string }
function diversify<T extends RankedDocument>(rows: T[], maximum: number): T[] {
  const counts = new Map<string, number>(); return rows.filter(row => { const n = counts.get(row.knowledge_id) ?? 0; counts.set(row.knowledge_id, n + 1); return n < maximum; });
}
/** MMR chooses a subset; actual provider rank is restored before cohort interleaving. */
export function selectChatDocuments<T extends RankedDocument>(rows: T[], top: number): T[] {
  const count = Math.min(rows.length, Math.max(1, top * 2)); let chosen = rows;
  if (rows.length > count) {
    const sets = rows.map(row => tokens(row.content));
    const low = rows.reduce((n, row) => Math.min(n, row.score), Infinity), high = rows.reduce((n, row) => Math.max(n, row.score), -Infinity), range = high - low || 1;
    const relevance = rows.map(row => (row.score - low) / range), similarity = rows.map(() => 0);
    const selected: number[] = [], remaining = new Set(rows.map((_, at) => at));
    for (let n = 0; n < count; n++) {
      let best = -1, maximum = -Infinity;
      for (const at of remaining) {
        const score = .7 * relevance[at]! - .3 * similarity[at]!;
        if (score > maximum) { best = at; maximum = score; }
      }
      if (best < 0) break; selected.push(best); remaining.delete(best);
      for (const at of remaining) { const a = sets[at]!, b = sets[best]!, intersection = [...a].filter(t => b.has(t)).length; similarity[at] = Math.max(similarity[at]!, intersection / Math.max(1, a.size + b.size - intersection)); }
    }
    chosen = selected.sort((a, b) => (rows[a]!.final_rank ?? a + 1) - (rows[b]!.final_rank ?? b + 1) || a - b).map(at => rows[at]!);
  }
  return diversify(chosen, Math.max(2, top));
}
function redundant(left: ChatSearchHit, right: ChatSearchHit): boolean {
  if (left.chunk_id === right.chunk_id || left.parent_chunk_id && left.parent_chunk_id === right.parent_chunk_id) return true;
  const a = normalize(left.content), b = normalize(right.content);
  if (!a || !b) return false;
  if (a === b || Math.min(Array.from(a).length, Array.from(b).length) >= 80 && (a.includes(b) || b.includes(a))) return true;
  const ta = tokens(a), tb = tokens(b), denominator = Math.min(ta.size, tb.size);
  return denominator > 0 && [...ta].filter(t => tb.has(t)).length / denominator >= .85;
}
function attribution(document: ChatSearchHit, graph: ChatSearchHit): ChatSearchHit {
  const provenance = [...document.graph_provenance ?? [], ...graph.graph_provenance ?? []];
  return { ...document, match_sources: [...new Set([...document.match_sources, ...graph.match_sources])],
    graph_provenance: [...new Map(provenance.map(row => [JSON.stringify(row), row])).values()] };
}
function deduplicate(rows: ChatSearchHit[]): ChatSearchHit[] {
  const kept: ChatSearchHit[] = [];
  for (const row of rows) { const index = kept.findIndex(other => redundant(row, other)); if (index < 0) kept.push(row); else if (row.graph_provenance) kept[index] = attribution(kept[index]!, row); }
  return kept;
}
/** Refresh actual source data after network waits; ranking facts never authorize a citation. */
function refresh(execution: ChatExecution, index: SearchIndex, rows: SearchHit[]): SearchHit[] {
  return rows.flatMap(row => (row.matched_child_ids ?? [row.chunk_id]).flatMap(id => {
    const fresh = index.hydrate(execution.scope, id);
    if (!fresh) return [];
    return [{ ...fresh, score: row.score, rrf_score: row.rrf_score, rerank_score: row.rerank_score, keyword_rank: row.keyword_rank,
      vector_rank: row.vector_rank, match_sources: [...row.match_sources], ...(row.final_rank === undefined ? {} : { final_rank: row.final_rank }),
      ...(row.distance === undefined ? {} : { distance: row.distance }),
      ...(row.keyword_stage_rank_score === undefined ? {} : { keyword_stage_rank_score: row.keyword_stage_rank_score }),
      ...(row.vector_stage_rank_score === undefined ? {} : { vector_stage_rank_score: row.vector_stage_rank_score }),
      ...(row.rerank_stage_rank_score === undefined ? {} : { rerank_stage_rank_score: row.rerank_stage_rank_score }) }];
  }));
}
function expandShort(execution: ChatExecution, index: SearchIndex, rows: ChatSearchHit[], cap: number): ChatSearchHit[] {
  const clause = scopeClause(execution.scope), siblings = new Map<string, string[]>();
  return rows.map(row => {
    if (row.chunk_type !== 'text' || row.parent_chunk_id || row.context_parent_id || Array.from(row.content).length >= 350) return row;
    const seed = index.hydrate(execution.scope, row.chunk_id);
    if (!seed || Array.from(seed.content).length >= 350) return row;
    let ids = siblings.get(row.knowledge_id);
    if (!ids) { ids = index.db.all(`SELECT c.id ${joins} WHERE ${clause.sql} AND ${searchable} AND c.knowledge_id=? AND c.chunk_type='text' AND c.context_parent_id IS NULL ORDER BY c.chunk_index,c.id`, ...clause.binds, row.knowledge_id).map(value => String(value.id)); siblings.set(row.knowledge_id, ids); }
    const at = ids.indexOf(row.chunk_id); if (at < 0) return row;
    const parts = [seed]; let size = Array.from(seed.content).length;
    for (const direction of [-1, 1]) for (let cursor = at + direction; cursor >= 0 && cursor < ids.length && size < 850; cursor += direction) {
      const neighbor = index.hydrate(execution.scope, ids[cursor]!);
      if (!neighbor?.content || seed.content.includes(neighbor.content)) continue;
      if (direction < 0) parts.unshift(neighbor); else parts.push(neighbor); size += Array.from(neighbor.content).length;
    }
    if (parts.length === 1) return row;
    const raw = parts.map(part => part.content).join('\n'), length = Array.from(raw).length, high = Math.min(cap, length); let offset = 0;
    const refs: JsonObject[] = parts.map(part => {
      const source = index.db.read('chunks', part.chunk_id)!, total = Array.from(part.content).length, start = offset, end = start + total; offset = end + 1;
      const visible = start < high, visibleEnd = Math.min(end, high), exact = Number(source.end_at) - Number(source.start_at) === total;
      return { chunk_id: part.chunk_id, seq_id: part.seq_id, knowledge_id: part.knowledge_id, knowledge_base_id: part.knowledge_base_id,
        source_start_at: source.start_at!, source_end_at: source.end_at!, source_range_exact: exact,
        context_start_at: visible ? start : null, context_end_at: visible ? visibleEnd : null, visible, clipped: !visible || visibleEnd < end,
        ...(exact && visible ? { visible_source_start_at: Number(source.start_at), visible_source_end_at: Number(source.start_at) + visibleEnd - start } : {}), metadata: part.metadata };
    });
    return { ...row, content: Array.from(raw).slice(0, high).join(''), expanded_chunk_ids: parts.map(part => part.chunk_id), expanded_source_refs: refs,
      context_window: { source_representation: 'adjacent_chunks', rendered_start_at: 0, rendered_end_at: high, max_context_chars: cap, clipped: high < length, clip_reason: high < length ? 'max_context_chars' : '' } };
  });
}
async function documentCandidates(execution: ChatExecution, index: SearchIndex, query: string, options: SearchOptions, top: number): Promise<{ results: SearchHit[]; meta: ChatSearchResult['meta'] }> {
  const keywordN = bounded(options.keywordTopK, top * 4), vectorN = bounded(options.vectorTopK, top * 4), rerankN = bounded(options.rerankTopK, top * 4), k = bounded(options.rrfK, 60, 1, 10000);
  const result = await new RetrievalService(index).search(execution.scope, query, { ...options, keywordTopK: keywordN, vectorTopK: vectorN, rerankTopK: 0, topK: top, deferContext: true }); execution.assert();
  let rows = result.results;
  // A finite total budget also bounds expansion when filtering leaves a sparse cohort.
  const budget = (options.strategy === 'vector' ? 0 : keywordN) + (options.strategy === 'keyword' ? 0 : vectorN);
  const groups = () => new Set(rows.map(row => row.context_parent_id ?? row.chunk_id)).size;
  if (keywordN > 0 && options.strategy !== 'vector' && groups() < top && execution.scope.knowledgeBaseIds?.length !== 0) {
    const seen = new Set(rows.map(row => row.chunk_id));
    for (const variant of expandChatQuery(query)) {
      const limit = Math.min(top * 2, keywordN, Math.max(0, budget - rows.length)); if (!limit) break;
      const extra = index.keyword(execution.scope, variant, limit), previous = rows.length;
      extra.forEach((row, at) => {
        const rank = (extra.length - at) / extra.length;
        if (rank < result.meta.thresholds.keyword) { result.meta.filtered_counts.keyword++; return; }
        if (seen.has(row.chunk_id)) return;
        const fresh = index.hydrate(execution.scope, row.chunk_id); if (!fresh) return;
        const score = 1 / (k + at + 1 + previous); seen.add(row.chunk_id);
        rows.push({ ...fresh, score, rrf_score: score, keyword_rank: at + 1, match_sources: ['keyword_expansion'], keyword_stage_rank_score: rank }); result.meta.candidate_counts.keyword++;
      });
      if (groups() >= top) break;
    }
    result.meta.candidate_counts.fused = rows.length;
  }
  if (rows.length && rerankN) {
    const degrade = (reason: string) => { result.meta.degraded = true; result.meta.degradations.push({ stage: 'rerank', reason }); };
    if (!options.reranker) degrade('rerank_model_not_configured');
    else try {
      execution.assert(); if (index.db.sqlite.inTransaction) throw new RetrievalError('network_in_transaction', 'Rerank must run outside a transaction');
      const input = rows.slice(0, rerankN); result.meta.candidate_counts.rerank_input = input.length;
      const ranked = await options.reranker.rerank(query, input.map(row => row.content), { signal: execution.signal }); result.meta.usage.rerank = ranked.usage; execution.assert();
      const seen = new Set<number>();
      const scored = ranked.results.map((item, at) => {
        if (!Number.isInteger(item.index) || item.index < 0 || item.index >= input.length || seen.has(item.index) || !Number.isFinite(item.relevance_score)) throw new RetrievalError('rerank_result_invalid', 'Rerank indices or scores are invalid');
        seen.add(item.index); return { ...input[item.index]!, score: item.relevance_score, rerank_score: item.relevance_score, rerank_stage_rank_score: (input.length - at) / input.length };
      });
      if (seen.size !== input.length) throw new RetrievalError('rerank_result_incomplete', 'Rerank did not return every candidate');
      const filtered = scored.filter(row => row.rerank_stage_rank_score >= result.meta.thresholds.rerank); result.meta.filtered_counts.rerank = scored.length - filtered.length;
      rows = [...filtered, ...rows.slice(input.length)];
    } catch (error) { execution.assert(); degrade(error instanceof RetrievalError ? error.code : 'rerank_call_failed'); }
  }
  return { results: refresh(execution, index, rows).map((row, at) => ({ ...row, final_rank: at + 1 })), meta: result.meta };
}
export async function retrieveChat(execution: ChatExecution, index: SearchIndex, query: string, options: SearchOptions = {}, hooks: ChatHooks = {}): Promise<ChatSearchResult> {
  execution.assert(); const top = bounded(options.topK, 5, 1, 200), cap = bounded(options.maxContextChars, 4096, 0, 1000000);
  const result = await documentCandidates(execution, index, query, { ...options, signal: execution.signal }, top); execution.assert();
  const degrade = (reason: string) => { result.meta.degraded = true; if (!result.meta.degradations.some(row => row.stage === 'graph' && row.reason === reason)) result.meta.degradations.push({ stage: 'graph', reason }); };
  const selected = execution.scope.knowledgeBaseIds ?? index.db.all('SELECT id FROM knowledge_bases WHERE tenant_id=? AND deleted_at IS NULL', String(execution.scope.tenantId)).map(row => String(row.id));
  if (!selected.length) return result;
  const graphEnabled = selected.some(id => { const kb = index.db.read('knowledge_bases', id); return kb && String(kb.tenant_id) === String(execution.scope.tenantId) && kb.deleted_at === null && enabled(object(kb.indexing_strategy).graph_enabled); });
  const graphRows: SearchHit[] = [], provenance = new Map<string, JsonObject[]>();
  const add = (id: string, score: number, relation: 'entity' | 'direct' | 'indirect', source?: string): boolean => {
    const row = index.hydrate(execution.scope, id); if (!row) return false;
    const at = graphRows.findIndex(hit => hit.chunk_id === id);
    if (relation === 'entity' && at < 0 && graphRows.length >= top) return false;
    const refs = provenance.get(id) ?? [];
    refs.push({ chunk_id: id, knowledge_id: row.knowledge_id, knowledge_base_id: row.knowledge_base_id, relation_type: relation,
      ...(source ? { source_chunk_id: source } : {}), metadata: row.metadata, image_info: row.image_info }); provenance.set(id, refs);
    if (at < 0) graphRows.push({ ...row, score, match_sources: ['graph'] });
    else if (score > graphRows[at]!.score) graphRows[at] = { ...row, score, match_sources: ['graph'] };
    return true;
  };
  if (graphEnabled && query.trim()) {
    if (!hooks.graphRetrieval) degrade('graph_retrieval_not_configured');
    else {
      const response = await hooks.graphRetrieval(execution, query, { limit: top, seenChunkIds: result.results.flatMap(row => row.matched_child_ids ?? [row.chunk_id]) }); execution.assert();
      if (!['connected', 'pending', 'model_not_configured'].includes(String(response.state)) || !Array.isArray(response.items) || !Array.isArray(response.warnings)) throw new RetrievalError('graph_result_invalid', 'Graph retrieval returned an invalid result');
      for (const warning of response.warnings.slice(0, 100)) { const code = object(warning).code; if (typeof code === 'string' && /^[a-z][a-z0-9_]{0,127}$/.test(code)) degrade(code); }
      if (response.state !== 'connected' && !response.warnings.length) degrade('graph_needs_configuration');
      for (const item of response.items.slice(0, 1000)) { const value = object(item); if (typeof value.chunk_id === 'string' && value.chunk_id.length <= 128 && value.chunk_id) add(value.chunk_id, typeof value.score === 'number' && Number.isFinite(value.score) ? value.score : 1, 'entity'); }
    }
  }
  execution.assert(); const documents = refresh(execution, index, result.results), seeds = [...documents, ...graphRows];
  // Stored direct/indirect relations are available even when the optional Neo4j service is disabled.
  const seen = new Set(seeds.map(row => row.chunk_id)); let extras = 0;
  for (const seed of seeds) {
    const row = index.db.read('chunks', seed.chunk_id); if (!row) continue;
    for (const [field, relation] of [['relation_chunks', 'direct'], ['indirect_relation_chunks', 'indirect']] as const) {
      const refs = row[field]; if (!Array.isArray(refs)) continue;
      for (const id of refs.slice(0, 128)) {
        if (extras >= Math.min(3, top)) break;
        if (typeof id === 'string' && !seen.has(id) && add(id, 1, relation, seed.chunk_id)) { seen.add(id); extras++; }
      }
    }
  }
  const docs: ChatSearchHit[] = deduplicate(expandShort(execution, index, index.resolveParents(execution.scope, documents, cap), cap));
  const graphs: ChatSearchHit[] = deduplicate(index.resolveParents(execution.scope, graphRows, cap).map((row): ChatSearchHit => {
    const refs = (row.matched_child_ids ?? [row.chunk_id]).flatMap(id => provenance.get(id) ?? []);
    const relation = refs[0]?.relation_type;
    return { ...row, retrieval_path: 'graph', match_type: 'graph', graph_provenance: refs, ...(relation === 'entity' || relation === 'direct' || relation === 'indirect' ? { relation_type: relation } : {}) };
  }).sort((a, b) => b.score - a.score));
  const remaining = graphs.filter(graph => { const at = docs.findIndex(doc => redundant(doc, graph)); if (at < 0) return true; docs[at] = attribution(docs[at]!, graph); return false; });
  const selectedDocs = selectChatDocuments(docs, top), selectedGraphs = diversify(remaining, Math.max(2, top));
  const merged: ChatSearchHit[] = [];
  for (let at = 0; at < Math.max(selectedDocs.length, selectedGraphs.length); at++) { if (selectedDocs[at]) merged.push(selectedDocs[at]!); if (selectedGraphs[at]) merged.push(selectedGraphs[at]!); }
  execution.assert(); return { results: merged.slice(0, top), meta: result.meta };
}
