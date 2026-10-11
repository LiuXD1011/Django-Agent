'use strict';
const assert = require('node:assert/strict');
const { test } = require('node:test');
const { mkdtempSync, writeFileSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const path = require('node:path');

test('packaged HTTPS handler serves actual bundled SPA files and denies foreign initiators and unsafe paths', async () => {
  let module; try { module = require('./protocol.cjs'); } catch {}
  assert.ok(module, 'installed application requires packaged assets without Vite/HTTP server');
  const root = mkdtempSync(path.join(tmpdir(), 'marlin-protocol-'));
  writeFileSync(path.join(root, 'index.html'), '<main>真实静态资源</main>'); writeFileSync(path.join(root, 'bundle.js'), 'export const value=1');
  const handler = module.createProtocolHandler(root, null, 'https://marlin.local');
  try {
    const request = (pathname, options = {}) => ({ url: 'https://marlin.local' + pathname, method: 'GET', ...options });
    assert.match(await (await handler(request('/platform/settings'))).text(), /真实静态资源/);
    const asset = await handler(request('/bundle.js', { initiatorOrigin: 'https://marlin.local' })); assert.match(asset.headers.get('content-type'), /javascript/);
    assert.match(asset.headers.get('content-security-policy'), /script-src 'self'/);
    assert.equal((await handler(request('/bundle.js', { initiatorOrigin: 'https://evil.invalid' }))).status, 403);
    assert.equal((await handler(request('/bundle.js', { method: 'POST' }))).status, 405);
    assert.equal((await handler(request('/%2e%2e%2fsecret.txt'))).status, 400);
    assert.equal((await handler(request('/missing.png'))).status, 404);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('remote HTTPS images retain ordinary networking without forwarding private core requests', async () => {
  const { createProtocolHandler } = require('./protocol.cjs');
  let forwarded;
  const handler = createProtocolHandler('/unused', { invoke() { throw new Error('remote request must not enter core'); } },
    'https://marlin.local', async request => { forwarded = request; return new Response('image', { headers: { 'Content-Type': 'image/png' } }); });
  const request = { url: 'https://images.example.invalid/wiki.png', method: 'GET', initiatorOrigin: 'https://marlin.local' };
  const response = await handler(request);
  assert.equal(response.status, 200);
  assert.equal(await response.text(), 'image');
  assert.equal(forwarded, request);
  assert.equal((await handler({ url: 'https://marlin.local/api/v1/auth/me', method: 'GET', initiatorOrigin: 'https://evil.invalid' })).status, 403);
});
