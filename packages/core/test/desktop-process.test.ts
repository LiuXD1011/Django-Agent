import assert from 'node:assert/strict';
import { fork, spawnSync, type ChildProcess } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { test } from 'node:test';
import type { CoreRequest, CoreResponse, HttpMethod, JsonObject } from '../src/contracts.js';

async function start(dataRoot: string, parser = false) {
  const python = parser ? spawnSync('python', ['-c', 'import sys;print(sys.executable)'], { encoding: 'utf8' }).stdout.trim() : '';
  // The evaluation helper is configured lazily: first window must not launch it.
  const args = ['--data-root', dataRoot, ...(parser ? ['--python', python, '--parser-worker', resolve('../../workers/document/worker.py'), '--ragas-worker', join(dataRoot, 'not-started-evaluation-worker.py')] : [])];
  const child = fork(resolve('src/tools/desktop-process.ts'), args, { execArgv: ['--import', 'tsx'], serialization: 'json', stdio: ['ignore', 'pipe', 'pipe', 'ipc'] });
  const pending = new Map<string, { resolve: (response: CoreResponse) => void; reject: (error: Error) => void }>();
  let output = '', stderr = ''; child.stdout!.on('data', bytes => { output += bytes; }); child.stderr!.on('data', bytes => { stderr += bytes; });
  const ready = await new Promise<JsonObject>((resolveReady, reject) => {
    const timer = setTimeout(() => reject(new Error('Desktop core did not publish its private ready handshake')), 15000);
    child.once('exit', () => { clearTimeout(timer); reject(new Error('Desktop TypeScript core must start without Django/HTTP')); });
    child.on('message', (message: any) => { if (message.type === 'ready') { clearTimeout(timer); resolveReady(message); } });
  }).catch(async error => { child.kill('SIGTERM'); await exited(child); throw error; });
  child.on('message', (message: any) => { if (message.type === 'response') { pending.get(message.id)?.resolve(message.response); pending.delete(message.id); } });
  child.on('exit', () => { for (const request of pending.values()) request.reject(new Error('Owned desktop core exited')); pending.clear(); });
  const request = (method: HttpMethod, path: string, body?: JsonObject, options?: JsonObject): Promise<CoreResponse> => {
    const input: CoreRequest = { protocol: 1, id: randomUUID(), method, path, ...(body ? { body } : {}) };
    return new Promise((resolveResponse, reject) => { pending.set(input.id, { resolve: resolveResponse, reject }); child.send({ type: 'invoke', id: input.id, request: input, ...(options ? { options } : {}) }, error => { if (error) { pending.delete(input.id); reject(error); } }); });
  };
  return { child, ready, request, stdout: () => output, stderr: () => stderr, async close() { if (child.exitCode !== null || child.signalCode !== null) return; child.send({ type: 'shutdown' }); await exited(child); assert.equal(child.exitCode, 0); } };
}
async function exited(child: ChildProcess) { if (child.exitCode !== null || child.signalCode !== null) return; await new Promise<void>((resolveExit, reject) => { const timer = setTimeout(() => { child.kill('SIGTERM'); reject(new Error('Owned core did not shut down')); }, 15000); child.once('exit', () => { clearTimeout(timer); resolveExit(); }); }); }

test('owned TypeScript desktop process initializes over private IPC and restores SQLite/private device state after real restart', async () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-desktop-process-')); let process;
  try {
    process = await start(root); assert.equal(process.ready.protocol, 1); assert.equal(process.ready.runtime, 'typescript'); assert.equal(process.ready.http_listener, false);
    const initial = await process.request('POST', '/api/v1/auth/auto-setup', { email: 'desktop-process@example.invalid', password: 'desktop-private-fixture-password' }); assert.equal(initial.status, 200);
    for (const key of ['credentials', 'token', 'refresh_token', 'password']) assert.equal(Object.hasOwn((initial.body as JsonObject).data!, key), false);
    const created = await process.request('POST', '/api/v1/knowledge-bases', { name: '原生进程 海盐' }); assert.equal(created.status, 200); const kbId = ((created.body as JsonObject).data as JsonObject).id;
    const identity = process.ready.service_id;
    await process.close(); assert.equal(process.stdout().includes('desktop-private-fixture-password') || process.stderr().includes('desktop-private-fixture-password'), false);
    process = await start(root); assert.equal(process.ready.service_id, identity);
    assert.equal((await process.request('GET', '/api/v1/auth/me')).status, 200);
    const loaded = await process.request('GET', `/api/v1/knowledge-bases/${kbId}`); assert.equal(((loaded.body as JsonObject).data as JsonObject).name, '原生进程 海盐');
    assert.equal((await process.request('POST', '/api/v1/auth/logout')).status, 200); assert.equal((await process.request('GET', '/api/v1/auth/me')).status, 401);
  } finally { await process?.close(); rmSync(root, { recursive: true, force: true }); }
});

test('private byte codec accepts the 64 MiB boundary and exact typed-array views without permissive base64 decoding', async () => {
  const { encodeDesktopBytes, decodeDesktopBytes, decodeDesktopInput, desktopByteLimit } = await import('../src/tools/desktop-wire.js');
  const hash = (bytes: Uint8Array) => createHash('sha256').update(bytes).digest('hex');
  for (const size of [0, 1, 2, 3, 257, desktopByteLimit]) {
    const source = new Uint8Array(size + 2); source.fill(167); source[0] = 4; source[source.length - 1] = 5;
    const view = source.subarray(1, size + 1), encoded = encodeDesktopBytes(view), decoded = decodeDesktopBytes(encoded);
    assert.equal(encoded.size_bytes, size); assert.equal(encoded.data.length, 4 * Math.ceil(size / 3));
    assert.equal(decoded.byteLength, size); assert.equal(hash(decoded), hash(view));
  }
  assert.throws(() => encodeDesktopBytes(new Uint8Array(desktopByteLimit + 1)), /超过限制/);
  for (const bytes of [
    { encoding: 'base64', size_bytes: -1, data: '' }, { encoding: 'base64', size_bytes: 0.5, data: '' },
    { encoding: 'base64', size_bytes: '1', data: 'Zg==' }, { encoding: 'base64', size_bytes: 1, data: 'Zh==' },
    { encoding: 'base64', size_bytes: 1, data: 'Zg==\n' }, { encoding: 'base64', size_bytes: 1, data: 'Zg-_' },
    { encoding: 'base64', size_bytes: 1, data: 'Zg==', source: '/private/source' },
  ]) assert.throws(() => decodeDesktopBytes(bytes));
  const request = { protocol: 1, id: randomUUID(), method: 'GET', path: '/api/v1/auth/me' };
  for (const input of [
    { type: 'invoke', id: request.id, request: { ...request, access: 'forged' } },
    { type: 'invoke', id: request.id, request, binding: { transport: 'ipc' } },
    { type: 'invoke', id: request.id, request, options: null },
    { type: 'ack', id: request.id, sequence: 0, source: '/private' },
    { type: 'shutdown', force: true }, { type: 'cancel', id: request.id, all: true },
  ]) assert.throws(() => decodeDesktopInput(input));
});

// Win Electron 44 / bundled Node 22: advanced V8 serialization rejected the first request.
test('JSON private wire round-trips exact managed source bytes and rejects noncanonical or privileged upload fields', async () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-desktop-json-bytes-')); let process;
  const bytes = Buffer.concat([Buffer.from('私有字节\u0000\r\n🙂', 'utf8'), Buffer.from(Array.from({ length: 256 }, (_, i) => i))]);
  const encoded = { encoding: 'base64', size_bytes: bytes.length, data: bytes.toString('base64') };
  try {
    process = await start(root, true);
    assert.equal((await process.request('POST', '/api/v1/auth/auto-setup', { password: 'private-json-wire-only-password' })).status, 200);
    const kb = await process.request('POST', '/api/v1/knowledge-bases', { name: 'JSON 字节边界' });
    const kbId = ((kb.body as JsonObject).data as JsonObject).id;
    const route = `/api/v1/knowledge-bases/${kbId}/knowledge/file`;
    const uploaded = await process.request('POST', route, {}, { upload: { name: '精确字节.md', bytes: encoded } });
    assert.equal(uploaded.status, 200, 'valid bounded base64 must reach the real protected upload adapter');
    const documentId = ((((uploaded.body as JsonObject).data as JsonObject).knowledge as JsonObject).id);
    const download = await process.request('GET', `/api/v1/knowledge/${documentId}/download`) as CoreResponse & { binary: JsonObject };
    assert.equal(download.status, 200); assert.deepEqual(download.binary.bytes, encoded);
    assert.deepEqual(Buffer.from((download.binary.bytes as JsonObject).data as string, 'base64'), bytes);
    for (const invalid of [
      { ...encoded, encoding: 'hex' }, { ...encoded, size_bytes: bytes.length + 1 },
      { ...encoded, data: encoded.data + '\n' }, { encoding: 'base64', size_bytes: 1, data: 'Zh==' },
      { encoding: 'base64', size_bytes: 64 * 1024 * 1024 + 1, data: '' },
      { ...encoded, path: '/etc/passwd' }, { 0: 65 },
    ]) {
      const result = await process.request('POST', route, {}, { upload: { name: 'reject.md', bytes: invalid } });
      assert.ok([400, 413].includes(result.status));
    }
    for (const options of [{ upload: { name: 'reject.md', bytes: encoded, source: '/etc/passwd' } }, { access: 'forged-private-access' }]) {
      assert.equal((await process.request('POST', route, {}, options)).status, 400);
    }
    const identity = process.ready.service_id;
    await process.close(); process = await start(root, true); assert.equal(process.ready.service_id, identity);
    const restored = await process.request('GET', `/api/v1/knowledge/${documentId}/download`) as CoreResponse & { binary: JsonObject };
    assert.deepEqual(restored.binary.bytes, encoded);
    assert.equal((process.stdout() + process.stderr()).includes('private-json-wire-only-password'), false);
  } finally { await process?.close(); rmSync(root, { recursive: true, force: true }); }
});
