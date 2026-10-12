import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Worker } from 'node:worker_threads';
import test from 'node:test';
import type { CoreRequest, HttpMethod, JsonObject } from '../src/contracts.js';
import { CoreOwner } from '../src/runtime/owner-client.js';

const request = (method: HttpMethod, path: string, body?: JsonObject): CoreRequest => ({ protocol: 1, id: randomUUID(), method, path, ...(body ? { body } : {}) });
const data = (response: { body: unknown }): any => (response.body as any).data;
async function deadline<T>(work: Promise<T>): Promise<T> {
  let timer: NodeJS.Timeout | undefined;
  try { return await Promise.race([work, new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error('Page read waited for the blocked writer')), 1200); })]); }
  finally { clearTimeout(timer); }
}
for (const rollback of [false, true]) test(`formal private HTTP and IPC page reads see complete WAL version while publication is blocked (${rollback ? 'rollback' : 'commit'})`, async () => {
  const root = await mkdtemp(join(tmpdir(), 'marlin-read-publication 真实 '));
  const authority = new SharedArrayBuffer(8), barrier = new SharedArrayBuffer(12), state = new Int32Array(barrier), generation = randomUUID();
  let owner: CoreOwner | undefined, publication: ReturnType<CoreOwner['invoke']> | undefined;
  try {
    const worker = new Worker(new URL('./fixtures/core-owner-publication-worker.ts', import.meta.url), { workerData: { config: { dataRoot: root }, authority, generation, barrier }, execArgv: [], stdout: true, stderr: true });
    owner = await CoreOwner.connect(worker, { authority, generation });
    assert.equal((await owner.invoke(request('POST', '/api/v1/auth/auto-setup', { password: 'publication-private-password' }))).status, 200);
    const seed = data(await owner.invoke(request('POST', '/api/v1/fixture/seed')));
    const http = await owner.httpTransport();
    const login = await http.dispatch(request('POST', '/api/v1/auth/login', { login: 'admin', password: 'publication-private-password' }), { transport: 'http' });
    assert.equal(login.response.status, 200);
    const binding = { transport: 'http' as const, access: login.authChange!.issue!.credentials.access };
    const path = `/api/v1/knowledge/${seed.docId}`, chunkPath = `/api/v1/chunks/${seed.docId}`;
    const before = await owner.invoke(request('GET', path)); assert.equal(before.status, 200); assert.equal(data(before).title, '旧完整版本');
    Atomics.store(state, 2, Number(rollback));
    publication = owner.invoke(request('POST', '/api/v1/fixture/publication', seed));
    const acquired = await Atomics.waitAsync(state, 0, 0, 5000).value;
    assert.notEqual(acquired, 'timed-out'); assert.equal(Atomics.load(state, 0), 1);
    const [ipcDoc, httpDoc, ipcChunks, httpChunks] = await deadline(Promise.all([
      owner.invoke(request('GET', path)), http.dispatch(request('GET', path), binding),
      owner.invoke(request('GET', chunkPath)), http.dispatch(request('GET', chunkPath), binding),
    ]));
    for (const result of [ipcDoc, httpDoc.response]) { assert.equal(result.status, 200); assert.equal(data(result).title, '旧完整版本'); assert.equal(data(result).metadata.content, '旧正文😀12345元'); }
    for (const result of [ipcChunks, httpChunks.response]) { assert.equal(result.status, 200); assert.equal(data(result).items[0].content, '旧分块😀12345元'); }
    Atomics.store(state, 1, 1); Atomics.notify(state, 1);
    assert.equal((await publication).status, rollback ? 409 : 200);
    const after = await owner.invoke(request('GET', path)), chunks = await owner.invoke(request('GET', chunkPath));
    assert.equal(data(after).title, rollback ? '旧完整版本' : '新完整版本');
    assert.equal(data(after).metadata.content, rollback ? '旧正文😀12345元' : '新正文😀67890元');
    assert.equal(data(chunks).items[0].content, rollback ? '旧分块😀12345元' : '新分块😀67890元');
  } finally {
    Atomics.store(state, 1, 1); Atomics.notify(state, 1);
    await publication?.catch(() => {}); await owner?.close(); await rm(root, { recursive: true, force: true });
  }
});
