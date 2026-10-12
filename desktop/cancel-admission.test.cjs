'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const { installIpc } = require('./ipc.cjs');
const { Runtime } = require('./runtime.cjs');
const { randomUUID } = require('node:crypto');
const { spawnSync } = require('node:child_process');
const { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } = require('node:fs');
const { tmpdir } = require('node:os');
const path = require('node:path');

const request = (id, cancel = false) => ({ protocol: 1, id, method: cancel ? 'POST' : 'GET', path: cancel ? '/api/v1/knowledge/owned/cancel-parse?from=fixture' : '/api/v1/capabilities' });
test('Electron boundary reserves eight exact cancellation calls while its 64 ordinary calls are saturated', async () => {
  // A boundary unit test: transport completion is controlled, not a real job ACK.
  const handlers = new Map(), frame = { url: 'https://marlin.local/platform/knowledge-bases/owned' }, sender = { id: 1, mainFrame: frame };
  const releases = [], runtime = { invoke: input => new Promise(resolve => releases.push(() => resolve({ protocol: 1, id: input.id, status: 200, body: {} }))) };
  installIpc({ handle: (name, fn) => handlers.set(name, fn), on() {} }, runtime, new Set([sender]), 'https://marlin.local');
  const invoke = handlers.get('marlin:invoke'), event = { sender, senderFrame: frame }, pending = [];
  try {
    for (let i = 0; i < 64; i++) pending.push(invoke(event, request(`ordinary-${i}`)));
    await assert.rejects(invoke(event, request('ordinary-overflow')), /过多/);
    for (let i = 0; i < 8; i++) pending.push(invoke(event, request(`cancel-${i}`, true)));
    await assert.rejects(invoke(event, request('cancel-overflow', true)), /过多/);
    assert.equal(releases.length, 72);
    await assert.rejects(invoke(event, { ...request('forged', true), path: '/api/v1/knowledge/owned/reparse' }), /过多/);
  } finally { for (const release of releases) release(); await Promise.allSettled(pending); }
});

test('JSON fork runtime preserves bounded cancellation admission and keeps sent cancel slots until its reply', async () => {
  // Transport admission unit test; no fake success is counted as business proof.
  const runtime = new Runtime('/unused', '/unused'); runtime.child = { connected: true };
  runtime.send = async () => {};
  const pending = [];
  try {
    for (let i = 0; i < 64; i++) pending.push(runtime.invoke(request(`normal-${i}`)));
    await assert.rejects(runtime.invoke(request('normal-overflow')), /过多/);
    const abort = new AbortController();
    const cancel = runtime.invoke(request('cancel-aborted', true), {}, abort.signal); pending.push(cancel);
    abort.abort(); await assert.rejects(cancel, /取消/);
    assert.ok(runtime.requests.has('cancel-aborted'), 'sent cancellation still owns its slot until terminal reply');
    for (let i = 0; i < 7; i++) pending.push(runtime.invoke(request(`cancel-${i}`, true)));
    await assert.rejects(runtime.invoke(request('cancel-overflow', true)), /过多/);
    runtime.receive({ type: 'response', id: 'cancel-aborted', response: { protocol: 1, id: 'cancel-aborted', status: 200, body: {} } });
    assert.equal(runtime.requests.has('cancel-aborted'), false);
  } finally { runtime.failRequests(new Error('fixture cleanup')); await Promise.allSettled(pending); }
});

test('actual desktop fork retains all eight aborted cancellation slots until the blocked owner acknowledges durable cancellation', { timeout: 45000 }, async () => {
  const root = mkdtempSync(path.join(tmpdir(), 'marlin-fork-cancel 真实 '));
  const coreRoot = path.resolve(__dirname, '../packages/core'), barrierRoot = path.join(root, 'fixture-cancel-barrier');
  const python = spawnSync('python', ['-c', 'import sys;print(sys.executable)'], { encoding: 'utf8' });
  assert.equal(python.status, 0);
  writeFileSync(path.join(root, 'fixture-parser.json'), JSON.stringify({ pythonExecutable: python.stdout.trim(), workerPath: path.join(coreRoot, '../../workers/document/worker.py'), timeoutMs: 10000 }));
  const runtime = new Runtime(coreRoot, root, () => {}, {
    nodeExecutable: process.execPath, coreDirectory: coreRoot,
    entryPoint: path.join(coreRoot, 'test/fixtures/desktop-document-cancel-process.ts'),
    execArgv: ['--import', 'tsx'], parser: false,
  });
  // The trusted startup fixture uses this real Python parser rather than a
  // packaged Windows parser; transport and business handlers stay unchanged.
  const req = (method, route, body) => ({ protocol: 1, id: randomUUID(), method, path: route, ...(body ? { body } : {}) });
  const waitFor = async predicate => {
    const deadline = Date.now() + 10000;
    while (!predicate()) {
      if (Date.now() >= deadline) assert.fail('Actual fork barrier did not arrive');
      await new Promise(resolve => setTimeout(resolve, 5));
    }
  };
  const count = name => existsSync(path.join(barrierRoot, name)) ? Number(readFileSync(path.join(barrierRoot, name), 'utf8')) : 0;
  const pending = [];
  try {
    await runtime.start();
    assert.equal((await runtime.invoke(req('POST', '/api/v1/auth/auto-setup', { password: 'fork-cancel-only-password' }))).status, 200);
    const kb = await runtime.invoke(req('POST', '/api/v1/knowledge-bases', { name: 'fork真实取消', indexing_strategy: { keyword_enabled: true, vector_enabled: false, graph_enabled: false, wiki_enabled: false } }));
    assert.equal(kb.status, 200);
    const upload = await runtime.invoke(req('POST', `/api/v1/knowledge-bases/${kb.body.data.id}/knowledge/file`), { upload: { name: 'fork取消.txt', bytes: Buffer.from('forkcancelword\n完整中文😀资料。\n'.repeat(40)) } });
    assert.equal(upload.status, 200);
    const id = upload.body.data.knowledge.id;
    let old;
    const deadline = Date.now() + 10000;
    do {
      old = await runtime.invoke(req('GET', `/api/v1/knowledge/${id}`));
      if (old.body.data.workflow_status === 'failed') assert.fail('Initial actual publication failed');
      if (Date.now() >= deadline) assert.fail('Initial actual publication did not complete');
    } while (old.body.data.workflow_status !== 'completed');
    assert.equal((await runtime.invoke(req('POST', '/api/v1/fixture/arm-document-publication'))).status, 200);
    assert.equal((await runtime.invoke(req('POST', `/api/v1/knowledge/${id}/reparse`, { process_config: { generate_summary: false } }))).status, 200);
    await waitFor(() => existsSync(path.join(barrierRoot, 'publication-paused')));
    const controls = [], requests = [];
    for (let i = 0; i < 8; i++) {
      const controller = new AbortController(), input = req('POST', `/api/v1/knowledge/${id}/cancel-parse`);
      controls.push(controller); requests.push(input);
      const promise = runtime.invoke(input, {}, controller.signal); void promise.catch(() => {}); pending.push(promise);
    }
    await waitFor(() => count('controls-sent') === 8);
    for (const controller of controls) controller.abort();
    for (const promise of pending) await assert.rejects(promise, /取消/);
    await waitFor(() => count('aborts-consumed') === 8);
    // A real readonly round trip fences earlier child IPC response deliveries.
    assert.equal((await runtime.invoke(req('GET', '/api/v1/auth/me'))).status, 200);
    assert.equal(requests.filter(input => runtime.requests.has(input.id)).length, 8, 'caller abort must not free sent controls before real owner ACK');
    await assert.rejects(runtime.invoke(req('POST', `/api/v1/knowledge/${id}/cancel-parse`)), /过多/);
    const settled = requests.map(input => runtime.waitForRequest(input.id));
    writeFileSync(path.join(barrierRoot, 'publication-release'), '1');
    await Promise.all(settled);
    const after = await runtime.invoke(req('GET', `/api/v1/knowledge/${id}`));
    assert.equal(after.body.data.workflow_status, 'cancelled');
    assert.equal(after.body.data.metadata.content, old.body.data.metadata.content);
    assert.equal(requests.some(input => runtime.requests.has(input.id)), false);
    const repeat = await runtime.invoke(req('POST', `/api/v1/knowledge/${id}/cancel-parse`));
    assert.equal(repeat.status, 200); assert.equal(repeat.body.data.status, 'cancelled');
  } finally {
    if (existsSync(barrierRoot)) writeFileSync(path.join(barrierRoot, 'publication-release'), '1');
    await Promise.allSettled(pending); await runtime.stop(); rmSync(root, { recursive: true, force: true });
  }
});
