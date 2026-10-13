import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { CoreOwner } from '../src/runtime/owner-client.js';
import { createCoreHttpServer } from '../src/adapters/http.js';
const request = (method: any, path: string, body?: any) => ({ protocol: 1 as const, id: randomUUID(), method, path, ...(body ? { body } : {}) });

test('trusted owner applies saved administrator opt-in after restart; ordinary HTTP/IPC cannot start services', async () => {
  const root = await mkdtemp(join(tmpdir(), 'marlin-local-owner 中文 ')); let owner: CoreOwner | undefined;
  let http: ReturnType<typeof createCoreHttpServer> | undefined;
  try {
    owner = await CoreOwner.start({ dataRoot: root, allowAutoSetup: true });
    assert.equal(typeof (owner as any).startDevelopmentLocalServices, 'function', 'trusted development owner method must exist');
    assert.equal((await (owner as any).startDevelopmentLocalServices({ sourceRoot: root })).state, 'disabled');
    assert.equal((await owner.invoke(request('POST', '/api/v1/auth/auto-setup', { password: 'local-owner-synthetic-password' }))).status, 200);
    assert.equal((await owner.invoke(request('PUT', '/api/v1/system/config/local_services', { autostart: true, startup_timeout_seconds: 1 }))).status, 200);
    await owner.close(); owner = await CoreOwner.start({ dataRoot: root });
    assert.equal((await (owner as any).startDevelopmentLocalServices({ sourceRoot: root })).state, 'missing_server_configuration');
    assert.equal(JSON.parse(await readFile(join(root, '.cache/langfuse/startup.json'), 'utf8')).state, 'missing_server_configuration');
    assert.equal((await owner.invoke(request('POST', '/api/v1/development-local-services', { sourceRoot: root, operation: 'development-local-services' }))).status, 404);
    assert.equal((await owner.invoke({ operation: 'development-local-services', sourceRoot: root })).status, 400);
    http = createCoreHttpServer(await owner.httpTransport(), { port: 0 }); const { origin } = await http.listen();
    assert.equal((await fetch(origin + '/health')).status, 200);
    assert.equal((await fetch(origin + '/api/v1/development-local-services', { method: 'GET' })).status, 404);
    await assert.rejects((owner as any).startDevelopmentLocalServices({ sourceRoot: root, argv: ['down'] }), { code: 'invalid_owner_call' });
    const malformedId = randomUUID();
    const rejected = new Promise<any>(done => {
      const receive = (message: any) => { if (message.id === malformedId) { owner!.worker.removeListener('message', receive); done(message); } };
      owner!.worker.on('message', receive);
    });
    owner.worker.postMessage({ protocol: 1, type: 'call', id: malformedId, epoch: '0', call: { operation: 'development-local-services', sourceRoot: root, argv: ['down'] } });
    assert.equal((await rejected).error.code, 'invalid_owner_call');
    assert.equal((await owner.invoke(request('POST', '/api/v1/auth/register', { email: 'local-nonadmin@example.invalid', password: 'local-nonadmin-synthetic-password' }))).status, 200);
    assert.equal((await owner.invoke(request('PUT', '/api/v1/system/config/local_services', { autostart: false }))).status, 403);
  } finally { await http?.close(); await owner?.close(); await rm(root, { recursive: true, force: true }); }
});
