import { randomUUID } from 'node:crypto';
import type { AuthService } from '../auth/index.js';
import type { AuthContext, JsonObject } from '../contracts.js';
import type { WorkflowHook, WorkflowHookResult } from '../documents/pipeline.js';
import type { IntegrationService, Neo4jCallOptions } from '../integrations/index.js';
import { enabled as booleanValue } from '../knowledge/config.js';
import type { ModelConfigurationService } from '../settings/model-configuration.js';
import type { CoreDatabase, Row } from '../storage/database.js';
import { array, check, chunks, completion, configuration, document, fail, hash, jsonPayload, kb, now, number, object, sourceFingerprint, sourceRefs, strings, warning } from '../wiki/internal.js';
import { defaultExtractConfig, normalizeNodes, normalizeRelations, parseGraph, relatedChunks, weightGraph, type ExtractedGraph, type GraphNode, type GraphRelation } from './extraction.js';
import { deleteDocument, readGenerations, writeGeneration } from './templates.js';
import { cleanupScope, pendingCleanup } from './cleanup.js';
import { AppError } from '../errors.js';
import { legacySnapshotGraph } from '../storage/graph-legacy.js';
export { parseGraph, weightGraph, relatedChunks, defaultExtractConfig } from './extraction.js';
export const graphNamespace = (tenantId: string, knowledgeBaseId: string): string => hash([tenantId, knowledgeBaseId]);
/** Trusted core dependency, never a renderer/API request field. Only GraphService's fixed templates reach it. */
export type GraphTransport = (ctx: AuthContext, knowledgeBaseId: string, statement: string, parameters: JsonObject, options?: Neo4jCallOptions) => Promise<JsonObject>;
export interface GraphOptions {
    transport?: GraphTransport;
}
export interface GraphBuildOptions {
    signal?: AbortSignal;
    publish?: <T>(work: () => T) => T;
    processConfig?: JsonObject;
    jobId?: string;
    attempt?: number;
}
export interface GraphView extends JsonObject {
    state: string;
    nodes: JsonObject[];
    edges: JsonObject[];
    meta: JsonObject;
    warnings: JsonObject[];
}
interface Snapshot {
    row: Row;
    doc: Row;
    data: JsonObject;
    fingerprint: string;
    graph: ExtractedGraph;
}
/** SQLite owns active generations. Neo4j receives parameterized staging generations, never direct business writes. */
export class GraphService {
    private readonly transport?: GraphTransport;
    private readonly controllers = new Set<AbortController>();
    private readonly active = new Set<Promise<unknown>>();
    private closed = false;
    constructor(private readonly db: CoreDatabase, private readonly auth: AuthService, private readonly models: ModelConfigurationService, private readonly integrations?: IntegrationService, options: GraphOptions = {}) {
        this.transport = options.transport ?? (integrations ? (ctx, id, statement, params, callOptions) => integrations.queryScopedNeo4j(ctx, id, statement, params, callOptions) : undefined);
    }
    private operation<T>(signal: AbortSignal | undefined, work: (signal: AbortSignal) => Promise<T>): Promise<T> {
        if (this.closed)
            return Promise.reject(new Error('Graph service is closed'));
        const controller = new AbortController();
        this.controllers.add(controller);
        const relay = () => controller.abort(signal?.reason);
        signal?.addEventListener('abort', relay, { once: true });
        if (signal?.aborted)
            relay();
        const running = Promise.resolve().then(() => { check(controller.signal); return work(controller.signal); }).finally(() => { signal?.removeEventListener('abort', relay); this.controllers.delete(controller); this.active.delete(running); });
        this.active.add(running);
        void running.catch(() => { });
        return running;
    }
    private scope(ctx: AuthContext, kbId: string, write = false): Row { return kb(this.db, this.auth, ctx, kbId, write ? 'document.write' : 'read'); }
    private params(ctx: AuthContext, kbId: string, extra: JsonObject = {}): JsonObject { return { ...extra, tenant_id: ctx.tenantId, knowledge_base_id: kbId, namespace: graphNamespace(ctx.tenantId, kbId) }; }
    private resourceId(ctx: AuthContext, kbId: string, docId: string): string { return `graph:${hash([ctx.tenantId, kbId, docId])}`; }
    capabilities(ctx: AuthContext, kbId: string): JsonObject {
        const base = this.scope(ctx, kbId), cfg = configuration(this.models, ctx, String(object(base.extract_config).model_id ?? base.summary_model_id ?? ''));
        const enabled = booleanValue(object(base.indexing_strategy).graph_enabled), readiness = this.integrations?.scopedNeo4jReadiness(ctx, kbId) ?? { state: this.transport ? 'configured' : 'not_configured', configured: !!this.transport, connection_verified: false };
        const legacy = this.snapshots(ctx, kbId).some(snapshot => snapshot.data.storage === 'legacy_sqlite');
        return { enabled, transport_available: !!this.transport && readiness.configured === true, model_configured: !!cfg, neo4j: readiness, namespace_version: 'tenant-kb-sha256-v1', state: !enabled ? 'disabled' : !legacy && readiness.state !== 'configured' ? readiness.state! : !cfg ? 'model_not_configured' : 'configured', legacy_namespace_status: legacy ? 'imported' : 'requires_rebuild', legacy_local_available: legacy };
    }
    private snapshots(ctx: AuthContext, kbId: string): Snapshot[] {
        this.scope(ctx, kbId);
        const rows = this.db.all("SELECT id FROM generic_resources WHERE tenant_id=? AND resource_type='graph_document' AND deleted_at IS NULL AND status='active' ORDER BY id", ctx.tenantId), result: Snapshot[] = [];
        for (const row of rows) {
            const resource = this.db.read('generic_resources', String(row.id))!, data = object(resource.data);
            if (data.knowledge_base_id !== kbId || data.namespace !== graphNamespace(ctx.tenantId, kbId))
                continue;
            const doc = this.db.read('knowledges', String(data.knowledge_id));
            if (!doc || String(doc.tenant_id) !== ctx.tenantId || doc.knowledge_base_id !== kbId || doc.deleted_at !== null || doc.enable_status !== 'enabled')
                continue;
            const fingerprint = sourceFingerprint(this.db, ctx, kbId, doc);
            if (fingerprint !== data.fingerprint)
                continue;
            const graph = data.storage === 'legacy_sqlite' ? legacySnapshotGraph(data) : { node: normalizeNodes(data.nodes ?? []), relation: normalizeRelations(data.relations ?? []) };
            result.push({ row: resource, doc, data, fingerprint, graph });
        }
        return result;
    }
    private async query(ctx: AuthContext, kbId: string, statement: string, params: JsonObject, options: Neo4jCallOptions = {}): Promise<JsonObject> {
        if (this.closed)
            fail(503, 'graph_closed', 'Graph service is closed');
        check(options.signal);
        this.scope(ctx, kbId, options.write === true);
        if (!this.transport)
            return { state: 'not_configured', records: [] };
        const result = await this.transport(ctx, kbId, statement, this.params(ctx, kbId, params), options);
        check(options.signal);
        this.scope(ctx, kbId, options.write === true);
        if (!result || !['connected', 'disabled', 'not_configured'].includes(String(result.state)) || result.state === 'connected' && !Array.isArray(result.records))
            fail(502, 'graph_invalid_response', 'Graph service returned an invalid result');
        return result;
    }
    private empty(state: string, query: JsonObject = {}): GraphView { return { state, nodes: [], edges: [], meta: { mode: query.mode ?? 'overview', total: 0, returned: 0, truncated: false, depth: query.depth ?? 1, center: query.center ?? '' }, warnings: state === 'connected' ? [] : [warning('graph_needs_configuration', 'graph', 'Configure Neo4j to query this knowledge graph')] }; }
    private evidence(ctx: AuthContext, kbId: string, docId: string, ids: string[]): JsonObject[] {
        const lookup = new Map(chunks(this.db, ctx, kbId, docId).map(c => [String(c.id), c])), doc = this.db.read('knowledges', docId);
        return ids.flatMap(id => { const chunk = lookup.get(id); if (!chunk)
            return []; const media = object(chunk.image_info); return sourceRefs(chunk).map(provenance => ({ ...provenance, knowledge_id: docId, knowledge_base_id: kbId, title: doc?.title ?? '', chunk_id: id, source_type: provenance.source_type ?? media.source_type ?? 'text', source_ref: provenance.source_ref ?? media.source_ref ?? '', ...(media.image_id ? { image_id: media.image_id } : {}) })); });
    }
    private async dataset(ctx: AuthContext, kbId: string, signal?: AbortSignal): Promise<GraphView> {
        const base = this.scope(ctx, kbId);
        if (!booleanValue(object(base.indexing_strategy).graph_enabled))
            return this.empty('disabled');
        const initial = this.snapshots(ctx, kbId), before = hash(initial.map(s => [s.row.id, s.data.generation, s.fingerprint])), preserved = initial.filter(s => s.data.storage === 'legacy_sqlite'), active = initial.filter(s => s.data.storage !== 'legacy_sqlite').map(s => ({ knowledge_id: s.doc.id!, generation: s.data.generation! })), records: JsonObject[] = [], warnings: JsonObject[] = [];
        for (const source of preserved) {
            const docId = String(source.doc.id), generation = source.data.generation!;
            for (const node of source.graph.node) records.push({ node: this.params(ctx, kbId, { id: this.nodeId(ctx, kbId, docId, node), knowledge_id: docId, generation, name: node.name }) });
            for (const relation of source.graph.relation) {
                const a = source.graph.node.find(n => n.name === relation.node1), b = source.graph.node.find(n => n.name === relation.node2);
                if (a && b) records.push({ relation: this.params(ctx, kbId, { id: this.relationId(ctx, kbId, docId, relation), knowledge_id: docId, generation, source: this.nodeId(ctx, kbId, docId, a), target: this.nodeId(ctx, kbId, docId, b), relation_type: relation.type, weight: relation.weight }) });
            }
        }
        let offset = 0, state = 'connected';
        if (active.length || !preserved.length) do {
            const result = await this.query(ctx, kbId, readGenerations, { active, offset, limit: 64 }, { signal });
            state = String(result.state);
            if (state !== 'connected') {
                if (!preserved.length) return this.empty(state);
                warnings.push(warning('graph_needs_configuration', 'graph', 'Preserved legacy graph is available locally; newer remote generations require Neo4j configuration'));
                state = 'connected'; break;
            }
            const rows = array(result.records).map(object);
            records.push(...rows);
            if (rows.length < 64)
                break;
            offset += rows.length;
            if (offset > 100000)
                fail(502, 'graph_response_too_large', 'Knowledge graph exceeds the query safety limit');
        } while (true);
        check(signal);
        if (hash(this.snapshots(ctx, kbId).map(s => [s.row.id, s.data.generation, s.fingerprint])) !== before)
            fail(409, 'graph_source_changed', 'Graph sources changed during query');
        const byDoc = new Map(initial.map(s => [String(s.doc.id), s])), nodeMap = new Map<string, JsonObject>(), remoteIds = new Map<string, string>(), edges = new Map<string, JsonObject>();
        const valid = (row: JsonObject): Snapshot | undefined => row.namespace === graphNamespace(ctx.tenantId, kbId) && String(row.tenant_id) === ctx.tenantId && row.knowledge_base_id === kbId && byDoc.get(String(row.knowledge_id))?.data.generation === row.generation ? byDoc.get(String(row.knowledge_id)) : undefined;
        for (const record of records) {
            const remote = object(record.node), source = valid(remote);
            if (!source)
                continue;
            const saved = source.graph.node.find(n => this.nodeId(ctx, kbId, String(source.doc.id), n) === remote.id);
            if (!saved || remote.name !== saved.name)
                continue;
            const id = hash([graphNamespace(ctx.tenantId, kbId), saved.type, saved.name]), evidence = this.evidence(ctx, kbId, String(source.doc.id), saved.chunks);
            if (!evidence.length)
                continue;
            const old = nodeMap.get(id);
            nodeMap.set(id, { id, name: saved.name, title: saved.name, label: saved.name, type: saved.type, node_type: saved.type, attributes: strings([...array(old?.attributes), ...saved.attributes]), chunks: strings([...array(old?.chunks), ...saved.chunks], 10000), source_refs: [...array(old?.source_refs), ...evidence], link_count: 0 });
            remoteIds.set(`${remote.generation}:${remote.id}`, id);
        }
        for (const record of records) {
            const remote = object(record.relation), source = valid(remote);
            if (!source)
                continue;
            const sourceId = remoteIds.get(`${remote.generation}:${remote.source}`), targetId = remoteIds.get(`${remote.generation}:${remote.target}`);
            if (!sourceId || !targetId || sourceId === targetId)
                continue;
            const relation = source.graph.relation.find(r => this.relationId(ctx, kbId, String(source.doc.id), r) === remote.id);
            if (!relation || relation.type !== remote.relation_type)
                continue;
            const id = hash([sourceId, targetId, relation.type]), old = edges.get(id);
            edges.set(id, { id, source: sourceId, target: targetId, type: relation.type, strength: Math.max(Number(old?.strength ?? 1), relation.strength), weight: Math.max(Number(old?.weight ?? 1), Number(remote.weight ?? 1)), chunks: strings([...array(old?.chunks), ...relation.chunks], 10000), source_refs: [...array(old?.source_refs), ...this.evidence(ctx, kbId, String(source.doc.id), relation.chunks)] });
        }
        for (const node of nodeMap.values())
            node.link_count = edges.size ? new Set([...edges.values()].filter(e => e.source === node.id || e.target === node.id).map(e => e.source === node.id ? e.target : e.source)).size : 0;
        return { state, nodes: [...nodeMap.values()], edges: [...edges.values()], meta: { mode: 'overview', total: nodeMap.size, returned: nodeMap.size, truncated: false, ...(preserved.length ? { legacy_local_documents: preserved.length } : {}) }, warnings };
    }
    private view(data: GraphView, query: JsonObject): GraphView {
        const mode = String(query.mode ?? 'overview'), center = String(query.center ?? ''), depth = number(query.depth, 1, 1, 3), limit = number(query.limit, 500, 1, 2000), offset = number(query.offset, 0, 0, 10000000), types = new Set(typeof query.types === 'string' ? query.types.split(',').map(s => s.trim()).filter(Boolean) : strings(query.types));
        if (!['overview', 'ego'].includes(mode))
            fail(400, 'invalid_graph_mode', 'Graph mode must be overview or ego');
        if (mode === 'ego' && !center)
            fail(400, 'graph_center_required', 'Graph center is required');
        const byId = new Map(data.nodes.map(n => [String(n.id), n])), eligible = data.nodes.filter(n => !types.size || types.has(String(n.type))), allowed = new Set(eligible.map(n => String(n.id)));
        let selected = eligible;
        if (mode === 'ego') {
            const id = byId.has(center) ? center : String(data.nodes.find(n => n.name === center)?.id ?? ''), seen = new Set<string>(id ? [id] : []);
            let frontier = [...seen];
            for (let i = 0; i < depth; i++) {
                const next = strings(frontier.flatMap(s => data.edges.filter(e => e.source === s || e.target === s).map(e => e.source === s ? e.target : e.source))).filter(s => allowed.has(s) && !seen.has(s));
                for (const s of next)
                    seen.add(s);
                frontier = next;
            }
            selected = data.nodes.filter(n => seen.has(String(n.id)));
        }
        selected.sort((a, b) => Number(b.link_count) - Number(a.link_count) || String(a.name).localeCompare(String(b.name)) || String(a.id).localeCompare(String(b.id)));
        const total = selected.length, nodes = selected.slice(offset, offset + limit), chosen = new Set(nodes.map(n => String(n.id)));
        return { ...data, nodes, edges: data.edges.filter(e => chosen.has(String(e.source)) && chosen.has(String(e.target))), meta: { mode, total, returned: nodes.length, truncated: total > nodes.length, depth, center, offset, limit } };
    }
    overview(ctx: AuthContext, kbId: string, query: JsonObject = {}, options: {
        signal?: AbortSignal;
    } = {}): Promise<GraphView> { return this.operation(options.signal, async (signal) => this.view(await this.dataset(ctx, kbId, signal), { ...query, mode: 'overview' })); }
    ego(ctx: AuthContext, kbId: string, center: string, query: JsonObject = {}, options: {
        signal?: AbortSignal;
    } = {}): Promise<GraphView> { return this.operation(options.signal, async (signal) => this.view(await this.dataset(ctx, kbId, signal), { ...query, mode: 'ego', center })); }
    types(ctx: AuthContext, kbId: string, options: {
        signal?: AbortSignal;
    } = {}): Promise<JsonObject> { return this.operation(options.signal, async (signal) => { const data = await this.dataset(ctx, kbId, signal); return { state: data.state, node_types: strings(data.nodes.map(n => n.type)), relation_types: strings(data.edges.map(e => e.type)), warnings: data.warnings }; }); }
    private nodeId(ctx: AuthContext, kbId: string, docId: string, node: GraphNode): string { return hash([graphNamespace(ctx.tenantId, kbId), docId, node.type, node.name]); }
    private relationId(ctx: AuthContext, kbId: string, docId: string, relation: GraphRelation): string { return hash([graphNamespace(ctx.tenantId, kbId), docId, relation.node1, relation.node2, relation.type]); }
    readonly workflowHook: WorkflowHook = context => this.build(context.auth, context.knowledgeBaseId, context.knowledgeId, { signal: context.signal, publish: context.publish, processConfig: context.processConfig, jobId: context.jobId, attempt: context.attempt });
    build(ctx: AuthContext, kbId: string, docId: string, options: GraphBuildOptions = {}): Promise<WorkflowHookResult> {
        return this.operation(options.signal, signal => this.generate(ctx, kbId, docId, { ...options, signal }));
    }
    private async generate(ctx: AuthContext, kbId: string, docId: string, options: GraphBuildOptions): Promise<WorkflowHookResult> {
        check(options.signal);
        const base = this.scope(ctx, kbId, true), doc = document(this.db, this.auth, ctx, kbId, docId, 'document.write'), source = chunks(this.db, ctx, kbId, docId), config = { ...defaultExtractConfig, ...object(base.extract_config), ...object(options.processConfig?.extract_config ?? options.processConfig?.extractConfig) };
        const enabled = booleanValue(options.processConfig?.graph_enabled, booleanValue(object(base.indexing_strategy).graph_enabled));
        if (!enabled || doc.enable_status !== 'enabled' || !source.length)
            return { status: 'pending', output: { reason: doc.enable_status !== 'enabled' ? 'source_disabled' : !source.length ? 'no_chunks' : 'graph_disabled' }, warnings: [warning('graph_pending', 'graph', 'Graph extraction requires an enabled source and graph configuration')] };
        const cfg = configuration(this.models, ctx, String(config.model_id ?? base.summary_model_id ?? ''));
        if (!this.transport || !cfg)
            return { status: 'needs_configuration', output: { reason: !this.transport ? 'neo4j_not_configured' : 'graph_model_not_configured', pending: true }, warnings: [warning('graph_needs_configuration', 'graph', 'Configure Neo4j and an extraction model to build the graph')] };
        const readiness = await this.query(ctx, kbId, readGenerations, { active: [], offset: 0, limit: 1 }, { signal: options.signal });
        if (readiness.state !== 'connected')
            return { status: 'needs_configuration', output: { reason: readiness.state!, pending: true }, warnings: [warning('graph_needs_configuration', 'graph', 'Neo4j is disabled or incomplete; extraction was not dispatched')] };
        const fingerprint = sourceFingerprint(this.db, ctx, kbId, doc), configHash = hash([config, cfg]), existing = this.db.read('generic_resources', this.resourceId(ctx, kbId, docId));
        if (existing && String(existing.tenant_id) === ctx.tenantId && existing.status === 'active' && object(existing.data).fingerprint === fingerprint && object(existing.data).configuration_signature === configHash)
            return { status: 'completed', output: { repeated: true, nodes: array(object(existing.data).nodes).length, relations: array(object(existing.data).relations).length } };
        const nodeTypes = strings(array(config.nodes).map(n => object(n).name)), tags = strings(config.tags);
        if (!String(config.text ?? '').trim() || !nodeTypes.length || !tags.length)
            fail(400, 'invalid_extract_config', 'Graph extraction needs a prompt, node schema and relation types');
        const callOptions = { ...options, knowledgeId: docId, knowledgeBaseId: kbId }, nodes: GraphNode[] = [], relations: GraphRelation[] = [];
        for (let offset = 0; offset < source.length; offset += 5) {
            const batch = source.slice(offset, offset + 5), aliases = new Map(batch.map((chunk, i) => [`c${String(i + 1).padStart(3, '0')}`, chunk]));
            const payload = jsonPayload(await completion(this.db, this.auth, this.models, ctx, cfg, `GRAPH_ENTITIES\n${config.text}\nAllowed node types: ${JSON.stringify(nodeTypes)}. Return strict JSON [{"chunk_key":"c001","entities":[{"name":"...","type":"Entity","attributes":[]}]}]. Attach each entity to its exact chunk_key.\n${[...aliases].map(([key, chunk]) => `CHUNK ${key}\n<source_text>\n${String(chunk.content).slice(0, 6000)}\n</source_text>`).join('\n')}`, 'graph_entity_extract', callOptions));
            if (!Array.isArray(payload))
                fail(502, 'graph_entities_invalid', 'Model returned an invalid entity batch');
            const batchNodes: GraphNode[] = [];
            for (const value of payload) {
                const item = object(value), chunk = aliases.get(String(item.chunk_key));
                if (!chunk)
                    continue;
                for (const node of normalizeNodes(item.entities ?? item.nodes ?? [])) {
                    if (!nodeTypes.includes(node.type))
                        node.type = nodeTypes[0]!;
                    node.chunks = [String(chunk.id)];
                    batchNodes.push(node);
                }
            }
            const mergedBatch = normalizeNodes(batchNodes as unknown as JsonObject[]);
            nodes.push(...mergedBatch);
            if (mergedBatch.length >= 2) {
                const raw = await completion(this.db, this.auth, this.models, ctx, cfg, `GRAPH_RELATIONS\n${config.text}\nAllowed relation types: ${JSON.stringify(tags)}. Allowed schema: ${JSON.stringify(config.relations)}. Return strict JSON [{"entity1":"...","entity2":"...","relation":"...","strength":1}]. Use only supplied entity names.\nENTITIES: ${JSON.stringify(mergedBatch)}\nSOURCE: ${batch.map(c => String(c.content)).join('\n\n').slice(0, 8000)}`, 'graph_relation_extract', callOptions), parsed = parseGraph(raw), names = new Set(mergedBatch.map(n => n.name));
                for (const relation of parsed.relation)
                    if (names.has(relation.node1) && names.has(relation.node2) && tags.includes(relation.type)) {
                        relation.chunks = strings(mergedBatch.filter(n => [relation.node1, relation.node2].includes(n.name)).flatMap(n => n.chunks), 10000);
                        relations.push(relation);
                    }
            }
        }
        const graph = weightGraph({ node: normalizeNodes(nodes as unknown as JsonObject[]), relation: normalizeRelations(relations as unknown as JsonObject[]) }), generation = randomUUID();
        const remoteNodes = graph.node.map(node => this.params(ctx, kbId, { id: this.nodeId(ctx, kbId, docId, node), knowledge_id: docId, generation, name: node.name, node_type: node.type, attributes: node.attributes, chunks: node.chunks }));
        const remoteRelations = graph.relation.map(relation => { const a = graph.node.find(n => n.name === relation.node1)!, b = graph.node.find(n => n.name === relation.node2)!; return this.params(ctx, kbId, { id: this.relationId(ctx, kbId, docId, relation), knowledge_id: docId, generation, source: this.nodeId(ctx, kbId, docId, a), target: this.nodeId(ctx, kbId, docId, b), relation_type: relation.type, chunks: relation.chunks, strength: relation.strength, weight: relation.weight, combined_degree: relation.combined_degree }); });
        // Persist all endpoints before edges. Every batch is acknowledged, and staging stays invisible until publication.
        const batches: Array<{
            nodes: JsonObject[];
            relations: JsonObject[];
        }> = [];
        const addBatches = (values: JsonObject[], role: 'nodes' | 'relations') => {
            let batch: JsonObject[] = [];
            for (const value of values) {
                if (Buffer.byteLength(JSON.stringify(value)) > 180 * 1024)
                    fail(413, 'graph_entity_too_large', 'Graph entity evidence exceeds the transport limit');
                if (batch.length >= 32 || Buffer.byteLength(JSON.stringify([...batch, value])) > 190 * 1024) {
                    batches.push({ nodes: role === 'nodes' ? batch : [], relations: role === 'relations' ? batch : [] });
                    batch = [];
                }
                batch.push(value);
            }
            if (batch.length)
                batches.push({ nodes: role === 'nodes' ? batch : [], relations: role === 'relations' ? batch : [] });
        };
        if (remoteNodes.length <= 32 && remoteRelations.length <= 32 && Buffer.byteLength(JSON.stringify([remoteNodes, remoteRelations])) < 190 * 1024)
            batches.push({ nodes: remoteNodes, relations: remoteRelations });
        else {
            addBatches(remoteNodes, 'nodes');
            addBatches(remoteRelations, 'relations');
        }
        for (const { nodes: nodeBatch, relations: relationBatch } of batches) {
            const result = await this.query(ctx, kbId, writeGeneration, { knowledge_id: docId, generation, nodes: nodeBatch, relations: relationBatch }, { signal: options.signal, write: true });
            if (result.state !== 'connected')
                return { status: 'needs_configuration', output: { reason: result.state!, pending: true }, warnings: [warning('graph_needs_configuration', 'graph', 'Neo4j is disabled or incomplete; graph was not published')] };
            const counts = object(array(result.records)[0]);
            if (Number(counts.nodes) !== nodeBatch.length || Number(counts.relations) !== relationBatch.length)
                fail(502, 'graph_write_incomplete', 'Neo4j did not acknowledge the complete graph generation');
        }
        check(options.signal);
        return this.db.transaction(() => {
            let open = true, committed = false, finished = false;
            const commit = (): WorkflowHookResult => {
                if (!open || committed)
                    fail(409, 'graph_publication_expired', 'Graph publication is no longer active');
                committed = true;
                check(options.signal);
                const current = document(this.db, this.auth, ctx, kbId, docId, 'document.write'), currentBase = this.scope(ctx, kbId, true), currentConfig = { ...defaultExtractConfig, ...object(currentBase.extract_config), ...object(options.processConfig?.extract_config ?? options.processConfig?.extractConfig) }, currentCfg = configuration(this.models, ctx, String(currentConfig.model_id ?? currentBase.summary_model_id ?? ''));
                if (sourceFingerprint(this.db, ctx, kbId, current) !== fingerprint || hash([currentConfig, currentCfg]) !== configHash || current.enable_status !== 'enabled')
                    fail(409, 'graph_source_changed', 'Document or extraction model changed during graph generation');
                const id = this.resourceId(ctx, kbId, docId), previous = this.db.read('generic_resources', id);
                if (previous && (String(previous.tenant_id) !== ctx.tenantId || previous.resource_type !== 'graph_document' || object(previous.data).knowledge_base_id !== kbId || object(previous.data).knowledge_id !== docId))
                    fail(409, 'graph_scope_mismatch', 'Graph snapshot namespace is inconsistent');
                const data = { namespace: graphNamespace(ctx.tenantId, kbId), knowledge_base_id: kbId, knowledge_id: docId, generation, source_generation: object(current.metadata).source_generation ?? null, fingerprint, configuration_signature: configHash, nodes: graph.node as unknown as JsonObject[], relations: graph.relation as unknown as JsonObject[], published_at: now() };
                if (previous)
                    this.db.update('generic_resources', id, { data, status: 'active', updated_at: now() });
                else
                    this.db.insert('generic_resources', { id, tenant_id: ctx.tenantId, resource_type: 'graph_document', name: String(current.title), data, status: 'active' });
                this.publishRelations(ctx, kbId);
                finished = true;
                return { status: 'completed', output: { nodes: graph.node.length, relations: graph.relation.length, repeated: false, generation }, warnings: [] };
            };
            try {
                const result = options.publish ? options.publish(commit) : commit();
                if (result && typeof (result as unknown as {
                    then?: unknown;
                }).then === 'function') {
                    void Promise.resolve(result).catch(() => { });
                    fail(409, 'graph_publication_async', 'Graph publication must be synchronous');
                }
                if (!finished)
                    fail(409, 'graph_publication_missing', 'Graph publication did not complete the write');
                return result;
            }
            finally {
                open = false;
            }
        });
    }
    private publishRelations(ctx: AuthContext, kbId: string): void {
        const snapshots = this.snapshots(ctx, kbId), graph = weightGraph({ node: normalizeNodes(snapshots.flatMap(s => s.graph.node) as unknown as JsonObject[]), relation: normalizeRelations(snapshots.flatMap(s => s.graph.relation) as unknown as JsonObject[]) }), related = relatedChunks(graph), local = chunks(this.db, ctx, kbId), allowed = new Set(local.map(c => String(c.id)));
        for (const chunk of local) {
            const meta = object(chunk.metadata), next = related.get(String(chunk.id)) ?? { direct: [], indirect: [] }, oldDirect = new Set(strings(meta.graph_relation_chunks)), oldIndirect = new Set(strings(meta.graph_indirect_relation_chunks));
            this.db.update('chunks', String(chunk.id), { relation_chunks: strings([...strings(chunk.relation_chunks).filter(id => !oldDirect.has(id) && allowed.has(id)), ...next.direct]), indirect_relation_chunks: strings([...strings(chunk.indirect_relation_chunks).filter(id => !oldIndirect.has(id) && allowed.has(id)), ...next.indirect]), metadata: { ...meta, graph_relation_chunks: next.direct, graph_indirect_relation_chunks: next.indirect } });
        }
    }
    removeDocument(ctx: AuthContext, kbId: string, docId: string, options: {
        signal?: AbortSignal;
        generation?: string;
    } = {}): Promise<WorkflowHookResult> {
        return this.operation(options.signal, signal => this.cleanupDocument(ctx, kbId, docId, { ...options, signal }));
    }
    private async cleanupDocument(ctx: AuthContext, kbId: string, docId: string, options: {
        signal?: AbortSignal;
        generation?: string;
    }): Promise<WorkflowHookResult> {
        this.scope(ctx, kbId, true);
        const found = this.db.read('knowledges', docId);
        if (found && String(found.tenant_id) !== ctx.tenantId)
            fail(404, 'knowledge_not_found', 'Document not found');
        const previous = this.db.read('generic_resources', this.resourceId(ctx, kbId, docId));
        const preserved = previous && String(previous.tenant_id) === ctx.tenantId && object(previous.data).storage === 'legacy_sqlite';
        // Retire the local publication first: remote outages cannot make deleted/edited sources queryable.
        this.db.transaction(() => { this.scope(ctx, kbId, true); const row = this.db.read('generic_resources', this.resourceId(ctx, kbId, docId)); if (row && (!options.generation || object(row.data).generation === options.generation))
            this.db.update('generic_resources', String(row.id), { status: 'retired', updated_at: now() }); this.publishRelations(ctx, kbId); });
        if (preserved) return { status: 'completed', output: { knowledge_id: docId, remote_cleanup: 'not_required', source: 'legacy_local' }, warnings: [] };
        const result = await this.query(ctx, kbId, deleteDocument, { knowledge_id: docId, generation: options.generation ?? '' }, { signal: options.signal, write: true });
        if (result.state !== 'connected')
            return { status: 'pending', output: { reason: result.state!, remote_cleanup: 'pending' }, warnings: [warning('graph_cleanup_pending', 'graph', 'Remote graph cleanup requires Neo4j configuration')] };
        return { status: 'completed', output: { knowledge_id: docId, remote_cleanup: 'completed' }, warnings: [] };
    }
    async removeKnowledgeBase(ctx: AuthContext, kbId: string, options: {
        signal?: AbortSignal;
    } = {}): Promise<WorkflowHookResult> {
        this.scope(ctx, kbId, true);
        const ids = strings([...this.db.all('SELECT id FROM knowledges WHERE tenant_id=? AND knowledge_base_id=?', ctx.tenantId, kbId).map(r => String(r.id)), ...this.db.all("SELECT id FROM generic_resources WHERE tenant_id=? AND resource_type='graph_document'", ctx.tenantId).map(r => object(this.db.read('generic_resources', String(r.id))?.data)).filter(d => d.knowledge_base_id === kbId).map(d => String(d.knowledge_id))], 100000), results: WorkflowHookResult[] = [];
        for (const id of ids)
            results.push(await this.removeDocument(ctx, kbId, id, options));
        return { status: results.every(r => r.status === 'completed') ? 'completed' : 'pending', output: { documents: ids.length }, warnings: results.flatMap(r => r.warnings ?? []) };
    }
    /** Reserve before local deletion so empty libraries and unpublished staging also have durable cleanup. */
    queueKnowledgeBaseCleanup(ctx: AuthContext, kbId: string): string {
        return this.db.transaction(() => {
            this.scope(ctx, kbId); this.auth.assertCan(ctx, 'kb.delete');
            const key = `knowledge.graph.pending:${randomUUID()}`;
            this.db.run('INSERT INTO desktop_meta(key,value) VALUES(?,?)', key, JSON.stringify({ schema_version: 2, tenant_id: ctx.tenantId, knowledge_base_id: kbId, namespace: graphNamespace(ctx.tenantId, kbId), operation: 'delete_knowledge_base', status: 'pending', created_at: now() }));
            return key;
        });
    }
    processPending(ctx: AuthContext, kbId: string, options: {
        signal?: AbortSignal;
        limit?: number;
    } = {}): Promise<JsonObject> { return this.operation(options.signal, signal => this.processCleanup(ctx, kbId, { ...options, signal })); }
    private async processCleanup(ctx: AuthContext, kbId: string, options: { signal: AbortSignal; limit?: number }): Promise<JsonObject> {
        cleanupScope(this.db, this.auth, ctx, kbId);
        const pending = this.db.all("SELECT key,value FROM desktop_meta WHERE key LIKE 'knowledge.graph.pending:%' ORDER BY key").map(r => { let value: JsonObject = {}; try { value = object(JSON.parse(String(r.value))); } catch {} return { key: String(r.key), value }; }).filter(r => r.value.tenant_id === ctx.tenantId && r.value.knowledge_base_id === kbId && r.value.status === 'pending').slice(0, number(options.limit, 20, 1, 100)), results: JsonObject[] = [], warnings: JsonObject[] = [];
        for (const item of pending) {
            check(options.signal);
            try {
                const ticket = pendingCleanup(this.db, this.auth, ctx, kbId, item.key);
                this.db.transaction(() => {
                    const base = cleanupScope(this.db, this.auth, ctx, kbId);
                    for (const ref of this.db.all("SELECT id FROM generic_resources WHERE tenant_id=? AND resource_type='graph_document'", ctx.tenantId)) {
                        const row = this.db.read('generic_resources', String(ref.id))!, data = object(row.data);
                        if (data.knowledge_base_id === kbId && data.namespace === graphNamespace(ctx.tenantId, kbId) && (ticket.ticket.operation === 'delete_knowledge_base' || !ticket.skip && data.knowledge_id === ticket.params.knowledge_id && (!ticket.params.generation || data.generation === ticket.params.generation))) this.db.update('generic_resources', String(row.id), { status: 'retired', updated_at: now() });
                    }
                    if (base.deleted_at === null) this.publishRelations(ctx, kbId);
                });
                const result = this.integrations ? await this.integrations.cleanupScopedNeo4j(ctx, kbId, item.key, { signal: options.signal }) : ticket.skip ? { state: 'connected', records: [] } : this.transport ? await this.transport(ctx, kbId, ticket.statement, ticket.params, { signal: options.signal, write: true }) : { state: 'not_configured' };
                check(options.signal); cleanupScope(this.db, this.auth, ctx, kbId);
                if (pendingCleanup(this.db, this.auth, ctx, kbId, item.key).raw !== ticket.raw) fail(409, 'graph_cleanup_ticket_changed', 'Graph cleanup ticket changed');
                if (!['connected', 'disabled', 'not_configured'].includes(String(result.state)) || result.state === 'connected' && !Array.isArray(result.records)) fail(502, 'graph_invalid_response', 'Graph service returned an invalid result');
                const completed = result.state === 'connected';
                results.push({ status: completed ? 'completed' : 'pending', remote_cleanup: completed ? 'completed' : 'pending', reason: result.state!, ...(ticket.ticket.knowledge_id ? { knowledge_id: ticket.ticket.knowledge_id } : {}) });
                if (completed) this.db.transaction(() => { cleanupScope(this.db, this.auth, ctx, kbId); if (pendingCleanup(this.db, this.auth, ctx, kbId, item.key).raw !== ticket.raw) fail(409, 'graph_cleanup_ticket_changed', 'Graph cleanup ticket changed'); this.db.run('UPDATE desktop_meta SET value=? WHERE key=? AND value=?', JSON.stringify({ ...ticket.ticket, status: 'completed', completed_at: now() }), item.key, ticket.raw); });
                else warnings.push(warning('graph_cleanup_pending', 'graph', 'Local deletion is complete; remote graph cleanup remains pending'));
            } catch (error) {
                check(options.signal); cleanupScope(this.db, this.auth, ctx, kbId);
                if (!(error instanceof AppError) || !(error.status >= 500 || error.code.startsWith('graph_cleanup_') || error.code === 'integration_invalid_endpoint')) throw error;
                results.push({ status: 'pending', remote_cleanup: 'pending', reason: error.code });
                warnings.push(warning('graph_cleanup_pending', 'graph', 'Local deletion is complete; remote graph cleanup failed and can be retried'));
            }
        }
        const remaining = this.db.all("SELECT value FROM desktop_meta WHERE key LIKE 'knowledge.graph.pending:%'").filter(row => { try { const ticket = object(JSON.parse(String(row.value))); return ticket.tenant_id === ctx.tenantId && ticket.knowledge_base_id === kbId && ticket.status === 'pending'; } catch { return false; } }).length;
        return { processed: results.length, remaining, results, warnings };
    }
    search(ctx: AuthContext, requested: string | string[], query: string, options: {
        signal?: AbortSignal;
        limit?: number;
        seenChunkIds?: string[];
    } = {}): Promise<JsonObject> {
        return this.operation(options.signal, signal => this.searchSources(ctx, requested, query, { ...options, signal }));
    }
    private async searchSources(ctx: AuthContext, requested: string | string[], query: string, options: {
        signal?: AbortSignal;
        limit?: number;
        seenChunkIds?: string[];
    }): Promise<JsonObject> {
        const kbIds = typeof requested === 'string' ? [requested] : [...new Set(requested)];
        if (!kbIds.length)
            return { state: 'connected', items: [], warnings: [] };
        const eligible: string[] = [], warnings: JsonObject[] = [];
        for (const id of kbIds) {
            const base = this.scope(ctx, id);
            const local = this.snapshots(ctx, id).some(s => s.data.storage === 'legacy_sqlite');
            const readiness = booleanValue(object(base.indexing_strategy).graph_enabled) ? local ? { state: 'connected' } : await this.query(ctx, id, readGenerations, { active: [], offset: 0, limit: 1 }, { signal: options.signal }) : { state: 'disabled' };
            if (readiness.state === 'connected')
                eligible.push(id);
            else
                warnings.push(warning('graph_needs_configuration', 'graph', 'Configure and enable Neo4j before graph query extraction'));
        }
        if (!eligible.length)
            return { state: 'pending', items: [], warnings };
        const cfg = configuration(this.models, ctx);
        if (!cfg)
            return { state: 'model_not_configured', items: [], warnings: [warning('graph_query_needs_configuration', 'graph', 'Configure an extraction model to identify query entities')] };
        const extracted = parseGraph(await completion(this.db, this.auth, this.models, ctx, cfg, `GRAPH_QUERY\nExtract query entities, strict JSON {"node":[{"name":"..."}],"relation":[]}.\nQUERY: ${query.slice(0, 12000)}`, 'graph_query_extract', { signal: options.signal, knowledgeBaseId: eligible[0]!, action: 'read' })), names = extracted.node.map(n => n.name.toLocaleLowerCase()), selected = new Set<string>(options.seenChunkIds), results: JsonObject[] = [];
        for (const id of eligible) {
            const data = await this.dataset(ctx, id, options.signal);
            warnings.push(...data.warnings);
            const matching = data.nodes.filter(n => names.some(name => String(n.name).toLocaleLowerCase().includes(name))), candidates = strings(matching.flatMap(n => array(n.chunks)), 10000), lookup = new Map(chunks(this.db, ctx, id).map(c => [String(c.id), c]));
            for (const chunkId of candidates) {
                if (selected.has(chunkId))
                    continue;
                const chunk = lookup.get(chunkId);
                if (!chunk)
                    continue;
                selected.add(chunkId);
                const doc = this.db.read('knowledges', String(chunk.knowledge_id))!;
                results.push({ id: chunkId, chunk_id: chunkId, content: chunk.content!, knowledge_id: chunk.knowledge_id!, knowledge_base_id: id, knowledge_title: doc.title!, knowledge_base_name: this.db.read('knowledge_bases', id)!.name!, metadata: chunk.metadata!, score: 1, match_type: 'graph' });
            }
        }
        return { state: warnings.length ? 'pending' : 'connected', items: results.slice(0, options.limit ?? 10), warnings };
    }
    async close(): Promise<void> { this.closed = true; for (const controller of this.controllers)
        controller.abort(); await Promise.allSettled([...this.active]); }
}
