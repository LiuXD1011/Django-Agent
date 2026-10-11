import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { test } from 'node:test';
import { CoreApplication } from '../src/application.js';
import { CoreIpcAdapter } from '../src/adapters/ipc.js';

async function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'marlin-native-langfuse-'));
  const app = new CoreApplication(root, { allowAutoSetup: true }), ipc = new CoreIpcAdapter(app);
  const invoke = (method: string, path: string, body?: object) => ipc.invoke({ protocol: 1, id: randomUUID(), method, path, ...(body ? { body } : {}) });
  await invoke('POST', '/api/v1/auth/auto-setup', { email: 'owner@example.invalid', password: 'native-langfuse-only-password' });
  const saved = app.vault.decrypt(JSON.parse(String(app.database.get("SELECT value FROM desktop_meta WHERE key='ipc.session'")!.value)));
  const owner = app.authorize({ transport: 'ipc', ...JSON.parse(saved.token as string) });
  let calls = 0, mismatch = false, project = 'project', changed: (() => void) | undefined;
  const server = createServer(async (req, res) => {
    calls++; res.setHeader('content-type', 'application/json');
    if (req.url === '/api/auth/csrf') { res.setHeader('set-cookie', 'next-auth.csrf-token=csrf-private; HttpOnly; Path=/'); res.end('{"csrfToken":"csrf"}'); }
    else if (req.url === '/api/auth/callback/credentials') {
      let body = ''; for await (const chunk of req) body += chunk;
      const form = new URLSearchParams(body); assert.equal(form.get('email'), 'fixture@local'); assert.equal(form.get('password'), 'fixture-login-private');
      assert.equal(form.get('csrfToken'), 'csrf'); assert.match(String(req.headers.cookie), /next-auth.csrf-token=csrf-private/);
      res.setHeader('set-cookie', ['next-auth.session-token.0=session-private-a; HttpOnly; Path=/', 'next-auth.session-token.1=session-private-b; HttpOnly; Path=/']); res.end('{}');
    } else if (req.url === '/api/auth/session') { changed?.(); res.end(JSON.stringify({ user: { email: mismatch ? 'wrong@local' : 'fixture@local', organizations: [{ projects: [{ id: project }] }] } })); }
    else { res.statusCode = 404; res.end('{}'); }
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${(server.address() as { port: number }).port}`;
  const configure = async (local = {}) => {
    await invoke('PUT', '/api/v1/system/config/langfuse', { base_url: url, ui_base_url: url, ui_project_id: 'project' });
    await invoke('PUT', '/api/v1/system/config/local_services', { auto_login: true, login_email: 'fixture@local', password: 'fixture-login-private', ...local });
  };
  const native = (action: string, extra = {}) => (ipc as any).nativeLangfuse({ id: randomUUID(), action, ...extra });
  return { app, ipc, invoke, owner, url, configure, native, calls: () => calls, mismatch: () => { mismatch = true; }, project: () => { project = 'other'; }, change: (fn: () => void) => { changed = fn; }, async close() { server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); await app.close(); rmSync(root, { recursive: true, force: true }); } };
}

test('native Langfuse uses real saved configuration, private NextAuth cookies and account/project verification without faking HTTP origin', async () => {
  const f = await fixture();
  try {
    assert.equal(typeof (f.ipc as any).nativeLangfuse, 'function', 'Native login needs a dedicated trusted adapter');
    const missing = await f.native('prepare'); assert.equal(missing.response.body.error.code, 'needs_configuration'); assert.equal(f.calls(), 0);
    await f.configure();
    const prepared = await f.native('prepare'); assert.equal(prepared.response.status, 200); assert.equal(prepared.plan.origin, f.url); assert.equal(prepared.plan.mode, 'automatic');
    assert.equal(JSON.stringify(prepared.response).includes('fixture-login-private'), false);
    const result = await f.native('session', { ticket: prepared.plan.ticket });
    assert.equal(result.response.status, 200); assert.equal(result.response.body.data.state, 'connected'); assert.equal(f.calls(), 3);
    assert.deepEqual(result.cookies.map((c: any) => c.name), ['next-auth.session-token.0', 'next-auth.session-token.1']);
    assert.equal(JSON.stringify(result.response).includes('session-private'), false); assert.equal(result.cookies[0].value, 'session-private-a');
    const reused = await f.native('session', { ticket: prepared.plan.ticket, existingCookies: Object.fromEntries(result.cookies.map((c: any) => [c.name, c.value])) });
    assert.equal(reused.response.body.data.state, 'reused'); assert.equal(f.calls(), 4);
    f.mismatch(); const denied = await f.native('session', { ticket: prepared.plan.ticket, existingCookies: { 'next-auth.session-token': 'other' } });
    assert.equal(denied.response.body.error.code, 'account_conflict'); assert.equal(denied.cookies, undefined);
    assert.equal((await f.invoke('POST', '/api/v1/observability/langfuse/session', {})).status, 501, 'HTTP route still requires its own trusted HTTP context');
  } finally { await f.close(); }
});

test('native Langfuse manual plans preserve disabled and missing credential fallback without protocol calls', async () => {
  const f = await fixture();
  try {
    assert.equal(typeof (f.ipc as any).nativeLangfuse, 'function');
    await f.configure({ auto_login: false }); let prepared = await f.native('prepare'); assert.equal(prepared.plan.mode, 'manual'); assert.equal(prepared.plan.reason, 'auto_login_disabled');
    await f.invoke('DELETE', '/api/v1/system/config/local_services', { field: 'password' });
    // Imported/incomplete saved settings may retain auto_login even without a password.
    const local = f.app.database.read('integration_configs', 'local_services')!;
    f.app.database.update('integration_configs', 'local_services', { parameters: f.app.vault.encrypt({ ...f.app.vault.decrypt(local.parameters!), auto_login: true }) });
    prepared = await f.native('prepare'); assert.equal(prepared.plan.mode, 'manual'); assert.equal(prepared.plan.reason, 'credentials_missing');
    assert.equal((await f.native('session', { ticket: prepared.plan.ticket })).response.body.data.state, 'manual'); assert.equal(f.calls(), 0);
    await f.configure(); await f.invoke('PUT', '/api/v1/system/config/langfuse', { ui_base_url: 'https://example.invalid', base_url: 'https://example.invalid' });
    prepared = await f.native('prepare'); assert.equal(prepared.plan.mode, 'manual'); assert.equal(prepared.plan.reason, 'local_host_required'); assert.equal(f.calls(), 0);
  } finally { await f.close(); }
});

test('native login ticket fences configuration, device revocation, foreign identities and forged authority before publishing cookies', async () => {
  const f = await fixture();
  try {
    assert.equal(typeof (f.ipc as any).nativeLangfuse, 'function'); await f.configure();
    let prepared = await f.native('prepare');
    await f.invoke('PUT', '/api/v1/system/config/langfuse', { ui_project_id: 'other' });
    assert.equal((await f.native('validate', { ticket: prepared.plan.ticket })).response.body.error.code, 'integration_configuration_changed');
    await f.configure(); prepared = await f.native('prepare');
    f.change(() => f.app.database.run('UPDATE device_sessions SET revoked_at=? WHERE id=?', new Date().toISOString(), f.owner.deviceId));
    const revoked = await f.native('session', { ticket: prepared.plan.ticket }); assert.equal(revoked.response.status, 401); assert.equal(revoked.cookies, undefined);
    assert.equal((await f.native('prepare', { origin: f.url, cookies: { secret: 'forged' } })).response.status, 400);
    assert.equal((await f.native('prepare', { access: 'forged' })).response.status, 400);
  } finally { await f.close(); }
});

test('native login rejects another authorized user’s ticket and a missing configured project', async () => {
  const f = await fixture();
  try {
    await f.configure(); const outside = f.app.auth.register({ username: 'outside', password: 'outside-native-password' });
    f.app.settings.updateIntegration(f.owner, 'local_services', { local_login_user_id: outside.context.userId });
    const prepared = await f.native('prepare');
    assert.equal((await f.invoke('POST', '/api/v1/auth/login', { username: 'outside', password: 'outside-native-password' })).status, 200);
    const denied = await f.native('validate', { ticket: prepared.plan.ticket }); assert.equal(denied.response.body.error.code, 'native_login_superseded'); assert.equal(f.calls(), 0);
    const own = await f.native('prepare'); f.project();
    const wrongProject = await f.native('session', { ticket: own.plan.ticket }); assert.equal(wrongProject.response.body.error.code, 'login_failed'); assert.equal(wrongProject.cookies, undefined);
  } finally { await f.close(); }
});

test('native login does not publish cookies after actual await-time configuration changes or cancellation', async () => {
  for (const mode of ['configuration', 'cancel']) {
    const f = await fixture(); const controller = new AbortController();
    try {
      await f.configure(); const prepared = await f.native('prepare');
      f.change(() => { if (mode === 'configuration') f.app.settings.updateIntegration(f.owner, 'langfuse', { ui_project_id: 'other' }); else controller.abort(); });
      const result = await f.ipc.nativeLangfuse({ id: randomUUID(), action: 'session', ticket: prepared.plan.ticket }, controller.signal);
      assert.equal(result.response.body.error.code, mode === 'configuration' ? 'integration_configuration_changed' : 'integration_cancelled'); assert.equal(result.cookies, undefined); assert.equal(f.calls(), 3);
    } finally { await f.close(); }
  }
});

test('a pre-cancelled native capability returns a safe explicit cancellation without a login call', async () => {
  const f = await fixture();
  try {
    const controller = new AbortController(); controller.abort(new Error('private cancellation reason'));
    const result = await f.ipc.nativeLangfuse({ id: randomUUID(), action: 'prepare' }, controller.signal);
    assert.equal(result.response.status, 499); assert.equal(result.response.body.error.code, 'integration_cancelled');
    assert.equal(JSON.stringify(result).includes('private cancellation reason'), false); assert.equal(f.calls(), 0);
  } finally { await f.close(); }
});
