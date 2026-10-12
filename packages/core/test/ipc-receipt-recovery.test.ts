import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { access, mkdtemp, readFile, rm, unlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Worker } from 'node:worker_threads';
import test from 'node:test';
import { CoreApplication } from '../src/application.js';
import { CoreIpcAdapter } from '../src/adapters/ipc.js';
import { CoreOwner } from '../src/runtime/owner-client.js';
import type { CoreRequest, HttpMethod, JsonObject } from '../src/contracts.js';

const credentials = { email: 'receipt-qa@example.invalid', password: 'isolated-receipt-password' };
const request = (method: HttpMethod, path: string, body?: JsonObject): CoreRequest => ({ protocol: 1, id: randomUUID(), method, path, ...(body ? { body } : {}) });
const login = () => request('POST', '/api/v1/auth/login', credentials);
const me = () => request('GET', '/api/v1/auth/me');
const device = (response: { body: any }) => String(response.body.data.device.id);
const pending = (ipc: CoreIpcAdapter, input = login()) => ipc.invokeForOwner(input, {}, new AbortController().signal, { isCurrent: () => true });
async function initial(ipc: CoreIpcAdapter) {
  const result = await ipc.invoke(request('POST', '/api/v1/auth/auto-setup', credentials));
  assert.equal(result.status, 200);
  return device(result);
}
function journal(app: CoreApplication) { return app.database.get("SELECT value FROM desktop_meta WHERE key='ipc.receipts'"); }
function privateSession(app: CoreApplication): { access: string; refresh: string } {
  const row = app.database.get("SELECT value FROM desktop_meta WHERE key='ipc.session'")!;
  const value = app.vault.decrypt(JSON.parse(String(row.value))) as JsonObject;
  return JSON.parse(String(value.token));
}

// Goal P1: terminate the actual owner while its private response is still behind the delivery barrier.
test('forced owner termination before IPC delivery recovers the accepted device and revokes the undisclosed login', { timeout: 25000 }, async () => {
  const root = await mkdtemp(join(tmpdir(), 'marlin-receipt-crash 真实 '));
  const authority = new SharedArrayBuffer(8), barrier = new SharedArrayBuffer(12), replyBarrier = new SharedArrayBuffer(8), reply = new Int32Array(replyBarrier), generation = randomUUID();
  let owner: CoreOwner | undefined;
  let worker: Worker | undefined;
  try {
    worker = new Worker(new URL('./fixtures/core-owner-publication-worker.ts', import.meta.url), { workerData: { config: { dataRoot: root }, authority, generation, barrier, replyBarrier }, execArgv: [], stdout: true, stderr: true });
    owner = await CoreOwner.connect(worker, { authority, generation });
    const accepted = await owner.invoke(request('POST', '/api/v1/auth/auto-setup', credentials));
    assert.equal(accepted.status, 200);
    const acceptedDevice = device(accepted);
    await owner.startupLog('INFO', 'receipt.fixture_accepted');
    await owner.invoke(request('POST', '/api/v1/fixture/arm-auth-reply'));
    const unexposed = owner.invoke(login());
    const rejected = assert.rejects(unexposed, { code: 'owner_failed' });
    assert.notEqual(await Atomics.waitAsync(reply, 0, 0, 5000).value, 'timed-out');
    assert.equal(await worker.terminate(), 1);
    await rejected;
    await owner.close().catch(() => {}); owner = undefined;
    owner = await CoreOwner.start({ dataRoot: root });
    const restored = await owner.invoke(me());
    assert.equal(restored.status, 200);
    assert.equal(device(restored), acceptedDevice, 'crash recovery must not restore the unexposed provisional device');
    const devices = await owner.invoke(request('GET', '/api/v1/auth/devices'));
    assert.equal((devices.body as any).data.items.filter((row: any) => !row.is_revoked).length, 1);
  } finally {
    Atomics.store(reply, 1, 1); Atomics.notify(reply, 1);
    await owner?.close().catch(() => {}); await worker?.terminate();
    await rm(root, { recursive: true, force: true });
  }
});

test('two pending logins are encrypted together with the saved session and both recover to the accepted predecessor', async () => {
  const root = await mkdtemp(join(tmpdir(), 'marlin-receipt-chain 真实 '));
  let app = new CoreApplication(root, { allowAutoSetup: true });
  try {
    let ipc = new CoreIpcAdapter(app);
    const acceptedDevice = await initial(ipc);
    const a = await pending(ipc), b = await pending(ipc);
    assert.equal(a.response.status, 200); assert.equal(b.response.status, 200);
    assert.ok(a.commit && b.commit);
    const stored = journal(app);
    assert.ok(stored, 'unconfirmed receipts must survive process loss');
    assert.match(String(stored.value), /enc:v1:/);
    const rawSession = app.vault.decrypt(JSON.parse(String(app.database.get("SELECT value FROM desktop_meta WHERE key='ipc.session'")!.value))) as JsonObject;
    const session = JSON.parse(String(rawSession.token));
    assert.equal(String(stored.value).includes(session.access), false);
    assert.equal(String(stored.value).includes(session.refresh), false);
    await app.close(); app = new CoreApplication(root);
    ipc = new CoreIpcAdapter(app);
    assert.equal(device(await ipc.invoke(me())), acceptedDevice);
    assert.equal(app.database.get('SELECT COUNT(*) AS count FROM device_sessions WHERE revoked_at IS NULL')?.count, 1);
    assert.equal(journal(app), undefined);
  } finally { await app.close(); await rm(root, { recursive: true, force: true }); }
});

test('discarding an earlier provisional login durably rebases its later pending predecessor', async () => {
  const root = await mkdtemp(join(tmpdir(), 'marlin-receipt-rebase 真实 '));
  let app = new CoreApplication(root, { allowAutoSetup: true });
  try {
    let ipc = new CoreIpcAdapter(app); const acceptedDevice = await initial(ipc);
    const a = await pending(ipc), b = await pending(ipc);
    ipc.settleInvocation(a.commit!, false);
    assert.equal(device(await ipc.invoke(me())), device(b.response));
    await app.close(); app = new CoreApplication(root); ipc = new CoreIpcAdapter(app);
    assert.equal(device(await ipc.invoke(me())), acceptedDevice);
    assert.equal(app.database.get('SELECT COUNT(*) AS count FROM device_sessions WHERE revoked_at IS NULL')?.count, 1);
  } finally { await app.close(); await rm(root, { recursive: true, force: true }); }
});

test('a later accepted login remains accepted when an older pending receipt is recovered', async () => {
  const root = await mkdtemp(join(tmpdir(), 'marlin-receipt-accepted 真实 '));
  let app = new CoreApplication(root, { allowAutoSetup: true });
  try {
    let ipc = new CoreIpcAdapter(app); await initial(ipc);
    const a = await pending(ipc), b = await pending(ipc);
    ipc.settleInvocation(b.commit!, true);
    await app.close(); app = new CoreApplication(root); ipc = new CoreIpcAdapter(app);
    assert.equal(device(await ipc.invoke(me())), device(b.response));
    assert.equal(app.database.read('device_sessions', device(a.response))?.revoke_reason, 'auth_superseded');
    assert.equal(app.database.read('device_sessions', device(b.response))?.revoked_at, null);
    assert.equal(journal(app), undefined);
  } finally { await app.close(); await rm(root, { recursive: true, force: true }); }
});

test('corrupt receipt ciphertext stops recovery without changing accepted records or key material', async () => {
  const root = await mkdtemp(join(tmpdir(), 'marlin-receipt-corrupt 真实 '));
  const app = new CoreApplication(root, { allowAutoSetup: true });
  try {
    const ipc = new CoreIpcAdapter(app); await initial(ipc); await pending(ipc);
    const corrupted = JSON.stringify({ token: 'enc:v1:invalid-ciphertext' });
    app.database.run("INSERT INTO desktop_meta(key,value) VALUES('ipc.receipts',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", corrupted);
    const session = app.database.get("SELECT value FROM desktop_meta WHERE key='ipc.session'")!.value;
    const devices = app.database.all('SELECT * FROM device_sessions');
    const key = await readFile(app.vault.keyPath);
    assert.throws(() => new CoreIpcAdapter(app), { status: 503, code: 'ipc_receipts_unavailable' });
    assert.equal(journal(app)?.value, corrupted);
    assert.equal(app.database.get("SELECT value FROM desktop_meta WHERE key='ipc.session'")!.value, session);
    assert.deepEqual(app.database.all('SELECT * FROM device_sessions'), devices);
    assert.ok((await readFile(app.vault.keyPath)).equals(key));
  } finally { await app.close(); await rm(root, { recursive: true, force: true }); }
});

test('pending refresh chain recovery preserves the accepted stable device and its original refresh token', async () => {
  const root = await mkdtemp(join(tmpdir(), 'marlin-receipt-refresh 真实 '));
  let app = new CoreApplication(root, { allowAutoSetup: true });
  try {
    let ipc = new CoreIpcAdapter(app); const acceptedDevice = await initial(ipc);
    const accepted = privateSession(app);
    const acceptedRow = app.database.read('device_sessions', acceptedDevice);
    const a = await pending(ipc, request('POST', '/api/v1/auth/refresh'));
    const rejectedA = privateSession(app);
    const b = await pending(ipc, request('POST', '/api/v1/auth/refresh'));
    const rejectedB = privateSession(app);
    assert.equal(a.response.status, 200); assert.equal(b.response.status, 200);
    assert.equal(device(a.response), acceptedDevice); assert.equal(device(b.response), acceptedDevice);
    await app.close(); app = new CoreApplication(root); ipc = new CoreIpcAdapter(app);
    const restored = await ipc.invoke(me()); assert.equal(restored.status, 200);
    assert.equal(device(restored), acceptedDevice);
    assert.ok(privateSession(app).access === accepted.access);
    assert.ok(privateSession(app).refresh === accepted.refresh);
    assert.equal(app.database.read('device_sessions', acceptedDevice)?.revoked_at, null);
    assert.deepEqual(app.database.read('device_sessions', acceptedDevice), acceptedRow);
    assert.throws(() => app.auth.refresh(rejectedB.refresh), { code: 'invalid_refresh' });
    const valid = app.auth.refresh(accepted.refresh);
    assert.equal(valid.context.deviceId, acceptedDevice);
    assert.equal(journal(app), undefined);
    assert.ok(rejectedA.refresh !== valid.credentials.refresh);
  } finally { await app.close(); await rm(root, { recursive: true, force: true }); }
});

test('rejecting a refresh predecessor durably rebases the dependent refresh undo to the accepted generation', async () => {
  const root = await mkdtemp(join(tmpdir(), 'marlin-receipt-refresh-rebase 真实 '));
  let app = new CoreApplication(root, { allowAutoSetup: true });
  try {
    let ipc = new CoreIpcAdapter(app); const acceptedDevice = await initial(ipc), accepted = privateSession(app);
    const a = await pending(ipc, request('POST', '/api/v1/auth/refresh'));
    const b = await pending(ipc, request('POST', '/api/v1/auth/refresh'));
    assert.ok(a.commit && b.commit); ipc.settleInvocation(a.commit, false);
    await app.close(); app = new CoreApplication(root); ipc = new CoreIpcAdapter(app);
    const restored = await ipc.invoke(me()); assert.equal(restored.status, 200);
    assert.equal(device(restored), acceptedDevice);
    assert.ok(privateSession(app).access === accepted.access && privateSession(app).refresh === accepted.refresh);
    assert.equal(app.auth.refresh(accepted.refresh).context.deviceId, acceptedDevice);
  } finally { await app.close(); await rm(root, { recursive: true, force: true }); }
});

test('accepted refresh descendant wins over the older pending same-device generation during recovery', async () => {
  const root = await mkdtemp(join(tmpdir(), 'marlin-receipt-refresh-accepted 真实 '));
  let app = new CoreApplication(root, { allowAutoSetup: true });
  try {
    let ipc = new CoreIpcAdapter(app); const acceptedDevice = await initial(ipc);
    const a = await pending(ipc, request('POST', '/api/v1/auth/refresh'));
    const b = await pending(ipc, request('POST', '/api/v1/auth/refresh'));
    const accepted = privateSession(app);
    assert.ok(a.commit && b.commit); ipc.settleInvocation(b.commit, true);
    await app.close(); app = new CoreApplication(root); ipc = new CoreIpcAdapter(app);
    assert.equal((await ipc.invoke(me())).status, 200);
    assert.equal(app.database.read('device_sessions', acceptedDevice)?.revoked_at, null);
    assert.ok(privateSession(app).access === accepted.access && privateSession(app).refresh === accepted.refresh);
    assert.equal(app.auth.refresh(accepted.refresh).context.deviceId, acceptedDevice);
    assert.equal(journal(app), undefined);
  } finally { await app.close(); await rm(root, { recursive: true, force: true }); }
});

for (const reason of ['user_revoked', 'password_changed', 'logout_all'] as const) {
  test(`external ${reason} wins over a pending refresh recovery`, async () => {
    const root = await mkdtemp(join(tmpdir(), 'marlin-receipt-revoked 真实 '));
    let app = new CoreApplication(root, { allowAutoSetup: true });
    try {
      let ipc = new CoreIpcAdapter(app); const acceptedDevice = await initial(ipc);
      await pending(ipc, request('POST', '/api/v1/auth/refresh'));
      const ctx = app.auth.authenticateAccess(ipc.privateSessionAccess()!);
      if (reason === 'user_revoked') app.auth.revokeDevice(ctx, acceptedDevice);
      else if (reason === 'password_changed') app.auth.changePassword(ctx, credentials.password, 'changed-receipt-password');
      else app.auth.logoutAll(ctx);
      const row = app.database.read('device_sessions', acceptedDevice)!;
      await app.close(); app = new CoreApplication(root); ipc = new CoreIpcAdapter(app);
      assert.equal((await ipc.invoke(me())).status, 401);
      assert.equal(app.database.read('device_sessions', acceptedDevice)?.revoked_at, row.revoked_at);
      assert.equal(app.database.read('device_sessions', acceptedDevice)?.revoke_reason, reason);
      assert.equal(journal(app), undefined);
    } finally { await app.close(); await rm(root, { recursive: true, force: true }); }
  });
}

test('a receipt journal write fault cannot commit a replacement session separately', async () => {
  const root = await mkdtemp(join(tmpdir(), 'marlin-receipt-atomic 真实 '));
  const app = new CoreApplication(root, { allowAutoSetup: true });
  try {
    const ipc = new CoreIpcAdapter(app); const acceptedDevice = await initial(ipc);
    app.database.sqlite.exec("CREATE TRIGGER receipt_fault BEFORE INSERT ON desktop_meta WHEN NEW.key='ipc.receipts' BEGIN SELECT RAISE(ABORT,'receipt_write_fault'); END");
    const result = await pending(ipc);
    assert.equal(result.response.status, 500); assert.equal(result.commit, undefined);
    assert.equal(device(await ipc.invoke(me())), acceptedDevice);
    assert.equal(device(await new CoreIpcAdapter(app).invoke(me())), acceptedDevice);
    assert.equal(app.database.get('SELECT COUNT(*) AS count FROM device_sessions WHERE revoked_at IS NULL')?.count, 1);
    assert.equal(journal(app), undefined);
  } finally { await app.close(); await rm(root, { recursive: true, force: true }); }
});

test('a receipt removal fault rolls back device discard and keeps the pending receipt recoverable', async () => {
  const root = await mkdtemp(join(tmpdir(), 'marlin-receipt-settle-atomic 真实 '));
  const app = new CoreApplication(root, { allowAutoSetup: true });
  try {
    const ipc = new CoreIpcAdapter(app); const acceptedDevice = await initial(ipc);
    const result = await pending(ipc);
    app.database.sqlite.exec("CREATE TRIGGER receipt_delete_fault BEFORE DELETE ON desktop_meta WHEN OLD.key='ipc.receipts' BEGIN SELECT RAISE(ABORT,'receipt_delete_fault'); END");
    assert.throws(() => ipc.settleInvocation(result.commit!, false), /receipt_delete_fault/);
    assert.equal(app.database.read('device_sessions', device(result.response))?.revoked_at, null);
    assert.equal(device(await ipc.invoke(me())), device(result.response));
    assert.ok(journal(app));
    app.database.sqlite.exec('DROP TRIGGER receipt_delete_fault');
    ipc.settleInvocation(result.commit!, false);
    assert.equal(device(await ipc.invoke(me())), acceptedDevice);
    assert.equal(journal(app), undefined);
  } finally { await app.close(); await rm(root, { recursive: true, force: true }); }
});

test('missing encryption key stops receipt recovery and never creates replacement key material', async () => {
  const root = await mkdtemp(join(tmpdir(), 'marlin-receipt-key 真实 '));
  const app = new CoreApplication(root, { allowAutoSetup: true });
  try {
    const ipc = new CoreIpcAdapter(app); await initial(ipc); await pending(ipc);
    const saved = app.database.all("SELECT * FROM desktop_meta WHERE key IN ('ipc.session','ipc.receipts')");
    const devices = app.database.all('SELECT * FROM device_sessions');
    await unlink(app.vault.keyPath);
    assert.throws(() => new CoreIpcAdapter(app), { status: 503, code: 'ipc_credentials_unavailable' });
    assert.deepEqual(app.database.all("SELECT * FROM desktop_meta WHERE key IN ('ipc.session','ipc.receipts')"), saved);
    assert.deepEqual(app.database.all('SELECT * FROM device_sessions'), devices);
    await assert.rejects(access(app.vault.keyPath), { code: 'ENOENT' });
  } finally { await app.close(); await rm(root, { recursive: true, force: true }); }
});

test('confirmed IPC receipt survives an abrupt owner termination after confirmation processing', { timeout: 25000 }, async () => {
  const root = await mkdtemp(join(tmpdir(), 'marlin-receipt-confirmed-crash 真实 '));
  const authority = new SharedArrayBuffer(8), barrier = new SharedArrayBuffer(12), generation = randomUUID();
  let owner: CoreOwner | undefined, worker: Worker | undefined;
  try {
    worker = new Worker(new URL('./fixtures/core-owner-publication-worker.ts', import.meta.url), { workerData: { config: { dataRoot: root }, authority, generation, barrier }, execArgv: [], stdout: true, stderr: true });
    owner = await CoreOwner.connect(worker, { authority, generation });
    const accepted = await owner.invoke(request('POST', '/api/v1/auth/auto-setup', credentials));
    assert.equal(accepted.status, 200);
    await owner.startupLog('INFO', 'receipt.confirmed');
    assert.equal(await worker.terminate(), 1);
    await owner.close().catch(() => {}); owner = undefined;
    owner = await CoreOwner.start({ dataRoot: root });
    const restored = await owner.invoke(me());
    assert.equal(restored.status, 200); assert.equal(device(restored), device(accepted));
  } finally { await owner?.close().catch(() => {}); await worker?.terminate(); await rm(root, { recursive: true, force: true }); }
});

for (const corruption of ['late-invalid-entry', 'inconsistent-session', 'plaintext-envelope'] as const) {
  test(`receipt ${corruption} is rejected before any partial cleanup`, async () => {
    const root = await mkdtemp(join(tmpdir(), 'marlin-receipt-shape 真实 '));
    const app = new CoreApplication(root, { allowAutoSetup: true });
    try {
      const ipc = new CoreIpcAdapter(app); await initial(ipc); await pending(ipc); await pending(ipc);
      const stored = journal(app)!;
      const opened = app.vault.decrypt(JSON.parse(String(stored.value))) as JsonObject;
      const payload = JSON.parse(String(opened.token));
      if (corruption === 'late-invalid-entry') payload.pending[1].issue.context.userId = '';
      else if (corruption === 'inconsistent-session') payload.current.access = 'unmatched-private-session';
      const value = JSON.stringify(corruption === 'plaintext-envelope' ? { token: JSON.stringify(payload) } : app.vault.encrypt({ token: JSON.stringify(payload) }));
      app.database.run("UPDATE desktop_meta SET value=? WHERE key='ipc.receipts'", value);
      const before = app.database.all("SELECT * FROM desktop_meta WHERE key IN ('ipc.session','ipc.receipts')");
      const devices = app.database.all('SELECT * FROM device_sessions');
      const key = await readFile(app.vault.keyPath);
      assert.throws(() => new CoreIpcAdapter(app), { status: 503, code: 'ipc_receipts_unavailable' });
      assert.deepEqual(app.database.all("SELECT * FROM desktop_meta WHERE key IN ('ipc.session','ipc.receipts')"), before);
      assert.deepEqual(app.database.all('SELECT * FROM device_sessions'), devices);
      assert.ok((await readFile(app.vault.keyPath)).equals(key));
    } finally { await app.close(); await rm(root, { recursive: true, force: true }); }
  });
}

test('revoked membership prevents pending refresh recovery from reactivating its device', async () => {
  const root = await mkdtemp(join(tmpdir(), 'marlin-receipt-authority 真实 '));
  let app = new CoreApplication(root, { allowAutoSetup: true });
  try {
    let ipc = new CoreIpcAdapter(app); const acceptedDevice = await initial(ipc);
    await pending(ipc, request('POST', '/api/v1/auth/refresh'));
    const ctx = app.auth.authenticateAccess(ipc.privateSessionAccess()!);
    const member = app.database.get('SELECT id FROM tenant_members WHERE user_id=? AND tenant_id=?', ctx.userId, ctx.tenantId)!;
    app.database.update('tenant_members', String(member.id), { status: 'revoked' });
    await app.close(); app = new CoreApplication(root); ipc = new CoreIpcAdapter(app);
    assert.equal((await ipc.invoke(me())).status, 401);
    assert.equal(app.database.read('device_sessions', acceptedDevice)?.revoke_reason, 'auth_superseded');
    assert.equal(app.database.read('tenant_members', String(member.id))?.status, 'revoked');
    assert.equal(journal(app), undefined);
  } finally { await app.close(); await rm(root, { recursive: true, force: true }); }
});

test('refresh recovery does not resurrect an original accepted idle deadline that has elapsed', async () => {
  const root = await mkdtemp(join(tmpdir(), 'marlin-receipt-expiry 真实 '));
  let now = Date.now(), app = new CoreApplication(root, { allowAutoSetup: true, now: () => now });
  try {
    let ipc = new CoreIpcAdapter(app); const acceptedDevice = await initial(ipc);
    now += 29 * 86400000;
    assert.equal((await pending(ipc, request('POST', '/api/v1/auth/refresh'))).response.status, 200);
    now += 2 * 86400000;
    await app.close(); app = new CoreApplication(root, { now: () => now }); ipc = new CoreIpcAdapter(app);
    assert.equal((await ipc.invoke(me())).status, 401);
    assert.equal(app.database.read('device_sessions', acceptedDevice)?.revoke_reason, 'auth_superseded');
    assert.equal(journal(app), undefined);
  } finally { await app.close(); await rm(root, { recursive: true, force: true }); }
});
