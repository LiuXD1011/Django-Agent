import type { Json, JsonObject } from '../contracts.js';
import { array, jsonPayload, object, strings } from '../wiki/internal.js';
export interface GraphNode {
    name: string;
    type: string;
    attributes: string[];
    chunks: string[];
}
export interface GraphRelation {
    node1: string;
    node2: string;
    type: string;
    strength: number;
    chunks: string[];
    weight: number;
    combined_degree: number;
}
export interface ExtractedGraph {
    node: GraphNode[];
    relation: GraphRelation[];
}
export const defaultExtractConfig: JsonObject = { enabled: true, text: 'Extract core entities and relationships from source chunks.', tags: ['related_to', 'part_of', 'depends_on', 'uses', 'causes', 'describes'], nodes: [{ name: 'Entity', attributes: ['name', 'description'] }, { name: 'Concept', attributes: ['name', 'description'] }], relations: [{ node1: 'Entity', node2: 'Entity', type: 'related_to' }, { node1: 'Entity', node2: 'Concept', type: 'describes' }] };
export function normalizeNodes(values: Json): GraphNode[] {
    const result = new Map<string, GraphNode>();
    for (const value of array(values)) {
        const row = typeof value === 'string' ? { name: value } : object(value), name = String(row.name ?? row.title ?? row.entity ?? '').trim().slice(0, 512);
        if (!name)
            continue;
        const type = String(row.type ?? row.node_type ?? row.entity_type ?? 'Entity').slice(0, 64), key = JSON.stringify([type, name]), attributes = strings(typeof (row.attributes ?? row.entity_attributes) === 'string' ? [row.attributes ?? row.entity_attributes] : row.attributes ?? row.entity_attributes, 32).map(s => s.slice(0, 2048)), chunks = strings(row.chunks, 10000);
        const old = result.get(key);
        result.set(key, { name, type, attributes: strings([...(old?.attributes ?? []), ...attributes], 32), chunks: strings([...(old?.chunks ?? []), ...chunks], 10000) });
    }
    return [...result.values()];
}
export function normalizeRelations(values: Json): GraphRelation[] {
    const result = new Map<string, GraphRelation>();
    for (const value of array(values)) {
        const row = object(value), source = String(row.node1 ?? row.source ?? row.entity1 ?? '').trim().slice(0, 512), target = String(row.node2 ?? row.target ?? row.entity2 ?? '').trim().slice(0, 512), type = String(row.type ?? row.relation ?? row.description ?? 'related_to').trim().slice(0, 128);
        if (!source || !target || source === target || !type)
            continue;
        const n = Number(row.strength ?? row.weight ?? 1), strength = Number.isFinite(n) ? Math.max(1, Math.min(10, Math.trunc(n))) : 1, key = JSON.stringify([source, target, type]), old = result.get(key);
        result.set(key, { node1: source, node2: target, type, strength: Math.max(strength, old?.strength ?? 1), chunks: strings([...(old?.chunks ?? []), ...strings(row.chunks)], 10000), weight: 1, combined_degree: 0 });
    }
    return [...result.values()];
}
/** Original GraphRAG object, array and fenced JSON shapes; malformed output is an explicit failure. */
export function parseGraph(raw: string): ExtractedGraph {
    const payload = jsonPayload(raw), row = object(payload), values = Array.isArray(payload) ? payload : array(row.node ?? row.nodes), relationValues = Array.isArray(payload) ? payload : array(row.relation ?? row.relations);
    const nodes = normalizeNodes(values), relations = normalizeRelations(relationValues), names = new Set(nodes.map(n => n.name));
    for (const relation of relations)
        for (const name of [relation.node1, relation.node2])
            if (!names.has(name)) {
                names.add(name);
                nodes.push({ name, type: 'Entity', attributes: [], chunks: [] });
            }
    return { node: nodes, relation: relations };
}
export function weightGraph(graph: ExtractedGraph): ExtractedGraph {
    const entities = new Map(graph.node.map(n => [n.name, n])), totalEntities = graph.node.reduce((s, n) => s + Math.max(n.chunks.length, 1), 0), totalRelations = graph.relation.reduce((s, r) => s + Math.max(r.chunks.length, 1), 0);
    const pmis = graph.relation.map(r => { const p = Math.max(entities.get(r.node1)?.chunks.length ?? 0, 1) / totalEntities, q = Math.max(entities.get(r.node2)?.chunks.length ?? 0, 1) / totalEntities; return Math.max(0, Math.log2(Math.max(r.chunks.length, 1) / totalRelations / (p * q))); }), maxPMI = Math.max(0, ...pmis), maxStrength = Math.max(1, ...graph.relation.map(r => r.strength));
    const degree = (name: string) => graph.relation.filter(r => r.node1 === name || r.node2 === name).length;
    graph.relation.forEach((r, i) => { r.weight = 1 + 9 * ((maxPMI ? pmis[i]! / maxPMI : 0) * 0.6 + r.strength / maxStrength * 0.4); r.combined_degree = degree(r.node1) + degree(r.node2); });
    return graph;
}
export function relatedChunks(graph: ExtractedGraph): Map<string, {
    direct: string[];
    indirect: string[];
}> {
    const entity = new Map(graph.node.map(n => [n.name, n.chunks])), adjacency = new Map<string, Map<string, {
        weight: number;
        degree: number;
    }>>();
    const add = (a: string, b: string, weight: number, degree: number) => { const links = adjacency.get(a) ?? new Map(); const old = links.get(b); if (!old || weight > old.weight)
        links.set(b, { weight, degree }); adjacency.set(a, links); };
    for (const r of graph.relation)
        for (const a of entity.get(r.node1) ?? [])
            for (const b of entity.get(r.node2) ?? [])
                if (a !== b) {
                    add(a, b, r.weight, r.combined_degree);
                    add(b, a, r.weight, r.combined_degree);
                }
    const sorted = (values: Map<string, {
        weight: number;
        degree: number;
    }>) => [...values].sort((a, b) => b[1].weight - a[1].weight || b[1].degree - a[1].degree || a[0].localeCompare(b[0])).slice(0, 8).map(([id]) => id), result = new Map<string, {
        direct: string[];
        indirect: string[];
    }>();
    for (const [id, neighbors] of adjacency) {
        const indirect = new Map<string, {
            weight: number;
            degree: number;
        }>();
        for (const [near, first] of neighbors)
            for (const [second, next] of adjacency.get(near) ?? [])
                if (second !== id && !neighbors.has(second)) {
                    const value = { weight: first.weight * next.weight * 0.5, degree: Math.max(first.degree, next.degree) };
                    if (!indirect.has(second) || indirect.get(second)!.weight < value.weight)
                        indirect.set(second, value);
                }
        result.set(id, { direct: sorted(neighbors), indirect: sorted(indirect) });
    }
    return result;
}
