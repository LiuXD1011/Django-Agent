import { createHash, randomBytes } from 'node:crypto';
import type { AuthContext, Json, JsonObject } from '../contracts.js';
import type { AuthService } from '../auth/index.js';
import { ChannelGrantAuthority, type ChannelGrant } from '../auth/channel-principal.js';
import type { CoreDatabase, Row } from '../storage/database.js';
import { CredentialVault, isSecretKey, publicParameters } from '../storage/credentials.js';
import type { ChatService } from '../chat/index.js';
import { array, bounded, ids, now, object, text } from '../chat/internal.js';
import { AppError } from '../errors.js';
export type ChannelKind = 'embed_channels' | 'im_channels';
const fail = (status: number, code: string, message: string): never => { throw new AppError(status, code, message); };
const publicDefaultTools = ['actor', 'thinking', 'knowledge_search', 'list_knowledge_docs', 'get_document_info', 'grep_chunks', 'wiki_search', 'wiki_read_page'];
const publicTools = new Set(['actor', 'thinking', 'knowledge_search', 'list_knowledge_docs', 'get_document_info', 'grep_chunks', 'wiki_search', 'wiki_read_page', 'wiki_list_pages', 'wiki_read_source_doc', 'query_knowledge_graph']);
function hasSecrets(value: Json): boolean {
  return !!value && typeof value === 'object' && (Array.isArray(value) ? value.some(hasSecrets) : Object.entries(value).some(([name, item]) => isSecretKey(name) || hasSecrets(item)));
}
function mergeSecrets(previous: Json, input: Json): Json {
  if (Array.isArray(input)) return input.map(item => mergeSecrets(null, item));
  if (!input || typeof input !== 'object') return input;
  const old = object(previous); const next: JsonObject = { ...old };
  for (const [key, value] of Object.entries(input)) {
    if (isSecretKey(key)) {
      if (value === null || value === '' || value === '******') continue;
      if (typeof value !== 'string' || value.startsWith('enc:v1:')) fail(400, 'invalid_channel_credential', '请提供原始凭据，不能上传加密存储值。');
    }
    next[key] = mergeSecrets(old[key] ?? null, value);
  }
  return next;
}
/** Tenant-scoped channel configuration and fixed public-chat delegation. No IM callbacks are fabricated. */
export class ChannelService {
  private readonly authority: ChannelGrantAuthority;
  private closed = false; private readonly active = new Set<Promise<JsonObject>>();
  constructor(readonly db: CoreDatabase, readonly auth: AuthService, readonly vault: CredentialVault, readonly chat: ChatService, options: { now?: () => number } = {}) {
    this.authority = new ChannelGrantAuthority(db, auth, grant => this.current(grant), options.now);
  }
  private available(): void { if (this.closed) fail(503, 'channel_closed', '渠道服务已关闭。'); }
  private data(row: Row): JsonObject { return object(this.vault.decrypt(row.data!)); }
  private row(ctx: AuthContext, kind: ChannelKind, id: string, write = false): Row {
    this.available(); this.auth.assertCan(ctx, write ? 'agent.write' : 'read'); if (ctx.channel) fail(403, 'channel_action_forbidden', '访客不能管理渠道。');
    const row = this.db.read('generic_resources', id); if (!row || row.deleted_at !== null || row.resource_type !== kind || String(row.tenant_id) !== ctx.tenantId) return fail(404, 'channel_not_found', '渠道不存在。');
    return row;
  }
  private enabled(row: Row): boolean { return row.status === 'active' && this.data(row).enabled !== false; }
  private version(row: Row): string {
    const agent = this.data(row).agent_id ? this.db.read('generic_resources', String(this.data(row).agent_id)) : null;
    return createHash('sha256').update(JSON.stringify([row.id, row.status, row.updated_at, row.data, agent?.data ?? null, agent?.deleted_at ?? null])).digest('hex');
  }
  private selections(row: Row): string[] {
    const data = this.data(row), selected = ids(data.knowledge_base_ids ?? data.knowledge_bases ?? []);
    return selected.length ? selected : this.db.all('SELECT id FROM knowledge_bases WHERE tenant_id=? AND deleted_at IS NULL AND is_temporary=0 ORDER BY id', String(row.tenant_id)).map(kb => String(kb.id));
  }
  private validKb(tenantId: string, id: string): boolean { const kb = this.db.read('knowledge_bases', id); return !!kb && kb.deleted_at === null && String(kb.tenant_id) === tenantId && kb.is_temporary !== true && kb.is_temporary !== 1; }
  private current(grant: ChannelGrant): boolean {
    if (this.closed) return false; const row = this.db.read('generic_resources', grant.channel.id);
    if (!row || row.deleted_at !== null || row.resource_type !== 'embed_channels' || String(row.tenant_id) !== grant.tenantId || !this.enabled(row) || this.data(row).owner_user_id !== grant.userId || this.version(row) !== grant.channel.version) return false;
    const selected = this.selections(row);
    return grant.channel.knowledgeBaseIds.every(id => selected.includes(id) && this.validKb(grant.tenantId, id));
  }
  private dto(row: Row): JsonObject {
    const data = this.data(row), safe = publicParameters(data); delete safe.owner_user_id;
    return { ...safe, id: String(row.id), tenant_id: row.tenant_id!, name: row.name!, status: row.status!, token_configured: !!data.token, owner_bound: typeof data.owner_user_id === 'string', created_at: row.created_at!, updated_at: row.updated_at! };
  }
  private validate(ctx: AuthContext, data: JsonObject): void {
    if (data.name !== undefined) text(data.name, 255);
    if (data.enabled !== undefined && typeof data.enabled !== 'boolean') fail(400, 'invalid_channel', '启用状态必须为布尔值。');
    if (data.allowed_origins !== undefined) {
      if (!Array.isArray(data.allowed_origins) || data.allowed_origins.length > 100 || data.allowed_origins.some(value => typeof value !== 'string' || value !== '*' && !this.isOrigin(value))) fail(400, 'invalid_channel_origin', '来源必须为完整 HTTP(S) origin 或 *。');
    }
    for (const id of ids(data.knowledge_base_ids ?? data.knowledge_bases ?? [])) if (!this.validKb(ctx.tenantId, id)) fail(404, 'knowledge_base_not_found', '知识库不存在。');
    if (data.agent_id) { const agent = this.db.read('generic_resources', String(data.agent_id)); if (!agent || agent.deleted_at !== null || agent.resource_type !== 'agents' || String(agent.tenant_id) !== ctx.tenantId) fail(404, 'agent_not_found', 'Agent 不存在。'); }
    if (data.model_id && this.chat.dependencies.models.configuration(ctx, String(data.model_id)).type !== 'KnowledgeQA') fail(404, 'model_not_found', '对话模型不存在。');
  }
  private isOrigin(value: string): boolean { try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) && url.origin === value && !url.username && !url.password; } catch { return false; } }
  private audit(ctx: AuthContext, row: Row, action: string): void { this.db.insert('audit_logs', { tenant_id: ctx.tenantId, actor_user_id: ctx.userId, actor_role: ctx.role, action, target_type: String(row.resource_type), target_id: String(row.id), outcome: 'success', details: { resource_id: String(row.id) } }); }
  list(ctx: AuthContext, kind: ChannelKind, query: JsonObject = {}, agentId?: string): JsonObject {
    this.available(); this.auth.assertCan(ctx, 'read'); if (ctx.channel) fail(403, 'channel_action_forbidden', '访客不能管理渠道。');
    if (agentId) this.validate(ctx, { agent_id: agentId });
    const q = String(query.keyword ?? query.q ?? query.query ?? '').toLocaleLowerCase();
    const rows = this.db.all('SELECT id FROM generic_resources WHERE tenant_id=? AND resource_type=? AND deleted_at IS NULL ORDER BY updated_at DESC,id', ctx.tenantId, kind).map(r => this.db.read('generic_resources', String(r.id))!).filter(r => (!agentId || this.data(r).agent_id === agentId) && (!q || `${r.name} ${this.data(r).description ?? ''}`.toLocaleLowerCase().includes(q)));
    const size = bounded(query.page_size ?? query.limit, 20), page = bounded(query.page, 1, 100000), offset = query.offset !== undefined && query.page === undefined ? Math.max(0, Number(query.offset) || 0) : (page - 1) * size, items = rows.slice(offset, offset + size).map(r => this.dto(r));
    return { items, data: items, total: rows.length, page: Math.floor(offset / size) + 1, page_size: size };
  }
  get(ctx: AuthContext, kind: ChannelKind, id: string): JsonObject { return this.dto(this.row(ctx, kind, id)); }
  create(ctx: AuthContext, kind: ChannelKind, input: JsonObject): JsonObject {
    this.available(); this.auth.assertCan(ctx, 'agent.write'); if (!ctx.userId || ctx.channel) fail(403, 'user_principal_required', '配置渠道需要真实用户。');
    const data = object(mergeSecrets({ name: kind === 'embed_channels' ? '网页嵌入' : 'IM 渠道', enabled: kind === 'embed_channels', ...(kind === 'embed_channels' ? { token: randomBytes(24).toString('base64url'), allowed_origins: ['*'] } : { provider: 'wechat' }) }, input));
    data.owner_user_id = ctx.userId; this.validate(ctx, data); if (hasSecrets(input)) this.auth.assertCan(ctx, 'credentials.manage');
    return this.db.transaction(() => { this.auth.assertCan(ctx, 'agent.write'); const row = this.db.insert('generic_resources', { tenant_id: ctx.tenantId, resource_type: kind, name: String(data.name), status: String(data.status ?? (data.enabled ? 'active' : 'disabled')), data: this.vault.encrypt(data) }); this.audit(ctx, row, 'channel.created'); return this.dto(row); });
  }
  update(ctx: AuthContext, kind: ChannelKind, id: string, input: JsonObject): JsonObject {
    return this.db.transaction(() => { const row = this.row(ctx, kind, id, true), previous = this.data(row); if (!previous.owner_user_id) this.auth.assertCan(ctx, 'tenant.admin');
      if (hasSecrets(input)) this.auth.assertCan(ctx, 'credentials.manage');
      const data = object(mergeSecrets(previous, input)); data.owner_user_id = previous.owner_user_id ?? ctx.userId; this.validate(ctx, data);
      const next = this.db.update('generic_resources', id, { name: data.name ?? row.name, status: input.status ?? (input.enabled !== undefined ? data.enabled ? 'active' : 'disabled' : row.status), data: this.vault.encrypt(data), updated_at: now() })!; this.audit(ctx, next, 'channel.updated'); return this.dto(next);
    });
  }
  delete(ctx: AuthContext, kind: ChannelKind, id: string): JsonObject { return this.db.transaction(() => { const row = this.row(ctx, kind, id, true); this.db.update('generic_resources', id, { deleted_at: now(), updated_at: now() }); this.audit(ctx, row, 'channel.deleted'); return {}; }); }
  rotate(ctx: AuthContext, id: string, reveal: boolean): JsonObject {
    return this.db.transaction(() => { const row = this.row(ctx, 'embed_channels', id, true); this.auth.assertCan(ctx, 'credentials.manage'); const token = randomBytes(24).toString('base64url'); const updated = this.db.update('generic_resources', id, { data: this.vault.encrypt({ ...this.data(row), token }), updated_at: now() })!; this.audit(ctx, row, 'channel.token_rotated'); return { id, rotated: true, token_configured: true, config: this.dto(updated), ...(reveal ? { token } : {}) }; });
  }
  toggle(ctx: AuthContext, kind: ChannelKind, id: string): JsonObject { const row = this.row(ctx, kind, id, true); return this.update(ctx, kind, id, { enabled: !this.enabled(row) }); }
  preview(ctx: AuthContext, id: string): JsonObject { const row = this.row(ctx, 'embed_channels', id, true), data = this.data(row); return { session: this.chat.create(ctx, { title: 'Agent 预览会话', agent_config: { agent_enabled: true, agent_id: data.agent_id ?? '', knowledge_base_ids: this.selections(row), preview_embed_channel_id: id } }) }; }
  stats(ctx: AuthContext, id: string): JsonObject {
    this.row(ctx, 'embed_channels', id); const rows = this.db.all('SELECT id FROM sessions WHERE tenant_id=? AND deleted_at IS NULL', ctx.tenantId).filter(r => object(this.db.read('sessions', String(r.id))?.agent_config).embed_channel_id === id);
    let messages = 0, last: Json = null; for (const row of rows) { const session = this.db.read('sessions', String(row.id))!; messages += Number(this.db.get('SELECT count(*) AS n FROM messages WHERE session_id=? AND deleted_at IS NULL AND visible_to_user=1', String(row.id))?.n ?? 0); if (last === null || String(session.updated_at) > String(last)) last = session.updated_at!; }
    return { sessions: rows.length, messages, last_active_at: last };
  }
  exchange(id: string, origin: string): JsonObject {
    this.available(); const row = this.db.read('generic_resources', id);
    if (!row || row.deleted_at !== null || row.resource_type !== 'embed_channels' || !this.enabled(row)) return fail(404, 'channel_not_found', '公开渠道未启用。');
    const data = this.data(row), allowed = array(data.allowed_origins); if (!allowed.includes('*') && !allowed.includes(origin)) fail(403, 'channel_origin_forbidden', '来源不在渠道允许列表中。');
    if (typeof data.owner_user_id !== 'string' || !data.owner_user_id) fail(409, 'channel_needs_owner_binding', '遗留渠道需要管理员授权绑定创建者后才能公开访问。');
    const selected = this.selections(row); if (selected.some(kb => !this.validKb(String(row.tenant_id), kb))) fail(409, 'channel_scope_unavailable', '渠道知识库已变更，请更新配置。');
    return { ...this.authority.issueOwned(data.owner_user_id as string, String(row.tenant_id), id, this.version(row), origin, selected), channel_id: id, session: {} };
  }
  authenticate(id: string, token: string, origin: string): AuthContext { this.available(); return this.authority.authenticate(token, id, origin); }
  config(ctx: AuthContext): JsonObject { this.auth.assertCan(ctx, 'read'); const row = this.db.read('generic_resources', ctx.channel!.id)!, data = this.data(row); return { id: String(row.id), name: row.name!, status: row.status!, enabled: true, allowed_origins: data.allowed_origins ?? [], agent_id: data.agent_id ?? '', knowledge_base_ids: ctx.channel!.knowledgeBaseIds }; }
  questions(ctx: AuthContext): JsonObject { this.auth.assertCan(ctx, 'read'); const data = this.data(this.db.read('generic_resources', ctx.channel!.id)!); const items = array(data.suggested_questions).filter(q => typeof q === 'string').map(question => ({ question })); return { state: items.length ? 'configured' : 'not_configured', items }; }
  private sessionProjection(session: JsonObject): JsonObject { const safe = { ...session }; delete safe.user_id; delete safe.tenant_id; for (const key of ['agent_config', 'last_request_state']) { const config = { ...object(safe[key]) }; delete config.channel_guest_id; delete config.channel_grant_id; safe[key] = config; } return safe; }
  private agentConfig(ctx: AuthContext): JsonObject {
    const data = this.data(this.db.read('generic_resources', ctx.channel!.id)!); const agent = data.agent_id ? this.db.read('generic_resources', String(data.agent_id)) : undefined;
    const config = agent ? object(this.vault.decrypt(agent.data!)) : {};
    if (agent) { if (array(config.allowed_tools).some(tool => !publicTools.has(String(tool))) || array(config.mcp_services).length || config.web_search_enabled === true) fail(409, 'channel_agent_not_public', '所选 Agent 含访客不适用的外部或管理工具，请配置受限公开 Agent。'); }
    return { allowed_tools: config.allowed_tools ?? [...publicDefaultTools], agent_id: data.agent_id ?? '', model_id: data.model_id ?? '', agent_enabled: true, knowledge_base_ids: ctx.channel!.knowledgeBaseIds, knowledge_selection_explicit: true, enable_memory: false, web_search_enabled: false, mcp_service_ids: [], embed_channel_id: ctx.channel!.id, channel_guest_id: ctx.channel!.guestId, channel_grant_id: ctx.channel!.grantId };
  }
  createSession(ctx: AuthContext): JsonObject { this.auth.assertCan(ctx, 'write'); return this.sessionProjection(this.chat.create(ctx, { title: 'Embed chat', agent_config: this.agentConfig(ctx) })); }
  input(ctx: AuthContext, input: JsonObject): JsonObject {
    this.auth.assertCan(ctx, 'write'); if (Object.keys(input).some(key => !['query', 'stream', 'request_id', 'knowledge_base_ids'].includes(key))) fail(403, 'channel_config_forbidden', '访客不能更改渠道模型、工具或附件配置。');
    if (input.knowledge_base_ids !== undefined && ids(input.knowledge_base_ids).some(id => !ctx.channel!.knowledgeBaseIds.includes(id))) fail(403, 'channel_scope_forbidden', '知识库不在公开渠道范围内。');
    return { ...input, channel: 'embed', allowed_tools: this.agentConfig(ctx).allowed_tools! };
  }
  track(work: Promise<JsonObject>): Promise<JsonObject> { this.active.add(work); void work.finally(() => this.active.delete(work)).catch(() => {}); return work; }
  async close(): Promise<void> { this.closed = true; await Promise.allSettled([...this.active]); this.authority.close(); }
}
