import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { mkdtemp, mkdir, writeFile, readFile, rm, access } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import test from 'node:test';
const loaded = await import('../src/integrations/local-services.js');
const cli = resolve('test/fixtures/local-services-cli.cjs');
async function fixture(snapshot: object = { autostart: true, timeoutSeconds: 3 }, env: NodeJS.ProcessEnv = {}) {
  assert.equal(typeof loaded?.LocalServicesStartupService, 'function', 'development startup service must exist');
  const root = await mkdtemp(join(tmpdir(), 'marlin-local 中文 空格 ')), source = join(root, 'source 中文'), data = join(root, 'data 中文');
  await mkdir(source); await writeFile(join(source, '.env.langfuse'), '# synthetic configuration only\n');
  await writeFile(join(source, 'docker-compose.langfuse.yml'), '# CLI protocol fixture, not real compose\n');
  const record = join(root, 'calls.jsonl');
  const service = new loaded!.LocalServicesStartupService(data, () => snapshot, { executable: { file: process.execPath, args: [cli] } });
  const environ = { PATH: '', MARLIN_LOCAL_FIXTURE_RECORD: record, ...env };
  return { root, source, data, record, service, environ, start: (signal?: AbortSignal) => service.start({ sourceRoot: source, environ, signal }),
    calls: async () => (await readFile(record, 'utf8').catch(() => '')).trim().split('\n').filter(Boolean).map(line => JSON.parse(line)),
    async close() { await service.close(); await rm(root, { recursive: true, force: true }); },
  };
}
async function health(status = 200, hold = false) {
  assert.equal(typeof loaded?.LocalServicesStartupService, 'function', 'development startup service must exist');
  const seen: string[] = [];
  const server = createServer((req, res) => { seen.push(req.url!); if (!hold) { res.writeHead(status); res.end('fixture'); } });
  await new Promise<void>(done => server.listen(0, '127.0.0.1', done));
  const url = `http://127.0.0.1:${(server.address() as any).port}`;
  return { url, seen, async close() { server.closeAllConnections(); await new Promise<void>(done => server.close(() => done())); } };
}
async function waitFor(path: string) { for (let i = 0; i < 400; i++) { try { await access(path); return; } catch {} await delay(10); } throw new Error('fixture did not publish readiness'); }
function gone(pid: number) { try { process.kill(pid, 0); return false; } catch { return true; } }

test('default off and explicit environment false have no cache or commands', async () => {
  for (const [snapshot, env] of [[{}, {}], [{ autostart: true }, { LANGFUSE_AUTOSTART: ' false ' }]] as const) {
    const f = await fixture(snapshot, env);
    try { assert.equal((await f.start()).state, 'disabled'); assert.deepEqual(await f.calls(), []); await assert.rejects(access(join(f.data, '.cache'))); } finally { await f.close(); }
  }
});
test('external API selection ignores local UI and performs no side effects', async () => {
  const f = await fixture({ autostart: true, baseUrl: 'https://external.invalid', uiBaseUrl: 'http://localhost:3000' });
  try { assert.equal((await f.start()).state, 'external'); assert.deepEqual(await f.calls(), []); await assert.rejects(access(join(f.data, '.cache'))); } finally { await f.close(); }
});
test('BASE_URL then saved API then HOST select direct health with fixed argv and cwd', async () => {
  const h = await health();
  try { for (const [snapshot, env] of [
    [{ autostart: true, timeoutSeconds: 3, baseUrl: 'https://external.invalid' }, { LANGFUSE_BASE_URL: h.url + '/prefix/', LANGFUSE_UI_BASE_URL: 'https://ui.invalid', HTTP_PROXY: 'http://127.0.0.1:9' }],
    [{ autostart: true, timeoutSeconds: 3, baseUrl: h.url }, { LANGFUSE_HOST: 'https://external.invalid' }],
    [{ autostart: true, timeoutSeconds: 3 }, { LANGFUSE_HOST: h.url, LANGFUSE_AUTOSTART: ' YeS ' }],
  ] as const) {
    const f = await fixture(snapshot, env);
    try {
      assert.equal((await f.start()).state, 'healthy');
      assert.deepEqual((await f.calls()).map(c => c.args), [
        ['compose', '--env-file', join(f.source, '.env.langfuse'), '-f', join(f.source, 'docker-compose.langfuse.yml'), 'config', '--quiet'],
        ['compose', '--env-file', join(f.source, '.env.langfuse'), '-f', join(f.source, 'docker-compose.langfuse.yml'), 'up', '-d'],
      ]); assert.ok((await f.calls()).every(c => c.cwd === f.source));
      const state = JSON.parse(await readFile(join(f.data, '.cache/langfuse/startup.json'), 'utf8'));
      assert.equal(state.state, 'healthy'); assert.equal(typeof state.checked_at, 'number'); assert.deepEqual(Object.keys(state).sort(), ['checked_at', 'state']);
      await assert.rejects(access(join(f.source, '.cache')));
    } finally { await f.close(); }
  } assert.ok(h.seen.includes('/prefix/api/public/health')); } finally { await h.close(); }
});
test('timeout parser preserves floating values, finite default and 1–120 clamp', () => {
  assert.equal(typeof loaded?.resolveLocalServicesConfiguration, 'function');
  for (const [value, expected] of [['0', 1], ['0.5', 1], ['1.25', 1.25], ['999', 120], ['no', 45], ['Infinity', 45], ['NaN', 45], [' ', 45], ['0x10', 45], ['1e1', 10], ['-.5', 1]]) {
    assert.equal(loaded!.resolveLocalServicesConfiguration({}, { LANGFUSE_STARTUP_TIMEOUT_SECONDS: value }).timeoutSeconds, expected);
  }
  assert.equal(loaded!.resolveLocalServicesConfiguration({ timeoutSeconds: 2.5 }, {}).timeoutSeconds, 2.5);
});
test('missing synthetic config and executable are fixed nonfatal states without commands', async () => {
  const f = await fixture();
  try { await rm(join(f.source, '.env.langfuse')); assert.equal((await f.start()).state, 'missing_server_configuration'); assert.deepEqual(await f.calls(), []); } finally { await f.close(); }
  const root = await mkdtemp(join(tmpdir(), 'marlin-no-cli ')); await writeFile(join(root, '.env.langfuse'), '# synthetic');
  const service = new loaded!.LocalServicesStartupService(join(root, 'data'), () => ({ autostart: true }));
  try { assert.equal((await service.start({ sourceRoot: root, environ: { PATH: join(root, 'absent') } })).state, 'docker_unavailable'); } finally { await service.close(); await rm(root, { recursive: true, force: true }); }
});
test('config failure never runs up and never writes stderr secrets', async () => {
  const f = await fixture(undefined, { MARLIN_LOCAL_FIXTURE_MODE: 'fail-config' });
  try { assert.equal((await f.start()).state, 'compose_failed'); assert.equal((await f.calls()).length, 1); assert.equal((await readFile(join(f.data, '.cache/langfuse/startup.json'), 'utf8')).includes('synthetic-private'), false); } finally { await f.close(); }
});
test('config consumes the single budget and prevents up; owned tree is cleaned', async () => {
  const f = await fixture({ autostart: true, timeoutSeconds: 1 }, { MARLIN_LOCAL_FIXTURE_MODE: 'hold-config' });
  try {
    const begin = performance.now(); assert.equal((await f.start()).state, 'startup_timeout'); assert.ok(performance.now() - begin < 4000);
    const calls = await f.calls(); assert.equal(calls.length, 1); assert.equal(gone(calls[0].pid), true);
    const pid = Number(await readFile(f.record + '.child', 'utf8')); for (let i = 0; i < 100 && !gone(pid); i++) await delay(10); assert.equal(gone(pid), true);
  } finally { await f.close(); }
});
test('health rejects redirect and 503 within the remaining total budget', async () => {
  for (const status of [302, 503]) {
    const h = await health(status), f = await fixture({ autostart: true, timeoutSeconds: 1.4, baseUrl: h.url });
    try { assert.equal((await f.start()).state, 'startup_timeout'); assert.ok(h.seen.length > 0); } finally { await f.close(); await h.close(); }
  }
});
test('pending health request and close are cancelled promptly', async () => {
  const h = await health(200, true), f = await fixture({ autostart: true, timeoutSeconds: 10, baseUrl: h.url });
  try {
    const pending = f.start(); for (let i = 0; i < 400 && !h.seen.length; i++) await delay(10); assert.ok(h.seen.length);
    const begin = performance.now(); await f.service.close(); assert.equal((await pending).state, 'cancelled'); assert.ok(performance.now() - begin < 2000);
  } finally { await f.close(); await h.close(); }
});
test('caller abort and close wait for only the owned CLI tree', async () => {
  const f = await fixture({ autostart: true, timeoutSeconds: 10 }, { MARLIN_LOCAL_FIXTURE_MODE: 'hold-config' }); const controller = new AbortController();
  const bystander = spawn(process.execPath, ['-e', 'setInterval(() => {},1000)'], { stdio: 'ignore' }); const terminal = new Promise<void>(done => bystander.once('exit', () => done()));
  try {
    const pending = f.start(controller.signal); await waitFor(f.record + '.child'); controller.abort(); await f.service.close(); assert.equal((await pending).state, 'cancelled');
    const calls = await f.calls(); assert.equal(gone(calls[0].pid), true); assert.equal(gone(bystander.pid!), false);
  } finally { bystander.kill(); await terminal; await f.close(); }
});
// This unchanged test is the native Windows gate too: real SQLite OS locks and
// controlled Node CLI children, never a mock lock or Docker executable.
test('two actual Node processes share lock budget, release and crash recovery', { timeout: 30000 }, async () => {
  const h = await health(), f = await fixture({ autostart: true, timeoutSeconds: 3, baseUrl: h.url });
  const holder = (mode: string, timeout: number) => {
    const child = spawn(process.execPath, ['--import', 'tsx', resolve('test/fixtures/local-services-process.ts'), f.data, f.source, f.record, mode, String(timeout), h.url], { stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = '', stderr = ''; child.stdout!.on('data', b => stdout += b); child.stderr!.on('data', b => stderr += b);
    const ended = new Promise<{ code: number | null; stdout: string; stderr: string }>(done => child.once('exit', code => done({ code, stdout, stderr }))); return { child, ended };
  }; let first: ReturnType<typeof holder> | undefined;
  try {
    first = holder('hold-lock', 10); await waitFor(f.record + '.locked');
    const blocked = await holder('start', 1).ended; assert.equal(blocked.code, 0, blocked.stderr); assert.equal(JSON.parse(blocked.stdout).state, 'startup_timeout'); assert.deepEqual(await f.calls(), []);
    first.child.kill(); await first.ended; first = undefined;
    const recovered = await holder('start', 3).ended; assert.equal(recovered.code, 0, recovered.stderr); assert.equal(JSON.parse(recovered.stdout).state, 'healthy'); assert.equal((await f.calls()).length, 2);
    await rm(f.record + '.locked'); first = holder('release-lock', 10); await waitFor(f.record + '.locked');
    const following = await holder('start', 3).ended; assert.equal(following.code, 0, following.stderr); assert.equal(JSON.parse(following.stdout).state, 'healthy'); assert.equal((await first.ended).code, 0); first = undefined;
  } finally { if (first) { first.child.kill(); await first.ended; } await f.close(); await h.close(); }
});

test('a directory is not server configuration and must never invoke compose', async () => {
  const f = await fixture();
  try { await rm(join(f.source, '.env.langfuse')); await mkdir(join(f.source, '.env.langfuse')); assert.equal((await f.start()).state, 'missing_server_configuration'); assert.deepEqual(await f.calls(), []); }
  finally { await f.close(); }
});

test('a lock waiter records fixed timeout without issuing a command', async () => {
  const f = await fixture({ autostart: true, timeoutSeconds: 1 });
  const { openNativeDatabase } = await import('../src/storage/database.js');
  await mkdir(join(f.data, '.cache/langfuse'), { recursive: true });
  const lock = openNativeDatabase(join(f.data, '.cache/langfuse/startup-lock.sqlite3'), { timeout: 0 }); lock.exec('BEGIN IMMEDIATE');
  try { assert.equal((await f.start()).state, 'startup_timeout'); assert.deepEqual(await f.calls(), []); assert.equal(JSON.parse(await readFile(join(f.data, '.cache/langfuse/startup.json'), 'utf8')).state, 'startup_timeout'); }
  finally { lock.exec('ROLLBACK'); lock.close(); await f.close(); }
});

test('compose protocol ignores large CLI output and retains only a fixed healthy state', async () => {
  const h = await health(), f = await fixture({ autostart: true, timeoutSeconds: 3, baseUrl: h.url }, { MARLIN_LOCAL_FIXTURE_MODE: 'noisy' });
  try { assert.equal((await f.start()).state, 'healthy'); assert.equal((await f.calls()).length, 2); assert.equal((await readFile(join(f.data, '.cache/langfuse/startup.json'), 'utf8')).includes('synthetic-private'), false); }
  finally { await f.close(); await h.close(); }
});

test('lock grant keeps the original deadline rather than granting compose a fresh budget', async () => {
  const h = await health(), f = await fixture({ autostart: true, timeoutSeconds: 1, baseUrl: h.url });
  const { openNativeDatabase } = await import('../src/storage/database.js');
  await mkdir(join(f.data, '.cache/langfuse'), { recursive: true });
  const lock = openNativeDatabase(join(f.data, '.cache/langfuse/startup-lock.sqlite3'), { timeout: 0 }); lock.exec('BEGIN IMMEDIATE');
  const release = setTimeout(() => lock.exec('ROLLBACK'), 850);
  try {
    const begin = performance.now(); assert.equal((await f.start()).state, 'startup_timeout'); assert.ok(performance.now() - begin < 4000);
    assert.ok((await f.calls()).every(call => call.args.includes('config')), 'elapsed lock budget must prevent up');
  } finally { clearTimeout(release); if (lock.inTransaction) lock.exec('ROLLBACK'); lock.close(); await f.close(); await h.close(); }
});
