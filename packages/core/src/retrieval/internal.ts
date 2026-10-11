import { createHash } from 'node:crypto';
import type { JsonObject, ModelUsage } from '../contracts.js';
import type { BindValue, CoreDatabase, Row } from '../storage/database.js';
import type { SearchScope, SearchHit } from './types.js';

export class RetrievalError extends Error {
  constructor(public readonly code: string, message: string) { super(message); this.name = 'RetrievalError'; }
}
export class IndexUsageError extends RetrievalError {
  readonly providerResponded=true;
  constructor(readonly usage: ModelUsage) { super('index_usage_handler_failed','Model provider responded, but the usage observer failed; do not replay the model call'); }
}
export function integer(value: unknown): bigint {
  if (typeof value === 'number' && !Number.isSafeInteger(value)) throw new RetrievalError('unsafe_id', 'Integer identifier must preserve exact precision');
  if (!['number','string','bigint'].includes(typeof value) || !/^\d+$/.test(String(value))) throw new RetrievalError('invalid_id', 'Integer identifier must be decimal');
  const result = BigInt(String(value));
  if (result < 0 || result > 9223372036854775807n) throw new RetrievalError('invalid_id', 'Integer identifier exceeds SQLite range');
  return result;
}
export function bounded(value: number | undefined, fallback: number, min = 0, max = 10000): number {
  const result = value ?? fallback;
  if (!Number.isSafeInteger(result) || result < min || result > max) throw new RetrievalError('invalid_limit', 'Retrieval limit is outside its supported range');
  return result;
}
export function cancelled(signal?: AbortSignal): void {
  if (signal?.aborted) throw new RetrievalError('retrieval_cancelled', 'Retrieval was cancelled');
}
export function hash(value: string): string { return createHash('sha256').update(value).digest('hex'); }
export function scopeClause(scope: SearchScope, column = 'c'): { sql: string; binds: BindValue[] } {
  const binds: BindValue[] = [integer(scope.tenantId)];
  let sql = `${column}.tenant_id=?`;
  if (scope.knowledgeBaseIds !== undefined) {
    if (!Array.isArray(scope.knowledgeBaseIds) || scope.knowledgeBaseIds.some(value => typeof value !== 'string' || !value)) throw new RetrievalError('invalid_scope', 'Knowledge base scope must be an array of identifiers');
    const ids = [...new Set(scope.knowledgeBaseIds)];
    if (ids.length > 900) throw new RetrievalError('invalid_scope', 'Knowledge base scope exceeds the parameter limit');
    if (!ids.length) sql += ' AND 0';
    else { sql += ` AND ${column}.knowledge_base_id IN (${ids.map(() => '?').join(',')})`; binds.push(...ids); }
  }
  return { sql, binds };
}
export const joins = `FROM chunks c JOIN knowledges d ON d.id=c.knowledge_id
  JOIN knowledge_bases b ON b.id=c.knowledge_base_id JOIN tenants t ON t.id=c.tenant_id`;
export const active = `c.deleted_at IS NULL AND d.deleted_at IS NULL AND b.deleted_at IS NULL
  AND t.deleted_at IS NULL AND t.status='active' AND d.enable_status='enabled'
  AND c.tenant_id=d.tenant_id AND c.tenant_id=b.tenant_id AND d.knowledge_base_id=c.knowledge_base_id`;
export const searchable = `${active} AND c.is_enabled=1 AND c.chunk_type IN ('text','image_ocr','image_caption')`;
export interface ChunkRecord {
  id: string; seq_id: string | null; tenant_id: string; knowledge_base_id: string; knowledge_id: string; content: string;
  chunk_index: number; start_at: number; end_at: number; chunk_type: string; context_header: string; context_parent_id: string | null;
  updated_at: string; metadata: JsonObject; image_info: JsonObject | null; knowledge_metadata: JsonObject;
  knowledge_title: string; knowledge_description: string; knowledge_base_name: string; embedding_model_id: string;
}
function json(value: unknown): JsonObject {
  const decoded = typeof value === 'string' ? JSON.parse(value) : value;
  return decoded && typeof decoded === 'object' && !Array.isArray(decoded) ? decoded as JsonObject : {};
}
export function records(db: CoreDatabase, scope: SearchScope, includeParents = false, chunkId?: string, includeKnowledgeMetadata = true): ChunkRecord[] {
  const clause = scopeClause(scope);
  const rows = db.all(`SELECT c.*,d.title AS knowledge_title,d.description AS knowledge_description,b.name AS knowledge_base_name,
    coalesce(nullif(d.embedding_model_id,''),b.embedding_model_id) AS resolved_model
    ${joins} WHERE ${clause.sql} AND ${includeParents ? active : searchable}${chunkId === undefined ? '' : ' AND c.id=?'} ORDER BY c.id`,
    ...clause.binds, ...(chunkId === undefined ? [] : [chunkId]));
  const documents = new Map<string, JsonObject>();
  if (includeKnowledgeMetadata) {
    const documentScope = scopeClause(scope, 'd');
    for (const row of rows) {
      const id = String(row.knowledge_id);
      if (documents.has(id)) continue;
      const source = db.get(`SELECT d.metadata FROM knowledges d
        JOIN knowledge_bases b ON b.id=d.knowledge_base_id JOIN tenants t ON t.id=d.tenant_id
        WHERE ${documentScope.sql} AND d.id=? AND d.knowledge_base_id=? AND d.deleted_at IS NULL
        AND d.enable_status='enabled' AND b.tenant_id=d.tenant_id AND b.deleted_at IS NULL
        AND t.deleted_at IS NULL AND t.status='active'`, ...documentScope.binds, id, String(row.knowledge_base_id));
      if (source) documents.set(id, json(source.metadata));
    }
  }
  return rows.flatMap(row => {
    if (includeKnowledgeMetadata && !documents.has(String(row.knowledge_id))) return [];
    const numeric = (field: string) => { const n = Number(row[field]); if (!Number.isSafeInteger(n)) throw new RetrievalError('invalid_offset', 'Chunk offsets must be safe codepoint integers'); return n; };
    return [{ id: String(row.id), seq_id: row.seq_id === null ? null : integer(row.seq_id).toString(), tenant_id: String(row.tenant_id),
      knowledge_base_id: String(row.knowledge_base_id), knowledge_id: String(row.knowledge_id), content: String(row.content),
      chunk_index: numeric('chunk_index'), start_at: numeric('start_at'), end_at: numeric('end_at'), chunk_type: String(row.chunk_type),
      context_header: String(row.context_header), context_parent_id: row.context_parent_id === null ? null : String(row.context_parent_id),
      updated_at: String(row.updated_at), metadata: json(row.metadata), image_info: row.image_info === null ? null : json(row.image_info),
      knowledge_metadata: documents.get(String(row.knowledge_id)) ?? {}, knowledge_title: String(row.knowledge_title), knowledge_description: String(row.knowledge_description),
      knowledge_base_name: String(row.knowledge_base_name), embedding_model_id: String(row.resolved_model) }];
  });
}
/** Fence the embedded source, not auxiliary summary/wiki/workflow bookkeeping. */
export function fingerprint(row: ChunkRecord): string {
  return hash(JSON.stringify(['embedding-source-v2', row.id, row.seq_id, row.tenant_id,
    row.knowledge_base_id, row.knowledge_id, row.chunk_type, row.start_at, row.end_at,
    row.context_parent_id, row.embedding_model_id, row.metadata.source_generation ?? null,
    row.knowledge_metadata.source_generation ?? null, embeddingContent(row)]));
}
export function embeddingContent(row: ChunkRecord): string { return [row.context_header, row.content].filter(Boolean).join('\n\n'); }
export function hit(row: ChunkRecord): SearchHit {
  return { id: row.id, chunk_id: row.id, seq_id: row.seq_id ?? '', content: row.content, score: 0, rrf_score: 0, keyword_rank: null,
    vector_rank: null, rerank_score: null, match_sources: [], retrieval_path: 'document', knowledge_id: row.knowledge_id,
    knowledge_base_id: row.knowledge_base_id, knowledge_title: row.knowledge_title, knowledge_description: row.knowledge_description,
    knowledge_base_name: row.knowledge_base_name, chunk_type: row.chunk_type, context_parent_id: row.context_parent_id,
    image_info: row.image_info, metadata: row.metadata };
}
export function pack(vector: number[], dimension: number): Buffer {
  if (!Number.isSafeInteger(dimension) || dimension < 1 || dimension > 65536 || !Array.isArray(vector) || vector.length !== dimension) throw new RetrievalError('embedding_dimension_mismatch', 'Embedding dimension does not match its index space');
  const result = Buffer.alloc(dimension * 4);
  vector.forEach((value, index) => {
    if (typeof value !== 'number' || !Number.isFinite(value) || !Number.isFinite(Math.fround(value))) throw new RetrievalError('embedding_invalid', 'Embedding must contain finite float32 values');
    result.writeFloatLE(value, index * 4);
  });
  return result;
}
