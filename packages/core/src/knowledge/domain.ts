import type { AuthService } from '../auth/index.js';
import type { AuthContext, JsonObject } from '../contracts.js';
import type { JobQueue } from '../jobs/queue.js';
import { SearchIndex } from '../retrieval/search-index.js';
import type { CoreDatabase, Row } from '../storage/database.js';
import { fail, object } from './config.js';
import { KnowledgeReadDomain } from './read-domain.js';
export { documentFilterStatus } from './read-domain.js';

export const now = () => new Date().toISOString();
export interface Warning extends JsonObject { code: string; stage: string; message: string }
export const warning = (code: string, stage: string, message: string): Warning => ({ code, stage, message });
export class KnowledgeDomain extends KnowledgeReadDomain {
  readonly index: SearchIndex;
  constructor(override readonly db: CoreDatabase, override readonly auth: AuthService,
    index?: SearchIndex, readonly jobs?: JobQueue) {
    const writerIndex = index ?? new SearchIndex(db);
    super(db, auth, writerIndex);
    this.index = writerIndex;
  }
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
}
