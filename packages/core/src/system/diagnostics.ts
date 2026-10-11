import { lstatSync } from 'node:fs';
import { createHash } from 'node:crypto';
import type { AuthService } from '../auth/index.js';
import type { AuthContext, Json, JsonObject } from '../contracts.js';
import { AppError } from '../errors.js';
import { ParserError, type DocumentParser } from '../documents/parser.js';
import { embeddingBinding } from '../documents/pipeline.js';
import { ModelRuntimeError, resolveProvider } from '../models/providers.js';
import type { ModelConfigurationService } from '../settings/model-configuration.js';
import type { CoreDatabase } from '../storage/database.js';
import type { CredentialVault } from '../storage/credentials.js';

export interface SystemDiagnosticOptions { parser?: DocumentParser; }
const object = (value: Json | undefined): JsonObject => value && typeof value === 'object' && !Array.isArray(value) ? value : {};
const positiveInteger = (value: Json | undefined): number | null => typeof value === 'number' && Number.isSafeInteger(value) && value > 0 ? value : null;
const dependencies = ['PyMuPDF', 'Pillow', 'python-docx', 'python-pptx', 'CairoSVG', 'openpyxl', 'xlrd', 'msoffcrypto-tool', 'requests', 'LibreOffice'];
const capabilities = ['text_extraction', 'embedded_images', 'tables', 'records', 'scanned_pdf_rendering', 'remote_image_localization'];

/** Read-only diagnostics. No caller-supplied SQL, paths, endpoints or external model calls. */
export class SystemDiagnostics {
  constructor(private readonly db: CoreDatabase, private readonly auth: AuthService, private readonly vault: CredentialVault, private readonly models: ModelConfigurationService, private readonly options: SystemDiagnosticOptions = {}) {}

  async parserEngines(ctx: AuthContext, options: { signal?: AbortSignal } = {}): Promise<JsonObject> {
    this.auth.assertCan(ctx, 'read');
    const missing: JsonObject = { name: 'builtin', display_name: 'Builtin Multimodal Python Parser', available: false, enabled: false, status: 'not_configured', parser_version: null, formats: [], format_status: {}, dependencies: [], dependency_status: {}, capabilities: [], ocr_available: false, caption_available: false, vlm_available: this.modelState(ctx, 'VLLM').configured === true };
    if (!this.options.parser) return { items: [missing] };
    let value: JsonObject;
    try { value = await this.options.parser.capabilities({ signal: options.signal }); }
    catch (error) {
      this.auth.assertCan(ctx, 'read');
      if (options.signal?.aborted || error instanceof ParserError && error.code === 'parser_cancelled') throw new AppError(409, 'diagnostic_cancelled', '解析器检查已取消。');
      const code = error instanceof ParserError && /^[a-z0-9_]{1,100}$/.test(error.code) ? error.code : 'parser_check_failed';
      return { items: [{ ...missing, status: 'unavailable', error_code: code }] };
    }
    this.auth.assertCan(ctx, 'read');
    if (options.signal?.aborted) throw new AppError(409, 'diagnostic_cancelled', '解析器检查已取消。');
    const formats = Array.isArray(value.formats) ? value.formats.filter((format): format is string => typeof format === 'string' && /^[a-z0-9]{1,16}$/.test(format)) : [];
    const formatStatus = object(value.format_status), dependencyStatus = object(value.dependency_status);
    const actualFormats: JsonObject = Object.fromEntries(formats.map(format => [format, formatStatus[format] === true]));
    const actualDependencies: JsonObject = Object.fromEntries(dependencies.filter(name => Object.hasOwn(dependencyStatus, name)).map(name => [name, dependencyStatus[name] === true]));
    const available = value.available === true && formats.length > 0 && Object.values(actualFormats).some(Boolean);
    const partial = Object.values(actualFormats).some(value => value !== true);
    return { items: [{ ...missing, available, enabled: available, status: available ? partial ? 'partial' : 'available' : 'unavailable',
      parser_version: typeof value.parser_version === 'string' && /^[a-z0-9_.-]{1,100}$/i.test(value.parser_version) ? value.parser_version : null,
      formats, format_status: actualFormats, dependencies: Object.keys(actualDependencies), dependency_status: actualDependencies,
      dependency_versions_status: 'not_reported_by_worker', capabilities: Array.isArray(value.capabilities) ? capabilities.filter(name => (value.capabilities as Json[]).includes(name)) : [],
      ocr_available: value.ocr_available === true, caption_available: value.caption_available === true,
      remote_images: { schemes: ['http', 'https'], public_addresses_only: true },
    }] };
  }

  storageStatus(ctx: AuthContext): JsonObject {
    this.auth.assertCan(ctx, 'read');
    const checks: JsonObject = {};
    let sqliteVersion: Json = null, vectorVersion: Json = null, journalMode: Json = null, busyTimeout: Json = null;
    try {
      checks.integrity = this.db.get('PRAGMA quick_check(1)')?.quick_check === 'ok';
      checks.foreign_key_violations = this.db.get('SELECT count(*) AS n FROM pragma_foreign_key_check')?.n ?? null;
      checks.foreign_keys_enabled = this.db.get('PRAGMA foreign_keys')?.foreign_keys === 1;
      sqliteVersion = this.db.get('SELECT sqlite_version() AS version')?.version ?? null;
      vectorVersion = this.db.get('SELECT vec_version() AS version')?.version ?? null;
      checks.vector_extension = typeof vectorVersion === 'string' && this.db.get("SELECT vec_length('[1,0]') AS n")?.n === 2;
      checks.fts5 = this.db.get("SELECT sqlite_compileoption_used('ENABLE_FTS5') AS enabled")?.enabled === 1 && this.db.get("SELECT count(*) AS n FROM chunks_fts WHERE chunks_fts MATCH ?", 'marlinreadonlydiagnostic') !== undefined;
      journalMode = this.db.get('PRAGMA journal_mode')?.journal_mode ?? null;
      busyTimeout = this.db.get('PRAGMA busy_timeout')?.timeout ?? null;
      checks.schema_version = this.db.get('SELECT max(version) AS version FROM desktop_schema_versions')?.version ?? null;
    } catch { checks.database_probe = false; }
    try { checks.database_file = lstatSync(this.db.path).isFile(); checks.data_directory = lstatSync(this.db.dataRoot).isDirectory(); }
    catch { checks.database_file = false; checks.data_directory = false; }
    const available = checks.integrity === true && checks.foreign_key_violations === 0 && checks.foreign_keys_enabled === true && checks.vector_extension === true && checks.fts5 === true && checks.database_file === true && checks.data_directory === true && checks.database_probe !== false;
    return { provider: 'local', status: available ? 'available' : 'degraded', readonly_check: true, write_probe_performed: false, database: { engine: 'SQLite', version: sqliteVersion, schema_version: checks.schema_version ?? null, journal_mode: journalMode, busy_timeout_ms: busyTimeout, connection_open: this.db.sqlite.open }, vector: { engine: 'sqlite-vec', version: vectorVersion }, checks };
  }

  private modelState(ctx: AuthContext, role: string): JsonObject {
    try {
      const cfg = this.models.configuration(ctx, role), params = cfg.parameters;
      const provider = resolveProvider(cfg);
      const configured = ['local', 'ollama'].includes(cfg.source) || Boolean(params.api_key || params.token);
      const dimension = provider.dimension ?? null;
      return { configured, dimension, state: configured ? 'configured_unverified' : 'needs_credentials' };
    } catch (error) {
      if (error instanceof ModelRuntimeError) return { configured: false, dimension: null, state: 'invalid_configuration' };
      if (!(error instanceof AppError) || error.code !== 'model_not_found') throw error;
      return { configured: false, dimension: null, state: 'not_configured' };
    }
  }

  info(ctx: AuthContext): JsonObject {
    this.auth.assertCan(ctx, 'read');
    const application = object(this.db.read('integration_configs', 'application')?.parameters);
    let graph: JsonObject = {}, credentialsAvailable = true;
    try { graph = object(this.vault.decrypt(object(this.db.read('integration_configs', 'neo4j')?.parameters))); }
    catch { credentialsAvailable = false; }
    let endpointValid = false;
    try { const uri = new URL(String(graph.uri)); endpointValid = ['bolt:', 'bolt+s:', 'bolt+ssc:', 'neo4j:', 'neo4j+s:', 'neo4j+ssc:'].includes(uri.protocol) && !!uri.hostname && !uri.username && !uri.password && !uri.search && !uri.hash; } catch {}
    const configured = credentialsAvailable && graph.enabled === true && endpointValid && Boolean(graph.username && graph.password);
    const embedding = this.modelState(ctx, 'Embedding');
    const indices = this.db.all("SELECT m.* FROM search_index_meta m JOIN knowledge_bases b ON b.id=m.knowledge_base_id AND b.tenant_id=m.tenant_id WHERE m.tenant_id=? AND m.status='ready' AND m.id LIKE 'active:%' AND b.deleted_at IS NULL", ctx.tenantId);
    const dimensions = [...new Set(indices.map(row => row.dimension!).filter(value => positiveInteger(value) !== null))].sort((a, b) => Number(a) - Number(b));
    const indexedDimension = dimensions.length === 1 ? dimensions[0]! : null;
    let dimensionVerified = false;
    try {
      const binding = embeddingBinding(this.models.configuration(ctx, 'Embedding'));
      dimensionVerified = embedding.configured === true && indices.some(row => {
        if (row.model_signature !== binding.signature || row.dimension !== binding.dimension) return false;
        const table = `retrieval_vec_${createHash('sha256').update(JSON.stringify([binding.signature, binding.dimension, row.generation])).digest('hex').slice(0, 32)}`;
        if (!this.db.get("SELECT name FROM sqlite_master WHERE type='table' AND name=?", table)) return false;
        return this.db.get(`SELECT vec_length(embedding) AS n FROM ${table} LIMIT 1`)?.n === binding.dimension;
      });
    } catch (error) { if (!(error instanceof AppError && error.code === 'model_not_found') && !(error instanceof ModelRuntimeError)) throw error; }
    const graphBase = this.db.all('SELECT indexing_strategy FROM knowledge_bases WHERE tenant_id=? AND deleted_at IS NULL', ctx.tenantId).some(row => { try { return object(JSON.parse(String(row.indexing_strategy))).graph_enabled === true; } catch { return false; } });
    return { name: typeof application.name === 'string' ? application.name : 'Marlin', edition: 'desktop-typescript', version: '0.7.0', storage: 'SQLite + filesystem', cache: 'SQLite', vector: 'sqlite-vec',
      graph_database_engine: configured ? 'neo4j' : 'Not Enabled', graph_rag_enabled: configured && graphBase && this.modelState(ctx, 'KnowledgeQA').configured === true,
      neo4j_configured: configured, graph_adapter_status: !credentialsAvailable ? 'credentials_unavailable' : configured ? 'configured_unverified' : graph.enabled === true ? 'not_configured' : 'disabled', graph_connection_verified: false,
      bailian: { enabled: false, configured: false, local_embedding_dimension: embedding.dimension ?? null },
      embedding: { ...embedding, indexed_dimension: indexedDimension, indexed_dimensions: dimensions, dimension_verified: dimensionVerified },
      storage_status: this.storageStatus(ctx),
    };
  }
}
