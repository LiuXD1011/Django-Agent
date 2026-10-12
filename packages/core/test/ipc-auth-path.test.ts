import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { CoreApplication } from '../src/application.js';
import { CoreIpcAdapter } from '../src/adapters/ipc.js';
import type { CoreRequest, JsonObject } from '../src/contracts.js';

const request = (path: string, body?: JsonObject): CoreRequest => ({ protocol: 1, id: randomUUID(), method: 'POST', path, ...(body ? { body } : {}) });

test('a later query-bearing logout defeats a query-bearing login and revokes its undisclosed issued device', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'marlin-ipc-auth-path '));
  const app = new CoreApplication(directory, { allowAutoSetup: true });
  try {
    const ipc = new CoreIpcAdapter(app);
    const credentials = { email: 'ipc-path-qa@example.invalid', password: 'isolated-query-path-password' };
    assert.equal((await ipc.invoke(request('/api/v1/auth/auto-setup', credentials))).status, 200);
    const login = ipc.invoke(request('/api/v1/auth/login?intent=earlier', credentials));
    const logout = ipc.invoke(request('/api/v1/auth/logout?intent=later'));
    const [earlier, later] = await Promise.all([login, logout]);
    assert.equal(earlier.status, 409, 'a normalized auth path must participate in the same epoch fence');
    assert.equal(later.status, 200);
    assert.equal((await ipc.invoke({ protocol: 1, id: randomUUID(), method: 'GET', path: '/api/v1/auth/me' })).status, 401);
    assert.equal(app.database.get('SELECT COUNT(*) AS count FROM device_sessions WHERE revoked_at IS NULL')?.count, 0,
      'discarding an earlier response must also revoke the device that would otherwise be undisclosed');
    assert.equal(app.database.get("SELECT value FROM desktop_meta WHERE key='ipc.session'"), undefined);
  } finally {
    await app.close();
    await rm(directory, { recursive: true, force: true });
  }
});

for (const boundary of ['issued-before-save', 'saved-before-reply'] as const) {
  test(`a trusted newer authority epoch at ${boundary} revokes a superseded issue and preserves the previous private session`, async () => {
    const directory = await mkdtemp(join(tmpdir(), 'marlin-ipc-auth-save '));
    const app = new CoreApplication(directory, { allowAutoSetup: true });
    try {
      const ipc = new CoreIpcAdapter(app);
      const credentials = { email: 'ipc-save-qa@example.invalid', password: 'isolated-save-window-password' };
      const initial = await ipc.invoke(request('/api/v1/auth/auto-setup', credentials));
      assert.equal(initial.status, 200);
      const deviceId = (initial.body as any).data.device.id;
      const epochs = new BigUint64Array(new SharedArrayBuffer(8));
      Atomics.store(epochs, 0, 1n);
      const fence = { isCurrent: () => Atomics.load(epochs, 0) === 1n };
      if (boundary === 'issued-before-save') {
        const dispatch = app.dispatch.bind(app);
        app.dispatch = async (...args) => {
          const result = await dispatch(...args);
          if (args[0].path === '/api/v1/auth/login') Atomics.store(epochs, 0, 2n);
          return result;
        };
      } else {
        const run = app.database.run.bind(app.database);
        app.database.run = (...args) => {
          const result = run(...args);
          if (args[0].startsWith('INSERT INTO desktop_meta') && args[1] === 'ipc.session') Atomics.store(epochs, 0, 2n);
          return result;
        };
      }
      const result = await ipc.invoke(request('/api/v1/auth/login', credentials), {}, undefined, fence);
      assert.equal(result.status, 409, 'a newer trusted intent must defeat an earlier auth result at either save boundary');
      const current = await ipc.invoke({ protocol: 1, id: randomUUID(), method: 'GET', path: '/api/v1/auth/me' });
      assert.equal(current.status, 200);
      assert.equal((current.body as any).data.device.id, deviceId);
      assert.equal(app.database.get('SELECT COUNT(*) AS count FROM device_sessions WHERE revoked_at IS NULL')?.count, 1);
      const restored = new CoreIpcAdapter(app);
      const persisted = await restored.invoke({ protocol: 1, id: randomUUID(), method: 'GET', path: '/api/v1/auth/me' });
      assert.equal((persisted.body as any).data.device.id, deviceId);
    } finally {
      await app.close();
      await rm(directory, { recursive: true, force: true });
    }
  });
}
