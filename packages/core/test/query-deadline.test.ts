import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Worker } from 'node:worker_threads';
import test from 'node:test';
import { CoreApplication } from '../src/application.js';
import { QueryClient } from '../src/runtime/query-client.js';

test('actual query deadline terminates only readonly isolation, waits for exit, and preserves business data', { timeout: 30000 }, async () => {
  const root = await mkdtemp(join(tmpdir(), 'marlin-query-deadline ')), app = new CoreApplication(root);
  const issue = app.auth.register({ username: 'deadline-user', password: 'deadline-user-password' });
  const authority = new SharedArrayBuffer(8), barrier = new SharedArrayBuffer(8), state = new Int32Array(barrier), bootstrap = { databasePath: app.database.path, dataRoot: root, generation: randomUUID(), parserEnabled: false };
  let client: QueryClient | undefined;
  const request = { protocol: 1 as const, id: randomUUID(), method: 'GET' as const, path: '/api/v1/auth/me' };
  try {
    const worker = new Worker(new URL('./fixtures/query-deadline-worker.ts', import.meta.url), { workerData: { bootstrap, authority, barrier }, execArgv: [], stdout: true, stderr: true });
    client = await QueryClient.connect(worker, bootstrap, authority, () => true);
    const pending = client.dispatch(request, { transport: 'ipc', access: issue.credentials.access }, '0');
    const timeout = assert.rejects(pending, { status: 408, code: 'query_timeout' });
    assert.notEqual(await Atomics.waitAsync(state, 0, 0, 5000).value, 'timed-out');
    await timeout;
    await client.close(); assert.equal(worker.threadId, -1);
    assert.equal(app.auth.me(issue.context).user.username, 'deadline-user');
    assert.equal(app.database.get('SELECT count(*) AS n FROM device_sessions WHERE revoked_at IS NULL')?.n, 1);
    assert.equal(client.pendingCount, 0);
  } finally { Atomics.store(state, 1, 1); Atomics.notify(state, 1); await client?.close(); await app.close(); await rm(root, { recursive: true, force: true }); }
});
