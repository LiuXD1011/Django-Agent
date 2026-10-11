import type { CoreApplication } from '../application.js';
import type { JsonObject } from '../contracts.js';
import { AppError } from '../errors.js';
import { KnowledgeService } from '../knowledge/index.js';
import { SearchIndex } from '../retrieval/index.js';

function optionalString(data: JsonObject, ...keys: string[]): string | undefined {
  const value = keys.map(key => data[key]).find(value => value !== undefined && value !== null && value !== '');
  if (value === undefined) return;
  if (typeof value !== 'string') throw new AppError(400, 'invalid_field', '请求字段必须是文本。');
  return value;
}
function identifiers(data: JsonObject) { return data.ids ?? data.knowledge_ids ?? data.knowledgeIds ?? []; }
export function registerKnowledgeRoutes(app: CoreApplication) {
  const index = new SearchIndex(app.database);
  const knowledge = new KnowledgeService(app.database, app.auth, index, app.jobs);
  const bases = knowledge.knowledgeBases;
  app.route('GET', '/api/v1/knowledge-bases', c => bases.list(c.auth, Object.fromEntries(c.query)));
  app.route('POST', '/api/v1/knowledge-bases', c => bases.create(c.auth, c.body));
  app.route('POST', '/api/v1/knowledge-bases/copy', c => bases.copy(c.auth, optionalString(c.body, 'source_id') ?? ''));
  app.route('GET', '/api/v1/knowledge-bases/:id', c => bases.get(c.auth, c.params.id!));
  app.route('PUT', '/api/v1/knowledge-bases/:id', c => bases.update(c.auth, c.params.id!, c.body));
  app.route('PATCH', '/api/v1/knowledge-bases/:id', c => bases.update(c.auth, c.params.id!, c.body));
  app.route('DELETE', '/api/v1/knowledge-bases/:id', async c => {
    app.graph.queueKnowledgeBaseCleanup(c.auth, c.params.id!);
    const removed = await bases.delete(c.auth, c.params.id!);
    const cleanup = await app.graph.processPending(c.auth, c.params.id!, { signal: c.signal });
    const stillPending = Number(cleanup.remaining) > 0;
    const warnings = (removed.warnings as JsonObject[]).filter(item => item.code !== 'graph_cleanup_pending');
    return { ...removed, pending: stillPending ? ['graph_cleanup'] : [], warnings: [...warnings, ...(cleanup.warnings as JsonObject[])], graph_cleanup: cleanup };
  });
  app.route('PUT', '/api/v1/knowledge-bases/:id/pin', c => {
    if (c.body.is_pinned !== undefined && typeof c.body.is_pinned !== 'boolean') throw new AppError(400, 'invalid_pin', '置顶状态必须是布尔值。');
    return bases.pin(c.auth, c.params.id!, c.body.is_pinned as boolean | undefined);
  });
  app.route('GET', '/api/v1/knowledge-bases/:id/move-targets', c => bases.moveTargets(c.auth, c.params.id!));
  app.route('GET', '/api/v1/knowledge-bases/:id/knowledge', c => knowledge.list(c.auth, c.params.id!, Object.fromEntries(c.query)));
  app.route('DELETE', '/api/v1/knowledge-bases/:id/knowledge', c => knowledge.clear(c.auth, c.params.id!));
  app.route('GET', '/api/v1/knowledge-bases/:id/knowledge/stats', c => knowledge.stats(c.auth, c.params.id!));
  const remove = (data: JsonObject, kbId?: string) => ({ ids: identifiers(data), kbId: kbId ?? optionalString(data, 'kb_id', 'knowledge_base_id', 'source_kb_id') });
  app.route('POST', '/api/v1/knowledge-bases/:id/knowledge/batch-delete', c => { const data = remove(c.body, c.params.id!); return knowledge.batchDelete(c.auth, data.ids, data.kbId); });
  app.route('POST', '/api/v1/knowledge/batch-delete', c => { const data = remove(c.body); return knowledge.batchDelete(c.auth, data.ids, data.kbId); });
  for (const path of ['/api/v1/knowledge/move', '/api/v1/knowledge-bases/:id/knowledge/move']) {
    app.route('POST', path, c => knowledge.move(c.auth, identifiers(c.body), optionalString(c.body, 'target_kb_id', 'target_knowledge_base_id', 'knowledge_base_id') ?? '', c.params.id ?? optionalString(c.body, 'source_kb_id', 'kb_id')));
  }
  app.route('GET', '/api/v1/knowledge/batch', c => knowledge.batch(c.auth, c.query.get('ids') ?? ''));
  app.route('GET', '/api/v1/knowledge/search', c => knowledge.list(c.auth, undefined, Object.fromEntries(c.query)));
  app.route('GET', '/api/v1/knowledge/:id', c => knowledge.get(c.auth, c.params.id!));
  app.route('PUT', '/api/v1/knowledge/:id', c => knowledge.update(c.auth, c.params.id!, c.body));
  app.route('PATCH', '/api/v1/knowledge/:id', c => knowledge.update(c.auth, c.params.id!, c.body));
  app.route('DELETE', '/api/v1/knowledge/:id', c => knowledge.delete(c.auth, c.params.id!));
  app.route('GET', '/api/v1/chunks/by-id/:chunk', c => knowledge.getChunk(c.auth, c.params.chunk!));
  app.route('GET', '/api/v1/chunks/:id', c => knowledge.listChunks(c.auth, c.params.id!, Object.fromEntries(c.query)));
  app.route('DELETE', '/api/v1/chunks/:id', c => knowledge.deleteContent(c.auth, c.params.id!));
  app.route('GET', '/api/v1/chunks/:id/:chunk', c => knowledge.getChunk(c.auth, c.params.chunk!, c.params.id!));
  app.route('PUT', '/api/v1/chunks/:id/:chunk', c => knowledge.updateChunk(c.auth, c.params.id!, c.params.chunk!, c.body));
  app.route('PATCH', '/api/v1/chunks/:id/:chunk', c => knowledge.updateChunk(c.auth, c.params.id!, c.params.chunk!, c.body));
  app.route('DELETE', '/api/v1/chunks/:id/:chunk', c => knowledge.deleteChunk(c.auth, c.params.id!, c.params.chunk!));
  app.route('GET', '/api/v1/knowledge-bases/:id/tags', c => knowledge.listTags(c.auth, c.params.id!));
  app.route('POST', '/api/v1/knowledge-bases/:id/tags', c => knowledge.createTag(c.auth, c.params.id!, c.body));
  app.route('GET', '/api/v1/knowledge-bases/:id/tags/:tag', c => knowledge.getTag(c.auth, c.params.id!, c.params.tag!));
  app.route('PUT', '/api/v1/knowledge-bases/:id/tags/:tag', c => knowledge.updateTag(c.auth, c.params.id!, c.params.tag!, c.body));
  app.route('PATCH', '/api/v1/knowledge-bases/:id/tags/:tag', c => knowledge.updateTag(c.auth, c.params.id!, c.params.tag!, c.body));
  app.route('DELETE', '/api/v1/knowledge-bases/:id/tags/:tag', c => knowledge.deleteTag(c.auth, c.params.id!, c.params.tag!));
  return { index, knowledge };
}
