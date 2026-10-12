import type { DatabaseReader } from '../storage/read-database.js';
import type { SearchScope, VectorState } from './types.js';
import { scopeClause } from './internal.js';

export interface IndexStateReader { state(scope: SearchScope): VectorState[]; }

/** Pure state projection: construction does not initialize retrieval tables. */
export function readIndexState(db: DatabaseReader, scope: SearchScope): VectorState[] {
  const clause=scopeClause(scope,'m');
  return db.all(`SELECT m.* FROM search_index_meta m JOIN knowledge_bases b ON b.id=m.knowledge_base_id
      JOIN tenants t ON t.id=m.tenant_id WHERE ${clause.sql} AND m.id LIKE 'active:%' AND b.tenant_id=m.tenant_id
      AND b.deleted_at IS NULL AND t.deleted_at IS NULL AND t.status='active' ORDER BY m.knowledge_base_id`,...clause.binds)
    .map(row=>({id:String(row.id),tenant_id:String(row.tenant_id),knowledge_base_id:String(row.knowledge_base_id),model_signature:String(row.model_signature),dimension:Number(row.dimension),generation:String(row.generation),status:String(row.status)}));
}
