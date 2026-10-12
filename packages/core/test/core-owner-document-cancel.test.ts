import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { Worker } from 'node:worker_threads';
import test from 'node:test';
import type { CoreRequest, HttpMethod, JsonObject } from '../src/contracts.js';
import { AttemptState, readAttemptControl } from '../src/jobs/attempt-control.js';
import { CoreOwner } from '../src/runtime/owner-client.js';
import { openNativeDatabase } from '../src/storage/database.js';

const request = (method: HttpMethod, path: string, body?: JsonObject): CoreRequest => ({ protocol: 1, id: randomUUID(), method, path, ...(body ? { body } : {}) });
const data = (response: { body: unknown }): any => (response.body as any).data;
for (const transport of ['ipc', 'http'] as const) test(`real ${transport} document publication cancellation CASes before owner message pump resumes and ACKs durable rollback`, { timeout: 45000 }, async () => {
  const root = await mkdtemp(join(tmpdir(), 'marlin-owner-real-cancel 中文 '));
  const python = spawnSync('python', ['-c', 'import sys;print(sys.executable)'], { encoding: 'utf8' }); assert.equal(python.status, 0);
  const authority = new SharedArrayBuffer(8), barrier = new SharedArrayBuffer(12), state = new Int32Array(barrier), generation = randomUUID();
  let owner: CoreOwner | undefined, shared: SharedArrayBuffer | undefined, cancellation: Promise<unknown> | undefined;
  try {
    const worker = new Worker(new URL('./fixtures/core-owner-document-cancel-worker.ts', import.meta.url), { workerData: { config: { dataRoot: root, parser: { pythonExecutable: python.stdout.trim(), workerPath: resolve('../../workers/document/worker.py'), timeoutMs: 10000 } }, authority, generation, barrier }, execArgv: [], stdout: true, stderr: true });
    worker.on('message', message => { if (message.type === 'fixture-attempt') shared = message.shared; });
    owner = await CoreOwner.connect(worker, { authority, generation });
    assert.equal((await owner.invoke(request('POST', '/api/v1/auth/auto-setup', { password: 'owner-cancel-fixture-password' }))).status, 200);
    const kb = data(await owner.invoke(request('POST', '/api/v1/knowledge-bases', { name: '真实取消', indexing_strategy: { keyword_enabled: true, vector_enabled: false, graph_enabled: false, wiki_enabled: false } })));
    const content = 'durablecancelword\n保留完整中文😀数据。\n'.repeat(40);
    const upload = await owner.invoke(request('POST', `/api/v1/knowledge-bases/${kb.id}/knowledge/file`), { upload: { name: '真实取消.txt', bytes: Buffer.from(content) } }); assert.equal(upload.status, 200);
    const docId = String(data(upload).knowledge.id);
    for (let i = 0; i < 300; i++) {
      const doc = data(await owner.invoke(request('GET', `/api/v1/knowledge/${docId}`)));
      if (doc.workflow_status === 'completed') break;
      if (doc.workflow_status === 'failed') assert.fail('First real publication failed');
      await new Promise<void>(resolveWait => setTimeout(resolveWait, 20));
    }
    const before = await owner.invoke(request('GET', `/api/v1/knowledge/${docId}`)); assert.equal(data(before).workflow_status, 'completed');
    const oldChunks = data(await owner.invoke(request('GET', `/api/v1/chunks/${docId}`)));
    const http = await owner.httpTransport();
    const login = transport === 'http' ? await http.dispatch(request('POST', '/api/v1/auth/login', { login: 'admin', password: 'owner-cancel-fixture-password' }), { transport: 'http' }) : undefined;
    if (login) assert.equal(login.response.status, 200);
    assert.equal((await owner.invoke(request('POST', '/api/v1/fixture/arm-document-publication'))).status, 200);
    const reparse = await owner.invoke(request('POST', `/api/v1/knowledge/${docId}/reparse`, { process_config: { generate_summary: false } })); assert.equal(reparse.status, 200);
    const waited = await Atomics.waitAsync(state, 0, 0, 15000).value; assert.notEqual(waited, 'timed-out', 'actual reparse must reach native INSERT before cancel');
    assert.ok(shared); assert.equal(readAttemptControl(shared).state, AttemptState.ACTIVE);
    let acknowledged = false;
    const cancelRequest = request('POST', `/api/v1/knowledge/${docId}/cancel-parse`);
    cancellation = (transport === 'ipc' ? owner.invoke(cancelRequest) : http.dispatch(cancelRequest, { transport: 'http', access: login!.authChange!.issue!.credentials.access }).then(result => result.response)).then(result => { acknowledged = true; return result; });
    for (let i = 0; i < 100 && readAttemptControl(shared).state === AttemptState.ACTIVE; i++) await new Promise<void>(resolveWait => setTimeout(resolveWait, 10));
    assert.equal(readAttemptControl(shared).state, AttemptState.CANCEL_REQUESTED, 'coordinator cancels without waiting for blocked owner');
    assert.equal(acknowledged, false, 'volatile CAS is not a durable cancellation ACK');
    Atomics.store(state, 1, 1); Atomics.notify(state, 1);
    const result = await cancellation as { status: number; body: unknown }; assert.equal(result.status, 200); assert.equal(data(result).status, 'cancelled');
    const after = data(await owner.invoke(request('GET', `/api/v1/knowledge/${docId}`))); assert.equal(after.workflow_status, 'cancelled'); assert.equal(after.metadata.content, data(before).metadata.content);
    const chunks = data(await owner.invoke(request('GET', `/api/v1/chunks/${docId}`))); assert.deepEqual(chunks.items, oldChunks.items); assert.equal(chunks.total, oldChunks.total);
    await owner.close();
    const sqlite = openNativeDatabase(join(root, 'marlin.sqlite3'), { readonly: true, fileMustExist: true });
    try {
      assert.equal((sqlite.prepare('SELECT status FROM desktop_jobs WHERE id=?').get(data(reparse).task_id) as { status: string }).status, 'cancelled');
      const indexed = oldChunks.items.filter((chunk: any) => chunk.is_enabled && ['text', 'image_ocr', 'image_caption', 'table_summary'].includes(chunk.chunk_type)).length;
      assert.equal((sqlite.prepare("SELECT count(*) AS n FROM chunks_fts WHERE chunks_fts MATCH 'durablecancelword'").get() as { n: number }).n, indexed);
      assert.equal((sqlite.prepare("SELECT count(*) AS n FROM knowledge_processing_spans WHERE knowledge_id=? AND status='running'").get(docId) as { n: number }).n, 0);
    } finally { sqlite.close(); }
  } finally { Atomics.store(state, 1, 1); Atomics.notify(state, 1); await cancellation?.catch(() => {}); await owner?.close(); await rm(root, { recursive: true, force: true }); }
});
