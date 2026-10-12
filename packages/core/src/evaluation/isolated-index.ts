import { createHash, randomUUID } from 'node:crypto';
import { mkdtempSync, mkdirSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import type { AuthContext, JsonObject, ParsedDocument, ParsedTextBlock, ParsedImageBlock } from '../contracts.js';
import { CoreDatabase, type Row } from '../storage/database.js';
import { SearchIndex } from '../retrieval/search-index.js';
import type { EmbeddingBinding } from '../retrieval/types.js';
import { splitDocument, type ChunkerOptions, type ChunkDraft } from '../documents/chunker.js';
import { projectedChunking } from '../knowledge/config.js';
import { digest, fail, object } from './common.js';
export const evaluationStrategies = ['stored', 'fixed_window', 'recursive', 'auto_parent_child', 'semantic_parent_child', 'heading', 'layout', 'record'] as const;
export interface IsolatedIndexOptions { signal?: AbortSignal; embedding?: EmbeddingBinding; semanticEmbed?: ChunkerOptions['semanticEmbed']; semanticDimension?: number; semanticSignature?: string; check?: () => void; documents?: Row[]; chunkingConfig?: JsonObject }
/** Uses a fresh SQLite derived index. It never writes business documents/chunks or production index generations. */
export class IsolatedEvaluationIndex {
  private closed = false;
  readonly index: SearchIndex;
  private constructor(readonly root: string, readonly db: CoreDatabase, readonly diagnostics: JsonObject) { this.index = new SearchIndex(db); }
  static sourceDocuments(source: CoreDatabase, ctx: AuthContext, kbId: string): Row[] {
    const kb = source.read('knowledge_bases', kbId);
    if (!kb || kb.deleted_at !== null || String(kb.tenant_id) !== ctx.tenantId) return fail(404, 'knowledge_base_not_found', 'Knowledge base not found');
    const ids = source.all("SELECT id FROM knowledges WHERE tenant_id=? AND knowledge_base_id=? AND deleted_at IS NULL AND enable_status='enabled' ORDER BY id LIMIT 10001", ctx.tenantId, kbId);
    if (ids.length > 10000) return fail(413, 'evaluation_corpus_limit', 'Evaluation corpus exceeds the supported size');
    return ids.map(value => source.read('knowledges', String(value.id))!);
  }
  static async build(source: CoreDatabase, ctx: AuthContext, kbId: string, strategy: string, options: IsolatedIndexOptions = {}): Promise<IsolatedEvaluationIndex> {
    if (!evaluationStrategies.includes(strategy as typeof evaluationStrategies[number]) || strategy === 'stored') return fail(400, 'invalid_configuration', 'Unsupported isolated chunking strategy');
    const documents = options.documents ?? this.sourceDocuments(source, ctx, kbId), kb = source.read('knowledge_bases', kbId);
    const directory = join(source.dataRoot, '.cache', 'evaluation-isolated'); mkdirSync(directory, { recursive: true, mode: 0o700 }); const root = mkdtempSync(join(directory, 'index-'));
    const db = new CoreDatabase(root), diagnostics: JsonObject = { strategy, corpus_documents: documents.length, chunk_count: 0, parent_count: 0, source_representations: [], selected_strategies: [], isolated: true, full_corpus: true, token_counter_source: 'character_estimate' };
    const result = new IsolatedEvaluationIndex(root, db, diagnostics);
    try {
      db.insert('tenants', { id: ctx.tenantId, name: 'Isolated evaluation', status: 'active', space_type: 'legacy' });
      db.insert('knowledge_bases', { id: kbId, tenant_id: ctx.tenantId, name: 'Isolated evaluation', embedding_model_id: options.embedding?.modelId ?? '' });
      let total = 0;
      for (const document of documents) {
        options.signal?.throwIfAborted(); options.check?.(); if (String(document.tenant_id) !== ctx.tenantId || document.knowledge_base_id && String(document.knowledge_base_id) !== kbId) return fail(404, 'evaluation_source_not_found', 'Evaluation source is outside this scope'); const metadata = object(document.metadata), content = metadata.content ?? object(metadata.parser_document).canonical_text;
        if (typeof content !== 'string') return fail(422, 'evaluation_source_unparsed', 'Canonical source text is unavailable; parse all enabled corpus documents');
        total += Buffer.byteLength(content); if (total > 256 * 1024 * 1024) return fail(413, 'evaluation_corpus_limit', 'Evaluation source corpus exceeds the byte limit');
        const points = Array.from(content), parsed = parsedSource(document, content, strategy);
        const representations = diagnostics.source_representations as string[]; if (!representations.includes(String(parsed.diagnostics.source_representation))) representations.push(String(parsed.diagnostics.source_representation));
        db.insert('knowledges', { id: String(document.id), tenant_id: ctx.tenantId, knowledge_base_id: kbId, title: String(document.title || ''), enable_status: 'enabled', file_hash: String(document.file_hash || ''), embedding_model_id: options.embedding?.modelId ?? '', metadata: { content, source_generation: metadata.source_generation ?? null } });
        let parents: ChunkDraft[] = [], children: ChunkDraft[], selected: string;
        if (strategy === 'fixed_window') {
          const base = projectedChunking(options.chunkingConfig ?? kb?.chunking_config).config, size = Number(base.chunk_size), step = size - Number(base.chunk_overlap);
          children = []; for (let start = 0; start < points.length; start += step) { const end = Math.min(points.length, start + size), value = points.slice(start, end).join(''); if (value.trim()) children.push({ content: value, context_header: String(document.title || ''), start_at: start, end_at: end, chunk_type: 'text', context_parent_index: null, metadata: { strategy: 'fixed_window', chunk_size: size, chunk_overlap: Number(base.chunk_overlap) } }); if (end === points.length) break; } selected = 'fixed_window';
        } else {
          const strategyName = strategy === 'auto_parent_child' ? 'auto' : strategy === 'semantic_parent_child' ? 'semantic' : strategy;
          const chunks = await splitDocument(parsed, { ...projectedChunking(options.chunkingConfig ?? kb?.chunking_config).config, strategy: strategyName, enable_parent_child: true }, { title: String(document.title || ''), signal: options.signal, semanticEmbed: options.semanticEmbed, semanticDimension: options.semanticDimension, semanticSignature: options.semanticSignature });
          options.check?.(); if ((chunks.diagnostics.fallback_chain as JsonObject[]).length) return fail(422, 'evaluation_chunking_degraded', 'Requested production chunking strategy failed validation or model execution');
          parents = chunks.parents; children = chunks.children; selected = String(chunks.diagnostics.selected_strategy);
        }
        const selectedStrategies = diagnostics.selected_strategies as string[]; if (!selectedStrategies.includes(selected)) selectedStrategies.push(selected);
        const parentIds = parents.map((chunk, index) => String(db.insert('chunks', { id: stableChunk(strategy, String(document.id), chunk, `parent-${index}`), tenant_id: ctx.tenantId, knowledge_base_id: kbId, knowledge_id: String(document.id), chunk_index: index, chunk_type: 'parent_text', content: chunk.content, context_header: chunk.context_header, start_at: chunk.start_at, end_at: chunk.end_at, metadata: { ...chunk.metadata, source_generation: metadata.source_generation ?? null }, is_enabled: true }).id));
        for (let index = 0; index < children.length; index++) {
          const chunk = children[index]!, id = stableChunk(strategy, String(document.id), chunk, `child-${index}`);
          db.insert('chunks', { id, tenant_id: ctx.tenantId, knowledge_base_id: kbId, knowledge_id: String(document.id), chunk_index: index, chunk_type: 'text', content: chunk.content, context_header: chunk.context_header, start_at: chunk.start_at, end_at: chunk.end_at, context_parent_id: chunk.context_parent_index === null ? null : parentIds[chunk.context_parent_index]!, metadata: { ...chunk.metadata, source_generation: metadata.source_generation ?? null }, is_enabled: true }); result.index.indexKeyword({ tenantId: ctx.tenantId, knowledgeBaseIds: [kbId] }, id);
        }
        diagnostics.chunk_count = Number(diagnostics.chunk_count) + children.length; diagnostics.parent_count = Number(diagnostics.parent_count) + parents.length;
      }
      if (options.embedding) await result.index.rebuild({ tenantId: ctx.tenantId, knowledgeBaseIds: [kbId] }, options.embedding, { signal: options.signal });
      options.check?.(); return result;
    } catch (error) { await result.close(); throw error; }
  }
  async close(): Promise<void> { if (this.closed) return; this.closed = true; this.db.close(); rmSync(this.root, { recursive: true, force: true }); }
}
function stableChunk(strategy: string, documentId: string, chunk: ChunkDraft, kind: string): string { return digest([strategy, documentId, kind, chunk.start_at, chunk.end_at, chunk.content]).slice(0, 36); }
function parsedSource(document: Row, content: string, strategy: string): ParsedDocument {
  const metadata = object(document.metadata), points = Array.from(content), raw = metadata.parser_blocks;
  let blocks: ParsedTextBlock[], representation: string;
  if (Array.isArray(raw) && (raw.length || !points.length)) {
    const indices = new Set<number>(); blocks = raw.map(value => {
      const block = object(value), range = object(block.canonical_range);
      if (block.kind !== 'text' || typeof block.text !== 'string' || !Number.isSafeInteger(block.block_index) || indices.has(Number(block.block_index)) || !Number.isSafeInteger(range.start) || !Number.isSafeInteger(range.end) || Number(range.start) < 0 || Number(range.end) > points.length || Number(range.start) > Number(range.end) || points.slice(Number(range.start), Number(range.end)).join('') !== block.text) return fail(422, 'evaluation_parser_blocks_invalid', 'Persisted parser blocks do not match the canonical source');
      indices.add(Number(block.block_index)); return structuredClone(block) as unknown as ParsedTextBlock;
    }); representation = 'persisted_parser_text_blocks';
  } else {
    if (['layout', 'record', 'auto_parent_child', 'semantic_parent_child'].includes(strategy)) return fail(422, 'evaluation_parser_blocks_required', 'This strategy requires real parser text blocks; reparse the source document');
    blocks = points.length ? [{ id: 'canonical-text', kind: 'text', block_index: 0, block_type: 'paragraph', text: content, canonical_range: { start: 0, end: points.length }, provenance: {}, metadata: {} }] : []; representation = 'persisted_canonical_text';
  }
  const hash = createHash('sha256').update(content).digest('hex');
  const imageIndices = metadata.parser_image_block_indices, seenImages = new Set<number>();
  const images: ParsedImageBlock[] = Array.isArray(imageIndices) ? imageIndices.map(index => {
    if (!Number.isSafeInteger(index) || Number(index) < 0 || seenImages.has(Number(index)) || blocks.some(block => block.block_index === index)) return fail(422, 'evaluation_parser_blocks_invalid', 'Persisted image barrier indices are invalid');
    seenImages.add(Number(index));
    return { id: `image-barrier-${index}`, kind: 'image', block_index: Number(index), artifact_path: '', sha256: '', original_mime_type: '', mime_type: '', width: 0, height: 0, provenance: {}, metadata: { persisted_image_barrier: true } };
  }) : [];
  return { document: { name: String(document.title || ''), input_sha256: String(document.file_hash || hash), parser_version: 'evaluation-persisted-source-v1', canonicalization_version: 'blocks-double-newline-v1', offset_unit: 'unicode_code_point', canonical_text: content, canonical_sha256: hash }, blocks: [...blocks, ...images].sort((left, right) => left.block_index - right.block_index), warnings: [], diagnostics: { source_representation: representation, image_barriers: images.length } };
}
