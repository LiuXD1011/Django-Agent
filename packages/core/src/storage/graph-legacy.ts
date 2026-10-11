import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync } from 'node:fs';
import { dirname } from 'node:path';
import type { AuthAction, AuthService } from '../auth/index.js';
import type { AuthContext, Json, JsonObject } from '../contracts.js';
import type { IntegrationService, IntegrationCallOptions } from '../integrations/index.js';
import { legacyLabels, legacyReadTemplate } from '../graph/legacy-templates.js';
import { weightGraph, type ExtractedGraph, type GraphNode, type GraphRelation } from '../graph/extraction.js';
import { check, chunks, document, fail, hash, now, object } from '../wiki/internal.js';
import { CoreDatabase, openNativeDatabase, type Row } from './database.js';
import { CredentialVault } from './credentials.js';
import { fileHash, safeDataPath, writePrivateJson } from './files.js';
import { parseStoredJson } from './json.js';
import type { ImportManifest } from './legacy.js';

export interface LegacyGraphPage { phase: 'node' | 'relation'; cursor: string; limit: number }
/** An in-process migration capability, never a serialized renderer request. */
export interface LegacyGraphTicket { readonly kind: 'verified-legacy-graph-source' }
interface TicketState {
  db: CoreDatabase; auth: AuthService; owner: string; ctx: AuthContext;
  importFingerprint: string; manifest: string; configuration: string;
  action: AuthAction;
  kbId: string; docId: string; fingerprint: string; labels: string[]; chunkIds: Set<string>;
  associations: Map<string, { direct: string[]; indirect: string[] }>;
}
const tickets = new WeakMap<LegacyGraphTicket, TicketState>();
const actor = (ctx: AuthContext) => JSON.stringify([ctx.tenantId, ctx.userId, ctx.deviceId]);
const canonical = (value: unknown): string => Array.isArray(value) ? `[${value.map(canonical).join(',')}]` : value && typeof value === 'object' ? `{${Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => `${JSON.stringify(k)}:${canonical(v)}`).join(',')}}` : JSON.stringify(value);
const sha = (value: unknown) => createHash('sha256').update(canonical(value)).digest('hex');
const list = (value: unknown): string[] => Array.isArray(value) ? [...new Set(value.filter((v): v is string => typeof v === 'string' && v.length > 0))] : [];

function sourceMetadata(value: unknown): JsonObject {
  const { graph_relation_chunks: _direct, graph_indirect_relation_chunks: _indirect, ...metadata } = object(typeof value === 'string' ? parseStoredJson(value) : value);
  return metadata;
}

/** Exactly the GraphService source fingerprint, with one scoped SQL read per fence rather than one hydration per chunk per external page. */
function sourceHash(db: CoreDatabase, ctx: AuthContext, kbId: string, doc: Row): string {
  const rows = db.all(`SELECT c.id,c.content,c.chunk_type,c.content_hash,c.metadata FROM chunks c
    JOIN knowledges d ON d.id=c.knowledge_id JOIN knowledge_bases b ON b.id=c.knowledge_base_id
    WHERE c.tenant_id=? AND c.knowledge_base_id=? AND c.knowledge_id=? AND c.tenant_id=d.tenant_id AND d.tenant_id=b.tenant_id
    AND d.knowledge_base_id=c.knowledge_base_id AND b.deleted_at IS NULL AND d.deleted_at IS NULL AND d.enable_status='enabled'
    AND c.deleted_at IS NULL AND c.is_enabled=1 AND c.chunk_type IN ('text','image_ocr','image_caption') ORDER BY c.chunk_index,c.id`, ctx.tenantId, kbId, String(doc.id));
  return hash([doc.id, doc.title, doc.file_name, doc.source, doc.file_hash, doc.enable_status, object(doc.metadata).source_generation ?? null,
    rows.map(row => [row.id, row.content, row.chunk_type, row.content_hash, sourceMetadata(row.metadata)])]);
}

function state(db: CoreDatabase, auth: AuthService, ctx: AuthContext, ticket: LegacyGraphTicket): TicketState {
  const saved = tickets.get(ticket);
  if (!saved || saved.db !== db || saved.auth !== auth || saved.owner !== actor(ctx)) fail(403, 'legacy_graph_ticket_invalid', 'A verified migration source is required');
  auth.assertCan(ctx, saved.action);
  const imported = db.get('SELECT manifest FROM desktop_imports WHERE fingerprint=?', saved.importFingerprint);
  if (imported?.manifest !== saved.manifest) fail(409, 'legacy_graph_import_changed', 'The verified import source changed');
  const doc = document(db, auth, ctx, saved.kbId, saved.docId, saved.action);
  if (doc.enable_status !== 'enabled' || sourceHash(db, ctx, saved.kbId, doc) !== saved.fingerprint) fail(409, 'legacy_graph_source_changed', 'The imported graph source changed');
  if (sha(db.read('integration_configs', 'neo4j')) !== saved.configuration) fail(409, 'legacy_graph_configuration_changed', 'The original graph configuration changed');
  return saved;
}
/** Strict private IntegrationService entry: the template and endpoint are never supplied by the caller. */
export function legacyGraphReadQuery(db: CoreDatabase, auth: AuthService, ctx: AuthContext, ticket: LegacyGraphTicket, page: LegacyGraphPage): { statement: string; parameters: JsonObject } {
  const source = state(db, auth, ctx, ticket);
  if (!page || !['node', 'relation'].includes(page.phase) || typeof page.cursor !== 'string' || page.cursor.length > 1024 || !Number.isInteger(page.limit) || page.limit < 1 || page.limit > 64) fail(400, 'legacy_graph_page_invalid', 'Invalid legacy graph page');
  return { statement: legacyReadTemplate(source.labels, page.phase), parameters: { knowledge_id: source.docId, phase: page.phase, cursor: page.cursor, limit: page.limit } };
}

function plan(db: CoreDatabase, auth: AuthService, ctx: AuthContext, action: 'export' | 'import'): { fingerprint: string; tickets: LegacyGraphTicket[] } {
  auth.assertCan(ctx, action);
  if (action === 'import' && !ctx.userId) fail(403, 'user_principal_required', 'A real signed-in migration account is required');
  const imports = db.all('SELECT fingerprint,manifest FROM desktop_imports ORDER BY fingerprint');
  if (imports.length !== 1) fail(409, 'legacy_graph_import_required', 'Exactly one verified SQLite import is required');
  const fingerprint = String(imports[0]!.fingerprint), raw = String(imports[0]!.manifest);
  const manifest = parseStoredJson(raw) as unknown as ImportManifest;
  if (manifest.protocol !== 1 || manifest.fingerprint !== fingerprint || !/^[a-f0-9]{64}$/.test(fingerprint)) fail(409, 'legacy_graph_import_invalid', 'Invalid SQLite import manifest');
  const archivePath = `archives/legacy-import-${fingerprint.slice(0, 16)}/db.sqlite3`, archived = manifest.files.find(file => file.path === archivePath), path = safeDataPath(db.dataRoot, archivePath);
  if (!archived || !existsSync(path) || fileHash(path) !== archived.sha256) fail(409, 'legacy_graph_archive_invalid', 'The original database archive failed verification');
  const old = openNativeDatabase(path, { readonly: true, fileMustExist: true }); old.defaultSafeIntegers();
  try {
    const saved = db.read('integration_configs', 'neo4j'), original = old.prepare("SELECT parameters,deleted_at FROM integration_configs WHERE name='neo4j'").get() as { parameters: string; deleted_at: unknown } | undefined;
    if (!saved || saved.deleted_at !== null || !original || original.deleted_at !== null) fail(409, 'legacy_graph_configuration_missing', 'The imported source has no active original Neo4j configuration');
    const vault = new CredentialVault(db.dataRoot), current = vault.decrypt(object(saved.parameters)), source = vault.decrypt(object(parseStoredJson(original.parameters)));
    if (sha(current) !== sha(source)) fail(409, 'legacy_graph_configuration_changed', 'The saved Neo4j configuration differs from the import source');
    if (current.enabled !== true || !['uri', 'username', 'password'].every(k => typeof current[k] === 'string' && !!current[k])) fail(409, 'legacy_graph_not_configured', 'The original Neo4j configuration is disabled or incomplete');
    const ids = db.all(`SELECT d.id FROM knowledges d JOIN knowledge_bases b ON b.id=d.knowledge_base_id
      WHERE d.tenant_id=? AND b.tenant_id=d.tenant_id AND b.deleted_at IS NULL AND d.deleted_at IS NULL AND d.enable_status='enabled' ORDER BY d.knowledge_base_id,d.id`, ctx.tenantId);
    const result: LegacyGraphTicket[] = [];
    for (const ref of ids) {
      const doc = db.read('knowledges', String(ref.id))!, kbId = String(doc.knowledge_base_id), docId = String(doc.id);
      const sourceDoc = old.prepare(`SELECT d.* FROM knowledges d JOIN knowledge_bases b ON b.id=d.knowledge_base_id WHERE d.id=? AND d.tenant_id=? AND d.knowledge_base_id=? AND d.tenant_id=b.tenant_id AND b.deleted_at IS NULL AND d.deleted_at IS NULL AND d.enable_status='enabled'`).get(docId, ctx.tenantId, kbId) as Record<string, unknown> | undefined;
      if (!sourceDoc) continue;
      const current = chunks(db, ctx, kbId, docId);
      if (!current.length) continue;
      for (const key of ['title', 'source', 'file_name', 'file_hash']) if ((sourceDoc[key] ?? '') !== doc[key]) fail(409, 'legacy_graph_source_changed', 'An imported document was edited after migration');
      if (object(parseStoredJson(String(sourceDoc.metadata ?? '{}'))).source_generation !== object(doc.metadata).source_generation) fail(409, 'legacy_graph_source_changed', 'An imported document was reparsed after migration');
      const sourceChunks = old.prepare(`SELECT id,content,chunk_type,content_hash,metadata,relation_chunks,indirect_relation_chunks FROM chunks WHERE tenant_id=? AND knowledge_base_id=? AND knowledge_id=? AND deleted_at IS NULL AND is_enabled=1 AND chunk_type IN ('text','image_ocr','image_caption')`).all(ctx.tenantId, kbId, docId) as Array<Record<string, unknown>>;
      const previous = new Map(sourceChunks.map(c => [String(c.id), c]));
      for (const chunk of current) {
        const before = previous.get(String(chunk.id));
        if (!before || before.content !== chunk.content || before.chunk_type !== chunk.chunk_type || (before.content_hash ?? '') !== chunk.content_hash || sha(sourceMetadata(before.metadata)) !== sha(sourceMetadata(chunk.metadata))) fail(409, 'legacy_graph_source_changed', 'An imported graph chunk was edited or replaced');
      }
      const ticket = Object.freeze({ kind: 'verified-legacy-graph-source' as const });
      const originalList = (value: unknown) => list(typeof value === 'string' ? parseStoredJson(value) : value);
      const associations = new Map(current.map(chunk => { const original = previous.get(String(chunk.id))!; return [String(chunk.id), { direct: list(chunk.relation_chunks).filter(id => originalList(original.relation_chunks).includes(id)), indirect: list(chunk.indirect_relation_chunks).filter(id => originalList(original.indirect_relation_chunks).includes(id)) }]; }));
      tickets.set(ticket, { db, auth, owner: actor(ctx), ctx, action, importFingerprint: fingerprint, manifest: raw, configuration: sha(saved), kbId, docId, fingerprint: sourceHash(db, ctx, kbId, doc), labels: legacyLabels(kbId, docId), chunkIds: new Set(current.map(c => String(c.id))), associations });
      result.push(ticket);
    }
    if (!result.length) fail(404, 'legacy_graph_no_sources', 'No current imported graph sources belong to this account and space');
    return { fingerprint, tickets: result };
  } finally { old.close(); }
}

interface ExportedDocument { knowledge_base_id: string; knowledge_id: string; source_fingerprint: string; records: JsonObject[] }
interface ConvertedDocument extends ExportedDocument { graph: ExtractedGraph; warnings: string[] }
/** Published local graph data is validated without the model-output normalizer's truncation or weight reset. */
export function legacySnapshotGraph(data: JsonObject): ExtractedGraph {
  if (!Array.isArray(data.nodes) || !Array.isArray(data.relations)) fail(409, 'legacy_graph_snapshot_invalid', 'Invalid preserved graph snapshot');
  const node: GraphNode[] = data.nodes.map(value => {
    const n = object(value);
    if (typeof n.name !== 'string' || !n.name || typeof n.type !== 'string' || !n.type || !Array.isArray(n.attributes) || n.attributes.some(v => typeof v !== 'string') || !Array.isArray(n.chunks) || n.chunks.some(v => typeof v !== 'string')) fail(409, 'legacy_graph_snapshot_invalid', 'Invalid preserved graph entity');
    return { name: n.name, type: n.type, attributes: list(n.attributes), chunks: list(n.chunks) };
  });
  const relation: GraphRelation[] = data.relations.map(value => {
    const r = object(value);
    if (typeof r.node1 !== 'string' || typeof r.node2 !== 'string' || typeof r.type !== 'string' || !Array.isArray(r.chunks) || r.chunks.some(v => typeof v !== 'string') || typeof r.strength !== 'number' || typeof r.weight !== 'number' || typeof r.combined_degree !== 'number' || ![r.strength, r.weight, r.combined_degree].every(Number.isFinite)) fail(409, 'legacy_graph_snapshot_invalid', 'Invalid preserved graph relationship');
    return { node1: r.node1, node2: r.node2, type: r.type, strength: r.strength, weight: r.weight, combined_degree: r.combined_degree, chunks: list(r.chunks) };
  });
  return { node, relation };
}
export interface LegacyGraphSummary extends JsonObject {
  protocol: 1; state: string; import_fingerprint: string; documents: number; nodes: number; relations: number;
  published_documents: number; exported_nodes: number; exported_relations: number; filtered_nodes: number; filtered_relations: number;
  export_sha256: string; conversion_sha256: string; publication_sha256: string; repeated: boolean; warnings: string[];
}
export type LegacyGraphTransport = (ctx: AuthContext, ticket: LegacyGraphTicket, page: LegacyGraphPage, options: IntegrationCallOptions) => Promise<JsonObject>;
export interface LegacyGraphOptions { transport?: LegacyGraphTransport; pageSize?: number }
/** CLI-only migration. The original Neo4j namespace is exclusively read; all publication is local SQLite. */
export class LegacyGraphMigration {
  private readonly transport: LegacyGraphTransport;
  private readonly pageSize: number;
  constructor(private readonly db: CoreDatabase, private readonly auth: AuthService, integrations: IntegrationService, options: LegacyGraphOptions = {}) {
    this.transport = options.transport ?? ((ctx, ticket, page, opts) => integrations.readLegacyGraph(ctx, ticket, page, opts));
    this.pageSize = options.pageSize ?? 64;
    if (!Number.isInteger(this.pageSize) || this.pageSize < 1 || this.pageSize > 64) fail(400, 'legacy_graph_page_invalid', 'Invalid legacy graph page size');
  }
  private async exported(ctx: AuthContext, selected: ReturnType<typeof plan>, options: IntegrationCallOptions): Promise<ExportedDocument[]> {
    const output: ExportedDocument[] = []; let bytes = 0, count = 0;
    for (const ticket of selected.tickets) {
      const source = state(this.db, this.auth, ctx, ticket), records: JsonObject[] = [];
      for (const phase of ['node', 'relation'] as const) {
        let cursor = '';
        for (;;) {
          check(options.signal); legacyGraphReadQuery(this.db, this.auth, ctx, ticket, { phase, cursor, limit: this.pageSize });
          const result = await this.transport(ctx, ticket, { phase, cursor, limit: this.pageSize }, options);
          check(options.signal); state(this.db, this.auth, ctx, ticket);
          if (result.state !== 'connected' || !Array.isArray(result.records)) fail(503, 'legacy_graph_connection_unavailable', 'The original graph could not be read');
          const rows = result.records.map(value => object(object(value).record ?? value));
          if (rows.length > this.pageSize) fail(502, 'legacy_graph_response_invalid', 'Legacy graph returned an invalid page');
          for (const row of rows) {
            if (row.kind !== phase || typeof row.key !== 'string' || row.key <= cursor || !row.properties || typeof row.properties !== 'object' || Array.isArray(row.properties)) fail(502, 'legacy_graph_response_invalid', 'Legacy graph returned inconsistent cursor or properties');
            if (phase === 'node' && (object(row.properties).kg !== source.docId || !source.labels.every(label => list(row.labels).includes(label)))) fail(502, 'legacy_graph_scope_mismatch', 'Legacy graph returned a different document namespace');
            if (phase === 'relation' && (typeof row.source !== 'string' || typeof row.target !== 'string' || typeof row.relation_type !== 'string' || !row.relation_type)) fail(502, 'legacy_graph_response_invalid', 'Legacy graph returned an invalid relationship');
            bytes += Buffer.byteLength(canonical(row)); count++;
            if (bytes > 64 * 1024 * 1024 || count > 100000) fail(413, 'legacy_graph_export_too_large', 'Legacy graph exceeds the bounded migration export; nothing was published');
            cursor = row.key; records.push(row);
          }
          if (rows.length < this.pageSize) break;
        }
      }
      output.push({ knowledge_base_id: source.kbId, knowledge_id: source.docId, source_fingerprint: source.fingerprint, records });
    }
    return output;
  }
  private convert(ctx: AuthContext, exported: ExportedDocument[], selected: ReturnType<typeof plan>): ConvertedDocument[] {
    return exported.map((doc, i) => {
      const source = state(this.db, this.auth, ctx, selected.tickets[i]!), nodes = new Map<string, GraphNode>(), names = new Map<string, string>(), relations: GraphRelation[] = [], warnings: string[] = [];
      for (const row of doc.records.filter(r => r.kind === 'node')) {
        const p = object(row.properties);
        if (typeof p.name !== 'string' || !p.name) fail(502, 'legacy_graph_entity_invalid', 'Legacy entity has no name');
        const allowed = list(p.chunks).filter(id => source.chunkIds.has(id));
        if (!allowed.length) continue;
        const name = p.name, type = typeof p.type === 'string' && p.type ? p.type : 'Entity', key = JSON.stringify([type, name]);
        const previous = nodes.get(key);
        nodes.set(key, { name, type, attributes: list([...(previous?.attributes ?? []), ...list(p.attributes)]), chunks: list([...(previous?.chunks ?? []), ...allowed]) }); names.set(String(row.key), name);
      }
      for (const row of doc.records.filter(r => r.kind === 'relation')) {
        const a = names.get(String(row.source)), b = names.get(String(row.target)); if (!a || !b || a === b) continue;
        const p = object(row.properties), supplied = list(p.chunks).filter(id => source.chunkIds.has(id)), inferred = list([...nodes.values()].filter(n => n.name === a || n.name === b).flatMap(n => n.chunks));
        const strength = typeof p.strength === 'number' && Number.isFinite(p.strength) ? p.strength : 1;
        if (typeof p.strength !== 'number' || !Number.isFinite(p.strength)) warnings.push('legacy_relationship_strength_not_stored');
        if (!supplied.length) warnings.push('legacy_relationship_evidence_inferred_from_entities');
        if (typeof p.weight !== 'number' || !Number.isFinite(p.weight)) warnings.push('legacy_relationship_weight_not_stored');
        relations.push({ node1: a, node2: b, type: String(row.relation_type), strength, chunks: supplied.length ? supplied : inferred, weight: typeof p.weight === 'number' && Number.isFinite(p.weight) ? p.weight : NaN, combined_degree: typeof p.combined_degree === 'number' && Number.isFinite(p.combined_degree) ? p.combined_degree : -1 });
      }
      const graph = { node: [...nodes.values()], relation: relations }, derived = weightGraph({ node: graph.node, relation: relations.map(r => ({ ...r })) });
      graph.relation.forEach((r, j) => { if (!Number.isFinite(r.weight)) r.weight = derived.relation[j]!.weight; if (r.combined_degree < 0) r.combined_degree = derived.relation[j]!.combined_degree; });
      return { ...doc, graph, warnings: [...new Set(warnings)] };
    });
  }
  private async prepare(ctx: AuthContext, options: IntegrationCallOptions, action: 'export' | 'import'): Promise<{ selected: ReturnType<typeof plan>; exported: ExportedDocument[]; converted: ConvertedDocument[]; summary: LegacyGraphSummary }> {
    check(options.signal); const selected = plan(this.db, this.auth, ctx, action), exported = await this.exported(ctx, selected, options), verified = await this.exported(ctx, selected, options);
    if (sha(exported) !== sha(verified)) fail(409, 'legacy_graph_external_changed', 'The original external graph changed during export; retry without publishing');
    const converted = this.convert(ctx, exported, selected), nodes = converted.reduce((n, doc) => n + doc.graph.node.length, 0), relations = converted.reduce((n, doc) => n + doc.graph.relation.length, 0), rawNodes = exported.reduce((n, doc) => n + doc.records.filter(r => r.kind === 'node').length, 0), rawRelations = exported.reduce((n, doc) => n + doc.records.filter(r => r.kind === 'relation').length, 0), conversion = converted.map(doc => ({ knowledge_base_id: doc.knowledge_base_id, knowledge_id: doc.knowledge_id, source_fingerprint: doc.source_fingerprint, graph: doc.graph, warnings: doc.warnings }));
    return { selected, exported, converted, summary: { protocol: 1, state: rawNodes || rawRelations ? 'exported' : 'verified_empty', import_fingerprint: selected.fingerprint, documents: exported.length, nodes, relations, exported_nodes: rawNodes, exported_relations: rawRelations, filtered_nodes: rawNodes - nodes, filtered_relations: rawRelations - relations, published_documents: 0, export_sha256: sha(exported), conversion_sha256: sha(conversion), publication_sha256: '', repeated: false, warnings: [...new Set(converted.flatMap(doc => doc.warnings))] } };
  }
  async inspect(ctx: AuthContext, options: IntegrationCallOptions = {}): Promise<LegacyGraphSummary> { return (await this.prepare(ctx, options, 'export')).summary; }
  async import(ctx: AuthContext, options: IntegrationCallOptions = {}): Promise<LegacyGraphSummary> {
    const prepared = await this.prepare(ctx, options, 'import'), { selected, exported, converted, summary } = prepared;
    const archive = `archives/legacy-graph-${selected.fingerprint.slice(0, 16)}/${summary.export_sha256}.json`, archivePath = safeDataPath(this.db.dataRoot, archive), payload = { protocol: 1, kind: 'legacy-neo4j-export', import_fingerprint: selected.fingerprint, export_sha256: summary.export_sha256, documents: exported };
    // Content-addressed immutable export is written before publication. A rollback can leave a safe unreferenced archive, never half a visible graph.
    if (existsSync(archivePath)) { if (sha(parseStoredJson(readFileSync(archivePath, 'utf8'))) !== sha(payload)) fail(409, 'legacy_graph_archive_conflict', 'An existing graph export has different content'); }
    else { mkdirSync(dirname(archivePath), { recursive: true, mode: 0o700 }); writePrivateJson(archivePath, payload); }
    const archiveSHA = fileHash(archivePath), generation = `legacy:${summary.conversion_sha256}`, publications: JsonObject[] = [];
    return this.db.transaction(() => {
      check(options.signal); for (const ticket of selected.tickets) state(this.db, this.auth, ctx, ticket);
      let repeated = true;
      for (const [index, doc] of converted.entries()) {
        const id = `graph:${hash([ctx.tenantId, doc.knowledge_base_id, doc.knowledge_id])}`, previous = this.db.read('generic_resources', id);
        if (previous && (String(previous.tenant_id) !== ctx.tenantId || previous.resource_type !== 'graph_document' || object(previous.data).knowledge_id !== doc.knowledge_id || object(previous.data).knowledge_base_id !== doc.knowledge_base_id)) fail(409, 'legacy_graph_publication_conflict', 'The graph publication belongs to a different source');
        const namespace = hash([ctx.tenantId, doc.knowledge_base_id]), data: JsonObject = { namespace, knowledge_base_id: doc.knowledge_base_id, knowledge_id: doc.knowledge_id, generation, fingerprint: doc.source_fingerprint, storage: 'legacy_sqlite', import_fingerprint: selected.fingerprint, export_sha256: summary.export_sha256, conversion_sha256: summary.conversion_sha256, archive_path: archive, archive_sha256: archiveSHA, nodes: doc.graph.node as unknown as Json[], relations: doc.graph.relation as unknown as Json[], weight_status: doc.warnings.includes('legacy_relationship_weight_not_stored') ? 'derived_missing_source_weight' : 'preserved', source_generation: object(this.db.read('knowledges', doc.knowledge_id)?.metadata).source_generation ?? null };
        if (previous && object(previous.data).storage !== 'legacy_sqlite') fail(409, 'legacy_graph_publication_conflict', 'A new graph generation already exists; migration cannot overwrite it');
        if (!previous || previous.status !== 'active' || sha(previous.data) !== sha(data)) {
          repeated = false;
          if (previous) this.db.update('generic_resources', id, { data, status: 'active', updated_at: now() });
          else this.db.insert('generic_resources', { id, tenant_id: ctx.tenantId, resource_type: 'graph_document', name: String(this.db.read('knowledges', doc.knowledge_id)!.title), status: 'active', data });
        }
        publications.push({ id, data });
        // Preserve the original array order exactly. Record only associations proven to come from this source so later graph retirement can remove them.
        const source = state(this.db, this.auth, ctx, selected.tickets[index]!);
        for (const [chunkId, original] of source.associations) {
          const chunk = this.db.read('chunks', chunkId)!, metadata = object(chunk.metadata);
          const next = { ...metadata, graph_relation_chunks: list([...list(metadata.graph_relation_chunks), ...original.direct]), graph_indirect_relation_chunks: list([...list(metadata.graph_indirect_relation_chunks), ...original.indirect]) };
          if (sha(metadata) !== sha(next)) this.db.update('chunks', chunkId, { metadata: next });
        }
      }
      const result: LegacyGraphSummary = { ...summary, state: summary.state === 'verified_empty' ? 'verified_empty' : 'imported', archive_path: archive, archive_sha256: archiveSHA, published_documents: publications.length, publication_sha256: sha(publications), repeated };
      const key = `legacy-graph:${hash([ctx.tenantId, selected.fingerprint])}`;
      this.db.run('INSERT INTO desktop_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', key, JSON.stringify(result));
      return result;
    });
  }
}
