import { createHash } from 'node:crypto';
import type { AuthContext, JsonObject } from '../contracts.js';
import type { Row } from '../storage/database.js';
import { fail, input, object, searchableTypes, text } from './config.js';
import { KnowledgeDomain, now } from './domain.js';
import { invalidateEvaluations, pendingGraph, pendingWiki, refreshWiki } from './derived.js';

function mutable(row: Row): void {
  if (row.chunk_type === 'parent_text') fail(409, 'chunk_parent_read_only', 'Parent text chunks are read-only');
  if (row.chunk_type === 'image_container') fail(409, 'chunk_container_read_only', 'Image container chunks are read-only');
}
function relationships(domain: KnowledgeDomain, ctx: AuthContext, doc: Row, removed?: Row): void {
  const db = domain.db, chunks = domain.chunks(ctx, doc), removedId = removed ? String(removed.id) : undefined;
  if (removedId) for (const chunk of chunks) {
    const refs = (key: string) => Array.isArray(chunk[key]) ? (chunk[key] as unknown[]).filter(id => String(id) !== removedId) : chunk[key];
    const anchor = chunks.find(c => c.id === removed!.anchor_chunk_id && c.chunk_type === 'text' && c.is_enabled);
    const preserveAnchor = ['image_ocr', 'image_caption'].includes(String(removed!.chunk_type)) && !!anchor && removed!.deleted_at === null;
    db.update('chunks', String(chunk.id), { relation_chunks: chunk.id === removedId ? [] : refs('relation_chunks'), indirect_relation_chunks: chunk.id === removedId ? [] : refs('indirect_relation_chunks'), anchor_chunk_id: chunk.anchor_chunk_id === removedId || chunk.id === removedId && !preserveAnchor ? null : chunk.anchor_chunk_id });
  }
  for (const parent of chunks.filter(c => ['parent_text', 'image_container'].includes(String(c.chunk_type)))) {
    const key = parent.chunk_type === 'parent_text' ? 'context_parent_id' : 'media_parent_id', allowed = parent.chunk_type === 'parent_text' ? ['text'] : ['image_ocr', 'image_caption'];
    if (chunks.some(c => c.id !== removedId && c[key] === parent.id && c.is_enabled && allowed.includes(String(c.chunk_type)))) continue;
    for (const child of chunks.filter(c => c[key] === parent.id)) db.update('chunks', String(child.id), { [key]: null });
    domain.removeIndex(ctx, parent);
    db.run('DELETE FROM chunks WHERE id=? AND tenant_id=? AND knowledge_base_id=? AND knowledge_id=?', String(parent.id), ctx.tenantId, String(doc.knowledge_base_id), String(doc.id));
  }
  // Dangling imported references are cleared only within this validated document namespace.
  const current = domain.chunks(ctx, doc), currentIds = new Set(current.map(c => c.id));
  for (const c of current) {
    const patch: Record<string, unknown> = {};
    for (const key of ['context_parent_id', 'media_parent_id']) if (c[key] !== null && !currentIds.has(c[key])) patch[key] = null;
    if (c.anchor_chunk_id && !current.some(a => a.id === c.anchor_chunk_id && a.chunk_type === 'text' && a.is_enabled)) patch.anchor_chunk_id = null;
    if (Object.keys(patch).length) db.update('chunks', String(c.id), patch);
  }
  const eligible = current.filter(c => c.id !== removedId && c.is_enabled && searchableTypes.has(String(c.chunk_type)));
  for (const c of current) {
    const index = eligible.findIndex(x => x.id === c.id);
    db.update('chunks', String(c.id), { pre_chunk_id: index > 0 ? eligible[index - 1]!.id : '', next_chunk_id: index >= 0 && index + 1 < eligible.length ? eligible[index + 1]!.id : '' });
  }
}
export async function mutateChunk(domain: KnowledgeDomain, ctx: AuthContext, documentId: string, chunkId: string, payload?: JsonObject): Promise<JsonObject> {
  const original = domain.chunk(ctx, chunkId, documentId, 'chunk.write'); mutable(original);
  const data = payload === undefined ? undefined : input(payload);
  if (data && 'content' in data) text(data.content);
  if (data && 'is_enabled' in data && typeof data.is_enabled !== 'boolean') fail(400, 'invalid_chunk_enabled', 'Chunk enabled flag must be boolean');
  if (data && 'metadata' in data && data.metadata !== null) input(data.metadata);
  const document = domain.doc(ctx, documentId); domain.cancel(ctx, [document]);
  return domain.db.transaction(() => {
    const chunk = domain.chunk(ctx, chunkId, documentId, 'chunk.write'); mutable(chunk);
    const doc = domain.doc(ctx, documentId), kbId = String(doc.knowledge_base_id), chunks = domain.chunks(ctx, doc);
    for (const c of chunks) domain.removeIndex(ctx, c);
    if (!data) {
      domain.db.run('DELETE FROM chunks WHERE id=? AND tenant_id=? AND knowledge_base_id=? AND knowledge_id=?', chunkId, ctx.tenantId, kbId, documentId);
      relationships(domain, ctx, doc, { ...chunk, deleted_at: now() });
    } else {
      const patch: Record<string, unknown> = { updated_at: now() };
      if ('content' in data) { patch.content = data.content; patch.content_hash = createHash('sha256').update(String(data.content)).digest('hex'); }
      if ('is_enabled' in data) patch.is_enabled = data.is_enabled;
      if ('metadata' in data) patch.metadata = data.metadata;
      const current = domain.db.update('chunks', chunkId, patch)!;
      relationships(domain, ctx, doc, data.is_enabled === false && chunk.is_enabled === true ? current : undefined);
    }
    pendingGraph(domain, ctx, doc, 'update'); domain.markDocument(ctx, doc); refreshWiki(domain, ctx, doc, false); pendingWiki(domain, ctx, doc);
    invalidateEvaluations(domain, ctx, [kbId], [documentId]);
    for (const c of domain.chunks(ctx, doc)) domain.index.indexKeyword(domain.scope(ctx, kbId), String(c.id));
    return data ? domain.chunkDto(domain.chunk(ctx, chunkId, documentId)) : {};
  });
}
