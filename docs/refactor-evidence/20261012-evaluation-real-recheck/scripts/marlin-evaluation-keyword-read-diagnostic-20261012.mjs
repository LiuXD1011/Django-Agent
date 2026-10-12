import { writeFileSync, readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { ReadDatabase } from '/home/liuxuedeng/Django-Agent/packages/core/src/storage/read-database.ts';
import { joins, searchable, scopeClause } from '/home/liuxuedeng/Django-Agent/packages/core/src/retrieval/internal.ts';

const root='/home/liuxuedeng/Django-Agent', dataRoot='/home/liuxuedeng/.local/share/marlin-refactor/20261010-browser-qa';
const db=new ReadDatabase(`${dataRoot}/marlin.sqlite3`,dataRoot), kbId='86f94109-c3f2-4cba-819e-d7bfdea42709';
let result;
try {
  result=db.snapshot(()=>{
    const scope={tenantId:'2',knowledgeBaseIds:[kbId]},clause=scopeClause(scope);
    const tenant=db.read('tenants','2'),saved=tenant.retrieval_config ?? {};
    const fields=['embedding_top_k','rerank_top_k','keyword_top_k','vector_threshold','keyword_threshold','rerank_threshold','rerank_enabled'];
    const mainChunks=db.all(`SELECT c.id,c.knowledge_id,c.content,c.start_at,c.end_at,c.chunk_type ${joins} WHERE ${clause.sql} AND ${searchable}`, ...clause.binds);
    const entries=[];
    for(const datasetId of ['2f99f534-5d8a-45b8-ba67-3ddd87f740d5','6c630a4d-309d-4dfd-8bac-b31bfdd20bec']) {
      const dataset=db.read('generic_resources',datasetId);
      for(const entry of dataset.data.entries) entries.push({...entry,dataset_id:datasetId});
    }
    const queries=entries.map(entry=>{
      const query=entry.question,words=query.match(/[\p{L}\p{N}_]+/gu)??[],long=words.filter(word=>Array.from(word).length>=3);
      const bind=long.length?long.map(word=>`"${word.replaceAll('"','""')}"`).join(' OR '):`%${query.trim().replace(/[\\%_]/g,'\\$&')}%`;
      const condition=long.length?'chunks_fts MATCH ?':"chunks_fts.content LIKE ? ESCAPE '\\'";
      const from=long.length?joins.replace('FROM chunks c','FROM chunks_fts CROSS JOIN chunks c INDEXED BY retrieval_chunk_sequence'):`${joins} JOIN chunks_fts ON chunks_fts.rowid=c.seq_id`;
      const hits=db.all(`SELECT c.id,c.knowledge_id,c.start_at,c.end_at,c.content ${from} WHERE ${long.length?'chunks_fts.rowid=c.seq_id AND ':''}${clause.sql} AND c.seq_id IS NOT NULL AND ${searchable} AND ${condition} ORDER BY ${long.length?'bm25(chunks_fts),c.id':'c.chunk_index,c.id'} LIMIT ?`,...clause.binds,bind,80);
      return {dataset_id:entry.dataset_id,entry_id:entry.id,query,words,long_terms:long,actual_match_expression:bind,stored_keyword_candidate_count:hits.length,hits,
        declared_evidence:entry.evidence.map(e=>({...e,currently_overlapping_searchable_chunks:mainChunks.filter(c=>c.knowledge_id===e.knowledge_id && c.start_at<e.source_end && c.end_at>e.source_start).map(c=>({id:c.id,start_at:c.start_at,end_at:c.end_at}))}))};
    });
    const controls=['P1','林青','传感器'].map(query=>({query,hits:db.all(`SELECT c.id,c.knowledge_id,c.start_at,c.end_at ${joins} JOIN chunks_fts ON chunks_fts.rowid=c.seq_id WHERE ${clause.sql} AND ${searchable} AND chunks_fts.content LIKE ?`,...clause.binds,`%${query}%`)}));
    return {created_utc:new Date().toISOString(),readonly_native_connection:true,query_only:true,consistent_snapshot:true,
      fts_schema:db.get("SELECT sql FROM sqlite_master WHERE name='chunks_fts'").sql,
      saved_retrieval_configuration:Object.fromEntries(fields.filter(k=>k in saved).map(k=>[k,saved[k]])),
      deterministic_runtime_limits:{topK:20,keywordTopK:80,vectorTopK:0,rerankTopK:0,threshold_defaults:{keyword:0,vector:0,rerank:0}},
      main_searchable_chunks:mainChunks.map(c=>({id:c.id,knowledge_id:c.knowledge_id,start_at:c.start_at,end_at:c.end_at,chunk_type:c.chunk_type})),
      queries,controls,vendor_requests:0,live_database_writes:0,
      limitation:'Stored production FTS candidates checked with the exact current SearchIndex SQL. The earlier temporary derived database was deleted after evaluation; this does not reconstruct its raw result objects.',
      source_sha256:Object.fromEntries(['packages/core/src/retrieval/search-index.ts','packages/core/src/retrieval/service.ts','packages/core/src/evaluation/deterministic.ts'].map(s=>[s,createHash('sha256').update(readFileSync(`${root}/${s}`)).digest('hex')]))};
  });
} finally {db.close();}
writeFileSync(`${root}/docs/refactor-evidence/20261012-evaluation-real-recheck/088-keyword-query-readonly-diagnostic.json`,JSON.stringify(result,null,2)+'\n');
process.stdout.write(JSON.stringify(result,null,2)+'\n');
