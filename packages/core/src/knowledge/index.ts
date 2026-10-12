import type { AuthService } from '../auth/index.js';
import type { AuthContext, JsonObject } from '../contracts.js';
import type { JobQueue } from '../jobs/queue.js';
import type { SearchIndex } from '../retrieval/search-index.js';
import type { CoreDatabase } from '../storage/database.js';
import { fail, ids, input, object, text, type Page } from './config.js';
import { recoverCleanup } from './artifacts.js';
import { mutateChunk } from './chunks.js';
import { invalidateEvaluations, pendingGraph, pendingWiki, refreshWiki } from './derived.js';
import { KnowledgeDomain, now, warning } from './domain.js';
import { KnowledgeBaseService } from './knowledge-bases.js';
import { KnowledgeQueries } from './read-queries.js';
import { cleanRetiredDocuments, deleteDocuments } from './lifecycle.js';
export { KnowledgeError, defaultChunking, chunking, projectedChunking, effectiveChunking } from './config.js';
export { KnowledgeBaseService } from './knowledge-bases.js';

/** Trusted core context only. All DTOs keep the existing HTTP snake_case shapes. */
export class KnowledgeService {
  private readonly domain: KnowledgeDomain;
  readonly knowledgeBases: KnowledgeBaseService;
  readonly queries: KnowledgeQueries;
  constructor(db: CoreDatabase, auth: AuthService, index?: SearchIndex, jobs?: JobQueue) {
    this.domain = new KnowledgeDomain(db, auth, index, jobs);
    this.queries = new KnowledgeQueries(this.domain);
    this.knowledgeBases = new KnowledgeBaseService(db, auth, index, jobs, this.domain);
  }
  get(ctx: AuthContext, id: string): JsonObject { return this.queries.get(ctx, id); }
  list(ctx: AuthContext, kbId?: string, query: JsonObject = {}): Page { return this.queries.list(ctx, kbId, query); }
  batch(ctx: AuthContext, requested: unknown): JsonObject { return this.queries.batch(ctx, requested); }
  stats(ctx: AuthContext, kbId: string): JsonObject { return this.queries.stats(ctx, kbId); }
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
  listChunks(ctx: AuthContext, documentId: string, query: JsonObject = {}): Page { return this.queries.listChunks(ctx, documentId, query); }
  getChunk(ctx: AuthContext, chunkId: string, documentId?: string): JsonObject { return this.queries.getChunk(ctx, chunkId, documentId); }
  async updateChunk(ctx: AuthContext, documentId: string, chunkId: string, data: JsonObject): Promise<JsonObject> { return mutateChunk(this.domain, ctx, documentId, chunkId, data); }
  async toggleChunk(ctx: AuthContext, documentId: string, chunkId: string, value: boolean): Promise<JsonObject> { return this.updateChunk(ctx, documentId, chunkId, { is_enabled: value }); }
  async deleteChunk(ctx: AuthContext, documentId: string, chunkId: string): Promise<JsonObject> { return mutateChunk(this.domain, ctx, documentId, chunkId); }
  listTags(ctx: AuthContext, kbId: string): JsonObject { return this.queries.listTags(ctx, kbId); }
  getTag(ctx: AuthContext, kbId: string, tagId: string): JsonObject { return this.queries.getTag(ctx, kbId, tagId); }
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
