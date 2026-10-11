import { CoreCookieResult, type CoreApplication, type RouteContext } from '../application.js';
import type { JsonObject } from '../contracts.js';
import { AppError } from '../errors.js';
import { ModelConfigurationService, SettingsService } from '../settings/index.js';

function object(value: unknown): JsonObject {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new AppError(400, 'invalid_configuration', '配置必须是 JSON 对象。');
  return value as JsonObject;
}
export function registerSettingsRoutes(app: CoreApplication) {
  const models = new ModelConfigurationService(app.database, app.auth, app.vault);
  const settings = new SettingsService(app.database, app.auth, app.vault);
  app.route('GET', '/api/v1/models/providers', () => models.providers());
  app.route('GET', '/api/v1/models/usage', c => models.usage(c.auth, Object.fromEntries(c.query)));
  app.route('GET', '/api/v1/models', c => models.list(c.auth, c.query.get('type') ?? undefined));
  app.route('POST', '/api/v1/models', c => models.create(c.auth, c.body));
  app.route('GET', '/api/v1/models/:id', c => models.get(c.auth, c.params.id!));
  app.route('PUT', '/api/v1/models/:id', c => models.update(c.auth, c.params.id!, c.body));
  app.route('DELETE', '/api/v1/models/:id', c => models.delete(c.auth, c.params.id!));
  app.route('GET', '/api/v1/models/:id/thinking', c => models.thinking(c.auth, c.params.id!));
  app.route('PUT', '/api/v1/models/:id/thinking', c => models.updateThinking(c.auth, c.params.id!, c.body));
  app.route('GET', '/api/v1/models/:id/credentials', c => models.credentials(c.auth, c.params.id!));
  app.route('PUT', '/api/v1/models/:id/credentials', c => models.updateCredentials(c.auth, c.params.id!, c.body));
  app.route('DELETE', '/api/v1/models/:id/credentials/:field', c => models.clearCredential(c.auth, c.params.id!, c.params.field!));
  app.route('POST', '/api/v1/models/:id/test', c => models.test(c.auth, c.params.id!, { signal: c.signal }));
  app.route('GET', '/api/v1/tenants/kv/:key', c => settings.getKV(c.auth, c.params.key!));
  app.route('PUT', '/api/v1/tenants/kv/:key', c => settings.setKV(c.auth, c.params.key!, object(c.body.value)));
  app.route('GET', '/api/v1/system/config/:section', c => settings.getIntegration(c.auth, c.params.section!));
  app.route('PUT', '/api/v1/system/config/:section', c => settings.updateIntegration(c.auth, c.params.section!, c.body));
  app.route('DELETE', '/api/v1/system/config/:section', c => settings.clearIntegrationCredential(c.auth, c.params.section!, typeof c.body.field === 'string' ? c.body.field : undefined));
  app.route('POST', '/api/v1/system/config/:section/test', c => app.integrations.testIntegration(c.auth, c.params.section!, { signal: c.signal }));
  app.route('DELETE', '/api/v1/tenants/kv/:key/credentials/:field', c => settings.clearKVCredential(c.auth, c.params.key!, c.params.field!));
  app.route('GET', '/api/v1/integrations/langfuse/credentials', c => settings.langfuseCredentials(c.auth));
  app.route('PUT', '/api/v1/integrations/langfuse/credentials', c => settings.updateIntegration(c.auth, 'langfuse', object(c.body.credentials ?? c.body)));
  app.route('DELETE', '/api/v1/integrations/langfuse/credentials', c => settings.clearIntegrationCredential(c.auth, 'langfuse'));
  app.route('GET', '/api/v1/observability/langfuse/status', c => app.integrations.langfuseStatus(c.auth, { signal: c.signal }));
  const sessionOptions = (c: RouteContext) => {
    if (!c.localSession) throw new AppError(501, 'local_session_transport_unavailable', '当前传输未配置 Langfuse 本地浏览器会话。');
    return { ...c.localSession, signal: c.signal };
  };
  app.route('POST', '/api/v1/observability/langfuse/session', async c => {
    const result = await app.integrations.langfuseSession(c.auth, sessionOptions(c));
    return new CoreCookieResult(result.result, result.cookies);
  });
  app.route('POST', '/api/v1/observability/langfuse/session/clear', c => {
    const result = app.integrations.clearLangfuseSession(c.auth, sessionOptions(c));
    return new CoreCookieResult(result.result, result.cookies);
  });
  app.route('GET', '/api/v1/vector-stores/types', () => ({ items: [{ type: 'sqlite', name: 'SQLite sqlite-vec', builtin: true }] }));
  app.route('GET', '/api/v1/web-search-providers/types', () => ({ items: ['duckduckgo', 'bing', 'google', 'searxng'].map(provider => ({ provider })) }));
  for (const [path, type] of [['mcp-services', 'mcp_services'], ['web-search-providers', 'web_search_providers'], ['vector-stores', 'vector_stores'], ['system-settings', 'system_settings']] as const) {
    app.route('GET', `/api/v1/${path}`, c => settings.listProviders(c.auth, type));
    app.route('POST', `/api/v1/${path}`, c => settings.createProvider(c.auth, type, c.body));
    app.route('GET', `/api/v1/${path}/:id`, c => settings.getProvider(c.auth, type, c.params.id!));
    app.route('PUT', `/api/v1/${path}/:id`, c => settings.updateProvider(c.auth, type, c.params.id!, c.body));
    app.route('DELETE', `/api/v1/${path}/:id`, c => settings.deleteProvider(c.auth, type, c.params.id!));
    app.route('POST', `/api/v1/${path}/:id/test`, c => app.integrations.testProvider(c.auth, type, c.params.id!, { signal: c.signal }));
    app.route('GET', `/api/v1/${path}/:id/credentials`, c => settings.providerCredentials(c.auth, type, c.params.id!));
    app.route('PUT', `/api/v1/${path}/:id/credentials`, c => settings.updateProviderCredentials(c.auth, type, c.params.id!, c.body));
    app.route('DELETE', `/api/v1/${path}/:id/credentials/:field`, c => settings.clearProviderCredential(c.auth, type, c.params.id!, c.params.field!));
  }
  app.route('GET', '/api/v1/mcp-services/:id/tools', c => app.integrations.listMcpTools(c.auth, c.params.id!, { signal: c.signal }));
  return { models, settings };
}
