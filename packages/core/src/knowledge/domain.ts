import type { AuthAction, AuthService } from '../auth/index.js';
import type { AuthContext, JsonObject } from '../contracts.js';
import type { JobQueue } from '../jobs/queue.js';
import { SearchIndex } from '../retrieval/search-index.js';
import type { CoreDatabase, Row } from '../storage/database.js';
import { publicParameters } from '../storage/credentials.js';
import { effectiveChunking, fail, object, processingStatuses, projectedChunking, indexing, searchableTypes } from './config.js';

export const now = () => new Date().toISOString();
export interface Warning extends JsonObject { code: string; stage: string; message: string }
export const warning = (code: string, stage: string, message: string): Warning => ({ code, stage, message });
export class KnowledgeDomain {
  readonly index: SearchIndex;
  constructor(readonly db: CoreDatabase, readonly auth: AuthService, index?: SearchIndex, readonly jobs?: JobQueue) { this.index = index ?? new SearchIndex(db); }
  assert(ctx: AuthContext, action: AuthAction = 'read'): void { this.auth.assertCan(ctx, action, ctx.tenantId); }
  kb(ctx: AuthContext, id: string, action: AuthAction = 'read'): Row {
    this.assert(ctx); const row = this.db.read('knowledge_bases', id);
    if (!row || row.deleted_at !== null || String(row.tenant_id) !== ctx.tenantId) fail(404, 'knowledge_base_not_found', 'Knowledge base not found');
    this.assert(ctx, action); return row!;
  }
  doc(ctx: AuthContext, id: string, action: AuthAction = 'read', kbId?: string): Row {
    this.assert(ctx); const row = this.db.read('knowledges', id);
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
  scope(ctx: AuthContext, kbId: string) { return { tenantId: ctx.tenantId, knowledgeBaseIds: [kbId] }; }
  removeIndex(ctx: AuthContext, chunk: Row): void {
    this.assert(ctx);
    const doc = this.db.read('knowledges', String(chunk.knowledge_id));
    if (String(chunk.tenant_id) !== ctx.tenantId || !doc || String(doc.tenant_id) !== ctx.tenantId || doc.knowledge_base_id !== chunk.knowledge_base_id) fail(409, 'index_scope_mismatch', 'Chunk index namespace is inconsistent');
    const registered = this.db.get('SELECT * FROM retrieval_chunk_ids WHERE chunk_id=?', String(chunk.id));
    if (registered && (String(registered.tenant_id) !== ctx.tenantId || registered.knowledge_base_id !== chunk.knowledge_base_id || registered.knowledge_id !== chunk.knowledge_id)) fail(409, 'index_scope_mismatch', 'Chunk index namespace is inconsistent');
    if (chunk.seq_id !== null && this.db.get('SELECT id FROM chunks WHERE seq_id=? AND id<>? LIMIT 1', String(chunk.seq_id), String(chunk.id))) fail(409, 'seq_id_collision', 'Chunk sequence identifier is shared by another chunk');
    this.index.deleteChunk(this.scope(ctx, String(chunk.knowledge_base_id)), String(chunk.id), chunk.seq_id == null ? undefined : String(chunk.seq_id));
    // Imported FTS rows can predate the new registration table. The validated,
    // collision-free chunk supplies the exact rowid; no unscoped purge is used.
    if (chunk.seq_id !== null) this.db.run('DELETE FROM chunks_fts WHERE rowid=?', String(chunk.seq_id));
  }
  invalidate(ctx: AuthContext, kbId: string): void {
    this.db.run("UPDATE search_index_meta SET status='needs_rebuild',updated_at=? WHERE tenant_id=? AND knowledge_base_id=?", now(), ctx.tenantId, kbId);
    this.db.run('DELETE FROM retrieval_builds WHERE id IN (SELECT id FROM search_index_meta WHERE tenant_id=? AND knowledge_base_id=?)', ctx.tenantId, kbId);
  }
  markDocument(ctx: AuthContext, d: Row, codes = ['graph_rebuild_required', 'wiki_rebuild_required', 'vector_rebuild_required']): Warning[] {
    const warnings = codes.map(code => warning(code, code.split('_')[0]!, 'Derived data requires rebuilding after the document change'));
    const meta = object(this.db.read('knowledges', String(d.id))?.metadata);
    const existing = Array.isArray(meta.processing_warnings) ? meta.processing_warnings : [];
    const stages = Object.fromEntries(codes.map(code => [`${code.split('_')[0]}_status`, 'needs_rebuild']));
    this.db.update('knowledges', String(d.id), { metadata: { ...meta, ...stages, processing_warnings: [...existing.filter(w => !codes.includes(String(object(w).code))), ...warnings] }, updated_at: now() });
    this.invalidate(ctx, String(d.knowledge_base_id)); return warnings;
  }
  /** Called after validating all targets, before mutations; queue cancellation fences late publications immediately. */
  cancel(ctx: AuthContext, documents: Row[], kbIds: string[] = []): void {
    const docIds = new Set(documents.map(d => String(d.id))), bases = new Set(kbIds);
    const related = (payload: JsonObject) => docIds.has(String(payload.knowledge_id ?? payload.knowledgeId ?? payload.document_id ?? payload.documentId ?? '')) || bases.has(String(payload.knowledge_base_id ?? payload.kb_id ?? payload.knowledgeBaseId ?? '')) || Array.isArray(payload.knowledge_base_ids) && payload.knowledge_base_ids.some(id => bases.has(String(id)));
    this.assert(ctx);
    for (const row of this.db.all("SELECT * FROM desktop_jobs WHERE tenant_id=? AND status IN ('queued','running')", ctx.tenantId)) {
      const payload = object(JSON.parse(String(row.payload)));
      if (!related(object(payload.input))) continue;
      if (this.jobs) this.jobs.cancelByRequest(String(row.request_id), { tenantId: ctx.tenantId, userId: String(row.user_id) });
      else this.db.run("UPDATE desktop_jobs SET status='cancelled',cancel_requested_at=?,finished_at=?,updated_at=? WHERE id=? AND tenant_id=? AND status IN ('queued','running')", now(), now(), now(), String(row.id), ctx.tenantId);
    }
    for (const row of this.db.all("SELECT id,payload FROM task_records WHERE status IN ('pending','running')")) {
      const payload = object(JSON.parse(String(row.payload)));
      if (payload.tenant_id !== undefined && String(payload.tenant_id) !== ctx.tenantId || !related(payload)) continue;
      this.db.run("UPDATE task_records SET status='cancelled',cancel_requested_at=?,claimed_by='',payload=json_remove(payload,'$._worker_token'),lease_expires_at=NULL,error_message='cancelled after document change',updated_at=? WHERE id=? AND status IN ('pending','running')", now(), now(), String(row.id));
    }
    for (const doc of documents) this.db.run("UPDATE knowledges SET parse_status='cancelled',pending_subtasks_count=0,updated_at=? WHERE id=? AND tenant_id=? AND knowledge_base_id=? AND parse_status IN ('pending','processing','finalizing')", now(), String(doc.id), ctx.tenantId, String(doc.knowledge_base_id));
  }
  chunkDto(row: Row): JsonObject {
    const { deleted_at: _deleted, content_hash: _hash, ...value } = row;
    return publicParameters({ ...value, seq_id: row.seq_id == null ? null : String(row.seq_id), tenant_id: row.tenant_id! });
  }
  docDto(row: Row, list = false): JsonObject {
    const listFields = ['id', 'knowledge_base_id', 'type', 'title', 'description', 'source', 'parse_status', 'enable_status', 'file_name', 'file_type', 'file_size', 'storage_size', 'tag_id', 'summary_status', 'pending_subtasks_count', 'error_message', 'processed_at', 'created_at', 'updated_at'];
    if (list) return Object.fromEntries(listFields.map(k => [k, row[k] ?? null]));
    const { deleted_at: _deleted, last_faq_import_result: _faq, ...value } = row;
    const images = this.db.get('SELECT count(*) AS n,sum(CASE WHEN status=\'failed\' THEN 1 ELSE 0 END) AS failed FROM knowledge_images WHERE tenant_id=? AND knowledge_base_id=? AND knowledge_id=? AND deleted_at IS NULL', String(row.tenant_id), String(row.knowledge_base_id), String(row.id));
    return publicParameters({ ...value, knowledge_base_name: this.db.read('knowledge_bases', String(row.knowledge_base_id))?.name ?? '', image_count: Number(images?.n ?? 0), image_failed_count: Number(images?.failed ?? 0) });
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
    if (this.index.state(this.scope(ctx, String(row.id))).some(state => state.status !== 'ready')) needsReindex = true;
    const chunks = documents.flatMap(d => this.chunks(ctx, d)), processing = this.processingCount(ctx, documents);
    const fields = ['id', 'name', 'description', 'tenant_id', 'image_processing_config', 'embedding_model_id', 'summary_model_id', 'storage_provider_config', 'vlm_config', 'asr_config', 'extract_config', 'question_generation_config', 'wiki_config', 'is_temporary', 'is_pinned', 'pinned_at', 'creator_id', 'created_at', 'updated_at'];
    return publicParameters({ ...Object.fromEntries(fields.map(k => [k, row[k] ?? null])), type: ['wiki', 'faq'].includes(String(row.type)) ? 'document' : row.type!, chunking_config: config.config, needs_reindex: needsReindex, last_effective_strategy: lastStrategy, indexing_strategy: strategy, capabilities: { vector: strategy.vector_enabled!, keyword: strategy.keyword_enabled!, wiki: strategy.wiki_enabled!, graph: strategy.graph_enabled! }, creator_name: row.creator_id === ctx.userId ? this.db.read('users', ctx.userId)?.username ?? '' : '', vector_store_id: row.vector_store_id || null, vector_store_name: 'SQLite local', vector_store_engine_type: 'sqlite-vec', vector_store_source: 'env', vector_store_status: 'available', knowledge_count: documents.length, document_count: documents.length, chunk_count: chunks.filter(c => searchableTypes.has(String(c.chunk_type))).length, total_chunk_count: chunks.length, processing_count: processing, is_processing: processing > 0 });
  }
}
