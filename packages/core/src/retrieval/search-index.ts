import { randomUUID } from 'node:crypto';
import type { CoreDatabase, BindValue, Row } from '../storage/database.js';
import type { ModelUsage } from '../contracts.js';
import type { EmbeddingBinding, IndexOptions, SearchScope, SearchHit, VectorState, SyncPublish } from './types.js';
import { IndexUsageError, RetrievalError, active, bounded, cancelled, embeddingContent, fingerprint, hash, hit, integer, joins, pack,
  records, scopeClause, searchable, type ChunkRecord } from './internal.js';
import { resolveParentContext } from './parent-context.js';

/** Uses the existing single core writer connection. Callers supply authorization and an optional synchronous owner fence. */
export class SearchIndex {
  constructor(readonly db: CoreDatabase) {
    db.sqlite.exec(`CREATE INDEX IF NOT EXISTS retrieval_chunk_sequence ON chunks(seq_id);
      CREATE TABLE IF NOT EXISTS retrieval_chunk_ids (
      rowid INTEGER PRIMARY KEY,chunk_id TEXT NOT NULL UNIQUE,tenant_id INTEGER NOT NULL,knowledge_base_id TEXT NOT NULL,knowledge_id TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS retrieval_vector_entries (
      table_name TEXT NOT NULL,rowid INTEGER NOT NULL,chunk_id TEXT NOT NULL,tenant_id INTEGER NOT NULL,
      knowledge_base_id TEXT NOT NULL,knowledge_id TEXT NOT NULL,fingerprint TEXT NOT NULL,PRIMARY KEY(table_name,rowid),UNIQUE(table_name,chunk_id));
      CREATE INDEX IF NOT EXISTS retrieval_entry_chunk ON retrieval_vector_entries(chunk_id);
      CREATE TABLE IF NOT EXISTS retrieval_builds (id TEXT PRIMARY KEY,generation TEXT NOT NULL);`);
  }
  #write(work: () => void, publish?: SyncPublish): void {
    if(publish?.constructor.name==='AsyncFunction') throw new RetrievalError('invalid_publish','Publication must be synchronous');
    this.db.transaction(()=>{
      let ran=false,active=true;
      const commit=()=>{
        if(!active) throw new RetrievalError('invalid_publish','Publication commit is no longer active');
        if(ran) throw new RetrievalError('invalid_publish','Publication must execute once');ran=true;work();
      };
      try {
        if(publish) {
          const result:unknown=publish(commit);active=false;
          if(result && typeof (result as {then?:unknown}).then==='function') {
            void Promise.resolve(result).catch(()=>undefined);
            throw new RetrievalError('invalid_publish','Publication must be synchronous');
          }
          if(!ran) throw new RetrievalError('invalid_publish','Publication did not execute the write');
        } else commit();
      } finally {active=false;}
    });
  }
  #assertGeneration(keys:string[],generation:string): void {
    if(keys.some(key=>this.db.get('SELECT generation FROM retrieval_builds WHERE id=?',key)?.generation!==generation)) {
      throw new RetrievalError('stale_generation','A newer generation superseded this rebuild');
    }
  }
  #scopeRecord(scope: SearchScope, chunkId: string, includeKnowledgeMetadata = true): ChunkRecord | undefined { return records(this.db,scope,false,chunkId,includeKnowledgeMetadata)[0]; }
  /** Only accepts rows selected inside the current scoped write transaction. */
  #rowid(chunk: Row): bigint {
    const chunkId=String(chunk.id);
    const rowid = chunk.seq_id === null ? BigInt(`0x${hash(chunkId).slice(0,15)}`) : integer(chunk.seq_id);
    // Read current global occupancy once per chunk, preserving ordered release
    // of prior IDs inside the same write transaction; never cache across chunks.
    const association = this.db.get(`SELECT
      (SELECT id FROM chunks WHERE seq_id=? AND id<>? LIMIT 1) AS conflicting_id,
      (SELECT chunk_id FROM retrieval_chunk_ids WHERE rowid=?) AS registered_chunk_id,
      (SELECT rowid FROM retrieval_chunk_ids WHERE chunk_id=?) AS previous_rowid`,rowid,chunkId,rowid,chunkId)!;
    if (association.conflicting_id!==null || association.registered_chunk_id!==null && association.registered_chunk_id!==chunkId) throw new RetrievalError('seq_id_collision','Chunk seq_id collision cannot overwrite an index');
    if (association.previous_rowid!==null && integer(association.previous_rowid)!==rowid) { this.db.run('DELETE FROM chunks_fts WHERE rowid=?',integer(association.previous_rowid)); this.#removeVectors(chunkId); this.db.run('DELETE FROM retrieval_chunk_ids WHERE chunk_id=?',chunkId); }
    if (chunk.seq_id===null) this.db.run('UPDATE chunks SET seq_id=? WHERE id=?',rowid,chunkId);
    this.db.run(`INSERT INTO retrieval_chunk_ids(rowid,chunk_id,tenant_id,knowledge_base_id,knowledge_id) VALUES(?,?,?,?,?)
      ON CONFLICT(chunk_id) DO UPDATE SET rowid=excluded.rowid,tenant_id=excluded.tenant_id,knowledge_base_id=excluded.knowledge_base_id,knowledge_id=excluded.knowledge_id`,
      rowid,chunkId,integer(chunk.tenant_id),String(chunk.knowledge_base_id),String(chunk.knowledge_id));
    return rowid;
  }
  #removeVectors(chunkId: string): void {
    for (const entry of this.db.all('SELECT table_name,rowid FROM retrieval_vector_entries WHERE chunk_id=?',chunkId)) {
      const table = this.#validTable(String(entry.table_name)); this.db.run(`DELETE FROM ${table} WHERE rowid=?`,integer(entry.rowid));
    }
    this.db.run('DELETE FROM retrieval_vector_entries WHERE chunk_id=?',chunkId);
  }
  indexKeyword(scope: SearchScope, chunkId: string, publish?: SyncPublish): void {
    this.indexKeywords(scope,[chunkId],publish);
  }
  indexKeywords(scope: SearchScope, chunkIds: string[], publish?: SyncPublish): void {
    const clause=scopeClause(scope),ids=[...new Set(chunkIds)];
    this.#write(()=>{
      // 64 IDs plus the largest accepted KB scope fit below 999 SQLite parameters.
      for(let offset=0;offset<ids.length;offset+=64) {
        const batch=ids.slice(offset,offset+64);
        const rows=this.db.all(`WITH wanted(id) AS (VALUES ${batch.map(()=>'(?)').join(',')})
          SELECT c.id,c.seq_id,c.tenant_id,c.knowledge_base_id,c.knowledge_id,
          c.chunk_index,c.start_at,c.end_at,CASE WHEN ${searchable} THEN 1 ELSE 0 END AS searchable,
          d.title AS knowledge_title,c.context_header,c.content
          FROM wanted CROSS JOIN chunks c LEFT JOIN knowledges d ON d.id=c.knowledge_id
          LEFT JOIN knowledge_bases b ON b.id=c.knowledge_base_id LEFT JOIN tenants t ON t.id=c.tenant_id
          WHERE c.id=wanted.id AND ${clause.sql}`,...batch,...clause.binds);
        const byId=new Map(rows.map(row=>[String(row.id),row])),rowids:bigint[]=[],entries:BindValue[]=[];
        for(const id of batch) {
          const row=byId.get(id);if(!row) continue;
          const rowid=this.#rowid(row);rowids.push(rowid);
          if(row.searchable===1) {
            for(const field of ['chunk_index','start_at','end_at']) if(!Number.isSafeInteger(Number(row[field])))
              throw new RetrievalError('invalid_offset','Chunk offsets must be safe codepoint integers');
            entries.push(rowid,[row.knowledge_title,row.context_header,row.content].map(String).filter(Boolean).join('\n\n'));
          } else this.#removeVectors(id);
        }
        if(rowids.length) this.db.run(`DELETE FROM chunks_fts WHERE rowid IN (${rowids.map(()=>'?').join(',')})`,...rowids);
        if(entries.length) this.db.run(`INSERT INTO chunks_fts(rowid,content) VALUES ${Array.from({length:entries.length/2},()=>'(?,?)').join(',')}`,...entries);
      }
    },publish);
  }
  deleteChunk(scope: SearchScope, chunkId: string, seqId?: string | bigint, publish?: SyncPublish): void {
    const clause=scopeClause(scope,'r');
    this.#write(()=>{
      const ref=this.db.get(`SELECT r.* FROM retrieval_chunk_ids r WHERE ${clause.sql} AND r.chunk_id=?`,...clause.binds,chunkId);
      if(!ref) return;
      if(seqId!==undefined && integer(seqId)!==integer(ref.rowid)) throw new RetrievalError('seq_id_collision','Deletion seq_id does not match the chunk');
      this.db.run('DELETE FROM chunks_fts WHERE rowid=?',integer(ref.rowid)); this.#removeVectors(chunkId);
      this.db.run('DELETE FROM retrieval_chunk_ids WHERE chunk_id=?',chunkId);
    },publish);
  }
  hydrate(scope: SearchScope, chunkId: string): SearchHit | undefined { const row=this.#scopeRecord(scope,chunkId); return row?hit(row):undefined; }
  keyword(scope: SearchScope, query: string, limit: number): SearchHit[] {
    bounded(limit,10); if(!limit || !query.trim()) return [];
    const clause=scopeClause(scope);
    const words=query.match(/[\p{L}\p{N}_]+/gu)??[];
    const long=words.filter(word=>Array.from(word).length>=3);
    let condition: string; const binds: BindValue[]=[...clause.binds];
    // Natural-language short words must not turn trigram terms into a whole-phrase LIKE.
    // Queries with no trigram term retain literal LIKE, including short Chinese and punctuation.
    if(long.length) { condition='chunks_fts MATCH ?'; binds.push(long.map(word=>`"${word.replaceAll('"','""')}"`).join(' OR ')); }
    else { condition="chunks_fts.content LIKE ? ESCAPE '\\'"; binds.push(`%${query.trim().replace(/[\\%_]/g,'\\$&')}%`); }
    const order=condition.startsWith('chunks_fts MATCH')?'bm25(chunks_fts),c.id':'c.chunk_index,c.id';
    // MATCH starts with FTS candidates; short literal LIKE retains a scoped source scan.
    const from=long.length ? joins.replace('FROM chunks c','FROM chunks_fts CROSS JOIN chunks c INDEXED BY retrieval_chunk_sequence')
      : `${joins} JOIN chunks_fts ON chunks_fts.rowid=c.seq_id`;
    const rows=this.db.all(`SELECT c.id ${from}
      WHERE ${long.length?'chunks_fts.rowid=c.seq_id AND ':''}${clause.sql} AND c.seq_id IS NOT NULL AND ${searchable} AND ${condition} ORDER BY ${order} LIMIT ?`,...binds,limit);
    if(!rows.length) return [];
    const byId=new Map(records(this.db,scope,false,rows.map(row=>String(row.id))).map(row=>[row.id,row]));
    return rows.flatMap(row=>{const current=byId.get(String(row.id)); return current?[hit(current)]:[];});
  }
  #stateId(scope: SearchScope, kbId: string): string { return `active:${hash(JSON.stringify([integer(scope.tenantId).toString(),kbId]))}`; }
  state(scope: SearchScope): VectorState[] {
    const clause=scopeClause(scope,'m');
    return this.db.all(`SELECT m.* FROM search_index_meta m JOIN knowledge_bases b ON b.id=m.knowledge_base_id
      JOIN tenants t ON t.id=m.tenant_id WHERE ${clause.sql} AND m.id LIKE 'active:%' AND b.tenant_id=m.tenant_id
      AND b.deleted_at IS NULL AND t.deleted_at IS NULL AND t.status='active' ORDER BY m.knowledge_base_id`,...clause.binds)
      .map(row=>({id:String(row.id),tenant_id:String(row.tenant_id),knowledge_base_id:String(row.knowledge_base_id),model_signature:String(row.model_signature),dimension:Number(row.dimension),generation:String(row.generation),status:String(row.status)}));
  }
  embeddingModelIds(scope: SearchScope): string[] { return [...new Set(records(this.db,scope).map(row=>row.embedding_model_id))]; }
  vectorTable(signature: string, dimension: number, generation: string): string {
    bounded(dimension,2,1,65536);
    if(!signature || !/^[0-9a-f-]{36}$/.test(generation)) throw new RetrievalError('invalid_generation','Vector generation must be a generated UUID');
    return `retrieval_vec_${hash(JSON.stringify([signature,dimension,generation])).slice(0,32)}`;
  }
  #validTable(table: string): string {
    if(!/^retrieval_vec_[a-f0-9]{32}$/.test(table)) throw new RetrievalError('invalid_index_table','Vector table name failed validation'); return table;
  }
  #create(binding: Pick<EmbeddingBinding,'signature'|'dimension'>, generation: string): string {
    const table=this.vectorTable(binding.signature,binding.dimension,generation);
    this.db.sqlite.exec(`CREATE VIRTUAL TABLE IF NOT EXISTS ${table} USING vec0(embedding float[${binding.dimension}] distance_metric=l2)`); return table;
  }
  #put(table: string, row: ChunkRecord, vector: number[], dimension: number): void {
    if(row.seq_id===null) throw new RetrievalError('invalid_id','Chunk must have an exact seq_id before indexing');
    const blob=pack(vector,dimension); const rowid=integer(row.seq_id);
    const prior=this.db.get('SELECT chunk_id FROM retrieval_vector_entries WHERE table_name=? AND rowid=?',table,rowid);
    if(prior && prior.chunk_id!==row.id) throw new RetrievalError('seq_id_collision','Vector seq_id collision cannot overwrite another chunk');
    this.db.run(`DELETE FROM ${table} WHERE rowid=?`,rowid); this.db.run(`INSERT INTO ${table}(rowid,embedding) VALUES(?,?)`,rowid,blob);
    this.db.run(`INSERT INTO retrieval_vector_entries(table_name,rowid,chunk_id,tenant_id,knowledge_base_id,knowledge_id,fingerprint) VALUES(?,?,?,?,?,?,?)
      ON CONFLICT(table_name,rowid) DO UPDATE SET fingerprint=excluded.fingerprint`,table,rowid,row.id,integer(row.tenant_id),row.knowledge_base_id,row.knowledge_id,fingerprint(row));
  }
  #setState(scope: SearchScope, kbId: string, binding: Pick<EmbeddingBinding,'signature'|'dimension'>, generation: string, status: string): void {
    this.db.run(`INSERT INTO search_index_meta(id,tenant_id,knowledge_base_id,model_signature,dimension,generation,status,updated_at) VALUES(?,?,?,?,?,?,?,?)
      ON CONFLICT(id) DO UPDATE SET model_signature=excluded.model_signature,dimension=excluded.dimension,generation=excluded.generation,status=excluded.status,updated_at=excluded.updated_at`,
      this.#stateId(scope,kbId),integer(scope.tenantId),kbId,binding.signature,binding.dimension,generation,status,new Date().toISOString());
  }
  async #usage(usage: ModelUsage, options: IndexOptions): Promise<void> {
    try { await options.onUsage?.(structuredClone(usage)); } catch { throw new IndexUsageError(structuredClone(usage)); }
  }
  async indexChunk(scope: SearchScope, chunkId: string, binding: EmbeddingBinding, options: IndexOptions={}): Promise<{indexed:boolean;usage?:ModelUsage}> {
    cancelled(options.signal); this.indexKeyword(scope,chunkId,options.publish);
    const row=this.#scopeRecord(scope,chunkId); if(!row) return {indexed:false};
    const originalGeneration=this.state({tenantId:scope.tenantId,knowledgeBaseIds:[row.knowledge_base_id]})[0]?.generation;
    this.#assertModel(binding,[row]);
    if(this.db.sqlite.inTransaction) throw new RetrievalError('network_in_transaction','Embedding must run outside a database transaction');
    const result=await binding.runtime.embed([embeddingContent(row)],{signal:options.signal}); await this.#usage(result.usage,options); cancelled(options.signal);
    if(result.vectors.length!==1) throw new RetrievalError('embedding_count_mismatch','Embedding result count does not match the batch');
    pack(result.vectors[0]!,binding.dimension);
    this.#write(()=>{
      cancelled(options.signal); const current=this.#scopeRecord(scope,chunkId);
      if(!current || fingerprint(current)!==fingerprint(row)) throw new RetrievalError('stale_index','Chunk changed before index publication');
      const scoped={tenantId:scope.tenantId,knowledgeBaseIds:[row.knowledge_base_id]};
      const state=this.state(scoped)[0];
      if(state?.generation!==originalGeneration) throw new RetrievalError('stale_generation','A newer generation superseded this incremental index response');
      if(state && (state.model_signature!==binding.signature || state.dimension!==binding.dimension)) throw new RetrievalError('index_space_changed','Model signature changed; a complete rebuild is required');
      const generation=state?.generation??randomUUID(),table=this.#create(binding,generation);
      this.#put(table,current,result.vectors[0]!,binding.dimension);
      const validEntries=new Map(this.db.all('SELECT chunk_id,fingerprint FROM retrieval_vector_entries WHERE table_name=?',table).map(entry=>[String(entry.chunk_id),String(entry.fingerprint)]));
      const ready=records(this.db,scoped).every(chunk=>validEntries.get(chunk.id)===fingerprint(chunk));
      this.#setState(scoped,row.knowledge_base_id,binding,generation,ready?'ready':'needs_rebuild');
    },options.publish);
    return {indexed:true,usage:result.usage};
  }
  #assertModel(binding: EmbeddingBinding, rows: ChunkRecord[]): void {
    bounded(binding.dimension,2,1,65536);
    if(!binding.signature) throw new RetrievalError('invalid_signature','Embedding model signature is required');
    const models=new Set(rows.map(row=>row.embedding_model_id));
    if(models.size>1) throw new RetrievalError('mixed_embedding_spaces','Documents pin different embedding model spaces');
    if(binding.modelId!==undefined && rows.some(row=>row.embedding_model_id && row.embedding_model_id!==binding.modelId)) throw new RetrievalError('embedding_model_mismatch','Embedding binding does not match the document model');
  }
  async rebuild(scope: SearchScope, binding: EmbeddingBinding, options: IndexOptions={}): Promise<{indexed:number;generation:string;usage:ModelUsage[]}> {
    cancelled(options.signal); const initial=records(this.db,scope); this.#assertModel(binding,initial);
    const batchSize=bounded(options.batchSize,32,1,512),generation=randomUUID(),usage:ModelUsage[]=[];
    const kbIds=[...new Set(initial.map(row=>row.knowledge_base_id))];
    const buildKeys=kbIds.map(kb=>this.#stateId(scope,kb));
    this.#write(()=>{for(const key of buildKeys) this.db.run('INSERT INTO retrieval_builds(id,generation) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET generation=excluded.generation',key,generation);},options.publish);
    for(const row of initial) this.indexKeyword(scope,row.id,options.publish);
    const snapshot=records(this.db,scope);
    const table=this.vectorTable(binding.signature,binding.dimension,generation);
    try {
      this.#write(()=>{cancelled(options.signal);this.#create(binding,generation);},options.publish);
      for(let offset=0;offset<snapshot.length;offset+=batchSize) {
        cancelled(options.signal);
        if(this.db.sqlite.inTransaction) throw new RetrievalError('network_in_transaction','Embedding must run outside a database transaction');
        const batch=snapshot.slice(offset,offset+batchSize),result=await binding.runtime.embed(batch.map(embeddingContent),{signal:options.signal});
        usage.push(result.usage);await this.#usage(result.usage,options);
        cancelled(options.signal);
        if(result.vectors.length!==batch.length) throw new RetrievalError('embedding_count_mismatch','Embedding result count does not match the batch');
        result.vectors.forEach(vector=>pack(vector,binding.dimension));
        this.#write(()=>{
          cancelled(options.signal);
          this.#assertGeneration(buildKeys,generation);
          for(let index=0;index<batch.length;index++) this.#put(table,batch[index]!,result.vectors[index]!,binding.dimension);
        },options.publish);
      }
      this.#write(()=>{
        cancelled(options.signal);
        this.#assertGeneration(buildKeys,generation);
        const current=records(this.db,scope);
        if(JSON.stringify(current.map(fingerprint))!==JSON.stringify(snapshot.map(fingerprint))) throw new RetrievalError('stale_generation','Documents changed before rebuild publication');
        for(const kbId of kbIds) this.#setState(scope,kbId,binding,generation,'ready');
      },options.publish);
      return {indexed:snapshot.length,generation,usage};
    } catch(error) {
      // Only this unpublished UUID is removed; previous active tables and business rows remain intact.
      this.db.transaction(()=>{this.db.run('DELETE FROM retrieval_vector_entries WHERE table_name=?',table);this.db.sqlite.exec(`DROP TABLE IF EXISTS ${this.#validTable(table)}`);});
      throw error;
    } finally { this.db.transaction(()=>{for(const key of buildKeys) this.db.run('DELETE FROM retrieval_builds WHERE id=? AND generation=?',key,generation);}); }
  }
  checkSpace(scope: SearchScope, binding: Pick<EmbeddingBinding,'signature'|'dimension'>, options: { verifyFingerprints?: boolean } = {}): VectorState[] {
    const states=this.state(scope);
    const current=records(this.db,scope);
    const indexedKBs=new Set(states.map(state=>state.knowledge_base_id));
    if(!states.length || current.some(row=>!indexedKBs.has(row.knowledge_base_id))) throw new RetrievalError('vector_reindex_required','Vector index is not ready for every requested knowledge base');
    if(states.some(state=>state.model_signature!==binding.signature || state.dimension!==binding.dimension)) throw new RetrievalError('mixed_embedding_spaces','Vector model signature or dimension differs from the requested space');
    if(states.some(state=>state.status!=='ready')) throw new RetrievalError('vector_reindex_required','Vector generation requires rebuilding');
    if(options.verifyFingerprints) for(const state of states) {
      const table=this.vectorTable(state.model_signature,state.dimension,state.generation);
      const stored=new Map(this.db.all('SELECT chunk_id,fingerprint FROM retrieval_vector_entries WHERE table_name=?',table)
        .map(row=>[String(row.chunk_id),String(row.fingerprint)]));
      if(current.some(row=>row.knowledge_base_id===state.knowledge_base_id && stored.get(row.id)!==fingerprint(row)))
        throw new RetrievalError('vector_reindex_required','Source vectors are stale; rebuild the vector index');
    }
    return states;
  }
  vector(scope: SearchScope, query: number[], binding: Pick<EmbeddingBinding,'signature'|'dimension'>, limit: number): SearchHit[] {
    bounded(limit,10); if(!limit) return [];
    const blob=pack(query,binding.dimension),states=this.checkSpace(scope,binding);
    const scopedRows=records(this.db,scope),ranked=new Map<string,SearchHit>(),tables=new Map<string,Set<string>>();
    for(const state of states) {
      const table=this.vectorTable(state.model_signature,state.dimension,state.generation),kbIds=tables.get(table)??new Set<string>();
      kbIds.add(state.knowledge_base_id);tables.set(table,kbIds);
    }
    for(const [table,kbIds] of tables) {
      const activeRows=scopedRows.filter(row=>kbIds.has(row.knowledge_base_id));
      const bySeq=new Map(activeRows.filter(row=>row.seq_id!==null).map(row=>[row.seq_id!,row]));
      const fingerprints=new Map(this.db.all('SELECT chunk_id,fingerprint FROM retrieval_vector_entries WHERE table_name=?',table).map(row=>[String(row.chunk_id),String(row.fingerprint)]));
      const total=Number(this.db.get(`SELECT count(*) AS count FROM ${table}`)?.count??0); if(!total) continue;
      let k=Math.min(total,Math.max(limit*8,64),4096);
      while(true) {
        const candidates=this.db.all(`SELECT rowid,distance FROM ${table} WHERE embedding MATCH ? AND k=? ORDER BY distance`,blob,k);
        const accepted: SearchHit[]=[];
        for(const candidate of candidates) {
          const row=bySeq.get(integer(candidate.rowid).toString());
          if(row && fingerprints.get(row.id)===fingerprint(row)) accepted.push({...hit(row),distance:Number(candidate.distance)});
        }
        const threshold=accepted.length>=limit?accepted[limit-1]!.distance!:Infinity;
        const last=Number(candidates.at(-1)?.distance??Infinity);
        if(k>=total || accepted.length>=limit && last>threshold) {
          for(const candidate of accepted) ranked.set(candidate.chunk_id,candidate); break;
        }
        if(k>=4096) {
          // vec0 caps K; use the actual sqlite-vec L2 function for an exact scoped scan beyond that cap.
          const clause=scopeClause(scope);
          const exact=this.db.all(`SELECT c.id,vec_distance_L2(v.embedding,?) AS distance ${joins}
            JOIN ${table} v ON v.rowid=c.seq_id JOIN retrieval_vector_entries e ON e.rowid=c.seq_id AND e.table_name=? AND e.chunk_id=c.id
            WHERE ${clause.sql} AND ${searchable} ORDER BY distance,c.id`,blob,table,...clause.binds);
          const byId=new Map(activeRows.map(row=>[row.id,row]));
          for(const candidate of exact) {const row=byId.get(String(candidate.id)); if(row && fingerprints.get(row.id)===fingerprint(row)) ranked.set(row.id,{...hit(row),distance:Number(candidate.distance)});}
          break;
        }
        k=Math.min(total,k*4,4096);
      }
    }
    return [...ranked.values()].sort((a,b)=>a.distance!-b.distance! || a.chunk_id.localeCompare(b.chunk_id)).slice(0,limit);
  }
  resolveParents(scope: SearchScope, hits: SearchHit[], cap: number): SearchHit[] { return resolveParentContext(records(this.db,scope),records(this.db,scope,true),hits,cap); }
}
