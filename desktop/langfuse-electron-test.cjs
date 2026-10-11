'use strict';
// Run with Electron and explicit disposable paths. Never included in the installer.
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { app, BrowserWindow, session, ipcMain } = require('electron');
const { Runtime } = require('./runtime.cjs');
const { installIpc } = require('./ipc.cjs');
const { LangfuseWindows } = require('./langfuse.cjs');

const [testRoot, coreDirectory, nodeExecutable, reportPath] = process.argv.slice(2);
assert.ok(testRoot && coreDirectory && nodeExecutable && reportPath, 'Explicit disposable root/core/node/report required');
assert.ok(!fs.existsSync(testRoot), 'Electron fixture must not reuse any existing application data');
fs.mkdirSync(testRoot, { recursive: true }); app.setPath('userData', path.join(testRoot, 'chromium'));
app.on('window-all-closed', () => {});
let runtime, windows, primary, server;
const report = { format: 'marlin-langfuse-native-test-v1', state: 'failed', platform: process.platform, electron: process.versions.electron, node: process.versions.node, paid_model_calls: 0, real_external_deployment: false };
async function run() {
  await app.whenReady();
  let loginCalls = 0, projectCalls = 0, wrongProjectCalls = 0, observedBrowserCookie = false, hold = false, held, releaseHeld, heldPage, releasePage;
  const heldRequest = new Promise(resolve => { held = resolve; });
  const heldNavigation = new Promise(resolve => { heldPage = resolve; });
  server = http.createServer(async (req, res) => {
    if (req.url === '/app') { res.setHeader('content-type', 'text/html'); res.end('<!doctype html><title>Owned Langfuse IPC fixture</title><h1>Native IPC fixture</h1>'); return; }
    if (req.url?.startsWith('/project/other/')) { wrongProjectCalls++; res.end('wrong project'); return; }
    if (req.url?.startsWith('/project/one/')) {
      projectCalls++; observedBrowserCookie = /next-auth.session-token\.0=native-cookie-a/.test(String(req.headers.cookie)) && /next-auth.session-token\.1=native-cookie-b/.test(String(req.headers.cookie));
      if (req.url === '/project/one/traces/hold') { heldPage(); releasePage = () => res.end('<h1>Late page</h1>'); return; }
      res.setHeader('content-type', 'text/html'); res.end('<!doctype html><title>Local NextAuth project</title><h1>Owned project</h1>'); return;
    }
    res.setHeader('content-type', 'application/json');
    if (req.url === '/api/auth/csrf') {
      loginCalls++;
      if (hold) { held(); releaseHeld = () => { res.setHeader('set-cookie', 'next-auth.csrf-token=csrf; Path=/; HttpOnly'); res.end('{"csrfToken":"csrf"}'); }; return; }
      res.setHeader('set-cookie', 'next-auth.csrf-token=csrf; Path=/; HttpOnly'); res.end('{"csrfToken":"csrf"}');
    } else if (req.url === '/api/auth/callback/credentials') {
      loginCalls++; let form = ''; for await (const chunk of req) form += chunk;
      assert.equal(new URLSearchParams(form).get('password'), 'native-fixture-login-private');
      res.setHeader('set-cookie', ['next-auth.session-token.0=native-cookie-a; Path=/; HttpOnly', 'next-auth.session-token.1=native-cookie-b; Path=/; HttpOnly']); res.end('{}');
    } else if (req.url === '/api/auth/session') { loginCalls++; res.end('{"user":{"email":"native@local","organizations":[{"projects":[{"id":"one"}]}]}}'); }
    else { res.statusCode = 404; res.end('{}'); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  runtime = new Runtime(coreDirectory, path.join(testRoot, 'core-data'), () => {}, { nodeExecutable, coreDirectory, entryPoint: path.join(coreDirectory, 'dist/tools/desktop-process.js'), parser: false });
  await runtime.start();
  const invoke = (method, route, body) => runtime.invoke({ protocol: 1, id: randomUUID(), method, path: route, ...(body ? { body } : {}) });
  assert.equal((await invoke('POST', '/api/v1/auth/auto-setup', { email: 'native-owner@example.invalid', password: 'native-langfuse-device-password' })).status, 200);
  assert.equal((await invoke('PUT', '/api/v1/system/config/langfuse', { base_url: origin, ui_base_url: origin, ui_project_id: 'one' })).status, 200);
  assert.equal((await invoke('PUT', '/api/v1/system/config/local_services', { auto_login: true, login_email: 'native@local', password: 'native-fixture-login-private' })).status, 200);
  await session.defaultSession.cookies.set({ url: origin, name: 'unrelated-browser-cookie', value: 'preserved', path: '/' });
  primary = new BrowserWindow({ show: false, webPreferences: { preload: path.join(__dirname, 'preload.cjs'), sandbox: true, nodeIntegration: false, contextIsolation: true } });
  const allowed = new Set([primary.webContents]); windows = new LangfuseWindows({ BrowserWindow, session }, runtime);
  const ipc = installIpc(ipcMain, runtime, allowed, origin, windows);
  await primary.loadURL(origin + '/app');
  const command = input => primary.webContents.executeJavaScript(`window.marlinDesktop.langfuse(${JSON.stringify({ id: randomUUID(), ...input })})`);
  const rendererInvoke = (method, route, body) => primary.webContents.executeJavaScript(`window.marlinDesktop.invoke(${JSON.stringify({ protocol: 1, id: randomUUID(), method, path: route, ...(body ? { body } : {}) })})`);
  const result = await command({ action: 'open' }); assert.equal(result.status, 200); assert.equal(result.body.data.state, 'connected');
  assert.equal(loginCalls, 3); assert.equal(projectCalls, 1); assert.equal(observedBrowserCookie, true);
  assert.equal(JSON.stringify(result).includes('native-cookie') || JSON.stringify(result).includes('native-fixture-login-private') || JSON.stringify(result).includes('ticket'), false);
  const target = windows.current.window, ownedSession = windows.current.session;
  assert.notEqual(ownedSession, session.defaultSession); assert.equal(ownedSession.isPersistent(), false);
  const cookies = await ownedSession.cookies.get({ url: origin });
  assert.equal(cookies.length, 2); for (const cookie of cookies) { assert.equal(cookie.httpOnly, true); assert.equal(cookie.hostOnly, true); assert.equal(cookie.sameSite, 'lax'); assert.equal(cookie.path, '/'); }
  const preferences = target.webContents.getLastWebPreferences();
  assert.equal(preferences.nodeIntegration, false); assert.equal(preferences.sandbox, true); assert.equal(preferences.contextIsolation, true); assert.ok(!preferences.preload);
  const renderer = await target.webContents.executeJavaScript('({node:typeof process,require:typeof require,bridge:typeof window.marlinDesktop,cookie:document.cookie})');
  assert.deepEqual(renderer, { node: 'undefined', require: 'undefined', bridge: 'undefined', cookie: '' });
  const count = BrowserWindow.getAllWindows().length;
  await target.webContents.executeJavaScript(`window.open(${JSON.stringify(origin + '/project/one/traces')});true`);
  await new Promise(resolve => setTimeout(resolve, 100)); assert.equal(BrowserWindow.getAllWindows().length, count);
  await assert.rejects(target.loadURL(origin + '/project/other/traces')); assert.equal(wrongProjectCalls, 0);
  await assert.rejects(target.loadURL('file:///private')); assert.equal(wrongProjectCalls, 0);
  const manualConfig = await rendererInvoke('PUT', '/api/v1/system/config/local_services', { auto_login: false }); assert.equal(manualConfig.status, 200);
  assert.equal(target.isDestroyed(), true); assert.equal(windows.current, null);
  const manual = await command({ action: 'open' }); assert.equal(manual.body.data.state, 'manual'); assert.equal(manual.body.data.manual_reason, 'auto_login_disabled'); assert.equal(loginCalls, 3);
  await command({ action: 'clear' }); assert.equal(windows.current, null);
  assert.equal((await ownedSession.cookies.get({ url: origin })).length, 0);
  assert.equal((await session.defaultSession.cookies.get({ url: origin, name: 'unrelated-browser-cookie' }))[0].value, 'preserved');
  await invoke('PUT', '/api/v1/system/config/local_services', { auto_login: true }); hold = true;
  const requestId = randomUUID(), pending = command({ id: requestId, action: 'open' }); void pending.catch(() => {}); await heldRequest;
  await primary.webContents.executeJavaScript(`window.marlinDesktop.cancel(${JSON.stringify(requestId)})`);
  await assert.rejects(pending); releaseHeld?.();
  assert.equal(windows.current, null); assert.equal(BrowserWindow.getAllWindows().length, 1);
  hold = false;
  const navigationId = randomUUID(), navigation = command({ id: navigationId, action: 'open', traceUrl: origin + '/project/one/traces/hold' }); void navigation.catch(() => {});
  await heldNavigation; await primary.webContents.executeJavaScript(`window.marlinDesktop.cancel(${JSON.stringify(navigationId)})`);
  try { await Promise.race([assert.rejects(navigation), new Promise((_, reject) => setTimeout(() => reject(new Error('Public cancellation must end a real pending BrowserWindow navigation')), 1200))]); }
  finally { releasePage?.(); }
  assert.equal(windows.current, null); assert.equal(BrowserWindow.getAllWindows().length, 1);
  await command({ action: 'open' }); const beforeLogout = windows.current.window, logoutSession = windows.current.session;
  assert.equal((await rendererInvoke('POST', '/api/v1/auth/logout')).status, 200);
  assert.equal(beforeLogout.isDestroyed(), true); assert.equal(windows.current, null); assert.equal((await logoutSession.cookies.get({ url: origin })).length, 0);
  ipc.close(); await windows.close(); await runtime.stop(); assert.equal(runtime.child.exitCode, 0);
  primary.destroy(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
  Object.assign(report, { state: 'verified', real_nextauth_protocol: true, actual_private_child_json: true, renderer_cookie_secret_absent: true, isolated_memory_session: true, httponly_host_only_lax: true, sandbox_no_preload_node: true, foreign_project_requests: wrongProjectCalls, popups_denied: true, owned_cookie_clear: true, unrelated_browser_cookie_preserved: true, public_cancel_no_window: true, public_cancel_pending_navigation: true, public_logout_clears_window: true, public_configuration_change_clears_window: true, owned_core_exit_code: 0 });
}
run().catch(error => { report.error = error.message; process.exitCode = 1; }).finally(async () => {
  await windows?.close().catch(() => {}); await runtime?.stop().catch(() => {});
  if (primary && !primary.isDestroyed()) primary.destroy();
  server?.closeAllConnections();
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + '\n');
  app.exit(report.state === 'verified' ? 0 : 1);
});
