import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Worker } from 'node:worker_threads';
import test from 'node:test';
import { CoreApplication } from '../src/application.js';
import { QueryClient } from '../src/runtime/query-client.js';
import type { CoreRequest } from '../src/contracts.js';

for (const revokeEpoch of [false, true]) test(`private cancellation preflight has bounded reserved priority and fences actual readonly results (${revokeEpoch ? 'epoch change' : 'saturation'})`, async () => {
  const root = await mkdtemp(join(tmpdir(), 'marlin-query-cancel-control ')), app = new CoreApplication(root);
  const issue = app.auth.register({ username: 'control-query', password: 'Control✓Password' });
  const kb = app.knowledge.knowledgeBases.create(issue.context, { name: '取消权限' });
  const doc = app.database.insert('knowledges', { tenant_id: issue.context.tenantId, knowledge_base_id: kb.id, type: 'file', title: '资料' });
  const job = app.jobs.create({ kind: 'process_knowledge', requestId: randomUUID(), recoveryPolicy: 'safe', scope: { tenantId: issue.context.tenantId, userId: issue.context.userId }, payload: { tenant_id: issue.context.tenantId, knowledge_base_id: kb.id!, knowledge_id: doc.id! } });
  app.database.update('knowledges', String(doc.id), { metadata: { workflow_job_id: job.id } });
  const authority = new SharedArrayBuffer(8), barrier = new SharedArrayBuffer(8), state = new Int32Array(barrier);
  const bootstrap = { databasePath: app.database.path, dataRoot: root, generation: randomUUID(), parserEnabled: true }, binding = { transport: 'http' as const, access: issue.credentials.access };
  const get = (): CoreRequest => ({ protocol: 1, id: randomUUID(), method: 'GET', path: '/api/v1/auth/me' });
  const cancel = (): CoreRequest => ({ protocol: 1, id: randomUUID(), method: 'POST', path: `/api/v1/knowledge/${doc.id}/cancel-parse` });
  let client: QueryClient | undefined; const pending: Promise<unknown>[] = [], order: string[] = [];
  try {
    const worker = new Worker(new URL('./fixtures/query-deadline-worker.ts', import.meta.url), { workerData: { bootstrap, authority, barrier }, execArgv: [], stdout: true, stderr: true });
    client = await QueryClient.connect(worker, bootstrap, authority, () => true);
    const first = revokeEpoch ? client.cancelPreflight(cancel(), binding, '0', () => order.push('forbidden-cas')) : client.dispatch(get(), binding, '0');
    pending.push(first); void first.catch(() => {});
    assert.notEqual(await Atomics.waitAsync(state, 0, 0, 5000).value, 'timed-out');
    if (revokeEpoch) {
      Atomics.add(new BigUint64Array(authority), 0, 1n);
      Atomics.store(state, 1, 1); Atomics.notify(state, 1);
      await assert.rejects(first, { code: 'auth_superseded', status: 409 });
      assert.deepEqual(order, [], 'a stale authorized snapshot never reaches coordinator CAS');
    } else {
      for (let i = 0; i < 32; i++) { const item = client.dispatch(get(), binding, '0').then(() => order.push(`read-${i}`)); pending.push(item); void item.catch(() => {}); }
      await assert.rejects(client.dispatch(get(), binding, '0'), { status: 429 });
      for (let i = 0; i < 8; i++) { const item = client.cancelPreflight(cancel(), binding, '0', target => { assert.equal(target?.identity.jobId, job.id); order.push(`cancel-${i}`); }); pending.push(item); void item.catch(() => {}); }
      await assert.rejects(client.cancelPreflight(cancel(), binding, '0', () => {}), { status: 429 });
      assert.equal(client.pendingCount, 41);
      Atomics.store(state, 1, 1); Atomics.notify(state, 1); await Promise.all(pending);
      assert.deepEqual(order.slice(0, 8), Array.from({ length: 8 }, (_, i) => `cancel-${i}`));
    }
  } finally { Atomics.store(state, 1, 1); Atomics.notify(state, 1); await Promise.allSettled(pending); await client?.close(); await app.close(); await rm(root, { recursive: true, force: true }); }
});
