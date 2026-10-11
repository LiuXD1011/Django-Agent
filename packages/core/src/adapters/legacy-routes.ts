import { CoreStream, type CoreApplication, type PublicRouteContext } from '../application.js';
import { AppError } from '../errors.js';
import { LegacyTenantService, ChannelService } from '../legacy/index.js';

export function registerLegacyRoutes(app: CoreApplication): { tenants: LegacyTenantService; channels: ChannelService } {
  const tenants = new LegacyTenantService(app.database, app.auth);
  for (const path of ['/api/v1/tenants', '/api/v1/tenants/all', '/api/v1/tenants/search']) app.route('GET', path, c => tenants.list(c.auth, Object.fromEntries(c.query)));
  app.route('POST', '/api/v1/tenants', c => tenants.create(c.auth, c.body));
  app.route('GET', '/api/v1/tenants/:id', c => tenants.get(c.auth, c.params.id!));
  for (const method of ['PUT', 'PATCH'] as const) app.route(method, '/api/v1/tenants/:id', c => tenants.update(c.auth, c.params.id!, c.body));
  app.route('DELETE', '/api/v1/tenants/:id', c => tenants.delete(c.auth, c.params.id!));
  app.route('GET', '/api/v1/tenants/:id/members', c => tenants.members(c.auth, c.params.id!));
  app.route('POST', '/api/v1/tenants/:id/members', c => tenants.setMember(c.auth, c.params.id!, c.body));
  for (const method of ['PUT', 'PATCH'] as const) app.route(method, '/api/v1/tenants/:id/members/:user', c => tenants.setMember(c.auth, c.params.id!, c.body, c.params.user!));
  app.route('DELETE', '/api/v1/tenants/:id/members/:user', c => tenants.removeMember(c.auth, c.params.id!, c.params.user!));
  app.route('POST', '/api/v1/tenants/:id/api-key', c => tenants.rotateApiKey(c.auth, c.params.id!, { revealKey: c.transport === 'http' }));
  app.route('POST', '/api/v1/auth/switch-tenant', c => {
    const id = c.body.tenant_id;
    if ((typeof id !== 'string' && typeof id !== 'number') || !/^\d+$/.test(String(id))) throw new AppError(400, 'invalid_tenant', '空间标识不正确。');
    return tenants.switch(c.auth, String(id));
  });
  app.route('GET', '/api/v1/tenants/:id/audit-log', c => tenants.auditLog(c.auth, c.params.id!));
  app.route('GET', '/api/v1/system/admin/audit-log', c => tenants.auditLog(c.auth));
  const channels = new ChannelService(app.database, app.auth, app.vault, app.chat);
  for (const [path, kind] of [['embed-channels', 'embed_channels'], ['im-channels', 'im_channels']] as const) {
    app.route('GET', `/api/v1/${path}`, c => channels.list(c.auth, kind, Object.fromEntries(c.query)));
    app.route('POST', `/api/v1/${path}`, c => channels.create(c.auth, kind, c.body));
    app.route('GET', `/api/v1/${path}/:id`, c => channels.get(c.auth, kind, c.params.id!));
    for (const method of ['PUT', 'PATCH'] as const) app.route(method, `/api/v1/${path}/:id`, c => channels.update(c.auth, kind, c.params.id!, c.body));
    app.route('DELETE', `/api/v1/${path}/:id`, c => channels.delete(c.auth, kind, c.params.id!));
    app.route('POST', `/api/v1/${path}/:id/toggle`, c => channels.toggle(c.auth, kind, c.params.id!));
    app.route('GET', `/api/v1/agents/:id/${path}`, c => channels.list(c.auth, kind, Object.fromEntries(c.query), c.params.id!));
    app.route('POST', `/api/v1/agents/:id/${path}`, c => channels.create(c.auth, kind, { ...c.body, agent_id: c.params.id! }));
  }
  app.route('POST', '/api/v1/embed-channels/:id/rotate-token', c => channels.rotate(c.auth, c.params.id!, c.transport === 'http'));
  app.route('POST', '/api/v1/embed-channels/:id/preview-session', c => channels.preview(c.auth, c.params.id!));
  app.route('GET', '/api/v1/embed-channels/:id/stats', c => channels.stats(c.auth, c.params.id!));
  const guest = (c: PublicRouteContext) => channels.authenticate(c.params.channel!, c.bearer ?? c.query.get('token') ?? '', c.origin ?? '');
  app.publicRoute('POST', '/api/v1/embed/:channel/exchange', c => channels.exchange(c.params.channel!, c.origin ?? ''));
  app.publicRoute('GET', '/api/v1/embed/:channel/config', c => channels.config(guest(c)));
  app.publicRoute('GET', '/api/v1/embed/:channel/suggested-questions', c => channels.questions(guest(c)));
  app.publicRoute('POST', '/api/v1/embed/:channel/sessions', c => {
    if (Object.keys(c.body).some(key => !['title'].includes(key))) throw new AppError(403, 'channel_config_forbidden', '公开会话配置由渠道固定。');
    return channels.createSession(guest(c));
  });
  app.publicRoute('GET', '/api/v1/embed/:channel/messages/:session/load', c => app.chat.loadMessages(guest(c), c.params.session!, Object.fromEntries(c.query)));
  app.publicRoute('GET', '/api/v1/embed/:channel/sessions/:session/events', c => app.chat.events(guest(c), c.params.session!, Object.fromEntries(c.query)));
  app.publicRoute('GET', '/api/v1/embed/:channel/chunks/:chunk', c => {
    const auth = guest(c), row = app.database.read('chunks', c.params.chunk!), doc = row ? app.database.read('knowledges', String(row.knowledge_id)) : undefined;
    if (!row || row.deleted_at !== null || row.is_enabled !== true || String(row.tenant_id) !== auth.tenantId || !auth.channel!.knowledgeBaseIds.includes(String(row.knowledge_base_id)) || !doc || doc.deleted_at !== null || doc.enable_status !== 'enabled' || String(doc.tenant_id) !== auth.tenantId || doc.knowledge_base_id !== row.knowledge_base_id) throw new AppError(404, 'chunk_not_found', '分块不存在。');
    return Object.fromEntries(['id', 'knowledge_id', 'knowledge_base_id', 'content', 'chunk_type', 'seq_id', 'start_at', 'end_at', 'created_at', 'updated_at'].map(key => [key, row[key] ?? null]));
  });
  app.publicRoute('POST', '/api/v1/embed/:channel/sessions/:session/stop', c => {
    const auth = guest(c), id = c.body.message_id ?? c.body.request_id;
    if (typeof id !== 'string') throw new AppError(400, 'message_required', '请指定回复或请求标识。');
    return app.chat.stop(auth, c.params.session!, id);
  });
  for (const [path, agent] of [['knowledge-chat', false], ['agent-chat', true]] as const) app.publicRoute('POST', `/api/v1/embed/:channel/${path}/:session`, c => {
    const auth = guest(c), input = channels.input(auth, c.body), started = app.chat.start(auth, c.params.session!, input, c.request.id, agent);
    const work = channels.track(app.runTask(() => app.chat.run(auth, c.params.session!, started.request_id)));
    void work.catch(() => { try { const scope = { tenantId: auth.tenantId, userId: auth.userId }, job = app.jobs.get(started.job_id, scope); if (!started.idempotent && job.status === 'queued' && job.attempt === 0) app.jobs.cancelByRequest(job.requestId, scope); } catch {} });
    return c.body.stream === true ? new CoreStream(app.chat.stream(auth, c.params.session!, started.request_id, { signal: c.signal })) : work;
  });
  return { tenants, channels };
}
