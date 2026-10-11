import { randomUUID } from 'node:crypto';
import type { AuthContext, JsonObject } from '../contracts.js';
import type { AuthService } from '../auth/index.js';
import type { CoreDatabase, Row } from '../storage/database.js';
import { CredentialVault, isSecretKey } from '../storage/credentials.js';
import { clearSecret, endpoint, fail, merge, object, protectEndpoint, publicValue, secretFields } from './internal.js';
import { StartupConfiguration } from './startup.js';

const fields = new Set(['agent_config', 'context_config', 'conversation_config', 'web_search_config', 'parser_engine_config', 'storage_engine_config', 'chat_history_config', 'retrieval_config', 'credentials', 'model_thinking_config']);
const defaults: Record<string, JsonObject> = {
  application: { name: 'Marlin' },
  neo4j: { enabled: false, uri: 'bolt://localhost:7687', username: 'neo4j', password: '' },
  langfuse: { enabled: false, base_url: 'http://localhost:3000', public_key: '', secret_key: '', ui_base_url: '', ui_project_id: '', trace_links_enabled: false, sample_rate: 1, log_content: false, upload_eval_datasets: false, tracing_environment: 'default', orphan_mode: 'skip' },
  local_services: { autostart: false, startup_timeout_seconds: 45, auto_login: false, login_email: '', password: '', local_login_user_id: '' },
};
const providers = new Set(['mcp_services', 'web_search_providers', 'vector_stores', 'system_settings']);

export class SettingsService {
  readonly startup: StartupConfiguration;
  constructor(private readonly db: CoreDatabase, private readonly auth: AuthService, private readonly vault: CredentialVault) { this.startup = new StartupConfiguration(db.dataRoot); }
  private field(key: string): string {
    let normalized = key.replaceAll('-', '_');
    if (normalized === 'prompt_templates') normalized = 'credentials';
    if (!normalized.endsWith('_config') && normalized !== 'credentials') normalized += '_config';
    if (!fields.has(normalized)) fail(404, 'setting_not_found', 'Setting not found');
    return normalized;
  }
  getKV(ctx: AuthContext, key: string): JsonObject {
    this.auth.assertCan(ctx, 'read'); const field = this.field(key), saved = this.db.read('tenants', ctx.tenantId)![field];
    const value = saved ? this.vault.decrypt(object(saved)) : {};
    return { key, field, value: publicValue(value), configured: Object.keys(value).length > 0, fields: secretFields(value) };
  }
  setKV(ctx: AuthContext, key: string, value: JsonObject): JsonObject {
    this.auth.assertCan(ctx, 'admin'); const field = this.field(key);
    if (field === 'model_thinking_config') fail(400, 'thinking_dedicated_endpoint', 'Use the dedicated thinking endpoint');
    return this.db.transaction(() => {
      const saved = this.db.read('tenants', ctx.tenantId)![field], previous = saved ? this.vault.decrypt(object(saved)) : {};
      const next = merge(previous, object(value));
      for (const k of ['base_url', 'url']) if (next[k]) protectEndpoint(previous, value, next, k);
      if (field === 'retrieval_config') {
        for (const key of ['embedding_top_k', 'rerank_top_k', 'keyword_top_k']) if (next[key] !== undefined && (typeof next[key] !== 'number' || !Number.isInteger(next[key]) || next[key] < 1 || next[key] > 1000)) fail(400, 'invalid_retrieval_config', 'Retrieval limits must be integers between 1 and 1000');
        for (const key of ['vector_threshold', 'keyword_threshold', 'rerank_threshold']) if (next[key] !== undefined && (typeof next[key] !== 'number' || next[key] < 0 || next[key] > 1)) fail(400, 'invalid_retrieval_config', 'Retrieval thresholds must be between zero and one');
        if (next.rerank_enabled !== undefined && typeof next.rerank_enabled !== 'boolean') fail(400, 'invalid_retrieval_config', 'Rerank flag must be boolean');
      }
      this.db.update('tenants', ctx.tenantId, { [field]: this.vault.encrypt(next), updated_at: new Date().toISOString() });
      return this.getKV(ctx, key);
    });
  }
  clearKVCredential(ctx: AuthContext, key: string, credential: string): JsonObject {
    this.auth.assertCan(ctx, 'admin'); const field = this.field(key);
    if (field === 'model_thinking_config') fail(400, 'thinking_dedicated_endpoint', 'Use the dedicated thinking endpoint');
    return this.db.transaction(() => {
      const saved = this.db.read('tenants', ctx.tenantId)![field], previous = saved ? this.vault.decrypt(object(saved)) : {};
      this.db.update('tenants', ctx.tenantId, { [field]: this.vault.encrypt(clearSecret(previous, credential)), updated_at: new Date().toISOString() });
      return this.getKV(ctx, key);
    });
  }
  private administrator(ctx: AuthContext): void {
    this.auth.assertCan(ctx, 'read');
    if (!ctx.userId || this.auth.me(ctx).user.is_system_admin !== true) fail(403, 'system_admin_required', 'Only system administrators may manage global integration settings');
  }
  private integration(section: string): JsonObject {
    if (!defaults[section]) fail(404, 'configuration_not_found', 'Configuration not found');
    const row = this.db.read('integration_configs', section);
    return { ...defaults[section], ...(row && row.deleted_at == null ? this.vault.decrypt(object(row.parameters)) : {}) };
  }
  getIntegration(ctx: AuthContext, section: string): JsonObject {
    this.administrator(ctx); if (section === 'startup') return this.startup.projection(this.db.path);
    const value = this.integration(section);
    return { values: publicValue(value), fields: secretFields(value), restart_required: section === 'local_services' };
  }
  updateIntegration(ctx: AuthContext, section: string, changes: JsonObject): JsonObject {
    this.administrator(ctx); object(changes);
    if (section === 'startup') return this.startup.update(changes, this.db.path);
    return this.db.transaction(() => {
      const previous = this.integration(section), schema = defaults[section]!;
      for (const [field, value] of Object.entries(changes)) {
        if (!(field in schema)) fail(400, 'invalid_configuration', 'Unknown configuration field');
        if (isSecretKey(field) && (value === null || value === '' || value === '******')) continue;
        const expected = typeof schema[field];
        if (typeof value !== expected || (typeof value === 'string' && (value.length > 4096 || value.startsWith('enc:v1:')))) fail(400, 'invalid_configuration', 'Invalid configuration field');
        if (field === 'sample_rate' && (Number(value) < 0 || Number(value) > 1 || !Number.isFinite(value))) fail(400, 'invalid_configuration', 'Sample rate must be between zero and one');
        if (field === 'startup_timeout_seconds' && (Number(value) < 1 || Number(value) > 120 || !Number.isFinite(value))) fail(400, 'invalid_configuration', 'Startup timeout must be between 1 and 120 seconds');
        if (['base_url', 'uri', 'ui_base_url'].includes(field) && (value || field !== 'ui_base_url')) endpoint(value, field === 'uri');
        if (field === 'orphan_mode' && !['skip', 'standalone'].includes(String(value))) fail(400, 'invalid_configuration', 'Invalid orphan mode');
        if (field === 'name' && !String(value).trim()) fail(400, 'invalid_configuration', 'Application name is required');
      }
      const next = merge(previous, changes);
      if (section === 'neo4j') protectEndpoint(previous, changes, next, 'uri', ['password'], true);
      if (section === 'langfuse') protectEndpoint(previous, changes, next, 'base_url', ['public_key', 'secret_key']);
      if (section === 'neo4j' && next.enabled && !['uri', 'username', 'password'].every(k => next[k])) fail(400, 'integration_not_configured', 'Save Neo4j endpoint, username and password before enabling');
      if (section === 'langfuse' && next.enabled && !['base_url', 'public_key', 'secret_key'].every(k => next[k])) fail(400, 'integration_not_configured', 'Save Langfuse endpoint and credentials before enabling');
      if (section === 'local_services' && next.auto_login && !['login_email', 'password'].every(k => next[k])) fail(400, 'integration_not_configured', 'Automatic login requires an account and password');
      this.storeIntegration(section, next); return this.getIntegration(ctx, section);
    });
  }
  private storeIntegration(section: string, parameters: JsonObject): void {
    const values = { parameters: this.vault.encrypt(parameters), updated_at: new Date().toISOString(), deleted_at: null };
    if (this.db.read('integration_configs', section)) this.db.update('integration_configs', section, values);
    else this.db.insert('integration_configs', { name: section, ...values });
  }
  clearIntegrationCredential(ctx: AuthContext, section: string, field?: string): JsonObject {
    this.administrator(ctx);
    if (section === 'startup') fail(405, 'startup_save_required', 'Use save to update startup configuration');
    return this.db.transaction(() => {
      const previous = this.integration(section), secrets = Object.keys(defaults[section]!).filter(isSecretKey);
      if (field !== undefined && !secrets.includes(field)) fail(400, 'invalid_credential', 'Unknown credential field');
      if (field === undefined && section !== 'langfuse') fail(400, 'invalid_credential', 'Specify the credential field to clear');
      for (const key of field === undefined ? secrets : [field]) previous[key] = '';
      if (section === 'local_services') previous.auto_login = false; else previous.enabled = false;
      this.storeIntegration(section, previous); return this.getIntegration(ctx, section);
    });
  }
  langfuseCredentials(ctx: AuthContext): JsonObject {
    const data = this.getIntegration(ctx, 'langfuse'), values = data.values as JsonObject;
    return { enabled: values.enabled!, base_url: values.base_url!, fields: data.fields! };
  }
  testIntegration(ctx: AuthContext, section: string): never { this.administrator(ctx); this.integration(section); return fail(501, 'integration_test_unavailable', 'Connection testing requires the integration adapter'); }
  private providerType(ctx: AuthContext, type: string, write = false): void {
    if (!providers.has(type)) fail(404, 'provider_not_found', 'Provider type not found');
    this.auth.assertCan(ctx, write ? 'admin' : 'read'); if (type === 'system_settings') this.administrator(ctx);
  }
  private providerRow(ctx: AuthContext, type: string, id: string, write = false): Row {
    this.providerType(ctx, type, write); const row = this.db.read('generic_resources', id);
    if (!row || row.deleted_at != null || String(row.tenant_id) !== ctx.tenantId || row.resource_type !== type) fail(404, 'provider_not_found', 'Provider not found');
    return row;
  }
  private providerProjection(row: Row): JsonObject {
    const data = this.vault.decrypt(object(row.data));
    return { ...publicValue(data), id: row.id!, tenant_id: row.tenant_id!, name: row.name!, status: row.status!, created_at: row.created_at!, updated_at: row.updated_at!, credential_fields: secretFields(data), credentials_configured: Object.values(secretFields(data)).some(f => f.configured) };
  }
  listProviders(ctx: AuthContext, type: string): JsonObject {
    this.providerType(ctx, type);
    const items = this.db.all('select id from generic_resources where tenant_id=? and resource_type=? and deleted_at is null order by created_at,id', ctx.tenantId, type).map(r => this.providerProjection(this.db.read('generic_resources', String(r.id))!));
    return { items, total: items.length };
  }
  getProvider(ctx: AuthContext, type: string, id: string): JsonObject { return this.providerProjection(this.providerRow(ctx, type, id)); }
  providerCredentials(ctx: AuthContext, type: string, id: string): JsonObject {
    const row = this.providerRow(ctx, type, id), data = this.vault.decrypt(object(row.data));
    return { fields: { api_key: { configured: Boolean(data.api_key || data.apiKey || data.apikey) }, app_secret: { configured: Boolean(data.app_secret) }, token: { configured: Boolean(data.token) }, ...secretFields(data) } };
  }
  updateProviderCredentials(ctx: AuthContext, type: string, id: string, credentials: JsonObject): JsonObject {
    const incoming = object(credentials.credentials ?? credentials);
    if (Object.keys(incoming).some(key => !isSecretKey(key))) fail(400, 'invalid_credential', 'Unknown credential field');
    this.updateProvider(ctx, type, id, incoming); return this.providerCredentials(ctx, type, id);
  }
  clearProviderCredential(ctx: AuthContext, type: string, id: string, credential: string): JsonObject {
    return this.db.transaction(() => {
      const row = this.providerRow(ctx, type, id, true), data = this.vault.decrypt(object(row.data));
      this.db.update('generic_resources', id, { data: this.vault.encrypt(clearSecret(data, credential)), updated_at: new Date().toISOString() });
      return this.providerCredentials(ctx, type, id);
    });
  }
  createProvider(ctx: AuthContext, type: string, data: JsonObject): JsonObject {
    this.providerType(ctx, type, true); const values = merge({}, object(data));
    for (const key of ['url', 'base_url']) if (values[key]) endpoint(values[key]);
    if (typeof values.name !== 'string' || !values.name.trim()) fail(400, 'invalid_provider', 'Provider name is required');
    return this.db.transaction(() => this.providerProjection(this.db.insert('generic_resources', { id: randomUUID(), tenant_id: ctx.tenantId, resource_type: type, name: values.name, data: this.vault.encrypt(values), status: String(values.status || 'active') })));
  }
  updateProvider(ctx: AuthContext, type: string, id: string, changes: JsonObject): JsonObject {
    return this.db.transaction(() => {
      const row = this.providerRow(ctx, type, id, true), previous = this.vault.decrypt(object(row.data)), next = merge(previous, object(changes));
      for (const key of ['url', 'base_url']) if (next[key]) protectEndpoint(previous, changes, next, key);
      return this.providerProjection(this.db.update('generic_resources', id, { name: String(next.name || row.name), status: String(next.status || row.status), data: this.vault.encrypt(next), updated_at: new Date().toISOString() })!);
    });
  }
  deleteProvider(ctx: AuthContext, type: string, id: string): JsonObject { return this.db.transaction(() => { this.providerRow(ctx, type, id, true); this.db.update('generic_resources', id, { deleted_at: new Date().toISOString(), updated_at: new Date().toISOString() }); return {}; }); }
  testProvider(ctx: AuthContext, type: string, id: string): never { this.providerRow(ctx, type, id, true); return fail(501, 'provider_test_unavailable', 'Connection testing requires the provider integration adapter'); }
}
