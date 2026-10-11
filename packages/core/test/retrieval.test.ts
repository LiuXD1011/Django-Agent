import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { ModelRuntime } from '../src/models/runtime.js';
import { CoreDatabase } from '../src/storage/database.js';
import type { EmbeddingBinding, SearchScope } from '../src/retrieval/types.js';
import { SearchIndex, RetrievalService, rrfFuse, IndexUsageError } from '../src/retrieval/index.js';

function fixture() {
  const directory = mkdtempSync(join(tmpdir(), 'marlin-retrieval-')); const db = new CoreDatabase(directory);
  const tenant = db.insert('tenants', { name: '空间', api_key: 'protocol-only' });
  const kb = db.insert('knowledge_bases', { tenant_id: tenant.id, name: '库' });
  const doc = db.insert('knowledges', { tenant_id: tenant.id, knowledge_base_id: kb.id, title: '预算报告', type: 'file', source: 'upload' });
  const scope: SearchScope = { tenantId: String(tenant.id), knowledgeBaseIds: [String(kb.id)] };
  const index = new SearchIndex(db); let sequence = 100n;
  const chunk = (content: string, values: Record<string, unknown> = {}) => db.insert('chunks', { tenant_id: tenant.id,
    knowledge_base_id: kb.id, knowledge_id: doc.id, content, chunk_index: Number(sequence), seq_id: sequence++, ...values });
  return { db, tenant, kb, doc, scope, index, chunk, close() { db.close(); rmSync(directory, { recursive: true, force: true }); } };
}
function binding(dimension = 2, signature = 'model-a:2', embed = (texts: string[]) => texts.map(() => [1, 0])): EmbeddingBinding {
  return { dimension, signature, runtime: { async embed(texts) { return { vectors: embed(texts), usage: { prompt_tokens: texts.length, completion_tokens: 0, total_tokens: texts.length, cached_tokens: 0, reasoning_tokens: 0 } }; } } };
}
const ids = (rows: Array<{ chunk_id: string }>) => rows.map(row => row.chunk_id);

test('real trigram and scoped LIKE recall Chinese budget and preserve 60-bit identifiers', () => {
  const f = fixture();
  try {
    const precise = 1152921504606846975n;
    const target = f.chunk('沧澜计划预算46.8万元', { seq_id: precise });
    f.index.indexKeyword(f.scope, String(target.id));
    assert.equal(f.db.get('select vec_version() as version')?.version, 'v0.1.9');
    assert.deepEqual(ids(f.index.keyword(f.scope, '沧澜计', 1)), [target.id]);
    assert.deepEqual(ids(f.index.keyword(f.scope, '预算', 1)), [target.id]);
    assert.deepEqual(ids(f.index.keyword(f.scope, '预', 1)), [target.id]);
    assert.equal(f.index.keyword(f.scope, '预算', 1)[0]?.seq_id, precise.toString());
    assert.deepEqual(f.index.keyword({ tenantId: f.tenant.id as number, knowledgeBaseIds: [] }, '预算', 10), []);
    assert.equal(f.index.keyword({ tenantId: f.tenant.id as number }, '预算', 10).length, 1);
  } finally { f.close(); }
});

test('scope and active record consistency apply before LIMIT and LIKE wildcards are literal', () => {
  const f = fixture();
  try {
    const other = f.db.insert('tenants', { name: '其他', api_key: 'other' });
    const otherKb = f.db.insert('knowledge_bases', { tenant_id: other.id, name: '其他库' });
    const otherDoc = f.db.insert('knowledges', { tenant_id: other.id, knowledge_base_id: otherKb.id, type: 'file', title: '其他', source: 'upload' });
    for (let i = 0; i < 70; i++) {
      const row = f.chunk('预算预算沧澜计划', { tenant_id: other.id, knowledge_base_id: otherKb.id, knowledge_id: otherDoc.id });
      f.index.indexKeyword({ tenantId: other.id as number }, String(row.id));
    }
    const target = f.chunk('沧澜计划预算'); f.index.indexKeyword(f.scope, String(target.id));
    assert.deepEqual(ids(f.index.keyword(f.scope, '沧澜计', 1)), [target.id]);
    assert.deepEqual(ids(f.index.keyword(f.scope, '预算', 1)), [target.id]);
    assert.deepEqual(f.index.keyword(f.scope, '%', 1), []);
    const inconsistent = f.chunk('预算', { knowledge_id: otherDoc.id }); f.index.indexKeyword(f.scope, String(inconsistent.id));
    assert(!ids(f.index.keyword(f.scope, '预算', 10)).includes(String(inconsistent.id)));
    f.db.update('knowledges', String(f.doc.id), { enable_status: 'disabled' }); assert.equal(f.index.keyword(f.scope, '预算', 10).length, 0);
  } finally { f.close(); }
});

test('editing, disabling, deleting and rowid collisions do not retain searchable stale content', async () => {
  const f = fixture();
  try {
    const target = f.chunk('旧预算'); await f.index.indexChunk(f.scope, String(target.id), binding());
    f.db.update('chunks', String(target.id), { content: '新的进度' }); f.index.indexKeyword(f.scope, String(target.id));
    assert.equal(f.index.keyword(f.scope, '旧预算', 10).length, 0); assert.equal(f.index.keyword(f.scope, '进度', 10).length, 1);
    assert.equal(f.index.vector(f.scope, [1, 0], binding(), 10).length, 0);
    await f.index.indexChunk(f.scope, String(target.id), binding());
    f.db.update('chunks', String(target.id), { is_enabled: false }); f.index.indexKeyword(f.scope, String(target.id));
    assert.equal(f.index.keyword(f.scope, '进度', 10).length, 0); assert.equal(f.index.vector(f.scope, [1, 0], binding(), 10).length, 0);
    f.db.update('chunks', String(target.id), { is_enabled: true }); await f.index.indexChunk(f.scope, String(target.id), binding());
    const collision = f.chunk('碰撞', { seq_id: target.seq_id }); assert.throws(() => f.index.indexKeyword(f.scope, String(collision.id)), /collision/i);
    f.db.run('delete from chunks where id=?', target.id as string); f.index.deleteChunk(f.scope, String(target.id), String(target.seq_id));
    assert.equal(f.db.get('select count(*) as count from chunks_fts')?.count, 0);
  } finally { f.close(); }
});

test('real L2 vectors expand candidates until out-of-scope records cannot crowd out scoped hits', async () => {
  const f = fixture();
  try {
    const target = f.chunk('向量目标', { seq_id: 1152921504606846974n }); await f.index.indexChunk(f.scope, String(target.id), binding(2, 'model-a:2', () => [[0, 0]]));
    const meta = f.index.state(f.scope)[0]!;
    const table = f.index.vectorTable(meta.model_signature, meta.dimension, meta.generation);
    const other = f.db.insert('tenants', { name: '外部', api_key: 'foreign' });
    const kb = f.db.insert('knowledge_bases', { tenant_id: other.id, name: '外部库' });
    const doc = f.db.insert('knowledges', { tenant_id: other.id, knowledge_base_id: kb.id, type: 'file', title: '外部', source: 'upload' });
    for (let i = 0; i < 70; i++) {
      const row = f.chunk('外部', { tenant_id: other.id, knowledge_base_id: kb.id, knowledge_id: doc.id });
      f.db.run(`insert into ${table}(rowid,embedding) values(?,?)`, BigInt(String(row.seq_id)), Buffer.from(new Float32Array([0.99, 0]).buffer));
    }
    const result = f.index.vector(f.scope, [1, 0], binding(), 1);
    assert.deepEqual(ids(result), [target.id]); assert.equal(result[0]?.distance, 1);
    assert.equal(result[0]?.seq_id, '1152921504606846974');
    assert.throws(() => f.index.vectorTable('a', 2, 'unsafe; DROP TABLE chunks'), /generation/i);
  } finally { f.close(); }
});

test('failed or cancelled generations preserve ready vectors and wrong dimensions never become ready', async () => {
  const f = fixture();
  try {
    const target = f.chunk('预算'); await f.index.rebuild(f.scope, binding());
    const original = f.index.state(f.scope)[0]!;
    await assert.rejects(f.index.rebuild(f.scope, binding(2, 'model-a:2', () => [[1]])), /dimension/i);
    assert.equal(f.index.state(f.scope)[0]?.generation, original.generation);
    assert.equal(f.index.vector(f.scope, [1, 0], binding(), 10).length, 1);
    const controller = new AbortController();
    const cancel = binding(2, 'model-a:2', texts => { controller.abort(); return texts.map(() => [0, 1]); });
    await assert.rejects(f.index.rebuild(f.scope, cancel, { signal: controller.signal }), /cancel/i);
    assert.equal(f.index.state(f.scope)[0]?.generation, original.generation);
    await f.index.rebuild(f.scope, binding(3, 'model-b:3', texts => texts.map(() => [1, 0, 0])));
    assert.equal(f.index.state(f.scope)[0]?.dimension, 3); assert.equal(f.index.state(f.scope)[0]?.model_signature, 'model-b:3');
    assert.throws(() => f.index.vector(f.scope, [1, 0], binding(), 1), /space|signature/i);
    assert.equal(f.db.read('chunks', String(target.id))?.content, '预算');
  } finally { f.close(); }
});

test('network runs outside transactions and stale builds or owner-fence rejection cannot publish', async () => {
  const f = fixture();
  try {
    const target = f.chunk('旧预算');
    const mutate = binding(2, 'model-a:2', texts => { assert.equal(f.db.sqlite.inTransaction, false); f.db.update('chunks', String(target.id), { content: '新预算' }); return texts.map(() => [1, 0]); });
    await assert.rejects(f.index.rebuild(f.scope, mutate), /changed|stale/i);
    assert.equal(f.index.state(f.scope).length, 0);
    await assert.rejects(f.index.rebuild(f.scope, binding(), { publish() { throw new Error('owner fenced'); } }), /fenced/);
    assert.equal(f.index.state(f.scope).length, 0);
    await f.index.indexChunk(f.scope, String(target.id), binding());
    assert.equal(f.index.state(f.scope)[0]?.status, 'ready');
  } finally { f.close(); }
});

test('stable RRF deduplicates each recall list and uses rank rather than raw distances', () => {
  const result = rrfFuse(['b', 'a', 'b'], ['a', 'b'], 60);
  assert.deepEqual(result.map(r => r.chunk_id), ['a', 'b']);
  assert.equal(result[0]?.rrf_score, 1 / 62 + 1 / 61);
  assert.deepEqual(rrfFuse(['b'], ['a'], 60).map(r => r.chunk_id), ['a', 'b']);
});

test('rerank order stays intact through parent collapse and reports actual model usage', async () => {
  const f = fixture();
  try {
    const first = f.chunk('预算第一'); const second = f.chunk('预算第二');
    f.index.indexKeyword(f.scope, String(first.id)); f.index.indexKeyword(f.scope, String(second.id));
    const service = new RetrievalService(f.index);
    const result = await service.search(f.scope, '预算', { topK: 2, vectorTopK: 0, reranker: { async rerank(query, documents) {
      assert.equal(query, '预算'); assert.equal(documents.length, 2);
      return { results: [{ index: 1, relevance_score: 0.9 }, { index: 0, relevance_score: 0.1 }], usage: { prompt_tokens: 7, completion_tokens: 0, total_tokens: 7, cached_tokens: 0, reasoning_tokens: 0 } };
    } } });
    const candidateOrder = rrfFuse(ids(f.index.keyword(f.scope, '预算', 10)), [], 60).map(r => r.chunk_id);
    assert.deepEqual(ids(result.results), candidateOrder.reverse()); assert.equal(result.meta.usage.rerank?.total_tokens, 7);
    const degraded = await service.search(f.scope, '预算', { vectorTopK: 2 });
    assert(degraded.meta.degradations.some(d => d.stage === 'vector')); assert(degraded.meta.degradations.some(d => d.stage === 'rerank'));
  } finally { f.close(); }
});

test('edit-aware parent context uses codepoints, same scope, matched ranges and standalone image provenance', () => {
  const f = fixture();
  try {
    const parent = f.chunk('甲😀乙丙丁戊', { chunk_type: 'parent_text', is_enabled: false, start_at: 100, end_at: 106 });
    const child = f.chunk('新😀内容', { context_parent_id: parent.id, start_at: 102, end_at: 104 });
    const sibling = f.chunk('丁戊', { context_parent_id: parent.id, start_at: 104, end_at: 106 });
    const media = f.chunk('图片预算', { chunk_type: 'image_ocr', context_parent_id: parent.id, image_info: { original_mime_type: 'image/jpeg', page: 3 }, metadata: { provenance: { page: 3, bbox: [1, 2, 3, 4] } } });
    for (const row of [child, sibling, media]) f.index.indexKeyword(f.scope, String(row.id));
    const hydrated = [child, sibling, media].map(row => f.index.hydrate(f.scope, String(row.id))!);
    const result = f.index.resolveParents(f.scope, hydrated, 4096);
    assert.equal(result.length, 2); assert.equal(result[0]?.content, '甲😀新😀内容丁戊');
    assert.deepEqual(result[0]?.matched_child_ids, [child.id, sibling.id]);
    assert.equal(result[0]?.matched_ranges?.[0]?.rendered_start_at, 2); assert.equal(result[0]?.matched_ranges?.[0]?.rendered_end_at, 6);
    assert.equal(result[1]?.image_info?.original_mime_type, 'image/jpeg'); assert.equal(result[1]?.metadata.provenance && (result[1].metadata.provenance as any).page, 3);
    assert.equal(result[1]?.parent_chunk_id, undefined); assert.equal(f.db.read('chunks', String(parent.id))?.content, '甲😀乙丙丁戊');
    const clipped = f.index.resolveParents(f.scope, [hydrated[0]!], 4)[0]!;
    assert.equal(Array.from(clipped.content).length, 4); assert.equal(clipped.content, '新😀内容');
    f.db.update('chunks', String(child.id), { context_parent_id: 'missing' });
    assert.equal(f.index.resolveParents(f.scope, [hydrated[0]!], 2)[0]?.context_fallback, 'missing_parent');
  } finally { f.close(); }
});

test('empty scopes and known unavailable index spaces never issue model calls', async () => {
  const f = fixture();
  try {
    const row=f.chunk('预算'); f.index.indexKeyword(f.scope,String(row.id)); let calls=0;
    const embed=binding(2,'a',texts=>{calls++;return texts.map(()=>[1,0]);});
    const service=new RetrievalService(f.index);
    const empty=await service.search({...f.scope,knowledgeBaseIds:[]},'预算',{embedding:embed});
    assert.equal(empty.results.length,0); assert.equal(calls,0);
    const unavailable=await service.search(f.scope,'预算',{embedding:embed});
    assert(unavailable.meta.degradations.some(d=>d.reason==='vector_reindex_required')); assert.equal(calls,0);
  } finally {f.close();}
});

test('asynchronous publication callbacks cannot mutate the database before being rejected', async () => {
  const f=fixture();
  try {
    const row=f.chunk('预算');
    assert.throws(()=>f.index.indexKeyword(f.scope,String(row.id),async write=>{write();}),/synchronous/i);
    assert.equal(f.db.get('select count(*) as count from chunks_fts')?.count,0);
  } finally {f.close();}
});

test('a newer rebuild on another index instance fences an older delayed generation', async () => {
  const f=fixture();
  try {
    f.chunk('预算'); let release!:()=>void,started!:()=>void;
    const ready=new Promise<void>(resolve=>{started=resolve;});const wait=new Promise<void>(resolve=>{release=resolve;});
    const slow:EmbeddingBinding={...binding(),runtime:{async embed(texts){started();await wait;return binding().runtime.embed(texts);}}};
    const stale=f.index.rebuild(f.scope,slow);await ready;
    const newer=await new SearchIndex(f.db).rebuild(f.scope,binding(2,'model-b:2'));
    release();await assert.rejects(stale,/superseded|generation/i);
    assert.equal(f.index.state(f.scope)[0]?.generation,newer.generation);
  } finally {f.close();}
});

test('mixed KB/document embedding models degrade before query embedding and never compare across spaces', async () => {
  const f=fixture();
  try {
    const first=f.chunk('预算A');await f.index.indexChunk(f.scope,String(first.id),binding());
    const kb=f.db.insert('knowledge_bases',{tenant_id:f.tenant.id,name:'B',embedding_model_id:'other-model'});
    const doc=f.db.insert('knowledges',{tenant_id:f.tenant.id,knowledge_base_id:kb.id,type:'file',title:'B',source:'upload'});
    const second=f.chunk('预算B',{knowledge_base_id:kb.id,knowledge_id:doc.id});
    const all={tenantId:f.scope.tenantId};f.index.indexKeyword(all,String(second.id));let calls=0;
    const result=await new RetrievalService(f.index).search(all,'预算',{embedding:binding(2,'model-a:2',texts=>{calls++;return texts.map(()=>[1,0]);})});
    assert(result.meta.degradations.some(d=>d.reason==='mixed_embedding_spaces'));assert.equal(calls,0);
  } finally {f.close();}
});

test('actual local HTTP embedding and rerank clients integrate with real SQLite and return vendor protocol usage', async () => {
  const f=fixture(),requests:string[]=[];
  const server=createServer(async(req,res)=>{
    let text='';for await(const chunk of req) text+=chunk;const body=JSON.parse(text);requests.push(req.url!);
    res.setHeader('Content-Type','application/json');
    if(req.url==='/v1/embeddings') res.end(JSON.stringify({data:body.input.map((_:string,index:number)=>({index,embedding:[1,index]})),usage:{prompt_tokens:3,total_tokens:3}}));
    else res.end(JSON.stringify({results:body.documents.map((_:string,index:number)=>({index,relevance_score:index===0?0.2:0.9})).reverse(),usage:{prompt_tokens:9,total_tokens:9}}));
  });
  server.listen(0,'127.0.0.1');await once(server,'listening');
  try {
    const address=server.address();assert(address&&typeof address!=='string');
    const runtime=new ModelRuntime({id:'controlled-http',type:'Embedding',source:'openai',name:'protocol',parameters:{base_url:`http://127.0.0.1:${address.port}/v1`,model:'protocol',dimension:2}});
    const first=f.chunk('预算甲'),second=f.chunk('预算乙');
    await f.index.rebuild(f.scope,{signature:'protocol:2',dimension:2,runtime});
    const result=await new RetrievalService(f.index).search(f.scope,'预算',{topK:2,embedding:{signature:'protocol:2',dimension:2,runtime},reranker:runtime});
    assert.equal(result.results.length,2);assert.equal(result.results[0]?.rerank_score,0.9);
    assert.equal(result.meta.usage.embedding?.total_tokens,3);assert.equal(result.meta.usage.rerank?.total_tokens,9);
    assert.deepEqual(requests,['/v1/embeddings','/v1/embeddings','/v1/rerank']);assert(result.results.every(row=>[first.id,second.id].includes(row.chunk_id)));
  } finally {server.closeAllConnections();server.close();await once(server,'close');f.close();}
});

test('parent collapse is idempotent and context recapping keeps representative evidence and codepoint ranges', () => {
  const f=fixture();
  try {
    const parent=f.chunk('甲😀乙丙丁戊己庚辛壬',{chunk_type:'parent_text',is_enabled:false,start_at:0,end_at:10});
    const first=f.chunk('乙丙',{context_parent_id:parent.id,start_at:2,end_at:4});
    const second=f.chunk('辛壬',{context_parent_id:parent.id,start_at:8,end_at:10});
    const hits=[f.index.hydrate(f.scope,String(second.id))!,f.index.hydrate(f.scope,String(first.id))!];
    const resolved=f.index.resolveParents(f.scope,hits,100);
    assert.deepEqual(f.index.resolveParents(f.scope,resolved,100),resolved);
    const capped=f.index.resolveParents(f.scope,resolved,4)[0]!;
    assert.equal(capped.content,'己庚辛壬');assert.equal(capped.matched_ranges?.[0]?.visible,true);assert.equal(capped.matched_ranges?.[1]?.visible,false);
  } finally {f.close();}
});

test('a KB without a valid generation makes a multi-KB vector scope explicitly unavailable', async () => {
  const f=fixture();
  try {
    f.chunk('已索引预算');await f.index.rebuild(f.scope,binding());
    const kb=f.db.insert('knowledge_bases',{tenant_id:f.tenant.id,name:'未索引'});
    const doc=f.db.insert('knowledges',{tenant_id:f.tenant.id,knowledge_base_id:kb.id,type:'file',title:'新库',source:'upload'});
    f.chunk('未索引预算',{knowledge_base_id:kb.id,knowledge_id:doc.id});
    assert.throws(()=>f.index.vector({tenantId:f.scope.tenantId},[1,0],binding(),10),/ready|rebuild/i);
  } finally {f.close();}
});

test('partial batch failure never publishes a ready generation or erases the previous valid index', async () => {
  const f=fixture();
  try {
    f.chunk('预算甲');f.chunk('预算乙');await f.index.rebuild(f.scope,binding());
    const previous=f.index.state(f.scope)[0]!;let batches=0;
    const broken:EmbeddingBinding={...binding(),runtime:{async embed(texts){if(++batches===2)throw new Error('controlled second batch failure');return binding().runtime.embed(texts);}}};
    await assert.rejects(f.index.rebuild(f.scope,broken,{batchSize:1}),/second batch/);
    assert.equal(f.index.state(f.scope)[0]?.generation,previous.generation);assert.equal(f.index.state(f.scope)[0]?.status,'ready');
    assert.equal(f.index.vector(f.scope,[1,0],binding(),10).length,2);
    assert.equal(f.db.get('select count(*) as count from retrieval_builds')?.count,0);
  } finally {f.close();}
});

test('L2 exact scope scan covers vec0 K limit and excludes thousands of unregistered nearer rows', async () => {
  const f=fixture();
  try {
    const target=f.chunk('预算远目标');await f.index.rebuild(f.scope,binding(2,'model-a:2',texts=>texts.map(()=>[0,0])));
    const state=f.index.state(f.scope)[0]!,table=f.index.vectorTable(state.model_signature,state.dimension,state.generation);
    const blob=Buffer.from(new Float32Array([0.99,0]).buffer);
    f.db.transaction(()=>{for(let i=0;i<4100;i++) f.db.run(`insert into ${table}(rowid,embedding) values(?,?)`,20000n+BigInt(i),blob);});
    assert.deepEqual(ids(f.index.vector(f.scope,[1,0],binding(),1)),[target.id]);
  } finally {f.close();}
});

test('same-scope parent overlays prefer newest edits and wrong-document parents fall back to cited child', () => {
  const f=fixture();
  try {
    const parent=f.chunk('abcdefghij',{chunk_type:'parent_text',is_enabled:false,start_at:0,end_at:10});
    const child=f.chunk('abcdef',{context_parent_id:parent.id,start_at:0,end_at:6});
    f.chunk('OLDER',{context_parent_id:parent.id,start_at:2,end_at:8,updated_at:'2020-01-01T00:00:00Z'});
    const newer=f.chunk('N',{context_parent_id:parent.id,start_at:3,end_at:5,updated_at:'2030-01-01T00:00:00Z'});
    const result=f.index.resolveParents(f.scope,[f.index.hydrate(f.scope,String(child.id))!],100)[0]!;
    assert.equal(result.content,'abcNfghij');assert.deepEqual(result.applied_edit_child_ids,[newer.id]);
    const doc=f.db.insert('knowledges',{tenant_id:f.tenant.id,knowledge_base_id:f.kb.id,type:'file',title:'other',source:'upload'});
    const wrong=f.chunk('wrong',{chunk_type:'parent_text',is_enabled:false,knowledge_id:doc.id,start_at:0,end_at:5});
    f.db.update('chunks',String(child.id),{context_parent_id:wrong.id});
    assert.equal(f.index.resolveParents(f.scope,[f.index.hydrate(f.scope,String(child.id))!],3)[0]?.context_fallback,'parent_scope_mismatch');
    f.db.update('tenants',f.tenant.id as number,{status:'disabled'});assert.deepEqual(f.index.resolveParents(f.scope,[result],100),[]);
  } finally {f.close();}
});

test('rerank failures stay explicit, cancellation propagates, and post-call disablement removes candidates', async () => {
  const f=fixture();
  try {
    const row=f.chunk('预算');f.index.indexKeyword(f.scope,String(row.id));const service=new RetrievalService(f.index);
    const failed=await service.search(f.scope,'预算',{vectorTopK:0,reranker:{async rerank(){throw new Error('credentials must not be reported');}}});
    assert.equal(failed.results.length,1);assert(failed.meta.degradations.some(d=>d.reason==='rerank_call_failed'));
    const incomplete=await service.search(f.scope,'预算',{vectorTopK:0,reranker:{async rerank(){return {results:[],usage:{prompt_tokens:0,completion_tokens:0,total_tokens:0,cached_tokens:0,reasoning_tokens:0}};}}});
    assert(incomplete.meta.degradations.some(d=>d.reason==='rerank_result_incomplete'));
    const controller=new AbortController();
    await assert.rejects(service.search(f.scope,'预算',{vectorTopK:0,signal:controller.signal,reranker:{async rerank(){controller.abort();throw new Error('cancel');}}}),/cancel/i);
    const disabled=await service.search(f.scope,'预算',{vectorTopK:0,reranker:{async rerank(){f.db.update('chunks',String(row.id),{is_enabled:false});return {results:[{index:0,relevance_score:1}],usage:{prompt_tokens:1,completion_tokens:0,total_tokens:1,cached_tokens:0,reasoning_tokens:0}};}}});
    assert.deepEqual(disabled.results,[]);
  } finally {f.close();}
});

test('indexing exposes actual response usage to business callbacks outside transactions', async () => {
  const f=fixture();
  try {
    const row=f.chunk('预算');const usage:any[]=[];
    const capture=(value:any)=>{assert.equal(f.db.sqlite.inTransaction,false);usage.push(value);};
    const indexed=await f.index.indexChunk(f.scope,String(row.id),binding(),{onUsage:capture});
    assert.equal(indexed.indexed,true);assert.equal(indexed.usage?.total_tokens,1);assert.equal(usage.length,1);
    const rebuilt=await f.index.rebuild(f.scope,binding(),{onUsage:capture});
    assert.equal(rebuilt.usage.length,1);assert.equal(rebuilt.usage[0]?.total_tokens,1);assert.equal(usage.length,2);
  } finally {f.close();}
});

test('an incremental embedding started before a same-model rebuild cannot overwrite the newer generation', async () => {
  const f=fixture();
  try {
    const row=f.chunk('预算');await f.index.rebuild(f.scope,binding());
    let started!:()=>void,release!:()=>void;
    const ready=new Promise<void>(resolve=>{started=resolve;}),wait=new Promise<void>(resolve=>{release=resolve;});
    const slow:EmbeddingBinding={...binding(),runtime:{async embed(texts){started();await wait;return binding().runtime.embed(texts);}}};
    const pending=f.index.indexChunk(f.scope,String(row.id),slow);await ready;
    const next=await f.index.rebuild(f.scope,binding());release();
    await assert.rejects(pending,/generation|stale/i);assert.equal(f.index.state(f.scope)[0]?.generation,next.generation);
  } finally {f.close();}
});

test('a failed usage observer preserves actual provider response facts without replaying the request', async () => {
  const f=fixture();
  try {
    const row=f.chunk('预算');await f.index.rebuild(f.scope,binding());
    const previous=f.index.state(f.scope)[0]!.generation;let calls=0,observations=0;
    const counted=binding(2,'model-a:2',texts=>{calls++;return texts.map(()=>[1,0]);});
    const onUsage=()=>{observations++;throw new Error('secret observer error must stay private');};
    const check=(error:unknown)=>{
      assert(error instanceof IndexUsageError);assert.equal(error.providerResponded,true);
      assert.equal(error.usage.total_tokens,1);assert.equal(error.code,'index_usage_handler_failed');
      assert(!error.message.includes('secret'));assert.equal(error.cause,undefined);return true;
    };
    await assert.rejects(f.index.indexChunk(f.scope,String(row.id),counted,{onUsage}),check);
    assert.equal(calls,1);assert.equal(observations,1);assert.equal(f.index.state(f.scope)[0]!.generation,previous);
    await assert.rejects(f.index.rebuild(f.scope,counted,{onUsage}),check);
    assert.equal(calls,2);assert.equal(observations,2);assert.equal(f.index.state(f.scope)[0]!.generation,previous);
    assert.equal(f.db.get('select count(*) as count from retrieval_builds')?.count,0);
  } finally {f.close();}
});

test('an asynchronous usage observer failure preserves usage and cannot become an unhandled rejection', async () => {
  const f=fixture();
  try {
    const row=f.chunk('预算');let calls=0;
    const counted=binding(2,'model-a:2',texts=>{calls++;return texts.map(()=>[1,0]);});
    await assert.rejects(f.index.indexChunk(f.scope,String(row.id),counted,{onUsage:async()=>{throw new Error('private observer');}}),error=>{
      assert(error instanceof IndexUsageError);assert.equal(error.providerResponded,true);assert.equal(error.usage.total_tokens,1);return true;
    });
    assert.equal(calls,1);assert.equal(f.index.state(f.scope).length,0);
  } finally {f.close();}
});

test('multi-KB recall uses each KB active generation in KNN and exact L2 scans', async () => {
  const f=fixture(),requests:string[][]=[];let revised=false;
  const server=createServer(async(req,res)=>{
    let text='';for await(const chunk of req) text+=chunk;
    const body=JSON.parse(text);requests.push(body.input);
    res.setHeader('Content-Type','application/json');
    res.end(JSON.stringify({data:body.input.map((content:string,index:number)=>({index,embedding:content==='预算A'?[revised?10:0,0]:[2,0]})),
      usage:{prompt_tokens:body.input.length,total_tokens:body.input.length}}));
  });
  server.listen(0,'127.0.0.1');await once(server,'listening');
  try {
    const address=server.address();assert(address&&typeof address!=='string');
    const runtime=new ModelRuntime({id:'generation-http',type:'Embedding',source:'openai',name:'protocol',parameters:{
      base_url:`http://127.0.0.1:${address.port}/v1`,model:'protocol',dimension:2}});
    const embedding:EmbeddingBinding={signature:'generation-http:2',dimension:2,runtime};
    for(const id of ['a','b']) {
      const kb=f.db.insert('knowledge_bases',{id,tenant_id:f.tenant.id,name:id});
      const doc=f.db.insert('knowledges',{id:`doc-${id}`,tenant_id:f.tenant.id,knowledge_base_id:kb.id,type:'file',title:id,source:'upload'});
      f.chunk(id==='a'?'预算A':'预算B',{id:`chunk-${id}`,knowledge_base_id:kb.id,knowledge_id:doc.id});
    }
    const all:SearchScope={tenantId:f.scope.tenantId,knowledgeBaseIds:['a','b']};
    const onlyA:SearchScope={tenantId:f.scope.tenantId,knowledgeBaseIds:['a']};
    const original=await f.index.rebuild(all,embedding);revised=true;
    const next=await f.index.rebuild(onlyA,embedding);
    assert.notEqual(next.generation,original.generation);
    assert.equal(f.index.state(all).find(state=>state.knowledge_base_id==='b')?.generation,original.generation);
    assert.equal(f.index.vector(onlyA,[0,0],embedding,10)[0]?.distance,10);
    const knn=f.index.vector(all,[0,0],embedding,10);
    const oldTable=f.index.vectorTable(embedding.signature,embedding.dimension,original.generation);
    const blob=Buffer.from(new Float32Array([0.1,0]).buffer);
    f.db.transaction(()=>{for(let i=0;i<4100;i++)f.db.run(`insert into ${oldTable}(rowid,embedding) values(?,?)`,20000n+BigInt(i),blob);});
    const exact=f.index.vector(all,[0,0],embedding,10);
    assert.deepEqual([knn,exact].map(rows=>rows.map(row=>[row.chunk_id,row.distance])),[
      [['chunk-b',2],['chunk-a',10]],[['chunk-b',2],['chunk-a',10]],
    ]);
    assert.deepEqual(requests,[['预算A','预算B'],['预算A']]);
    assert.equal(original.usage[0]?.total_tokens,2);assert.equal(next.usage[0]?.total_tokens,1);
  } finally {server.closeAllConnections();server.close();await once(server,'close');f.close();}
});

test('a first incremental response cannot write into a generation published while it waited', async () => {
  const f=fixture();let release!:()=>void;
  try {
    const row=f.chunk('预算');let started!:()=>void;
    const ready=new Promise<void>(resolve=>{started=resolve;}),wait=new Promise<void>(resolve=>{release=resolve;});
    const slow:EmbeddingBinding={...binding(),runtime:{async embed(texts){started();await wait;return binding().runtime.embed(texts);}}};
    const pending=f.index.indexChunk(f.scope,String(row.id),slow);await ready;
    assert.equal(f.index.state(f.scope).length,0);
    const next=await f.index.rebuild(f.scope,binding(2,'model-a:2',texts=>texts.map(()=>[0,1])));release();
    await assert.rejects(pending,error=>error instanceof Error && 'code' in error && error.code==='stale_generation');
    assert.equal(f.index.state(f.scope)[0]?.generation,next.generation);
    assert.equal(f.index.vector(f.scope,[0,1],binding(),1)[0]?.distance,0);
    assert.equal(f.db.read('chunks',String(row.id))?.content,'预算');
  } finally {release?.();f.close();}
});

test('a rejected Promise publication cannot invoke its commit after the transaction ends', async () => {
  const f=fixture();
  try {
    const row=f.chunk('预算');let scheduled!:Promise<void>;
    assert.throws(()=>f.index.indexKeyword(f.scope,String(row.id),write=>{
      scheduled=Promise.resolve().then(write);return scheduled;
    }),/synchronous/i);
    await assert.rejects(scheduled,/publication|commit/i);
    assert.equal(f.db.get('select count(*) as count from chunks_fts')?.count,0);
    assert.equal(f.db.get('select count(*) as count from retrieval_chunk_ids')?.count,0);
  } finally {f.close();}
});

test('synchronous writes from a publisher returning a Promise are rolled back', async () => {
  const f=fixture();
  try {
    const row=f.chunk('预算');let scheduled!:Promise<void>;
    assert.throws(()=>f.index.indexKeyword(f.scope,String(row.id),write=>{
      write();scheduled=Promise.resolve();return scheduled;
    }),/synchronous/i);
    await scheduled;
    assert.equal(f.db.get('select count(*) as count from chunks_fts')?.count,0);
    assert.equal(f.db.get('select count(*) as count from retrieval_chunk_ids')?.count,0);
  } finally {f.close();}
});

test('rejected Promise publishers have their asynchronous failures handled', async () => {
  const f=fixture();
  try {
    const row=f.chunk('预算');
    assert.throws(()=>f.index.indexKeyword(f.scope,String(row.id),()=>new Promise<void>((_resolve,reject)=>{
      setImmediate(()=>reject(new Error('controlled asynchronous publication failure')));
    })),/synchronous/i);
    await new Promise<void>(resolve=>setImmediate(resolve));
    assert.equal(f.db.get('select count(*) as count from chunks_fts')?.count,0);
  } finally {f.close();}
});

test('standalone codepoint clipping adjusts exact source spans and preserves image and edited provenance', () => {
  const f=fixture();
  try {
    const text=f.chunk('甲😀乙丙',{start_at:10,end_at:14});
    const fallback=f.chunk('甲😀乙丙',{start_at:10,end_at:14,context_parent_id:'missing'});
    const edited=f.chunk('扩展😀',{start_at:10,end_at:14});
    const image=f.chunk('图😀说明',{chunk_type:'image_ocr',start_at:100,end_at:100,
      image_info:{original_mime_type:'image/jpeg',page:3},metadata:{provenance:{page:3,bbox:[1,2,3,4]}}});
    const result=f.index.resolveParents(f.scope,[text,fallback,edited,image].map(row=>f.index.hydrate(f.scope,String(row.id))!),2);
    assert.deepEqual(result.map(row=>row.content),['甲😀','甲😀','扩展','图😀']);
    assert.deepEqual(result.map(row=>[row.context_window?.source_start_at,row.context_window?.source_end_at]),[[10,12],[10,12],[10,14],[100,100]]);
    assert.equal(result[1]?.context_fallback,'missing_parent');
    assert.deepEqual(result[1]?.matched_ranges?.map(range=>[range.start_at,range.end_at,range.context_start_at,range.context_end_at]),[[10,14,0,2]]);
    assert.equal(result[3]?.image_info?.original_mime_type,'image/jpeg');
    assert.deepEqual(result[3]?.metadata.provenance,{page:3,bbox:[1,2,3,4]});
    assert.equal(result[3]?.parent_chunk_id,undefined);
  } finally {f.close();}
});

test('single chunk hydration and keyword publication bound SQLite source work independently of corpus size', () => {
  const f=fixture();
  try {
    f.db.update('knowledges',String(f.doc.id),{metadata:{content:'实际长文档来源😀'.repeat(12000)}});
    let target:any;
    f.db.transaction(()=>{for(let i=0;i<600;i++) target=f.chunk(`预算条目${i}与可信来源`,{id:`large-corpus-${i}`,seq_id:1152921504606846976n+BigInt(i)});});
    const read=f.db.all.bind(f.db);let hydratedRows=0,sourceChars=0;
    f.db.all=((sql:string,...params:any[])=>{
      const rows=read(sql,...params);
      if(sql.includes('d.metadata AS knowledge_metadata')) {
        hydratedRows+=rows.length;sourceChars+=rows.reduce((n,row)=>n+String(row.knowledge_metadata).length,0);
      }
      return rows;
    }) as typeof f.db.all;
    f.index.indexKeyword(f.scope,String(target.id));
    const hit=f.index.hydrate(f.scope,String(target.id));
    assert.equal(hit?.chunk_id,target.id);assert.equal(hit?.seq_id,'1152921504606847575');
    assert.equal(hydratedRows,2,'Two single-record operations must hydrate exactly two records, not the entire 600-chunk corpus');
    assert.ok(sourceChars<500000,'Large document JSON must not be copied once per unrelated chunk');
    f.db.update('chunks',String(target.id),{is_enabled:false});
    assert.equal(f.index.hydrate(f.scope,String(target.id)),undefined);
    f.index.indexKeyword(f.scope,String(target.id));
    assert.equal(f.db.get('SELECT count(*) AS n FROM chunks_fts')?.n,0);
  } finally {f.close();}
});

test('natural-language keyword questions use trigram terms without forcing short words into an exact phrase', async () => {
  const f=fixture();
  try {
    f.db.update('knowledges',String(f.doc.id),{title:'Controlled source'});
    const target=f.chunk('Paris is the capital of France.',{seq_id:1152921504606846976n});
    const chinese=f.chunk('独立预算记录'),short=f.chunk('go'),literal=f.chunk('百分比%与下划线_');
    for(const row of [target,chinese,short,literal])f.index.indexKeyword(f.scope,String(row.id));
    assert.deepEqual(ids(f.index.keyword(f.scope,'What is the capital of France?',1)),[target.id]);
    assert.equal(f.index.keyword(f.scope,'What is the capital of France?',1)[0]?.seq_id,'1152921504606846976');
    const result=await new RetrievalService(f.index).search(f.scope,'What is the capital of France?',{strategy:'keyword',rerankTopK:0});
    assert.deepEqual(ids(result.results),[target.id]);
    assert.deepEqual(ids(f.index.keyword(f.scope,'预算',10)),[chinese.id]);
    assert.deepEqual(ids(f.index.keyword(f.scope,'go',10)),[short.id]);
    assert.deepEqual(ids(f.index.keyword(f.scope,'%',10)),[literal.id]);
    assert.deepEqual(ids(f.index.keyword(f.scope,'_',10)),[literal.id]);
    assert.deepEqual(f.index.keyword({...f.scope,knowledgeBaseIds:[]},'What is the capital of France?',1),[]);
  } finally {f.close();}
});

// UI-RETRIEVAL-RANK: preserve retrieval_config.py rank thresholds rather than inventing score probabilities.
async function strategyFixture() {
  const f=fixture(),requests:any[]=[];
  const server=createServer(async(req,res)=>{
    assert.equal(f.db.sqlite.inTransaction,false);let raw='';for await(const part of req)raw+=part;
    const body=JSON.parse(raw);requests.push({path:req.url,body});res.setHeader('Content-Type','application/json');
    if(req.url==='/v1/embeddings')res.end(JSON.stringify({data:body.input.map((content:string,index:number)=>({index,embedding:[content.includes('second')?100:content.includes('third')?200:0,0]})),usage:{prompt_tokens:body.input.length,total_tokens:body.input.length}}));
    else res.end(JSON.stringify({results:body.documents.map((_:string,index:number)=>({index,relevance_score:-100-index})),usage:{prompt_tokens:9,total_tokens:9}}));
  });
  server.listen(0,'127.0.0.1');await once(server,'listening');const address=server.address();assert(address&&typeof address!=='string');
  const runtime=new ModelRuntime({id:'strategy-protocol',type:'Embedding',source:'openai',name:'protocol',parameters:{base_url:`http://127.0.0.1:${address.port}/v1`,model:'protocol',dimension:2}});
  const embedding:EmbeddingBinding={signature:'strategy-protocol:2',dimension:2,runtime};
  return {...f,requests,runtime,embedding,service:new RetrievalService(f.index),async shutdown(){server.closeAllConnections();server.close();await once(server,'close');f.close();}};
}

test('strategy selects real keyword or L2 recall and explicit empty scopes never call paid protocols',async()=>{
  const f=await strategyFixture();try{
    const first=f.chunk('budget first'),second=f.chunk('budget second');await f.index.rebuild(f.scope,f.embedding);const base=f.requests.length;
    const keyword=await f.service.search(f.scope,'budget',{strategy:'keyword',embedding:f.embedding,rerankTopK:0});
    assert.equal(keyword.results.length,2);assert.equal(f.requests.length,base);assert.equal(keyword.meta.candidate_counts.vector,0);assert.equal(keyword.meta.degraded,false);
    const vector=await f.service.search(f.scope,'unmatched',{strategy:'vector',embedding:f.embedding,rerankTopK:0});
    assert.equal(vector.meta.candidate_counts.keyword,0);assert.deepEqual(vector.results.map(row=>row.match_sources),[['vector'],['vector']]);assert.deepEqual(ids(vector.results),[first.id,second.id]);assert.equal(f.requests.length,base+1);
    for(const strategy of ['keyword','vector','hybrid'] as const){const none=await f.service.search({...f.scope,knowledgeBaseIds:[]},'budget',{strategy,embedding:f.embedding,reranker:f.runtime});assert.deepEqual(none.results,[]);assert.equal(none.meta.degraded,false);}
    assert.equal(f.requests.length,base+1);
    const missing=await f.service.search({tenantId:f.scope.tenantId},'budget',{strategy:'keyword',rerankTopK:0});assert.equal(missing.results.length,2);
  }finally{await f.shutdown();}
});

test('keyword and vector thresholds preserve normalized within-stage rank independent of raw BM25 or L2 magnitude',async()=>{
  const f=await strategyFixture();try{
    const rows=[f.chunk('budget first'),f.chunk('budget second'),f.chunk('budget third')];await f.index.rebuild(f.scope,f.embedding);
    const ordered=ids(f.index.keyword(f.scope,'budget',20));
    const keyword=await f.service.search(f.scope,'budget',{strategy:'keyword',keywordThreshold:1,rerankTopK:0});assert.deepEqual(ids(keyword.results),ordered.slice(0,1));assert.equal(keyword.meta.filtered_counts.keyword,2);assert.equal(keyword.meta.threshold_metric,'normalized_stage_rank');
    const vector=await f.service.search(f.scope,'unmatched',{strategy:'vector',vectorThreshold:2/3,embedding:f.embedding,rerankTopK:0});
    assert.deepEqual(ids(vector.results),rows.slice(0,2).map(row=>row.id));assert.deepEqual(vector.results.map(row=>row.distance),[0,100]);assert.equal(vector.meta.score_metrics.vector,'l2_distance');assert.equal(vector.meta.candidate_counts.vector,2);assert.equal(vector.meta.filtered_counts.vector,1);
    const all=await f.service.search(f.scope,'budget',{strategy:'keyword',keywordThreshold:0,rerankTopK:0});assert.equal(all.results.length,3);
  }finally{await f.shutdown();}
});

test('rerank rank threshold filters scored candidates but preserves legacy unscored tail and explicit model failure',async()=>{
  const f=await strategyFixture();try{
    for(let n=0;n<4;n++){const row=f.chunk(`budget item${n}`);f.index.indexKeyword(f.scope,String(row.id));}
    const options={strategy:'keyword' as const,topK:10,rerankTopK:2,rerankThreshold:1};
    const reranked=await f.service.search(f.scope,'budget',{...options,reranker:f.runtime});
    assert.equal(reranked.results.length,3);assert.equal(reranked.results[0]?.rerank_score,-100);assert.deepEqual(reranked.results.slice(1).map(row=>row.rerank_score),[null,null]);assert.equal(reranked.meta.filtered_counts.rerank,1);assert.equal(reranked.meta.usage.rerank?.total_tokens,9);
    const unavailable=await f.service.search(f.scope,'budget',options);assert.equal(unavailable.results.length,4);assert(unavailable.meta.degradations.some(item=>item.reason==='rerank_model_not_configured'));
    assert.equal(f.requests.length,1);
  }finally{await f.shutdown();}
});

test('retrieval rejects invalid strategies and finite threshold bounds before network calls',async()=>{
  const f=await strategyFixture();try{
    const row=f.chunk('budget');await f.index.rebuild(f.scope,f.embedding);const before=f.requests.length;
    for(const value of [-0.01,1.01,NaN,Infinity])for(const key of ['keywordThreshold','vectorThreshold','rerankThreshold'])await assert.rejects(f.service.search(f.scope,'budget',{embedding:f.embedding,[key]:value}),/threshold/i);
    await assert.rejects(f.service.search(f.scope,'budget',{strategy:'unexpected' as any,embedding:f.embedding}),/strategy/i);assert.equal(f.requests.length,before);assert.ok(row.id);
  }finally{await f.shutdown();}
});
