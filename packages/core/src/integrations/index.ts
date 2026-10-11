import { Worker } from 'node:worker_threads';
import { createHash, randomUUID } from 'node:crypto';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import { SSEClientTransport } from '@modelcontextprotocol/sdk/client/sse.js';
import type { AuthContext, JsonObject } from '../contracts.js';
import { AuthError, type AuthService } from '../auth/index.js';
import type { CoreDatabase } from '../storage/database.js';
import { CredentialVault } from '../storage/credentials.js';
import type { SettingsService } from '../settings/index.js';
import { AppError } from '../errors.js';
import { CallScope, type IntegrationCallOptions, endpoint, fail, responseJSON, restrictedFetch } from './network.js';
import { search } from './search.js';
import { recordTrace, type TraceEvent } from './trace.js';
import { clearSession, login, nativeLogin, nativeGuard, openURL, type NativeLangfusePlan, type LangfuseSessionOptions, type LangfuseSessionResult } from './langfuse-login.js';
import { externalProjection } from './projection.js';
import { cleanupScope, pendingCleanup } from '../graph/cleanup.js';
import { legacyGraphReadQuery, type LegacyGraphPage, type LegacyGraphTicket } from '../storage/graph-legacy.js';

export type { IntegrationCallOptions } from './network.js';
export type { TraceEvent } from './trace.js';
export type { LangfuseSessionOptions, LangfuseSessionResult, SessionCookie } from './langfuse-login.js';
export interface Neo4jCallOptions extends IntegrationCallOptions { database?: string; write?: boolean }

export class IntegrationService {
  private readonly vault: CredentialVault;
  private readonly active = new Set<CallScope>();
  private readonly activeCalls = new Set<Promise<unknown>>();
  private readonly workers = new Set<Worker>();
  private readonly mcpClosers = new Set<() => Promise<void>>();
  private readonly loginCooldown = new Map<string, number>();
  private readonly nativeTickets = new Map<string, { owner: string; configuration: string; plan: NativeLangfusePlan }>();
  private closed = false;
  constructor(private readonly db: CoreDatabase, private readonly auth: AuthService, private readonly settings: SettingsService) { this.vault = new CredentialVault(db.dataRoot); }
  private administrator(ctx: AuthContext): void {
    this.auth.assertCan(ctx, 'read');
    if (!ctx.userId || this.auth.me(ctx).user.is_system_admin !== true) fail(403, 'system_admin_required', 'System administrator permission required');
  }
  private integration(ctx: AuthContext, name: string, administrator = true): JsonObject {
    if (administrator) this.settings.getIntegration(ctx, name); else this.auth.assertCan(ctx, 'read');
    const row = this.db.read('integration_configs', name);
    try { return row && row.deleted_at == null ? this.vault.decrypt(row.parameters ?? {}) as JsonObject : {}; }
    catch { return fail(503, 'integration_credentials_unavailable', 'Saved integration credentials are unavailable'); }
  }
  private provider(ctx: AuthContext, type: string, id: string, write = false): JsonObject {
    this.auth.assertCan(ctx, write ? 'admin' : 'read'); this.settings.getProvider(ctx, type, id);
    const row = this.db.read('generic_resources', id)!;
    if (row.status !== 'active') return { enabled: false };
    try { return this.vault.decrypt(row.data ?? {}) as JsonObject; }
    catch { return fail(503, 'integration_credentials_unavailable', 'Saved provider credentials are unavailable'); }
  }
  private async call<T>(options: IntegrationCallOptions, work: (scope: CallScope) => Promise<T>): Promise<T> {
    if (this.closed) return fail(503, 'integration_closed', 'Integration service is closed');
    const scope = new CallScope(options); this.active.add(scope);
    try {
      scope.check();
      const pending = Promise.resolve().then(() => { scope.check(); return work(scope); });
      this.activeCalls.add(pending);
      void pending.then(() => this.activeCalls.delete(pending), () => this.activeCalls.delete(pending));
      const value = await scope.wait(pending); scope.check(); return value;
    }
    catch (error) { scope.check(); if (error instanceof AppError || error instanceof AuthError) throw error; return fail(502, 'integration_connection_failed', 'External service connection failed'); }
    finally { scope.dispose(); this.active.delete(scope); }
  }
  async testIntegration(ctx: AuthContext, section: string, options: IntegrationCallOptions = {}): Promise<JsonObject> {
    if (!['neo4j', 'langfuse'].includes(section)) { this.administrator(ctx); return fail(404, 'integration_not_found', 'Integration not found'); }
    const config = this.integration(ctx, section);
    if (config.enabled !== true) return { state: 'disabled' };
    if (!(section === 'neo4j' ? ['uri', 'username', 'password'] : ['base_url', 'public_key', 'secret_key']).every(key => config[key])) return { state: 'not_configured' };
    if (section === 'neo4j') {
      return this.call(options, scope => this.neo4j(scope, config));
    }
    return this.call(options, async scope => {
      const base = endpoint(config.base_url), url = new URL(base.toString().replace(/\/$/, '') + '/api/public/projects');
      const response = await restrictedFetch(scope, base.origin)(url, { headers: { authorization: this.basic(config.public_key, config.secret_key), accept: 'application/json' } });
      const result = await responseJSON(response) as any;
      if (!Array.isArray(result?.data) || result.data.some((row: any) => !row || typeof row.id !== 'string' || typeof row.name !== 'string')) return fail(502, 'integration_invalid_response', 'Langfuse returned an invalid projects response');
      return { state: 'connected', project_count: result.data.length, tracing: { sample_rate: typeof config.sample_rate === 'number' ? config.sample_rate : 1, environment: String(config.tracing_environment || 'default'), content_enabled: config.log_content === true, transport: 'otlp_http_json', content_support: 'explicit_sanitized_previews', evaluation_dataset_support: 'requires_evaluation_adapter' } };
    });
  }
  private basic(user: unknown, password: unknown): string { return `Basic ${Buffer.from(`${user}:${password}`).toString('base64')}`; }
  private async neo4j(scope: CallScope, config: JsonObject, query: JsonObject = {}): Promise<JsonObject> {
    let url: URL; try { url = new URL(String(config.uri)); } catch { return fail(400, 'integration_invalid_endpoint', 'Invalid Neo4j endpoint'); }
    if (!['bolt:', 'bolt+s:', 'bolt+ssc:', 'neo4j:', 'neo4j+s:', 'neo4j+ssc:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) return fail(400, 'integration_invalid_endpoint', 'Invalid Neo4j endpoint');
    scope.check();
    const worker = new Worker(new URL(import.meta.url.endsWith('.ts') ? './neo4j-worker.ts' : './neo4j-worker.js', import.meta.url), { workerData: { uri: config.uri, username: config.username, password: config.password, timeoutMs: scope.timeoutMs, ...query } });
    this.workers.add(worker);
    const abort = () => { void worker.terminate().catch(() => {}); }; scope.signal.addEventListener('abort', abort, { once: true });
    try {
      return await scope.wait(new Promise<JsonObject>((resolve, reject) => {
        worker.once('message', (result: JsonObject) => {
          if (result.error) reject(new AppError(502, String(result.error), result.error === 'integration_response_too_large' ? 'Graph query exceeded the result limit' : 'External service connection failed'));
          else resolve(result);
        });
        worker.once('error', () => reject(new AppError(502, 'integration_connection_failed', 'External service connection failed')));
        worker.once('exit', () => reject(new AppError(502, 'integration_connection_failed', 'External service connection failed')));
      }));
    } finally { scope.signal.removeEventListener('abort', abort); await worker.terminate(); this.workers.delete(worker); }
  }
  /** Trusted core-only arbitrary Cypher; do not expose this method as a tenant query route. */
  async queryNeo4j(ctx: AuthContext, statement: string, parameters: JsonObject = {}, options: Neo4jCallOptions = {}): Promise<JsonObject> {
    const config = this.integration(ctx, 'neo4j');
    if (config.enabled !== true) return { state: 'disabled' };
    if (!['uri', 'username', 'password'].every(key => config[key])) return { state: 'not_configured' };
    const snapshot = this.graphQuery(statement, parameters, options);
    return this.call(options, scope => this.neo4j(scope, config, snapshot));
  }
  private graphQuery(statement: string, parameters: JsonObject, options: Neo4jCallOptions): JsonObject {
    if (typeof statement !== 'string' || !statement.trim() || Buffer.byteLength(statement) > 16384 || !parameters || typeof parameters !== 'object' || Array.isArray(parameters)) return fail(400, 'integration_invalid_query', 'Invalid graph query');
    let count = 0;
    const valid = (value: unknown, depth = 0): boolean => {
      if (++count > 10000 || depth > 16) return false;
      if (value === null || typeof value === 'string' || typeof value === 'boolean') return true;
      if (typeof value === 'number') return Number.isFinite(value);
      if (typeof value !== 'object') return false;
      if (!Array.isArray(value) && Object.getPrototypeOf(value) !== Object.prototype && Object.getPrototypeOf(value) !== null) return false;
      return Object.values(value).every(item => valid(item, depth + 1));
    };
    if (!valid(parameters)) return fail(400, 'integration_invalid_query', 'Invalid graph query');
    const serialized = JSON.stringify(parameters);
    if (Buffer.byteLength(serialized) > 256 * 1024) return fail(400, 'integration_invalid_query', 'Invalid graph query');
    if (options.database !== undefined && (typeof options.database !== 'string' || !/^[a-zA-Z0-9_.-]{1,63}$/.test(options.database))) return fail(400, 'integration_invalid_database', 'Invalid graph database name');
    return { statement, parameters: JSON.parse(serialized), database: options.database || 'neo4j', write: options.write === true };
  }
  /** Trusted core graph templates only. The caller owns all Cypher predicates and generation fences; never route arbitrary tenant Cypher here. */
  async queryScopedNeo4j(ctx: AuthContext, kbId: string, statement: string, parameters: JsonObject = {}, options: Neo4jCallOptions = {}): Promise<JsonObject> {
    const assertScope = () => {
      this.auth.assertCan(ctx, 'read');
      const kb = this.db.read('knowledge_bases', kbId);
      if (!kb || kb.deleted_at !== null || String(kb.tenant_id) !== ctx.tenantId) return fail(404, 'knowledge_base_not_found', 'Knowledge base not found');
      if (options.write === true) this.auth.assertCan(ctx, 'document.write');
    };
    assertScope();
    const query = this.graphQuery(statement, parameters, options), bound = query.parameters as JsonObject;
    const namespace = createHash('sha256').update(JSON.stringify([ctx.tenantId, kbId])).digest('hex');
    if (bound.tenant_id !== ctx.tenantId || bound.knowledge_base_id !== kbId || bound.namespace !== namespace) return fail(400, 'integration_scope_mismatch', 'Graph query parameters do not match the authorized knowledge base');
    const config = this.integration(ctx, 'neo4j', false);
    if (config.enabled !== true) return { state: 'disabled' };
    if (!['uri', 'username', 'password'].every(key => config[key])) return { state: 'not_configured' };
    return this.call(options, async scope => {
      assertScope();
      if (JSON.stringify(this.integration(ctx, 'neo4j', false)) !== JSON.stringify(config)) return fail(409, 'integration_configuration_changed', 'Saved graph configuration changed during the connection');
      const result = await this.neo4j(scope, config, query);
      assertScope();
      if (JSON.stringify(this.integration(ctx, 'neo4j', false)) !== JSON.stringify(config)) return fail(409, 'integration_configuration_changed', 'Saved graph configuration changed during the connection');
      return externalProjection(result, config);
    });
  }
  /** Public readiness contains no endpoint or credentials and requires only a real authorized KB read. */
  /** CLI migration only: a verified opaque source ticket, fixed ENTITY read templates, and the original saved connection. Never expose as a renderer route. */
  async readLegacyGraph(ctx: AuthContext, ticket: LegacyGraphTicket, page: LegacyGraphPage, options: IntegrationCallOptions = {}): Promise<JsonObject> {
    const fixed = legacyGraphReadQuery(this.db, this.auth, ctx, ticket, page);
    const config = this.integration(ctx, 'neo4j', false);
    const query = this.graphQuery(fixed.statement, fixed.parameters, { ...options, write: false });
    return this.call(options, async scope => {
      legacyGraphReadQuery(this.db, this.auth, ctx, ticket, page);
      const result = await this.neo4j(scope, config, query);
      scope.check(); legacyGraphReadQuery(this.db, this.auth, ctx, ticket, page);
      // These properties go only to a private source archive. Applying a public settings projection would silently lose original graph properties.
      return result;
    });
  }
  /** Public readiness contains no endpoint or credentials and requires only a real authorized KB read. */
  scopedNeo4jReadiness(ctx: AuthContext, kbId: string): JsonObject {
    this.auth.assertCan(ctx, 'read'); const kb = this.db.read('knowledge_bases', kbId);
    if (!kb || kb.deleted_at !== null || String(kb.tenant_id) !== ctx.tenantId) return fail(404, 'knowledge_base_not_found', 'Knowledge base not found');
    const config = this.integration(ctx, 'neo4j', false);
    let valid = false;
    try { const uri = new URL(String(config.uri)); valid = ['bolt:', 'bolt+s:', 'bolt+ssc:', 'neo4j:', 'neo4j+s:', 'neo4j+ssc:'].includes(uri.protocol) && !!uri.hostname && !uri.username && !uri.password && !uri.search && !uri.hash; } catch {}
    const configured = config.enabled === true && valid && ['username', 'password'].every(key => typeof config[key] === 'string' && Boolean(config[key]));
    return { state: config.enabled !== true ? 'disabled' : configured ? 'configured' : 'not_configured', enabled: config.enabled === true, configured, connection_verified: false };
  }
  /** Trusted core deletion outbox only. No caller-selected Cypher or parameters; tombstones permit deletion, never reads. */
  async cleanupScopedNeo4j(ctx: AuthContext, kbId: string, pendingKey: string, options: IntegrationCallOptions = {}): Promise<JsonObject> {
    const pending = pendingCleanup(this.db, this.auth, ctx, kbId, pendingKey);
    const config = this.integration(ctx, 'neo4j', false);
    if (config.enabled !== true) return { state: 'disabled' };
    if (!['uri', 'username', 'password'].every(key => config[key])) return { state: 'not_configured' };
    const query = this.graphQuery(pending.statement, pending.params, { ...options, write: true });
    const assertUnchanged = () => {
      cleanupScope(this.db, this.auth, ctx, kbId);
      if (pendingCleanup(this.db, this.auth, ctx, kbId, pendingKey).raw !== pending.raw) return fail(409, 'graph_cleanup_ticket_changed', 'Graph cleanup ticket changed');
      if (JSON.stringify(this.integration(ctx, 'neo4j', false)) !== JSON.stringify(config)) return fail(409, 'integration_configuration_changed', 'Saved graph configuration changed during the connection');
    };
    return this.call(options, async scope => { assertUnchanged(); const result = pending.skip ? { state: 'connected', records: [] } : await this.neo4j(scope, config, query); scope.check(); assertUnchanged(); return externalProjection(result, config); });
  }
  async search(ctx: AuthContext, id: string, query: string, options: IntegrationCallOptions = {}): Promise<JsonObject> {
    const config = this.provider(ctx, 'web_search_providers', id);
    if (config.enabled === false) return { state: 'disabled', results: [] };
    return this.call(options, async scope => {
      const result = await search(scope, config, query) as unknown as JsonObject;
      this.provider(ctx, 'web_search_providers', id);
      return externalProjection(result, config);
    });
  }
  /** Core-only telemetry. Caller handles its optional failure separately from the business/model call. */
  async recordTrace(ctx: AuthContext, event: TraceEvent, options: IntegrationCallOptions = {}): Promise<JsonObject> {
    const config = this.integration(ctx, 'langfuse', false);
    if (config.enabled !== true) return { state: 'disabled' };
    if (!['base_url', 'public_key', 'secret_key'].every(key => config[key])) return { state: 'not_configured' };
    return this.call(options, scope => recordTrace(scope, config, ctx.tenantId, ctx.userId, event));
  }
  private loginConfiguration(ctx: AuthContext): { config: JsonObject; local: JsonObject } {
    this.auth.assertCan(ctx, 'read'); const config = this.integration(ctx, 'langfuse', false), local = this.integration(ctx, 'local_services', false);
    if (!ctx.userId || (this.auth.me(ctx).user.is_system_admin !== true && (!local.local_login_user_id || local.local_login_user_id !== ctx.userId))) return fail(403, 'local_account_required', 'This account is not authorized for local Langfuse login');
    return { config, local };
  }
  /** Private native adapter only. These tickets/cookies are not renderer route data. */
  prepareNativeLangfuse(ctx: AuthContext): NativeLangfusePlan {
    if (this.closed) return fail(503, 'integration_closed', 'Integration service is closed');
    const { config, local } = this.loginConfiguration(ctx);
    if (!config.base_url || !config.ui_project_id) return fail(409, 'needs_configuration', '请先在设置中配置 Langfuse 界面地址与项目。');
    const destination = new URL(openURL(config));
    const owner = JSON.stringify([ctx.tenantId, ctx.userId, ctx.deviceId]);
    let reason = local.auto_login !== true ? 'auto_login_disabled' : !local.login_email || !local.password ? 'credentials_missing' : '';
    if (!reason) { try { nativeGuard(config); } catch (error) { if (!(error instanceof AppError) || error.code !== 'local_host_required') throw error; reason = error.code; } }
    const plan: NativeLangfusePlan = { ticket: randomUUID(), ownerScope: createHash('sha256').update(owner).digest('hex'), origin: destination.origin, projectPath: destination.pathname.replace(/\/traces$/, '/'), open_url: destination.href, mode: reason ? 'manual' : 'automatic', reason };
    // One current ticket per exact private device/space. A fresh plan invalidates old publication.
    for (const [ticket, saved] of this.nativeTickets) if (saved.owner === owner) this.nativeTickets.delete(ticket);
    if (this.nativeTickets.size >= 64) this.nativeTickets.delete(this.nativeTickets.keys().next().value!);
    this.nativeTickets.set(plan.ticket, { owner, configuration: JSON.stringify([config, local]), plan });
    return { ...plan };
  }
  assertNativeLangfuse(ctx: AuthContext, ticket: string): NativeLangfusePlan {
    const { config, local } = this.loginConfiguration(ctx), saved = this.nativeTickets.get(ticket);
    if (this.closed) return fail(503, 'integration_closed', 'Integration service is closed');
    if (!saved || saved.owner !== JSON.stringify([ctx.tenantId, ctx.userId, ctx.deviceId])) return fail(409, 'native_login_superseded', 'Langfuse 登录状态已改变，请重新打开。');
    if (saved.configuration !== JSON.stringify([config, local])) { this.nativeTickets.delete(ticket); return fail(409, 'integration_configuration_changed', 'Langfuse 配置已改变，请重新打开。'); }
    return { ...saved.plan };
  }
  clearNativeLangfuse(ctx: AuthContext): JsonObject {
    this.auth.assertCan(ctx, 'read'); const owner = JSON.stringify([ctx.tenantId, ctx.userId, ctx.deviceId]);
    for (const [ticket, saved] of this.nativeTickets) if (saved.owner === owner) this.nativeTickets.delete(ticket);
    this.loginCooldown.delete(`${ctx.tenantId}:${ctx.userId}`); return { state: 'cleared' };
  }
  async nativeLangfuseSession(ctx: AuthContext, ticket: string, existingCookies: Record<string, string> | undefined, options: IntegrationCallOptions = {}): Promise<LangfuseSessionResult> {
    const plan = this.assertNativeLangfuse(ctx, ticket);
    if (plan.mode === 'manual') return { result: { state: 'manual', manual_reason: plan.reason, open_url: plan.open_url, message: '已打开 Langfuse，请在新页面手动登录。' }, cookies: [] };
    const { config, local } = this.loginConfiguration(ctx), key = `${ctx.tenantId}:${ctx.userId}`;
    if ((this.loginCooldown.get(key) || 0) > Date.now()) return fail(429, 'login_cooldown', 'Local login failed recently; retry after one minute');
    try {
      return await this.call(options, async scope => {
        this.assertNativeLangfuse(ctx, ticket);
        const result = await nativeLogin(scope, config, local, existingCookies);
        scope.check(); this.assertNativeLangfuse(ctx, ticket); return result;
      });
    } catch (error) {
      if (error instanceof AppError && ['login_failed', 'integration_connection_failed', 'integration_invalid_response'].includes(error.code)) { this.loginCooldown.set(key, Date.now() + 60000); return fail(502, 'login_failed', 'Langfuse login verification failed; check the service and account configuration'); }
      throw error;
    }
  }
  async langfuseStatus(ctx: AuthContext, options: IntegrationCallOptions = {}): Promise<JsonObject> {
    const { config, local } = this.loginConfiguration(ctx), destination = openURL(config);
    return this.call(options, async scope => {
      const base = endpoint(config.base_url || 'http://localhost:3000');
      let healthy = false;
      try { const response = await restrictedFetch(scope, base.origin)(new URL(base.toString().replace(/\/$/, '') + '/api/public/health')); healthy = response.ok; await response.body?.cancel(); }
      catch (error) { scope.check(); if (error instanceof AppError && error.code === 'integration_redirect_rejected') throw error; }
      return { state: healthy ? 'healthy' : 'unavailable', auto_login: local.auto_login === true, credentials_configured: Boolean(local.login_email && local.password), open_url: destination };
    });
  }
  /** Trusted HTTP/platform adapter only. Serialize result; apply cookies as HttpOnly, never JSON. */
  async langfuseSession(ctx: AuthContext, options: LangfuseSessionOptions): Promise<LangfuseSessionResult> {
    const { config, local } = this.loginConfiguration(ctx);
    if (local.auto_login !== true) return fail(409, 'auto_login_disabled', 'Local automatic login is disabled');
    const key = `${ctx.tenantId}:${ctx.userId}`;
    if ((this.loginCooldown.get(key) || 0) > Date.now()) return fail(429, 'login_cooldown', 'Local login failed recently; retry after one minute');
    try {
      return await this.call(options, async scope => {
        const result = await login(scope, config, local, options);
        this.loginConfiguration(ctx); return result;
      });
    } catch (error) {
      if (error instanceof AppError && ['login_failed', 'integration_connection_failed', 'integration_invalid_response'].includes(error.code)) { this.loginCooldown.set(key, Date.now() + 60000); return fail(502, 'login_failed', 'Langfuse login verification failed; check the service and account configuration'); }
      throw error;
    }
  }
  clearLangfuseSession(ctx: AuthContext, options: LangfuseSessionOptions): LangfuseSessionResult {
    this.auth.assertCan(ctx, 'read'); const config = this.integration(ctx, 'langfuse', false);
    this.loginCooldown.delete(`${ctx.tenantId}:${ctx.userId}`); return clearSession(config, options);
  }
  async testProvider(ctx: AuthContext, type: string, id: string, options: IntegrationCallOptions = {}): Promise<JsonObject> {
    this.provider(ctx, type, id, true);
    if (type === 'web_search_providers') { const result = await this.search(ctx, id, 'Marlin connection test', options); return { state: result.state!, result_count: Array.isArray(result.results) ? result.results.length : 0 }; }
    if (type === 'mcp_services') { const result = await this.listMcpTools(ctx, id, options); return { state: result.state!, tool_count: Array.isArray(result.tools) ? result.tools.length : 0 }; }
    return fail(501, 'integration_unsupported_provider', 'Provider has no external adapter');
  }
  private async mcp(ctx: AuthContext, id: string, options: IntegrationCallOptions, work: (client: Client, scope: CallScope) => Promise<JsonObject>, write = false): Promise<JsonObject> {
    const config = this.provider(ctx, 'mcp_services', id, write);
    if (config.enabled === false) return { state: 'disabled', tools: [] };
    if (!config.url) return { state: 'not_configured', tools: [] };
    const url = endpoint(config.url), headers: Record<string, string> = {};
    if (config.headers && typeof config.headers === 'object' && !Array.isArray(config.headers)) for (const [name, value] of Object.entries(config.headers)) {
      if (!/^[a-zA-Z0-9-]{1,80}$/.test(name) || typeof value !== 'string' || /[\r\n]/.test(value) || /^(host|cookie|connection|content-length|proxy-authorization)$/i.test(name)) return fail(400, 'integration_invalid_headers', 'Invalid MCP request headers');
      headers[name] = value;
    }
    if (config.api_key) headers.Authorization = `Bearer ${config.api_key}`;
    const kind = String(config.transport || 'streamable_http');
    if (!['sse', 'streamable_http', 'streamable-http', 'http'].includes(kind)) return fail(400, 'integration_unsupported_transport', 'Unsupported MCP transport');
    return this.call(options, async scope => {
      const fetch = restrictedFetch(scope, url.origin);
      const transport = kind === 'sse' ? new SSEClientTransport(url, { fetch, requestInit: { headers, redirect: 'manual' }, eventSourceInit: { fetch }, redirectPolicy: 'follow' }) : new StreamableHTTPClientTransport(url, { fetch, requestInit: { headers, redirect: 'manual' }, redirectPolicy: 'follow', reconnectionOptions: { maxRetries: 0, initialReconnectionDelay: 1000, maxReconnectionDelay: 1000, reconnectionDelayGrowFactor: 1 } });
      const client = new Client({ name: 'marlin-core', version: '0.7.0' }, { capabilities: {} });
      const cleanup = async () => { await client.close().catch(() => {}); await transport.close().catch(() => {}); };
      this.mcpClosers.add(cleanup);
      try {
        await scope.wait(client.connect(transport, { signal: scope.signal, timeout: scope.timeoutMs, maxTotalTimeout: scope.timeoutMs }));
        // Reauthorize after handshake before discovering data or invoking an external side effect.
        if (JSON.stringify(this.provider(ctx, 'mcp_services', id, write)) !== JSON.stringify(config)) return fail(409, 'integration_configuration_changed', 'Saved MCP configuration changed during the connection');
        const result = await scope.wait(work(client, scope));
        this.provider(ctx, 'mcp_services', id, write);
        return externalProjection(result, config);
      } finally {
        if (transport instanceof StreamableHTTPClientTransport && transport.sessionId && !scope.signal.aborted) await scope.wait(transport.terminateSession()).catch(() => {});
        await cleanup(); this.mcpClosers.delete(cleanup);
      }
    });
  }
  async listMcpTools(ctx: AuthContext, id: string, options: IntegrationCallOptions = {}): Promise<JsonObject> {
    return this.mcp(ctx, id, options, async (client, scope) => {
      const tools: JsonObject[] = [], cursors = new Set<string>(); let cursor: string | undefined;
      do {
        const page = await client.listTools(cursor ? { cursor } : undefined, { signal: scope.signal, timeout: scope.timeoutMs, maxTotalTimeout: scope.timeoutMs });
        for (const tool of page.tools) { if (tools.length >= 1000) return fail(502, 'integration_response_too_large', 'MCP tool list exceeds the limit'); tools.push({ name: tool.name, description: tool.description || '', inputSchema: tool.inputSchema as JsonObject, ...(tool.annotations ? { annotations: tool.annotations as JsonObject } : {}) }); }
        cursor = page.nextCursor; if (cursor) { if (cursors.has(cursor)) return fail(502, 'integration_invalid_response', 'MCP pagination cursor repeated'); cursors.add(cursor); }
      } while (cursor);
      return { state: 'connected', tools, untrusted: true };
    });
  }
  async callMcpTool(ctx: AuthContext, id: string, name: string, args: JsonObject, options: IntegrationCallOptions = {}): Promise<JsonObject> {
    if (typeof name !== 'string' || !name || name.length > 128 || !args || typeof args !== 'object' || Array.isArray(args) || Buffer.byteLength(JSON.stringify(args)) > 256 * 1024) { this.auth.assertCan(ctx, 'admin'); return fail(400, 'integration_invalid_tool', 'Invalid MCP tool request'); }
    return this.mcp(ctx, id, options, async (client, scope) => {
      const result = await client.callTool({ name, arguments: args }, undefined, { signal: scope.signal, timeout: scope.timeoutMs, maxTotalTimeout: scope.timeoutMs });
      if (!('content' in result) || !Array.isArray(result.content)) return fail(502, 'integration_invalid_response', 'MCP tool returned an unsupported response');
      return { state: 'connected', content: result.content as unknown as JsonObject[], ...(result.structuredContent ? { structuredContent: result.structuredContent as JsonObject } : {}), isError: result.isError === true, untrusted: true };
    }, true);
  }
  async close(): Promise<void> {
    this.closed = true;
    this.nativeTickets.clear();
    const scopes = [...this.active];
    for (const scope of scopes) scope.controller.abort(new AppError(503, 'integration_closed', 'Integration service is closed'));
    await Promise.allSettled([...this.workers].map(worker => worker.terminate()));
    await Promise.allSettled([...this.mcpClosers].map(cleanup => cleanup()));
    await Promise.allSettled([...this.activeCalls]);
    await Promise.allSettled(scopes.map(scope => scope.finished));
  }
}
