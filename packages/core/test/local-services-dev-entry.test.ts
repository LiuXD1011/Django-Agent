import assert from 'node:assert/strict';
import { spawn, fork, type ChildProcess } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { createServer } from 'node:http';
import { mkdtemp, mkdir, writeFile, readFile, rm, access } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import test from 'node:test';
import { CoreOwner } from '../src/runtime/owner-client.js';
const req = (method: any, path: string, body?: any) => ({ protocol: 1 as const, id: randomUUID(), method, path, ...(body ? { body } : {}) });
async function f() {
  const root = await mkdtemp(join(tmpdir(), 'marlin-dev-entry 中文 ')), source = join(root, 'source 中文'), data = join(root, 'data 中文'), bin = join(root, 'bin');
  await mkdir(source); await mkdir(bin); const record = join(root, 'calls.jsonl');
  // Synthetic files; neither Docker nor the real repository .env is read.
  await writeFile(join(source, '.env.langfuse'), '# synthetic'); await writeFile(join(source, 'docker-compose.langfuse.yml'), '# CLI fixture');
  await writeFile(join(bin, 'docker'), `#!${process.execPath}\nrequire(${JSON.stringify(resolve('test/fixtures/local-services-cli.cjs'))});\n`, { mode: 0o700 });
  const owner = await CoreOwner.start({ dataRoot: data, allowAutoSetup: true });
  try {
    assert.equal((await owner.invoke(req('POST', '/api/v1/auth/auto-setup', { password: 'dev-fixture-synthetic-password' }))).status, 200);
    assert.equal((await owner.invoke(req('PUT', '/api/v1/system/config/local_services', { autostart: true, startup_timeout_seconds: 3 }))).status, 200);
  } finally { await owner.close(); }
  const env = { PATH: bin, LANGFUSE_AUTOSTART: '', LANGFUSE_STARTUP_TIMEOUT_SECONDS: '', LANGFUSE_BASE_URL: '', LANGFUSE_HOST: '', MARLIN_LOCAL_FIXTURE_RECORD: record };
  const calls = async () => (await readFile(record, 'utf8').catch(() => '')).trim().split('\n').filter(Boolean).map(v => JSON.parse(v));
  return { root, source, data, record, env, calls };
}
function terminal(child: ChildProcess) { return new Promise<{ code: number | null; signal: string | null }>(done => child.once('exit', (code, signal) => done({ code, signal }))); }
async function launch(fixture: Awaited<ReturnType<typeof f>>, env: object = {}, port = 0) {
  const child = spawn(process.execPath, ['--import', 'tsx', resolve('src/tools/dev-server.ts'), '--data-root', fixture.data, '--source-root', fixture.source, '--port', String(port)], { env: { ...fixture.env, ...env }, stdio: ['ignore', 'pipe', 'pipe'] });
  const ended = terminal(child); let stdout = '', stderr = ''; child.stdout!.on('data', b => stdout += b); child.stderr!.on('data', b => stderr += b);
  return { child, ended, stdout: () => stdout, stderr: () => stderr, async close() { if (child.exitCode === null && child.signalCode === null) child.kill('SIGTERM'); return await ended; }, async ready() {
    for (let i = 0; i < 800; i++) { const match = /listening at (http:\/\/127.0.0.1:\d+)/.exec(stdout); if (match) return match[1]!; if (child.exitCode !== null) break; await delay(10); }
    assert.fail(`real dev entry did not listen: ${stderr}`);
  } };
}

test('real dev entry applies saved opt-in before HTTP; desktop stays zero CLI and env false overrides saved true', { skip: process.platform === 'win32', timeout: 60000 }, async () => {
  const fixture = await f(); const server = createServer((_req, res) => res.end('fixture healthy'));
  await new Promise<void>(done => server.listen(0, '127.0.0.1', done)); const base = `http://127.0.0.1:${(server.address() as any).port}`;
  let dev: Awaited<ReturnType<typeof launch>> | undefined; let desktop: ChildProcess | undefined;
  try {
    dev = await launch(fixture, { LANGFUSE_BASE_URL: base }); const origin = await dev.ready();
    assert.equal((await fetch(origin + '/health')).status, 200); assert.equal((await fixture.calls()).length, 2);
    assert.equal(JSON.parse(await readFile(join(fixture.data, '.cache/langfuse/startup.json'), 'utf8')).state, 'healthy');
    assert.ok(dev.stdout().includes('Langfuse local startup: healthy')); assert.equal(dev.stderr(), ''); assert.equal((await dev.close()).code, 0); dev = undefined;
    await rm(fixture.record); await rm(join(fixture.data, '.cache'), { recursive: true });
    dev = await launch(fixture, { LANGFUSE_AUTOSTART: 'false', LANGFUSE_BASE_URL: base }); assert.equal((await fetch((await dev.ready()) + '/health')).status, 200);
    assert.deepEqual(await fixture.calls(), []); await assert.rejects(access(join(fixture.data, '.cache'))); assert.equal((await dev.close()).code, 0); dev = undefined;
    desktop = fork(resolve('src/tools/desktop-process.ts'), ['--data-root', fixture.data], { execArgv: ['--import', 'tsx'], env: { ...fixture.env, LANGFUSE_AUTOSTART: 'true', LANGFUSE_BASE_URL: base }, stdio: ['ignore', 'pipe', 'pipe', 'ipc'] });
    const ended = terminal(desktop); await new Promise<void>((done, reject) => { desktop!.once('error', reject); desktop!.on('message', (message: any) => { if (message.type === 'ready') done(); }); desktop!.once('exit', () => reject(new Error('desktop failed ready'))); });
    desktop.send({ type: 'shutdown' }); assert.equal((await ended).code, 0); desktop = undefined;
    assert.deepEqual(await fixture.calls(), []); await assert.rejects(access(join(fixture.data, '.cache')));
  } finally { await dev?.close(); if (desktop) { const ended = terminal(desktop); desktop.kill(); await ended; } server.closeAllConnections(); await new Promise<void>(done => server.close(() => done())); await rm(fixture.root, { recursive: true, force: true }); }
});

test('actual dev nonfatal failures still listen with fixed state and no secret output', { skip: process.platform === 'win32', timeout: 60000 }, async () => {
  const fixture = await f(); let dev: Awaited<ReturnType<typeof launch>> | undefined;
  try {
    for (const [env, expected, count] of [
      [{ MARLIN_LOCAL_FIXTURE_MODE: 'fail-config', LANGFUSE_BASE_URL: 'http://127.0.0.1:9' }, 'compose_failed', 1],
      [{ PATH: join(fixture.root, 'absent'), LANGFUSE_BASE_URL: 'http://127.0.0.1:9' }, 'docker_unavailable', 0],
    ] as const) {
      dev = await launch(fixture, env); assert.equal((await fetch((await dev.ready()) + '/health')).status, 200);
      assert.equal(JSON.parse(await readFile(join(fixture.data, '.cache/langfuse/startup.json'), 'utf8')).state, expected);
      assert.equal((await fixture.calls()).length, count); assert.equal((dev.stdout() + dev.stderr()).includes('synthetic-private'), false);
      assert.equal((await dev.close()).code, 0); dev = undefined; await rm(fixture.record, { force: true });
    }
    await rm(join(fixture.source, '.env.langfuse')); dev = await launch(fixture); assert.equal((await fetch((await dev.ready()) + '/health')).status, 200);
    assert.equal(JSON.parse(await readFile(join(fixture.data, '.cache/langfuse/startup.json'), 'utf8')).state, 'missing_server_configuration'); assert.deepEqual(await fixture.calls(), []);
  } finally { await dev?.close(); await rm(fixture.root, { recursive: true, force: true }); }
});

test('SIGTERM during actual dev startup cancels owned CLI before HTTP listen and awaits terminal close', { skip: process.platform === 'win32', timeout: 30000 }, async () => {
  const fixture = await f(); const dev = await launch(fixture, { MARLIN_LOCAL_FIXTURE_MODE: 'hold-config', LANGFUSE_STARTUP_TIMEOUT_SECONDS: '10', LANGFUSE_BASE_URL: 'http://127.0.0.1:9' });
  try {
    for (let i = 0; i < 1000; i++) { try { await access(fixture.record + '.child'); break; } catch {} await delay(10); }
    await access(fixture.record + '.child'); const before = performance.now(); assert.equal((await dev.close()).code, 0); assert.ok(performance.now() - before < 5000);
    assert.equal(dev.stdout().includes('listening at'), false); assert.equal((await fixture.calls()).length, 1);
    assert.equal(JSON.parse(await readFile(join(fixture.data, '.cache/langfuse/startup.json'), 'utf8')).state, 'cancelled');
    for (const pid of [(await fixture.calls())[0].pid, Number(await readFile(fixture.record + '.child', 'utf8'))]) {
      let running = true; for (let i = 0; i < 200; i++) { try { process.kill(pid, 0); } catch { running = false; break; } await delay(10); } assert.equal(running, false);
    }
  } finally { await dev.close(); await rm(fixture.root, { recursive: true, force: true }); }
});


test('actual dev port failure keeps a nonzero exit and fixed safe diagnostic', { skip: process.platform === 'win32', timeout: 30000 }, async () => {
  const fixture = await f(); const server = createServer((_req, res) => res.end());
  await new Promise<void>(done => server.listen(0, '127.0.0.1', done));
  const dev = await launch(fixture, { LANGFUSE_AUTOSTART: 'false' }, (server.address() as any).port);
  try { assert.equal((await dev.ended).code, 1); assert.match(dev.stderr(), /TypeScript core startup failed/); assert.deepEqual(await fixture.calls(), []); }
  finally { await dev.close(); await new Promise<void>(done => server.close(() => done())); await rm(fixture.root, { recursive: true, force: true }); }
});
