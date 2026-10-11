import type { Json, JsonObject } from '../contracts.js';
import { AppError } from '../errors.js';

export class KnowledgeError extends AppError {
  constructor(status: number, code: string, message: string) { super(status, code, message); this.name = 'KnowledgeError'; }
}
export function fail(status: number, code: string, message: string): never { throw new KnowledgeError(status, code, message); }
export const object = (value: unknown): JsonObject => value && typeof value === 'object' && !Array.isArray(value) ? value as JsonObject : {};
export function input(value: unknown): JsonObject {
  if (!value || typeof value !== 'object' || Array.isArray(value)) fail(400, 'invalid_payload', 'Payload must be an object');
  return value as JsonObject;
}
export function text(value: unknown, limit = 65536): string {
  if (typeof value !== 'string' || value.length > limit) fail(400, 'invalid_field', 'Invalid text field');
  return value as string;
}
export const enabled = (value: unknown, fallback = false): boolean => value == null ? fallback : typeof value === 'boolean' ? value : ['1', 'true', 'yes', 'on', 'enabled'].includes(String(value).toLowerCase());
export const searchableTypes = new Set(['text', 'image_ocr', 'image_caption']);
export const processingStatuses = new Set(['pending', 'processing', 'finalizing']);
export const defaultChunking: JsonObject = { strategy: 'auto', chunk_size: 512, chunk_overlap: 80, enable_parent_child: true, parent_chunk_size: 2048, child_chunk_size: 384, child_chunk_overlap: 64, token_limit: 0, semantic_window_size: 3, semantic_breakpoint_percentile: 90 };
const aliases: Record<string, string> = { chunkSize: 'chunk_size', chunkOverlap: 'chunk_overlap', enableParentChild: 'enable_parent_child', parentChunkSize: 'parent_chunk_size', childChunkSize: 'child_chunk_size', childChunkOverlap: 'child_chunk_overlap', tokenLimit: 'token_limit', semanticWindowSize: 'semantic_window_size', semanticBreakpointPercentile: 'semantic_breakpoint_percentile' };
const strategies = new Set(['auto', 'recursive', 'heading', 'layout', 'record', 'semantic']);
const ranges: Record<string, [number, number]> = { chunk_size: [128, 4096], parent_chunk_size: [512, 8192], child_chunk_size: [128, 2048], token_limit: [0, 32768], semantic_window_size: [1, 32] };
export function chunking(raw: unknown): JsonObject {
  const source = raw == null ? {} : input(raw), result: JsonObject = { ...source, ...defaultChunking };
  for (const key of Object.keys(defaultChunking)) if (key in source) result[key] = source[key]!;
  if (!strategies.has(String(result.strategy)) || typeof result.enable_parent_child !== 'boolean') fail(400, 'invalid_chunking_config', 'Invalid chunking strategy or parent-child flag');
  for (const [key, [min, max]] of Object.entries(ranges)) {
    if (typeof result[key] === 'boolean' || !['number', 'string'].includes(typeof result[key])) fail(400, 'invalid_chunking_config', 'Invalid chunking integer');
    const n = Number(result[key]);
    if (!Number.isSafeInteger(n) || n < min || n > max) fail(400, 'invalid_chunking_config', 'Chunking value is outside its supported range');
    result[key] = n;
  }
  for (const [overlap, size] of [['chunk_overlap', 'chunk_size'], ['child_chunk_overlap', 'child_chunk_size']]) {
    const n = Number(result[overlap!]);
    if (typeof result[overlap!] === 'boolean' || !['number', 'string'].includes(typeof result[overlap!]) || !Number.isSafeInteger(n) || n < 0 || n > Number(result[size!]) / 2) fail(400, 'invalid_chunking_config', 'Chunk overlap cannot exceed half the chunk size');
    result[overlap!] = n;
  }
  const percentile = Number(result.semantic_breakpoint_percentile);
  if (typeof result.semantic_breakpoint_percentile === 'boolean' || !['number', 'string'].includes(typeof result.semantic_breakpoint_percentile) || !Number.isFinite(percentile) || percentile < 0 || percentile > 100 || Number(result.parent_chunk_size) < Number(result.child_chunk_size)) fail(400, 'invalid_chunking_config', 'Invalid semantic percentile or parent size');
  result.semantic_breakpoint_percentile = percentile;
  return result;
}
/** Historical JSON is projected, never rewritten during reads. Opaque fields remain stored. */
export function projectedChunking(raw: unknown): { config: JsonObject; compatible: boolean } {
  const source = { ...object(raw) }, result = { ...defaultChunking }; let compatible = !!raw && typeof raw === 'object' && !Array.isArray(raw);
  for (const [old, key] of Object.entries(aliases)) if (old in source && !(key in source)) { source[key] = source[old]!; compatible = false; }
  if ('strategy' in source) { if (strategies.has(String(source.strategy))) result.strategy = source.strategy!; else compatible = false; }
  for (const [key, [min, max]] of Object.entries(ranges)) if (key in source) {
    const n = typeof source[key] === 'boolean' ? NaN : Number(source[key]);
    result[key] = Number.isFinite(n) ? Math.max(min, Math.min(Math.trunc(n), max)) : defaultChunking[key]!;
    if (!Number.isSafeInteger(n) || result[key] !== n) compatible = false;
  }
  if ('enable_parent_child' in source) {
    const value = source.enable_parent_child;
    if (typeof value === 'boolean' || value === 0 || value === 1 || ['1', 'true', 'yes', 'on', 'enabled', '0', 'false', 'no', 'off', 'disabled'].includes(String(value).toLowerCase())) result.enable_parent_child = enabled(value);
    else compatible = false;
  }
  for (const [key, size] of [['chunk_overlap', 'chunk_size'], ['child_chunk_overlap', 'child_chunk_size']]) {
    const n = key! in source && typeof source[key!] !== 'boolean' ? Number(source[key!]) : Number(defaultChunking[key!]);
    result[key!] = Number.isFinite(n) ? Math.max(0, Math.min(Math.trunc(n), Math.floor(Number(result[size!]) / 2))) : defaultChunking[key!]!;
    if (!Number.isSafeInteger(n) || n !== result[key!]) compatible = false;
  }
  if ('semantic_breakpoint_percentile' in source) { const n = typeof source.semantic_breakpoint_percentile === 'boolean' ? NaN : Number(source.semantic_breakpoint_percentile); result.semantic_breakpoint_percentile = Number.isFinite(n) ? Math.max(0, Math.min(n, 100)) : 90; if (!Number.isFinite(n) || n !== result.semantic_breakpoint_percentile) compatible = false; }
  if (Number(result.parent_chunk_size) < Number(result.child_chunk_size)) { result.parent_chunk_size = result.child_chunk_size!; compatible = false; }
  try { const strict = chunking(raw); if (Object.keys(defaultChunking).some(key => strict[key] !== result[key])) compatible = false; } catch { compatible = false; }
  return { config: result, compatible };
}
export function effectiveChunking(kb: unknown, process: unknown): JsonObject {
  const config = object(process), override = config.chunking_config ?? config.chunkingConfig;
  return chunking({ ...projectedChunking(kb).config, ...(override == null ? {} : input(override)) });
}
export function indexing(raw: unknown, type = 'document'): JsonObject {
  const source = object(raw);
  return Object.fromEntries(['vector_enabled', 'keyword_enabled', 'wiki_enabled', 'graph_enabled'].map(key => [key, key === 'wiki_enabled' && type === 'wiki' || enabled(source[key], true)]));
}
export const defaultExtract: JsonObject = { enabled: true, text: '从知识片段中抽取核心实体和实体关系，用于 GraphRAG 检索增强。', tags: ['related_to', 'part_of', 'depends_on', 'uses', 'causes', 'describes'], nodes: [{ name: 'Entity', attributes: ['name', 'description'] }, { name: 'Concept', attributes: ['name', 'description'] }], relations: [{ node1: 'Entity', node2: 'Entity', type: 'related_to' }, { node1: 'Entity', node2: 'Concept', type: 'describes' }] };
export function validateExtract(raw: Json): void {
  if (raw === null) return;
  const value = input(raw); if (!enabled(value.enabled)) return;
  if (!String(value.text ?? '').trim() || !Array.isArray(value.tags) || !value.tags.some(tag => String(tag).trim()) || !Array.isArray(value.nodes) || !value.nodes.length || !Array.isArray(value.relations) || !value.relations.length) fail(400, 'invalid_extract_config', 'Graph extraction text, tags, nodes and relations are required');
  const names = value.nodes.map(node => String(object(node).name ?? '').trim());
  if (names.some(name => !name) || new Set(names).size !== names.length) fail(400, 'invalid_extract_config', 'Graph nodes require unique names');
  for (const relation of value.relations) { const r = object(relation); if (!names.includes(String(r.node1)) || !names.includes(String(r.node2)) || !String(r.type ?? '').trim()) fail(400, 'invalid_extract_config', 'Graph relation references an unknown node or has no type'); }
}
export function ids(value: unknown): string[] {
  if (typeof value === 'string') value = value.split(',');
  if (!Array.isArray(value)) fail(400, 'invalid_ids', 'Document identifiers must be a list');
  const result = [...new Set((value as unknown[]).map(id => text(id, 64).trim()).filter(Boolean))];
  if (result.length > 900) fail(400, 'invalid_ids', 'Too many document identifiers');
  return result;
}
export const csv = (value: unknown): string[] => value ? (Array.isArray(value) ? value : String(value).split(',')).map(String).map(x => x.trim()).filter(Boolean) : [];
const bounded = (value: unknown, fallback: number, min: number, max = Number.MAX_SAFE_INTEGER) => { const n = Number(value ?? fallback); return Number.isFinite(n) ? Math.max(min, Math.min(Math.trunc(n), max)) : fallback; };
export interface Page extends JsonObject { items: JsonObject[]; page: number; page_size: number; total: number }
export function paginate(items: JsonObject[], query: JsonObject = {}): Page {
  const size = bounded(query.page_size ?? query.limit, 20, 1, 100), offset = 'offset' in query && !('page' in query) ? bounded(query.offset, 0, 0) : (bounded(query.page, 1, 1) - 1) * size;
  return { items: items.slice(offset, offset + size), page: Math.floor(offset / size) + 1, page_size: size, total: items.length };
}
