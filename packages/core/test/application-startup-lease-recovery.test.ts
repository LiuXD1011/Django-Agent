import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import test from 'node:test';
import { CoreApplication } from '../src/application.js';
import { AuthService } from '../src/auth/index.js';
import { DocumentParser } from '../src/documents/parser.js';
import { JobQueue, type Job } from '../src/jobs/queue.js';
import { CoreDatabase } from '../src/storage/database.js';

// Persisted crash fixtures use real queues and SQLite; no parser or model work is replayed.
function fixture(leaseUntil: number) {
  const directory = mkdtempSync(join(tmpdir(), 'marlin-startup-lease-recovery-'));
  const db = new CoreDatabase(directory), auth = new AuthService(db), queue = new JobQueue(db);
  const ctx = auth.register({ username: 'lease-fixture', password: 'Startup lease unit fixture password #1' }).context;
  const scope = { tenantId: ctx.tenantId, userId: ctx.userId };
  const kb = db.insert('knowledge_bases', { tenant_id: ctx.tenantId, name: 'Lease fixture' });
  const doc = db.insert('knowledges', {
    tenant_id: ctx.tenantId, knowledge_base_id: kb.id, title: 'Published source',
    parse_status: 'completed', processed_at: new Date().toISOString(), pending_subtasks_count: 1,
    metadata: { content: 'Preserved source😀', source_generation: 'original-source' },
  });
  const document = queue.create({ scope, kind: 'process_knowledge', requestId: randomUUID(), recoveryPolicy: 'manual',
    payload: { knowledge_id: doc.id!, knowledge_base_id: kb.id!, auth: ctx as any } });
  const running = (job: Job) => db.run('UPDATE desktop_jobs SET status=\'running\',attempt=1,payload=? WHERE id=?',
    JSON.stringify({ input: job.payload, claim: { ownerToken: 'earlier-core-owner', leaseUntil } }), job.id);
  running(document);
  db.update('knowledges', String(doc.id), { metadata: { ...doc.metadata as object, workflow_job_id: document.id, workflow_status: 'processing' } });
  db.insert('task_records', { id: document.id, task_type: 'process_knowledge', status: 'running', payload: { knowledge_id: doc.id! } });
  const span = db.insert('knowledge_processing_spans', { knowledge_id: doc.id, attempt: 1, span_id: randomUUID(),
    name: 'process_knowledge', kind: 'root', status: 'running', started_at: new Date().toISOString(),
    metadata: { job_id: document.id, queue_attempt: 1 } });
  const session = db.insert('sessions', { tenant_id: ctx.tenantId, user_id: ctx.userId, title: 'Interrupted actor' });
  const requestId = randomUUID(), message = db.insert('messages', { session_id: session.id, role: 'assistant', request_id: requestId });
  const actor = db.insert('agent_actors', { session_id: session.id, parent_message_id: message.id, actor_id: 'fixture-actor', status: 'running' });
  const actorJob = queue.create({ scope, kind: 'chat.actor', requestId: randomUUID(), recoveryPolicy: 'manual',
    payload: { session_id: session.id!, message_id: message.id!, actor_row_id: actor.id!, request_id: requestId } });
  running(actorJob); db.update('agent_actors', String(actor.id), { metadata: { job_id: actorJob.id } });
  const evaluation = queue.create({ scope, kind: 'rag_evaluation', requestId: randomUUID(), recoveryPolicy: 'manual', payload: {} });
  running(evaluation);
  db.insert('generic_resources', { id: evaluation.id, tenant_id: ctx.tenantId, resource_type: 'rag_eval_runs', status: 'running',
    data: { requested_configuration: {}, fingerprint: {} } });
  db.close();
  const app = new CoreApplication(directory, { parser: new DocumentParser({
    pythonExecutable: resolve(process.env.MARLIN_TEST_PYTHON ?? '/tmp/marlin-parser-isolation-20261010/bin/python'),
    workerPath: resolve('../../workers/document/worker.py'),
  }) });
  return { app, directory, ctx, scope, doc, document, span, actor, actorJob, evaluation,
    async close() { await app.close(); rmSync(directory, { recursive: true, force: true }); } };
}

test('startup waits for live leases then reconciles document, actor and evaluation without manual replay', async context => {
  const initial = Date.now(); context.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: initial });
  const f = fixture(initial + 1000);
  try {
    const before = f.app.database.read('knowledges', String(f.doc.id));
    context.mock.timers.tick(999);
    assert.equal(f.app.jobs.get(f.document.id, f.scope).status, 'running');
    assert.deepEqual(f.app.database.read('knowledges', String(f.doc.id)), before);
    context.mock.timers.tick(1);
    assert.equal(f.app.jobs.get(f.document.id, f.scope).status, 'interrupted');
    assert.equal(f.app.database.read('task_records', f.document.id)?.status, 'interrupted');
    assert.equal(f.app.database.read('knowledge_processing_spans', String(f.span.id))?.status, 'interrupted');
    const recovered = f.app.database.read('knowledges', String(f.doc.id))!;
    assert.equal((recovered.metadata as any).workflow_status, 'interrupted');
    assert.equal((recovered.metadata as any).content, 'Preserved source😀');
    assert.equal((recovered.metadata as any).source_generation, 'original-source');
    assert.equal(recovered.parse_status, 'completed'); assert.equal(recovered.pending_subtasks_count, 0);
    assert.equal(f.app.jobs.get(f.actorJob.id, f.scope).status, 'interrupted');
    assert.equal(f.app.database.read('agent_actors', String(f.actor.id))?.status, 'interrupted');
    assert.equal(f.app.evaluation.status(f.ctx, f.evaluation.id).status, 'interrupted');
    for (const job of [f.document, f.actorJob, f.evaluation]) assert.equal(f.app.jobs.get(job.id, f.scope).attempt, 1);
    assert.equal(f.app.database.get('SELECT count(*) AS n FROM model_usage')?.n, 0);
  } finally { await f.close(); }
});

test('startup recovery rechecks a renewed lease instead of preempting its live owner', async context => {
  const initial = Date.now(); context.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: initial });
  const f = fixture(initial + 1000);
  try {
    context.mock.timers.tick(500);
    f.app.database.run("UPDATE desktop_jobs SET payload=json_set(payload,'$.claim.leaseUntil',?) WHERE id=?", initial + 3000, f.document.id);
    context.mock.timers.tick(500);
    assert.equal(f.app.jobs.get(f.document.id, f.scope).status, 'running');
    context.mock.timers.tick(1999);
    assert.equal(f.app.jobs.get(f.document.id, f.scope).status, 'running');
    context.mock.timers.tick(1);
    assert.equal(f.app.jobs.get(f.document.id, f.scope).status, 'interrupted');
    assert.equal(f.app.database.read('task_records', f.document.id)?.status, 'interrupted');
    assert.equal(f.app.database.get('SELECT count(*) AS n FROM model_usage')?.n, 0);
  } finally { await f.close(); }
});

test('application shutdown cancels pending startup recovery before closing storage', async context => {
  const initial = Date.now(); context.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: initial });
  const f = fixture(initial + 1000);
  try {
    await f.app.close();
    let reads = 0; const all = f.app.database.all.bind(f.app.database), get = f.app.database.get.bind(f.app.database);
    f.app.database.all = ((...args: Parameters<typeof all>) => { reads++; return all(...args); }) as typeof all;
    f.app.database.get = ((...args: Parameters<typeof get>) => { reads++; return get(...args); }) as typeof get;
    assert.doesNotThrow(() => context.mock.timers.tick(10000));
    assert.equal(reads, 0);
  } finally { await f.close(); }
});

test('startup recovery stops monitoring after its original jobs finish and does not enroll new jobs', async context => {
  const initial = Date.now(); context.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: initial });
  const f = fixture(initial + 1000);
  try {
    const later = f.app.jobs.create({ scope: f.scope, kind: 'rag_evaluation', requestId: randomUUID(), recoveryPolicy: 'manual', payload: {} });
    f.app.database.run("UPDATE desktop_jobs SET status='running',attempt=1,payload=? WHERE id=?",
      JSON.stringify({ input: later.payload, claim: { ownerToken: 'later-task-owner', leaseUntil: initial + 2000 } }), later.id);
    context.mock.timers.tick(1000);
    assert.equal(f.app.jobs.get(f.document.id, f.scope).status, 'interrupted');
    context.mock.timers.tick(2000);
    assert.equal(f.app.jobs.get(later.id, f.scope).status, 'running');
    assert.equal(f.app.jobs.get(later.id, f.scope).attempt, 1);
    assert.equal(f.app.database.get('SELECT count(*) AS n FROM model_usage')?.n, 0);
  } finally { await f.close(); }
});

test('document recovery locks and rechecks the queue before modifying a newly claimed attempt', async () => {
  const f = fixture(Date.now() + 100000), other = new CoreDatabase(f.directory);
  const queue = new JobQueue(other); let release!: () => void, running: ReturnType<JobQueue['run']> | undefined;
  queue.register('process_knowledge', async () => { await new Promise<void>(resolve => release = resolve); return {}; });
  try {
    f.app.database.run("UPDATE desktop_jobs SET status='interrupted' WHERE id=?", f.document.id);
    const transaction = f.app.database.transaction.bind(f.app.database); let calls = 0, before: unknown, currentSpanId = '';
    f.app.database.transaction = work => {
      if (++calls === 2) {
        queue.retry(f.document.id, f.scope); running = queue.run(f.document.id);
        other.update('task_records', f.document.id, { status: 'running', attempt_count: 2 });
        const doc = other.read('knowledges', String(f.doc.id))!;
        other.update('knowledges', String(f.doc.id), { pending_subtasks_count: 1,
          metadata: { ...doc.metadata as object, workflow_status: 'processing', workflow_attempt: 2 } });
        currentSpanId = String(other.insert('knowledge_processing_spans', { knowledge_id: f.doc.id, attempt: 2,
          span_id: randomUUID(), name: 'process_knowledge', kind: 'root', status: 'running', started_at: new Date().toISOString(),
          metadata: { job_id: f.document.id, queue_attempt: 2 } }).id);
        before = { doc: other.read('knowledges', String(f.doc.id)), task: other.read('task_records', f.document.id),
          span: other.read('knowledge_processing_spans', currentSpanId) };
      }
      return transaction(work);
    };
    f.app.documents!.recover(); f.app.database.transaction = transaction;
    assert.equal(queue.get(f.document.id, f.scope).attempt, 2);
    assert.deepEqual({ doc: f.app.database.read('knowledges', String(f.doc.id)), task: f.app.database.read('task_records', f.document.id),
      span: f.app.database.read('knowledge_processing_spans', currentSpanId) }, before);
    await Promise.resolve(); release(); await running;
  } finally {
    await Promise.resolve(); release?.(); await running; await queue.close(); other.close(); await f.close();
  }
});
