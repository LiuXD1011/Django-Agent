import type { AuthContext, JsonObject } from '../contracts.js';
import type { Row } from '../storage/database.js';
import { csv, fail, ids, input, object, paginate, type Page } from './config.js';
import { documentFilterStatus, KnowledgeReadDomain } from './read-domain.js';

export class KnowledgeBaseQueries {
  constructor(private readonly domain: KnowledgeReadDomain) {}
  get(ctx: AuthContext, id: string): JsonObject { return this.domain.kbDto(ctx, this.domain.kb(ctx, id)); }
  list(ctx: AuthContext, query: JsonObject = {}): Page {
    this.domain.assert(ctx); const q = input(query), keyword = String(q.keyword ?? q.q ?? q.query ?? '').toLowerCase();
    const rows = this.domain.db.all('SELECT id FROM knowledge_bases WHERE tenant_id=? AND deleted_at IS NULL AND is_temporary=0 ORDER BY is_pinned DESC,updated_at DESC,id', ctx.tenantId).map(r => this.domain.kb(ctx, String(r.id))).filter(row => {
      if (keyword && ![row.name, row.description].some(value => String(value).toLowerCase().includes(keyword))) return false;
      if (q.creator === 'mine' && ctx.userId && row.creator_id !== ctx.userId || q.creator === 'others' && ctx.userId && row.creator_id === ctx.userId) return false;
      if (q.type === 'faq') return false;
      if (q.type === 'wiki') return row.type === 'wiki' || object(row.indexing_strategy).wiki_enabled === true;
      return !q.type || row.type === q.type;
    });
    const result = paginate(rows, q); result.items = result.items.map(row => this.domain.kbDto(ctx, row)); return result;
  }
  moveTargets(ctx: AuthContext, id: string): JsonObject {
    const source = this.domain.kb(ctx, id);
    return { items: this.domain.db.all('SELECT id FROM knowledge_bases WHERE tenant_id=? AND type=? AND deleted_at IS NULL AND id<>? ORDER BY name,id', ctx.tenantId, String(source.type), id).map(r => this.get(ctx, String(r.id))) };
  }
}

/** Synchronous queries shared by the owning services and the WAL read dispatcher. */
export class KnowledgeQueries {
  readonly knowledgeBases: KnowledgeBaseQueries;
  constructor(private readonly domain: KnowledgeReadDomain) {
    this.knowledgeBases = new KnowledgeBaseQueries(domain);
  }
  get(ctx: AuthContext, id: string): JsonObject { return this.domain.docDto(this.domain.doc(ctx, id)); }
  list(ctx: AuthContext, kbId?: string, query: JsonObject = {}): Page {
    const params = input(query), all = this.domain.docs(ctx, kbId), keyword = String(params.keyword ?? params.q ?? params.query ?? '').toLowerCase();
    const tag = params.tag_id ?? params.tagId, statuses = csv(params.parse_status ?? params.parseStatus), types = csv(params.file_types ?? params.file_type ?? params.fileType), source = params.source ?? params.channel;
    const start = params.start_time ?? params.startTime, end = params.end_time ?? params.endTime;
    for (const bound of [start, end]) if (bound && !Number.isFinite(Date.parse(String(bound)))) fail(400, 'invalid_time_filter', 'Invalid date filter');
    const filtered = all.filter(d => {
      if (keyword && ![d.title, d.file_name, d.source, d.description, object(d.metadata).content].some(v => String(v ?? '').toLowerCase().includes(keyword))) return false;
      if (tag && d.tag_id !== tag || statuses.length && !statuses.includes(documentFilterStatus(d)) || types.length && !types.includes(String(d.file_type)) && !types.includes(String(d.type))) return false;
      if (source && (source === 'file' ? d.type !== source : d.channel !== source && d.source !== source)) return false;
      return !(start && Date.parse(String(d.created_at)) < Date.parse(String(start)) || end && Date.parse(String(d.created_at)) > Date.parse(String(end)));
    });
    const result = paginate(filtered.map(d => this.domain.docDto(d, kbId !== undefined)), params);
    if (kbId !== undefined) {
      const counts = (keyFor: (row: Row) => string) => all.reduce<JsonObject>((total, d) => { const key = keyFor(d); total[key] = Number(total[key] ?? 0) + 1; return total; }, {});
      result.status_counts = counts(documentFilterStatus); result.tag_counts = counts(d => String(d.tag_id)); result.processing_records = all.slice(0, 200).map(d => this.domain.docDto(d, true));
    }
    return result;
  }
  batch(ctx: AuthContext, requested: unknown): JsonObject { return { items: ids(requested).map(id => this.get(ctx, id)) }; }
  stats(ctx: AuthContext, kbId: string): JsonObject {
    const docs = this.domain.docs(ctx, kbId), statuses = ['pending', 'processing', 'finalizing', 'completed', 'failed', 'cancelled'];
    const counts = Object.fromEntries(statuses.map(status => [status, docs.filter(d => documentFilterStatus(d) === status).length]));
    const storage = docs.reduce((total, d) => total + BigInt(String(d.storage_size)), 0n), processing = this.domain.processingCount(ctx, docs);
    return { knowledge_base_id: kbId, knowledge_count: docs.length, document_count: docs.length, total: docs.length, completed: counts.completed!, processing, pending: counts.pending!, failed: counts.failed!, cancelled: counts.cancelled!, chunk_count: this.domain.chunkCounts(ctx, kbId).total, storage_size: storage <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(storage) : storage.toString(), status_counts: counts, is_processing: processing > 0 };
  }
  listChunks(ctx: AuthContext, documentId: string, query: JsonObject = {}): Page {
    const references = this.domain.chunkReferences(ctx, documentId), params = input(query);
    const result = paginate(references.filter(c => !params.chunk_type || c.chunk_type === params.chunk_type), params);
    result.items = result.items.map(c => this.domain.chunkDto(this.domain.db.read('chunks', String(c.id))!)); return result;
  }
  getChunk(ctx: AuthContext, chunkId: string, documentId?: string): JsonObject { return this.domain.chunkDto(this.domain.chunk(ctx, chunkId, documentId)); }
  listTags(ctx: AuthContext, kbId: string): JsonObject {
    this.domain.kb(ctx, kbId); return { items: this.domain.db.all('SELECT id FROM knowledge_tags WHERE tenant_id=? AND knowledge_base_id=? AND deleted_at IS NULL ORDER BY sort_order,created_at,id', ctx.tenantId, kbId).map(r => this.getTag(ctx, kbId, String(r.id))) };
  }
  getTag(ctx: AuthContext, kbId: string, tagId: string): JsonObject {
    this.domain.kb(ctx, kbId); const tag = this.domain.db.read('knowledge_tags', tagId);
    if (!tag || String(tag.tenant_id) !== ctx.tenantId || tag.knowledge_base_id !== kbId || tag.deleted_at !== null) fail(404, 'tag_not_found', 'Tag not found');
    const { deleted_at: _deleted, seq_id: _seq, ...value } = tag!; return value;
  }
}
