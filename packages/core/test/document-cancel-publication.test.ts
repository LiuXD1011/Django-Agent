import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import test from 'node:test';
import { Worker } from 'node:worker_threads';
import { setTimeout as delay } from 'node:timers/promises';
import { AttemptState, readAttemptControl, requestCancel, type AttemptControlBridge, type DocumentAttemptIdentity } from '../src/jobs/attempt-control.js';
import { AuthService } from '../src/auth/index.js';
import { DocumentParser } from '../src/documents/parser.js';
import { DocumentWorkflow } from '../src/documents/workflow.js';
import { JobQueue } from '../src/jobs/queue.js';
import { SearchIndex } from '../src/retrieval/search-index.js';
import { ModelConfigurationService } from '../src/settings/model-configuration.js';
import { CoreDatabase } from '../src/storage/database.js';
import { CredentialVault } from '../src/storage/credentials.js';
import { ReadDatabase } from '../src/storage/read-database.js';

async function fixture(bridge?: AttemptControlBridge) {
  const root = mkdtempSync(join(tmpdir(), 'marlin-cancel-publication-'));
  const db = new CoreDatabase(root), auth = new AuthService(db), jobs = new JobQueue(db, { attemptControl: bridge }), index = new SearchIndex(db);
  const ctx = auth.register({ username: 'publication', password: 'PublicationFixture✓Password' }).context;
  const kb = db.insert('knowledge_bases', { tenant_id: ctx.tenantId, name: '事务边界', indexing_strategy: { keyword_enabled: true, vector_enabled: false, graph_enabled: false, wiki_enabled: false } });
  const models = new ModelConfigurationService(db, auth, new CredentialVault(root));
  const parser = new DocumentParser({ pythonExecutable: process.env.MARLIN_TEST_PYTHON ?? '/tmp/marlin-parser-isolation-20261010/bin/python', workerPath: resolve('../../workers/document/worker.py') });
  const workflow = new DocumentWorkflow(db, auth, jobs, models, undefined, { parser, index, scheduler: () => undefined });
  return { root, db, auth, jobs, index, ctx, kb, workflow, close: async () => { await workflow.close(); await jobs.close(); db.close(); rmSync(root, { recursive: true, force: true }); } };
}

// DOCUMENT-CANCEL-COMMIT-DESIGN: a late cancel must observe the completed attempt.
test('late document cancellation preserves the real completed outcome and published sources', async () => {
  const f = await fixture();
  try {
    const upload = await f.workflow.upload(f.ctx, String(f.kb.id), { name: '最终提交😀.txt', bytes: Buffer.from('实际Python解析和SQLite发布，late-cancel-source😀。') }, randomUUID());
    assert.equal((await f.jobs.run(upload.task_id)).status, 'completed');
    const before = f.db.read('knowledges', upload.knowledge.id)!;
    const chunks = f.db.all('SELECT * FROM chunks WHERE knowledge_id=? ORDER BY id', upload.knowledge.id);
    const events = f.jobs.events(upload.task_id, { tenantId: f.ctx.tenantId, userId: f.ctx.userId });
    const cancelled = await f.workflow.cancel(f.ctx, String(upload.knowledge.id));
    assert.equal(cancelled.status, 'completed');
    assert.deepEqual(f.db.read('knowledges', upload.knowledge.id), before);
    assert.deepEqual(f.db.all('SELECT * FROM chunks WHERE knowledge_id=? ORDER BY id', upload.knowledge.id), chunks);
    assert.deepEqual(f.jobs.events(upload.task_id, { tenantId: f.ctx.tenantId, userId: f.ctx.userId }), events);
    assert.ok(f.index.keyword({ tenantId: f.ctx.tenantId, knowledgeBaseIds: [String(f.kb.id)] }, 'late-cancel-source', 5).length);
    assert.equal(f.db.get('SELECT count(*) AS n FROM model_usage')?.n, 0);
  } finally { await f.close(); }
});

test('claim registration ACK precedes parser execution and failed ACK publishes failed task/document telemetry', async () => {
  let registerCalls = 0;
  const f = await fixture({ register: async () => { registerCalls++; throw new Error('Controlled registry rejection'); }, unregister: () => assert.fail('Unacknowledged slot must not pretend successful unregister') });
  try {
    const upload = await f.workflow.upload(f.ctx, String(f.kb.id), { name: 'ack-failure.txt', bytes: Buffer.from('No provider or parser may start before ACK') }, randomUUID());
    assert.equal((await f.jobs.run(upload.task_id)).status, 'failed');
    assert.equal(registerCalls, 1);
    assert.equal(f.db.read('task_records', upload.task_id)?.status, 'failed');
    assert.equal((f.db.read('knowledges', upload.knowledge.id)?.metadata as any).workflow_status, 'failed');
    assert.equal(f.db.read('knowledges', upload.knowledge.id)?.error_message, 'attempt_registration_failed');
    assert.equal(f.db.get('SELECT count(*) AS n FROM chunks')?.n, 0);
    assert.equal(f.db.get('SELECT count(*) AS n FROM desktop_job_steps')?.n, 0);
    assert.equal(f.db.get('SELECT count(*) AS n FROM model_usage')?.n, 0);
  } finally { await f.close(); }
});

test('deadline abort while registration ACK is pending is consumed, settles normally and starts no parser', async () => {
  let slot: SharedArrayBuffer | undefined, removed = false;
  const f = await fixture({ register: async (_identity, shared) => { slot = shared; await delay(60); }, unregister: (_identity, shared) => { assert.equal(shared, slot); assert.equal(readAttemptControl(shared).state, AttemptState.FAILED); removed = true; } });
  try {
    const upload = await f.workflow.upload(f.ctx, String(f.kb.id), { name: 'pending-ack.txt', bytes: Buffer.from('Registration must remain before handler') }, randomUUID());
    const result = await f.jobs.run(upload.task_id, { timeoutMs: 5 });
    assert.equal(result.status, 'failed'); assert.equal(removed, true);
    assert.equal(f.db.read('task_records', upload.task_id)?.status, 'failed');
    assert.equal(f.db.read('knowledges', upload.knowledge.id)?.error_message, 'job_timeout');
    assert.equal(f.db.get('SELECT count(*) AS n FROM desktop_job_steps')?.n, 0);
  } finally { await f.close(); }
});

test('a native failure of completion and failure publication returns explicit unconfirmed error instead of running success', async () => {
  let slot: SharedArrayBuffer | undefined, removed = false;
  const f = await fixture({ register: async (_identity, shared) => { slot = shared; }, unregister: () => { removed = true; } });
  try {
    const upload = await f.workflow.upload(f.ctx, String(f.kb.id), { name: 'terminal-fault.txt', bytes: Buffer.from('Preserve real locally published source😀') }, randomUUID());
    f.db.sqlite.exec("CREATE TRIGGER fixture_terminal_fault BEFORE UPDATE OF status ON desktop_jobs WHEN NEW.status IN ('completed','failed') BEGIN SELECT RAISE(ABORT,'controlled_terminal_failure'); END");
    await assert.rejects(f.jobs.run(upload.task_id), (error: any) => error.status === 503 && error.code === 'job_outcome_failed');
    assert.equal(readAttemptControl(slot!).state, AttemptState.INVALID);
    assert.equal(removed, false, 'No durable terminal ACK exists to unregister');
    assert.equal(f.db.get('SELECT status FROM desktop_jobs WHERE id=?', upload.task_id)?.status, 'running');
    assert.equal((f.db.read('knowledges', upload.knowledge.id)?.metadata as any).workflow_status, 'processing');
    assert.equal(f.db.read('task_records', upload.task_id)?.status, 'running');
    assert.equal(f.db.get("SELECT count(*) AS n FROM desktop_job_events WHERE job_id=? AND type IN ('completed','failed','cancelled')", upload.task_id)?.n, 0);
    assert.equal(f.db.get('SELECT count(*) AS n FROM model_usage')?.n, 0);
  } finally { f.db.sqlite.exec('DROP TRIGGER IF EXISTS fixture_terminal_fault'); await f.close(); }
});

test('queued cancel binds previousAttempt and source tuple and is idempotent without a synthetic owner token', async () => {
  const f = await fixture();
  try {
    const upload = await f.workflow.upload(f.ctx, String(f.kb.id), { name: 'queued.txt', bytes: Buffer.from('Exact queued cancellation') }, randomUUID());
    const target = { jobId: upload.task_id, previousAttempt: 0, tenantId: f.ctx.tenantId, jobUserId: f.ctx.userId, knowledgeId: String(upload.knowledge.id), knowledgeBaseId: String(f.kb.id) };
    for (const mismatch of [{ knowledgeId: randomUUID() }, { tenantId: '999999' }, { knowledgeBaseId: randomUUID() }, { jobUserId: randomUUID() }, { previousAttempt: 1 }]) {
      assert.equal((await f.workflow.cancelAttempt({ ...target, ...mismatch })).status, 'superseded');
      assert.equal(f.jobs.get(upload.task_id, { tenantId: f.ctx.tenantId, userId: f.ctx.userId }).status, 'queued');
    }
    assert.equal((await f.workflow.cancelAttempt(target)).status, 'cancelled');
    assert.equal((await f.workflow.cancelAttempt(target)).status, 'cancelled');
    assert.equal((await f.jobs.run(upload.task_id)).status, 'cancelled');
    assert.equal(f.db.read('task_records', upload.task_id)?.status, 'cancelled');
    assert.equal((f.db.read('knowledges', upload.knowledge.id)?.metadata as any).workflow_status, 'cancelled');
    assert.equal(f.db.get("SELECT count(*) AS n FROM desktop_job_events WHERE job_id=? AND type='cancelled'", upload.task_id)?.n, 1);
  } finally { await f.close(); }
});

test('queued preflight acknowledges only its immediate claim and a subsequent reparse remains untouched', async () => {
  let claimed!: () => void, release!: () => void;
  const entered = new Promise<void>(resolve => { claimed = resolve; }), gate = new Promise<void>(resolve => { release = resolve; });
  let actual: DocumentAttemptIdentity | undefined, shared: SharedArrayBuffer | undefined;
  const f = await fixture({ register: async (identity, control) => { actual = identity; shared = control; claimed(); await gate; }, unregister: () => {} });
  try {
    const upload = await f.workflow.upload(f.ctx, String(f.kb.id), { name: 'queued-claim-race.txt', bytes: Buffer.from('No fabricated running identity') }, randomUUID());
    const target = { jobId: upload.task_id, previousAttempt: 0, tenantId: f.ctx.tenantId, jobUserId: f.ctx.userId, knowledgeId: String(upload.knowledge.id), knowledgeBaseId: String(f.kb.id) };
    const running = f.jobs.run(upload.task_id); await entered;
    assert.equal(actual!.attempt, 1); assert.equal(actual!.previousAttempt, 0);
    let ack = false;
    const cancellation = f.workflow.cancelAttempt(target).then(result => { ack = true; return result; });
    await delay(5); assert.equal(ack, false); assert.equal(readAttemptControl(shared!).state, AttemptState.CANCEL_REQUESTED);
    release(); assert.equal((await cancellation).status, 'cancelled'); assert.equal((await running).status, 'cancelled');
    assert.equal(f.db.get('SELECT count(*) AS n FROM desktop_job_steps')?.n, 0);
    const replacement = await f.workflow.reparse(f.ctx, String(upload.knowledge.id), undefined, randomUUID());
    assert.equal((await f.workflow.cancelAttempt(target)).status, 'superseded');
    assert.equal(f.jobs.get(replacement.task_id, { tenantId: f.ctx.tenantId, userId: f.ctx.userId }).status, 'queued');
    assert.equal((f.db.read('knowledges', upload.knowledge.id)?.metadata as any).workflow_job_id, replacement.task_id);
  } finally { release(); await f.close(); }
});

type FixtureMessage = { type: string; [key: string]: any };
async function nativeFixture(phase: 'chunks' | 'fts' | 'local' | 'final', commitFault = false) {
  const root = mkdtempSync(join(tmpdir(), 'marlin-publication-worker 真实😀 '));
  const barrier = new SharedArrayBuffer(8), state = new Int32Array(barrier), messages: FixtureMessage[] = [];
  let failed: Error | undefined;
  const worker = new Worker(new URL('./fixtures/document-cancel-publication-worker.ts', import.meta.url), { workerData: { root, barrier, phase, commitFault, python: process.env.MARLIN_TEST_PYTHON ?? '/tmp/marlin-parser-isolation-20261010/bin/python', parserPath: resolve('../../workers/document/worker.py') }, execArgv: [] });
  worker.on('message', (message: FixtureMessage) => { if (message.type === 'error') failed = new Error(message.error); else messages.push(message); });
  worker.on('error', error => { failed = error; });
  const wait = async (type: string) => {
    for (let i = 0; i < 2000; i++) {
      if (failed) throw failed;
      const at = messages.findIndex(message => message.type === type);
      if (at !== -1) return messages.splice(at, 1)[0]!;
      await delay(10);
    }
    throw new Error(`Native publication fixture deadline: ${type}`);
  };
  const release = () => { Atomics.store(state, 1, 1); Atomics.notify(state, 1); };
  return { root, worker, wait, release, close: async () => {
    release();
    if (worker.threadId !== -1) {
      const exited = new Promise<void>(resolve => worker.once('exit', () => resolve()));
      worker.postMessage({ type: 'close' });
      let timer: NodeJS.Timeout | undefined;
      try { await Promise.race([exited, new Promise<void>(resolve => { timer = setTimeout(() => { void worker.terminate().then(() => resolve()); }, 3000); })]); }
      finally { clearTimeout(timer); }
    }
    rmSync(root, { recursive: true, force: true });
  } };
}

for (const phase of ['chunks', 'fts', 'local', 'final'] as const) test(`actual Worker and native ${phase} publication barrier preserve the correct cancel/COMMIT winner`, async t => {
  const f = await nativeFixture(phase);
  let reader: ReadDatabase | undefined;
  try {
    const ready = await f.wait('ready');
    reader = new ReadDatabase(join(f.root, 'marlin.sqlite3'), f.root);
    f.worker.postMessage({ type: 'run' });
    const registration = await f.wait('registered');
    assert.equal(registration.identity.previousAttempt, 0);
    assert.equal(registration.identity.attempt, 1);
    // The actual claim is durable, while handler/parser work is still blocked on ACK.
    assert.equal(reader.get('SELECT status FROM desktop_jobs WHERE id=?', ready.taskId)?.status, 'running');
    assert.equal(reader.get('SELECT status FROM task_records WHERE id=?', ready.taskId)?.status, 'pending');
    assert.equal(reader.get('SELECT count(*) AS n FROM desktop_job_steps WHERE job_id=?', ready.taskId)?.n, 0);
    f.worker.postMessage({ type: 'ack', ownerToken: registration.identity.ownerToken });
    const blocked = await f.wait('barrier');
    assert.equal(blocked.evidence.inTransaction, true);
    if (phase === 'chunks') assert.match(blocked.evidence.insertedChunkId, /^[a-f0-9-]{36}$/);
    else assert.ok(Number(blocked.evidence.newChunks) > 0);
    if (phase === 'final') {
      assert.notEqual((reader.read('knowledges', ready.docId)?.metadata as any).source_generation, ready.before.doc.metadata.source_generation);
      assert.equal((reader.read('knowledges', ready.docId)?.metadata as any).workflow_status, 'processing');
      assert.equal(reader.get('SELECT status FROM desktop_jobs WHERE id=?', ready.taskId)?.status, 'running');
      assert.equal(reader.get('SELECT status FROM task_records WHERE id=?', ready.taskId)?.status, 'running');
    } else {
      assert.equal((reader.read('knowledges', ready.docId)?.metadata as any).source_generation, ready.before.doc.metadata.source_generation);
      assert.deepEqual(reader.all('SELECT * FROM chunks WHERE knowledge_id=? ORDER BY id', ready.docId), ready.before.chunks);
    }
    const requestedAt = performance.now(), cancellation = requestCancel(registration.shared);
    assert.equal(cancellation.disposition, phase === 'final' ? 'finalizing' : phase === 'local' ? 'after_local_commit' : 'requested');
    f.worker.postMessage({ type: 'cancel', identity: registration.identity });
    f.release();
    const [run, cancelled, unregister] = await Promise.all([f.wait('result'), f.wait('cancel-result'), f.wait('unregistered')]);
    const status = phase === 'final' ? 'completed' : 'cancelled';
    assert.equal(run.result.status, status);
    assert.equal(cancelled.result.status, status);
    assert.equal(run.after.doc.metadata.workflow_status, status);
    assert.equal(unregister.control.state, phase === 'final' ? AttemptState.DONE : AttemptState.CANCELLED_DURABLE);
    assert.equal(readAttemptControl(registration.shared).state, unregister.control.state);
    assert.equal(run.after.runningSpans, 0); assert.equal(run.after.runningSteps, 0);
    assert.deepEqual(run.after.foreignKeys, []); assert.equal(run.after.modelCalls, 0);
    if (phase === 'chunks' || phase === 'fts') {
      assert.equal(run.after.doc.metadata.source_generation, ready.before.doc.metadata.source_generation);
      assert.deepEqual(run.after.chunks, ready.before.chunks); assert.deepEqual(run.after.fts, ready.before.fts); assert.deepEqual(run.after.registry, ready.before.registry);
    } else {
      assert.notEqual(run.after.doc.metadata.source_generation, ready.before.doc.metadata.source_generation);
      assert.ok(run.after.chunks.length); assert.ok(run.after.fts.length);
    }
    assert.equal(run.after.tasks.find((task: any) => task.id === ready.taskId).status, status);
    t.diagnostic(JSON.stringify({ phase, control: { ...cancellation, ordinal: String(cancellation.ordinal) }, observed_sql: blocked.evidence, request_to_terminal_and_cleanup_ms: performance.now() - requestedAt }, (_key, value) => typeof value === 'bigint' ? value.toString() : value));
  } finally { reader?.close(); await f.close(); }
});

test('actual deferred FK failure after FINAL permission rolls back completion and publishes failure, never DONE', async () => {
  const f = await nativeFixture('final', true);
  try {
    await f.wait('ready'); f.worker.postMessage({ type: 'run' });
    const registration = await f.wait('registered'); f.worker.postMessage({ type: 'ack', ownerToken: registration.identity.ownerToken });
    const barrier = await f.wait('barrier'); assert.equal(barrier.evidence.control.state, AttemptState.COMMITTING_FINAL);
    assert.equal(requestCancel(registration.shared).disposition, 'finalizing');
    f.worker.postMessage({ type: 'cancel', identity: registration.identity }); f.release();
    const [run, cancelled, unregister] = await Promise.all([f.wait('result'), f.wait('cancel-result'), f.wait('unregistered')]);
    assert.equal(run.result.status, 'failed'); assert.equal(cancelled.result.status, 'failed');
    assert.equal(run.after.doc.metadata.workflow_status, 'failed');
    assert.equal(run.after.tasks.find((task: any) => task.id === run.result.id).status, 'failed');
    assert.equal(unregister.control.state, AttemptState.FAILED);
    assert.equal(run.after.runningSpans, 0); assert.equal(run.after.runningSteps, 0); assert.deepEqual(run.after.foreignKeys, []);
    assert.equal(run.after.modelCalls, 0);
  } finally { await f.close(); }
});
