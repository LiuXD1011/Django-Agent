import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { createServer } from 'node:http';
import { mkdtemp, mkdir, writeFile, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import test from 'node:test';
const req = (method: string, path: string, body?: object) => ({ protocol: 1 as const, id: randomUUID(), method, path, ...(body ? { body } : {}) });

test('fresh compiled owner private startup reads saved opt-in and keeps HTTP available on missing config', {
  skip: process.env.MARLIN_LOCAL_SERVICES_COMPILED_TEST !== '1', timeout: 30000,
}, async () => {
  assert.deepEqual(process.execArgv, []);
  const { CoreOwner } = await import('../dist/runtime/owner-client.js');
  const { createCoreHttpServer } = await import('../dist/adapters/http.js');
  const root = await mkdtemp(join(tmpdir(), 'marlin-local-compiled 中文 ')); let owner: any; let http: any;
  try {
    owner = await CoreOwner.start({ dataRoot: root, allowAutoSetup: true });
    assert.equal((await owner.startDevelopmentLocalServices({ sourceRoot: root })).state, 'disabled');
    assert.equal((await owner.invoke(req('POST', '/api/v1/auth/auto-setup', { password: 'compiled-local-synthetic-password' }))).status, 200);
    assert.equal((await owner.invoke(req('PUT', '/api/v1/system/config/local_services', { autostart: true }))).status, 200);
    await owner.close(); owner = await CoreOwner.start({ dataRoot: root });
    assert.equal((await owner.startDevelopmentLocalServices({ sourceRoot: root })).state, 'missing_server_configuration');
    http = createCoreHttpServer(await owner.httpTransport(), { port: 0 }); const { origin } = await http.listen();
    assert.equal((await fetch(origin + '/health')).status, 200);
  } finally { await http?.close(); await owner?.close(); await rm(root, { recursive: true, force: true }); }
});

test('fresh compiled dev process executes fixed CLI protocol and real loopback health before HTTP without tsx', {
  skip: process.env.MARLIN_LOCAL_SERVICES_COMPILED_TEST !== '1' || process.platform === 'win32', timeout: 30000,
}, async () => {
  assert.deepEqual(process.execArgv, []); const { CoreOwner } = await import('../dist/runtime/owner-client.js');
  const root = await mkdtemp(join(tmpdir(), 'marlin-local-compiled-dev 中文 ')), data = join(root, 'data'), source = join(root, 'source'), bin = join(root, 'bin'), record = join(root, 'calls');
  await mkdir(source); await mkdir(bin); await writeFile(join(source, '.env.langfuse'), '# synthetic'); await writeFile(join(source, 'docker-compose.langfuse.yml'), '# protocol fixture');
  await writeFile(join(bin, 'docker'), `#!${process.execPath}\nrequire(${JSON.stringify(resolve('test/fixtures/local-services-cli.cjs'))});\n`, { mode: 0o700 });
  const server = createServer((_req, res) => res.end('fixture')); await new Promise<void>(done => server.listen(0, '127.0.0.1', done));
  let owner: any, child: ReturnType<typeof spawn> | undefined, terminal: Promise<number | null> | undefined;
  try {
    owner = await CoreOwner.start({ dataRoot: data, allowAutoSetup: true });
    assert.equal((await owner.invoke(req('POST', '/api/v1/auth/auto-setup', { password: 'compiled-dev-synthetic-password' }))).status, 200);
    assert.equal((await owner.invoke(req('PUT', '/api/v1/system/config/local_services', { autostart: true, startup_timeout_seconds: 3 }))).status, 200); await owner.close(); owner = undefined;
    child = spawn(process.execPath, [resolve('dist/tools/dev-server.js'), '--data-root', data, '--source-root', source, '--port', '0'], { env: { PATH: bin, MARLIN_LOCAL_FIXTURE_RECORD: record, LANGFUSE_BASE_URL: `http://127.0.0.1:${(server.address() as any).port}` }, stdio: ['ignore', 'pipe', 'pipe'] });
    terminal = new Promise(done => child!.once('exit', done)); let output = '', errors = ''; child.stdout!.on('data', b => output += b); child.stderr!.on('data', b => errors += b);
    for (let i = 0; i < 1000 && !output.includes('listening at'); i++) { if (child.exitCode !== null) break; await delay(10); }
    const origin = /listening at (http:\/\/127.0.0.1:\d+)/.exec(output)?.[1]; assert.ok(origin, errors); assert.equal((await fetch(origin + '/health')).status, 200);
    const calls = (await readFile(record, 'utf8')).trim().split('\n').map(line => JSON.parse(line)); assert.equal(calls.length, 2);
    assert.deepEqual(calls.map(c => c.args.slice(-2)), [['config', '--quiet'], ['up', '-d']]);
    assert.equal(JSON.parse(await readFile(join(data, '.cache/langfuse/startup.json'), 'utf8')).state, 'healthy'); assert.equal(errors, '');
    child.kill('SIGTERM'); assert.equal(await terminal, 0); child = undefined;
  } finally {
    if (child && child.exitCode === null && child.signalCode === null) child.kill('SIGTERM'); await terminal; await owner?.close();
    server.closeAllConnections(); await new Promise<void>(done => server.close(() => done())); await rm(root, { recursive: true, force: true });
  }
});
