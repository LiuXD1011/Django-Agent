import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { once } from 'node:events';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { isAbsolute, join } from 'node:path';
import { test } from 'node:test';
import { CoreDatabase } from '../src/storage/database.js';
import { CredentialVault } from '../src/storage/credentials.js';
import { AuthService } from '../src/auth/index.js';
import { ModelConfigurationService } from '../src/settings/index.js';
import { SearchIndex } from '../src/retrieval/search-index.js';
import { JobQueue } from '../src/jobs/queue.js';
import { EvaluationService, RagasBridge } from '../src/evaluation/index.js';

const pythonExecutable = process.env.MARLIN_TEST_PYTHON ?? (process.platform === 'win32' ? '' : '/usr/bin/python3');
assert.ok(isAbsolute(pythonExecutable), 'An absolute trusted Python executable is required; on Windows set MARLIN_TEST_PYTHON to an owned helper copy');

const code = (expected: string) => (error: any) => error.code === expected;
// This helper uses two deterministic RPCs per row to prove checkpoint fencing and transport cancellation only.
// The unchanged evaluation.test.ts separately verifies the installed Ragas 0.4.3 algorithms with localhost models.
const worker = `import json,sys,uuid
r=json.loads(sys.stdin.readline())
def send(kind,**data):
 print(json.dumps(dict(protocol=1,id=r['id'],type=kind,**data)),flush=True)
if r['operation']=='capabilities':
 send('result',operation='capabilities',result=dict(ragas_version='0.4.3',django_imported=False))
else:
 scores=[]
 for i,row in enumerate(r['rows']):
  for index in (1,2):
   send('model_call',call_id=str(uuid.uuid4()),example_id=row['example_id'],call_index=index,operation='chat',prompt='fixture-'+row['example_id']+'-'+str(index),schema=dict(type='object'))
   json.loads(sys.stdin.readline())
  scores.append(dict(example_id=row['example_id'],faithfulness=1,answer_relevancy=1,context_precision=1))
  send('progress',completed=i+1,total=len(r['rows']),example_id=row['example_id'])
 send('result',operation='evaluate',result=dict(rows=scores))
`;

test('executor supplies batch budget; worker deadline audit survives restart, completed calls reuse and unknown retry needs explicit unchanged-config confirmation', async () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-evaluation-budget-recovery-')), db = new CoreDatabase(root), auth = new AuthService(db);
  const ctx = auth.register({ username: 'owner', password: 'TemporaryFixturePassword' }).context;
  const models = new ModelConfigurationService(db, auth, new CredentialVault(root)), index = new SearchIndex(db), jobs = new JobQueue(db), path = join(root, 'fixture.py'); writeFileSync(path, worker);
  let requests = 0, hold = true, disconnected = false;
  const server = createServer(async (req, res) => {
    for await (const _chunk of req) {} requests++;
    if (requests === 7 && hold) { res.on('close', () => { disconnected = true; }); res.setHeader('content-type', 'application/json'); res.write('{'); return; }
    res.setHeader('content-type', 'application/json'); res.end(JSON.stringify({ choices: [{ message: { content: 'Paris is the capital of France.' }, finish_reason: 'stop' }], usage: { prompt_tokens: 2, completion_tokens: 1, total_tokens: 3 } }));
  });
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  const options = { ragas: { pythonExecutable, workerPath: path } };
  let service = new EvaluationService(db, auth, models, index, jobs, options);
  const planned: number[] = [];
  const configureFixtureDeadline = () => {
    const bridge = (service as unknown as { bridge: RagasBridge }).bridge, original = bridge.evaluate.bind(bridge);
    bridge.evaluate = (rows, callback, callOptions) => { planned.push(callOptions?.timeoutMs ?? 0); assert.equal(callOptions?.timeoutMs, 2500000, 'Executor must pass its computed serial scoring budget'); return original(rows, callback, { ...callOptions, timeoutMs: 2000 }); };
  };
  configureFixtureDeadline();
  try {
    const parameters = { base_url: `http://127.0.0.1:${(server.address() as any).port}/v1`, api_key: 'fixture-only-key', timeoutMs: 60000 };
    const judge = models.create(ctx, { name: 'fixture-chat', type: 'KnowledgeQA', source: 'openai', parameters, is_default: true });
    models.create(ctx, { name: 'fixture-embedding', type: 'Embedding', source: 'openai', parameters: { ...parameters, dimension: 2 }, is_default: true });
    const kbId = String(db.insert('knowledge_bases', { tenant_id: ctx.tenantId, name: 'Evidence' }).id), source = 'Paris is the capital of France.';
    const docId = String(db.insert('knowledges', { tenant_id: ctx.tenantId, knowledge_base_id: kbId, title: 'Evidence', file_hash: createHash('sha256').update(source).digest('hex'), metadata: { content: source } }).id);
    const chunkId = String(db.insert('chunks', { tenant_id: ctx.tenantId, knowledge_base_id: kbId, knowledge_id: docId, content: source, start_at: 0, end_at: source.length, is_enabled: true }).id); index.indexKeyword({ tenantId: ctx.tenantId, knowledgeBaseIds: [kbId] }, chunkId);
    const entries = Array.from({ length: 5 }, (_, i) => ({ question: `France capital ${i}`, answer: 'Paris', evidence: [{ chunk_id: chunkId, knowledge_id: docId, source_start: 0, source_end: source.length }] }));
    const draft = service.createDataset(ctx, { knowledge_base_id: kbId, review_mode: 'auto', entries }); service.publish(ctx, String(draft.id));
    const run = await service.createRun(ctx, { source: { type: 'tenant_dataset', dataset_id: draft.id, knowledge_base_id: kbId }, retrieval_strategy: 'keyword', rerank_enabled: false });
    const failed = await jobs.run(String(run.run_id));
    assert.deepEqual(planned, [2500000]); assert.equal(failed.status, 'failed'); assert.equal(requests, 7); assert.equal(disconnected, true);
    const failedEvents = jobs.events(String(run.run_id), { tenantId: ctx.tenantId, userId: ctx.userId }); assert.equal(failedEvents.at(-1)?.type, 'failed');
    const usage = db.all('SELECT * FROM model_usage WHERE tenant_id=? ORDER BY created_at,id', ctx.tenantId); assert.equal(usage.length, 7);
    assert.equal(usage.filter(row => row.success === 0).length, 1); const unknownUsage = usage.find(row => row.success === 0)!;
    assert.equal(unknownUsage.error_message, 'model_cancelled'); assert.equal(JSON.parse(String(unknownUsage.metadata)).result_unknown, true);
    const knownIds = usage.filter(row => row.success !== 0).map(row => row.id).sort();
    assert.equal(db.all("SELECT id FROM generic_resources WHERE resource_type='rag_eval_invocations' AND status='completed'").length, 6);
    assert.equal(db.all("SELECT id FROM generic_resources WHERE resource_type='rag_eval_invocations' AND status='unknown'").length, 1);
    await service.close(); service = new EvaluationService(db, auth, models, index, jobs, options); configureFixtureDeadline();
    const stopped = service.status(ctx, String(run.run_id)); assert.equal(stopped.result_unknown, true); assert.equal(stopped.run_status, 'failed');
    assert.throws(() => service.resume(ctx, String(run.run_id)), code('paid_result_unknown')); assert.equal(requests, 7);
    models.update(ctx, String(judge.id), { parameters: { timeoutMs: 61000 } });
    assert.throws(() => service.resume(ctx, String(run.run_id), { acknowledge_unknown_paid_request: true }), code('checkpoint_mismatch')); assert.equal(requests, 7);
    models.update(ctx, String(judge.id), { parameters: { timeoutMs: 60000 } }); hold = false;
    const resumed = service.resume(ctx, String(run.run_id), { acknowledge_unknown_paid_request: true }); assert.equal(resumed.run_id, run.run_id); assert.equal(requests, 7);
    const completed = await jobs.run(String(resumed.run_id)); assert.equal(completed.status, 'completed', completed.error); assert.equal(requests, 16); assert.deepEqual(planned, [2500000, 2500000]);
    const after = db.all('SELECT * FROM model_usage WHERE tenant_id=?', ctx.tenantId); assert.equal(after.length, requests); assert.deepEqual(after.filter(row => knownIds.includes(row.id)).map(row => row.id).sort(), knownIds);
    assert.equal(service.status(ctx, String(run.run_id)).result_unknown, false); assert.equal(service.status(ctx, String(run.run_id)).verification_status, 'verified');
    assert.equal(db.all("SELECT id FROM generic_resources WHERE resource_type='rag_eval_invocations' AND status='completed'").length, 15);
  } finally { await service.close(); await jobs.close(); db.close(); server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); rmSync(root, { recursive: true, force: true }); }
});
