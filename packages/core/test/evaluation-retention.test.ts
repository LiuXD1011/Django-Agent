import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { createServer } from 'node:http';
import type { AddressInfo } from 'node:net';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { CoreApplication } from '../src/application.js';
import { CoreIpcAdapter } from '../src/adapters/ipc.js';
import { createCoreHttpServer } from '../src/adapters/http.js';
import type { HttpMethod, JsonObject } from '../src/contracts.js';

for (const transport of ['http', 'ipc'] as const) test(`${transport}: retained deterministic evaluation and legacy RAG entry points use scoped actual algorithms`, async t => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-evaluation-retention-'));
  const app = new CoreApplication(root, { allowAutoSetup: true }), server = createCoreHttpServer(app, { port: 0 });
  try {
    const issue = app.auth.autoSetup({ email: 'evaluation-retention@example.invalid', password: 'evaluation-retention-fixture' });
    const { origin } = await server.listen(), ipc = new CoreIpcAdapter(app);
    const login = await ipc.invoke({ protocol: 1, id: randomUUID(), method: 'POST', path: '/api/v1/auth/login', body: { login: 'evaluation-retention@example.invalid', password: 'evaluation-retention-fixture' } });
    assert.equal(login.status, 200);
    const request = async (method: HttpMethod, path: string, body?: JsonObject) => {
      if (transport === 'ipc') return ipc.invoke({ protocol: 1, id: randomUUID(), method, path, ...(body ? { body } : {}) });
      const response = await fetch(origin + path, { method, headers: { authorization: `Bearer ${issue.credentials.access}`, 'content-type': 'application/json' }, ...(body ? { body: JSON.stringify(body) } : {}) });
      return { status: response.status, body: await response.json() };
    };
    const kb = app.knowledge.knowledgeBases.create(issue.context, { name: 'Retention fixture' }), content = 'Marlin sea salt maintenance belongs to Lin Ming.';
    const doc = app.database.insert('knowledges', { tenant_id: issue.context.tenantId, knowledge_base_id: kb.id, title: 'Sea salt', file_hash: 'fixture-hash', parse_status: 'completed', metadata: { content, source_generation: 'v1', parser_blocks: [{ id: 'p', kind: 'text', block_index: 0, block_type: 'paragraph', text: content, canonical_range: { start: 0, end: content.length }, provenance: {}, metadata: {} }] } });
    const chunk = app.database.insert('chunks', { tenant_id: issue.context.tenantId, knowledge_base_id: kb.id, knowledge_id: doc.id, content, start_at: 0, end_at: content.length, seq_id: '1' });
    app.searchIndex.indexKeyword({ tenantId: issue.context.tenantId, knowledgeBaseIds: [String(kb.id)] }, String(chunk.id));
    const entries = Array.from({ length: 5 }, (_, i) => ({ question: `sea salt maintenance ${i}`, answer: 'Lin Ming', evidence: [{ chunk_id: chunk.id!, knowledge_id: doc.id!, source_start: 0, source_end: content.length, source_quote: content }] }));
    const created = await request('POST', '/api/v1/rag-eval/datasets', { knowledge_base_id: kb.id!, entries, review_mode: 'manual' });
    const candidate = (created.body as JsonObject).data as JsonObject;
    const published = await request('POST', `/api/v1/rag-eval/datasets/${candidate.id}/review`, { entry_ids: (candidate.entries as JsonObject[]).map(entry => entry.id!), status: 'approved', publish: true });
    assert.equal(published.status, 200);
    const input: JsonObject = { source: { type: 'tenant_dataset', dataset_id: candidate.id!, knowledge_base_id: kb.id! }, retrieval_strategy: 'keyword', rerank_enabled: false };
    await t.test('legacy /run retains configuration guard rather than 404', async () => {
      const value = await request('POST', '/api/v1/rag-eval/run', { ...input, dataset_id: candidate.id!, knowledge_base_id: kb.id! });
      assert.equal(value.status, 422); assert.equal(((value.body as JsonObject).error as JsonObject).code, 'needs_configuration');
    });
    for (const kind of ['retrieval', 'chunking']) await t.test(`${kind} computes actual span metrics and downloadable report without answer/judge calls`, async () => {
      const value = await request('POST', `/api/v1/rag-eval/${kind}`, { ...input, strategies: ['fixed_window', 'recursive'] });
      assert.equal(value.status, 200);
      const data = (value.body as JsonObject).data as JsonObject;
      assert.equal(data.evaluation_type, kind); assert.equal(data.verification_status, 'verified');
      assert.equal(data.freshness_status, 'current');
      const metrics = data.metrics as JsonObject;
      assert.equal(kind === 'retrieval' ? metrics.mrr_new : (metrics.primary as JsonObject).mrr_at_10, 1);
      assert.equal((metrics as JsonObject).metrics_scope, 'retrieval_and_resources_only');
      assert.ok(data.report_id);
      assert.equal(app.database.get('SELECT count(*) AS n FROM chunks')?.n, 1, 'comparison must not replace production chunks');
      const history = await request('GET', '/api/v1/rag-eval/history');
      assert.ok(((history.body as JsonObject).data as JsonObject).history instanceof Array);
      assert.ok((((history.body as JsonObject).data as JsonObject).history as JsonObject[]).some(item => item.report_id === data.report_id && item.evaluation_type === kind && item.legacy_import !== true));
      if (transport === 'ipc') { const report = await request('GET', `/api/v1/rag-eval/reports/${data.report_id}`); assert.equal(report.status, 200); assert.ok('binary' in report); }
      else { const report = await fetch(origin + `/api/v1/rag-eval/reports/${data.report_id}`, { headers: { authorization: `Bearer ${issue.credentials.access}` } }); assert.equal(report.status, 200); assert.equal((await report.json()).evaluation_type, kind); }
    });
    await t.test('candidate versions preserve publication and edit/delete work on both actual transports', async () => {
      const version = await request('POST', `/api/v1/rag-eval/datasets/${candidate.id}/versions`, {}), next = (version.body as JsonObject).data as JsonObject;
      const entry = (next.entries as JsonObject[])[0]!;
      const edited = await request('PATCH', `/api/v1/rag-eval/datasets/${next.id}/entries/${entry.id}`, { question: 'Corrected salt question', answer: 'Lin Ming corrected', reference_answer: 'Lin Ming corrected', ground_truth: 'Lin Ming corrected' });
      assert.equal(edited.status, 200); const changed = (((edited.body as JsonObject).data as JsonObject).entries as JsonObject[])[0]!;
      assert.equal(changed.status, 'pending_review'); assert.deepEqual(changed.evidence, entry.evidence);
      const deleted = await request('DELETE', `/api/v1/rag-eval/datasets/${next.id}/entries/${entry.id}`); assert.equal(deleted.status, 200); assert.equal((((deleted.body as JsonObject).data as JsonObject).entries as JsonObject[]).length, 4);
      const immutable = await request('DELETE', `/api/v1/rag-eval/datasets/${candidate.id}/entries/${entry.id}`); assert.equal(immutable.status, 409);
      const missing = await request('POST', '/api/v1/rag-eval/retrieval', { ...input, retrieval_strategy: 'vector' }); assert.equal(missing.status, 422); assert.equal(((missing.body as JsonObject).error as JsonObject).code, 'needs_configuration');
      const unverified = await request('POST', '/api/v1/rag-eval/chunking', { strategies: ['fixed_window'] }); assert.equal(unverified.status, 422);
    });
    assert.equal(app.database.get('SELECT count(*) AS n FROM model_usage')?.n, 0);
  } finally { await server.close(); await app.close(); rmSync(root, { recursive: true, force: true }); }
});

test('dedicated public source-span evaluation uses pinned real HTTP corpus without tenant imports or Ragas', async () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-evaluation-public-retention-'));
  const queries = Object.fromEntries(Array.from({ length: 5 }, (_, i) => [`q${i}`, { query: `Sea salt ${i}` }])), answers = Object.fromEntries(Object.keys(queries).map(id => [id, 'Sea'])), qrels = Object.fromEntries(Object.keys(queries).map(id => [id, { doc_id: 'doc', section_id: 's' }]));
  const corpus = JSON.stringify({ id: 'doc', title: 'Salt', sections: [{ section_id: 's', text: 'Sea salt comes from the sea.' }] });
  const oid = createHash('sha1').update(`blob ${Buffer.byteLength(corpus)}\0`).update(corpus).digest('hex'), tree = Buffer.concat([Buffer.from('100644 doc.json\0'), Buffer.from(oid, 'hex')]), treeOid = createHash('sha1').update(`tree ${tree.length}\0`).update(tree).digest('hex');
  const files: Record<string, string> = { 'queries.json': JSON.stringify(queries), 'answers.json': JSON.stringify(answers), 'qrels.json': JSON.stringify(qrels), 'pdf_urls.json': '{}' };
  const server = createServer((req, res) => { res.setHeader('content-type', 'application/json'); res.end(req.url?.includes('/tree/') ? JSON.stringify(req.url.includes('/corpus?') ? [{ type: 'file', path: 'pdf/arxiv/corpus/doc.json', oid }] : [{ type: 'directory', path: 'pdf/arxiv/corpus', oid: treeOid }]) : req.url?.endsWith('/corpus/doc.json') ? corpus : files[req.url!.split('/').at(-1)!] || '{}'); });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const app = new CoreApplication(root, { allowAutoSetup: true, evaluation: { publicOrigin: `http://127.0.0.1:${(server.address() as AddressInfo).port}`, publicDatasetSpecs: [{ id: 'fixture_public', version: 'v1', label: 'Fixture', repository: 'fixture/corpus', revision: 'b'.repeat(40), basePath: 'pdf/arxiv', sourceUrl: 'https://example.invalid', license: 'CC0-1.0', expectedQueries: 5, artifactExpectedQueries: 5, expectedDocuments: 1, corpusTreeOid: treeOid, files: Object.fromEntries(Object.entries(files).map(([name, value]) => [name, createHash('sha256').update(value).digest('hex')])), manifestSha256: 'c'.repeat(64), artifactManifestSha256: 'c'.repeat(64), queryIds: [] }] } });
  try {
    const issue = app.auth.autoSetup({ password: 'public-retention-fixture-password' }); await app.evaluation.prepareOpen(issue.context, 'fixture_public');
    for (const kind of ['retrieval', 'chunking'] as const) {
      const result = await app.evaluation.runDeterministic(issue.context, kind, { open_dataset_id: 'fixture_public', sample_size: 5, retrieval_strategy: 'keyword', rerank_enabled: false, strategies: ['fixed_window', 'recursive'] });
      assert.equal(result.verification_status, 'verified'); assert.equal(result.freshness_status, 'current'); assert.equal(result.evaluation_type, kind);
    }
    assert.equal(app.database.get('SELECT count(*) AS n FROM knowledges')?.n, 0); assert.equal(app.database.get('SELECT count(*) AS n FROM model_usage')?.n, 0);
  } finally { await app.close(); server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); rmSync(root, { recursive: true, force: true }); }
});

test('dedicated vector comparison audits actual HTTP embeddings, isolates corpus and awaits cancellation before close', async () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-evaluation-vector-retention-')), app = new CoreApplication(root, { allowAutoSetup: true });
  let received = 0, block = false, entered!: () => void; const waiting = new Promise<void>(resolve => { entered = resolve; });
  const server = createServer(async (request, response) => {
    let raw = ''; for await (const bytes of request) raw += bytes;
    const body = JSON.parse(raw); received++;
    assert.ok(request.url?.endsWith('/embeddings'), 'deterministic path must never dispatch answer/judge completions');
    if (block) { entered(); return; }
    response.setHeader('content-type', 'application/json'); response.end(JSON.stringify({ data: body.input.map((_: string, index: number) => ({ index, embedding: [1, 0] })), usage: { prompt_tokens: body.input.length, total_tokens: body.input.length } }));
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    const issue = app.auth.autoSetup({ password: 'vector-retention-fixture-password' }), kb = app.knowledge.knowledgeBases.create(issue.context, { name: 'Independent corpus' }), content = 'Sea salt belongs to the sea.';
    app.database.update('knowledge_bases', String(kb.id), { chunking_config: { chunk_size: 128, chunk_overlap: 32 } });
    const doc = app.database.insert('knowledges', { tenant_id: issue.context.tenantId, knowledge_base_id: kb.id, file_hash: 'fixture-version', metadata: { content, source_generation: 'v1' } });
    const chunk = app.database.insert('chunks', { tenant_id: issue.context.tenantId, knowledge_base_id: kb.id, knowledge_id: doc.id, content, start_at: 0, end_at: content.length });
    const content2 = 'An unrelated source with no relevant answer.'.repeat(40);
    app.database.insert('knowledges', { tenant_id: issue.context.tenantId, knowledge_base_id: kb.id, file_hash: 'other-version', metadata: { content: content2, source_generation: 'v1' } });
    const draft = app.evaluation.createDataset(issue.context, { knowledge_base_id: kb.id!, entries: [{ question: 'Sea salt', answer: 'Sea', evidence: [{ chunk_id: chunk.id!, knowledge_id: doc.id!, source_start: 0, source_end: content.length }] }] }); app.evaluation.publish(issue.context, String(draft.id));
    app.models.create(issue.context, { name: 'controlled-embedding', type: 'Embedding', source: 'openai', parameters: { base_url: `http://127.0.0.1:${(server.address() as AddressInfo).port}/v1`, api_key: 'fixture-only', dimension: 2 }, is_default: true });
    const input: JsonObject = { source: { type: 'tenant_dataset', dataset_id: draft.id!, knowledge_base_id: kb.id! }, strategies: ['fixed_window'], retrieval_strategy: 'vector', rerank_enabled: false };
    const before = app.database.all('SELECT * FROM chunks ORDER BY id'), result = await app.evaluation.runDeterministic(issue.context, 'chunking', input, 'vector-known');
    assert.equal(result.verification_status, 'verified'); assert.equal(((result.metrics as JsonObject).primary as JsonObject).corpus_documents, 2); assert.ok(Number(((result.metrics as JsonObject).primary as JsonObject).chunk_count) > 10, 'fixed window must inherit actual KB size and overlap');
    assert.deepEqual(app.database.all('SELECT * FROM chunks ORDER BY id'), before);
    assert.equal(app.database.get('SELECT count(*) AS n FROM model_usage')?.n, received);
    await app.evaluation.runDeterministic(issue.context, 'chunking', input, 'vector-known'); assert.equal(app.database.get('SELECT count(*) AS n FROM model_usage')?.n, received, 'completed request ID returns report without replay');
    const other = app.auth.register({ email: 'scope-retention@example.invalid', password: 'scope-retention-fixture-password' });
    await assert.rejects(app.evaluation.runDeterministic(other.context, 'chunking', input), { code: 'dataset_not_found' }); assert.throws(() => app.evaluation.getReport(other.context, String(result.report_id)), { code: 'report_not_found' });
    app.database.update('knowledges', String(doc.id), { metadata: { content, source_generation: 'v2' } }); assert.equal(app.evaluation.getReport(issue.context, String(result.report_id)).freshness_status, 'stale');
    app.database.update('knowledges', String(doc.id), { metadata: { content, source_generation: 'v1' } });
    block = true; const pending = app.evaluation.runDeterministic(issue.context, 'chunking', input, 'vector-cancel'); const rejected = assert.rejects(pending); await waiting;
    const start = performance.now(); await app.evaluation.close(); await rejected; assert.ok(performance.now() - start < 2000);
    const usage = app.database.all('SELECT success,metadata FROM model_usage ORDER BY created_at,id'); assert.equal(usage.length, received); assert.equal(usage.at(-1)!.success, 0); assert.equal(JSON.parse(String(usage.at(-1)!.metadata)).result_unknown, true);
    assert.equal(app.database.get("SELECT count(*) AS n FROM generic_resources WHERE resource_type='rag_eval_deterministic_runs' AND status='cancelled'")?.n, 1);
  } finally { await app.close(); server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); rmSync(root, { recursive: true, force: true }); }
});

for (const validBeforeFailure of [0, 1]) test(`generation keeps ${validBeforeFailure} paid valid candidates when the next actual HTTP result is malformed and audits business failure`, async () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-evaluation-generation-retention-')), app = new CoreApplication(root, { allowAutoSetup: true }); let requests = 0;
  const server = createServer(async (request, response) => { for await (const _ of request) {} requests++; response.setHeader('content-type', 'application/json'); response.end(JSON.stringify({ choices: [{ message: { content: requests <= validBeforeFailure ? JSON.stringify({ question: `What is sea salt ${requests}?`, answer: 'Salt from the sea.' }) : 'not valid JSON' }, finish_reason: 'stop' }], usage: { prompt_tokens: 12, completion_tokens: 7, total_tokens: 19 } })); });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    const issue = app.auth.autoSetup({ password: 'generation-retention-fixture-password' }), kb = app.knowledge.knowledgeBases.create(issue.context, { name: 'Generation evidence' }), content = 'Sea salt is salt obtained from the sea. 😀';
    const doc = app.database.insert('knowledges', { tenant_id: issue.context.tenantId, knowledge_base_id: kb.id, file_hash: 'fixture-generation-v1', metadata: { content, source_generation: 'v1' } });
    app.database.insert('chunks', { tenant_id: issue.context.tenantId, knowledge_base_id: kb.id, knowledge_id: doc.id, content, start_at: 0, end_at: Array.from(content).length });
    app.models.create(issue.context, { name: 'local-generator', type: 'KnowledgeQA', source: 'openai', parameters: { base_url: `http://127.0.0.1:${(server.address() as AddressInfo).port}/v1`, api_key: 'fixture-only' }, is_default: true });
    await assert.rejects(app.evaluation.generate(issue.context, { knowledge_base_id: kb.id!, testset_size: 3, review_mode: 'manual' }), { code: 'evaluation_generation_invalid' });
    assert.equal(requests, validBeforeFailure + 1, 'malformed responses must never retry automatically');
    const drafts = app.evaluation.listDatasets(issue.context, 'testsets').testsets as JsonObject[];
    assert.equal(drafts.length, 1, 'paid partial work must survive as a discoverable draft');
    const draft = drafts[0]!, generation = draft.generation as JsonObject;
    assert.equal(draft.status, 'draft'); assert.equal(generation.status, 'failed'); assert.equal(generation.completed_count, validBeforeFailure); assert.equal(generation.requested_count, 3); assert.equal(generation.error_code, 'evaluation_generation_invalid');
    assert.equal((draft.entries as JsonObject[]).length, validBeforeFailure);
    if (validBeforeFailure) { const entry = (draft.entries as JsonObject[])[0]!; assert.equal(entry.status, 'pending_review'); assert.equal((entry.evidence as JsonObject[])[0]!.source_quote, content); app.evaluation.editEntry(issue.context, String(draft.id), String(entry.id), { question: 'Reviewed question' }); }
    const usage = app.database.all('SELECT success,prompt_tokens,completion_tokens FROM model_usage ORDER BY created_at,id'); assert.equal(usage.length, requests); assert.equal(usage.at(-1)!.success, 0); assert.equal(usage.at(-1)!.prompt_tokens, 12); assert.equal(usage.at(-1)!.completion_tokens, 7);
    const other = app.auth.register({ email: 'generation-scope@example.invalid', password: 'generation-scope-fixture-password' }); assert.throws(() => app.evaluation.getDataset(other.context, String(draft.id)), { code: 'dataset_not_found' });
  } finally { await app.close(); server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); rmSync(root, { recursive: true, force: true }); }
});

test('restart retains generation candidates and marks an unfinished paid checkpoint unknown without replay', async () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-evaluation-generation-restart-')); let app = new CoreApplication(root, { allowAutoSetup: true });
  try {
    const issue = app.auth.autoSetup({ password: 'generation-restart-fixture-password' }), kb = app.knowledge.knowledgeBases.create(issue.context, { name: 'Restart evidence' }), content = 'Sea salt comes from the sea.';
    const doc = app.database.insert('knowledges', { tenant_id: issue.context.tenantId, knowledge_base_id: kb.id, file_hash: 'restart-fixture', metadata: { content } });
    const chunk = app.database.insert('chunks', { tenant_id: issue.context.tenantId, knowledge_base_id: kb.id, knowledge_id: doc.id, content, start_at: 0, end_at: content.length });
    const draft = app.evaluation.createDataset(issue.context, { knowledge_base_id: kb.id!, review_mode: 'manual', entries: [{ question: 'Where does salt come from?', answer: 'The sea.', evidence: [{ chunk_id: chunk.id!, knowledge_id: doc.id!, source_start: 0, source_end: content.length }] }] });
    // Persist the exact pre-crash checkpoint; this represents an interrupted process, not a vendor success.
    const row = app.database.read('generic_resources', String(draft.id))!, data = row.data as JsonObject;
    app.database.update('generic_resources', String(draft.id), { data: { ...data, generation: { status: 'running', requested_count: 3, completed_count: 1, owner_user_id: issue.context.userId, error_code: '', result_unknown: false } } });
    await app.close(); app = new CoreApplication(root, { allowAutoSetup: true });
    const recovered = app.evaluation.getDataset(issue.context, String(draft.id)), generation = recovered.generation as JsonObject;
    assert.equal(generation.status, 'interrupted'); assert.equal(generation.result_unknown, true); assert.equal(generation.error_code, 'paid_result_unknown');
    assert.deepEqual(recovered.entries, draft.entries); assert.equal(app.database.get('SELECT count(*) AS n FROM model_usage')?.n, 0);
    app.evaluation.editEntry(issue.context, String(draft.id), String((draft.entries as JsonObject[])[0]!.id), { question: 'Reviewed after restart' });
  } finally { await app.close(); rmSync(root, { recursive: true, force: true }); }
});
