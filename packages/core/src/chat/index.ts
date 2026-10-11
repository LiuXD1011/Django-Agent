import { createHash, randomUUID } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';
import type { AuthContext, Json, JsonObject, ChatMessage } from '../contracts.js';
import type { AuthService } from '../auth/index.js';
import type { CoreDatabase, Row } from '../storage/database.js';
import { publicParameters } from '../storage/credentials.js';
import type { ModelConfigurationService } from '../settings/model-configuration.js';
import { ModelRuntimeError } from '../models/runtime.js';
import { JobQueue, type JobContext } from '../jobs/queue.js';
import { StreamStore } from '../jobs/streams.js';
import { SessionEventJournal } from '../jobs/journal.js';
import { SearchIndex } from '../retrieval/search-index.js';
import { retrieveChat } from './retrieval.js';
import { currentObservation } from '../observability/context.js';
import type { SearchOptions, SearchScope } from '../retrieval/types.js';
import { ModelCaller } from './calls.js';
import { array, bounded, ChatError, fail, historyMessages, ids, memorySystemPrompt, now, object, sessionDto, state, text, userContent } from './internal.js';
import type { ChatExecution, ChatForkInput, ChatForkHandle, ChatFrame, ChatHooks, ChatOutcome, ChatSearchHit, ChatSearchResult, ChatStart } from './types.js';
export { ChatError, ModelCaller };
export { ManagedChatUploads, createChatAttachmentHooks } from './attachments.js';
export type { ChatUploadInput, ChatUploadBytes, ChatAttachmentOptions, ChatAttachmentHooks } from './attachments.js';
export type { ChatExecution, ChatForkInput, ChatForkHandle, ChatFrame, ChatHooks, ChatOutcome, ChatSearchHit, ChatSearchResult, ChatStart } from './types.js';
export interface ChatDependencies { models: ModelConfigurationService; index?: SearchIndex; jobs?: JobQueue; hooks?: ChatHooks }

export class ChatService {
  readonly jobs: JobQueue; readonly index: SearchIndex; readonly streams: StreamStore; readonly journal: SessionEventJournal;
  private readonly kind = 'chat.turn';
  private readonly maintenanceKind = 'chat.maintenance';
  private readonly actorKind = 'chat.actor';
  private readonly actorCallbacks = new Map<string, (execution: ChatExecution) => Promise<Json>>();
  private readonly actorRuns = new Map<string, Promise<Json>>();
  private readonly runs = new Map<string, Promise<JsonObject>>();
  private readonly background = new Set<Promise<void>>();
  private readonly workers = new Map<string, Promise<Json>>();
  private readonly claims = new Map<string, JobContext>();
  private readonly workerSignals = new Map<string, AbortController>();
  private readonly owned = new Map<string, { context: AuthContext; sessionId: string; requestId: string }>();
  private readonly editing = new Set<string>(); private closed = false; private closing: Promise<void> | undefined;
  constructor(readonly db: CoreDatabase, readonly auth: AuthService, readonly dependencies: ChatDependencies) {
    this.jobs = dependencies.jobs ?? new JobQueue(db); this.index = dependencies.index ?? new SearchIndex(db);
    this.streams = new StreamStore(db); this.journal = new SessionEventJournal(db);
    const register = (kind: string, work: (job: JobContext, payload: JsonObject) => Promise<Json>) => this.jobs.register(kind, (job, payload) => {
      const controller = new AbortController(), local = { ...job, signal: AbortSignal.any([job.signal, controller.signal]) }; this.claims.set(job.jobId, job); this.workerSignals.set(job.jobId, controller);
      // close() can run after SQLite claim but before this handler's microtask.
      if (this.closing || this.closed) controller.abort(new ChatError(409, 'chat_cancelled', 'Chat service is closing'));
      const promise = work(local, payload); this.workers.set(job.jobId, promise);
      void promise.finally(() => { if (this.workers.get(job.jobId) === promise) { this.workers.delete(job.jobId); this.claims.delete(job.jobId); this.workerSignals.delete(job.jobId); } }).catch(() => {}); return promise;
    });
    register(this.kind, (job, payload) => this.generate(job, payload));
    register(this.maintenanceKind, (job, payload) => this.maintain(job, payload));
    register(this.actorKind, (job, payload) => this.runActor(job, payload));
  }
  private available(): void { if (this.closed) fail(503, 'chat_closed', 'Chat service is closed'); }
  private stopWorker(job: JobContext): void {
    this.workerSignals.get(job.jobId)?.abort(new ChatError(409, 'chat_cancelled', 'Chat worker stopped'));
    // Lost workers abort their own network request without cancelling a replacement owner.
    try { job.publish(() => { const r = this.db.get('select request_id,tenant_id,user_id from desktop_jobs where id=?', job.jobId)!; this.jobs.cancelByRequest(String(r.request_id), { tenantId: String(r.tenant_id), userId: String(r.user_id) }); }); } catch {}
  }
  private cancelOwned(jobId: string): void {
    const owner = this.owned.get(jobId); if (!owner) return;
    const claim = this.claims.get(jobId); if (claim) { this.stopWorker(claim); return; }
    this.db.transaction(() => { const job = this.jobs.get(jobId, this.scope(owner.context)); if (job.status === 'queued') this.jobs.cancelByRequest(job.requestId, job.scope); });
  }
  private scope(ctx: AuthContext) { return { tenantId: ctx.tenantId, userId: ctx.userId }; }
  private session(ctx: AuthContext, id: string, write = false): Row {
    this.available(); this.auth.assertCan(ctx, 'read'); const row = this.db.read('sessions', id);
    if (!ctx.userId || !row || row.deleted_at !== null || String(row.tenant_id) !== ctx.tenantId || row.user_id !== ctx.userId) fail(404, 'session_not_found', 'Session not found');
    const config = object(row!.agent_config);
    if (ctx.channel ? config.embed_channel_id !== ctx.channel.id || config.channel_guest_id !== ctx.channel.guestId || config.channel_grant_id !== ctx.channel.grantId : !!config.embed_channel_id) fail(404, 'session_not_found', 'Session not found');
    this.auth.assertCan(ctx, write ? 'write' : 'read', ctx.tenantId, ctx.userId); return row!;
  }
  private message(ctx: AuthContext, sessionId: string, id: string): Row {
    this.session(ctx, sessionId); const row = this.db.all("select id from messages where session_id=? and deleted_at is null and (id=? or request_id=?) order by case role when 'assistant' then 0 else 1 end limit 1", sessionId, id, id)[0];
    if (!row) fail(404, 'message_not_found', 'Message not found'); return this.db.read('messages', String(row!.id))!;
  }
  private projection(row: Row): JsonObject {
    const result = publicParameters({ ...row }); delete result.deleted_at;
    result.attachments = array(result.attachments).map(v => { const item = { ...object(v) }; delete item.data; delete item.path; return item; });
    result.actor_traces = this.db.all('select id from agent_actors where session_id=? and parent_message_id=? and deleted_at is null order by created_at,id', String(row.session_id), String(row.id)).map(r => publicParameters(this.db.read('agent_actors', String(r.id))!));
    return result;
  }
  private validateSelection(ctx: AuthContext, value: Json | undefined): string[] {
    const selected = ids(value);
    if (ctx.channel && selected.some(id => !ctx.channel!.knowledgeBaseIds.includes(id))) fail(403, 'channel_scope_forbidden', 'Knowledge base is outside the public channel selection');
    for (const id of selected) {
      const kb = this.db.read('knowledge_bases', id); if (!kb || kb.deleted_at !== null || String(kb.tenant_id) !== ctx.tenantId) fail(404, 'knowledge_base_not_found', 'Knowledge base not found');
    } return selected;
  }
  private validateConfig(ctx: AuthContext, config: JsonObject): void {
    this.validateSelection(ctx, config.knowledge_base_ids ?? []);
    if (ctx.channel && (config.embed_channel_id !== ctx.channel.id || config.channel_guest_id !== ctx.channel.guestId || config.channel_grant_id !== ctx.channel.grantId || config.enable_memory !== false || config.web_search_enabled !== false || ids(config.mcp_service_ids ?? []).length)) fail(403, 'channel_config_forbidden', 'Public channel configuration is fixed');
    if (config.agent_id) { const agent = this.db.read('generic_resources', String(config.agent_id)); if (!agent || agent.deleted_at !== null || agent.resource_type !== 'agents' || String(agent.tenant_id) !== ctx.tenantId) fail(404, 'agent_not_found', 'Agent not found'); }
    for (const id of ids(config.mcp_service_ids ?? [])) { const r = this.db.read('generic_resources', id); if (!r || r.deleted_at !== null || r.resource_type !== 'mcp_services' || String(r.tenant_id) !== ctx.tenantId) fail(404, 'mcp_not_found', 'MCP service not found'); }
  }
  create(ctx: AuthContext, input: JsonObject = {}): JsonObject {
    this.available(); this.auth.assertCan(ctx, 'write', ctx.tenantId, ctx.userId);
    if (!ctx.userId) fail(403, 'user_principal_required', 'A user account is required');
    const config = state(input); if (input.knowledge_base_id && !object(input.agent_config).knowledge_base_ids && input.knowledge_base_ids === undefined) { config.knowledge_base_ids = [text(input.knowledge_base_id, 128)]; config.knowledge_selection_explicit = true; }
    this.validateConfig(ctx, config);
    return sessionDto(this.db.insert('sessions', { tenant_id: ctx.tenantId, user_id: ctx.userId, title: input.title === undefined ? '新的对话' : text(input.title, 255), description: input.description === undefined ? '' : text(input.description, 16384), agent_id: String(config.agent_id), knowledge_base_id: String(array(config.knowledge_base_ids)[0] ?? ''), agent_config: config }));
  }
  get(ctx: AuthContext, id: string): JsonObject { return sessionDto(this.session(ctx, id)); }
  list(ctx: AuthContext, query: JsonObject = {}): JsonObject {
    this.available(); this.auth.assertCan(ctx, 'read'); if (ctx.channel) fail(403, 'channel_action_forbidden', 'Use the public session route'); const rows = this.db.all('select id from sessions where tenant_id=? and user_id=? and deleted_at is null order by is_pinned desc,updated_at desc,id desc', ctx.tenantId, ctx.userId).map(r => this.db.read('sessions', String(r.id))!);
    const q = String(query.query ?? query.keyword ?? query.q ?? '').toLocaleLowerCase(); const filtered = rows.filter(r => !object(r.agent_config).embed_channel_id && (!q || `${r.title}\n${r.description}`.toLocaleLowerCase().includes(q)));
    const size = bounded(query.page_size ?? query.limit, 20), page = bounded(query.page, 1, Number.MAX_SAFE_INTEGER);
    const offset = query.page === undefined && query.offset !== undefined ? Math.max(0, Number(query.offset) || 0) : (page - 1) * size;
    return { items: filtered.slice(offset, offset + size).map(sessionDto), page: Math.floor(offset / size) + 1, page_size: size, total: filtered.length };
  }
  update(ctx: AuthContext, id: string, input: JsonObject): JsonObject {
    return this.db.transaction(() => {
      const row = this.session(ctx, id, true), config = state(input, object(row.agent_config)); this.validateConfig(ctx, config);
      const values: JsonObject = { updated_at: now(), agent_config: config, agent_id: config.agent_id!, knowledge_base_id: String(array(config.knowledge_base_ids)[0] ?? '') };
      for (const key of ['title', 'description']) if (input[key] !== undefined) values[key] = text(input[key], key === 'title' ? 255 : 16384);
      if (input.knowledge_base_id !== undefined) { const selected = input.knowledge_base_id ? this.validateSelection(ctx, [text(input.knowledge_base_id, 128)]) : []; config.knowledge_base_ids = selected; config.knowledge_selection_explicit = true; values.knowledge_base_id = selected[0] ?? ''; }
      return sessionDto(this.db.update('sessions', id, values)!);
    });
  }
  pin(ctx: AuthContext, id: string, pinned: boolean): JsonObject { this.session(ctx, id, true); return sessionDto(this.db.update('sessions', id, { is_pinned: pinned, pinned_at: pinned ? now() : null, updated_at: now() })!); }
  loadMessages(ctx: AuthContext, id: string, query: JsonObject = {}): JsonObject {
    this.session(ctx, id); const limit = bounded(query.limit, 50); const before = String(query.before_time ?? query.before ?? '');
    const valid = before && Number.isFinite(Date.parse(before)) ? new Date(before).toISOString() : '';
    const rows = this.db.all(`select id from messages where session_id=? and visible_to_user=1 and deleted_at is null ${valid ? 'and created_at<?' : ''} order by created_at desc,rowid desc limit ?`, id, ...(valid ? [valid] : []), limit).map(r => this.db.read('messages', String(r.id))!).reverse();
    const items = rows.map(r => this.projection(r)); return { items, messages: items, has_more: rows.length >= limit };
  }
  searchMessages(ctx: AuthContext, query: JsonObject = {}): JsonObject {
    this.available(); this.auth.assertCan(ctx, 'read'); if (ctx.channel) fail(403, 'channel_action_forbidden', 'Use the public session route'); const q = String(query.query ?? query.q ?? '').toLocaleLowerCase();
    return { items: this.db.all('select m.id from messages m join sessions s on s.id=m.session_id where s.tenant_id=? and s.user_id=? and s.deleted_at is null and m.deleted_at is null and m.visible_to_user=1 order by m.created_at desc,m.id desc', ctx.tenantId, ctx.userId).map(r => this.db.read('messages', String(r.id))!).filter(r => !object(this.db.read('sessions', String(r.session_id))?.agent_config).embed_channel_id && (!q || String(r.content).toLocaleLowerCase().includes(q))).slice(0, 50).map(r => this.projection(r)) };
  }
  stats(ctx: AuthContext): JsonObject { this.available(); this.auth.assertCan(ctx, 'read'); if (ctx.channel) fail(403, 'channel_action_forbidden', 'Use the public session route'); return { total_sessions: this.db.get('select count(*) as n from sessions where tenant_id=? and user_id=? and deleted_at is null and coalesce(json_extract(agent_config,\'$.embed_channel_id\'),\'\')=\'\'', ctx.tenantId, ctx.userId)?.n ?? 0, total_messages: this.db.get('select count(*) as n from messages m join sessions s on s.id=m.session_id where s.tenant_id=? and s.user_id=? and s.deleted_at is null and m.deleted_at is null and m.visible_to_user=1 and coalesce(json_extract(s.agent_config,\'$.embed_channel_id\'),\'\')=\'\'', ctx.tenantId, ctx.userId)?.n ?? 0 }; }
  events(ctx: AuthContext, id: string, query: JsonObject = {}): JsonObject { this.session(ctx, id); const after = Math.max(0, Number(query.after_seq) || 0), limit = bounded(query.limit, 200, 2000), items = this.journal.read(id, this.scope(ctx), after, limit); return { items: items as unknown as Json[], has_more: items.length >= limit, next_after_seq: items.at(-1)?.seq ?? after }; }
  trajectory(ctx: AuthContext, id: string): JsonObject { this.session(ctx, id); const result = { session_id: id, ...this.journal.fold(id, this.scope(ctx)) }; return this.dependencies.hooks?.observability?.projectTrajectory(ctx, id, result) ?? result; }
  private observe<T>(execution: ChatExecution, work: () => Promise<T>, kind: 'chat.turn' | 'agent.run' | 'chat.maintenance'): Promise<T> { return this.dependencies.hooks?.observability?.run(execution, work, kind) ?? work(); }
  contextUsage(ctx: AuthContext, id: string, modelId = ''): JsonObject {
    const session = this.session(ctx, id), selected = modelId || String(object(session.agent_config).model_id || 'KnowledgeQA'); let window = 128000;
    try { window = this.dependencies.models.configuration(ctx, selected).context_window || window; } catch { /* No configured model: explicit estimate uses documented fallback window. */ }
    const history = this.history(ctx, session, '', true); const used = Math.ceil(JSON.stringify(history).length / 3);
    return { session_id: id, model_id: selected === 'KnowledgeQA' ? '' : selected, context_window: window, reserve_tokens: Math.min(8000, Math.floor(window / 4)), compact_threshold: Math.max(1, window - Math.min(8000, Math.floor(window / 4))), used_tokens: used, percent: Math.min(100, Math.round(used / window * 100)), estimated: true };
  }
  private jobRequest(ctx: AuthContext, sessionId: string, requestId: string): string { return `chat:${createHash('sha256').update(JSON.stringify([ctx.tenantId, ctx.userId, sessionId, requestId])).digest('hex')}`; }
  private requestKey(sessionId: string, requestId: string): string { return `chat.request:${createHash('sha256').update(JSON.stringify([sessionId, requestId])).digest('hex')}`; }
  private jobId(sessionId: string, requestId: string): string { const r = this.db.get('select value from desktop_meta where key=?', this.requestKey(sessionId, requestId)); return r ? String(object(JSON.parse(String(r.value))).job_id ?? '') : ''; }
  private resolveScope(ctx: AuthContext, session: Row, input: JsonObject): SearchScope {
    const config = object(session.agent_config); let selected: string[] | undefined;
    if (Object.hasOwn(input, 'knowledge_base_ids')) selected = this.validateSelection(ctx, input.knowledge_base_ids);
    else if (config.knowledge_selection_explicit === true || array(config.knowledge_base_ids).length) selected = this.validateSelection(ctx, config.knowledge_base_ids);
    else if (session.knowledge_base_id) selected = this.validateSelection(ctx, [String(session.knowledge_base_id)]);
    else selected = this.db.all('select id from knowledge_bases where tenant_id=? and deleted_at is null and is_temporary=0 order by id', ctx.tenantId).map(r => String(r.id));
    return { tenantId: ctx.tenantId, knowledgeBaseIds: selected };
  }
  start(ctx: AuthContext, sessionId: string, input: JsonObject, requestId = String(input.request_id ?? randomUUID()), agent = false): ChatStart {
    if (this.closing) fail(503, 'chat_closed', 'Chat service is closing');
    const session = this.session(ctx, sessionId, true); if (this.editing.has(sessionId)) fail(409, 'session_changing', 'Session history is changing');
    if (!/^[a-zA-Z0-9_.:-]{1,128}$/.test(requestId)) fail(400, 'invalid_request_id', 'Invalid request identifier');
    const query = text(input.query, 1000000); if (!query.trim()) fail(400, 'empty_query', 'A question is required');
    const clean = publicParameters(structuredClone(input)); delete clean.request_id;
    const signature = createHash('sha256').update(JSON.stringify({ input: clean, agent })).digest('hex');
    return this.db.transaction(() => {
      this.session(ctx, sessionId, true);
      const existing = this.db.get("select id from messages where session_id=? and request_id=? and role='assistant' and deleted_at is null", sessionId, requestId);
      if (existing) {
        const metadata = this.db.get('select value from desktop_meta where key=?', this.requestKey(sessionId, requestId));
        if (metadata && object(JSON.parse(String(metadata.value))).signature !== signature) fail(409, 'request_conflict', 'Request identifier already belongs to a different question');
        return { session_id: sessionId, request_id: requestId, assistant_message_id: String(existing.id), job_id: this.jobId(sessionId, requestId), message: this.projection(this.db.read('messages', String(existing.id))!), idempotent: true };
      }
      const config = state(clean, object(session.agent_config)); this.validateConfig(ctx, config); const scope = this.resolveScope(ctx, session, clean);
      const images = array(clean.images).map(v => { const img = typeof v === 'string' ? { url: v } : object(v); for (const key of ['path', 'file_path', 'source']) if (img[key] !== undefined) fail(400, 'upload_path_forbidden', 'Renderer file paths are not accepted'); if (img.upload_id) { if (!this.dependencies.hooks?.images || typeof img.upload_id !== 'string') fail(400, 'invalid_image', 'Managed image adapter is required'); return { upload_id: img.upload_id }; } const url = String(img.data ?? img.url ?? ''); if (!/^(data:image\/[\w.+-]+;base64,|https?:\/\/)/.test(url) || url.length > 16 * 1024 * 1024) fail(400, 'invalid_image', 'Invalid uploaded image'); return { url }; });
      const attachments = array(clean.attachment_uploads ?? clean.attachments); if (images.length > 5 || attachments.length > 5) fail(400, 'attachment_limit', 'At most five images and five attachments are supported');
      for (const v of attachments) { const a = object(v); if (a.data !== undefined && (typeof a.data !== 'string' || a.data.length > 32 * 1024 * 1024)) fail(400, 'invalid_attachment', 'Invalid uploaded attachment'); }
      const user = this.db.insert('messages', { session_id: sessionId, request_id: requestId, role: 'user', content: query, images, attachments, mentioned_items: array(clean.mentioned_items), is_completed: true, channel: String(clean.channel ?? 'web') });
      const assistant = this.db.insert('messages', { session_id: sessionId, request_id: requestId, role: 'assistant', content: '', channel: String(clean.channel ?? 'web'), agent_steps: [] });
      const job = this.jobs.create({ scope: this.scope(ctx), requestId: this.jobRequest(ctx, sessionId, requestId), kind: this.kind, recoveryPolicy: 'manual', payload: { context: { ...ctx }, session_id: sessionId, message_id: assistant.id!, user_message_id: user.id!, request_id: requestId, input: clean, config, agent, knowledge_base_ids: scope.knowledgeBaseIds ?? [] } });
      this.db.run('insert into desktop_meta(key,value) values(?,?)', this.requestKey(sessionId, requestId), JSON.stringify({ job_id: job.id, signature }));
      this.owned.set(job.id, { context: { ...ctx }, sessionId, requestId });
      if (!Number(session.event_seq)) this.journal.append(sessionId, requestId, 'session/started', { title: session.title!, kb_ids: scope.knowledgeBaseIds ?? [] }, this.scope(ctx));
      this.journal.append(sessionId, requestId, 'turn/user-message', { content: query, images: images.map(v => !v.url || v.url.startsWith('data:') ? '[uploaded image]' : v.url), attachments: attachments.map(v => ({ file_name: object(v).file_name ?? object(v).name ?? 'attachment', file_size: object(v).file_size ?? object(v).size ?? 0 })), mentioned_items: array(clean.mentioned_items), channel: String(clean.channel ?? 'web') }, this.scope(ctx));
      this.journal.append(sessionId, requestId, 'turn/assistant-created', { mode: agent ? 'agent' : 'rag', model_id: config.model_id!, channel: String(clean.channel ?? 'web') }, this.scope(ctx));
      this.db.update('sessions', sessionId, { agent_config: config, agent_id: config.agent_id!, updated_at: now() });
      this.streams.ensure(String(assistant.id), sessionId, this.scope(ctx));
      if (job.status === 'cancelled') this.finishCancelled(ctx, sessionId, String(assistant.id), requestId);
      return { session_id: sessionId, request_id: requestId, assistant_message_id: String(assistant.id), job_id: job.id, message: this.projection(this.db.read('messages', String(assistant.id))!), idempotent: false };
    });
  }
  private history(ctx: AuthContext, session: Row, currentId: string, agent: boolean): ChatMessage[] {
    this.session(ctx, String(session.id)); const mode = agent ? 'agent' : 'rag';
    const snapshotId = this.db.get('select id from context_snapshots where session_id=? and mode=? and is_active=1 and deleted_at is null order by updated_at desc limit 1', String(session.id), mode)?.id;
    const snapshot = snapshotId ? this.db.read('context_snapshots', String(snapshotId)) : undefined;
    const rows = this.db.all(`select id from messages where session_id=? and id<>? and is_completed=1 and visible_to_user=1 and deleted_at is null ${snapshot?.boundary_created_at ? 'and created_at>=?' : ''} order by created_at,rowid`, String(session.id), currentId, ...(snapshot?.boundary_created_at ? [String(snapshot.boundary_created_at)] : [])).map(r => this.db.read('messages', String(r.id))!);
    const messages = historyMessages(rows, bounded(session.max_rounds, 5, 20), agent);
    return snapshot?.content ? [{ role: 'system', content: String(snapshot.content) }, ...messages] : messages;
  }
  run(ctx: AuthContext, sessionId: string, id: string): Promise<JsonObject> {
    const message = this.message(ctx, sessionId, id), requestId = String(message.request_id), jobId = this.jobId(sessionId, requestId);
    if (!jobId) return Promise.resolve(this.response(ctx, sessionId, id));
    const existing = this.runs.get(jobId); if (existing) return existing;
    if (this.closing) fail(503, 'chat_closed', 'Chat service is closing');
    const promise = (async () => {
      await this.jobs.run(jobId); await this.workers.get(jobId)?.catch(() => {});
      if (!this.closed) this.reconcile(ctx, sessionId, String(message.id), requestId, jobId);
      return !this.closed ? this.response(ctx, sessionId, id) : {};
    })(); this.runs.set(jobId, promise);
    void promise.finally(() => { if (this.runs.get(jobId) === promise) this.runs.delete(jobId); }).catch(() => {}); return promise;
  }
  response(ctx: AuthContext, sessionId: string, id: string): JsonObject { const message = this.message(ctx, sessionId, id); return { message: this.projection(message), answer: message.content!, references: message.knowledge_references!, idempotent: true }; }
  private finishCancelled(ctx: AuthContext, sessionId: string, messageId: string, requestId: string): void {
    const message = this.message(ctx, sessionId, messageId);
    if (this.streams.finish(messageId, { content: String(message.content || '生成已取消。'), refs: array(message.knowledge_references), steps: array(message.agent_steps), durationMs: Number(message.agent_duration_ms), error: '生成已取消。' }, this.scope(ctx))) this.journal.append(sessionId, requestId, 'turn/completed', { content: message.content || '生成已取消。', stopped_reason: 'cancelled' }, this.scope(ctx));
    this.db.run("update agent_actors set status='cancelled',last_outcome='cancelled',completed_at=?,updated_at=? where session_id=? and parent_message_id=? and status in ('pending','running')", now(), now(), sessionId, messageId);
  }
  stop(ctx: AuthContext, sessionId: string, id: string): JsonObject {
    this.session(ctx, sessionId, true); if (!/^[a-zA-Z0-9_.:-]{1,128}$/.test(id)) fail(400, 'invalid_request_id', 'A message or request identifier is required');
    const row = this.db.get("select id,request_id from messages where session_id=? and deleted_at is null and role='assistant' and (id=? or request_id=?) limit 1", sessionId, id, id);
    const requestId = String(row?.request_id ?? id); this.jobs.cancelByRequest(this.jobRequest(ctx, sessionId, requestId), this.scope(ctx));
    this.jobs.cancelByRequest(`${this.jobRequest(ctx, sessionId, requestId)}:maintenance`, this.scope(ctx));
    for (const [jobId, owner] of this.owned) if (owner.sessionId === sessionId && owner.requestId === requestId) { this.cancelOwned(jobId); this.projectActor(jobId); }
    if (row) this.finishCancelled(ctx, sessionId, String(row.id), requestId);
    return { session_id: sessionId, message_id: row?.id ?? id, request_id: requestId, stopped: true };
  }
  private reconcile(ctx: AuthContext, sessionId: string, messageId: string, requestId: string, jobId: string): void {
    const message = this.message(ctx, sessionId, messageId); if (message.is_completed) return;
    const job = this.jobs.get(jobId, this.scope(ctx)); if (job.status === 'queued' || job.status === 'running') return;
    if (job.status === 'cancelled') { this.finishCancelled(ctx, sessionId, messageId, requestId); return; }
    const error = job.status === 'interrupted' ? '上游结果未知，请确认后重新发送。' : '生成失败，请检查模型配置后重新发送。';
    if (this.streams.finish(messageId, { content: String(message.content || error), refs: array(message.knowledge_references), steps: array(message.agent_steps), error, durationMs: Number(message.agent_duration_ms) }, this.scope(ctx))) this.journal.append(sessionId, requestId, 'turn/error', { message: error, stage: 'generation', result_unknown: job.status === 'interrupted' }, this.scope(ctx));
  }
  async *stream(ctx: AuthContext, sessionId: string, id: string, options: { afterOffset?: number; signal?: AbortSignal } = {}): AsyncGenerator<ChatFrame> {
    const message = this.message(ctx, sessionId, id), messageId = String(message.id), requestId = String(message.request_id), scope = this.scope(ctx);
    this.streams.ensure(messageId, sessionId, scope);
    yield { event: 'message_start', data: { id: messageId, request_id: requestId } };
    yield { event: 'message', data: { response_type: 'agent_query', assistant_message_id: messageId, session_id: sessionId, id: requestId, content: '', done: false } };
    let offset = Math.max(0, options.afterOffset ?? 0);
    while (!options.signal?.aborted) {
      this.session(ctx, sessionId); const jobId = this.jobId(sessionId, requestId); if (jobId) this.reconcile(ctx, sessionId, messageId, requestId, jobId);
      const events = this.streams.events(messageId, scope, offset);
      for (const event of events) {
        offset = event.offset + 1;
        const data = event.data;
        if (event.event_type === 'complete' || event.event_type === 'error') {
          const fresh = this.message(ctx, sessionId, messageId);
          yield { event: 'message', data: { ...this.projection(fresh), response_type: 'answer', assistant_message_id: messageId, id: requestId, content: fresh.content!, reasoning_content: [...array(fresh.agent_steps)].reverse().map(object).find(step => step.reasoning)?.reasoning ?? '', done: true, ...(event.event_type === 'error' ? { error: this.streams.read(messageId, scope)?.error_message ?? '生成失败。' } : {}) } };
          yield { event: 'message', data: { response_type: 'complete', assistant_message_id: messageId, id: requestId, done: true } }; yield { event: 'done', data: { message_id: messageId } }; return;
        }
        yield { event: 'message', data: { ...data, response_type: event.event_type === 'thinking' ? 'answer' : event.event_type, assistant_message_id: messageId, session_id: sessionId, id: requestId, done: false } };
      }
      const fresh = this.message(ctx, sessionId, messageId);
      if (fresh.is_completed) { yield { event: 'message', data: { ...this.projection(fresh), response_type: 'answer', assistant_message_id: messageId, id: requestId, done: true } }; yield { event: 'message', data: { response_type: 'complete', assistant_message_id: messageId, done: true } }; yield { event: 'done', data: { message_id: messageId } }; return; }
      try { await delay(30, undefined, { signal: options.signal }); } catch { return; }
    }
  }
  private async generate(job: JobContext, payload: JsonObject): Promise<Json> {
    const ctx = payload.context as unknown as AuthContext, sessionId = String(payload.session_id), messageId = String(payload.message_id), requestId = String(payload.request_id), input = object(payload.input), config = object(payload.config);
    const assert = () => { this.session(ctx, sessionId, true); if (job.signal.aborted) throw new ChatError(409, 'chat_cancelled', 'Chat cancelled'); const message = this.message(ctx, sessionId, messageId); if (message.is_completed) fail(409, 'chat_terminal', 'Chat is already terminal'); this.validateSelection(ctx, payload.knowledge_base_ids); };
    const publish = <T>(work: () => T): T => job.publish(() => { assert(); return work(); });
    const journal = (type: string, data: JsonObject) => { publish(() => this.journal.append(sessionId, requestId, type, publicParameters(data), this.scope(ctx))); currentObservation(ctx)?.journal(type, data); };
    const calls = new ModelCaller(this.db, this.dependencies.models, ctx, { session_id: sessionId, request_id: requestId, message_id: messageId, job_id: job.jobId, attempt: job.attempt }, assert, data => journal('llm/call', data));
    const session = this.session(ctx, sessionId), scope: SearchScope = { tenantId: ctx.tenantId, knowledgeBaseIds: ids(payload.knowledge_base_ids) };
    const execution: ChatExecution = { context: ctx, sessionId, messageId, requestId, query: String(input.query), input, config, history: this.history(ctx, session, String(payload.user_message_id), payload.agent === true), job, signal: job.signal, scope, calls, assert, publish,
      emit: (type, data) => { publish(() => { this.streams.append(messageId, type, publicParameters(data), this.scope(ctx)); if (type === 'thinking') this.db.update('messages', messageId, { content: data.content ?? '', rendered_content: data.content ?? '', agent_steps: [{ type: 'generation', thought: data.content ?? '', reasoning: data.reasoning_content ?? '' }], updated_at: now() }); }); }, journal,
      search: async (query, options = {}) => { assert(); journal('retrieval/search', { query, kb_ids: scope.knowledgeBaseIds ?? [], top_k: options.topK ?? 5 });
        const configured = this.dependencies.hooks?.retrievalOptions?.(ctx, scope) ?? {};
        const result = await retrieveChat(execution, this.index, query, { ...configured, ...options, signal: job.signal }, this.dependencies.hooks); assert();
        journal('retrieval/result', { count: result.results.length, refs: result.results as unknown as Json[], degradations: result.meta.degradations, intent: 'kb_search' }); return result; } };
    execution.fork = (options, work) => this.forkActor(execution, String(payload.user_message_id), options, work);
    const monitor = setInterval(() => { try { assert(); } catch { this.stopWorker(job); } }, 100); monitor.unref();
    const started = Date.now();
    try { return await this.observe(execution, async () => {
      let user = this.db.read('messages', String(payload.user_message_id))!;
      const images = array(user.images); const captions: Json[] = [];
      if (images.length && this.dependencies.hooks?.images) { const prepared = await this.dependencies.hooks.images(execution, images); assert(); captions.push(...prepared.images); if (prepared.warnings?.length) journal('maintenance/step', { stage: 'image_preparation', warnings: prepared.warnings }); }
      else for (const image of images) { const value = object(image); const caption = typeof value.caption === 'string' && value.caption.trim() ? value.caption.trim() : (await calls.vision('VLLM', String(value.url), `请识别用户上传的图片，为后续对话提供准确的文字上下文。逐字转写可读文字，描述主体、颜色、形状和相对位置；无法辨认时明确说明，不要猜测。用户问题：${execution.query}`, { signal: job.signal })).content.trim(); assert(); if (!caption) fail(502, 'image_caption_empty', 'Vision model returned an empty caption'); captions.push({ ...value, caption }); }
      if (captions.length) publish(() => { user = this.db.update('messages', String(user.id), { images: captions, updated_at: now() })!; });
      const attachments = array(user.attachments); let extra = '';
      if (attachments.length) {
        if (this.dependencies.hooks?.attachments) { const result = await this.dependencies.hooks.attachments(execution, attachments); assert(); extra = result.text; if (result.attachments) publish(() => { user = this.db.update('messages', String(user.id), { attachments: result.attachments!, updated_at: now() })!; }); if (result.warnings?.length) journal('maintenance/step', { stage: 'attachment_preparation', warnings: result.warnings }); }
        else {
          for (const value of attachments) { const a = object(value), name = String(a.file_name ?? a.name ?? 'attachment'); if (typeof a.data === 'string' && /\.(txt|md|csv|json|log)$/i.test(name)) { try { extra += `\n[${name}]\n${new TextDecoder('utf-8', { fatal: true }).decode(Buffer.from(a.data, 'base64'))}`; } catch { extra += `\n[${name}: 附件文字无法解码]`; } } else extra += `\n[${name}: 附件解析待配置]`; }
        }
      }
      execution.query = userContent(user) + extra;
      publish(() => this.db.update('messages', String(user.id), { rendered_content: execution.query, updated_at: now() }));
      execution.memoryEnabled = false;
      let memory = ''; if (config.enable_memory !== false && this.dependencies.hooks?.memory) { const result = await this.dependencies.hooks.memory(execution); assert(); memory = result.context; execution.memoryEnabled = result.enabled ?? true; if (result.warnings?.length) journal('maintenance/step', { stage: 'memory_retrieval', warnings: result.warnings }); }
      if (memory) execution.config = { ...config, memory_context: memory };
      let outcome: ChatOutcome;
      if (payload.agent === true && this.dependencies.hooks?.agent) outcome = await this.dependencies.hooks.agent(execution);
      else {
        if (payload.agent === true) fail(501, 'agent_unavailable', 'Agent execution is not configured');
        const retrieval = await execution.search(String(input.query), { topK: 5 }); const refs = retrieval.results as unknown as Json[];
        publish(() => this.db.update('messages', messageId, { knowledge_references: refs, updated_at: now() }));
        const context = retrieval.results.map((r, i) => `<context id="${i + 1}" title="${r.knowledge_title.replaceAll('"', '&quot;')}">\n${r.content}\n</context>`).join('\n\n');
        const messages: ChatMessage[] = [{ role: 'system', content: '你是知识库助手。根据提供的资料回答并标注文档来源；资料不足时明确说明，不编造。\n\n' + memorySystemPrompt(execution.memoryEnabled) }, ...execution.history, { role: 'user', content: [context, memory, execution.query].filter(Boolean).join('\n\n') }];
        let content = '', reasoning = '';
        await calls.invoke(String(config.model_id || 'KnowledgeQA'), 'chat', async (runtime, usage) => { for await (const delta of runtime.chat(messages, { signal: job.signal })) { if (delta.type === 'usage') usage(delta.usage); else if (delta.type === 'content' || delta.type === 'reasoning') { if (delta.type === 'content') content += delta.content; else reasoning += delta.content; execution.emit('thinking', { content, reasoning_content: reasoning }); } else if (delta.type === 'tool_calls') throw new ModelRuntimeError('model_response_invalid', 'Plain chat returned unexpected tool calls', undefined, true); } }, { operation: 'chat' });
        outcome = { content, refs, durationMs: Date.now() - started, steps: [{ type: 'generation', thought: content, reasoning }, { type: 'knowledge_search', query: input.query!, count: refs.length, degradations: retrieval.meta.degradations }] };
      }
      assert(); outcome.durationMs = Date.now() - started;
      let maintenanceId = '';
      publish(() => {
        this.streams.finish(messageId, { content: outcome.content, refs: outcome.refs, steps: outcome.steps, durationMs: outcome.durationMs }, this.scope(ctx));
        this.journal.append(sessionId, requestId, 'turn/completed', { content: outcome.content, duration_ms: outcome.durationMs, stopped_reason: outcome.stoppedReason ?? 'completed' }, this.scope(ctx));
        if (!ctx.channel && this.dependencies.hooks?.maintenance) {
          const sourceIds = [String(payload.user_message_id), messageId];
          const maintenance = this.jobs.create({ scope: this.scope(ctx), requestId: `${this.jobRequest(ctx, sessionId, requestId)}:maintenance`, kind: this.maintenanceKind, recoveryPolicy: 'manual', payload: { context: { ...ctx }, session_id: sessionId, message_id: messageId, request_id: requestId, input, config, query: execution.query, knowledge_base_ids: scope.knowledgeBaseIds ?? [], source_ids: sourceIds, source_fingerprints: sourceIds.map(id => JSON.stringify(this.db.read('messages', id))), outcome: outcome as unknown as JsonObject } });
          maintenanceId = maintenance.id; this.owned.set(maintenance.id, { context: { ...ctx }, sessionId, requestId });
        }
      });
      if (maintenanceId) this.scheduleMaintenance(maintenanceId);
      return { content: outcome.content, message_id: messageId };
    }, 'chat.turn'); } finally { clearInterval(monitor); }
  }
  private scheduleMaintenance(id: string): void {
    const work = (async () => { await this.jobs.run(id); await this.workers.get(id)?.catch(() => {}); })();
    this.background.add(work); void work.finally(() => this.background.delete(work)).catch(() => {});
  }
  private actorRow(ctx: AuthContext, sessionId: string, id: string, write = false): Row {
    this.session(ctx, sessionId, write);
    const found = this.db.get('select a.id from agent_actors a join messages m on m.id=a.parent_message_id and m.session_id=a.session_id where a.session_id=? and (a.id=? or a.actor_id=?) and a.deleted_at is null and m.deleted_at is null', sessionId, id, id);
    if (!found) fail(404, 'actor_not_found', 'Actor not found');
    return this.db.read('agent_actors', String(found!.id))!;
  }
  actors(ctx: AuthContext, sessionId: string): JsonObject {
    this.session(ctx, sessionId); return { items: this.db.all('select a.id from agent_actors a join messages m on m.id=a.parent_message_id and m.session_id=a.session_id where a.session_id=? and a.deleted_at is null and m.deleted_at is null order by a.created_at,a.id', sessionId).map(r => publicParameters(this.db.read('agent_actors', String(r.id))!)) };
  }
  actor(ctx: AuthContext, sessionId: string, id: string): JsonObject { return publicParameters(this.actorRow(ctx, sessionId, id)); }
  async cancelActor(ctx: AuthContext, sessionId: string, id: string): Promise<JsonObject> {
    const row = this.actorRow(ctx, sessionId, id, true), jobId = String(object(row.metadata).job_id ?? '');
    if (jobId) {
      const job = this.jobs.get(jobId, this.scope(ctx));
      if (job.kind !== this.actorKind || job.payload.session_id !== sessionId || job.payload.actor_row_id !== row.id) fail(404, 'actor_not_found', 'Actor not found');
      this.jobs.cancelByRequest(job.requestId, this.scope(ctx));
      await this.actorRuns.get(jobId)?.catch(() => {}); await this.workers.get(jobId)?.catch(() => {}); this.projectActor(jobId);
    } else if (['running', 'pending'].includes(String(row.status))) {
      this.db.transaction(() => { const fresh = this.actorRow(ctx, sessionId, id, true); if (!object(fresh.metadata).job_id) this.db.update('agent_actors', String(fresh.id), { status: 'cancelled', last_outcome: 'cancelled', completed_at: now(), updated_at: now() }); });
    }
    return this.actor(ctx, sessionId, id);
  }
  private forkActor(parent: ChatExecution, userMessageId: string, options: ChatForkInput, work: (execution: ChatExecution) => Promise<Json>): ChatForkHandle {
    if (this.closing) fail(503, 'chat_closed', 'Chat service is closing');
    const sourceIds = [...new Set([userMessageId, ...(options.sourceMessageIds ?? [])])];
    const actor = parent.publish(() => this.actorRow(parent.context, parent.sessionId, options.actorRowId, true));
    if (actor.actor_id !== options.actorId || actor.parent_message_id !== parent.messageId || object(actor.metadata).job_id) fail(409, 'actor_binding_conflict', 'Actor already belongs to another execution');
    const job = parent.publish(() => {
      const fingerprints = sourceIds.map(id => { const row = this.db.read('messages', id); if (!row || row.deleted_at !== null || row.session_id !== parent.sessionId || row.role !== 'user') fail(409, 'actor_source_invalid', 'Actor source is unavailable'); return JSON.stringify(row); });
      const job = this.jobs.create({ scope: this.scope(parent.context), requestId: `${this.jobRequest(parent.context, parent.sessionId, parent.requestId)}:actor:${actor.id}`, kind: this.actorKind, recoveryPolicy: 'manual', payload: { context: { ...parent.context }, session_id: parent.sessionId, message_id: parent.messageId, request_id: parent.requestId, parent_job_id: parent.job.jobId, actor_row_id: String(actor.id), actor_id: options.actorId, input: parent.input, config: options.config ?? parent.config, query: options.query, knowledge_base_ids: parent.scope.knowledgeBaseIds ?? [], source_ids: sourceIds, source_fingerprints: fingerprints } });
      this.db.update('agent_actors', String(actor.id), { metadata: { ...object(actor.metadata), job_id: job.id }, updated_at: now() }); return job;
    });
    this.owned.set(job.id, { context: { ...parent.context }, sessionId: parent.sessionId, requestId: parent.requestId }); this.actorCallbacks.set(job.id, work);
    const settled = (async (): Promise<Json> => {
      try {
        const terminal = await this.jobs.run(job.id, { timeoutMs: options.timeoutMs ?? 120000 }); await this.workers.get(job.id)?.catch(() => {}); this.projectActor(job.id);
        if (terminal.status !== 'completed') fail(409, terminal.status === 'interrupted' ? 'actor_result_unknown' : 'actor_stopped', terminal.status === 'interrupted' ? 'Actor result is unknown; explicit new request required' : 'Actor stopped');
        return terminal.result;
      } finally { this.actorCallbacks.delete(job.id); }
    })();
    this.actorRuns.set(job.id, settled); void settled.finally(() => { if (this.actorRuns.get(job.id) === settled) this.actorRuns.delete(job.id); }).catch(() => {});
    return { jobId: job.id, settled, cancel: async () => { this.cancelOwned(job.id); await settled.catch(() => {}); await this.workers.get(job.id)?.catch(() => {}); this.projectActor(job.id); } };
  }
  private async runActor(job: JobContext, payload: JsonObject): Promise<Json> {
    const callback = this.actorCallbacks.get(job.jobId);
    if (!callback) throw new ModelRuntimeError('model_response_invalid', 'Actor callback was lost; explicit new request required', undefined, true);
    const ctx = payload.context as unknown as AuthContext, sessionId = String(payload.session_id), messageId = String(payload.message_id), requestId = String(payload.request_id), sourceIds = ids(payload.source_ids), fingerprints = array(payload.source_fingerprints);
    const check = () => {
      job.signal.throwIfAborted(); this.session(ctx, sessionId, true); this.validateSelection(ctx, payload.knowledge_base_ids);
      const parent = this.message(ctx, sessionId, messageId), actor = this.actorRow(ctx, sessionId, String(payload.actor_row_id), true);
      if (parent.role !== 'assistant' || parent.request_id !== requestId || actor.parent_message_id !== messageId || actor.actor_id !== payload.actor_id || object(actor.metadata).job_id !== job.jobId || actor.status !== 'running') fail(409, 'actor_source_changed', 'Actor source changed');
      const parentJob = this.jobs.get(String(payload.parent_job_id), this.scope(ctx));
      if (['cancelled', 'interrupted', 'failed'].includes(parentJob.status) || sourceIds.some((id, i) => { const row = this.db.read('messages', id); return !row || row.session_id !== sessionId || row.deleted_at !== null || JSON.stringify(row) !== fingerprints[i]; })) fail(409, 'actor_source_changed', 'Actor source changed');
    };
    // A claim check also runs before provider work, not just when its result is published.
    const assert = () => job.publish(check), publish = <T>(work: () => T): T => job.publish(() => { check(); return work(); });
    const journal = (type: string, data: JsonObject) => { publish(() => this.journal.append(sessionId, requestId, type, publicParameters({ ...data, actor_id: payload.actor_id! }), this.scope(ctx))); currentObservation(ctx)?.journal(type, data); };
    const scope: SearchScope = { tenantId: ctx.tenantId, knowledgeBaseIds: ids(payload.knowledge_base_ids) };
    const calls = new ModelCaller(this.db, this.dependencies.models, ctx, { session_id: sessionId, request_id: requestId, message_id: messageId, actor_id: payload.actor_id!, job_id: job.jobId, attempt: job.attempt }, assert, data => journal('llm/call', data));
    const execution: ChatExecution = { context: ctx, sessionId, messageId, requestId, query: String(payload.query), input: object(payload.input), config: object(payload.config), history: [], scope, job, signal: job.signal, calls, assert, publish, journal,
      emit: (type, data) => publish(() => { const safe = publicParameters({ ...data, actor_id: payload.actor_id!, parent_message_id: messageId }); this.streams.append(messageId, type, safe, this.scope(ctx)); if (type === 'actor_update') this.journal.append(sessionId, requestId, 'agent/thinking', safe, this.scope(ctx)); }),
      search: async (query, options = {}) => { assert(); const result = await retrieveChat(execution, this.index, query, { ...(this.dependencies.hooks?.retrievalOptions?.(ctx, scope) ?? {}), ...options, signal: job.signal }, this.dependencies.hooks); assert(); return result; } };
    const monitor = setInterval(() => { try { assert(); } catch { this.stopWorker(job); } }, 100); monitor.unref();
    try { assert(); return await this.observe(execution, () => callback(execution), 'agent.run'); } finally { clearInterval(monitor); }
  }
  /** Terminal cleanup may mark an owned actor stopped; it never publishes a stale worker's output. */
  private projectActor(jobId: string): boolean {
    return this.db.transaction(() => {
      const raw = this.db.get('select tenant_id,user_id from desktop_jobs where id=?', jobId); if (!raw) return false;
      const job = this.jobs.get(jobId, { tenantId: String(raw.tenant_id), userId: String(raw.user_id) }); if (job.kind !== this.actorKind || ['running', 'queued', 'completed'].includes(job.status)) return false;
      const p = job.payload, row = this.db.read('agent_actors', String(p.actor_row_id)), session = this.db.read('sessions', String(p.session_id)), parent = this.db.read('messages', String(p.message_id));
      if (!row || !session || !parent || String(session.tenant_id) !== job.scope.tenantId || session.user_id !== job.scope.userId || parent.session_id !== session.id || parent.request_id !== p.request_id || row.session_id !== session.id || row.parent_message_id !== parent.id || object(row.metadata).job_id !== jobId || !['running', 'pending'].includes(String(row.status))) return false;
      const interrupted = job.status === 'interrupted', cancelled = job.status === 'cancelled', error = interrupted ? 'Upstream result unknown; explicit new request required' : cancelled ? 'cancelled' : 'Subagent execution failed';
      this.db.update('agent_actors', String(row.id), { status: interrupted ? 'interrupted' : cancelled ? 'cancelled' : 'idle', last_outcome: interrupted ? 'interrupted' : cancelled ? 'cancelled' : 'failure', error, completed_at: now(), updated_at: now() });
      if (session.deleted_at === null && parent.deleted_at === null && row.deleted_at === null) this.journal.append(String(session.id), String(p.request_id), 'agent/actor', { actor_id: row.actor_id!, agent_type: row.agent_type!, event: interrupted ? 'interrupted' : cancelled ? 'cancelled' : 'failed', status: interrupted ? 'interrupted' : cancelled ? 'cancelled' : 'idle', error, result_unknown: interrupted }, job.scope);
      return true;
    });
  }
  /** Call after JobQueue.recover() on startup. Lost callbacks never replay paid operations. */
  recoverActors(): { interrupted: number; projected: number } {
    this.available(); let interrupted = 0, projected = 0;
    for (const raw of this.db.all('select id,tenant_id,user_id from desktop_jobs where kind=?', this.actorKind)) {
      const id = String(raw.id); if (this.actorRuns.has(id) || this.actorCallbacks.has(id)) continue;
      this.db.transaction(() => {
        const changed = this.db.run("update desktop_jobs set status='interrupted',error=?,finished_at=?,updated_at=? where id=? and kind=? and status='queued'", 'Actor callback was lost; explicit new request required', now(), now(), id, this.actorKind);
        if (Number(changed.changes)) { interrupted++; this.db.run('insert into desktop_job_events(job_id,seq,type,data,created_at) select ?,coalesce(max(seq),0)+1,?,?,? from desktop_job_events where job_id=?', id, 'interrupted', JSON.stringify({ callback_lost: true, automatic_replay: false }), now(), id); }
      });
      if (this.projectActor(id)) projected++;
    }
    return { interrupted, projected };
  }
  private async maintain(job: JobContext, payload: JsonObject): Promise<Json> {
    const ctx = payload.context as unknown as AuthContext, sessionId = String(payload.session_id), messageId = String(payload.message_id), requestId = String(payload.request_id), sourceIds = ids(payload.source_ids), fingerprints = array(payload.source_fingerprints);
    const assert = () => { this.session(ctx, sessionId, true); if (job.signal.aborted) fail(409, 'chat_cancelled', 'Maintenance cancelled'); this.validateSelection(ctx, payload.knowledge_base_ids); if (!this.message(ctx, sessionId, messageId).is_completed || sourceIds.some((id, i) => JSON.stringify(this.db.read('messages', id)) !== fingerprints[i])) fail(409, 'maintenance_source_changed', 'Maintenance source changed'); };
    const publish = <T>(work: () => T): T => job.publish(() => { assert(); return work(); });
    const journal = (type: string, data: JsonObject) => { publish(() => this.journal.append(sessionId, requestId, type, publicParameters(data), this.scope(ctx))); currentObservation(ctx)?.journal(type, data); };
    const calls = new ModelCaller(this.db, this.dependencies.models, ctx, { session_id: sessionId, request_id: requestId, message_id: messageId, job_id: job.jobId, attempt: job.attempt }, assert, data => journal('llm/call', data));
    const scope: SearchScope = { tenantId: ctx.tenantId, knowledgeBaseIds: ids(payload.knowledge_base_ids) };
    const execution: ChatExecution = { context: ctx, sessionId, messageId, requestId, query: String(payload.query), input: object(payload.input), config: object(payload.config), history: sourceIds.map(id => this.db.read('messages', id)!).map(row => ({ role: row.role as 'user' | 'assistant', content: String(row.rendered_content || row.content) })), job, signal: job.signal, scope, calls, assert, publish, emit: (type, data) => journal('maintenance/step', { stage: type, ...data }), journal,
      search: async (query, options = {}) => { assert(); const result = await retrieveChat(execution, this.index, query, { ...(this.dependencies.hooks?.retrievalOptions?.(ctx, scope) ?? {}), ...options, signal: job.signal }, this.dependencies.hooks); assert(); return result; } };
    const monitor = setInterval(() => { try { assert(); } catch { this.stopWorker(job); } }, 100); monitor.unref();
    try { return await this.observe(execution, async () => { assert(); await this.dependencies.hooks?.maintenance?.(execution, payload.outcome as unknown as ChatOutcome); assert(); journal('maintenance/step', { stage: 'post_turn', status: 'completed' }); return { message_id: messageId, maintained: true }; }, 'chat.maintenance'); }
    catch (error) { try { journal('maintenance/failed', { stage: 'post_turn', result_unknown: error instanceof ModelRuntimeError && error.resultUnknown }); } catch {} throw error; }
    finally { clearInterval(monitor); }
  }
  async cancelSession(ctx: AuthContext, id: string): Promise<void> {
    this.session(ctx, id, true);
    for (const row of this.db.all("select request_id from messages where session_id=? and role='assistant' and is_completed=0 and deleted_at is null", id)) this.stop(ctx, id, String(row.request_id));
    const targets = [...this.owned].filter(([, owner]) => owner.sessionId === id).map(([jobId]) => jobId);
    for (const jobId of targets) this.cancelOwned(jobId);
    await Promise.all(targets.map(async jobId => { await this.runs.get(jobId)?.catch(() => {}); await this.actorRuns.get(jobId)?.catch(() => {}); await this.workers.get(jobId)?.catch(() => {}); this.projectActor(jobId); }));
  }
  async clearMessages(ctx: AuthContext, id: string): Promise<JsonObject> {
    this.session(ctx, id, true); this.editing.add(id);
    try { await this.cancelSession(ctx, id); const memory = await this.dependencies.hooks?.deleteMemory?.(ctx, id); this.db.transaction(() => { this.session(ctx, id, true); this.db.run('delete from stream_events where session_id=?', id); this.db.run('delete from stream_states where session_id=?', id); this.db.run('delete from context_snapshots where session_id=?', id); this.db.run('delete from agent_actors where session_id=?', id); this.db.run('delete from session_events where session_id=?', id); this.db.run('delete from messages where session_id=?', id); this.db.update('sessions', id, { event_seq: 0, updated_at: now() }); }); const uploads = await this.dependencies.hooks?.cleanupUploads?.(ctx, id), warnings = [...array(memory?.warnings), ...array(uploads?.warnings)]; return warnings.length ? { warnings } : {}; }
    finally { this.editing.delete(id); }
  }
  async delete(ctx: AuthContext, id: string): Promise<JsonObject> { this.session(ctx, id, true); if (this.editing.has(id)) fail(409, 'session_changing', 'Session history is changing'); this.editing.add(id); try { await this.cancelSession(ctx, id); const memory = await this.dependencies.hooks?.deleteMemory?.(ctx, id); this.session(ctx, id, true); this.db.update('sessions', id, { deleted_at: now(), updated_at: now() }); const uploads = await this.dependencies.hooks?.cleanupUploads?.(ctx, id), warnings = [...array(memory?.warnings), ...array(uploads?.warnings)]; return warnings.length ? { warnings } : {}; } finally { this.editing.delete(id); } }
  async batchDelete(ctx: AuthContext, input: JsonObject): Promise<JsonObject> { this.auth.assertCan(ctx, 'write', ctx.tenantId, ctx.userId); const selected = input.delete_all === true ? this.db.all('select id from sessions where tenant_id=? and user_id=? and deleted_at is null and coalesce(json_extract(agent_config,\'$.embed_channel_id\'),\'\')=\'\' order by id', ctx.tenantId, ctx.userId).map(row => String(row.id)) : ids(input.ids); for (const id of selected) this.session(ctx, id, true); const warnings: Json[] = []; for (const id of selected) warnings.push(...array((await this.delete(ctx, id)).warnings)); return { deleted_count: selected.length, ...(warnings.length ? { warnings } : {}) }; }
  async deleteMessage(ctx: AuthContext, sessionId: string, id: string): Promise<JsonObject> {
    const message = this.message(ctx, sessionId, id); this.session(ctx, sessionId, true); this.editing.add(sessionId);
    try {
      this.stop(ctx, sessionId, String(message.request_id));
      const targets = [...this.owned].filter(([, owner]) => owner.sessionId === sessionId && owner.requestId === message.request_id).map(([jobId]) => jobId);
      await Promise.all(targets.map(async jobId => { await this.runs.get(jobId)?.catch(() => {}); await this.actorRuns.get(jobId)?.catch(() => {}); await this.workers.get(jobId)?.catch(() => {}); }));
      this.db.transaction(() => { this.session(ctx, sessionId, true); this.streams.remove(String(message.id), this.scope(ctx)); this.db.run('delete from agent_actors where session_id=? and parent_message_id=?', sessionId, String(message.id)); this.db.run('delete from messages where id=? and session_id=?', String(message.id), sessionId); this.db.run('delete from context_snapshots where session_id=?', sessionId); }); const uploads = await this.dependencies.hooks?.cleanupUploads?.(ctx, sessionId); return uploads?.warnings ? { warnings: uploads.warnings } : {};
    } finally { this.editing.delete(sessionId); }
  }
  branch(ctx: AuthContext, id: string, input: JsonObject = {}): JsonObject {
    return this.db.transaction(() => { const source = this.session(ctx, id, true), boundary = input.message_id ? this.message(ctx, id, String(input.message_id)) : undefined;
      const selected = this.db.all('select id from messages where session_id=? and visible_to_user=1 and is_completed=1 and deleted_at is null order by created_at,rowid', id).map(r => this.db.read('messages', String(r.id))!);
      const position = boundary ? selected.findIndex(r => r.id === boundary.id) : selected.length - 1; if (boundary && position < 0) fail(409, 'incomplete_branch', 'Only completed history can be branched');
      const clone = this.create(ctx, { title: input.title ?? `${source.title} 分支`, description: source.description!, agent_config: { ...object(source.agent_config), branched_from_session_id: id, branched_at_message_id: boundary?.id ?? '' } });
      const mapping = new Map<string, string>();
      for (const row of selected.slice(0, position + 1)) { const next = this.db.insert('messages', { ...row, id: randomUUID(), session_id: clone.id, images: array(row.images).map(v => { const img = object(v); return img.upload_id ? { ...img, url: `/api/v1/sessions/${String(clone.id)}/uploads/${String(img.upload_id)}` } : v; }) }); mapping.set(String(row.id), String(next.id)); }
      for (const r of this.db.all('select id from agent_actors where session_id=? and deleted_at is null', id)) { const actor = this.db.read('agent_actors', String(r.id))!; const parent = mapping.get(String(actor.parent_message_id)); if (parent) { const metadata: JsonObject = { ...object(actor.metadata), snapshot_from_actor_id: actor.id! }; delete metadata.job_id; const running = ['running', 'pending'].includes(String(actor.status)); this.db.insert('agent_actors', { ...actor, id: randomUUID(), session_id: clone.id, parent_message_id: parent, metadata, ...(running ? { status: 'interrupted', last_outcome: 'interrupted', error: 'Branched actor is a snapshot; its source job continues in the original session', completed_at: now() } : {}) }); } }
      this.dependencies.hooks?.branchUploads?.(ctx, id, String(clone.id)); return clone;
    });
  }
  async close(): Promise<void> {
    if (this.closing) return this.closing;
    this.closing = (async () => {
      for (const [jobId] of this.owned) { try { this.cancelOwned(jobId); } catch {} }
      await Promise.all([...this.runs.values()].map(p => p.catch(() => {}))); await Promise.all([...this.actorRuns.values()].map(p => p.catch(() => {}))); await Promise.all([...this.background].map(p => p.catch(() => {}))); await Promise.all([...this.workers.values()].map(p => p.catch(() => {}))); this.closed = true;
    })(); return this.closing;
  }
}
