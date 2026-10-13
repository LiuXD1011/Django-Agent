'use strict';
// Build-time probes only. No renderer API, provider calls or system services.
const assert = require('node:assert/strict');
const { createRequire } = require('node:module');
const { pathToFileURL } = require('node:url');
const path = require('node:path');
const fs = require('node:fs');
const { parseArgs } = require('node:util');
const { createHash } = require('node:crypto');

const nodeVersion = 'v22.23.2';
function probeOwnedRuntime(payload, expectedNodeVersion = nodeVersion) {
  assert.equal(process.version, expectedNodeVersion);
  assert.equal(process.platform, 'win32'); assert.equal(process.arch, 'x64');
  assert.ok(Number(process.versions.napi) >= 8);
  const file = path.join(path.resolve(payload), 'owned-runtime/runtime-job.node');
  assert.ok(fs.lstatSync(file).isFile() && !fs.lstatSync(file).isSymbolicLink());
  const native = require(file);
  assert.equal(typeof native.currentIdentity, 'function'); assert.equal(typeof native.bindRoot, 'function');
  const identity = native.currentIdentity();
  assert.equal(identity.pid, process.pid);
  assert.match(identity.createdAt, /^[1-9][0-9]{0,19}$/);
  assert.equal(path.resolve(identity.executable).toLowerCase(), path.resolve(process.execPath).toLowerCase());
  return { node_version: process.version, platform: process.platform, arch: process.arch, napi_version: process.versions.napi,
    addon_sha256: createHash('sha256').update(fs.readFileSync(file)).digest('hex'), identity, identity_verified: true, api_verified: true };
}
async function probeNative(coreDirectory, expectedPlatform = 'win32') {
  assert.equal(process.version, nodeVersion, 'Product Node version differs from the official pin');
  assert.equal(process.platform, expectedPlatform, 'Native probe must run on the target platform');
  assert.equal(process.arch, 'x64', 'Native probe must use x64 Node');
  const root = path.resolve(coreDirectory), requireCore = createRequire(path.join(root, 'package.json'));
  for (const name of ['better-sqlite3', 'sqlite-vec']) {
    const location = requireCore.resolve(name);
    assert.ok(location.startsWith(path.join(root, 'node_modules') + path.sep), 'Native module resolved outside staged core');
  }
  const { openNativeDatabase } = await import(pathToFileURL(path.join(root, 'dist/storage/database.js')).href);
  const vec = requireCore('sqlite-vec'), db = openNativeDatabase(':memory:');
  try {
    db.defaultSafeIntegers();
    vec.load(db);
    const id = (1n << 60n) + 321n;
    db.exec('CREATE VIRTUAL TABLE pack_fts USING fts5(content); CREATE VIRTUAL TABLE pack_vec USING vec0(embedding float[2])');
    db.prepare('INSERT INTO pack_fts(rowid,content) VALUES (?,?)').run(id, 'windows packaging verification');
    db.prepare('INSERT INTO pack_vec(rowid,embedding) VALUES (?,?)').run(id, new Float32Array([0.25, 0.75]));
    const fts = db.prepare("SELECT rowid FROM pack_fts WHERE pack_fts MATCH 'packaging'").get();
    const vector = db.prepare('SELECT rowid,distance FROM pack_vec WHERE embedding MATCH ? AND k=1').get(new Float32Array([0.25, 0.75]));
    assert.equal(fts.rowid, id); assert.equal(vector.rowid, id); assert.equal(vector.distance, 0);
    return { node_version: process.version, platform: process.platform, arch: process.arch,
      sqlite_version: db.prepare('SELECT sqlite_version() version').get().version,
      vector_version: db.prepare('SELECT vec_version() version').get().version,
      fts_id: fts.rowid.toString(), vector_id: vector.rowid.toString(), paid_model_calls: 0 };
  } finally { db.close(); }
}

async function probeIpc(appDirectory, dataRoot) {
  assert.ok(!fs.existsSync(dataRoot) || fs.lstatSync(dataRoot).isDirectory() &&
    !fs.lstatSync(dataRoot).isSymbolicLink() && fs.readdirSync(dataRoot).length === 0,
  'IPC verification requires an empty disposable data directory');
  const { Runtime } = require(path.join(path.resolve(appDirectory), 'runtime.cjs'));
  const runtime = new Runtime(path.join(path.resolve(appDirectory), 'payload'), path.resolve(dataRoot));
  let ready, capabilities;
  try {
    ready = await runtime.start();
    assert.equal(ready.runtime, 'typescript'); assert.equal(ready.http_listener, false);
    capabilities = await runtime.invoke({ protocol: 1, id: 'packaging-capabilities', method: 'GET', path: '/api/v1/capabilities' });
    assert.equal(capabilities.status, 200);
    assert.equal(capabilities.body.success, true);
    assert.equal(capabilities.body.data.core_language, 'typescript');
    assert.equal(capabilities.body.data.setup_required, true);
  } finally { await runtime.stop(); }
  assert.equal(runtime.child?.exitCode, 0, 'Staged core must close cleanly');
  assert.equal(runtime.child?.signalCode, null, 'Staged core must complete its shutdown handshake');
  const bound = !!runtime.lifetime?.job && runtime.lifetime.authorized === true && runtime.lifetime.closed === true;
  if (process.platform === 'win32') assert.equal(bound, true, 'IPC core must start authorized and stop its actual native Job');
  return { protocol: ready.protocol, runtime: ready.runtime, http_listener: ready.http_listener,
    capabilities_status: capabilities.status, setup_required: capabilities.body.data.setup_required,
    exit_code: runtime.child.exitCode, paid_model_calls: 0, owned_runtime_job_bound: bound };
}

async function main() {
  const { values } = parseArgs({ options: { app: { type: 'string' }, 'data-root': { type: 'string' }, report: { type: 'string' } }, strict: true });
  assert.ok(values.app && values['data-root'] && values.report, 'Explicit isolated app/data/report paths are required');
  const app = path.resolve(values.app), payload = path.join(app, 'payload'), dataRoot = path.resolve(values['data-root']);
  const relative = path.relative(payload, dataRoot);
  assert.ok(relative === '..' || relative.startsWith('..' + path.sep) || path.isAbsolute(relative), 'Verification data must be outside payload');
  for (const name of ['langfuse.cjs', 'owned-runtime.cjs', 'runtime-bootstrap.cjs']) {
    assert.ok(fs.statSync(path.join(app, name)).isFile(), `Required staged application helper missing: ${name}`);
  }
  for (const name of ['frontend/index.html', 'node/node.exe', 'node/LICENSE', 'python/python.exe', 'python/LICENSE.txt',
    'workers/document/worker.py', 'workers/evaluation/worker.py', 'core/dist/tools/desktop-process.js', 'owned-runtime/runtime-job.node']) {
    assert.ok(fs.statSync(path.join(payload, name)).isFile(), `Required staged asset missing: ${name}`);
  }
  const owned = probeOwnedRuntime(payload), native = await probeNative(path.join(payload, 'core')), ipc = await probeIpc(app, dataRoot);
  const report = { format: 'marlin-core-payload-verification-v1', state: 'verified', native, ipc, owned_runtime: owned,
    paid_model_calls: 0, gui_verified: false, installer_verified: false };
  fs.writeFileSync(values.report, JSON.stringify(report, null, 2) + '\n', 'utf8');
  console.log('CORE_PAYLOAD_VERIFIED');
}
if (require.main === module) main().catch(error => { console.error(`CORE_PAYLOAD_VERIFICATION_FAILED: ${error.message}`); process.exitCode = 1; });
module.exports = { probeNative, probeIpc, probeOwnedRuntime };
