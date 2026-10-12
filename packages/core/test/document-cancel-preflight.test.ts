import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test, { type TestContext } from 'node:test';
import { AuthService } from '../src/auth/index.js';
import { CoreDatabase } from '../src/storage/database.js';
import { ReadDatabase } from '../src/storage/read-database.js';
import { KnowledgeService } from '../src/knowledge/index.js';
import { JobQueue, type JobContext } from '../src/jobs/queue.js';
import { QueryDispatcher, isQueryRequest } from '../src/runtime/query-dispatcher.js';
import type { CoreRequest } from '../src/contracts.js';

async function fixture(t: TestContext) {
  const root = mkdtempSync(join(tmpdir(), 'marlin-cancel-preflight 真实 '));
  const db = new CoreDatabase(root), auth = new AuthService(db), queue = new JobQueue(db);
  const issue = auth.register({ username: 'cancel-reader', password: 'Cancel✓PrivatePassword' });
  const other = auth.register({ username: 'cancel-other', password: 'Cancel✓OtherPassword' });
  const knowledge = new KnowledgeService(db, auth);
  const kb = knowledge.knowledgeBases.create(issue.context, { name: '精确取消资料' });
  const doc = db.insert('knowledges', { tenant_id: issue.context.tenantId, knowledge_base_id: kb.id, type: 'file', title: '资料', parse_status: 'completed', metadata: { content: '旧完整资料😀' } });
  const job = queue.create({ kind: 'process_knowledge', requestId: randomUUID(), recoveryPolicy: 'safe', scope: { tenantId: issue.context.tenantId, userId: issue.context.userId }, payload: { tenant_id: issue.context.tenantId, knowledge_base_id: kb.id!, knowledge_id: doc.id! } });
  db.update('knowledges', String(doc.id), { metadata: { ...doc.metadata as object, workflow_job_id: job.id } });
  const reader = new ReadDatabase(db.path, root), dispatcher = new QueryDispatcher(reader, true);
  let release!: () => void, claimed!: (ctx: JobContext) => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  const actualClaim = new Promise<JobContext>(resolve => { claimed = resolve; });
  queue.register('process_knowledge', async ctx => { claimed(ctx); await gate; return {}; });
  let running: Promise<unknown> | undefined;
  t.after(async () => { release(); await running; await queue.close(); reader.close(); db.close(); rmSync(root, { recursive: true, force: true }); });
  const request: CoreRequest = { protocol: 1, id: randomUUID(), method: 'POST', path: `/api/v1/knowledge/${doc.id}/cancel-parse?fixture=1`, body: {} };
  const binding = { transport: 'http' as const, access: issue.credentials.access };
  // The missing private capability is the first product RED, not a fake SQL result.
  const preflight = (token = binding.access) => dispatcher.cancelPreflight(request, { ...binding, access: token });
  return { db, auth, queue, issue, other, kb, doc, job, reader, request, preflight, async claim() { running = queue.run(job.id); return actualClaim; } };
}

test('private cancellation preflight authorizes exact queued and actual running claim on native readonly SQLite', async t => {
  const f = await fixture(t);
  assert.equal(isQueryRequest(f.request), false, 'cancel stays outside the public readonly GET audit');
  const before = f.db.get('SELECT total_changes() AS n')!.n;
  const queued = f.preflight(); assert.equal(queued.response.status, 200);
  assert.ok(queued.target);
  assert.deepEqual(queued.target, { state: 'queued', identity: { jobId: f.job.id, previousAttempt: 0, tenantId: f.issue.context.tenantId, jobUserId: f.issue.context.userId, knowledgeId: String(f.doc.id), knowledgeBaseId: String(f.kb.id) } });
  const claim = await f.claim();
  const running = f.preflight(); assert.equal(running.response.status, 200);
  assert.deepEqual(running.target, { state: 'running', identity: { ...queued.target.identity, attempt: claim.attempt, ownerToken: claim.ownerToken } });
  const afterClaim = f.db.get('SELECT total_changes() AS n')!.n;
  assert.ok(Number(afterClaim) > Number(before));
  f.preflight(); assert.equal(f.db.get('SELECT total_changes() AS n')!.n, afterClaim, 'preflight never writes');
  assert.equal(JSON.stringify(running.response).includes(claim.ownerToken), false, 'claim credentials never become renderer response fields');
});

test('terminal queued cancellation retains a null claim and cannot create a fictitious running attempt', async t => {
  const f = await fixture(t);
  f.queue.cancelByRequest(f.job.requestId, f.job.scope);
  const result = f.preflight(); assert.equal(result.response.status, 200);
  assert.deepEqual(result.target, { state: 'terminal', identity: { jobId: f.job.id, previousAttempt: 0, tenantId: f.issue.context.tenantId, jobUserId: f.issue.context.userId, knowledgeId: String(f.doc.id), knowledgeBaseId: String(f.kb.id) } });
});

test('private cancellation preflight fails closed for principal, scope, payload and lease changes', async t => {
  const f = await fixture(t); await f.claim();
  assert.equal(f.preflight('invalid').response.status, 401);
  assert.equal(f.preflight(f.other.credentials.access).response.status, 404);
  const payload = String(f.db.get('SELECT payload FROM desktop_jobs WHERE id=?', f.job.id)!.payload);
  f.db.run("UPDATE desktop_jobs SET payload=json_set(payload,'$.input.knowledge_base_id','wrong') WHERE id=?", f.job.id);
  assert.equal(f.preflight().response.status, 409);
  f.db.run('UPDATE desktop_jobs SET payload=? WHERE id=?', payload, f.job.id);
  f.db.run("UPDATE desktop_jobs SET payload=json_set(payload,'$.claim.leaseUntil',0) WHERE id=?", f.job.id);
  assert.equal(f.preflight().response.status, 409);
  f.db.run('UPDATE desktop_jobs SET payload=? WHERE id=?', payload, f.job.id);
  f.db.run("UPDATE tenant_members SET status='revoked' WHERE tenant_id=? AND user_id=?", f.issue.context.tenantId, f.issue.context.userId);
  assert.equal(f.preflight().response.status, 401);
});

test('parser availability is checked after the existing authentication boundary', async t => {
  const f = await fixture(t), disabled = new QueryDispatcher(f.reader, false);
  assert.equal(disabled.cancelPreflight(f.request, { transport: 'ipc' }).response.status, 401);
  assert.equal(disabled.cancelPreflight(f.request, { transport: 'ipc', access: f.issue.credentials.access }).response.status, 503);
});

test('no-job native snapshots retain the original JavaScript status coercion for legacy JSON values', async t => {
  const f = await fixture(t);
  for (const status of [true, false, null, '', 0, 3, 'completed', ['legacy', 'state'], { legacy: 'state' }]) {
    f.db.update('knowledges', String(f.doc.id), { metadata: { workflow_status: status } });
    const result = f.preflight(); assert.equal(result.response.status, 200);
    assert.equal(result.target, undefined);
    assert.deepEqual((result.response.body as { data: unknown }).data, { knowledge_id: String(f.doc.id), task_id: '', status: String(status || 'completed') });
  }
});
