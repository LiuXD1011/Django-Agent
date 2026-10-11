import { randomUUID } from 'node:crypto';
import type { AuthContext, CoreRequest, CoreResponse, HttpMethod, Json, JsonObject } from './contracts.js';
import { AuthService, AuthError, type AuthIssue } from './auth/index.js';
import { AppError } from './errors.js';
import { JobQueue, JobError } from './jobs/index.js';
import { CoreDatabase } from './storage/database.js';
import { CredentialVault } from './storage/credentials.js';
import { registerSettingsRoutes } from './adapters/settings-routes.js';
import type { ModelConfigurationService, SettingsService } from './settings/index.js';
import { registerKnowledgeRoutes } from './adapters/knowledge-routes.js';
import type { KnowledgeService } from './knowledge/index.js';
import type { SearchIndex } from './retrieval/index.js';
import { DocumentParser, ParserError } from './documents/parser.js';
import { DocumentWorkflow, type DocumentUpload } from './documents/workflow.js';
import { ModelRuntimeError } from './models/runtime.js';
import { registerDocumentRoutes } from './adapters/document-routes.js';
import { IntegrationService, type LangfuseSessionOptions, type SessionCookie } from './integrations/index.js';
import { AgentService } from './agents/index.js';
import { createApplicationAgentHooks } from './agents/application-hooks.js';
import { ObservabilityService } from './observability/index.js';
import { MemoryService } from './memory/index.js';
import { WikiService } from './wiki/index.js';
import { registerChatRoutes } from './adapters/chat-routes.js';
import type { ChatService } from './chat/index.js';
import { registerAgentRoutes } from './adapters/agent-routes.js';
import { registerWikiRoutes } from './adapters/wiki-routes.js';
import { GraphService } from './graph/index.js';
import { EvaluationService, type EvaluationOptions } from './evaluation/index.js';
import { ManagedChatUploads } from './chat/attachments.js';
import { registerGraphRoutes } from './adapters/graph-routes.js';
import { registerEvaluationRoutes } from './adapters/evaluation-routes.js';
import { registerSystemRoutes } from './adapters/system-routes.js';
import { registerLegacyRoutes } from './adapters/legacy-routes.js';

/** Created by a trusted HTTP/IPC adapter, never accepted in renderer request bodies. */
export interface PrivateBinding {
  transport: 'http' | 'ipc';
  access?: string;
  refresh?: string;
  bearer?: string;
  apiKey?: string;
  origin?: string;
  embedToken?: string;
  selectedTenant?: string;
  upload?: DocumentUpload;
  localSession?: Omit<LangfuseSessionOptions, 'signal'>;
}
/** Only registered core handlers construct binary results; never renderer JSON. */
export class CoreBinary {
  constructor(readonly bytes: Uint8Array, readonly name: string, readonly mimeType: string, readonly sha256: string) {}
}
export interface CoreFrame { event: string; data: JsonObject }
export class CoreStream { constructor(readonly frames: AsyncIterable<CoreFrame>) {} }
/** Session values are delivered only to a trusted transport's cookie store. */
export class CoreCookieResult { constructor(readonly data: JsonObject, readonly cookies: SessionCookie[]) {} }
export interface PrivateDispatch {
  response: CoreResponse;
  authChange?: { issue?: AuthIssue; clear: boolean };
  binary?: CoreBinary;
  stream?: CoreStream;
  cookies?: SessionCookie[];
}
export interface RouteContext {
  auth: AuthContext;
  transport: 'http' | 'ipc';
  request: CoreRequest;
  body: JsonObject;
  query: URLSearchParams;
  params: Record<string, string>;
  signal?: AbortSignal;
  upload?: DocumentUpload;
  localSession?: Omit<LangfuseSessionOptions, 'signal'>;
}
type RouteResult = Json | CoreBinary | CoreStream | CoreCookieResult;
export type RouteHandler = (context: RouteContext) => RouteResult | Promise<RouteResult>;
interface Route { method: HttpMethod; path: string; matcher: RegExp; names: string[]; handle: RouteHandler }
export interface PublicRouteContext {
  transport: 'http';
  request: CoreRequest;
  body: JsonObject;
  query: URLSearchParams;
  params: Record<string, string>;
  signal?: AbortSignal;
  origin?: string;
  bearer?: string;
}
export type PublicRouteHandler = (context: PublicRouteContext) => RouteResult | Promise<RouteResult>;
interface PublicRoute extends Omit<Route, 'handle'> { handle: PublicRouteHandler }
const PUBLIC_ROUTES = new Set([
  'POST /api/v1/embed/:channel/exchange',
  'GET /api/v1/embed/:channel/config',
  'GET /api/v1/embed/:channel/suggested-questions',
  'GET /api/v1/embed/:channel/chunks/:chunk',
  'POST /api/v1/embed/:channel/sessions',
  'POST /api/v1/embed/:channel/knowledge-chat/:session',
  'POST /api/v1/embed/:channel/agent-chat/:session',
  'GET /api/v1/embed/:channel/messages/:session/load',
  'POST /api/v1/embed/:channel/sessions/:session/stop',
  'GET /api/v1/embed/:channel/sessions/:session/events',
]);
function routePattern(path: string): Pick<Route, 'matcher' | 'names'> {
  const names: string[] = [];
  const matcher = path.split('/').map(part => {
    if (!part.startsWith(':')) return part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const wildcard = part.endsWith('*'); const name = part.slice(1, wildcard ? -1 : undefined);
    if (!/^[a-zA-Z][a-zA-Z0-9_]*$/.test(name)) throw new Error('Invalid core route');
    names.push(name); return wildcard ? '(.+)' : '([^/]+)';
  }).join('/');
  return { matcher: new RegExp(`^${matcher}$`), names };
}

export function success(data: Json): JsonObject { return { success: true, message: 'success', data }; }
export function errorResponse(id: string, error: unknown): CoreResponse {
  const known = error instanceof AuthError || error instanceof AppError || error instanceof JobError;
  const model = error instanceof ModelRuntimeError, parser = error instanceof ParserError;
  const status = known ? error.status : model ? error.status ?? (error.code === 'model_not_configured' ? 400 : 502) : parser ? error.code === 'parser_timeout' ? 408 : error.code === 'parser_cancelled' ? 409 : 400 : 500;
  const code = known || model || parser ? error.code : 'internal_error';
  const message = known || model ? error.message : parser ? '文档解析失败，请检查文件、解析器状态和处理记录。' : '操作失败，请查看应用诊断并重试。';
  return { protocol: 1, id, status, body: { success: false, message, error: { code, message, details: {} } } };
}

function requestObject(value: Json | undefined): JsonObject {
  if (value === undefined) return {};
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new AppError(400, 'invalid_body', '请求正文必须是 JSON 对象。');
  return value;
}
function field(body: JsonObject, name: string, alternative?: string): string {
  const value = body[name] ?? (alternative ? body[alternative] : undefined);
  if (value === undefined) return '';
  if (typeof value !== 'string') throw new AppError(400, 'invalid_field', '请求字段格式不正确。');
  return value;
}
function checkJson(value: unknown, ancestors = new Set<object>()): void {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return;
  if (typeof value === 'number' && Number.isFinite(value)) return;
  if (value && typeof value === 'object' && (Array.isArray(value) || Object.getPrototypeOf(value) === Object.prototype)) {
    if (ancestors.has(value)) throw new AppError(400, 'invalid_json', '请求包含循环引用。');
    ancestors.add(value);
    for (const item of Object.values(value)) checkJson(item, ancestors);
    ancestors.delete(value); return;
  }
  throw new AppError(400, 'invalid_json', '请求必须是有效的 JSON。');
}
export function validateCoreRequest(value: unknown): asserts value is CoreRequest {
  if (!value || typeof value !== 'object') throw new AppError(400, 'invalid_request', '请求协议不正确。');
  const request = value as CoreRequest;
  if (request.protocol !== 1 || typeof request.id !== 'string' || !request.id || request.id.length > 200 || /[\x00-\x1f\x7f]/.test(request.id) ||
    !['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method) || typeof request.path !== 'string' || request.path.length > 8192 ||
    !request.path.startsWith('/api/v1/') || /[\x00-\x20\x7f\\#]/.test(request.path) || /%(?:0[0-9a-f]|1[0-9a-f]|7f)/i.test(request.path)) {
    throw new AppError(400, 'invalid_request', '请求协议、方法或路径不正确。');
  }
  if (request.body !== undefined) checkJson(request.body);
}

/** Same application and registered business routes serve both transports. No Django forwarding. */
export class CoreApplication {
  readonly database: CoreDatabase;
  readonly vault: CredentialVault;
  readonly auth: AuthService;
  readonly jobs: JobQueue;
  readonly serviceId: string;
  readonly models: ModelConfigurationService;
  readonly settings: SettingsService;
  readonly knowledge: KnowledgeService;
  readonly searchIndex: SearchIndex;
  readonly documents?: DocumentWorkflow;
  readonly integrations: IntegrationService;
  readonly agents: AgentService;
  readonly memory: MemoryService;
  readonly wiki: WikiService;
  readonly graph: GraphService;
  readonly evaluation: EvaluationService;
  readonly chatUploads: ManagedChatUploads;
  readonly chat: ChatService;
  readonly #routes: Route[] = [];
  readonly #publicRoutes: PublicRoute[] = [];
  readonly #allowAutoSetup: boolean;
  #closing = false;
  #closePromise?: Promise<void>;
  readonly #requests = new Set<Promise<PrivateDispatch>>();
  readonly #controllers = new Set<AbortController>();
  readonly #tasks = new Set<Promise<unknown>>();
  readonly #agentAdapters: ReturnType<typeof createApplicationAgentHooks>;
  readonly #observability: ObservabilityService;
  readonly #legacy: ReturnType<typeof registerLegacyRoutes>;
  constructor(dataRoot: string, options: { allowAutoSetup?: boolean; now?: () => number; parser?: DocumentParser; evaluation?: EvaluationOptions } = {}) {
    this.database = new CoreDatabase(dataRoot);
    this.vault = new CredentialVault(dataRoot);
    this.#allowAutoSetup = options.allowAutoSetup === true;
    this.auth = new AuthService(this.database, options);
    this.jobs = new JobQueue(this.database, options);
    this.serviceId = this.database.transaction(() => {
      const row = this.database.get('select value from desktop_meta where key=?', 'service.identity');
      if (row) return String(JSON.parse(String(row.value)).id);
      const id = randomUUID();
      this.database.run('insert into desktop_meta(key,value) values(?,?)', 'service.identity', JSON.stringify({ id }));
      return id;
    });
    this.route('GET', '/api/v1/auth/me', c => this.auth.me(c.auth));
    this.route('PUT', '/api/v1/auth/me/preferences', c => this.auth.updatePreferences(c.auth, c.body));
    this.route('GET', '/api/v1/auth/devices', c => ({ items: this.auth.listDevices(c.auth) }));
    const services = registerSettingsRoutes(this);
    this.models = services.models; this.settings = services.settings;
    registerSystemRoutes(this, { parser: options.parser });
    this.settings.startup.applyDatabase(this.database);
    const domain = registerKnowledgeRoutes(this);
    this.knowledge = domain.knowledge; this.searchIndex = domain.index;
    this.integrations = new IntegrationService(this.database, this.auth, this.settings);
    this.graph = new GraphService(this.database, this.auth, this.models, this.integrations);
    this.#agentAdapters = createApplicationAgentHooks({ db: this.database, auth: this.auth, graph: this.graph, index: this.searchIndex, integrations: this.integrations });
    this.agents = new AgentService(this.database, this.auth, this.#agentAdapters.hooks);
    this.#observability = new ObservabilityService(this.database, this.auth, this.integrations);
    this.memory = new MemoryService(this.database, this.auth, { models: this.models, graph: this.integrations });
    this.wiki = new WikiService(this.database, this.auth, this.models);
    this.evaluation = new EvaluationService(this.database, this.auth, this.models, this.searchIndex, this.jobs, options.evaluation);
    this.chatUploads = new ManagedChatUploads(this.database, this.auth);
    this.chat = registerChatRoutes(this, options.parser, this.#observability.chatObserver);
    this.#legacy = registerLegacyRoutes(this);
    registerAgentRoutes(this);
    registerWikiRoutes(this);
    registerGraphRoutes(this);
    registerEvaluationRoutes(this);
    if (options.parser) this.documents = new DocumentWorkflow(this.database, this.auth, this.jobs, this.models, this.knowledge, {
      parser: options.parser, index: this.searchIndex,
      scheduler: id => this.runTask(() => this.#observability.observeDocumentJob(id, () => this.jobs.run(id))),
      hooks: { wiki: this.wiki.workflowHook, graph: this.graph.workflowHook },
    });
    registerDocumentRoutes(this);
    this.jobs.recover();
    this.chat.recoverActors();
  }
  route(method: HttpMethod, path: string, handle: RouteHandler): void {
    if (this.#routes.some(route => route.method === method && route.path === path)) throw new Error('Duplicate core route');
    this.#routes.push({ method, path, ...routePattern(path), handle });
  }
  /** Only the existing fixed embed protocol may run before account authentication. */
  publicRoute(method: HttpMethod, path: string, handle: PublicRouteHandler): void {
    if (!PUBLIC_ROUTES.has(`${method} ${path}`)) throw new Error('Public core route is not allowed');
    if (this.#publicRoutes.some(route => route.method === method && route.path === path)) throw new Error('Duplicate public core route');
    this.#publicRoutes.push({ method, path, ...routePattern(path), handle });
  }
  private context(binding: PrivateBinding): AuthContext {
    if (binding.bearer) {
      try { return this.auth.authenticateAccess(binding.bearer, binding.selectedTenant); }
      catch (error) { if (!(error instanceof AuthError)) throw error; return this.auth.authenticateLegacyBearer(binding.bearer, binding.selectedTenant); }
    }
    if (binding.apiKey) return this.auth.authenticateApiKey(binding.apiKey, binding.selectedTenant);
    return this.auth.authenticateAccess(binding.access ?? '', binding.selectedTenant);
  }
  /** Trusted transport preflight; it cannot accept a renderer-supplied AuthContext. */
  authorize(binding: PrivateBinding): AuthContext {
    if (this.#closing) throw new AppError(503, 'app_closing', '应用正在退出。');
    const context = this.context(binding); this.auth.assertCan(context, 'read'); return context;
  }
  runTask<T>(work: () => T | Promise<T>): Promise<T> {
    const pending = this.settings.startup.runTask(() => { if (this.#closing) throw new AppError(503, 'app_closing', '应用正在退出。'); return work(); });
    this.#tasks.add(pending); void pending.finally(() => this.#tasks.delete(pending)).catch(() => {}); return pending;
  }
  dispatch(request: CoreRequest, binding: PrivateBinding, signal?: AbortSignal): Promise<PrivateDispatch> {
    const controller = new AbortController(); this.#controllers.add(controller);
    const pending = this.execute(request, binding, signal ? AbortSignal.any([signal, controller.signal]) : controller.signal).then(result => {
      if (!result.stream) { this.#controllers.delete(controller); return result; }
      const source = result.stream.frames, controllers = this.#controllers;
      result.stream = new CoreStream((async function* () {
        try { if (!controller.signal.aborted) yield* source; }
        finally { controllers.delete(controller); }
      })());
      return result;
    });
    this.#requests.add(pending);
    void pending.finally(() => this.#requests.delete(pending)).catch(() => { this.#controllers.delete(controller); });
    return pending;
  }
  private async execute(request: CoreRequest, binding: PrivateBinding, signal?: AbortSignal): Promise<PrivateDispatch> {
    try {
      validateCoreRequest(request);
      if (this.#closing) throw new AppError(503, 'app_closing', '应用正在退出。');
      const url = new URL(request.path, 'http://core.invalid');
      if (url.origin !== 'http://core.invalid' || !url.pathname.startsWith('/api/v1/')) throw new AppError(400, 'invalid_path', '请求路径不正确。');
      const body = requestObject(request.body);
      const reply = (data: Json, authChange?: PrivateDispatch['authChange']): PrivateDispatch => {
        const publicData = binding.transport === 'ipc' && data && typeof data === 'object' && !Array.isArray(data) && data.auth_mode === 'cookie' ? { ...data, auth_mode: 'ipc' } : data;
        return { response: { protocol: 1, id: request.id, status: 200, body: success(publicData) }, ...(authChange ? { authChange } : {}) };
      };
      const routeReply = (result: RouteResult): PrivateDispatch => {
        if (result instanceof CoreBinary) return { ...reply({ name: result.name, mime_type: result.mimeType, sha256: result.sha256, size_bytes: result.bytes.byteLength }), binary: result };
        if (result instanceof CoreStream) return { ...reply({ streaming: true }), stream: result };
        if (result instanceof CoreCookieResult) return { ...reply(result.data), cookies: result.cookies };
        return reply(result);
      };
      if (request.method === 'GET' && url.pathname === '/api/v1/capabilities') {
        return reply({ service_id: this.serviceId, client_protocol: 1, auth_modes: ['cookie', 'ipc', 'legacy_bearer'], core_language: 'typescript', version: '0.7.0', setup_requires_password: true, setup_required: this.#allowAutoSetup && !this.database.get('select id from users where is_active=1 and deleted_at is null limit 1') });
      }
      if (request.method === 'POST' && ['/api/v1/auth/login', '/api/v1/auth/register', '/api/v1/auth/auto-setup'].includes(url.pathname)) {
        if (body.auth_mode !== undefined && !['cookie', 'device'].includes(String(body.auth_mode))) throw new AppError(400, 'invalid_auth_mode', '新登录必须使用受保护的设备会话。');
        const common = { password: field(body, 'password'), mode: 'device' as const, deviceName: field(body, 'device_name'), clientType: binding.transport === 'ipc' ? 'desktop' as const : 'web' as const };
        const issue = url.pathname.endsWith('/login') ? this.auth.login({ ...common, login: field(body, 'email', 'username') || field(body, 'login') }) :
          url.pathname.endsWith('/register') ? this.auth.register({ ...common, username: field(body, 'username') || undefined, email: field(body, 'email') || undefined }) :
          this.auth.autoSetup({ ...common, username: field(body, 'username') || 'admin', email: field(body, 'email') || 'admin@knowledge.local' });
        return reply(issue.public, { issue, clear: false });
      }
      if (request.method === 'POST' && url.pathname === '/api/v1/auth/refresh') {
        const issue = this.auth.refresh(binding.refresh ?? '');
        return reply(issue.public, { issue, clear: false });
      }
      if (request.method === 'POST' && url.pathname === '/api/v1/auth/logout') {
        try { this.auth.logout(this.context(binding)); }
        catch (error) { if (!(error instanceof AuthError) || error.status !== 401) throw error; if (binding.refresh) this.auth.logoutRefresh(binding.refresh); }
        return reply({}, { clear: true });
      }
      if (request.method === 'POST' && url.pathname === '/api/v1/auth/logout-all') {
        this.auth.logoutAll(this.context(binding)); return reply({}, { clear: true });
      }
      if (request.method === 'POST' && url.pathname === '/api/v1/auth/change-password') {
        this.auth.changePassword(this.context(binding), field(body, 'old_password', 'oldPassword'), field(body, 'new_password', 'newPassword'));
        return reply({}, { clear: true });
      }
      const revoke = /^\/api\/v1\/auth\/devices\/([^/]+)$/.exec(url.pathname);
      if (request.method === 'DELETE' && revoke) {
        const context = this.context(binding); const id = decodeURIComponent(revoke[1]!);
        this.auth.revokeDevice(context, id); return reply({}, id === context.deviceId ? { clear: true } : undefined);
      }
      for (const route of this.#publicRoutes) {
        if (route.method !== request.method) continue;
        const match = route.matcher.exec(url.pathname); if (!match) continue;
        if (binding.transport !== 'http') throw new AppError(404, 'not_found', '接口不存在。');
        const params: Record<string, string> = Object.create(null);
        try { route.names.forEach((name, index) => { params[name] = decodeURIComponent(match[index + 1]!); }); }
        catch { throw new AppError(400, 'invalid_path', '请求路径编码不正确。'); }
        return routeReply(await route.handle({ request, body, query: url.searchParams, params, signal, transport: 'http', origin: binding.origin, bearer: binding.bearer ?? binding.embedToken }));
      }
      for (const route of this.#routes) {
        if (route.method !== request.method) continue;
        const match = route.matcher.exec(url.pathname); if (!match) continue;
        const params: Record<string, string> = Object.create(null);
        try { route.names.forEach((name, index) => { params[name] = decodeURIComponent(match[index + 1]!); }); }
        catch { throw new AppError(400, 'invalid_path', '请求路径编码不正确。'); }
        const auth = this.context(binding); this.auth.assertCan(auth, 'read');
        const result = await route.handle({ auth, request, body, query: url.searchParams, params, signal, transport: binding.transport, upload: binding.upload, localSession: binding.localSession });
        return routeReply(result);
      }
      throw new AppError(404, 'not_found', '接口不存在。');
    } catch (error) { return { response: errorResponse(typeof request?.id === 'string' ? request.id : '', error) }; }
  }
  close(): Promise<void> {
    if (this.#closePromise) return this.#closePromise;
    this.#closing = true;
    this.#closePromise = (async () => {
      for (const controller of this.#controllers) controller.abort();
      const channelClosed = this.#legacy.channels.close();
      const results = await Promise.allSettled([channelClosed, this.documents?.close(), this.chat.close(), this.agents.close(), this.#agentAdapters.close(), this.#observability.close(), this.memory.close(), this.wiki.close(), this.graph.close(), this.evaluation.close(), this.integrations.close(), this.jobs.close()]);
      await Promise.allSettled([...this.#requests, ...this.#tasks]);
      this.database.close();
      if (results.some(result => result.status === 'rejected')) throw new AppError(500, 'shutdown_failed', '应用任务退出失败，请查看诊断。');
    })();
    return this.#closePromise;
  }
}
