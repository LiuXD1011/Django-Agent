import type { AuthService } from '../auth/index.js';
import type { AuthContext, JsonObject } from '../contracts.js';
import type { JobQueue } from '../jobs/queue.js';
import type { SearchIndex } from '../retrieval/search-index.js';
import { CredentialVault } from '../storage/credentials.js';
import type { CoreDatabase, Row } from '../storage/database.js';
import { chunking, defaultChunking, defaultExtract, effectiveChunking, enabled, fail, indexing, input, object, projectedChunking, text, validateExtract, type Page } from './config.js';
import { KnowledgeDomain, now, warning } from './domain.js';
import { KnowledgeBaseQueries } from './read-queries.js';
import { invalidateEvaluations } from './derived.js';
import { cleanRetiredDocuments, deleteDocuments } from './lifecycle.js';
import { recoverCleanup } from './artifacts.js';

const jsonFields = ['image_processing_config', 'cos_config', 'storage_provider_config', 'vlm_config', 'asr_config', 'extract_config', 'faq_config', 'question_generation_config', 'wiki_config'];
export class KnowledgeBaseService {
  private readonly domain: KnowledgeDomain;
  readonly queries: KnowledgeBaseQueries;
  constructor(db: CoreDatabase, auth: AuthService, index?: SearchIndex, jobs?: JobQueue, domain?: KnowledgeDomain) { this.domain = domain ?? new KnowledgeDomain(db, auth, index, jobs); this.queries = new KnowledgeBaseQueries(this.domain); }
  private values(data: JsonObject, existing?: Row): Record<string, unknown> {
    const config = data.config ? input(data.config) : data, type = data.type ?? existing?.type ?? 'document';
    if (type === 'faq') fail(400, 'unsupported_knowledge_base_type', 'FAQ knowledge bases are no longer supported');
    if (!['document', 'wiki'].includes(String(type))) fail(400, 'unsupported_knowledge_base_type', 'Unsupported knowledge base type');
    const strategy = indexing(config.indexing_strategy ?? existing?.indexing_strategy, String(type));
    if (!Object.values(strategy).some(Boolean)) fail(400, 'invalid_indexing_strategy', 'At least one indexing strategy must be enabled');
    let extract = config.extract_config ?? existing?.extract_config ?? null;
    if (strategy.graph_enabled) extract = { ...defaultExtract, ...object(extract), enabled: true };
    else if (extract && typeof extract === 'object' && !Array.isArray(extract)) extract = { ...extract, enabled: false };
    validateExtract(extract);
    const values: Record<string, unknown> = { type: 'document', indexing_strategy: strategy, extract_config: extract };
    const vault = new CredentialVault(this.domain.db.dataRoot);
    for (const field of ['name', 'description']) if (field in data) values[field] = text(data[field], field === 'name' ? 255 : 65536);
    for (const field of ['embedding_model_id', 'summary_model_id', 'vector_store_id']) if (field in config) values[field] = text(config[field], 64);
    for (const field of jsonFields) {
      if (!(field in config) || field === 'extract_config') continue;
      const value = config[field];
      if (value === null && !['image_processing_config', 'cos_config', 'vlm_config'].includes(field)) values[field] = null;
      else values[field] = vault.encrypt({ ...object(existing?.[field]), ...input(value) });
    }
    values.extract_config = extract === null ? null : vault.encrypt(extract);
    if (strategy.wiki_enabled && (values.wiki_config ?? existing?.wiki_config) == null) values.wiki_config = {};
    if (!existing || 'chunking_config' in config) {
      const opaque = Object.fromEntries(Object.entries(object(existing?.chunking_config)).filter(([key]) => !(key in defaultChunking)));
      values.chunking_config = vault.encrypt({ ...opaque, ...chunking(config.chunking_config) });
    }
    return values;
  }
  create(ctx: AuthContext, payload: JsonObject = {}): JsonObject {
    const data = input(payload);
    return this.domain.db.transaction(() => {
      this.domain.assert(ctx, 'kb.write'); const values = this.values(data);
      const row = this.domain.db.insert('knowledge_bases', { name: '未命名知识库', tenant_id: ctx.tenantId, creator_id: ctx.userId, image_processing_config: { enable_multimodal: false, model_id: '' }, storage_provider_config: { provider: 'local' }, ...values });
      return this.domain.kbDto(ctx, row);
    });
  }
  get(ctx: AuthContext, id: string): JsonObject { return this.queries.get(ctx, id); }
  list(ctx: AuthContext, query: JsonObject = {}): Page { return this.queries.list(ctx, query); }
  update(ctx: AuthContext, id: string, payload: JsonObject): JsonObject {
    const data = input(payload);
    return this.domain.db.transaction(() => {
      const row = this.domain.kb(ctx, id, 'kb.write'), values = this.values(data, row), documents = this.domain.docs(ctx, id);
      if (values.chunking_config && JSON.stringify(projectedChunking(values.chunking_config).config) !== JSON.stringify(projectedChunking(row.chunking_config).config)) {
        for (const d of documents) {
          const metadata = object(d.metadata);
          if (d.parse_status !== 'completed' || metadata.effective_chunking_config || !object(metadata.chunking_diagnostics).selected_strategy) continue;
          let effective: JsonObject;
          try { effective = effectiveChunking(row.chunking_config, metadata.process_config); } catch { continue; }
          this.domain.db.update('knowledges', String(d.id), { metadata: { ...metadata, effective_chunking_config: effective }, updated_at: now() });
        }
      }
      const embeddingChanged = values.embedding_model_id !== undefined && values.embedding_model_id !== row.embedding_model_id;
      const configChanged = Object.entries(values).some(([field, value]) => field !== 'name' && field !== 'description' && JSON.stringify(value) !== JSON.stringify(row[field]));
      const updated = this.domain.db.update('knowledge_bases', id, { ...values, updated_at: now() })!;
      if (configChanged) {
        this.domain.invalidate(ctx, id);
        if (embeddingChanged) for (const d of documents) this.domain.markDocument(ctx, d, ['vector_rebuild_required']);
        invalidateEvaluations(this.domain, ctx, [id], documents.map(d => String(d.id)));
      }
      return this.domain.kbDto(ctx, updated);
    });
  }
  pin(ctx: AuthContext, id: string, value?: boolean): JsonObject {
    return this.domain.db.transaction(() => {
      const row = this.domain.kb(ctx, id, 'kb.write'), pinned = value === undefined ? !row.is_pinned : enabled(value);
      return this.domain.kbDto(ctx, this.domain.db.update('knowledge_bases', id, { is_pinned: pinned, pinned_at: pinned ? now() : null, updated_at: now() })!);
    });
  }
  copy(ctx: AuthContext, sourceId: string): JsonObject {
    return this.domain.db.transaction(() => {
      const row = this.domain.kb(ctx, sourceId, 'kb.write'), { id: _id, tenant_id: _tenant, created_at: _created, updated_at: _updated, deleted_at: _deleted, is_pinned: _pin, pinned_at: _pinned, creator_id: _creator, is_temporary: _temporary, ...config } = row;
      const copied = this.domain.db.insert('knowledge_bases', { ...config, tenant_id: ctx.tenantId, name: `${row.name} copy`, creator_id: ctx.userId });
      return { knowledge_base: this.domain.kbDto(ctx, copied), task_id: '' };
    });
  }
  moveTargets(ctx: AuthContext, id: string): JsonObject { return this.queries.moveTargets(ctx, id); }
  async delete(ctx: AuthContext, id: string): Promise<JsonObject> {
    this.domain.kb(ctx, id, 'kb.delete'); const documents = this.domain.docs(ctx, id);
    const retired = this.domain.db.all('SELECT id FROM knowledges WHERE tenant_id=? AND knowledge_base_id=? AND deleted_at IS NOT NULL', ctx.tenantId, id).map(row => this.domain.db.read('knowledges', String(row.id))!);
    this.domain.cancel(ctx, [...documents, ...retired], [id]);
    let retiredCleanup: string | undefined;
    const result = await deleteDocuments(this.domain, ctx, documents, true, () => {
      this.domain.kb(ctx, id, 'kb.delete');
      retiredCleanup = cleanRetiredDocuments(this.domain, ctx, retired);
      for (const table of ['wiki_pages', 'wiki_folders', 'wiki_log_entries', 'knowledge_tags']) this.domain.db.run(`DELETE FROM ${table} WHERE tenant_id=? AND knowledge_base_id=?`, ctx.tenantId, id);
      this.domain.db.run('DELETE FROM wiki_pending_ops WHERE tenant_id=? AND scope_id=?', ctx.tenantId, id);
      this.domain.db.run('DELETE FROM search_index_meta WHERE tenant_id=? AND knowledge_base_id=?', ctx.tenantId, id);
      invalidateEvaluations(this.domain, ctx, [id], documents.map(d => String(d.id)));
      this.domain.db.update('knowledge_bases', id, { deleted_at: now(), updated_at: now() });
    });
    return { ...result, warnings: [...(result.warnings as JsonObject[]), ...(retiredCleanup ? recoverCleanup(this.domain, ctx, retiredCleanup) : [])] };
  }
}
