import { CoreBinary, CoreStream, type CoreApplication } from '../application.js';
import type { JsonObject } from '../contracts.js';
import { ChatService, ModelCaller } from '../chat/index.js';
import { AppError } from '../errors.js';
import { retrievalOptions } from './retrieval-options.js';
import { createChatAttachmentHooks } from '../chat/attachments.js';
import type { DocumentParser } from '../documents/parser.js';
import type { ChatObserver } from '../observability/types.js';

function identifier(body: JsonObject, ...fields: string[]): string {
  const value = fields.map(field => body[field]).find(value => value !== undefined && value !== '');
  if (typeof value !== 'string') throw new AppError(400, 'invalid_request_id', '请指定回复或请求标识。');
  return value;
}
export function registerChatRoutes(app: CoreApplication, parser?: DocumentParser, observer?: ChatObserver): ChatService {
  const chat = new ChatService(app.database, app.auth, { models: app.models, index: app.searchIndex, jobs: app.jobs, hooks: {
    observability: observer,
    ...createChatAttachmentHooks(app.database, app.auth, { parser, uploads: app.chatUploads }),
    agent: execution => app.agents.execute(execution),
    memory: execution => app.memory.chatContext(execution),
    maintenance: (execution, outcome) => app.memory.maintenance(execution, outcome),
    deleteMemory: (ctx, sessionId) => app.memory.deleteSession(ctx, sessionId),
    retrievalOptions: (ctx, scope) => retrievalOptions(app, ctx, scope),
    graphRetrieval: (execution, query, options) => app.graph.search(execution.context, execution.scope.knowledgeBaseIds ?? [], query, {
      signal: execution.signal, limit: options.limit, seenChunkIds: options.seenChunkIds,
    }),
  } });
  app.route('GET', '/api/v1/sessions', c => chat.list(c.auth, Object.fromEntries(c.query)));
  app.route('POST', '/api/v1/sessions', c => chat.create(c.auth, c.body));
  app.route('DELETE', '/api/v1/sessions/batch', c => chat.batchDelete(c.auth, c.body));
  app.route('GET', '/api/v1/sessions/:id', c => chat.get(c.auth, c.params.id!));
  app.route('PUT', '/api/v1/sessions/:id', c => chat.update(c.auth, c.params.id!, c.body));
  app.route('PATCH', '/api/v1/sessions/:id', c => chat.update(c.auth, c.params.id!, c.body));
  app.route('DELETE', '/api/v1/sessions/:id', c => chat.delete(c.auth, c.params.id!));
  app.route('POST', '/api/v1/sessions/:id/pin', c => chat.pin(c.auth, c.params.id!, true));
  app.route('DELETE', '/api/v1/sessions/:id/pin', c => chat.pin(c.auth, c.params.id!, false));
  app.route('DELETE', '/api/v1/sessions/:id/messages', c => chat.clearMessages(c.auth, c.params.id!));
  app.route('POST', '/api/v1/sessions/:id/stop', c => chat.stop(c.auth, c.params.id!, identifier(c.body, 'message_id', 'request_id', 'id')));
  app.route('GET', '/api/v1/sessions/:id/trajectory', c => chat.trajectory(c.auth, c.params.id!));
  app.route('GET', '/api/v1/sessions/:id/context-usage', c => chat.contextUsage(c.auth, c.params.id!, c.query.get('model_id') ?? ''));
  app.route('GET', '/api/v1/sessions/:id/events', c => chat.events(c.auth, c.params.id!, Object.fromEntries(c.query)));
  app.route('GET', '/api/v1/sessions/:id/actors', c => chat.actors(c.auth, c.params.id!));
  app.route('GET', '/api/v1/sessions/:id/actors/:actor', c => chat.actor(c.auth, c.params.id!, c.params.actor!));
  app.route('POST', '/api/v1/sessions/:id/actors/:actor/cancel', c => chat.cancelActor(c.auth, c.params.id!, c.params.actor!));
  app.route('POST', '/api/v1/sessions/:id/uploads', c => {
    if (!c.upload || !(c.upload.bytes instanceof Uint8Array)) throw new AppError(400, 'upload_required', '请选择附件。');
    const kind = c.body.kind ?? (/\.(?:png|jpe?g|gif|webp|bmp|tiff?|svg)$/i.test(c.upload.name) ? 'image' : 'file');
    if (!['file', 'image'].includes(String(kind))) throw new AppError(400, 'invalid_upload_kind', '附件类型不正确。');
    return app.chatUploads.store(c.auth, c.params.id!, { name: c.upload.name, bytes: c.upload.bytes, kind: kind as 'file' | 'image' }, () => c.signal?.throwIfAborted());
  });
  app.route('GET', '/api/v1/sessions/:id/uploads/:upload', async c => {
    const file = await app.chatUploads.read(c.auth, c.params.id!, c.params.upload!, () => c.signal?.throwIfAborted());
    const mime = ['image/png', 'image/jpeg', 'image/gif', 'image/webp', 'text/plain', 'application/pdf'].includes(file.mimeType) ? file.mimeType : 'application/octet-stream';
    return new CoreBinary(file.bytes, file.name, mime, file.sha256);
  });
  app.route('POST', '/api/v1/sessions/:id/branch', c => chat.branch(c.auth, c.params.id!, c.body));
  app.route('POST', '/api/v1/sessions/:id/generate_title', async c => {
    const session = chat.get(c.auth, c.params.id!), source = c.body.title ?? c.body.query ?? '新的对话';
    if (typeof source !== 'string' || source.length > 100000) throw new AppError(400, 'invalid_title_source', '标题来源格式不正确。');
    const assert = () => { chat.get(c.auth, c.params.id!); app.auth.assertCan(c.auth, 'write', c.auth.tenantId, c.auth.userId); };
    const caller = new ModelCaller(app.database, app.models, c.auth, { session_id: session.id! }, assert, () => {});
    const result = await caller.complete(String((session.agent_config as JsonObject).model_id || 'KnowledgeQA'), [{ role: 'user', content: `请为下面的对话生成20字以内的中文标题，只输出标题。\n\n${source}` }], { signal: c.signal, maxTokens: 40 }, 'title');
    assert(); const title = result.content.trim().replace(/^['"“”]+|['"“”]+$/g, '').slice(0, 80);
    if (!title) throw new AppError(502, 'empty_title', '模型未返回标题。');
    return chat.update(c.auth, c.params.id!, { title });
  });
  app.route('GET', '/api/v1/messages/search', c => chat.searchMessages(c.auth, Object.fromEntries(c.query)));
  app.route('GET', '/api/v1/messages/chat-history-stats', c => chat.stats(c.auth));
  app.route('GET', '/api/v1/messages/:id/load', c => chat.loadMessages(c.auth, c.params.id!, Object.fromEntries(c.query)));
  app.route('DELETE', '/api/v1/messages/:id/:message', c => chat.deleteMessage(c.auth, c.params.id!, c.params.message!));
  app.route('GET', '/api/v1/sessions/continue-stream/:id', c => {
    const id = c.query.get('message_id') || c.query.get('request_id');
    if (!id) throw new AppError(400, 'message_required', '请指定需要恢复的回复。');
    chat.response(c.auth, c.params.id!, id);
    const after = Number(c.query.get('after_offset') ?? 0);
    if (!Number.isSafeInteger(after) || after < 0) throw new AppError(400, 'invalid_offset', '流事件位置不正确。');
    return new CoreStream(chat.stream(c.auth, c.params.id!, id, { signal: c.signal, afterOffset: after }));
  });
  for (const [path, agent] of [['knowledge-chat', false], ['agent-chat', true]] as const) app.route('POST', `/api/v1/${path}/:id`, async c => {
    const started = chat.start(c.auth, c.params.id!, c.body, c.request.id, agent);
    const work = app.runTask(() => chat.run(c.auth, c.params.id!, started.request_id));
    void work.catch(() => { try { app.database.transaction(() => { const scope = { tenantId: c.auth.tenantId, userId: c.auth.userId }, job = app.jobs.get(started.job_id, scope); if (!started.idempotent && job.status === 'queued' && job.attempt === 0) app.jobs.cancelByRequest(job.requestId, scope); }); } catch {} });
    if (c.body.stream === true) return new CoreStream(chat.stream(c.auth, c.params.id!, started.request_id, { signal: c.signal }));
    return work;
  });
  return chat;
}
