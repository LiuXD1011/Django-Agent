import type { AuthService } from '../auth/index.js';
import type { AuthContext, JsonObject } from '../contracts.js';
import type { JobQueue } from '../jobs/queue.js';
import type { SearchIndex } from '../retrieval/search-index.js';
import type { CoreDatabase, Row } from '../storage/database.js';
import { csv, fail, ids, input, object, paginate, text, type Page } from './config.js';
import { recoverCleanup } from './artifacts.js';
import { mutateChunk } from './chunks.js';
import { invalidateEvaluations, pendingGraph, pendingWiki, refreshWiki } from './derived.js';
import { KnowledgeDomain, now, warning } from './domain.js';
import { KnowledgeBaseService } from './knowledge-bases.js';
import { cleanRetiredDocuments, deleteDocuments } from './lifecycle.js';
export { KnowledgeError, defaultChunking, chunking, projectedChunking, effectiveChunking } from './config.js';
export { KnowledgeBaseService } from './knowledge-bases.js';

/** Trusted core context only. All DTOs keep the existing HTTP snake_case shapes. */
export class KnowledgeService {
  private readonly domain: KnowledgeDomain;
  readonly knowledgeBases: KnowledgeBaseService;
  constructor(db: CoreDatabase, auth: AuthService, index?: SearchIndex, jobs?: JobQueue) {
    this.domain = new KnowledgeDomain(db, auth, index, jobs);
    this.knowledgeBases = new KnowledgeBaseService(db, auth, index, jobs, this.domain);
  }
  get(ctx: AuthContext, id: string): JsonObject { return this.domain.docDto(this.domain.doc(ctx, id)); }
  list(ctx: AuthContext, kbId?: string, query: JsonObject = {}): Page {
    const params = input(query), all = this.domain.docs(ctx, kbId), keyword = String(params.keyword ?? params.q ?? params.query ?? '').toLowerCase();
    const tag = params.tag_id ?? params.tagId, statuses = csv(params.parse_status ?? params.parseStatus), types = csv(params.file_types ?? params.file_type ?? params.fileType), source = params.source ?? params.channel;
    const start = params.start_time ?? params.startTime, end = params.end_time ?? params.endTime;
    for (const bound of [start, end]) if (bound && !Number.isFinite(Date.parse(String(bound)))) fail(400, 'invalid_time_filter', 'Invalid date filter');
    const filtered = all.filter(d => {
      if (keyword && ![d.title, d.file_name, d.source, d.description, object(d.metadata).content].some(v => String(v ?? '').toLowerCase().includes(keyword))) return false;
      if (tag && d.tag_id !== tag || statuses.length && !statuses.includes(String(d.parse_status)) || types.length && !types.includes(String(d.file_type)) && !types.includes(String(d.type))) return false;
      if (source && (source === 'file' ? d.type !== source : d.channel !== source && d.source !== source)) return false;
      return !(start && Date.parse(String(d.created_at)) < Date.parse(String(start)) || end && Date.parse(String(d.created_at)) > Date.parse(String(end)));
    });
    const result = paginate(filtered.map(d => this.domain.docDto(d, kbId !== undefined)), params);
    if (kbId !== undefined) {
      const counts = (field: string) => all.reduce<JsonObject>((total, d) => { const key = String(d[field]); total[key] = Number(total[key] ?? 0) + 1; return total; }, {});
      result.status_counts = counts('parse_status'); result.tag_counts = counts('tag_id'); result.processing_records = all.slice(0, 200).map(d => this.domain.docDto(d, true));
    }
    return result;
  }
  batch(ctx: AuthContext, requested: unknown): JsonObject { return { items: ids(requested).map(id => this.get(ctx, id)) }; }
  stats(ctx: AuthContext, kbId: string): JsonObject {
    const docs = this.domain.docs(ctx, kbId), statuses = ['pending', 'processing', 'finalizing', 'completed', 'failed', 'cancelled'];
    const counts = Object.fromEntries(statuses.map(status => [status, docs.filter(d => d.parse_status === status).length]));
    const storage = docs.reduce((total, d) => total + BigInt(String(d.storage_size)), 0n), processing = this.domain.processingCount(ctx, docs);
    return { knowledge_base_id: kbId, knowledge_count: docs.length, document_count: docs.length, total: docs.length, completed: counts.completed!, processing, pending: counts.pending!, failed: counts.failed!, cancelled: counts.cancelled!, chunk_count: docs.flatMap(d => this.domain.chunks(ctx, d)).length, storage_size: storage <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(storage) : storage.toString(), status_counts: counts, is_processing: processing > 0 };
  }
  async update(ctx: AuthContext, id: string, payload: JsonObject): Promise<JsonObject> {
    const data = input(payload), original = this.domain.doc(ctx, id, 'document.write'), patch: Record<string, unknown> = {};
    for (const key of ['title', 'description', 'enable_status', 'tag_id']) if (key in data) patch[key] = text(data[key], ['title'].includes(key) ? 255 : key === 'tag_id' ? 36 : 65536);
    if (patch.enable_status !== undefined && !['enabled', 'disabled'].includes(String(patch.enable_status))) fail(400, 'invalid_enable_status', 'Document status must be enabled or disabled');
    if (patch.tag_id) this.getTag(ctx, String(original.knowledge_base_id), String(patch.tag_id));
    if (!Object.entries(patch).some(([key, value]) => value !== original[key])) return this.get(ctx, id);
    this.domain.cancel(ctx, [original]);
    return this.domain.db.transaction(() => {
      const doc = this.domain.doc(ctx, id, 'document.write'), kbId = String(doc.knowledge_base_id);
      if (patch.tag_id) this.getTag(ctx, kbId, String(patch.tag_id));
      const chunks = this.domain.chunks(ctx, doc);
      for (const c of chunks) this.domain.removeIndex(ctx, c);
      const updated = this.domain.db.update('knowledges', id, { ...patch, updated_at: now() })!;
      pendingGraph(this.domain, ctx, doc, 'update');
      this.domain.markDocument(ctx, updated); refreshWiki(this.domain, ctx, updated, false); pendingWiki(this.domain, ctx, updated);
      invalidateEvaluations(this.domain, ctx, [kbId], [id]);
      for (const c of chunks) this.domain.index.indexKeyword(this.domain.scope(ctx, kbId), String(c.id));
      return this.get(ctx, id);
    });
  }
  async delete(ctx: AuthContext, id: string): Promise<JsonObject> {
    const doc = this.domain.doc(ctx, id, 'document.delete'); this.domain.cancel(ctx, [doc]);
    return { id, ...await deleteDocuments(this.domain, ctx, [doc], true) };
  }
  async batchDelete(ctx: AuthContext, requested: unknown, sourceKbId?: string): Promise<JsonObject> {
    this.domain.assert(ctx, 'document.delete'); const selected = ids(requested);
    if (sourceKbId) this.domain.kb(ctx, sourceKbId);
    const docs = selected.map(id => this.domain.doc(ctx, id, 'document.delete', sourceKbId || undefined)); this.domain.cancel(ctx, docs);
    return { deleted: docs.length, deleted_count: docs.length, ids: selected, kb_id: sourceKbId ?? null, ...await deleteDocuments(this.domain, ctx, docs, true) };
  }
  async deleteContent(ctx: AuthContext, id: string): Promise<JsonObject> {
    const doc = this.domain.doc(ctx, id, 'document.delete'); this.domain.cancel(ctx, [doc]);
    return deleteDocuments(this.domain, ctx, [doc], false);
  }
  /** Original collection DELETE: clear content while retaining the knowledge base configuration and tags. */
  async clear(ctx: AuthContext, kbId: string): Promise<JsonObject> {
    this.domain.kb(ctx, kbId, 'kb.delete'); const docs = this.domain.docs(ctx, kbId);
    const retired = this.domain.db.all('SELECT id FROM knowledges WHERE tenant_id=? AND knowledge_base_id=? AND deleted_at IS NOT NULL', ctx.tenantId, kbId).map(row => this.domain.db.read('knowledges', String(row.id))!);
    this.domain.cancel(ctx, [...docs, ...retired], [kbId]); let retiredCleanup: string | undefined;
    const result = await deleteDocuments(this.domain, ctx, docs, true, () => {
      this.domain.kb(ctx, kbId, 'kb.delete');
      retiredCleanup = cleanRetiredDocuments(this.domain, ctx, retired);
      for (const table of ['wiki_pages', 'wiki_folders', 'wiki_log_entries']) this.domain.db.run(`DELETE FROM ${table} WHERE tenant_id=? AND knowledge_base_id=?`, ctx.tenantId, kbId);
      this.domain.db.run('DELETE FROM wiki_pending_ops WHERE tenant_id=? AND scope_id=?', ctx.tenantId, kbId);
      invalidateEvaluations(this.domain, ctx, [kbId], docs.map(doc => String(doc.id)));
    });
    return { ...result, warnings: [...result.warnings as JsonObject[], ...(retiredCleanup ? recoverCleanup(this.domain, ctx, retiredCleanup) : [])] };
  }
  async move(ctx: AuthContext, requested: unknown, targetKbId: string, sourceKbId?: string): Promise<JsonObject> {
    const selected = ids(requested), target = this.domain.kb(ctx, targetKbId, 'document.move');
    if (sourceKbId) this.domain.kb(ctx, sourceKbId);
    const docs = selected.map(id => this.domain.doc(ctx, id, 'document.move', sourceKbId || undefined));
    const moving = docs.filter(doc => doc.knowledge_base_id !== target.id);
    const fileIdentities = new Set<string>();
    for (const doc of moving) {
      if (this.domain.kb(ctx, String(doc.knowledge_base_id)).type !== target.type) fail(400, 'incompatible_knowledge_base', 'Document source and target knowledge base types differ');
      if (doc.type === 'file' && doc.file_name && doc.file_hash && this.domain.db.get('SELECT id FROM knowledges WHERE tenant_id=? AND knowledge_base_id=? AND type=\'file\' AND file_name=? AND file_hash=? AND deleted_at IS NULL', ctx.tenantId, targetKbId, String(doc.file_name), String(doc.file_hash))) fail(409, 'file_conflict', 'Target knowledge base already contains this file');
      if (doc.type === 'file' && doc.file_name && doc.file_hash) {
        const identity = JSON.stringify([doc.file_name, doc.file_hash]);
        if (fileIdentities.has(identity)) fail(409, 'file_conflict', 'Selected documents conflict in the target knowledge base');
        fileIdentities.add(identity);
      }
    }
    this.domain.cancel(ctx, moving);
    this.domain.db.transaction(() => {
      this.domain.kb(ctx, targetKbId, 'document.move');
      for (const original of moving) {
        const doc = this.domain.doc(ctx, String(original.id), 'document.move', String(original.knowledge_base_id)), oldKb = String(doc.knowledge_base_id), chunks = this.domain.chunks(ctx, doc);
        const sourcePages = refreshWiki(this.domain, ctx, doc, true).map(page => {
          const meta = object(page.page_metadata), contributions = object(meta.contributions), docId = String(doc.id);
          return { ...page, content: '', summary: '', source_refs: (Array.isArray(page.source_refs) ? page.source_refs : []).filter(ref => String(object(ref).knowledge_id ?? object(ref).id ?? ref) === docId), chunk_refs: (Array.isArray(page.chunk_refs) ? page.chunk_refs : []).filter(id => chunks.some(c => c.id === id)), page_metadata: { ...meta, source_namespace: oldKb, contributions: docId in contributions ? { [docId]: contributions[docId]! } : {} } };
        });
        for (const c of chunks) this.domain.removeIndex(ctx, c);
        if (doc.tag_id) {
          const sourceTag = this.domain.db.read('knowledge_tags', String(doc.tag_id));
          if (sourceTag && String(sourceTag.tenant_id) === ctx.tenantId && sourceTag.knowledge_base_id === oldKb) {
            const existing = this.domain.db.get('SELECT id FROM knowledge_tags WHERE tenant_id=? AND knowledge_base_id=? AND name=? AND deleted_at IS NULL', ctx.tenantId, targetKbId, String(sourceTag.name));
            const tag = existing ?? this.domain.db.insert('knowledge_tags', { tenant_id: ctx.tenantId, knowledge_base_id: targetKbId, name: sourceTag.name, color: sourceTag.color, sort_order: sourceTag.sort_order });
            doc.tag_id = tag.id!;
          } else doc.tag_id = '';
        }
        const updated = this.domain.db.update('knowledges', String(doc.id), { knowledge_base_id: targetKbId, tag_id: doc.tag_id, updated_at: now() })!;
        pendingGraph(this.domain, ctx, doc, 'move', targetKbId);
        for (const table of ['chunks', 'knowledge_images']) this.domain.db.run(`UPDATE ${table} SET knowledge_base_id=?,updated_at=? WHERE tenant_id=? AND knowledge_base_id=? AND knowledge_id=?`, targetKbId, now(), ctx.tenantId, oldKb, String(doc.id));
        this.domain.invalidate(ctx, oldKb); this.domain.markDocument(ctx, updated); pendingWiki(this.domain, ctx, updated, sourcePages);
        invalidateEvaluations(this.domain, ctx, [oldKb, targetKbId], [String(doc.id)]);
        for (const c of chunks) this.domain.index.indexKeyword(this.domain.scope(ctx, targetKbId), String(c.id));
      }
    });
    return { moved: moving.length, knowledge_count: moving.length, source_kb_id: sourceKbId ?? null, target_kb_id: targetKbId, target_knowledge_base_id: targetKbId, task_id: '', message: 'Knowledge metadata moved; derived rebuilds are pending', warnings: [warning('graph_rebuild_required', 'graph', 'Graph namespaces require cleanup and rebuilding after the move'), warning('wiki_rebuild_required', 'wiki', 'Wiki contributions were preserved for rebuilding in the target namespace'), warning('vector_rebuild_required', 'vector', 'Vector data requires rebuilding in the target knowledge base')], pending: ['graph_cleanup', 'graph_rebuild', 'wiki_rebuild', 'vector_rebuild'] };
  }
  listChunks(ctx: AuthContext, documentId: string, query: JsonObject = {}): Page {
    const doc = this.domain.doc(ctx, documentId), params = input(query);
    return paginate(this.domain.chunks(ctx, doc).filter(c => !params.chunk_type || c.chunk_type === params.chunk_type).map(c => this.domain.chunkDto(c)), params);
  }
  getChunk(ctx: AuthContext, chunkId: string, documentId?: string): JsonObject { return this.domain.chunkDto(this.domain.chunk(ctx, chunkId, documentId)); }
  async updateChunk(ctx: AuthContext, documentId: string, chunkId: string, data: JsonObject): Promise<JsonObject> { return mutateChunk(this.domain, ctx, documentId, chunkId, data); }
  async toggleChunk(ctx: AuthContext, documentId: string, chunkId: string, value: boolean): Promise<JsonObject> { return this.updateChunk(ctx, documentId, chunkId, { is_enabled: value }); }
  async deleteChunk(ctx: AuthContext, documentId: string, chunkId: string): Promise<JsonObject> { return mutateChunk(this.domain, ctx, documentId, chunkId); }
  listTags(ctx: AuthContext, kbId: string): JsonObject {
    this.domain.kb(ctx, kbId); return { items: this.domain.db.all('SELECT id FROM knowledge_tags WHERE tenant_id=? AND knowledge_base_id=? AND deleted_at IS NULL ORDER BY sort_order,created_at,id', ctx.tenantId, kbId).map(r => this.getTag(ctx, kbId, String(r.id))) };
  }
  getTag(ctx: AuthContext, kbId: string, tagId: string): JsonObject {
    this.domain.kb(ctx, kbId); const tag = this.domain.db.read('knowledge_tags', tagId);
    if (!tag || String(tag.tenant_id) !== ctx.tenantId || tag.knowledge_base_id !== kbId || tag.deleted_at !== null) fail(404, 'tag_not_found', 'Tag not found');
    const { deleted_at: _deleted, seq_id: _seq, ...value } = tag!; return value;
  }
  private tagValues(payload: JsonObject): Record<string, unknown> {
    const data = input(payload), values: Record<string, unknown> = {};
    for (const field of ['name', 'color']) if (field in data) values[field] = text(data[field], field === 'name' ? 255 : 64);
    if ('sort_order' in data) { if (typeof data.sort_order !== 'number' || !Number.isSafeInteger(data.sort_order)) fail(400, 'invalid_tag_order', 'Tag order must be an integer'); values.sort_order = data.sort_order; }
    return values;
  }
  private tagMutation<T>(work: () => T): T {
    try { return this.domain.db.transaction(work); } catch (e) { if ((e as { code?: string }).code === 'SQLITE_CONSTRAINT_UNIQUE') fail(409, 'tag_exists', 'A tag with this name already exists'); throw e; }
  }
  createTag(ctx: AuthContext, kbId: string, payload: JsonObject = {}): JsonObject {
    const values = this.tagValues(payload);
    return this.tagMutation(() => { this.domain.kb(ctx, kbId, 'kb.write'); const tag = this.domain.db.insert('knowledge_tags', { tenant_id: ctx.tenantId, knowledge_base_id: kbId, name: '未命名', ...values }); return this.getTag(ctx, kbId, String(tag.id)); });
  }
  updateTag(ctx: AuthContext, kbId: string, tagId: string, payload: JsonObject): JsonObject {
    const values = this.tagValues(payload);
    return this.tagMutation(() => { this.domain.kb(ctx, kbId, 'kb.write'); this.getTag(ctx, kbId, tagId); this.domain.db.update('knowledge_tags', tagId, { ...values, updated_at: now() }); return this.getTag(ctx, kbId, tagId); });
  }
  deleteTag(ctx: AuthContext, kbId: string, tagId: string): JsonObject { return this.tagMutation(() => { this.domain.kb(ctx, kbId, 'kb.write'); this.getTag(ctx, kbId, tagId); this.domain.db.run('DELETE FROM knowledge_tags WHERE id=? AND tenant_id=? AND knowledge_base_id=?', tagId, ctx.tenantId, kbId); return {}; }); }
  /** Explicit recovery entry point; scoped to the authenticated tenant and safe to call after restart. */
  recoverCleanup(ctx: AuthContext): JsonObject { return { warnings: recoverCleanup(this.domain, ctx) }; }
}
