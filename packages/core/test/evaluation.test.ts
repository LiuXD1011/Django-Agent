import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { test } from 'node:test';
import { CoreDatabase } from '../src/storage/database.js';
import { CredentialVault } from '../src/storage/credentials.js';
import { AuthService } from '../src/auth/index.js';
import { ModelConfigurationService } from '../src/settings/index.js';
import { SearchIndex } from '../src/retrieval/search-index.js';
import { JobQueue } from '../src/jobs/queue.js';

const code = (expected: string) => (error: any) => error.code === expected;
async function fixture() {
  const module = await import('../src/evaluation/index.js').catch(() => null);
  assert.ok(module, 'Independent evaluation must retain real candidates, review and published source evidence');
  const root = mkdtempSync(join(tmpdir(), 'marlin-evaluation-')), db = new CoreDatabase(root), auth = new AuthService(db);
  const ctx = auth.register({ username: 'owner', password: 'TemporaryFixturePassword' }).context;
  const other = auth.register({ username: 'other', password: 'TemporaryFixturePassword' }).context;
  const models = new ModelConfigurationService(db, auth, new CredentialVault(root)), index = new SearchIndex(db), jobs = new JobQueue(db);
  const service = new module.EvaluationService(db, auth, models, index, jobs);
  const kbId = String(db.insert('knowledge_bases', { tenant_id: ctx.tenantId, name: 'Evidence' }).id);
  const source = '真实证据 😀：巴黎是法国首都。柏林是德国首都。';
  const fileHash = createHash('sha256').update(source).digest('hex');
  const docId = String(db.insert('knowledges', { tenant_id: ctx.tenantId, knowledge_base_id: kbId, title: 'Evidence source', file_hash: fileHash, metadata: { content: source, source_generation: 'generation-1' } }).id);
  const chunkId = String(db.insert('chunks', { tenant_id: ctx.tenantId, knowledge_base_id: kbId, knowledge_id: docId, content: source, start_at: 0, end_at: Array.from(source).length, is_enabled: true }).id);
  const entries = Array.from({ length: 5 }, (_, i) => ({ question: `问题 ${i + 1}：法国首都？`, answer: '巴黎', evidence: [{ chunk_id: chunkId, knowledge_id: docId, source_start: 0, source_end: Array.from(source).length }] }));
  return { root, db, auth, ctx, other, models, index, jobs, service, kbId, docId, chunkId, entries, async close() { await service.close(); await jobs.close(); db.close(); rmSync(root, { recursive: true, force: true }); } };
}

test('candidates require real scoped code point evidence and explicit publication; edit resets review and versions preserve publications', async () => {
  const f = await fixture();
  try {
    const draft = f.service.createDataset(f.ctx, { name: 'Manual', knowledge_base_id: f.kbId, review_mode: 'manual', entries: f.entries });
    assert.equal(draft.status, 'draft'); assert.equal(draft.review_summary.pending, 5);
    assert.throws(() => f.service.publish(f.ctx, draft.id), code('unverified_eval_dataset'));
    assert.throws(() => f.service.getDataset(f.other, draft.id), code('dataset_not_found'));
    const approved = f.service.review(f.ctx, draft.id, { entry_ids: draft.entries.map((entry: any) => entry.id), status: 'approved' });
    f.service.editEntry(f.ctx, draft.id, approved.entries[0].id, { question: '编辑后的法国首都？' });
    assert.equal(f.service.getDataset(f.ctx, draft.id).entries[0].status, 'pending_review');
    f.service.review(f.ctx, draft.id, { entry_ids: [approved.entries[0].id], status: 'approved' });
    const published = f.service.publish(f.ctx, draft.id); assert.equal(published.status, 'published'); assert.equal(published.entries.length, 5);
    assert.throws(() => f.service.editEntry(f.ctx, draft.id, published.entries[0].id, { question: 'replace' }), code('dataset_immutable'));
    const version = f.service.newVersion(f.ctx, draft.id); assert.notEqual(version.id, draft.id); assert.equal(version.version, Number(published.version) + 1);
    f.service.deleteEntry(f.ctx, version.id, version.entries[0].id); assert.equal(f.service.getDataset(f.ctx, version.id).entries.length, 4);
    assert.equal(f.service.getDataset(f.ctx, draft.id).entries.length, 5);
  } finally { await f.close(); }
});

test('stale or foreign evidence cannot be approved and unpublished candidates are not effective evaluation questions', async () => {
  const f = await fixture();
  try {
    const invalid = f.service.createDataset(f.ctx, { knowledge_base_id: f.kbId, review_mode: 'auto', entries: [{ ...f.entries[0], evidence: [{ ...f.entries[0].evidence[0], source_end: 999 }] }] });
    assert.equal(invalid.entries[0].status, 'rejected'); assert.ok(invalid.entries[0].validation_errors.includes('source_span'));
    assert.throws(() => f.service.review(f.ctx, invalid.id, { entry_ids: [invalid.entries[0].id], status: 'approved' }), code('unverified_eval_dataset'));
    const draft = f.service.createDataset(f.ctx, { knowledge_base_id: f.kbId, review_mode: 'auto', entries: f.entries });
    const input = { source: { type: 'tenant_dataset', dataset_id: draft.id, knowledge_base_id: f.kbId }, retrieval_strategy: 'keyword', rerank_enabled: false };
    await assert.rejects(f.service.estimate(f.ctx, input), code('dataset_not_published'));
    f.db.update('knowledges', f.docId, { file_hash: 'changed', metadata: { content: 'changed', source_generation: 'generation-2' } });
    assert.throws(() => f.service.publish(f.ctx, draft.id), code('unverified_eval_dataset'));
  } finally { await f.close(); }
});

test('five valid approved published questions still require actual answer, judge, embedding and worker configuration', async () => {
  const f = await fixture();
  try {
    const draft = f.service.createDataset(f.ctx, { knowledge_base_id: f.kbId, review_mode: 'auto', entries: f.entries });
    f.service.publish(f.ctx, draft.id);
    const input = { source: { type: 'tenant_dataset', dataset_id: draft.id, knowledge_base_id: f.kbId }, retrieval_strategy: 'keyword', rerank_enabled: false };
    await assert.rejects(f.service.createRun(f.ctx, input), code('needs_configuration'));
    assert.equal(f.jobs.list({ tenantId: f.ctx.tenantId, userId: f.ctx.userId }).length, 0);
  } finally { await f.close(); }
});

test('independent real Ragas collections score five rows over bounded core RPC without Django or direct model access', async () => {
  const mod = await import('../src/evaluation/ragas.js').catch(() => null);
  assert.ok(mod, 'An actual independent Ragas RPC bridge is required');
  const bridge = new mod.RagasBridge({ pythonExecutable: '/home/liuxuedeng/anaconda3/bin/python', workerPath: resolve('../../workers/evaluation/worker.py') });
  let calls = 0;
  try {
    const capabilities = await bridge.capabilities(); assert.equal(capabilities.ragas_version, '0.4.3'); assert.equal(capabilities.django_imported, false);
    const rows = Array.from({ length: 5 }, (_, index) => ({ example_id: `row-${index}`, question: 'What is the capital of France?', answer: 'Paris is the capital of France.', reference: 'Paris', contexts: ['Paris is the capital of France.'] }));
    const result = await bridge.evaluate(rows, async (request: any) => {
      calls++;
      if (request.operation === 'embed') return { vectors: request.texts.map(() => [1, 0]) };
      const title = request.schema.title;
      const output = title === 'StatementGeneratorOutput' ? { statements: ['Paris is the capital of France.'] } : title === 'NLIStatementOutput' ? { statements: [{ statement: 'Paris is the capital of France.', reason: 'In context', verdict: 1 }] } : title === 'AnswerRelevanceOutput' ? { question: 'What is the capital of France?', noncommittal: 0 } : { reason: 'Provides the answer', verdict: 1 };
      return { content: JSON.stringify(output) };
    });
    assert.equal(result.rows.length, 5); assert.equal(calls, 40);
    for (const row of result.rows) { assert.equal(row.faithfulness, 1); assert.equal(row.answer_relevancy, 1); assert.ok(row.context_precision > 0.999); }
    let attempted = 0;
    await assert.rejects(bridge.evaluate([rows[0]], async () => { attempted++; return { content: 'invalid JSON' }; }), code('ragas_scoring_failed'));
    assert.equal(attempted, 1, 'Malformed paid result must not be retried automatically');
  } finally { await bridge.close(); }
});

test('five approved rows execute real HTTP models, Ragas, job progress, audited usage and scoped downloadable reports', async () => {
  const f = await fixture(), { createServer } = await import('node:http');
  let requests = 0;
  const server = createServer(async (req, res) => {
    let body = ''; for await (const chunk of req) body += chunk;
    const input = JSON.parse(body); requests++; res.setHeader('content-type', 'application/json');
    if (req.url?.endsWith('/embeddings')) { res.end(JSON.stringify({ data: input.input.map((_: string, index: number) => ({ index, embedding: [1, 0] })), usage: { prompt_tokens: input.input.length, total_tokens: input.input.length } })); return; }
    const system = input.messages[0].content;
    let content = 'Paris is the capital of France.';
    if (system.includes('StatementGeneratorOutput')) content = JSON.stringify({ statements: ['Paris is the capital of France.'] });
    else if (system.includes('NLIStatementOutput')) content = JSON.stringify({ statements: [{ statement: 'Paris is the capital of France.', reason: 'In context', verdict: 1 }] });
    else if (system.includes('AnswerRelevanceOutput')) content = JSON.stringify({ question: 'What is the capital of France?', noncommittal: 0 });
    else if (system.includes('ContextPrecisionOutput')) content = JSON.stringify({ reason: 'Provides answer', verdict: 1 });
    res.end(JSON.stringify({ choices: [{ message: { content }, finish_reason: 'stop' }], usage: { prompt_tokens: 2, completion_tokens: 1, total_tokens: 3 } }));
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const port = (server.address() as any).port;
  try {
    const { EvaluationService } = await import('../src/evaluation/index.js'); await f.service.close();
    const service = new EvaluationService(f.db, f.auth, f.models, f.index, f.jobs, { ragas: { pythonExecutable: '/home/liuxuedeng/anaconda3/bin/python', workerPath: resolve('../../workers/evaluation/worker.py') } });
    f.service = service;
    f.models.create(f.ctx, { name: 'controlled-answer', type: 'KnowledgeQA', source: 'openai', parameters: { base_url: `http://127.0.0.1:${port}/v1`, api_key: 'fixture-only-key' }, is_default: true });
    f.models.create(f.ctx, { name: 'controlled-embedding', type: 'Embedding', source: 'openai', parameters: { base_url: `http://127.0.0.1:${port}/v1`, api_key: 'fixture-only-key', dimension: 2 }, is_default: true });
    f.db.update('chunks', f.chunkId, { content: 'Paris is the capital of France.' }); f.index.indexKeyword({ tenantId: f.ctx.tenantId, knowledgeBaseIds: [f.kbId] }, f.chunkId);
    f.db.update('knowledges', f.docId, { metadata: { content: 'Paris is the capital of France. 😀\n\n'.repeat(20), source_generation: 'generation-1' } });
    const draft = service.createDataset(f.ctx, { knowledge_base_id: f.kbId, review_mode: 'auto', entries: f.entries.map((entry, index) => ({ ...entry, question: `France capital ${['Paris', 'Europe', 'French', 'City', 'Republic'][index]}` })) }); service.publish(f.ctx, draft.id);
    const input = { source: { type: 'tenant_dataset', dataset_id: draft.id, knowledge_base_id: f.kbId }, retrieval_strategy: 'keyword', rerank_enabled: false, primary_chunking_strategy: 'recursive', comparison_chunking_strategies: ['fixed_window'] };
    const created = await service.createRun(f.ctx, input, 'controlled-evaluation-run'); assert.equal(created.run_status, 'queued');
    const job = await f.jobs.run(created.run_id); assert.equal(job.status, 'completed', job.error);
    const status = service.status(f.ctx, created.run_id); assert.equal(status.verification_status, 'verified'); assert.equal(status.freshness_status, 'current'); assert.equal(status.effective_pipeline.retrieval_strategy, 'keyword');
    assert.equal(status.metrics.ragas.faithfulness, 1); assert.equal(status.metrics.samples, 5); assert.equal(requests, 45); assert.equal(status.metrics.chunking_comparison.strategies.fixed_window.full_corpus, true); assert.ok(status.metrics.chunking_comparison.strategies.recursive.index_bytes > 0);
    assert.equal(f.db.all('SELECT id FROM model_usage WHERE tenant_id=?', f.ctx.tenantId).length, requests);
    const download = service.downloadReport(f.ctx, status.report.id); const report = JSON.parse(download.bytes.toString()); assert.equal(report.metrics.samples, 5);
    assert.ok(!download.bytes.toString().includes('fixture-only-key')); assert.ok(!download.bytes.toString().includes('Paris is the capital')); assert.ok(!download.bytes.toString().includes('ground_truth'));
    assert.throws(() => service.downloadReport(f.other, status.report.id), code('report_not_found'));
    f.db.update('knowledges', f.docId, { file_hash: 'new-source' }); assert.equal(service.status(f.ctx, created.run_id).freshness_status, 'stale');
    service.deleteReport(f.ctx, status.report.id); assert.equal(service.status(f.ctx, created.run_id).report.available, false); assert.throws(() => service.downloadReport(f.ctx, status.report.id), code('report_not_found'));
  } finally { await f.close(); server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); }
});

test('legacy questions remain unverified and empty saved lists stay empty; real generation retains scoped canonical evidence', async () => {
  const f = await fixture(), { createServer } = await import('node:http');
  let requests = 0;
  const server = createServer(async (req, res) => { for await (const _chunk of req) {} requests++; res.setHeader('content-type', 'application/json'); res.end(JSON.stringify({ choices: [{ message: { content: JSON.stringify({ question: '法国首都是什么？', answer: '巴黎' }) }, finish_reason: 'stop' }], usage: { prompt_tokens: 3, completion_tokens: 2, total_tokens: 5 } })); });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    assert.equal(f.service.questions(f.ctx).questions.length, 0);
    const added = f.service.addQuestion(f.ctx, { question: '旧问题', ground_truth: '旧答案' }); assert.equal(added.question.status, 'pending_review');
    f.service.deleteQuestion(f.ctx, added.question.id); assert.equal(f.service.questions(f.ctx).questions.length, 0);
    f.models.create(f.ctx, { name: 'generator', type: 'KnowledgeQA', source: 'openai', parameters: { base_url: `http://127.0.0.1:${(server.address() as any).port}/v1`, api_key: 'controlled-key' }, is_default: true });
    const draft = await f.service.generate(f.ctx, { knowledge_base_id: f.kbId, testset_size: 5, review_mode: 'manual' });
    assert.equal(draft.entries.length, 5); assert.equal(draft.review_summary.pending, 5); assert.equal(requests, 5);
    assert.equal(draft.entries[0].evidence[0].source_end, Array.from('真实证据 😀：巴黎是法国首都。柏林是德国首都。').length);
    assert.equal(f.db.all('SELECT id FROM model_usage WHERE scenario=?', 'evaluation_generation').length, 5);
    assert.throws(() => f.service.publish(f.ctx, draft.id), code('unverified_eval_dataset'));
  } finally { await f.close(); server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); }
});

test('cancelled paid request is audited, encrypted checkpoint survives restart, and manual resume never repeats known answers', async () => {
  const f = await fixture(), { createServer } = await import('node:http');
  let requests = 0, entered!: () => void; const secondRequest = new Promise<void>(resolve => { entered = resolve; });
  const server = createServer(async (req, res) => {
    let body = ''; for await (const chunk of req) body += chunk; const input = JSON.parse(body); requests++;
    if (requests === 2) { entered(); return; }
    res.setHeader('content-type', 'application/json');
    if (req.url?.endsWith('/embeddings')) { res.end(JSON.stringify({ data: input.input.map((_: string, index: number) => ({ index, embedding: [1, 0] })), usage: { prompt_tokens: 1, total_tokens: 1 } })); return; }
    const prompt = input.messages[0].content;
    const result = prompt.includes('StatementGeneratorOutput') ? { statements: ['Paris is the capital of France.'] } : prompt.includes('NLIStatementOutput') ? { statements: [{ statement: 'Paris is the capital of France.', reason: 'In context', verdict: 1 }] } : prompt.includes('AnswerRelevanceOutput') ? { question: 'France capital', noncommittal: 0 } : prompt.includes('ContextPrecisionOutput') ? { reason: 'Provides answer', verdict: 1 } : undefined;
    res.end(JSON.stringify({ choices: [{ message: { content: result ? JSON.stringify(result) : 'Paris is the capital of France.' }, finish_reason: 'stop' }], usage: { prompt_tokens: 2, completion_tokens: 1, total_tokens: 3 } }));
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    const { EvaluationService } = await import('../src/evaluation/index.js'); await f.service.close();
    const options = { ragas: { pythonExecutable: '/home/liuxuedeng/anaconda3/bin/python', workerPath: resolve('../../workers/evaluation/worker.py') } };
    f.service = new EvaluationService(f.db, f.auth, f.models, f.index, f.jobs, options);
    for (const type of ['KnowledgeQA', 'Embedding']) f.models.create(f.ctx, { name: `controlled-${type}`, type, source: 'openai', parameters: { base_url: `http://127.0.0.1:${(server.address() as any).port}/v1`, api_key: 'fixture-only-key', ...(type === 'Embedding' ? { dimension: 2 } : {}) }, is_default: true });
    f.db.update('chunks', f.chunkId, { content: 'Paris is the capital of France.' }); f.index.indexKeyword({ tenantId: f.ctx.tenantId, knowledgeBaseIds: [f.kbId] }, f.chunkId);
    const draft = f.service.createDataset(f.ctx, { knowledge_base_id: f.kbId, review_mode: 'auto', entries: f.entries.map((entry, index) => ({ ...entry, question: `France capital ${['Paris', 'Europe', 'French', 'City', 'Republic'][index]}` })) }); f.service.publish(f.ctx, draft.id);
    const run = await f.service.createRun(f.ctx, { source: { type: 'tenant_dataset', dataset_id: draft.id, knowledge_base_id: f.kbId }, retrieval_strategy: 'keyword', rerank_enabled: false });
    const executing = f.jobs.run(run.run_id); await secondRequest;
    f.service.cancel(f.ctx, run.run_id); await executing; await f.service.close();
    assert.equal(requests, 2); const usage = f.db.all('SELECT * FROM model_usage WHERE tenant_id=? ORDER BY created_at', f.ctx.tenantId); assert.equal(usage.length, 2); assert.equal(usage[1].success, 0); assert.equal(JSON.parse(String(usage[1].metadata)).result_unknown, true);
    const checkpoints = f.db.all("SELECT data FROM generic_resources WHERE resource_type='rag_eval_checkpoints'"); assert.ok(checkpoints.every(row => !String(row.data).includes('France capital')));
    f.service = new EvaluationService(f.db, f.auth, f.models, f.index, f.jobs, options);
    assert.equal(f.service.status(f.ctx, run.run_id).result_unknown, true);
    assert.throws(() => f.service.resume(f.ctx, run.run_id), code('paid_result_unknown')); assert.equal(requests, 2);
    const resumed = f.service.resume(f.ctx, run.run_id, { acknowledge_unknown_paid_request: true }); assert.notEqual(resumed.run_id, run.run_id); assert.equal(requests, 2);
    const completed = await f.jobs.run(resumed.run_id); assert.equal(completed.status, 'completed', completed.error); assert.equal(requests, 46);
    assert.equal(f.db.all('SELECT id FROM model_usage WHERE tenant_id=?', f.ctx.tenantId).length, requests);
    assert.equal(f.service.status(f.ctx, resumed.run_id).verification_status, 'verified');
  } finally { await f.close(); server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); }
});

test('isolated production chunk comparison uses real scoped full sources and leaves business chunks and indexes intact', async () => {
  const f = await fixture();
  try {
    const module = await import('../src/evaluation/isolated-index.js').catch(() => null); assert.ok(module, 'Chunk strategies must build independent real production indexes');
    const before = f.db.all('SELECT * FROM chunks ORDER BY id');
    const content = '# Countries\n\nParis is the capital of France. 😀\n\n'.repeat(20);
    f.db.update('knowledges', f.docId, { metadata: { content, source_generation: 'generation-1' } });
    const isolated = await module.IsolatedEvaluationIndex.build(f.db, f.ctx, f.kbId, 'recursive');
    try {
      assert.ok(isolated.diagnostics.chunk_count > 1); assert.equal(isolated.diagnostics.corpus_documents, 1);
      const hit = isolated.index.keyword({ tenantId: f.ctx.tenantId, knowledgeBaseIds: [f.kbId] }, 'France', 20); assert.ok(hit.length > 0);
      for (const chunk of isolated.db.all('SELECT * FROM chunks WHERE chunk_type=?', 'text')) assert.equal(Array.from(content).slice(Number(chunk.start_at), Number(chunk.end_at)).join(''), chunk.content);
    } finally { await isolated.close(); }
    assert.deepEqual(f.db.all('SELECT * FROM chunks ORDER BY id'), before);
    assert.throws(() => module.IsolatedEvaluationIndex.sourceDocuments(f.db, f.other, f.kbId), code('knowledge_base_not_found'));
  } finally { await f.close(); }
});

test('public catalog pins variants and preparation validates actual HTTP core hashes and corpus Git blobs without importing tenant documents', async () => {
  const f = await fixture(), { createServer } = await import('node:http');
  try {
    const catalog = f.service.openDatasets(f.ctx); assert.deepEqual(catalog.datasets.map((item: any) => item.count), [180, 3045]);
    assert.equal(f.service.openStatus(f.ctx, 'open_rag_benchmark_180').ready, false);
    const queries = { first: { query: 'France capital' } }, qrels = { first: { doc: ['section'] } }, answers = { first: 'Paris' }, urls = { doc: 'https://example.test/paper' };
    const corpus = JSON.stringify({ id: 'doc', title: 'Countries', sections: [{ section_id: 'section', text: 'Paris is the capital of France.' }] });
    const gitBlob = createHash('sha1').update(`blob ${Buffer.byteLength(corpus)}\0`).update(corpus).digest('hex');
    const treeBytes = Buffer.concat([Buffer.from('100644 doc.json\0'), Buffer.from(gitBlob, 'hex')]), treeOid = createHash('sha1').update(`tree ${treeBytes.length}\0`).update(treeBytes).digest('hex');
    const files: Record<string, string> = { 'queries.json': JSON.stringify(queries), 'qrels.json': JSON.stringify(qrels), 'answers.json': JSON.stringify(answers), 'pdf_urls.json': JSON.stringify(urls) };
    const server = createServer((req, res) => {
      res.setHeader('content-type', 'application/json');
      if (req.url?.includes('/tree/') && req.url.includes('/corpus?')) res.end(JSON.stringify([{ type: 'file', path: 'pdf/arxiv/corpus/doc.json', oid: gitBlob }]));
      else if (req.url?.includes('/tree/')) res.end(JSON.stringify([{ type: 'directory', path: 'pdf/arxiv/corpus', oid: treeOid }]));
      else if (req.url?.endsWith('/corpus/doc.json')) res.end(corpus);
      else res.end(files[req.url!.split('/').at(-1)!] || '{}');
    });
    await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
    try {
      const { EvaluationService } = await import('../src/evaluation/index.js'); await f.service.close();
      const spec = { id: 'controlled_fixture', version: 'fixture-v1', label: 'Controlled protocol fixture', repository: 'fixture/corpus', revision: 'b'.repeat(40), basePath: 'pdf/arxiv', sourceUrl: 'https://example.test/source', license: 'CC0-1.0', expectedQueries: 1, artifactExpectedQueries: 1, expectedDocuments: 1, corpusTreeOid: treeOid, files: Object.fromEntries(Object.entries(files).map(([name, bytes]) => [name, createHash('sha256').update(bytes).digest('hex')])), manifestSha256: 'c'.repeat(64), artifactManifestSha256: 'c'.repeat(64), queryIds: [] };
      f.service = new EvaluationService(f.db, f.auth, f.models, f.index, f.jobs, { publicDatasetSpecs: [spec], publicOrigin: `http://127.0.0.1:${(server.address() as any).port}` });
      const queued = f.service.queuePrepareOpen(f.ctx, 'controlled_fixture', 'controlled-public-prepare'); assert.equal(queued.status, 'queued'); assert.equal(f.service.openStatus(f.ctx, 'controlled_fixture').status, 'queued');
      const preparedJob = await f.jobs.run(queued.task_id); assert.equal(preparedJob.status, 'completed', preparedJob.error);
      const prepared = f.service.openStatus(f.ctx, 'controlled_fixture'); assert.equal(prepared.ready, true); assert.deepEqual(prepared.capabilities, ['keyword']);
      assert.equal(f.db.all('SELECT id FROM knowledges').length, 1, 'Public preparation never writes tenant documents');
      assert.equal(f.db.all('SELECT id FROM chunks').length, 1);
      const { writeFileSync } = await import('node:fs'); writeFileSync(join(f.root, '.cache', 'eval-datasets', 'fixture-corpus', 'fixture-v1', 'answers.json'), '{}');
      assert.equal(f.service.openStatus(f.ctx, 'controlled_fixture').ready, false, 'Any pinned artifact change invalidates readiness');
      const { readFileSync } = await import('node:fs'), cache = join(f.root, '.cache', 'eval-datasets', 'fixture-corpus', 'fixture-v1');
      writeFileSync(join(cache, 'answers.json'), files['answers.json']);
      const forged = JSON.stringify({ id: 'doc', sections: [{ section_id: 'section', text: 'Forged corpus text' }] }), state = JSON.parse(readFileSync(join(cache, 'state.json'), 'utf8'));
      state.corpus['doc.json'] = createHash('sha1').update(`blob ${Buffer.byteLength(forged)}\0`).update(forged).digest('hex');
      writeFileSync(join(cache, 'corpus', 'doc.json'), forged); writeFileSync(join(cache, 'state.json'), JSON.stringify(state));
      assert.equal(f.service.openStatus(f.ctx, 'controlled_fixture').ready, false, 'Cache state cannot replace the pinned Git tree identity');
    } finally { server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); }
  } finally { await f.close(); }
});

test('estimates retain actual primary and comparison strategies and fingerprint the entire enabled corpus', async () => {
  const f = await fixture();
  try {
    const { EvaluationService } = await import('../src/evaluation/index.js'); await f.service.close();
    f.service = new EvaluationService(f.db, f.auth, f.models, f.index, f.jobs, { ragas: { pythonExecutable: '/home/liuxuedeng/anaconda3/bin/python', workerPath: resolve('../../workers/evaluation/worker.py') } });
    for (const type of ['KnowledgeQA', 'Embedding']) f.models.create(f.ctx, { name: `estimate-${type}`, type, source: 'openai', parameters: { base_url: 'http://127.0.0.1:9/v1', api_key: 'fixture-only-key', ...(type === 'Embedding' ? { dimension: 2 } : {}) }, is_default: true });
    const draft = f.service.createDataset(f.ctx, { knowledge_base_id: f.kbId, review_mode: 'auto', entries: f.entries }); f.service.publish(f.ctx, draft.id);
    const estimate = await f.service.estimate(f.ctx, { source: { type: 'tenant_dataset', dataset_id: draft.id, knowledge_base_id: f.kbId }, retrieval_strategy: 'keyword', rerank_enabled: false, primary_chunking_strategy: 'recursive', comparison_chunking_strategies: ['fixed_window', 'heading'] });
    assert.equal(estimate.effective_pipeline.primary_chunking_strategy, 'recursive'); assert.deepEqual(estimate.effective_pipeline.comparison_chunking_strategies, ['fixed_window', 'heading']); assert.equal(estimate.effective_pipeline.full_corpus, true);
    const legacy = await f.service.estimate(f.ctx, { source: { type: 'tenant_dataset', dataset_id: draft.id, knowledge_base_id: f.kbId }, retrieval_strategy: 'keyword', rerank_enabled: false, chunking_strategies: ['recursive', 'fixed_window'] });
    assert.equal(legacy.effective_pipeline.primary_chunking_strategy, 'recursive'); assert.deepEqual(legacy.effective_pipeline.comparison_chunking_strategies, ['fixed_window']);
    await assert.rejects(f.service.estimate(f.ctx, { source: { type: 'tenant_dataset', dataset_id: draft.id, dataset_version: '999', knowledge_base_id: f.kbId }, retrieval_strategy: 'keyword', rerank_enabled: false }), code('invalid_configuration'));
  } finally { await f.close(); }
});

test('legacy database and file reports remain scoped and downloadable without editing original artifacts', async () => {
  const f = await fixture(), { mkdirSync, writeFileSync, readFileSync } = await import('node:fs');
  try {
    const directory = join(f.root, 'legacy-cache', 'eval-reports', f.ctx.tenantId); mkdirSync(directory, { recursive: true });
    const file = join(directory, 'legacy-file.json'), bytes = JSON.stringify({ report_id: 'legacy-file', run_id: 'legacy-task', verified: true, result: { faithfulness: 0.7, question: 'private source text', api_key: 'legacy-secret' } }); writeFileSync(file, bytes);
    f.db.insert('generic_resources', { id: 'legacy-db', tenant_id: f.ctx.tenantId, resource_type: 'rag_eval_runs', name: 'Legacy evaluation', status: 'verified', data: { report_id: 'legacy-db', run_id: 'old-task', verified: true, result: { faithfulness: 0.8 } } });
    const { EvaluationService } = await import('../src/evaluation/index.js'); await f.service.close();
    f.service = new EvaluationService(f.db, f.auth, f.models, f.index, f.jobs, { legacyCacheRoot: join(f.root, 'legacy-cache') });
    const history = f.service.history(f.ctx).history;
    assert.ok(history.some((row: any) => row.report_id === 'legacy-file')); assert.ok(history.some((row: any) => row.report_id === 'legacy-db'));
    const report = f.service.downloadReport(f.ctx, 'legacy-file').bytes.toString(); assert.ok(report.includes('0.7')); assert.ok(!report.includes('private source text')); assert.ok(!report.includes('legacy-secret'));
    assert.throws(() => f.service.downloadReport(f.other, 'legacy-file'), code('report_not_found'));
    f.service.deleteReport(f.ctx, 'legacy-file'); assert.throws(() => f.service.downloadReport(f.ctx, 'legacy-file'), code('report_not_found')); assert.equal(readFileSync(file, 'utf8'), bytes);
    assert.equal(f.service.downloadReport(f.ctx, 'legacy-db').bytes.toString().includes('0.8'), true);
  } finally { await f.close(); }
});

test('pinned public five-question evaluation uses the full isolated corpus, actual HTTP usage and real Ragas', async () => {
  const f = await fixture(), { createServer } = await import('node:http');
  const queries = Object.fromEntries(Array.from({ length: 5 }, (_, index) => [`q${index}`, { query: `France capital ${index}` }]));
  const qrels = Object.fromEntries(Object.keys(queries).map(id => [id, { doc_id: 'paper', section_id: 'section' }])), answers = Object.fromEntries(Object.keys(queries).map(id => [id, 'Paris']));
  const artifacts = { 'queries.json': JSON.stringify(queries), 'qrels.json': JSON.stringify(qrels), 'answers.json': JSON.stringify(answers), 'pdf_urls.json': '{}' };
  const documents = { 'paper.json': JSON.stringify({ id: 'paper', sections: [{ section_id: 'section', text: 'Paris is the capital of France.' }] }), 'distractor.json': JSON.stringify({ id: 'distractor', sections: [{ section_id: 'other', text: 'Berlin belongs to Germany.' }] }) };
  const oids = Object.fromEntries(Object.entries(documents).map(([name, bytes]) => [name, createHash('sha1').update(`blob ${Buffer.byteLength(bytes)}\0`).update(bytes).digest('hex')]));
  const tree = Buffer.concat(Object.keys(oids).sort().map(name => Buffer.concat([Buffer.from(`100644 ${name}\0`), Buffer.from(oids[name], 'hex')]))), treeOid = createHash('sha1').update(`tree ${tree.length}\0`).update(tree).digest('hex');
  let requests = 0;
  const server = createServer(async (req, res) => {
    res.setHeader('content-type', 'application/json');
    if (req.url?.startsWith('/v1/')) {
      let body = ''; for await (const chunk of req) body += chunk; const input = JSON.parse(body); requests++;
      if (req.url.endsWith('/embeddings')) { res.end(JSON.stringify({ data: input.input.map((_: string, index: number) => ({ index, embedding: [1, 0] })), usage: { prompt_tokens: 1, total_tokens: 1 } })); return; }
      const system = input.messages[0].content;
      const result = system.includes('StatementGeneratorOutput') ? { statements: ['Paris is the capital of France.'] } : system.includes('NLIStatementOutput') ? { statements: [{ statement: 'Paris is the capital of France.', reason: 'Evidence', verdict: 1 }] } : system.includes('AnswerRelevanceOutput') ? { question: 'France capital', noncommittal: 0 } : system.includes('ContextPrecisionOutput') ? { reason: 'Evidence', verdict: 1 } : null;
      res.end(JSON.stringify({ choices: [{ message: { content: result ? JSON.stringify(result) : 'Paris is the capital of France.' }, finish_reason: 'stop' }], usage: { prompt_tokens: 2, completion_tokens: 1, total_tokens: 3 } })); return;
    }
    if (req.url?.includes('/tree/') && req.url.includes('/corpus?')) res.end(JSON.stringify(Object.keys(oids).map(name => ({ type: 'file', path: `pdf/arxiv/corpus/${name}`, oid: oids[name] }))));
    else if (req.url?.includes('/tree/')) res.end(JSON.stringify([{ type: 'directory', path: 'pdf/arxiv/corpus', oid: treeOid }]));
    else { const name = req.url!.split('/').at(-1)!; res.end((documents as any)[name] ?? (artifacts as any)[name] ?? '{}'); }
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    const { EvaluationService } = await import('../src/evaluation/index.js'); await f.service.close(); const origin = `http://127.0.0.1:${(server.address() as any).port}`;
    const spec = { id: 'public_fixture', version: 'fixture-v1', label: 'Controlled public fixture', repository: 'fixture/corpus', revision: 'b'.repeat(40), basePath: 'pdf/arxiv', sourceUrl: 'https://example.test', license: 'CC0-1.0', expectedQueries: 5, artifactExpectedQueries: 5, expectedDocuments: 2, corpusTreeOid: treeOid, files: Object.fromEntries(Object.entries(artifacts).map(([name, bytes]) => [name, createHash('sha256').update(bytes).digest('hex')])), manifestSha256: 'c'.repeat(64), artifactManifestSha256: 'c'.repeat(64), queryIds: [] };
    f.service = new EvaluationService(f.db, f.auth, f.models, f.index, f.jobs, { publicDatasetSpecs: [spec], publicOrigin: origin, ragas: { pythonExecutable: '/home/liuxuedeng/anaconda3/bin/python', workerPath: resolve('../../workers/evaluation/worker.py') } });
    for (const type of ['KnowledgeQA', 'Embedding']) f.models.create(f.ctx, { name: `public-${type}`, type, source: 'openai', parameters: { base_url: `${origin}/v1`, api_key: 'fixture-only-key', ...(type === 'Embedding' ? { dimension: 2 } : {}) }, is_default: true });
    await f.service.prepareOpen(f.ctx, 'public_fixture');
    const run = await f.service.createRun(f.ctx, { source: { type: 'open_dataset', dataset_id: 'public_fixture' }, retrieval_strategy: 'keyword', rerank_enabled: false, primary_chunking_strategy: 'recursive', comparison_chunking_strategies: ['fixed_window'] });
    const completed = await f.jobs.run(run.run_id); assert.equal(completed.status, 'completed', completed.error);
    const status = f.service.status(f.ctx, run.run_id); assert.equal(status.metrics.samples, 5); assert.equal(status.metrics.chunking_comparison.strategies.recursive.corpus_documents, 2); assert.equal(status.freshness_status, 'current'); assert.equal(requests, 45);
    assert.equal(f.db.all('SELECT id FROM model_usage').length, 45); assert.equal(f.db.all('SELECT id FROM knowledges').length, 1); assert.equal(f.db.all('SELECT id FROM chunks').length, 1);
  } finally { await f.close(); server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); }
});

test('worker protocol faults, cancellation, timeout and inherited pipes stay bounded and preserve unrelated processes', { skip: process.platform === 'win32' }, async () => {
  const { RagasBridge } = await import('../src/evaluation/ragas.js'), { writeFileSync, existsSync, readFileSync } = await import('node:fs'), { spawn } = await import('node:child_process');
  const root = mkdtempSync(join(tmpdir(), 'marlin-eval-protocol-')), python = '/usr/bin/python3', path = join(root, 'protocol fixture.py'), marker = join(root, 'child.pid');
  const other = spawn(python, ['-c', 'import time; time.sleep(60)'], { stdio: 'ignore' });
  const prefix = 'import json,sys,os,time,subprocess\nr=json.loads(sys.stdin.readline())\n';
  const valid = "assert os.environ.get('PYTHONUTF8')=='1'\nassert os.environ.get('PATH')=='/usr/bin:/usr/bin:/bin'\nprint(json.dumps({'protocol':1,'id':r['id'],'type':'result','operation':'capabilities','result':{'ragas_version':'0.4.3','django_imported':False}}),flush=True)\n";
  const alive = (pid: number) => { try { process.kill(pid, 0); return true; } catch { return false; } };
  const started = async () => { const deadline = Date.now() + 3000; while (Date.now() < deadline) { try { if (Number(readFileSync(marker, 'utf8')) > 1) return; } catch {} await new Promise(resolve => setTimeout(resolve, 10)); } assert.fail('Protocol fixture did not acknowledge its owned descendant'); };
  let bridge: InstanceType<typeof RagasBridge> | undefined;
  try {
    writeFileSync(path, prefix + "os.write(1,b'\\xff\\n')\n"); bridge = new RagasBridge({ pythonExecutable: python, workerPath: path });
    await assert.rejects(bridge.capabilities(), code('ragas_protocol_invalid'));
    writeFileSync(path, prefix + 'sys.exit(7)\n'); await assert.rejects(bridge.capabilities(), code('evaluation_worker_failed'));
    writeFileSync(path, prefix + valid); assert.equal((await bridge.capabilities()).ragas_version, '0.4.3', 'Protocol fault fixture proves bridge reusability, not installed Ragas'); await bridge.close();
    const hanging = prefix + `p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\nopen(${JSON.stringify(marker)},'w').write(str(p.pid))\ntime.sleep(60)\n`;
    writeFileSync(path, hanging); bridge = new RagasBridge({ pythonExecutable: python, workerPath: path }); const controller = new AbortController(); const cancelled = bridge.capabilities({ signal: controller.signal }); await started(); const pid = Number(readFileSync(marker, 'utf8')), before = Date.now(); controller.abort(); await assert.rejects(cancelled, code('evaluation_cancelled')); assert.ok(Date.now() - before < 3500); await bridge.close();
    const dead = (ownedPid: number) => { assert.ok(ownedPid > 1); if (!alive(ownedPid)) return true; try { return process.platform === 'linux' && readFileSync(`/proc/${ownedPid}/stat`, 'utf8').split(' ')[2] === 'Z'; } catch { return !alive(ownedPid); } }; assert.ok(dead(pid), 'Owned descendant is stopped; an unreaped zombie cannot continue executing');
    const { unlinkSync } = await import('node:fs'); unlinkSync(marker); bridge = new RagasBridge({ pythonExecutable: python, workerPath: path }); const timeoutStart = Date.now(); await assert.rejects(bridge.capabilities({ timeoutMs: 1500 }), code('evaluation_timeout')); assert.ok(Date.now() - timeoutStart < 4500); assert.ok(dead(Number(readFileSync(marker, 'utf8')))); await bridge.close();
    writeFileSync(path, prefix + `p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\nopen(${JSON.stringify(marker)},'w').write(str(p.pid))\n` + valid); bridge = new RagasBridge({ pythonExecutable: python, workerPath: path }); const exitStart = Date.now(); await bridge.capabilities({ timeoutMs: 2000 }); assert.ok(Date.now() - exitStart < 3000); assert.ok(dead(Number(readFileSync(marker, 'utf8')))); await bridge.close();
    assert.ok(alive(other.pid!), 'Cleanup retains the unrelated child');
  } finally { await bridge?.close(); other.kill(); await new Promise<void>(resolve => other.once('close', () => resolve())); rmSync(root, { recursive: true, force: true }); }
});

test('disabled documents, missing canonical sources and oversized text cannot become approved evaluation evidence', async () => {
  const f = await fixture();
  try {
    const rejected = (entry = f.entries[0]) => f.service.createDataset(f.ctx, { knowledge_base_id: f.kbId, review_mode: 'auto', entries: [entry] }).entries[0];
    f.db.update('knowledges', f.docId, { enable_status: 'disabled' }); assert.equal(rejected().status, 'rejected');
    f.db.update('knowledges', f.docId, { enable_status: 'enabled', metadata: {} }); assert.equal(rejected().status, 'rejected');
    f.db.update('knowledges', f.docId, { metadata: { content: '真实证据 😀：巴黎是法国首都。柏林是德国首都。' } });
    assert.equal(rejected({ ...f.entries[0], question: '😀'.repeat(16385) }).status, 'rejected');
  } finally { await f.close(); }
});

test('multi-context generation supplies distinct real scoped source chunks and refuses insufficient evidence before dispatch', async () => {
  const f = await fixture(), { createServer } = await import('node:http'); let requests = 0, prompt = '';
  const server = createServer(async (req, res) => { let body = ''; for await (const chunk of req) body += chunk; prompt = JSON.parse(body).messages[1].content; requests++; res.setHeader('content-type', 'application/json'); res.end(JSON.stringify({ choices: [{ message: { content: JSON.stringify({ question: '法国和德国的首都分别是什么？', answer: '巴黎和柏林' }) }, finish_reason: 'stop' }], usage: { prompt_tokens: 3, completion_tokens: 2, total_tokens: 5 } })); });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    f.models.create(f.ctx, { name: 'multi-generator', type: 'KnowledgeQA', source: 'openai', parameters: { base_url: `http://127.0.0.1:${(server.address() as any).port}/v1`, api_key: 'fixture-key' }, is_default: true });
    const input = { knowledge_base_id: f.kbId, testset_size: 1, question_types: ['multi-context'], review_mode: 'manual' };
    await assert.rejects(f.service.generate(f.ctx, input), code('evaluation_evidence_unavailable')); assert.equal(requests, 0);
    const source = '德国首都是柏林。', id = String(f.db.insert('knowledges', { tenant_id: f.ctx.tenantId, knowledge_base_id: f.kbId, title: 'Germany', file_hash: createHash('sha256').update(source).digest('hex'), metadata: { content: source } }).id);
    f.db.insert('chunks', { tenant_id: f.ctx.tenantId, knowledge_base_id: f.kbId, knowledge_id: id, content: source, start_at: 0, end_at: Array.from(source).length, is_enabled: true });
    const draft = await f.service.generate(f.ctx, input); assert.equal(draft.entries[0].evidence.length, 2); assert.equal(new Set(draft.entries[0].evidence.map((row: any) => row.chunk_id)).size, 2); assert.ok(prompt.includes('德国首都是柏林')); assert.ok(prompt.includes('真实证据')); assert.equal(requests, 1);
  } finally { await f.close(); server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); }
});

test('public selection and candidate review sampling preserve actual historical Python Random seed results', async () => {
  const module = await import('../src/evaluation/selection.js').catch(() => null); assert.ok(module, 'Historical published benchmark selection must remain reproducible');
  const ids = Array.from({ length: 20 }, (_, index) => index);
  assert.deepEqual(module.shuffled(ids, 0), [10, 18, 16, 14, 0, 17, 11, 2, 3, 9, 5, 7, 4, 19, 6, 15, 8, 1, 13, 12]);
  assert.deepEqual(module.shuffled(ids, 20260819), [3, 9, 16, 14, 8, 5, 7, 0, 1, 18, 2, 11, 12, 6, 19, 10, 4, 17, 13, 15]);
  assert.deepEqual(module.shuffled(ids, -9007199254740991), [5, 10, 8, 13, 19, 2, 9, 16, 15, 12, 11, 18, 0, 14, 1, 4, 6, 7, 17, 3]);
  assert.deepEqual(module.sampledIndices(100, 10), [62, 55, 68, 79, 18, 40, 86, 52, 89, 22]);
  const f = await fixture(); try { const draft = f.service.createDataset(f.ctx, { knowledge_base_id: f.kbId, review_mode: 'sample', entries: Array.from({ length: 100 }, (_, index) => ({ ...f.entries[0], id: String(index) })) }); assert.deepEqual(draft.entries.filter((entry: any) => entry.review_sampled).map((entry: any) => Number(entry.id)).sort((a: number, b: number) => a-b), [18, 22, 40, 52, 55, 62, 68, 79, 86, 89]); } finally { await f.close(); }
});
