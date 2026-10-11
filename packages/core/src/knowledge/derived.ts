import { createHash, randomUUID } from 'node:crypto';
import type { AuthContext, Json, JsonObject } from '../contracts.js';
import { CredentialVault } from '../storage/credentials.js';
import type { Row } from '../storage/database.js';
import { indexing, object, searchableTypes } from './config.js';
import { KnowledgeDomain, now } from './domain.js';

const sourceId = (ref: Json) => String(typeof ref === 'object' && ref ? object(ref).knowledge_id ?? object(ref).id ?? object(ref).knowledgeId ?? '' : ref ?? '');
function evidence(domain: KnowledgeDomain, ctx: AuthContext, kbId: string, refs: Json[]): string[] {
  return refs.flatMap((id, index) => {
    const chunk = domain.db.read('chunks', String(id));
    if (!chunk || String(chunk.tenant_id) !== ctx.tenantId || chunk.knowledge_base_id !== kbId || chunk.deleted_at !== null || !chunk.is_enabled || !searchableTypes.has(String(chunk.chunk_type))) return [];
    try { domain.chunk(ctx, String(chunk.id)); } catch { return []; }
    return [`- [c${String(index + 1).padStart(3, '0')}] ${String(chunk.content).replace(/\s+/gu, ' ').slice(0, 300)}`];
  });
}
/** Deterministic retraction; no paid LLM call and no other document's contribution is removed. */
export function refreshWiki(domain: KnowledgeDomain, ctx: AuthContext, document: Row, retract: boolean): JsonObject[] {
  const db = domain.db, docId = String(document.id), kbId = String(document.knowledge_base_id), snapshots: JsonObject[] = [], removedSlugs = new Set<string>();
  for (const ref of db.all('SELECT id FROM wiki_pages WHERE tenant_id=? AND knowledge_base_id=? AND deleted_at IS NULL', ctx.tenantId, kbId)) {
    const page = db.read('wiki_pages', String(ref.id))!, meta = object(page.page_metadata), contributions = { ...object(meta.contributions) };
    const refs = Array.isArray(page.source_refs) ? page.source_refs : [], chunks = Array.isArray(page.chunk_refs) ? page.chunk_refs : [];
    if (!(docId in contributions) && !refs.some(ref => sourceId(ref) === docId) && !chunks.some(id => db.read('chunks', String(id))?.knowledge_id === docId)) continue;
    snapshots.push({ ...page });
    if (retract) delete contributions[docId];
    const sourceRefs = retract ? refs.filter(ref => sourceId(ref) !== docId) : refs;
    const chunkRefs = [...new Set(Object.values(contributions).flatMap(c => Array.isArray(object(c).chunks) ? object(c).chunks as Json[] : []))].filter(id => {
      const chunk = db.read('chunks', String(id));
      return chunk && String(chunk.tenant_id) === ctx.tenantId && chunk.knowledge_base_id === kbId && chunk.deleted_at === null && chunk.is_enabled && (!retract || chunk.knowledge_id !== docId);
    });
    if ('contributions' in meta && !Object.keys(contributions).length) { db.run('DELETE FROM wiki_pages WHERE id=? AND tenant_id=? AND knowledge_base_id=?', String(page.id), ctx.tenantId, kbId); removedSlugs.add(String(page.slug)); continue; }
    if (Object.keys(contributions).length) {
      for (const [id, value] of Object.entries(contributions)) {
        const c = object(value), ownedChunks = Array.isArray(c.chunks) ? c.chunks.filter(chunkId => chunkRefs.includes(chunkId)) : [];
        contributions[id] = { ...c, chunks: ownedChunks };
      }
      const lines = [`# ${page.title}`, '', '## 来源摘要', '', ...Object.entries(contributions).sort(([, a], [, b]) => String(object(a).doc_title).localeCompare(String(object(b).doc_title))).map(([id, c]) => `- 《${object(c).doc_title || id}》：${object(c).description || object(c).summary || '文档中包含相关信息。'}`)];
      const details = evidence(domain, ctx, kbId, chunkRefs); if (details.length) lines.push('', '## 证据片段', '', ...details);
      db.update('wiki_pages', String(page.id), { content: lines.join('\n').trim(), summary: '', source_refs: sourceRefs, chunk_refs: chunkRefs, page_metadata: { ...meta, contributions, needs_rebuild: true }, version: Number(page.version) + 1, updated_at: now() });
    } else {
      // Imported/manual pages lacking contribution boundaries cannot be truthfully regenerated here.
      const remaining = chunks.filter(id => db.read('chunks', String(id))?.knowledge_id !== docId);
      db.update('wiki_pages', String(page.id), { source_refs: sourceRefs, chunk_refs: remaining, page_metadata: { ...meta, needs_rebuild: true }, status: 'needs_rebuild', version: Number(page.version) + 1, updated_at: now() });
    }
  }
  for (const ref of db.all('SELECT id FROM wiki_pages WHERE tenant_id=? AND knowledge_base_id=? AND deleted_at IS NULL', ctx.tenantId, kbId)) {
    const page = db.read('wiki_pages', String(ref.id))!;
    const clean = (value: Json | undefined) => Array.isArray(value) ? value.filter(link => !removedSlugs.has(String(link))) : [];
    db.update('wiki_pages', String(page.id), { in_links: clean(page.in_links), out_links: clean(page.out_links), content: String(page.content).replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/gu, (whole, slug: string, label?: string) => removedSlugs.has(slug) ? label ?? slug : whole) });
  }
  db.run('DELETE FROM wiki_pending_ops WHERE tenant_id=? AND scope_id=? AND dedup_key=?', ctx.tenantId, kbId, docId);
  return snapshots;
}
export function pendingWiki(domain: KnowledgeDomain, ctx: AuthContext, doc: Row, sourcePages: JsonObject[] = []): void {
  const kb = domain.db.read('knowledge_bases', String(doc.knowledge_base_id));
  if (!indexing(kb?.indexing_strategy, String(kb?.type)).wiki_enabled) return;
  domain.db.insert('wiki_pending_ops', { tenant_id: ctx.tenantId, scope_id: doc.knowledge_base_id, op: 'ingest', dedup_key: doc.id, payload: { knowledge_id: doc.id!, source_pages: sourcePages, needs_rebuild: true } });
}
/** Remote graph effects cannot be claimed as complete. Keep the original namespace across crashes and moves. */
export function pendingGraph(domain: KnowledgeDomain, ctx: AuthContext, doc: Row, operation: 'update' | 'delete' | 'move', targetKbId?: string): void {
  const namespace = createHash('sha256').update(JSON.stringify([ctx.tenantId, doc.knowledge_base_id])).digest('hex');
  const id = `graph:${createHash('sha256').update(JSON.stringify([ctx.tenantId, doc.knowledge_base_id, doc.id])).digest('hex')}`, snapshot = domain.db.read('generic_resources', id), data = object(snapshot?.data);
  const generation = snapshot && String(snapshot.tenant_id) === ctx.tenantId && data.knowledge_base_id === doc.knowledge_base_id && data.knowledge_id === doc.id ? data.generation ?? null : null;
  domain.db.run('INSERT INTO desktop_meta(key,value) VALUES(?,?)', `knowledge.graph.pending:${randomUUID()}`, JSON.stringify({ schema_version: 2, tenant_id: ctx.tenantId, knowledge_base_id: doc.knowledge_base_id, namespace, generation, knowledge_id: doc.id, target_knowledge_base_id: targetKbId ?? null, operation, status: 'pending', source_updated_at: doc.updated_at, created_at: now() }));
}
function relates(value: Json, kbIds: Set<string>, docIds: Set<string>, key = ''): boolean {
  if (Array.isArray(value)) return value.some(item => relates(item, kbIds, docIds, key));
  if (value && typeof value === 'object') return Object.entries(value).some(([name, item]) => relates(item, kbIds, docIds, name));
  return /^(knowledge_base_id|kb_id|knowledge_base_ids|kb_ids)$/.test(key) && kbIds.has(String(value)) || /^(knowledge_id|document_id|knowledge_ids|document_ids)$/.test(key) && docIds.has(String(value));
}
/** Preserve historical metrics/source evidence while exposing the invalidated freshness. */
export function invalidateEvaluations(domain: KnowledgeDomain, ctx: AuthContext, kbIds: string[], docIds: string[]): void {
  const db = domain.db, vault = new CredentialVault(db.dataRoot), bases = new Set(kbIds), docs = new Set(docIds);
  for (const row of db.all("SELECT id FROM generic_resources WHERE tenant_id=? AND resource_type LIKE 'rag_eval_%' AND deleted_at IS NULL", ctx.tenantId)) {
    const resource = db.read('generic_resources', String(row.id))!, data = object(resource.data);
    if (relates(data, bases, docs)) db.update('generic_resources', String(row.id), { data: vault.encrypt({ ...data, freshness_status: 'stale', source_changed_at: now() }), updated_at: now() });
  }
}
