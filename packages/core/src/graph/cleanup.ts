import { createHash } from 'node:crypto';
import type { AuthService } from '../auth/index.js';
import type { AuthContext, JsonObject } from '../contracts.js';
import { AppError } from '../errors.js';
import type { CoreDatabase, Row } from '../storage/database.js';
import { deleteDocument, deleteKnowledgeBase } from './templates.js';

const object = (value: unknown): JsonObject => value && typeof value === 'object' && !Array.isArray(value) ? value as JsonObject : {};
const fail = (status: number, code: string): never => { throw new AppError(status, code, 'Graph cleanup scope or deletion ticket is unavailable'); };
export function cleanupScope(db: CoreDatabase, auth: AuthService, ctx: AuthContext, kbId: string): Row {
  auth.assertCan(ctx, 'read');
  const kb = db.read('knowledge_bases', kbId);
  if (!kb || String(kb.tenant_id) !== ctx.tenantId) return fail(404, 'knowledge_base_not_found');
  auth.assertCan(ctx, kb.deleted_at === null ? 'document.write' : 'kb.delete');
  return kb;
}
/** Trusted SQLite outbox only; never accept its payload or a Cypher statement from a renderer. */
export function pendingCleanup(db: CoreDatabase, auth: AuthService, ctx: AuthContext, kbId: string, key: string) {
  const kb = cleanupScope(db, auth, ctx, kbId);
  if (typeof key !== 'string' || !/^knowledge\.graph\.pending:[a-zA-Z0-9-]{1,100}$/.test(key)) return fail(404, 'graph_cleanup_ticket_not_found');
  const saved = db.get('SELECT value FROM desktop_meta WHERE key=?', key);
  if (!saved) return fail(404, 'graph_cleanup_ticket_not_found');
  let ticket: JsonObject; try { ticket = object(JSON.parse(String(saved.value))); } catch { return fail(409, 'graph_cleanup_ticket_invalid'); }
  const namespace = createHash('sha256').update(JSON.stringify([ctx.tenantId, kbId])).digest('hex');
  if (![1, 2].includes(Number(ticket.schema_version)) || ticket.status !== 'pending' || ticket.tenant_id !== ctx.tenantId || ticket.knowledge_base_id !== kbId || ticket.namespace !== undefined && ticket.namespace !== namespace) return fail(404, 'graph_cleanup_ticket_not_found');
  const params: JsonObject = { tenant_id: ctx.tenantId, knowledge_base_id: kbId, namespace };
  if (ticket.operation === 'delete_knowledge_base') {
    auth.assertCan(ctx, 'kb.delete');
    if (ticket.schema_version !== 2 || ticket.namespace !== namespace) return fail(409, 'graph_cleanup_ticket_invalid');
    if (kb.deleted_at === null) return fail(409, 'graph_cleanup_source_active');
    return { key, raw: String(saved.value), ticket, params, statement: deleteKnowledgeBase, skip: false };
  }
  if (!['delete', 'move', 'update'].includes(String(ticket.operation)) || typeof ticket.knowledge_id !== 'string' || !ticket.knowledge_id) return fail(409, 'graph_cleanup_ticket_invalid');
  const doc = db.read('knowledges', ticket.knowledge_id);
  if (!doc || String(doc.tenant_id) !== ctx.tenantId || doc.knowledge_base_id !== kbId && !(ticket.operation === 'move' && doc.knowledge_base_id === ticket.target_knowledge_base_id)) return fail(404, 'graph_cleanup_ticket_not_found');
  const retired = doc.deleted_at !== null || doc.knowledge_base_id !== kbId || kb.deleted_at !== null;
  let generation = typeof ticket.generation === 'string' ? ticket.generation : '';
  if (!retired && ticket.schema_version === 1) {
    // Imported wall-clock timestamps cannot prove which generation preceded an old ticket.
    // Keep ambiguous live-source work pending; tombstoned/moved sources can safely delete all.
    const snapshot = db.read('generic_resources', `graph:${createHash('sha256').update(JSON.stringify([ctx.tenantId, kbId, doc.id])).digest('hex')}`);
    if (snapshot) return fail(409, 'graph_cleanup_generation_missing');
  }
  return { key, raw: String(saved.value), ticket, params: { ...params, knowledge_id: ticket.knowledge_id, generation: retired ? '' : generation }, statement: deleteDocument, skip: !retired && !generation };
}
