'use strict';
const assert = require('node:assert/strict');
const { test } = require('node:test');

test('desktop IPC grants only registered top frames at the exact application origin', () => {
  let boundary;
  try { boundary = require('./ipc.cjs'); } catch {}
  assert.ok(boundary, 'formal Electron IPC must validate registered sender and top frame');
  const frame = { url: 'https://marlin.local/platform/settings' }, sender = { mainFrame: frame }, allowed = new Set([sender]);
  assert.doesNotThrow(() => boundary.assertSender({ sender, senderFrame: frame }, allowed, 'https://marlin.local'));
  for (const event of [{ sender: { mainFrame: frame }, senderFrame: frame }, { sender, senderFrame: null },
    { sender, senderFrame: { url: frame.url } }]) assert.throws(() => boundary.assertSender(event, allowed, 'https://marlin.local'));
  frame.url = 'https://evil.invalid/platform/settings'; assert.throws(() => boundary.assertSender({ sender, senderFrame: frame }, allowed, 'https://marlin.local'));
});

test('desktop boundary accepts bounded public DTOs and file bytes, rejects private authority and arbitrary file paths', () => {
  let boundary;
  try { boundary = require('./ipc.cjs'); } catch {}
  assert.ok(boundary);
  const request = { protocol: 1, id: 'chosen', method: 'POST', path: '/api/v1/knowledge-bases/kb/knowledge/file', body: { tag_id: 'tag' } };
  assert.doesNotThrow(() => boundary.validateInvocation(request, { tenantId: 'space', upload: { name: '中文 文件.md', bytes: new Uint8Array([1]) } }));
  for (const input of [{ ...request, auth: { userId: 'admin' } }, { ...request, path: '/etc/passwd' }, { ...request, path: 'https://evil.invalid/api/v1/auth/me' },
    { ...request, body: { invalid: undefined } }, { ...request, body: { value: 'x'.repeat(2 * 1024 * 1024) } }]) assert.throws(() => boundary.validateInvocation(input, {}));
  for (const options of [{ access: 'forged' }, { upload: { path: '/etc/passwd', name: 'owned.md' } }, { upload: { name: '../escape', bytes: new Uint8Array([1]) } }]) assert.throws(() => boundary.validateInvocation(request, options));
});

test('only registered application top frames can invoke the fixed Langfuse window capability', async () => {
  const handlers = new Map(), events = new Map(), observed = [];
  const frame = { url: 'https://marlin.local/platform/settings' }, sender = { id: 1, mainFrame: frame }, allowed = new Set([sender]);
  const fakeIpc = { handle: (name, fn) => handlers.set(name, fn), on: (name, fn) => events.set(name, fn) };
  const windows = { handle: async (input) => { observed.push(input); return { protocol: 1, id: input.id, status: 200, body: { success: true, data: { state: 'manual' } } }; }, invalidate: async () => {} };
  require('./ipc.cjs').installIpc(fakeIpc, {}, allowed, 'https://marlin.local', windows);
  assert.equal(typeof handlers.get('marlin:langfuse'), 'function', 'A fixed native capability must be bound');
  const command = handlers.get('marlin:langfuse'), input = { id: 'window-one', action: 'open' };
  const result = await command({ sender, senderFrame: frame }, input); assert.equal(result.body.data.state, 'manual'); assert.equal(observed.length, 1);
  await assert.rejects(command({ sender, senderFrame: { url: frame.url } }, input));
  await assert.rejects(command({ sender, senderFrame: frame }, { ...input, cookies: { secret: 'forged' } }));
  assert.equal(observed.length, 1);
});
