import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { createCoreHttpServer } from '../src/adapters/http.js';
import { CoreOwner } from '../src/runtime/owner-client.js';

test('loopback health reports a real owner crash and cannot serve stale readonly data', async () => {
  const root = await mkdtemp(join(tmpdir(), 'marlin-owner-health '));
  let owner: CoreOwner | undefined, http: ReturnType<typeof createCoreHttpServer> | undefined;
  try {
    owner = await CoreOwner.start({ dataRoot: root });
    http = createCoreHttpServer(await owner.httpTransport(), { port: 0 });
    const { origin } = await http.listen();
    assert.equal((await fetch(origin + '/health')).status, 200);
    await owner.worker.terminate();
    assert.equal((await fetch(origin + '/health')).status, 503);
    assert.equal((await fetch(origin + '/api/v1/auth/me')).status, 503);
    await assert.rejects(owner.close(), { code: 'owner_failed' });
  } finally { await http?.close(); await owner?.close().catch(() => {}); await rm(root, { recursive: true, force: true }); }
});
