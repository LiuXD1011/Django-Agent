import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { createServer } from 'node:http';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { AuthService } from '../src/auth/index.js';
import { ModelCaller } from '../src/chat/calls.js';
import * as chatRetrieval from '../src/chat/retrieval.js';
import type { ChatExecution, ChatHooks, ChatSearchResult } from '../src/chat/types.js';
import type { Json, JsonObject } from '../src/contracts.js';
import { JobQueue } from '../src/jobs/queue.js';
import { SearchIndex } from '../src/retrieval/search-index.js';
import { RetrievalService } from '../src/retrieval/service.js';
import type { SearchOptions } from '../src/retrieval/types.js';
import { ModelConfigurationService } from '../src/settings/model-configuration.js';
import { CredentialVault } from '../src/storage/credentials.js';
import { CoreDatabase } from '../src/storage/database.js';

async function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'marlin-chat-context-')), db = new CoreDatabase(root), auth = new AuthService(db), ctx = auth.register({ username: 'retriever', password: 'Retrieval✓Password' }).context, jobs = new JobQueue(db), index = new SearchIndex(db), models = new ModelConfigurationService(db, auth, new CredentialVault(root));
  const kb = String(db.insert('knowledge_bases', { tenant_id: ctx.tenantId, name: 'Allowed', indexing_strategy: { graph_enabled: false } }).id), doc = String(db.insert('knowledges', { tenant_id: ctx.tenantId, knowledge_base_id: kb, title: 'Fixture' }).id); let seq = 100n, ordinal = 0;
  const add = (content: string, fields: JsonObject = {}) => String(db.insert('chunks', { tenant_id: ctx.tenantId, knowledge_base_id: kb, knowledge_id: doc, content, seq_id: String(++seq), chunk_index: ordinal++, start_at: 0, end_at: Array.from(content).length, ...fields }).id);
  const scope = { tenantId: ctx.tenantId, knowledgeBaseIds: [kb] };
  const run = async (query: string, options: SearchOptions = {}, hooks: ChatHooks = {}): Promise<ChatSearchResult> => {
    let result!: ChatSearchResult; const kind = `fixture.${randomUUID()}`;
    jobs.register(kind, async job => { const check = () => { auth.assertCan(ctx, 'read'); job.signal.throwIfAborted(); job.publish(() => {}); };
      const execution: ChatExecution = { context: ctx, sessionId: 'fixture', messageId: 'fixture', requestId: job.jobId, query, input: {}, config: {}, history: [], scope, job, signal: job.signal,
        calls: new ModelCaller(db, models, ctx, {}, check, () => {}), assert: check, publish: job.publish, emit: () => {}, journal: () => {}, search: () => { throw new Error('Not used'); } };
      result = await chatRetrieval.retrieveChat(execution, index, query, options, hooks); return {};
    }); const job = jobs.create({ kind, scope: { tenantId: ctx.tenantId, userId: ctx.userId }, requestId: randomUUID(), recoveryPolicy: 'manual', payload: {} });
    const terminal = await jobs.run(job.id); assert.equal(terminal.status, 'completed', terminal.error); return result;
  };
  return { db, auth, ctx, jobs, index, models, kb, doc, scope, add, run, close: async () => { await jobs.close(); db.close(); rmSync(root, { recursive: true, force: true }); } };
}

test('chat local query variants preserve Chinese prefixes quoted phrases stopwords and five-variant bound', () => {
  assert.equal(typeof chatRetrieval.expandChatQuery, 'function');
  assert.deepEqual(chatRetrieval.expandChatQuery('什么是量子纠缠'), ['量子纠缠']);
  assert.ok(chatRetrieval.expandChatQuery('What is "quantum entanglement"?').includes('quantum entanglement'));
  const variants = chatRetrieval.expandChatQuery('please alphaone, betatwo; gammathree。deltafour! epsilonfive? zetasix');
  assert.equal(variants.length, 5); assert.equal(new Set(variants.map(v => v.toLowerCase())).size, variants.length);
});

test('core-only deferred context retains all budgeted child candidates while the default search remains resolved and limited', async () => {
  const f = await fixture(); try {
    const parent = f.add('Needle parent text', { chunk_type: 'parent_text', is_enabled: false }), child = f.add('Needle', { context_parent_id: parent, start_at: 0, end_at: 6 }), second = f.add('Needle separate', { knowledge_id: String(f.db.insert('knowledges', { tenant_id: f.ctx.tenantId, knowledge_base_id: f.kb }).id) });
    for (const id of [child, second]) f.index.indexKeyword(f.scope, id);
    const service = new RetrievalService(f.index), resolved = await service.search(f.scope, 'Needle', { topK: 1, keywordTopK: 2, vectorTopK: 0, rerankTopK: 0 }); assert.equal(resolved.results.length, 1);
    const raw = await service.search(f.scope, 'Needle', { topK: 1, keywordTopK: 2, vectorTopK: 0, rerankTopK: 0, deferContext: true }); assert.equal(raw.results.length, 2); assert.equal(raw.results.find(r => r.chunk_id === child)!.content, 'Needle'); assert.equal(raw.results.some(r => r.parent_chunk_id), false); assert.deepEqual(raw.results.map(r => r.final_rank), [1, 2]);
  } finally { await f.close(); }
});

test('short flat chunks expand real active neighbors with Unicode source ranges and a codepoint cap', async () => {
  const f = await fixture(); try {
    const previous = f.add('之前😀证据', { start_at: 10, end_at: 15 }), seed = f.add('Needle', { start_at: 15, end_at: 21 }), next = f.add('后来🐱证据', { start_at: 21, end_at: 26 });
    f.add('DISABLED_SECRET', { is_enabled: false }); f.add('DELETED_SECRET', { deleted_at: new Date().toISOString() }); f.add('IMAGE_SECRET', { chunk_type: 'image_ocr' }); f.add('PARENT_SECRET', { chunk_type: 'parent_text', is_enabled: false }); f.index.indexKeyword(f.scope, seed);
    const result = await f.run('Needle', { strategy: 'keyword', rerankTopK: 0, topK: 1, maxContextChars: 15 }), row = result.results[0]!;
    assert.ok(row.content.startsWith('之前😀证据\nNeedle')); assert.equal(Array.from(row.content).length, 15); assert.equal(row.content.includes('SECRET'), false); assert.deepEqual(row.expanded_chunk_ids, [previous, seed, next]);
    assert.equal(row.expanded_source_refs!.find(r => r.chunk_id === previous)!.source_start_at, 10); assert.equal(row.expanded_source_refs!.find(r => r.chunk_id === seed)!.context_start_at, 6); assert.equal(row.expanded_source_refs!.find(r => r.chunk_id === next)!.clipped, true);
    f.db.update('chunks', previous, { deleted_at: new Date().toISOString() }); const fresh = await f.run('Needle', { strategy: 'keyword', rerankTopK: 0, topK: 1 }); assert.equal(fresh.results[0]!.content.includes('之前'), false);
  } finally { await f.close(); }
});

test('short chunk expansion cannot mix a different KB document disabled document or parent-child and image media', async () => {
  const f = await fixture(); try {
    const wrongKb = String(f.db.insert('knowledge_bases', { tenant_id: f.ctx.tenantId }).id), wrongDoc = String(f.db.insert('knowledges', { tenant_id: f.ctx.tenantId, knowledge_base_id: wrongKb }).id), disabledDoc = String(f.db.insert('knowledges', { tenant_id: f.ctx.tenantId, knowledge_base_id: f.kb, enable_status: 'disabled' }).id);
    f.add('UNSELECTED', { knowledge_base_id: wrongKb, knowledge_id: wrongDoc }); f.add('MISMATCH', { knowledge_id: wrongDoc }); f.add('DISABLED_DOCUMENT', { knowledge_id: disabledDoc });
    const parent = f.add('Needle parent original', { chunk_type: 'parent_text', is_enabled: false }), child = f.add('Needle', { context_parent_id: parent, start_at: 0, end_at: 6 }), image = f.add('Needle media', { chunk_type: 'image_ocr', image_info: { image_id: 'real-media', source_ref: 'page:3' } });
    for (const id of [child, image]) f.index.indexKeyword(f.scope, id); const rows = (await f.run('Needle', { strategy: 'keyword', rerankTopK: 0, topK: 5 })).results;
    assert.equal(rows.find(r => r.chunk_id === child)!.parent_chunk_id, parent); assert.equal(rows.find(r => r.chunk_id === image)!.image_info!.image_id, 'real-media'); assert.equal(rows.some(r => r.expanded_chunk_ids), false); assert.equal(JSON.stringify(rows).includes('UNSELECTED'), false);
  } finally { await f.close(); }
});

test('local Chinese query expansion feeds one real HTTP rerank with original query actual candidate text and reported usage', async () => {
  const f = await fixture(), requests: JsonObject[] = [];
  const server = createServer(async (req, res) => { let raw = ''; for await (const part of req) raw += part; assert.equal(f.db.sqlite.inTransaction, false); const body = JSON.parse(raw) as JsonObject; requests.push(body); const documents = body.documents as string[]; res.setHeader('content-type', 'application/json'); res.end(JSON.stringify({ results: documents.map((_, i) => ({ index: documents.length - i - 1, relevance_score: 1 - i / 10 })), usage: { prompt_tokens: 17, total_tokens: 17 } })); });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve)); const address = server.address(); assert.ok(address && typeof address !== 'string');
  try {
    // Chinese trigram questions now recall contiguous source terms directly.
    // Spaced short terms retain a real no-hit seed and exercise local expansion.
    const query = '什么是量子 纠缠';
    const one = f.add('量子 纠缠 first evidence ' + '甲'.repeat(360)), two = f.add('量子 纠缠 second evidence ' + '乙'.repeat(360)); for (const id of [one, two]) f.index.indexKeyword(f.scope, id);
    assert.deepEqual(f.index.keyword(f.scope, query, 4), []);
    assert.ok(chatRetrieval.expandChatQuery(query).includes('量子 纠缠'));
    const model = f.models.create(f.ctx, { name: 'fixture-reranker', source: 'openai', type: 'Rerank', parameters: { model: 'fixture', base_url: `http://127.0.0.1:${address.port}/v1` } }), caller = new ModelCaller(f.db, f.models, f.ctx, { operation: 'rerank' }, () => f.auth.assertCan(f.ctx, 'read'), () => {});
    const reranker = { rerank: (query: string, documents: string[], options: Parameters<ModelCaller['complete']>[2]) => caller.invoke(String(model.id), 'query_rerank', async (runtime, usage) => { const result = await runtime.rerank(query, documents, options); usage(result.usage); return result; }) };
    const result = await f.run(query, { topK: 2, strategy: 'keyword', keywordTopK: 4, rerankTopK: 2, reranker }); assert.equal(requests.length, 1); assert.equal(requests[0]!.query, query); assert.equal((requests[0]!.documents as Json[]).length, 2); assert.deepEqual(result.results.map(row => row.content), [...requests[0]!.documents as string[]].reverse()); assert.equal(result.meta.usage.rerank!.total_tokens, 17); assert.equal(result.meta.candidate_counts.rerank_input, 2); assert.ok(result.results.every(row => row.match_sources.includes('keyword_expansion')));
    const receipts = f.db.all('SELECT * FROM model_usage'); assert.equal(receipts.length, 1); assert.equal(receipts[0]!.scenario, 'query_rerank'); assert.equal(receipts[0]!.total_tokens, 17); assert.equal(receipts[0]!.request_count, 1);
    requests.length = 0; const cut = await f.run(query, { topK: 2, strategy: 'keyword', keywordTopK: 4, keywordThreshold: .6, rerankTopK: 0 }); assert.equal(cut.results.length, 1); assert.equal(requests.length, 0);
  } finally { server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); await f.close(); }
});

test('MMR selects the legacy relevance diversity subset and then restores factual provider order', () => {
  assert.equal(typeof chatRetrieval.selectChatDocuments, 'function');
  const rows = [
    { chunk_id: 'a', content: 'alpha beta gamma delta', score: 1, final_rank: 1, knowledge_id: 'one' },
    { chunk_id: 'b', content: 'alpha beta gamma delta epsilon', score: .99, final_rank: 2, knowledge_id: 'one' },
    { chunk_id: 'c', content: 'zeta eta theta iota', score: .98, final_rank: 3, knowledge_id: 'two' },
    { chunk_id: 'd', content: 'kappa lambda mu nu', score: 0, final_rank: 4, knowledge_id: 'three' },
  ];
  assert.deepEqual(chatRetrieval.selectChatDocuments(rows, 1).map(r => r.chunk_id), ['a', 'c']); assert.equal(rows[2]!.final_rank, 3);
});

test('MMR uses the full budgeted real corpus rather than a topK prefix', async () => {
  const f = await fixture(); try {
    const corpus = ['alpha beta gamma delta', 'alpha beta gamma epsilon', 'zeta eta theta iota', 'kappa lambda mu nu', 'omicron pi rho sigma', 'tau upsilon phi chi', 'psi omega nonshared nouns', 'minimum zero relevancy facts'];
    const ids = corpus.map((text, i) => f.add('Needle ' + text + ' ' + String.fromCharCode(97 + i).repeat(360), { knowledge_id: String(f.db.insert('knowledges', { tenant_id: f.ctx.tenantId, knowledge_base_id: f.kb }).id) }));
    for (const id of ids) f.index.indexKeyword(f.scope, id); const scores = [1, .5, .49, .48, .47, .46, .45, 0];
    const reranker = { rerank: async (_: string, documents: string[]) => ({ results: documents.map((text, index) => ({ index, relevance_score: scores[corpus.findIndex(part => text.includes(part))]! })).sort((a,b) => b.relevance_score-a.relevance_score), usage: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, cached_tokens: 0, reasoning_tokens: 0 } }) };
    const result = await f.run('Needle', { topK: 2, strategy: 'keyword', keywordTopK: 8, rerankTopK: 8, reranker }); assert.equal(result.meta.candidate_counts.rerank_input, 8); assert.deepEqual(result.results.map(row => row.chunk_id), [ids[0], ids[2]]); assert.deepEqual(result.results.map(row => row.final_rank), [1, 3]);
    f.db.update('knowledge_bases', f.kb, { indexing_strategy: { graph_enabled: true } });
    const duplicate = await f.run('Needle', { topK: 2, strategy: 'keyword', keywordTopK: 8, rerankTopK: 8, reranker }, { graphRetrieval: async () => ({ state: 'connected', items: [{ chunk_id: ids[1], score: 1 }], warnings: [] }) });
    assert.deepEqual(duplicate.results.map(row => row.chunk_id), [ids[0], ids[2]], 'A graph duplicate cannot reintroduce a document discarded by MMR');
  } finally { await f.close(); }
});

test('context clipping cannot turn a long flat chunk into an adjacent expansion seed', async () => {
  const f = await fixture(); try {
    f.add('Previous neighbor'); const seed = f.add('Needle' + '😀'.repeat(400)); f.index.indexKeyword(f.scope, seed);
    const row = (await f.run('Needle', { topK: 1, strategy: 'keyword', rerankTopK: 0, maxContextChars: 8 })).results[0]!;
    assert.equal(row.content, 'Needle😀😀'); assert.equal(row.expanded_chunk_ids, undefined); assert.equal(row.context_window!.source_end_at, 8);
  } finally { await f.close(); }
});

test('local expansion honors explicit keyword disablement total candidate budget and invalid deferred modes', async () => {
  const f = await fixture(); try {
    for (let at = 0; at < 6; at++) { const id = f.add('量子纠缠 fixture ' + at + ' ' + '文'.repeat(350), { knowledge_id: String(f.db.insert('knowledges', { tenant_id: f.ctx.tenantId, knowledge_base_id: f.kb }).id) }); f.index.indexKeyword(f.scope, id); }
    const budgeted = await f.run('什么是量子纠缠', { topK: 5, strategy: 'keyword', keywordTopK: 1, rerankTopK: 0 }); assert.equal(budgeted.meta.candidate_counts.fused, 1); assert.equal(budgeted.results.length, 1);
    const disabled = await f.run('什么是量子纠缠', { topK: 5, keywordTopK: 0, vectorTopK: 0, rerankTopK: 0 }); assert.deepEqual(disabled.results, []);
    await assert.rejects(new RetrievalService(f.index).search(f.scope, 'Needle', { deferContext: 'true' as unknown as boolean }), (error: unknown) => (error as { code?: string }).code === 'invalid_context_mode');
  } finally { await f.close(); }
});
