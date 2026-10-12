import type { AuthAction } from '../auth/index.js';
import type { AuthReader } from '../auth/reader.js';
import type { AuthContext, JsonObject } from '../contracts.js';
import { readIndexState, type IndexStateReader } from '../retrieval/index-state.js';
import type { Row } from '../storage/database.js';
import type { DatabaseReader } from '../storage/read-database.js';
import { publicParameters } from '../storage/credentials.js';
import { effectiveChunking, fail, object, processingStatuses, projectedChunking, indexing, searchableTypes } from './config.js';

/** Match the displayed workflow state without overwriting an already published parsing result. */
export function documentFilterStatus(row: Row): string {
  const workflow = object(row.metadata).workflow_status;
  if (workflow === 'interrupted') return 'failed';
  return typeof workflow === 'string' && ['pending', 'processing', 'failed', 'cancelled'].includes(workflow) ? workflow : String(row.parse_status);
}
export class KnowledgeReadDomain {
  constructor(readonly db: DatabaseReader, readonly auth: AuthReader,
    readonly indexState: IndexStateReader = { state: scope => readIndexState(db, scope) }) {}
  assert(ctx: AuthContext, action: AuthAction = 'read'): void { this.auth.assertCan(ctx, action, ctx.tenantId); }
  kb(ctx: AuthContext, id: string, action: AuthAction = 'read'): Row {
    this.assert(ctx); const row = this.db.read('knowledge_bases', id);
    if (!row || row.deleted_at !== null || String(row.tenant_id) !== ctx.tenantId) fail(404, 'knowledge_base_not_found', 'Knowledge base not found');
    this.assert(ctx, action); return row!;
  }
  doc(ctx: AuthContext, id: string, action: AuthAction = 'read', kbId?: string): Row {
    this.assert(ctx); return this.documentScope(ctx, this.db.read('knowledges', id), action, kbId);
  }
  private documentScope(ctx: AuthContext, row: Row | undefined, action: AuthAction, kbId?: string): Row {
    if (!row || row.deleted_at !== null || String(row.tenant_id) !== ctx.tenantId || kbId !== undefined && row.knowledge_base_id !== kbId) fail(404, 'knowledge_not_found', 'Document not found');
    this.kb(ctx, String(row!.knowledge_base_id)); this.assert(ctx, action); return row!;
  }
  chunk(ctx: AuthContext, id: string, docId?: string, action: AuthAction = 'read'): Row {
    this.assert(ctx); const row = this.db.read('chunks', id);
    if (!row || row.deleted_at !== null || String(row.tenant_id) !== ctx.tenantId || docId !== undefined && row.knowledge_id !== docId) fail(404, 'chunk_not_found', 'Chunk not found');
    const d = this.doc(ctx, String(row!.knowledge_id));
    if (row!.knowledge_base_id !== d.knowledge_base_id) fail(404, 'chunk_not_found', 'Chunk not found');
    this.assert(ctx, action); return row!;
  }
  docs(ctx: AuthContext, kbId?: string): Row[] {
    this.assert(ctx); if (kbId !== undefined) this.kb(ctx, kbId);
    return this.db.all(`SELECT d.id FROM knowledges d JOIN knowledge_bases b ON b.id=d.knowledge_base_id WHERE d.tenant_id=? AND b.tenant_id=d.tenant_id AND d.deleted_at IS NULL AND b.deleted_at IS NULL ${kbId === undefined ? '' : 'AND b.id=?'} ORDER BY d.updated_at DESC,d.id`, ctx.tenantId, ...(kbId === undefined ? [] : [kbId])).map(r => this.db.read('knowledges', String(r.id))!);
  }
  chunks(ctx: AuthContext, d: Row): Row[] {
    this.doc(ctx, String(d.id));
    return this.db.all('SELECT id FROM chunks WHERE tenant_id=? AND knowledge_base_id=? AND knowledge_id=? AND deleted_at IS NULL ORDER BY chunk_index,id', ctx.tenantId, String(d.knowledge_base_id), String(d.id)).map(r => this.db.read('chunks', String(r.id))!);
  }
  chunkReferences(ctx: AuthContext, documentId: string): Row[] {
    this.assert(ctx);
    const d = this.documentScope(ctx, this.db.get('SELECT id,tenant_id,knowledge_base_id,deleted_at FROM knowledges WHERE id=?', documentId), 'read');
    return this.db.all('SELECT id,chunk_type FROM chunks WHERE tenant_id=? AND knowledge_base_id=? AND knowledge_id=? AND deleted_at IS NULL ORDER BY chunk_index,id', ctx.tenantId, String(d.knowledge_base_id), documentId);
  }
  chunkCounts(ctx: AuthContext, kbId: string): { total: number; searchable: number } {
    this.kb(ctx, kbId);
    const types = [...searchableTypes];
    const counts = this.db.get(`SELECT count(*) AS total,
      coalesce(sum(CASE WHEN c.chunk_type IN (${types.map(() => '?').join(',')}) THEN 1 ELSE 0 END),0) AS searchable
      FROM chunks c JOIN knowledges d ON d.id=c.knowledge_id AND d.tenant_id=c.tenant_id AND d.knowledge_base_id=c.knowledge_base_id
      JOIN knowledge_bases b ON b.id=d.knowledge_base_id AND b.tenant_id=d.tenant_id
      WHERE c.tenant_id=? AND c.knowledge_base_id=? AND c.deleted_at IS NULL AND d.deleted_at IS NULL AND b.deleted_at IS NULL`, ...types, ctx.tenantId, kbId);
    return { total: Number(counts?.total ?? 0), searchable: Number(counts?.searchable ?? 0) };
  }
  scope(ctx: AuthContext, kbId: string) { return { tenantId: ctx.tenantId, knowledgeBaseIds: [kbId] }; }
  chunkDto(row: Row): JsonObject {
    const { deleted_at: _deleted, content_hash: _hash, ...value } = row;
    return publicParameters({ ...value, seq_id: row.seq_id == null ? null : String(row.seq_id), tenant_id: row.tenant_id! });
  }
  docDto(row: Row, list = false): JsonObject {
    const listFields = ['id', 'knowledge_base_id', 'type', 'title', 'description', 'source', 'parse_status', 'enable_status', 'file_name', 'file_type', 'file_size', 'storage_size', 'tag_id', 'summary_status', 'pending_subtasks_count', 'error_message', 'processed_at', 'created_at', 'updated_at'];
    const metadata = object(row.metadata);
    const workflow = {
      workflow_status: typeof metadata.workflow_status === 'string' ? metadata.workflow_status : '',
      source_generation: typeof metadata.source_generation === 'string' ? metadata.source_generation : '',
      processing_warning_codes: [...new Set((Array.isArray(metadata.processing_warnings) ? metadata.processing_warnings : [])
        .flatMap(value => { const code = object(value).code; return typeof code === 'string' ? [code] : []; }))],
    };
    if (list) return { ...Object.fromEntries(listFields.map(k => [k, row[k] ?? null])), ...workflow };
    const { deleted_at: _deleted, last_faq_import_result: _faq, ...value } = row;
    const images = this.db.get('SELECT count(*) AS n,sum(CASE WHEN status=\'failed\' THEN 1 ELSE 0 END) AS failed FROM knowledge_images WHERE tenant_id=? AND knowledge_base_id=? AND knowledge_id=? AND deleted_at IS NULL', String(row.tenant_id), String(row.knowledge_base_id), String(row.id));
    return publicParameters({ ...value, ...workflow, knowledge_base_name: this.db.read('knowledge_bases', String(row.knowledge_base_id))?.name ?? '', image_count: Number(images?.n ?? 0), image_failed_count: Number(images?.failed ?? 0) });
  }
  processingCount(ctx: AuthContext, documents: Row[]): number {
    this.assert(ctx);
    if (!documents.length) return 0;
    // Local parsing completes before auxiliary model work. A legacy pending
    // counter alone is not proof that a current workflow can still publish.
    const active = new Map(this.db.all(`SELECT id,json_extract(payload,'$.input.knowledge_id') AS knowledge_id,json_extract(payload,'$.input.knowledge_base_id') AS knowledge_base_id
      FROM desktop_jobs WHERE tenant_id=? AND kind='process_knowledge' AND cancel_requested_at IS NULL
      AND json_extract(payload,'$.input.tenant_id')=?
      AND (status='queued' OR (status='running' AND attempt>0
        AND json_type(payload,'$.claim.ownerToken')='text' AND length(json_extract(payload,'$.claim.ownerToken'))>0
        AND json_type(payload,'$.claim.leaseUntil') IN ('integer','real') AND json_extract(payload,'$.claim.leaseUntil')>?))`, ctx.tenantId, ctx.tenantId, Date.now()).map(job => [String(job.id), job]));
    return documents.filter(d => {
      if (processingStatuses.has(String(d.parse_status))) return true;
      const metadata = object(d.metadata);
      if (metadata.workflow_status === 'cancelled') return false;
      const job = active.get(String(metadata.workflow_job_id ?? ''));
      return !!job && job.knowledge_id === d.id && job.knowledge_base_id === d.knowledge_base_id;
    }).length;
  }
  kbDto(ctx: AuthContext, row: Row): JsonObject {
    const config = projectedChunking(row.chunking_config), strategy = indexing(row.indexing_strategy, String(row.type)), documents = this.docs(ctx, String(row.id));
    let needsReindex = !config.compatible, lastStrategy: string | null = null;
    for (const d of [...documents].sort((a, b) => String(b.processed_at ?? b.updated_at).localeCompare(String(a.processed_at ?? a.updated_at)))) {
      const meta = object(d.metadata), diagnostic = object(meta.chunking_diagnostics), selected = diagnostic.selected_strategy;
      try {
        const effective = meta.effective_chunking_config ? effectiveChunking(meta.effective_chunking_config, {}) : d.parse_status === 'completed' && selected ? effectiveChunking(config.config, meta.process_config) : null;
        if (effective) {
          if (Object.keys(config.config).some(key => effective[key] !== config.config[key])) needsReindex = true;
          if (!lastStrategy && selected) lastStrategy = String(selected);
        }
        if (processingStatuses.has(String(d.parse_status))) { const requested = effectiveChunking(config.config, meta.process_config); if (Object.keys(config.config).some(key => requested[key] !== config.config[key])) needsReindex = true; }
      } catch { needsReindex = true; }
      if (meta.vector_status === 'needs_rebuild') needsReindex = true;
    }
    if (this.indexState.state(this.scope(ctx, String(row.id))).some(state => state.status !== 'ready')) needsReindex = true;
    const counts = this.chunkCounts(ctx, String(row.id)), processing = this.processingCount(ctx, documents);
    const fields = ['id', 'name', 'description', 'tenant_id', 'image_processing_config', 'embedding_model_id', 'summary_model_id', 'storage_provider_config', 'vlm_config', 'asr_config', 'extract_config', 'question_generation_config', 'wiki_config', 'is_temporary', 'is_pinned', 'pinned_at', 'creator_id', 'created_at', 'updated_at'];
    return publicParameters({ ...Object.fromEntries(fields.map(k => [k, row[k] ?? null])), type: ['wiki', 'faq'].includes(String(row.type)) ? 'document' : row.type!, chunking_config: config.config, needs_reindex: needsReindex, last_effective_strategy: lastStrategy, indexing_strategy: strategy, capabilities: { vector: strategy.vector_enabled!, keyword: strategy.keyword_enabled!, wiki: strategy.wiki_enabled!, graph: strategy.graph_enabled! }, creator_name: row.creator_id === ctx.userId ? this.db.read('users', ctx.userId)?.username ?? '' : '', vector_store_id: row.vector_store_id || null, vector_store_name: 'SQLite local', vector_store_engine_type: 'sqlite-vec', vector_store_source: 'env', vector_store_status: 'available', knowledge_count: documents.length, document_count: documents.length, chunk_count: counts.searchable, total_chunk_count: counts.total, processing_count: processing, is_processing: processing > 0 });
  }
}
