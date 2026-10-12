import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { Worker } from 'node:worker_threads';
import test from 'node:test';
import type { CoreRequest, CoreResponse, HttpMethod, JsonObject } from '../src/contracts.js';
import { AttemptState, readAttemptControl, type DocumentAttemptIdentity } from '../src/jobs/attempt-control.js';
import { CoreOwner } from '../src/runtime/owner-client.js';
import { QueryClient } from '../src/runtime/query-client.js';
import { openNativeDatabase } from '../src/storage/database.js';

const request = (method: HttpMethod, path: string, body?: JsonObject): CoreRequest => ({ protocol: 1, id: randomUUID(), method, path, ...(body ? { body } : {}) });
function data(response: CoreResponse): JsonObject {
  assert.ok(response.body && typeof response.body === 'object' && !Array.isArray(response.body));
  const value = response.body.data;
  assert.ok(value && typeof value === 'object' && !Array.isArray(value));
  return value;
}

test('a real authorized no-job snapshot cannot cancel a document claim created before its late response arrives', { timeout: 45000 }, async () => {
  // Independent stage3 review P2: old owner-route fallback selected a future
  // claim. Only the trusted startup factory attaches a real barrier Worker;
  // every SQL/auth/dispatch/workflow operation below uses production code.
  const root = await mkdtemp(join(tmpdir(), 'marlin-no-job-cancel 真实 '));
  const python = spawnSync('python', ['-c', 'import sys;print(sys.executable)'], { encoding: 'utf8' }); assert.equal(python.status, 0);
  const authority = new SharedArrayBuffer(8), barrier = new SharedArrayBuffer(24), state = new Int32Array(barrier), generation = randomUUID();
  const originalStart = QueryClient.start;
  let owner: CoreOwner | undefined, shared: SharedArrayBuffer | undefined, identity: DocumentAttemptIdentity | undefined;
  let observed!: () => void;
  const actualAttempt = new Promise<void>(resolveAttempt => { observed = resolveAttempt; });
  let cancellation: Promise<CoreResponse> | undefined;
  try {
    QueryClient.start = async (bootstrap, sharedAuthority, ownerAlive) => {
      const query = new Worker(new URL('./fixtures/query-no-job-worker.ts', import.meta.url), { workerData: { bootstrap, authority: sharedAuthority, barrier }, execArgv: [], stdout: true, stderr: true });
      return QueryClient.connect(query, bootstrap, sharedAuthority, ownerAlive);
    };
    const worker = new Worker(new URL('./fixtures/core-owner-no-job-worker.ts', import.meta.url), { workerData: { config: { dataRoot: root, parser: { pythonExecutable: python.stdout.trim(), workerPath: resolve('../../workers/document/worker.py'), timeoutMs: 10000 } }, authority, generation, barrier }, execArgv: [], stdout: true, stderr: true });
    worker.on('message', message => { if (message.type === 'fixture-attempt') { shared = message.shared; identity = message.identity; observed(); } });
    owner = await CoreOwner.connect(worker, { authority, generation });
    assert.equal((await owner.invoke(request('POST', '/api/v1/auth/auto-setup', { password: 'no-job-fixture-private-password' }))).status, 200);
    const base = data(await owner.invoke(request('POST', '/api/v1/knowledge-bases', { name: '未来任务保护', indexing_strategy: { keyword_enabled: true, vector_enabled: false, graph_enabled: false, wiki_enabled: false } })));
    const legacy = data(await owner.invoke(request('POST', '/api/v1/fixture/no-job-file', { knowledge_base_id: base.id! })));
    const docId = String(legacy.id);
    cancellation = owner.invoke(request('POST', `/api/v1/knowledge/${docId}/cancel-parse`)); void cancellation.catch(() => {});
    assert.notEqual(await Atomics.waitAsync(state, 0, 0, 5000).value, 'timed-out', 'actual authenticated no-job snapshot must finish first');
    assert.equal(Atomics.load(state, 5), 0, 'snapshot really contains no target job');
    const newer = await owner.invoke(request('POST', `/api/v1/knowledge/${docId}/reparse`)); assert.equal(newer.status, 200);
    const newJob = String(data(newer).task_id);
    assert.notEqual(await Atomics.waitAsync(state, 2, 0, 5000).value, 'timed-out', 'future job is durably claimed and acknowledged by actual registry');
    await actualAttempt; // Atomics notification may precede MessagePort delivery.
    assert.ok(shared); assert.ok(identity); assert.equal(identity.jobId, newJob); assert.equal(identity.knowledgeId, docId);
    assert.equal(readAttemptControl(shared).state, AttemptState.ACTIVE);
    Atomics.store(state, 1, 1); Atomics.notify(state, 1);
    const boundary = await Promise.race([
      cancellation.then(response => ({ kind: 'reply' as const, response })),
      Promise.resolve(Atomics.waitAsync(state, 4, 0, 5000).value).then(waited => { assert.notEqual(waited, 'timed-out', 'late cancellation must reply or reach the actual owner route'); return { kind: 'owner-route' as const }; }),
    ]);
    assert.equal(readAttemptControl(shared).state, AttemptState.ACTIVE, 'the old no-job cancellation must leave the future actual claim ACTIVE');
    assert.equal(boundary.kind, 'reply', 'a no-job result is a terminal no-op, with no later owner route selection');
    assert.ok('response' in boundary); assert.equal(boundary.response.status, 200);
    assert.deepEqual(data(boundary.response), { knowledge_id: docId, task_id: '', status: 'completed' });
    Atomics.store(state, 3, 1); Atomics.notify(state, 3);
    let completed = false;
    for (let i = 0; i < 300; i++) {
      const current = data(await owner.invoke(request('GET', `/api/v1/knowledge/${docId}`)));
      assert.ok(!['cancelled', 'failed', 'interrupted'].includes(String(current.workflow_status)), 'future job must survive old cancellation');
      if (current.workflow_status === 'completed') { completed = true; break; }
      await new Promise<void>(resolveWait => setTimeout(resolveWait, 20));
    }
    assert.ok(completed, 'future actual Python/chunk/publication job must complete');
    await owner.close();
    const sqlite = openNativeDatabase(join(root, 'marlin.sqlite3'), { readonly: true, fileMustExist: true });
    try {
      assert.equal((sqlite.prepare('SELECT status FROM desktop_jobs WHERE id=?').get(newJob) as { status: string }).status, 'completed');
      const content = (sqlite.prepare("SELECT json_extract(metadata,'$.content') AS content FROM knowledges WHERE id=?").get(docId) as { content: string }).content;
      assert.ok(content.includes('futureonlysurvival') && content.includes('中文资料😀'), 'surviving future job publishes complete real source');
      assert.equal((sqlite.prepare('SELECT count(*) AS n FROM model_usage').get() as { n: number }).n, 0);
    } finally { sqlite.close(); }
  } finally {
    for (const index of [1, 3, 4]) { Atomics.store(state, index, 1); Atomics.notify(state, index); }
    try { await cancellation?.catch(() => {}); await owner?.close(); }
    finally { QueryClient.start = originalStart; await rm(root, { recursive: true, force: true }); }
  }
});
