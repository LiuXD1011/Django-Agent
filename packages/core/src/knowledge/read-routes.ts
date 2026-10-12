import type { AuthContext, Json } from '../contracts.js';
import type { KnowledgeQueries } from './read-queries.js';

export interface ReadRouteContext {
  auth: AuthContext;
  params: Record<string, string>;
  query: URLSearchParams;
}
export interface ReadRouteRegistrar {
  route(method: 'GET', path: string, handle: (context: ReadRouteContext) => Json): void;
}

/** One registration source for owner and readonly dispatcher; handlers stay synchronous. */
export function registerKnowledgeReadRoutes(registrar: ReadRouteRegistrar, knowledge: KnowledgeQueries): void {
  const bases = knowledge.knowledgeBases;
  registrar.route('GET', '/api/v1/knowledge-bases', c => bases.list(c.auth, Object.fromEntries(c.query)));
  registrar.route('GET', '/api/v1/knowledge-bases/:id', c => bases.get(c.auth, c.params.id!));
  registrar.route('GET', '/api/v1/knowledge-bases/:id/move-targets', c => bases.moveTargets(c.auth, c.params.id!));
  registrar.route('GET', '/api/v1/knowledge-bases/:id/knowledge', c => knowledge.list(c.auth, c.params.id!, Object.fromEntries(c.query)));
  registrar.route('GET', '/api/v1/knowledge-bases/:id/knowledge/stats', c => knowledge.stats(c.auth, c.params.id!));
  registrar.route('GET', '/api/v1/knowledge/batch', c => knowledge.batch(c.auth, c.query.get('ids') ?? ''));
  registrar.route('GET', '/api/v1/knowledge/search', c => knowledge.list(c.auth, undefined, Object.fromEntries(c.query)));
  registrar.route('GET', '/api/v1/knowledge/:id', c => knowledge.get(c.auth, c.params.id!));
  registrar.route('GET', '/api/v1/chunks/by-id/:chunk', c => knowledge.getChunk(c.auth, c.params.chunk!));
  registrar.route('GET', '/api/v1/chunks/:id', c => knowledge.listChunks(c.auth, c.params.id!, Object.fromEntries(c.query)));
  registrar.route('GET', '/api/v1/chunks/:id/:chunk', c => knowledge.getChunk(c.auth, c.params.chunk!, c.params.id!));
  registrar.route('GET', '/api/v1/knowledge-bases/:id/tags', c => knowledge.listTags(c.auth, c.params.id!));
  registrar.route('GET', '/api/v1/knowledge-bases/:id/tags/:tag', c => knowledge.getTag(c.auth, c.params.id!, c.params.tag!));
}
