import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import test from 'node:test';
import { AuthService } from '../src/auth/index.js';
import { AttemptState, readAttemptControl, type DocumentAttemptIdentity } from '../src/jobs/attempt-control.js';
import { JobQueue, type JobContext } from '../src/jobs/queue.js';
import { CoreDatabase } from '../src/storage/database.js';

function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'marlin-job-attempt-')), db = new CoreDatabase(root), auth = new AuthService(db);
  const ctx = auth.register({ username: 'attempt', password: 'AttemptFixture✓Password' }).context;
  const kb = db.insert('knowledge_bases', { tenant_id: ctx.tenantId, name: 'Attempt' });
  const doc = db.insert('knowledges', { tenant_id: ctx.tenantId, knowledge_base_id: kb.id, title: 'Attempt source' });
  let identity: DocumentAttemptIdentity | undefined, shared: SharedArrayBuffer | undefined, removed = false;
  const queue = new JobQueue(db, { attemptControl: { register: async (actual, control) => { identity = actual; shared = control; }, unregister: () => { removed = true; } } });
  const job = queue.create({ scope: { tenantId: ctx.tenantId, userId: ctx.userId }, kind: 'process_knowledge', requestId: randomUUID(), recoveryPolicy: 'safe', payload: { tenant_id: ctx.tenantId, knowledge_id: doc.id!, knowledge_base_id: kb.id! } });
  db.update('knowledges', doc.id!, { metadata: { workflow_job_id: job.id } });
  return { root, db, ctx, kb, doc, queue, job, get identity() { return identity!; }, get shared() { return shared!; }, get removed() { return removed; }, close: async () => { await queue.close(); db.close(); rmSync(root, { recursive: true, force: true }); } };
}

test('nested attempt publications share outer ordinal and refuse an unowned external transaction', async () => {
  const f = fixture();
  try {
    f.queue.register('process_knowledge', async context => {
      assert.throws(() => f.db.transaction(() => context.publish(() => f.db.update('knowledges', f.doc.id!, { description: 'foreign' }))), (error: any) => error.code === 'foreign_transaction');
      assert.equal(f.db.read('knowledges', f.doc.id!)?.description, '');
      context.publish(() => {
        f.db.update('knowledges', f.doc.id!, { description: 'outer durable' });
        context.publish(() => f.db.insert('chunks', { tenant_id: f.ctx.tenantId, knowledge_base_id: f.kb.id, knowledge_id: f.doc.id, content: 'nested original source😀' }));
        assert.deepEqual(readAttemptControl(f.shared), { state: AttemptState.ACTIVE, ordinal: 0n });
        assert.equal(f.db.sqlite.inTransaction, true);
      });
      assert.deepEqual(readAttemptControl(f.shared), { state: AttemptState.ACTIVE, ordinal: 1n });
      assert.equal(f.db.sqlite.inTransaction, false);
      return { actual: true };
    });
    assert.equal((await f.queue.run(f.job.id)).status, 'completed');
    assert.deepEqual(readAttemptControl(f.shared), { state: AttemptState.DONE, ordinal: 2n });
    assert.equal(f.db.read('knowledges', f.doc.id!)?.description, 'outer durable');
    assert.equal(f.db.get('SELECT count(*) AS n FROM chunks')?.n, 1); assert.equal(f.removed, true);
  } finally { await f.close(); }
});

test('precise cancellation waits real owned child exit and handler finally, rejecting stale tuple changes', async () => {
  const f = fixture();
  let started!: () => void, cleaned = false;
  const ready = new Promise<void>(resolve => { started = resolve; });
  let owned: ReturnType<JobContext['spawnOwned']> | undefined;
  try {
    f.queue.register('process_knowledge', async context => {
      owned = context.spawnOwned(process.execPath, ['-e', "process.stdout.write('ready');setInterval(()=>{},1000)"]);
      await new Promise<void>((resolve, reject) => { owned!.child.stdout.once('data', () => resolve()); owned!.child.once('error', reject); });
      started();
      try { return await owned.completion; } finally { await delay(25); cleaned = true; }
    });
    const running = f.queue.run(f.job.id); await ready;
    for (const patch of [{ attempt: 2 }, { ownerToken: 'wrong-owner' }, { previousAttempt: 3 }, { jobUserId: 'different-user' }, { knowledgeBaseId: randomUUID() }]) {
      assert.equal((await f.queue.cancelClaim({ ...f.identity, ...patch })).status, 'superseded');
      assert.equal(owned!.child.exitCode, null); assert.equal(readAttemptControl(f.shared).state, AttemptState.ACTIVE);
    }
    let acknowledged = false;
    const cancellation = f.queue.cancelClaim(f.identity).then(result => { acknowledged = true; return result; });
    await delay(5); assert.equal(acknowledged, false);
    assert.equal((await cancellation).status, 'cancelled'); assert.equal((await running).status, 'cancelled');
    assert.equal(cleaned, true); assert.equal(owned!.child.exitCode !== null || owned!.child.signalCode !== null, true);
    assert.equal(f.removed, true); assert.equal(readAttemptControl(f.shared).state, AttemptState.CANCELLED_DURABLE);
  } finally { await f.close(); }
});

test('initializer can register a synchronous outcome but cannot publish or spawn a helper before ACK', async () => {
  for (const action of ['publish', 'spawn'] as const) {
    const f = fixture(); let handlerCalls = 0;
    try {
      f.queue.register('process_knowledge', async () => { handlerCalls++; return {}; }, context => {
        context.onOutcome(() => {});
        if (action === 'publish') context.publish(() => f.db.update('knowledges', f.doc.id!, { description: 'forbidden' }));
        else context.spawnOwned(process.execPath, ['-e', 'process.exit(0)']);
      });
      assert.equal((await f.queue.run(f.job.id)).status, 'failed');
      assert.equal(handlerCalls, 0); assert.equal(f.db.read('knowledges', f.doc.id!)?.description, '');
      assert.equal(f.db.get('SELECT count(*) AS n FROM chunks')?.n, 0);
    } finally { await f.close(); }
  }
});
