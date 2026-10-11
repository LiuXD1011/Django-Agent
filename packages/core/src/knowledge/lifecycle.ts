import type { AuthContext, JsonObject } from '../contracts.js';
import type { Row } from '../storage/database.js';
import { planCleanup, recoverCleanup, sealCleanup } from './artifacts.js';
import { invalidateEvaluations, pendingGraph, refreshWiki } from './derived.js';
import { KnowledgeDomain, now, warning } from './domain.js';
import { fail } from './config.js';

export function cleanRetiredDocuments(domain: KnowledgeDomain, ctx: AuthContext, docs: Row[]): string | undefined {
  for (const doc of docs) {
    const current = domain.db.read('knowledges', String(doc.id));
    if (!current || current.deleted_at === null || String(current.tenant_id) !== ctx.tenantId || current.knowledge_base_id !== doc.knowledge_base_id) fail(409, 'cleanup_source_changed', 'Retired document changed before cleanup');
    domain.kb(ctx, String(doc.knowledge_base_id), 'document.delete');
  }
  const key = planCleanup(domain, ctx, docs, true);
  for (const doc of docs) {
    pendingGraph(domain, ctx, doc, 'delete');
    for (const ref of domain.db.all('SELECT id FROM chunks WHERE tenant_id=? AND knowledge_base_id=? AND knowledge_id=?', ctx.tenantId, String(doc.knowledge_base_id), String(doc.id))) domain.removeIndex(ctx, domain.db.read('chunks', String(ref.id))!);
    for (const table of ['chunks', 'knowledge_images']) domain.db.run(`DELETE FROM ${table} WHERE tenant_id=? AND knowledge_base_id=? AND knowledge_id=?`, ctx.tenantId, String(doc.knowledge_base_id), String(doc.id));
  }
  sealCleanup(domain, key);
  return key;
}

/** Local source rows, FTS/vector deletes, Wiki retractions and retirement commit together. */
export async function deleteDocuments(domain: KnowledgeDomain, ctx: AuthContext, docs: Row[], retire: boolean, extra?: () => void): Promise<JsonObject> {
  let cleanup: string | undefined;
  domain.db.transaction(() => {
    domain.assert(ctx, 'document.delete');
    for (const d of docs) domain.doc(ctx, String(d.id), 'document.delete', String(d.knowledge_base_id));
    cleanup = planCleanup(domain, ctx, docs, retire);
    for (const document of docs) {
      const d = domain.doc(ctx, String(document.id)), kbId = String(d.knowledge_base_id), chunks = domain.db.all('SELECT id FROM chunks WHERE tenant_id=? AND knowledge_base_id=? AND knowledge_id=?', ctx.tenantId, String(d.knowledge_base_id), String(d.id)).map(row => domain.db.read('chunks', String(row.id))!);
      refreshWiki(domain, ctx, d, true);
      pendingGraph(domain, ctx, d, 'delete');
      for (const c of chunks) domain.removeIndex(ctx, c);
      domain.db.run('DELETE FROM chunks WHERE tenant_id=? AND knowledge_base_id=? AND knowledge_id=?', ctx.tenantId, kbId, String(d.id));
      domain.db.run('DELETE FROM knowledge_images WHERE tenant_id=? AND knowledge_base_id=? AND knowledge_id=?', ctx.tenantId, kbId, String(d.id));
      domain.invalidate(ctx, kbId); invalidateEvaluations(domain, ctx, [kbId], [String(d.id)]);
      if (retire) domain.db.update('knowledges', String(d.id), { deleted_at: now(), parse_status: 'cancelled', pending_subtasks_count: 0, updated_at: now() });
      else domain.markDocument(ctx, d);
    }
    extra?.();
    sealCleanup(domain, cleanup);
  });
  const warnings = cleanup ? recoverCleanup(domain, ctx, cleanup) : [];
  warnings.push(warning('graph_cleanup_pending', 'graph', 'Local document data was removed; graph cleanup requires the graph integration'));
  return { warnings, pending: ['graph_cleanup'], task_id: '' };
}
