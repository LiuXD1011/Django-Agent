import { randomUUID } from 'node:crypto';
import type { AuthContext, JsonObject, ModelCallOptions, ModelConfiguration, ModelUsage } from '../contracts.js';
import type { AuthService } from '../auth/index.js';
import type { CoreDatabase, Row } from '../storage/database.js';
import { CredentialVault, isSecretKey } from '../storage/credentials.js';
import { ModelRuntime, ModelRuntimeError } from '../models/runtime.js';
import { providerTypes } from '../models/providers.js';
import { capability, normalizeThinking } from '../models/thinking.js';
import { canonical, fail, groups, merge, object, protectEndpoint, publicValue, storedType } from './internal.js';
import { usageSummary } from './usage.js';
import { StartupConfiguration } from './startup.js';
import { auditUsage, type UsageOutcome } from './usage-audit.js';

const credentials = ['api_key', 'app_secret', 'token'];
const zeroUsage: ModelUsage = { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, cached_tokens: 0, reasoning_tokens: 0 };
const sampleImage = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aXioAAAAASUVORK5CYII=';

export class ModelConfigurationService {
  private readonly startup: StartupConfiguration;
  constructor(private readonly db: CoreDatabase, private readonly auth: AuthService, private readonly vault: CredentialVault) { this.startup = new StartupConfiguration(db.dataRoot); }
  private row(ctx: AuthContext, id: string, write = false): Row {
    this.auth.assertCan(ctx, write ? 'admin' : 'read');
    const row = this.db.read('models', id);
    if (!row || row.deleted_at != null || String(row.tenant_id) !== ctx.tenantId) fail(404, 'model_not_found', 'Model not found');
    return row;
  }
  private params(row: Row): JsonObject {
    const params = this.vault.decrypt(object(row.parameters));
    if (!params.api_key && (params.apiKey || params.apikey)) params.api_key = params.apiKey || params.apikey!;
    if ((!params.base_url || typeof params.base_url === 'string' && !params.base_url.trim()) && params.baseURL) params.base_url = params.baseURL;
    delete params.apiKey; delete params.apikey; delete params.baseURL; return params;
  }
  private projection(row: Row): JsonObject {
    const params = this.params(row);
    return { ...row, id: String(row.id), type: storedType(row.type), raw_type: row.type!, parameters: publicValue(params),
      credential_fields: Object.fromEntries(credentials.map(key => [key, { configured: Boolean(params[key]) }])),
      credentials_configured: Object.entries(params).some(([k, v]) => isSecretKey(k) && Boolean(v)),
      context_window: row.context_window || 128000, context_window_configured: row.context_window !== null };
  }
  list(ctx: AuthContext, type?: string): JsonObject {
    this.auth.assertCan(ctx, 'read');
    const items = this.db.all('select id from models where tenant_id=? and deleted_at is null order by created_at,id', ctx.tenantId)
      .map(r => this.db.read('models', String(r.id))!).filter(r => !type || storedType(r.type) === canonical(type)).map(r => this.projection(r));
    const counts: JsonObject = {}; for (const item of items) { const group = groups[String(item.type)] ?? String(item.type).toLowerCase(); counts[group] = Number(counts[group] || 0) + 1; }
    return { items, models: items, total: items.length, counts_by_type: counts, bailian: { enabled: false, configured: false } };
  }
  get(ctx: AuthContext, id: string): JsonObject { return this.projection(this.row(ctx, id)); }
  providers(): JsonObject { const items = providerTypes.map(item => ({ ...item, types: [...item.types] })); return { items, providers: structuredClone(items) }; }
  private selectedEmbedding(ctx: AuthContext): string | undefined {
    return this.db.all('select id,type from models where tenant_id=? and deleted_at is null and status=? order by is_default desc,created_at,id', ctx.tenantId, 'active')
      .find(row => storedType(row.type) === 'Embedding')?.id as string | undefined;
  }
  private invalidate(ctx: AuthContext, previous: Row | undefined, next: Row, wasSelected = false): void {
    if ((previous && storedType(previous.type) === 'Embedding') || storedType(next.type) === 'Embedding') {
      // Default changes affect fallback libraries; explicit selection affects the referenced libraries.
      const defaultChanged = !!previous?.is_default || !!next.is_default || wasSelected || this.selectedEmbedding(ctx) === next.id;
      this.db.run(`update search_index_meta set status='needs_rebuild',updated_at=? where tenant_id=? and knowledge_base_id in
        (select id from knowledge_bases where tenant_id=? and deleted_at is null and (embedding_model_id=? or (?=1 and embedding_model_id='')))`,
      new Date().toISOString(), ctx.tenantId, ctx.tenantId, String(next.id), defaultChanged ? 1 : 0);
    }
  }
  private save(ctx: AuthContext, data: JsonObject, previous?: Row): Row {
    object(data); const existing = previous ? this.params(previous) : {};
    const wasSelected = previous !== undefined && this.selectedEmbedding(ctx) === previous.id;
    if (data.parameters !== undefined && Object.hasOwn(object(data.parameters), 'thinking')) fail(400, 'thinking_dedicated_endpoint', 'Use the dedicated thinking endpoint');
    const incoming = data.parameters === undefined ? {} : object(data.parameters);
    const params = merge(existing, incoming);
    if ('baseURL' in incoming && (!('base_url' in incoming) || !incoming.base_url)) params.base_url = incoming.baseURL!;
    delete params.baseURL;
    protectEndpoint(existing, incoming, params);
    const type = canonical(data.type ?? previous?.type);
    const values: Record<string, unknown> = { parameters: this.vault.encrypt(params), type, updated_at: new Date().toISOString() };
    for (const key of ['name', 'display_name', 'source', 'description', 'managed_by', 'status']) {
      const value = data[key] ?? (key === 'display_name' ? data.displayName : undefined);
      if (value !== undefined) {
        if (typeof value !== 'string' || value.length > (key === 'description' ? 16384 : 255)) fail(400, 'invalid_model', 'Invalid model text field');
        values[key] = value;
      }
    }
    if (!previous) { values.id = `model-${randomUUID()}`; values.tenant_id = ctx.tenantId; values.name ??= 'model'; values.source ??= 'openai'; }
    for (const key of ['is_default', 'is_builtin']) if (data[key] !== undefined) { if (typeof data[key] !== 'boolean') fail(400, 'invalid_model', 'Model flags must be boolean'); values[key] = data[key]; }
    if (data.fallback_priority !== undefined) { const n = Number(data.fallback_priority); if (!Number.isSafeInteger(n)) fail(400, 'invalid_model', 'Invalid fallback priority'); values.fallback_priority = n; }
    if (data.context_window !== undefined) {
      const n = data.context_window === null || data.context_window === '' || data.context_window === 0 ? null : Number(data.context_window);
      if (n !== null && (!Number.isSafeInteger(n) || n <= 0)) fail(400, 'invalid_model', 'Context window must be a positive integer or null');
      values.context_window = n;
    }
    if (values.is_default ?? previous?.is_default) for (const row of this.db.all('select id,type from models where tenant_id=? and deleted_at is null', ctx.tenantId)) {
      if (String(row.id) !== String(previous?.id) && storedType(row.type) === type) this.db.update('models', String(row.id), { is_default: false, updated_at: new Date().toISOString() });
    }
    const row = previous ? this.db.update('models', String(previous.id), values)! : this.db.insert('models', values);
    this.invalidate(ctx, previous, row, wasSelected); return row;
  }
  create(ctx: AuthContext, data: JsonObject): JsonObject { this.auth.assertCan(ctx, 'admin'); return this.db.transaction(() => this.projection(this.save(ctx, data))); }
  update(ctx: AuthContext, id: string, data: JsonObject): JsonObject { return this.db.transaction(() => this.projection(this.save(ctx, data, this.row(ctx, id, true)))); }
  delete(ctx: AuthContext, id: string): JsonObject {
    return this.db.transaction(() => { const previous = this.row(ctx, id, true), wasSelected = this.selectedEmbedding(ctx) === id; const next = this.db.update('models', id, { deleted_at: new Date().toISOString(), updated_at: new Date().toISOString() })!; this.invalidate(ctx, previous, next, wasSelected); return {}; });
  }
  credentials(ctx: AuthContext, id: string): JsonObject {
    const params = this.params(this.row(ctx, id)); return { fields: Object.fromEntries(credentials.map(key => [key, { configured: Boolean(params[key]) }])) };
  }
  updateCredentials(ctx: AuthContext, id: string, data: JsonObject): JsonObject {
    const input = object(data.credentials ?? data);
    if (Object.keys(input).some(k => !credentials.includes(k))) fail(400, 'invalid_credential', 'Unknown credential field');
    this.update(ctx, id, { parameters: input }); return this.credentials(ctx, id);
  }
  clearCredential(ctx: AuthContext, id: string, field: string): JsonObject {
    if (!credentials.includes(field)) fail(400, 'invalid_credential', 'Unknown credential field');
    return this.db.transaction(() => {
      const row = this.row(ctx, id, true), params = this.params(row); delete params[field];
      if (field === 'api_key') { delete params.apiKey; delete params.apikey; }
      const next = this.db.update('models', id, { parameters: this.vault.encrypt(params), updated_at: new Date().toISOString() })!;
      this.invalidate(ctx, row, next); return this.credentials(ctx, id);
    });
  }
  /** Trusted core-only object: never serialize this decrypted configuration to a renderer. */
  configuration(ctx: AuthContext, idOrRole: string): ModelConfiguration {
    this.auth.assertCan(ctx, 'read');
    let row = this.db.read('models', idOrRole);
    if (!row) {
      const type = canonical(idOrRole);
      row = this.db.all('select id,type from models where tenant_id=? and deleted_at is null and status=? order by is_default desc,created_at,id', ctx.tenantId, 'active')
        .filter(item => storedType(item.type) === type).map(item => this.db.read('models', String(item.id))!)[0];
    }
    if (!row || row.deleted_at != null || String(row.tenant_id) !== ctx.tenantId || row.status !== 'active') fail(404, 'model_not_found', 'Active model not found');
    const parameters = this.params(row);
    if ([parameters.timeoutMs, parameters.timeout].every(value => value === undefined || value === null || value === '')) parameters.timeoutMs = Number(this.startup.active.model_timeout) * 1000;
    return { id: String(row.id), name: String(row.name), type: canonical(row.type), source: String(row.source), parameters, context_window: row.context_window as number | null };
  }
  runtime(ctx: AuthContext, idOrRole: string): ModelRuntime { return new ModelRuntime(this.configuration(ctx, idOrRole)); }
  thinking(ctx: AuthContext, id: string): JsonObject {
    const row = this.row(ctx, id), params = this.params(row); let editable = true;
    try { this.auth.assertCan(ctx, 'admin'); } catch { editable = false; }
    const tenant = this.db.read('tenants', ctx.tenantId)!; const config = object(tenant.model_thinking_config);
    return { model_id: id, revision: Number(config.revision || 0), editable,
      entries: [{ role: 'model', capability: { ...capability(String(params.base_url ?? params.baseURL ?? ''), String(params.model ?? row.name)) }, policy: params.thinking ?? { mode: 'default', effort: null }, stale: false }] };
  }
  updateThinking(ctx: AuthContext, id: string, input: JsonObject): JsonObject {
    return this.db.transaction(() => {
      const row = this.row(ctx, id, true), params = this.params(row), tenant = this.db.read('tenants', ctx.tenantId)!;
      const config = object(tenant.model_thinking_config), revision = Number(config.revision || 0);
      if (input.revision !== revision) fail(409, 'revision_conflict', 'Configuration changed; refresh and retry');
      if (input.role !== 'model') fail(400, 'invalid_thinking', 'Select a role used by this model');
      let policy;
      try { policy = normalizeThinking(object(input.policy), capability(String(params.base_url ?? params.baseURL ?? ''), String(params.model ?? row.name))); }
      catch { return fail(400, 'invalid_thinking', 'Unsupported thinking policy for this endpoint and model'); }
      this.db.update('tenants', ctx.tenantId, { model_thinking_config: { ...config, revision: revision + 1 }, updated_at: new Date().toISOString() });
      this.db.update('models', id, { parameters: this.vault.encrypt({ ...params, thinking: { ...policy } }), updated_at: new Date().toISOString() });
      return this.thinking(ctx, id);
    });
  }
  async test(ctx: AuthContext, id: string, options: ModelCallOptions = {}): Promise<JsonObject> {
    const row = this.row(ctx, id, true), started = Date.now(); let usage = { ...zeroUsage }, success = false, errorCode = '', details: JsonObject = {};
    try {
      const cfg = this.configuration(ctx, id);
      if (!['local', 'ollama'].includes(cfg.source) && ![cfg.parameters.api_key, cfg.parameters.apiKey, cfg.parameters.token].some(v => typeof v === 'string' && v.trim())) fail(400, 'model_not_configured', 'Save model credentials before testing');
      const runtime = new ModelRuntime(cfg);
      if (cfg.type === 'Embedding') { const result = await runtime.embed(['Marlin connectivity check'], options); usage = result.usage; details = { dimension: result.vectors[0]!.length }; }
      else if (cfg.type === 'Rerank') { const result = await runtime.rerank('connectivity', ['Marlin connectivity check', 'unrelated sample'], options); usage = result.usage; details = { documents: result.results.length }; }
      else { const result = cfg.type === 'VLLM' ? await runtime.vision(sampleImage, 'Describe this small test image briefly.', { ...options, maxTokens: 16 }) : await runtime.complete([{ role: 'user', content: 'Reply OK for connectivity check.' }], { ...options, maxTokens: 16 }); usage = result.usage; }
      this.auth.assertCan(ctx, 'admin'); success = true;
      return { status: 'ok', model_id: id, model: cfg.name, model_type: cfg.type, latency_ms: Date.now() - started, ...details };
    } catch (error) {
      if (error instanceof ModelRuntimeError) { errorCode = error.code; fail(error.code === 'model_cancelled' ? 499 : 502, error.code, error.message); }
      errorCode = error && typeof error === 'object' && 'code' in error ? String(error.code) : 'model_test_failed';
      if (error && typeof error === 'object' && 'status' in error) throw error;
      return fail(502, 'model_test_failed', 'Model connection test failed; check saved endpoint, model and credentials');
    } finally {
      this.db.insert('model_usage', { tenant_id: ctx.tenantId, model_id: id, model_name: row.name, model_type: canonical(row.type), provider: row.source, scenario: 'model_test', success,
        ...usage, duration_ms: Date.now() - started, error_message: errorCode, metadata: { result_unknown: !success && errorCode !== 'model_not_configured' } });
    }
  }
  usage(ctx: AuthContext, query: JsonObject = {}): JsonObject { this.auth.assertCan(ctx, 'read'); return usageSummary(this.db, ctx.tenantId, query); }
  /** Trusted core-only audit; callers authorize before the actual model request. Never register as a route. */
  recordUsage(ctx: AuthContext, configuration: ModelConfiguration, usage: ModelUsage, outcome: UsageOutcome): JsonObject { return auditUsage(this.db, ctx, configuration, usage, outcome); }
}
