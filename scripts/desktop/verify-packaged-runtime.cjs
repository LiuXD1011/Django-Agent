'use strict';
// WIN-ASAR-BOOTSTRAP-001: build-only Electron main; no renderer or installer verdict.
const assert = require('node:assert/strict');
// Hash physical resources; Runtime require below retains Electron's ASAR loader.
const fs = process.versions.electron ? require('original-fs') : require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { spawnSync } = require('node:child_process');
const { parseArgs } = require('node:util');
const { auditAsar, inventory } = require('./audit-asar.cjs');
const sha = file => createHash('sha256').update(fs.readFileSync(file)).digest('hex');

async function main() {
  assert.ok(process.versions.electron && process.type === 'browser' && !process.env.ELECTRON_RUN_AS_NODE,
    'Packaged gate requires official Electron main mode');
  assert.equal(process.platform, 'win32'); assert.equal(process.arch, 'x64');
  const { values } = parseArgs({ args: process.argv.slice(2), options: {
    app: { type: 'string' }, fixture: { type: 'string' }, report: { type: 'string' }
  }, strict: true });
  assert.ok(values.app && values.fixture && values.report, 'Explicit build app/owned fixture/report required');
  const appDirectory = path.resolve(values.app), fixture = path.resolve(values.fixture);
  assert.equal(fs.existsSync(fixture), false, 'Packaged gate fixture must be fresh');
  const metadata = JSON.parse(fs.readFileSync(path.join(appDirectory, 'package.json')));
  assert.equal(process.versions.electron, metadata.devDependencies.electron);
  assert.equal(path.resolve(process.execPath).toLowerCase(), path.resolve(appDirectory, 'node_modules/electron/dist/electron.exe').toLowerCase(),
    'Gate must use the prepared locked official Electron');
  const audit = auditAsar(appDirectory);
  const resources = path.join(appDirectory, metadata.build.directories.output, 'win-unpacked/resources');
  const archive = path.join(resources, 'app.asar'), root = path.join(resources, 'runtime');
  const relative = path.relative(appDirectory, fixture);
  assert.ok(relative === '..' || relative.startsWith('..' + path.sep) || path.isAbsolute(relative), 'Fixture must be outside application resources');
  fs.mkdirSync(fixture);
  fs.writeFileSync(path.join(fixture, '.owned'), 'marlin-packaged-runtime-gate-v1\n');
  const { app, BrowserWindow, webContents } = require('electron');
  const profile = path.join(fixture, 'profile'), data = path.join(fixture, 'data');
  fs.mkdirSync(profile); fs.mkdirSync(data);
  app.setPath('userData', profile); app.setPath('sessionData', profile);
  const noRenderer = () => {
    assert.equal(BrowserWindow.getAllWindows().length, 0);
    assert.equal(webContents.getAllWebContents().length, 0);
  };
  await app.whenReady(); noRenderer();
  const runtimeFile = path.join(archive, 'runtime.cjs');
  assert.equal(require.resolve(runtimeFile), runtimeFile, 'Runtime must resolve from actual ASAR');
  const { Runtime } = require(runtimeFile);
  const manifestFile = path.join(root, 'source-manifest.json');
  const manifest = JSON.parse(fs.readFileSync(manifestFile));
  const node = path.join(root, 'node/node.exe');
  const nodeProbe = spawnSync(node, ['--version'], { encoding: 'utf8', timeout: 10000, windowsHide: true });
  assert.equal(nodeProbe.status, 0); assert.equal(nodeProbe.signal, null);
  assert.equal(nodeProbe.stdout.trim(), 'v22.23.2');
  const failures = [], runtime = new Runtime(root, data, message => failures.push(message));
  let ready, capabilities, childPid;
  try {
    ready = await runtime.start(); childPid = runtime.child.pid;
    assert.equal(ready.protocol, 1); assert.equal(ready.runtime, 'typescript'); assert.equal(ready.http_listener, false);
    assert.ok(runtime.lifetime.job && runtime.lifetime.authorized);
    capabilities = await runtime.invoke({ protocol: 1, id: 'actual-asar-capabilities', method: 'GET', path: '/api/v1/capabilities' });
    assert.equal(capabilities.status, 200); assert.equal(capabilities.body.success, true);
    assert.equal(capabilities.body.data.core_language, 'typescript'); assert.equal(capabilities.body.data.setup_required, true);
  } finally { await runtime.stop(); }
  assert.equal(runtime.child.exitCode, 0); assert.equal(runtime.child.signalCode, null);
  assert.equal(runtime.lifetime.closed, true); assert.deepEqual(failures, []); noRenderer();
  // Count the real synthetic database after its owner closed it, using only product Node/native SQLite.
  const query = "const {pathToFileURL}=require('node:url');const path=require('node:path');" +
    "import(pathToFileURL(path.join(process.argv[1],'core/dist/storage/database.js')).href).then(({openNativeDatabase})=>{" +
    "const db=openNativeDatabase(process.argv[2],{readonly:true,fileMustExist:true});try{console.log(JSON.stringify({model_usage_rows:db.prepare('SELECT count(*) count FROM model_usage').get().count}));}finally{db.close();}}).catch(e=>{console.error(e.message);process.exitCode=1;});";
  const usage = spawnSync(node, ['-e', query, root, path.join(data, 'marlin.sqlite3')], { encoding: 'utf8', timeout: 15000, windowsHide: true });
  assert.equal(usage.status, 0, usage.stderr); assert.equal(usage.signal, null);
  const usageRows = JSON.parse(usage.stdout).model_usage_rows; assert.equal(usageRows, 0);
  assert.deepEqual(inventory(root), manifest.files, 'Actual runtime bytes changed during packaged gate');
  assert.equal(sha(archive), audit.asar_sha256); assert.equal(sha(manifestFile), audit.runtime_manifest_sha256);
  const report = { format: 'marlin-packaged-runtime-verification-v1', state: 'verified', scope: 'actual_asar',
    platform: process.platform, arch: process.arch, electron: process.versions.electron,
    electron_executable: process.execPath, electron_executable_sha256: sha(process.execPath),
    asar_path: archive, runtime_path: runtimeFile, payload_root: root,
    asar_sha256: audit.asar_sha256, runtime_sha256: audit.asset_sha256['runtime.cjs'],
    bootstrap_sha256: audit.physical_bootstrap_sha256, physical_bootstrap_matches_asar: true,
    native_addon_sha256: sha(path.join(root, 'owned-runtime/runtime-job.node')),
    core_entry_sha256: sha(path.join(root, 'core/dist/tools/desktop-process.js')),
    node_sha256: sha(node), node_version: nodeProbe.stdout.trim(),
    source_sha256: manifest.source_sha256, payload_manifest_sha256: sha(manifestFile),
    core_pid: childPid, ready, capabilities_status: capabilities.status, setup_required: true,
    owned_runtime_job_bound: true, owned_runtime_job_closed: true, core_exit_code: runtime.child.exitCode,
    core_signal: runtime.child.signalCode, model_usage_rows: usageRows, paid_model_calls: 0,
    renderer_count: 0, gui_verified: false, installer_executed: false };
  fs.writeFileSync(values.report, JSON.stringify(report, null, 2) + '\n');
  console.log('ACTUAL_ASAR_RUNTIME_VERIFIED');
  app.exit(0);
}
// The official Electron default app imports CJS, keeping require.main at its own loader.
if (require.main === module || process.defaultApp === true && process.type === 'browser' && process.versions.electron) main().catch(error => {
  console.error(`PACKAGED_RUNTIME_GATE_ERROR=${error.message}`);
  if (process.versions.electron && process.type === 'browser') require('electron').app.exit(1);
  else process.exitCode = 1;
});
module.exports = { main };
