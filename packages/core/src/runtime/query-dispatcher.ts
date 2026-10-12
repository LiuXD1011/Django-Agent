import { errorResponse, success, validateCoreRequest } from '../application.js';
import { AuthError, AuthReader } from '../auth/reader.js';
import type { CoreRequest, CoreResponse, Json } from '../contracts.js';
import { registerDocumentReadRoutes } from '../documents/stages-query.js';
import { AppError } from '../errors.js';
import { KnowledgeReadDomain } from '../knowledge/read-domain.js';
import { KnowledgeQueries } from '../knowledge/read-queries.js';
import { registerKnowledgeReadRoutes, type ReadRouteContext } from '../knowledge/read-routes.js';
import { coreRequestUrl, requestObject, routePattern } from '../routing.js';
import type { ReadDatabase } from '../storage/read-database.js';
import type { QueryBinding } from './query-contracts.js';
import { readCancelProjection, type CancelTarget } from './document-cancel-preflight.js';

const readPaths = [
  '/api/v1/auth/me', '/api/v1/auth/devices',
  '/api/v1/knowledge-bases', '/api/v1/knowledge-bases/:id', '/api/v1/knowledge-bases/:id/move-targets',
  '/api/v1/knowledge-bases/:id/knowledge', '/api/v1/knowledge-bases/:id/knowledge/stats',
  '/api/v1/knowledge/batch', '/api/v1/knowledge/search', '/api/v1/knowledge/:id',
  '/api/v1/chunks/by-id/:chunk', '/api/v1/chunks/:id', '/api/v1/chunks/:id/:chunk',
  '/api/v1/knowledge-bases/:id/tags', '/api/v1/knowledge-bases/:id/tags/:tag', '/api/v1/knowledge/:id/stages',
];
const readMatchers = readPaths.map(path => routePattern(path).matcher);
/** Fail closed: new GET capabilities stay on the owner until explicitly audited. */
export function isQueryRequest(request: CoreRequest): boolean {
  return request.method === 'GET' && readMatchers.some(matcher => matcher.test(coreRequestUrl(request.path).pathname));
}
interface ReadRoute { path: string; matcher: RegExp; names: string[]; handle(context: ReadRouteContext): Json }
export class QueryDispatcher {
  readonly #auth: AuthReader;
  readonly #routes: ReadRoute[] = [];
  constructor(readonly database: ReadDatabase, readonly parserEnabled: boolean) {
    this.#auth = new AuthReader(database);
    const domain = new KnowledgeReadDomain(database, this.#auth), knowledge = new KnowledgeQueries(domain);
    const registrar = { route: (_method: 'GET', path: string, handle: (context: ReadRouteContext) => Json) => {
      this.#routes.push({ path, ...routePattern(path), handle });
    } };
    registrar.route('GET', '/api/v1/auth/me', c => this.#auth.me(c.auth));
    registrar.route('GET', '/api/v1/auth/devices', c => ({ items: this.#auth.listDevices(c.auth) }));
    registerKnowledgeReadRoutes(registrar, knowledge);
    registerDocumentReadRoutes(registrar, domain, { parserEnabled });
    if (this.#routes.length !== readPaths.length || this.#routes.some(route => !readPaths.includes(route.path))) throw new Error('Readonly route audit is incomplete');
  }
  private authorize(binding: QueryBinding) {
    if (binding.bearer) {
      try { return this.#auth.authenticateAccess(binding.bearer, binding.selectedTenant); }
      catch (error) { if (!(error instanceof AuthError)) throw error; return this.#auth.authenticateLegacyBearer(binding.bearer, binding.selectedTenant); }
    }
    if (binding.apiKey) return this.#auth.authenticateApiKey(binding.apiKey, binding.selectedTenant);
    return this.#auth.authenticateAccess(binding.access ?? '', binding.selectedTenant);
  }
  cancelPreflight(request: CoreRequest, binding: QueryBinding): { response: CoreResponse; target?: CancelTarget } {
    try {
      validateCoreRequest(request); requestObject(request.body);
      return this.database.snapshot(() => {
        const auth = this.authorize(binding);
        this.#auth.assertCan(auth, 'read');
        if (!this.parserEnabled) throw new AppError(503, 'parser_not_configured', '文档解析器尚未配置，请检查应用运行环境。');
        const projection = readCancelProjection(this.database, this.#auth, auth, request);
        return { response: { protocol: 1, id: request.id, status: 200, body: success(projection.noJob ?? {}) }, ...(projection.target ? { target: projection.target } : {}) };
      });
    } catch (error) { return { response: errorResponse(typeof request?.id === 'string' ? request.id : '', error) }; }
  }
  dispatch(request: CoreRequest, binding: QueryBinding): CoreResponse {
    try {
      validateCoreRequest(request); requestObject(request.body);
      if (!isQueryRequest(request)) throw new AppError(404, 'not_found', '接口不存在。');
      const url = coreRequestUrl(request.path);
      const route = this.#routes.find(route => route.matcher.test(url.pathname));
      if (!route) throw new AppError(404, 'not_found', '接口不存在。');
      const params: Record<string, string> = Object.create(null), match = route.matcher.exec(url.pathname)!;
      try { route.names.forEach((name, index) => { params[name] = decodeURIComponent(match[index + 1]!); }); }
      catch { throw new AppError(400, 'invalid_path', '请求路径编码不正确。'); }
      return this.database.snapshot(() => {
        const auth = this.authorize(binding);
        this.#auth.assertCan(auth, 'read');
        const result = route.handle({ auth, query: url.searchParams, params });
        const data = binding.transport === 'ipc' && result && typeof result === 'object' && !Array.isArray(result) && result.auth_mode === 'cookie' ? { ...result, auth_mode: 'ipc' } : result;
        return { protocol: 1, id: request.id, status: 200, body: success(data) };
      });
    } catch (error) { return errorResponse(typeof request?.id === 'string' ? request.id : '', error); }
  }
}
