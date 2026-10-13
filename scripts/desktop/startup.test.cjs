'use strict';
const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { spawn, spawnSync } = require('node:child_process');
const { createHash } = require('node:crypto');
const root = path.resolve(__dirname, '../..');
const launcherFile = path.join(__dirname, 'start-desktop.cjs');
const launcher = fs.existsSync(launcherFile) ? require(launcherFile) : {};
function implementation() { assert.equal(typeof launcher.main, 'function', 'A strict Node desktop launcher must replace the Django launcher'); return launcher; }
const appFiles = ['main.cjs', 'runtime.cjs', 'owned-runtime.cjs', 'runtime-bootstrap.cjs', 'ipc.cjs', 'preload.cjs', 'protocol.cjs', 'langfuse.cjs', 'loading.html', 'package.json', 'LICENSE', 'icon.png'];
const sha = file => createHash('sha256').update(fs.readFileSync(file)).digest('hex');
function put(file, content = 'fixture') { fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, content); }
function sourceSnapshot() {
  const files = {};
  const visit = directory => { for (const name of fs.readdirSync(path.join(root, directory), { withFileTypes: true })) {
    const relative = directory + '/' + name.name;
    if (name.isDirectory()) visit(relative);
    else if (!relative.split('/').some(part => ['.env', '.secrets', '.settings', '.git', 'credentials', 'secrets', '__pycache__'].includes(part) || part.startsWith('.env.')) && !/\.(?:sqlite|sqlite3|db|key|p12|pfx|secret|log|pyc)$/i.test(relative)) files[relative] = sha(path.join(root, relative));
  } };
  for (const folder of ['frontend/src', 'frontend/public', 'packages/core/src', 'packages/core/test', 'workers/document', 'workers/evaluation', 'scripts/desktop', 'desktop/native/runtime-job']) visit(folder);
  for (const name of ['LICENSE', 'scripts/build_windows.py', 'scripts/bundle_windows_native.py', 'scripts/test_build_windows.py', 'desktop/runtime.test.cjs', 'desktop/runtime-shutdown.test.cjs', 'desktop/runtime-bootstrap.test.cjs', 'desktop/runtime-quit.test.cjs', 'desktop/packaged-bootstrap.test.cjs', 'desktop/langfuse-electron-test.cjs', ...appFiles.filter(name => !['LICENSE', 'icon.png'].includes(name)).map(name => 'desktop/' + name), 'desktop/package-lock.json', 'frontend/package.json', 'frontend/package-lock.json', 'frontend/index.html', 'frontend/vite.config.ts', 'packages/core/package.json', 'packages/core/package-lock.json', 'packages/core/tsconfig.json', 'packages/core/scripts/prepare-native.mjs']) files[name] = sha(path.join(root, name));
  return files;
}
function fixture(entry = "process.stdout.write(JSON.stringify({argv:process.argv.slice(2),env:process.env})+'\\n');process.exitCode=7;") {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'marlin-launcher-'));
  const work = path.join(directory, '中文 空格 build'), app = path.join(work, 'app'), payload = path.join(app, 'payload'), data = path.join(directory, '隔离 数据');
  put(path.join(work, '.marlin-build'), 'marlin-electron-build-v1\n');
  for (const name of appFiles) put(path.join(app, name));
  fs.copyFileSync(path.join(root, 'desktop/runtime-bootstrap.cjs'), path.join(app, 'runtime-bootstrap.cjs'));
  put(path.join(payload, 'owned-runtime/runtime-bootstrap.cjs'), fs.readFileSync(path.join(app, 'runtime-bootstrap.cjs')));
  const metadata = JSON.parse(fs.readFileSync(path.join(root, 'desktop/package.json'), 'utf8'));
  put(path.join(app, 'package.json'), JSON.stringify(metadata));
  put(path.join(app, 'package-lock.json'), '{}'); put(path.join(app, 'main.cjs'), entry);
  put(path.join(app, 'node_modules/electron/package.json'), JSON.stringify({ name: 'electron', version: '44.7.0' }));
  put(path.join(app, 'node_modules/electron/dist/electron.exe'), 'MZ controlled fixture, never executed');
  put(path.join(app, 'node_modules/electron/dist/version'), metadata.devDependencies.electron);
  put(path.join(app, 'node_modules/electron/dist/resources.pak'), 'controlled distribution fixture');
  put(path.join(app, 'node_modules/electron/path.txt'), 'electron.exe');
  put(path.join(payload, 'owned-runtime/runtime-job.node'), 'MZ synthetic owned addon, never loaded');
  for (const name of ['LICENSE', 'frontend/index.html', 'core/dist/index.js', 'core/dist/application.js', 'core/dist/tools/desktop-process.js', 'node/node.exe', 'node/LICENSE', 'python/python.exe', 'python/LICENSE.txt', 'workers/document/worker.py', 'workers/document/requirements.txt', 'workers/document/LICENSE', 'workers/evaluation/worker.py', 'workers/evaluation/requirements.txt', 'workers/evaluation/LICENSE', 'core/node_modules/better-sqlite3/prebuilds/win32-x64.node', 'core/node_modules/sqlite-vec-windows-x64/vec0.dll']) put(path.join(payload, name));
  put(path.join(payload, 'core/package.json'), JSON.stringify({ name: '@marlin/core', version: '0.7.0', type: 'module' }));
  put(path.join(payload, 'core/package-lock.json'), '{}');
  put(path.join(payload, 'python/runtime-manifest.json'), JSON.stringify({ format: 'marlin-python-runtime-v1', platform: 'win_amd64',
    inputs: { python_version: '3.13.16', dependency_lock_sha256: sha(path.join(root, 'scripts/desktop/python-runtime-lock-windows-x64.txt')), native_lock_sha256: sha(path.join(root, 'scripts/desktop/python-runtime-lock-native.txt')) },
    dependencies: [{name: 'ragas', version: '0.4.3'}] }));
  function manifest() {
    const files = {};
    const visit = directory => { for (const entry of fs.readdirSync(directory, { withFileTypes: true })) { const full = path.join(directory, entry.name); if (entry.isDirectory()) visit(full); else if (full !== path.join(payload, 'source-manifest.json')) files[path.relative(payload, full).split(path.sep).join('/')] = sha(full); } };
    visit(payload);
    const manifest = { format: 'marlin-electron-payload-v1', platform: 'win32-x64', versions: { desktop: metadata.version, core: '0.7.0', frontend: '0.6.2-django' }, node_version: '22.23.2', node_archive_sha256: '1177b4137ba5adaa56354ae40f1080c7450e8ae09cecb47da459d1c52ac99f97', input_sha256: {}, files, system_node_required_at_runtime: false, system_python_required_at_runtime: false, django_packaged: false };
    for (const name of ['desktop/package-lock.json', 'packages/core/package-lock.json', 'frontend/package-lock.json', 'scripts/desktop/python-runtime-lock-windows-x64.txt', 'scripts/desktop/python-runtime-lock-native.txt']) manifest.input_sha256[name] = sha(path.join(root, name));
    manifest.source_sha256 = sourceSnapshot();
    manifest.bootstrap_sha256 = sha(path.join(app, 'runtime-bootstrap.cjs'));
    put(path.join(payload, 'source-manifest.json'), JSON.stringify(manifest));
    // Synthetic formal shape tests the production validator only; no native gate is claimed to have run.
    const electronModule = path.join(app, 'node_modules/electron');
    const distribution = { format: 'marlin-electron-distribution-v1', version: metadata.devDependencies.electron,
      package_sha256: sha(path.join(electronModule, 'package.json')), path_sha256: sha(path.join(electronModule, 'path.txt')),
      files: Object.fromEntries(['electron.exe', 'version', 'resources.pak'].map(name => [name, sha(path.join(electronModule, 'dist', name))])) };
    const native = { format: 'marlin-core-payload-verification-v1', state: 'verified', paid_model_calls: 0, gui_verified: false, installer_verified: false,
      owned_runtime: { node_version: 'v22.23.2', platform: 'win32', arch: 'x64', napi_version: '10', addon_sha256: sha(path.join(payload, 'owned-runtime/runtime-job.node')), identity_verified: true, api_verified: true,
        identity: { pid: 123, createdAt: '1', executable: path.join(payload, 'node/node.exe') } },
      native: { node_version: 'v22.23.2', platform: 'win32', arch: 'x64', sqlite_version: '3.53.4', vector_version: 'v0.1.9', fts_id: '1152921504606847297', vector_id: '1152921504606847297', paid_model_calls: 0 },
      ipc: { protocol: 1, runtime: 'typescript', http_listener: false, capabilities_status: 200, setup_required: true, exit_code: 0, paid_model_calls: 0, owned_runtime_job_bound: true } };
    const nativePrefix = 'desktop/native/runtime-job/';
    const runtimeJob = { schemaVersion: 1, target: { platform: 'win32', arch: 'x64', napiVersion: 8, nodeVersion: '22.23.2' }, actualExitCode: 0,
      sourceFiles: Object.entries(manifest.source_sha256).filter(([name]) => name.startsWith(nativePrefix)).map(([name, hash]) => ({ path: name.slice(nativePrefix.length), size: fs.statSync(path.join(root, name)).size, sha256: hash })),
      nodeExecutable: { path: path.join(payload, 'node/node.exe'), sha256: sha(path.join(payload, 'node/node.exe')), platform: 'win32', arch: 'x64', versions: { node: '22.23.2', napi: '10' } },
      ownedRunnerSha256: sha(path.join(root, 'scripts/desktop/windows-job.py')), identitySmoke: { pid: 123, createdAt: '1', executable: path.join(payload, 'node/node.exe') },
      artifact: { path: path.join(payload, 'owned-runtime/runtime-job.node'), sha256: native.owned_runtime.addon_sha256, size: fs.statSync(path.join(payload, 'owned-runtime/runtime-job.node')).size },
      inputs: { headersArchiveSha256: 'daaf13ec5d45a38bbcfcff06d0723f72a6813b89ab27bb5af2ac8e1f6259dde0', nodeLibSha256: 'ac15f1e9d7c8279353723a77f6319967f1a41c06026521094a8234c2e6fbe052', shasumsSha256: '778ac5b2fcdbd68d9c0ae9f4310674faa3af0910bd0d18e7f6597787c40a3e39' }, compiler: { path: 'C:/BuildTools/cl.exe', sha256: '4'.repeat(64) },
      imports: ['KERNEL32.dll', 'node.exe'], commands: [{ argv: ['cl.exe'], exitCode: 0, log: 'synthetic compilation projection' }] };
    const electronLoader = { format: 'marlin-owned-runtime-loader-v1', state: 'verified', versions: { node: '24.21.0', electron: metadata.devDependencies.electron, napi: '10' },
      owned_runtime: { node_version: 'v24.21.0', platform: 'win32', arch: 'x64', napi_version: '10', addon_sha256: native.owned_runtime.addon_sha256,
        identity: { pid: 456, createdAt: '2', executable: path.join(electronModule, 'dist/electron.exe') }, identity_verified: true, api_verified: true },
      paid_model_calls: 0, gui_started: false, core_started: false };
    const python = { state: 'verified', paid_model_calls: 0, python: { version: '3.13.16 controlled fixture', isolated: 1, no_site: 1, django_spec: false, ragas_version: '0.4.3', dependencies: [{name: 'ragas', version: '0.4.3'}] },
      django_import: 'ModuleNotFoundError', fixtures: Array.from({length: 11}, (_, index) => ({ name: 'controlled-' + index, canonical_sha256: '1'.repeat(64) })),
      ragas: { ragas_version: '0.4.3', django_imported: false, model_transport: 'core_rpc' }, system_python_required_at_runtime: false };
    const langfuse = { format: 'marlin-langfuse-native-test-v1', state: 'verified', platform: 'win32', electron: metadata.devDependencies.electron,
      paid_model_calls: 0, owned_core_exit_code: 0, foreign_project_requests: 0 };
    for (const field of ['real_nextauth_protocol', 'actual_private_child_json', 'renderer_cookie_secret_absent', 'isolated_memory_session', 'httponly_host_only_lax', 'sandbox_no_preload_node', 'popups_denied', 'owned_cookie_clear', 'unrelated_browser_cookie_preserved', 'public_cancel_no_window', 'public_cancel_pending_navigation', 'public_logout_clears_window', 'public_configuration_change_clears_window']) langfuse[field] = true;
    put(path.join(work, 'core-verification.json'), JSON.stringify(native));
    put(path.join(work, 'runtime-job-build.json'), JSON.stringify(runtimeJob));
    put(path.join(work, 'controlled-gates/owned-runtime-electron.json'), JSON.stringify(electronLoader));
    put(path.join(work, 'python-verification.json'), JSON.stringify(python));
    put(path.join(work, 'controlled-gates/langfuse-native.json'), JSON.stringify(langfuse));
    const desktop = Object.fromEntries(appFiles.map(name => [name, sha(path.join(app, name))]));
    put(path.join(work, 'windows-gates.json'), JSON.stringify({ format: 'marlin-windows-build-gates-v1', state: 'verified', scope: 'frozen_source', source_before_after_equal: true,
      source_sha256: manifest.source_sha256, desktop_sha256: desktop, electron_distribution: distribution,
      core_entry_sha256: sha(path.join(payload, 'core/dist/tools/desktop-process.js')), frontend_index_sha256: sha(path.join(payload, 'frontend/index.html')),
      core_tests: { tests: 24, passed: 24, failed: 0, skipped: 0, duration_ms: 1 }, runtime_tests: { tests: 6, passed: 6, failed: 0, skipped: 0, duration_ms: 1 },
      packaged_bootstrap_tests: { tests: 2, passed: 2, failed: 0, skipped: 0, duration_ms: 1 },
      packaged_bootstrap_tests_scope: 'actual_asar_external_node_unit_native_core_doubles',
      owned_runtime_electron: electronLoader, owned_runtime_electron_report_sha256: sha(path.join(work, 'controlled-gates/owned-runtime-electron.json')),
      native, native_report_sha256: sha(path.join(work, 'core-verification.json')), runtime_job_build: runtimeJob, runtime_job_build_report_sha256: sha(path.join(work, 'runtime-job-build.json')), langfuse_report_sha256: sha(path.join(work, 'controlled-gates/langfuse-native.json')), manual_gui_verified: false, real_external_vendor_verified: false, installer_executed: false, python_report_sha256: sha(path.join(work, 'python-verification.json')), python_fixture_count: 11, langfuse, paid_model_calls: 0 }));
    put(path.join(work, 'prepared-build.json'), JSON.stringify({ format: 'marlin-prepared-windows-build-v1', state: 'verified', source_sha256: manifest.source_sha256, payload_manifest_sha256: sha(path.join(payload, 'source-manifest.json')), desktop_sha256: desktop, gates_sha256: sha(path.join(work, 'windows-gates.json')), electron_distribution: distribution }));
    return manifest;
  }
  manifest();
  return { directory, work, app, payload, data, manifest, close: () => fs.rmSync(directory, { recursive: true, force: true }) };
}
function options(extra = {}) { return { platform: 'win32', arch: 'x64', env: { SystemRoot: 'C:\\Windows', NODE_OPTIONS: '--require unsafe', ELECTRON_RUN_AS_NODE: '1', OPENAI_API_KEY: 'fixture-never-forward', PATH: 'unsafe', PYTHONPATH: 'unsafe', LOCALAPPDATA: 'fixture-profile' }, ...extra }; }
test('Windows SQLite prebuild from the locked published layout reaches the controlled child without a node-gyp artifact', async () => {
  const lock = JSON.parse(fs.readFileSync(path.join(root, 'packages/core/package-lock.json'), 'utf8'));
  assert.equal(lock.packages['node_modules/better-sqlite3'].version, '13.0.3');
  const f = fixture('process.exitCode=7;'); let child;
  try {
    assert.equal(fs.existsSync(path.join(f.payload, 'core/node_modules/better-sqlite3/build/Release/better_sqlite3.node')), false);
    assert.equal(fs.existsSync(path.join(f.payload, 'core/node_modules/better-sqlite3/prebuilds/win32-x64.node')), true);
    const code = await implementation().main(['--work-dir', f.work], options({ spawn: (_executable, argv, settings) => {
      child = spawn(process.execPath, argv, { ...settings, stdio: 'ignore' }); return child;
    } }));
    assert.equal(code, 7); assert.equal(child.exitCode, 7);
  } finally { if (child?.exitCode === null && child.signalCode === null) child.kill('SIGKILL'); f.close(); }
});
for (const damage of ['missing', 'old-fallback-only', 'wrong-architecture', 'tampered']) test('Windows SQLite prebuild rejects ' + damage + ' before any child', async () => {
  const f = fixture(), binary = path.join(f.payload, 'core/node_modules/better-sqlite3/prebuilds/win32-x64.node');
  try {
    if (damage === 'tampered') put(binary, 'modified native binary');
    else {
      fs.unlinkSync(binary);
      if (damage === 'old-fallback-only') put(path.join(f.payload, 'core/node_modules/better-sqlite3/build/Release/better_sqlite3.node'), 'old layout only');
      if (damage === 'wrong-architecture') put(path.join(f.payload, 'core/node_modules/better-sqlite3/prebuilds/win32-arm64.node'), 'wrong architecture');
      // Rebind synthetic manifests so the required native path itself is exercised.
      f.manifest();
    }
    await rejectsBeforeSpawn(['--work-dir', f.work], damage === 'tampered' ? /SHA256/ : /必要文件/);
  } finally { f.close(); }
});
async function rejectsBeforeSpawn(argv, pattern, extra = {}) {
  let calls = 0;
  await assert.rejects(implementation().main(argv, options({ spawn: () => { calls++; throw new Error('Must not spawn'); }, ...extra })), pattern);
  assert.equal(calls, 0);
}

// WIN-ASAR-BOOTSTRAP-001: inventory rebinding cannot turn a different script into the source bootstrap.
for (const damage of ['missing', 'rehashed-bytes']) test('physical bootstrap refuses ' + damage + ' before launch', async () => {
  const f = fixture();
  try {
    const file = path.join(f.payload, 'owned-runtime/runtime-bootstrap.cjs');
    if (damage === 'missing') fs.unlinkSync(file); else put(file, 'changed bootstrap');
    f.manifest();
    await rejectsBeforeSpawn(['--work-dir', f.work], /bootstrap|必要文件/);
  } finally { f.close(); }
});

for (const damage of ['missing-addon', 'addon-bytes', 'build-report', 'target', 'napi', 'source', 'source-omitted', 'node-version', 'node-hash', 'runner-hash', 'smoke-identity', 'artifact-hash', 'artifact-size', 'input-pin', 'imports', 'command', 'exit', 'loader-hash', 'loader-version', 'loader-identity', 'job-unbound', 'electron-loader-hash', 'electron-loader-version', 'electron-loader-identity', 'electron-gui', 'electron-core']) test('owned Runtime build and loader facts reject rebound SHA before child: ' + damage, async () => {
  const f = fixture();
  try {
    if (damage === 'missing-addon') { fs.unlinkSync(path.join(f.payload, 'owned-runtime/runtime-job.node')); }
    else if (damage === 'addon-bytes') put(path.join(f.payload, 'owned-runtime/runtime-job.node'), 'MZ altered addon');
    else if (damage === 'build-report') put(path.join(f.work, 'runtime-job-build.json'), '{}');
    else changeGates(f, g => {
      const build = g.runtime_job_build;
      if (damage === 'target') build.target.platform = 'linux';
      if (damage === 'napi') build.target.napiVersion = 9;
      if (damage === 'source') build.sourceFiles[0].sha256 = '0'.repeat(64);
      if (damage === 'source-omitted') build.sourceFiles = [];
      if (damage === 'node-version') build.nodeExecutable.versions.node = '0.0.0';
      if (damage === 'node-hash') build.nodeExecutable.sha256 = '0'.repeat(64);
      if (damage === 'runner-hash') build.ownedRunnerSha256 = '0'.repeat(64);
      if (damage === 'smoke-identity') build.identitySmoke.createdAt = 1;
      if (damage === 'artifact-hash') build.artifact.sha256 = '0'.repeat(64);
      if (damage === 'artifact-size') build.artifact.size++;
      if (damage === 'input-pin') build.inputs.nodeLibSha256 = '0'.repeat(64);
      if (damage === 'imports') build.imports.push('VCRUNTIME140.dll');
      if (damage === 'command') build.commands[0].exitCode = 1;
      if (damage === 'exit') build.actualExitCode = 1;
      if (damage === 'loader-hash') g.native.owned_runtime.addon_sha256 = '0'.repeat(64);
      if (damage === 'loader-version') g.native.owned_runtime.node_version = 'v0.0.0';
      if (damage === 'loader-identity') g.native.owned_runtime.identity.executable = 'C:/foreign.exe';
      if (damage === 'job-unbound') g.native.ipc.owned_runtime_job_bound = false;
      if (damage === 'electron-loader-hash') g.owned_runtime_electron.owned_runtime.addon_sha256 = '0'.repeat(64);
      if (damage === 'electron-loader-version') g.owned_runtime_electron.versions.node = '0.0.0';
      if (damage === 'electron-loader-identity') g.owned_runtime_electron.owned_runtime.identity.createdAt = 1;
      if (damage === 'electron-gui') g.owned_runtime_electron.gui_started = true;
      if (damage === 'electron-core') g.owned_runtime_electron.core_started = true;
      put(path.join(f.work, 'runtime-job-build.json'), JSON.stringify(build)); g.runtime_job_build_report_sha256 = sha(path.join(f.work, 'runtime-job-build.json'));
      put(path.join(f.work, 'core-verification.json'), JSON.stringify(g.native)); g.native_report_sha256 = sha(path.join(f.work, 'core-verification.json'));
      put(path.join(f.work, 'controlled-gates/owned-runtime-electron.json'), JSON.stringify(g.owned_runtime_electron)); g.owned_runtime_electron_report_sha256 = sha(path.join(f.work, 'controlled-gates/owned-runtime-electron.json'));
    });
    await rejectsBeforeSpawn(['--work-dir', f.work], /Runtime Job|必要文件|SHA256/);
  } finally { f.close(); }
});

test('root scripts use actual compiled TS/package commands and no normal Django runtime', () => {
  const { scripts } = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
  assert.equal(scripts['start:local'], 'node packages/core/dist/tools/dev-server.js');
  assert.equal(scripts['start:desktop'], 'node scripts/desktop/start-desktop.cjs');
  assert.equal(scripts.build, 'npm --prefix packages/core run build && npm --prefix frontend run build');
  assert.equal(scripts.typecheck, 'npm --prefix packages/core run typecheck');
  assert.equal(scripts['build:desktop'], 'python scripts/build_windows.py');
  assert.equal(scripts['test:core'], 'npm --prefix packages/core test');
  assert.equal(scripts['test:frontend'], 'npm --prefix frontend run test:unit');
  assert.equal(scripts['test:desktop'], 'npm --prefix desktop test');
  assert.equal(scripts['test:startup'], 'node --test scripts/desktop/startup.test.cjs');
  assert.equal(scripts.test, 'npm run test:core && npm run test:frontend && npm run test:desktop && npm run test:startup');
  for (const key of ['start:local', 'start:desktop', 'test', 'build', 'typecheck']) assert.doesNotMatch(scripts[key], /python|manage\.py|start_.*\.py/);
});

for (const argv of [[], ['--work-dir'], ['--work-dir', '--smoke-test'], ['--work-dir', 'x', '--unknown'], ['--work-dir', 'x', '--work-dir', 'y'], ['--work-dir', 'x', '--data-dir'], ['--work-dir', 'x', '--smoke-test', '--smoke-test'], ['--work-dir', 'x', '--python', 'x'], ['--work-dir', 'x', '--data-dir', 'bad\0path']]) test('invalid desktop CLI input is rejected before any child: ' + JSON.stringify(argv), () => rejectsBeforeSpawn(argv, /参数|work-dir|data-dir/));

test('non-Windows and non-x64 launches explicitly fail without starting a runtime', async () => {
  await rejectsBeforeSpawn(['--work-dir', '/unused'], /Windows x64/, { platform: 'linux' });
  await rejectsBeforeSpawn(['--work-dir', '/unused'], /Windows x64/, { arch: 'arm64' });
});

for (const damage of ['marker', 'main', 'electron', 'manifest', 'unknown-app', 'modified', 'extra', 'missing', 'manifest-platform', 'django', 'prepared', 'app-changed', 'gate-changed']) test('desktop preflight rejects ' + damage + ' without spawn', async () => {
  const f = fixture();
  try {
    if (damage === 'marker') put(path.join(f.work, '.marlin-build'), 'wrong\n');
    if (damage === 'main') fs.unlinkSync(path.join(f.app, 'main.cjs'));
    if (damage === 'electron') fs.unlinkSync(path.join(f.app, 'node_modules/electron/dist/electron.exe'));
    if (damage === 'manifest') fs.unlinkSync(path.join(f.payload, 'source-manifest.json'));
    if (damage === 'unknown-app') put(path.join(f.app, 'legacy-django.py'));
    if (damage === 'modified') put(path.join(f.payload, 'workers/document/worker.py'), 'modified helper');
    if (damage === 'extra') put(path.join(f.payload, 'surprise.py'));
    if (damage === 'missing') fs.unlinkSync(path.join(f.payload, 'core/dist/application.js'));
    if (damage === 'prepared') fs.unlinkSync(path.join(f.work, 'prepared-build.json'));
    if (damage === 'app-changed') put(path.join(f.app, 'main.cjs'), 'changed entry');
    if (damage === 'gate-changed') put(path.join(f.work, 'windows-gates.json'), '{}');
    if (damage === 'manifest-platform' || damage === 'django') { const m = f.manifest(); m[damage === 'django' ? 'django_packaged' : 'platform'] = damage === 'django' ? true : 'linux-x64'; put(path.join(f.payload, 'source-manifest.json'), JSON.stringify(m)); }
    await rejectsBeforeSpawn(['--work-dir', f.work], /构建|准备|清单|文件|Windows|Django|SHA/);
  } finally { f.close(); }
});

for (const place of ['work-parent', 'app', 'payload-child', 'electron', 'data-parent', 'marker']) test('symlink/junction ' + place + ' is rejected before spawn', async () => {
  const f = fixture();
  try {
    let work = f.work, data = f.data;
    const target = place === 'work-parent' ? path.join(f.directory, 'linked-work') : place === 'app' ? f.app : place === 'payload-child' ? path.join(f.payload, 'workers/document') : place === 'electron' ? path.join(f.app, 'node_modules/electron/dist/electron.exe') : place === 'marker' ? path.join(f.work, '.marlin-build') : path.join(f.directory, 'linked-data');
    const source = target + '-original';
    if (fs.existsSync(target)) fs.renameSync(target, source); else fs.mkdirSync(source);
    if (place === 'work-parent') { fs.rmdirSync(source); fs.symlinkSync(f.work, target, process.platform === 'win32' ? 'junction' : 'dir'); work = target; }
    else { fs.symlinkSync(source, target, ['electron', 'marker'].includes(place) ? 'file' : process.platform === 'win32' ? 'junction' : 'dir'); if (place === 'data-parent') data = path.join(target, 'new-data'); }
    await rejectsBeforeSpawn(['--work-dir', work, '--data-dir', data], /链接|junction|symlink/);
  } finally { f.close(); }
});

for (const kind of ['no-data', 'existing-content', 'payload-overlap', 'work-ancestor']) test('smoke data safety rejects ' + kind + ' without creating files', async () => {
  const f = fixture();
  try {
    let data = kind === 'payload-overlap' ? path.join(f.payload, 'test-data') : kind === 'work-ancestor' ? f.directory : f.data;
    if (kind === 'existing-content') put(path.join(data, 'core.sqlite3'), 'existing private data');
    const args = ['--work-dir', f.work, ...(kind === 'no-data' ? [] : ['--data-dir', data]), '--smoke-test'];
    await rejectsBeforeSpawn(args, /smoke|隔离|空|数据|data-dir/);
    if (kind === 'existing-content') assert.equal(fs.readFileSync(path.join(data, 'core.sqlite3'), 'utf8'), 'existing private data');
    if (kind === 'no-data') assert.equal(fs.existsSync(f.data), false);
  } finally { f.close(); }
});

for (const name of ['../outside', '/absolute', 'C:/outside', 'workers\\escape.py', 'workers//escape.py']) test('manifest path ' + JSON.stringify(name) + ' cannot escape or alias payload', async () => {
  const f = fixture();
  try { const m = f.manifest(); m.files[name] = '0'.repeat(64); put(path.join(f.payload, 'source-manifest.json'), JSON.stringify(m)); await rejectsBeforeSpawn(['--work-dir', f.work], /清单|路径/); }
  finally { f.close(); }
});

test('actual controlled Node child receives Chinese/spaces/shell syntax literally and exits with its own status under the runtime environment whitelist', async () => {
  const f = fixture(); let child, output = '';
  const dangerous = path.join(f.directory, '中文 数据 $(touch SHELL_SENTINEL); & echo unsafe');
  try {
    const result = await implementation().main(['--work-dir', f.work, '--data-dir', dangerous, '--smoke-test'], options({ spawn: (executable, argv, settings) => {
      assert.equal(executable, path.join(f.app, 'node_modules/electron/dist/electron.exe'));
      assert.equal(settings.shell, false); assert.equal(settings.cwd, f.app);
      child = spawn(process.execPath, argv, { ...settings, stdio: ['ignore', 'pipe', 'pipe'] }); child.stdout.on('data', bytes => output += bytes); return child;
    } }));
    assert.equal(result, 7); assert.equal(child.exitCode, 7); assert.equal(child.signalCode, null);
    const receipt = JSON.parse(output); assert.deepEqual(receipt.argv, ['--data-dir', dangerous, '--smoke-test']);
    for (const key of ['NODE_OPTIONS', 'ELECTRON_RUN_AS_NODE', 'OPENAI_API_KEY', 'PATH', 'PYTHONPATH']) assert.equal(receipt.env[key], undefined);
    assert.equal(receipt.env.SystemRoot, 'C:\\Windows'); assert.equal(receipt.env.LOCALAPPDATA, 'fixture-profile');
    assert.equal(fs.existsSync(path.join(f.app, 'SHELL_SENTINEL')), false);
    assert.equal(fs.existsSync(dangerous), false, 'launcher preflight does not create data or accounts');
    assert.throws(() => process.kill(child.pid, 0), /ESRCH/);
  } finally { if (child?.exitCode === null) child.kill('SIGKILL'); f.close(); }
});

test('ordinary launch keeps omitted data-dir omitted and preserves existing isolated data unchanged', async () => {
  const f = fixture(); let child, output = '';
  try {
    put(path.join(f.data, 'core.sqlite3'), 'untouched existing fixture');
    const receipt = await implementation().main(['--work-dir', f.work], options({ spawn: (_executable, argv, settings) => { child = spawn(process.execPath, argv, { ...settings, stdio: ['ignore', 'pipe', 'pipe'] }); child.stdout.on('data', bytes => output += bytes); return child; } }));
    assert.equal(receipt, 7); assert.deepEqual(JSON.parse(output).argv, []);
    assert.equal(fs.readFileSync(path.join(f.data, 'core.sqlite3'), 'utf8'), 'untouched existing fixture');
  } finally { if (child?.exitCode === null) child.kill('SIGKILL'); f.close(); }
});

test('a prepared source snapshot cannot silently omit an existing build input', async () => {
  const f = fixture();
  try {
    const manifest = f.manifest(), preparedFile = path.join(f.work, 'prepared-build.json');
    delete manifest.source_sha256['frontend/src/main.ts'];
    put(path.join(f.payload, 'source-manifest.json'), JSON.stringify(manifest));
    const prepared = JSON.parse(fs.readFileSync(preparedFile, 'utf8'));
    prepared.source_sha256 = manifest.source_sha256;
    prepared.payload_manifest_sha256 = sha(path.join(f.payload, 'source-manifest.json'));
    put(preparedFile, JSON.stringify(prepared));
    await rejectsBeforeSpawn(['--work-dir', f.work], /清单/);
  } finally { f.close(); }
});

test('cancelling launcher awaits its real owned child exit while an unrelated child remains alive', async () => {
  const f = fixture("process.stdout.write('READY\\n');setInterval(()=>{},1000);");
  const unrelated = spawn(process.execPath, ['-e', 'setInterval(()=>{},1000)'], { stdio: 'ignore' });
  const controller = new AbortController(); let child, ready;
  const started = new Promise(resolve => { ready = resolve; });
  try {
    const pending = implementation().main(['--work-dir', f.work], options({ signal: controller.signal, spawn: (_executable, argv, settings) => { child = spawn(process.execPath, argv, { ...settings, stdio: ['ignore', 'pipe', 'pipe'] }); child.stdout.on('data', bytes => { if (String(bytes).includes('READY')) ready(); }); return child; } }));
    await started; controller.abort(); assert.equal(await pending, 143);
    assert.notEqual(child.signalCode, null); assert.throws(() => process.kill(child.pid, 0), /ESRCH/);
    assert.doesNotThrow(() => process.kill(unrelated.pid, 0));
  } finally { if (child?.exitCode === null) child.kill('SIGKILL'); unrelated.kill('SIGKILL'); f.close(); }
});

test('actual npm start:local forwards original arguments into the compiled TS entry contract without invoking Python', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'marlin-npm-startup-'));
  try {
    put(path.join(directory, 'package.json'), fs.readFileSync(path.join(root, 'package.json')));
    put(path.join(directory, 'packages/core/dist/tools/dev-server.js'), "console.log('FORWARDED='+JSON.stringify(process.argv.slice(2)));process.exitCode=9;");
    const data = path.join(directory, '中文 空格 $(touch NPM_SENTINEL); & literal');
    const npmCli = [process.env.npm_execpath, path.join(path.dirname(process.execPath), 'node_modules/npm/bin/npm-cli.js'), path.join(path.dirname(process.execPath), '../lib/node_modules/npm/bin/npm-cli.js')].find(file => file && fs.existsSync(file));
    assert.ok(npmCli, 'The source npm command requires an installed npm-cli.js');
    const result = spawnSync(process.execPath, [npmCli, 'run', 'start:local', '--', '--data-root', data, '--port', '0', '--ui-origin', 'http://127.0.0.1:5173'], { cwd: directory, encoding: 'utf8', timeout: 20000 });
    assert.equal(result.status, 9, result.stderr);
    const line = result.stdout.split('\n').find(value => value.startsWith('FORWARDED='));
    assert.deepEqual(JSON.parse(line.slice('FORWARDED='.length)), ['--data-root', data, '--port', '0', '--ui-origin', 'http://127.0.0.1:5173']);
    assert.equal(fs.existsSync(path.join(directory, 'NPM_SENTINEL')), false);
  } finally { fs.rmSync(directory, { recursive: true, force: true }); }
});

function changeGates(f, change) {
  const reportFile = path.join(f.work, 'windows-gates.json'), preparedFile = path.join(f.work, 'prepared-build.json');
  const report = JSON.parse(fs.readFileSync(reportFile)); change(report); put(reportFile, JSON.stringify(report));
  const prepared = JSON.parse(fs.readFileSync(preparedFile)); prepared.gates_sha256 = sha(reportFile); put(preparedFile, JSON.stringify(prepared));
}
for (const damage of ['unknown-format', 'failed-state', 'artifact-only', 'source-changed', 'paid-call', 'suite-failed', 'suite-skipped', 'suite-short', 'suite-count-mismatch', 'suite-non-integer', 'suite-duration', 'langfuse-fact', 'langfuse-version', 'source-map', 'desktop-map', 'core-output', 'frontend-output', 'native-platform', 'native-vector', 'native-id', 'native-ipc', 'native-report', 'python-report', 'python-ragas', 'python-django', 'python-count', 'python-version', 'python-dependencies', 'python-duplicate-fixture', 'python-lock-pin', 'scope-claims', 'window-report']) test('formal gate semantics reject rebound SHA: ' + damage, async () => {
  const f = fixture();
  try {
    changeGates(f, g => {
      if (damage === 'unknown-format') g.format = 'unknown-format';
      if (damage === 'failed-state') g.state = 'failed';
      if (damage === 'artifact-only') g.scope = 'artifact_only';
      if (damage === 'source-changed') g.source_before_after_equal = false;
      if (damage === 'paid-call') g.paid_model_calls = 1;
      if (damage === 'suite-failed') g.core_tests.failed = 1;
      if (damage === 'suite-skipped') g.runtime_tests.skipped = 1;
      if (damage === 'suite-short') g.runtime_tests.tests = g.runtime_tests.passed = 5;
      if (damage === 'suite-count-mismatch') g.core_tests.tests = 25;
      if (damage === 'suite-non-integer') g.core_tests.tests = g.core_tests.passed = 24.5;
      if (damage === 'suite-duration') g.runtime_tests.duration_ms = -1;
      if (damage === 'langfuse-fact') g.langfuse.public_cancel_pending_navigation = false;
      if (damage === 'langfuse-version') g.langfuse.electron = '0.0.0';
      if (damage === 'source-map') delete g.source_sha256['frontend/src/main.ts'];
      if (damage === 'desktop-map') g.desktop_sha256['main.cjs'] = '0'.repeat(64);
      if (damage === 'core-output') g.core_entry_sha256 = '0'.repeat(64);
      if (damage === 'frontend-output') g.frontend_index_sha256 = '0'.repeat(64);
      if (damage === 'native-platform') g.native.native.platform = 'linux';
      if (damage === 'native-vector') g.native.native.vector_version = 'v0.0.0';
      if (damage === 'native-id') g.native.native.vector_id = '1';
      if (damage === 'native-ipc') g.native.ipc.http_listener = true;
      if (damage === 'scope-claims') g.installer_executed = true;
      if (damage.startsWith('native-') && damage !== 'native-report') { const file = path.join(f.work, 'core-verification.json'); put(file, JSON.stringify(g.native)); g.native_report_sha256 = sha(file); }
      if (damage.startsWith('langfuse-')) { const file = path.join(f.work, 'controlled-gates/langfuse-native.json'); put(file, JSON.stringify(g.langfuse)); g.langfuse_report_sha256 = sha(file); }
      if (damage === 'native-report') fs.unlinkSync(path.join(f.work, 'core-verification.json'));
      if (damage === 'window-report') put(path.join(f.work, 'controlled-gates/langfuse-native.json'), '{}');
      if (damage.startsWith('python-')) {
        const file = path.join(f.work, 'python-verification.json'), python = JSON.parse(fs.readFileSync(file));
        if (damage === 'python-report') put(file, '{}');
        else {
          if (damage === 'python-ragas') python.ragas.ragas_version = '0.0.0';
          if (damage === 'python-django') python.python.django_spec = true;
          if (damage === 'python-count') python.fixtures.pop();
          if (damage === 'python-version') python.python.version = '3.12.0 controlled fixture';
          if (damage === 'python-dependencies') python.python.dependencies[0].version = '0.0.0';
          if (damage === 'python-duplicate-fixture') python.fixtures[1] = python.fixtures[0];
          if (damage === 'python-lock-pin') { const runtime = JSON.parse(fs.readFileSync(path.join(f.payload, 'python/runtime-manifest.json'))); runtime.inputs.native_lock_sha256 = '0'.repeat(64); put(path.join(f.payload, 'python/runtime-manifest.json'), JSON.stringify(runtime));
            const manifestFile = path.join(f.payload, 'source-manifest.json'), manifest = JSON.parse(fs.readFileSync(manifestFile)); manifest.files['python/runtime-manifest.json'] = sha(path.join(f.payload, 'python/runtime-manifest.json')); put(manifestFile, JSON.stringify(manifest));
            const preparedFile = path.join(f.work, 'prepared-build.json'), prepared = JSON.parse(fs.readFileSync(preparedFile)); prepared.payload_manifest_sha256 = sha(manifestFile); put(preparedFile, JSON.stringify(prepared)); }
          put(file, JSON.stringify(python)); g.python_report_sha256 = sha(file);
        }
      }
    });
    await rejectsBeforeSpawn(['--work-dir', f.work], /gate|验证|报告|清单|SHA|文件|原生/i);
  } finally { f.close(); }
});
for (const damage of ['executable-bytes', 'extra-dist', 'missing-dist', 'package-bytes', 'path-bytes', 'dist-version', 'distribution-rebound', 'distribution-omitted']) test('Electron full distribution rejects ' + damage + ' before spawn', async () => {
  const f = fixture(); const modulePath = path.join(f.app, 'node_modules/electron');
  try {
    if (damage === 'executable-bytes') put(path.join(modulePath, 'dist/electron.exe'), 'ALTERED executable bytes');
    if (damage === 'extra-dist') put(path.join(modulePath, 'dist/new.dll'), 'unrecorded bytes');
    if (damage === 'missing-dist') fs.unlinkSync(path.join(modulePath, 'dist/resources.pak'));
    if (damage === 'package-bytes') fs.appendFileSync(path.join(modulePath, 'package.json'), '\n');
    if (damage === 'path-bytes') put(path.join(modulePath, 'path.txt'), '../electron.exe');
    if (damage === 'dist-version') put(path.join(modulePath, 'dist/version'), '0.0.0');
    if (damage === 'distribution-rebound' || damage === 'distribution-omitted') changeGates(f, g => { if (damage === 'distribution-omitted') delete g.electron_distribution; else g.electron_distribution.files['electron.exe'] = '0'.repeat(64); });
    await rejectsBeforeSpawn(['--work-dir', f.work], /Electron|分发|清单|SHA|文件/);
  } finally { f.close(); }
});

test('POSIX cancellation retains owned group cleanup after the leader exits while an unrelated child survives', { skip: process.platform === 'win32' }, async () => {
  const entry = "const {spawn}=require('node:child_process');const child=spawn(process.execPath,['-e',\"process.on('SIGTERM',()=>{});process.send('ready');setInterval(()=>{},1000)\"],{stdio:['ignore','ignore','ignore','ipc']});child.once('message',()=>process.stdout.write('DESCENDANT='+child.pid+'\\n'));";
  const f = fixture(entry), unrelated = spawn(process.execPath, ['-e', 'setInterval(()=>{},1000)'], { stdio: 'ignore' });
  const controller = new AbortController(); let child, descendant, output = '', ready;
  const started = new Promise(resolve => { ready = resolve; });
  const active = pid => { try { const stat = fs.readFileSync('/proc/' + pid + '/stat', 'utf8'); return !/[)] [ZX] /.test(stat); } catch (error) { if (error.code === 'ENOENT') return false; throw error; } };
  try {
    const pending = implementation().main(['--work-dir', f.work], options({ signal: controller.signal, spawn: (_exe, argv, settings) => {
      child = spawn(process.execPath, argv, { ...settings, stdio: ['ignore', 'pipe', 'pipe'] });
      child.stdout.on('data', bytes => { output += bytes; const match = output.match(/DESCENDANT=(\d+)\n/); if (match) { descendant = Number(match[1]); ready(); } }); return child;
    } }));
    await started; assert.equal(active(descendant), true); controller.abort(); assert.equal(await pending, 143);
    assert.equal(active(descendant), false, 'main must wait for the owned TERM-resistant descendant to stop');
    assert.throws(() => process.kill(child.pid, 0), /ESRCH/); assert.doesNotThrow(() => process.kill(unrelated.pid, 0));
  } finally {
    if (child?.pid) { try { process.kill(-child.pid, 'SIGKILL'); } catch (error) { if (error.code !== 'ESRCH') throw error; } }
    if (unrelated.exitCode === null && unrelated.signalCode === null) { const closed = new Promise(resolve => unrelated.once('close', resolve)); unrelated.kill('SIGKILL'); await closed; }
    f.close();
  }
});

function windowsEnvironment() {
  return Object.fromEntries(Object.entries(process.env).filter(([name]) => /^(systemroot|windir|systemdrive|comspec|pathext|temp|tmp|userprofile|localappdata|appdata)$/i.test(name)));
}
function realWindowsFixture(entry) {
  const f = fixture(entry);
  fs.copyFileSync(process.execPath, path.join(f.app, 'node_modules/electron/dist/electron.exe'));
  f.manifest(); return f;
}
async function waitFixture(file, pending) {
  const deadline = Date.now() + 15000;
  while (!fs.existsSync(file)) {
    assert.ok(Date.now() < deadline, 'actual owned fixture must publish its ready handshake');
    await Promise.race([new Promise(resolve => setTimeout(resolve, 25)), pending.then(() => { throw new Error('owned fixture exited before ready'); })]);
  }
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}
for (const mode of ['cancel', 'leader-exit']) test('Windows private JobObject cleans actual owned descendants and preserves unrelated child: ' + mode, { skip: process.platform !== 'win32' }, async t => {
  const helper = path.join(__dirname, 'windows-launch-supervisor.ps1');
  assert.equal(fs.existsSync(helper), true, 'production Windows launch requires its fixed JobObject supervisor');
  const f = realWindowsFixture(); const readyFile = path.join(f.directory, 'owned-ready.json');
  const entry = "const {spawn}=require('node:child_process');const fs=require('node:fs');const child=spawn(process.execPath,['-e',\"process.on('SIGTERM',()=>{});process.send('ready');setInterval(()=>{},1000)\"],{stdio:['ignore','ignore','ignore','ipc']});child.once('message',()=>{fs.writeFileSync(" + JSON.stringify(readyFile) + ",JSON.stringify({leader:process.pid,descendant:child.pid}));" + (mode === 'leader-exit' ? 'process.exit(7);' : 'setInterval(()=>{},1000);') + '});';
  put(path.join(f.app, 'main.cjs'), entry); f.manifest();
  const unrelated = spawn(process.execPath, ['-e', 'setInterval(()=>{},1000)'], { stdio: 'ignore' });
  const controller = new AbortController(); let receipt;
  try {
    const pending = implementation().main(['--work-dir', f.work], { signal: controller.signal, env: windowsEnvironment() });
    pending.catch(() => {});
    receipt = await waitFixture(readyFile, mode === 'cancel' ? pending : new Promise(() => {}));
    const began = Date.now(); if (mode === 'cancel') controller.abort();
    const code = await pending, cleanupMs = Date.now() - began;
    assert.equal(code, mode === 'cancel' ? 143 : 7); assert.ok(cleanupMs < 6500, 'actual native cleanup must stay bounded');
    for (const pid of [receipt.leader, receipt.descendant]) assert.throws(() => process.kill(pid, 0), /ESRCH/);
    assert.doesNotThrow(() => process.kill(unrelated.pid, 0));
    t.diagnostic(JSON.stringify({ scope: 'actual_win32_owned_node_fixture', mode, code, cleanup_ms: cleanupMs, leader_pid: receipt.leader, descendant_pid: receipt.descendant, unrelated_pid: unrelated.pid, leader_alive: false, descendant_alive: false, unrelated_alive: true }));
  } finally {
    if (unrelated.exitCode === null && unrelated.signalCode === null) { const closed = new Promise(resolve => unrelated.once('close', resolve)); unrelated.kill('SIGKILL'); await closed; }
    f.close();
  }
});
test('Windows private JobObject preserves actual stdout stderr exit and literal argv under the whitelist', { skip: process.platform !== 'win32' }, async t => {
  assert.equal(fs.existsSync(path.join(__dirname, 'windows-launch-supervisor.ps1')), true);
  const f = realWindowsFixture("process.stdout.write('RECEIPT='+JSON.stringify({argv:process.argv.slice(2),env:process.env})+'\\n');process.stderr.write('OWNED_STDERR\\n');process.exitCode=7;");
  const data = path.join(f.directory, '中文 空格 $(touch SENTINEL); & literal "quote"');
  try {
    const env = { ...windowsEnvironment(), OPENAI_API_KEY: 'controlled-never-forward', PYTHONPATH: 'unsafe', ELECTRON_RUN_AS_NODE: '1', NODE_OPTIONS: '--no-warnings', PATH: 'unsafe' };
    const result = spawnSync(process.execPath, [launcherFile, '--work-dir', f.work, '--data-dir', data], { env, encoding: 'utf8', timeout: 20000 });
    assert.equal(result.status, 7, result.stderr); assert.match(result.stderr, /OWNED_STDERR/);
    const line = result.stdout.split('\n').find(line => line.startsWith('RECEIPT=')); assert.ok(line, result.stdout);
    const receipt = JSON.parse(line.slice(8)); assert.deepEqual(receipt.argv, ['--data-dir', data]);
    for (const name of ['OPENAI_API_KEY', 'PYTHONPATH', 'ELECTRON_RUN_AS_NODE', 'NODE_OPTIONS', 'PATH']) assert.equal(receipt.env[name], undefined);
    assert.equal(fs.existsSync(path.join(f.app, 'SENTINEL')), false); assert.equal(fs.existsSync(data), false);
    t.diagnostic(JSON.stringify({ scope: 'actual_win32_owned_node_fixture', code: result.status, stdout_preserved: true, stderr_preserved: true, literal_argv_verified: true, poisoned_env_absent: true, no_shell_sentinel: true }));
  } finally { f.close(); }
});
for (const phase of ['create', 'assign']) test('Windows private JobObject actual API ' + phase + ' failure never resumes an uncontrolled child', { skip: process.platform !== 'win32' }, async t => {
  const helper = path.join(__dirname, 'windows-launch-supervisor.ps1'); assert.equal(fs.existsSync(helper), true);
  const f = realWindowsFixture(), marker = path.join(f.directory, 'must-not-execute');
  try {
    put(path.join(f.app, 'main.cjs'), 'require("node:fs").writeFileSync(' + JSON.stringify(marker) + ',"uncontrolled");setInterval(()=>{},1000);');
    // Fault only an isolated copy: invoke genuine Win32 failure, retain the production rollback and wait code.
    const original = fs.readFileSync(helper, 'utf8');
    const before = phase === 'create' ? 'CreateJobObjectW(IntPtr.Zero, null)' : 'AssignProcessToJobObject(job, process.process)';
    const after = phase === 'create' ? 'CreateJobObjectW(IntPtr.Zero, @"Marlin\\invalid")' : 'AssignProcessToJobObject(IntPtr.Zero, process.process)';
    assert.equal(original.split(before).length, 2, 'fault injection must identify one reviewed API call');
    const controlled = path.join(f.directory, 'fault-supervisor.ps1'); put(controlled, original.replace(before, after));
    const system = Object.entries(windowsEnvironment()).find(([name]) => name.toLowerCase() === 'systemroot')[1];
    const input = JSON.stringify({ format: 'marlin-electron-launch-v1', executable: path.join(f.app, 'node_modules/electron/dist/electron.exe'), argv: [f.app], cwd: f.app, env: windowsEnvironment() }) + '\n';
    const result = spawnSync(path.join(system, 'System32/WindowsPowerShell/v1.0/powershell.exe'), ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', controlled], { input, env: windowsEnvironment(), encoding: 'utf8', timeout: 20000 });
    assert.equal(result.status, 125, result.stderr); assert.match(result.stderr, /WIN32_SUPERVISION_FAILED/); assert.match(result.stderr, phase === 'create' ? /create private job/ : /assign suspended child/); assert.equal(fs.existsSync(marker), false);
    t.diagnostic(JSON.stringify({ scope: 'actual_win32_failure_in_isolated_helper_copy', phase, guard_exit: result.status, safe_error: result.stderr.trim(), resumed_marker_present: false }));
  } finally { f.close(); }
});

for (const [name, marker] of [['LF', 'marlin-electron-build-v1\n'], ['CRLF', 'marlin-electron-build-v1\r\n']]) test('official build marker ' + name + ' reaches the controlled child without rewriting the marker', async () => {
  const f = fixture('process.exitCode=7;'); let child;
  try {
    const markerFile = path.join(f.work, '.marlin-build'); put(markerFile, marker);
    const before = fs.readFileSync(markerFile);
    const code = await implementation().main(['--work-dir', f.work], options({ spawn: (executable, argv, settings) => {
      assert.equal(executable, path.join(f.app, 'node_modules/electron/dist/electron.exe'));
      assert.equal(settings.shell, false);
      child = spawn(process.execPath, argv, { ...settings, stdio: 'ignore' }); return child;
    } }));
    assert.equal(code, 7); assert.equal(child.exitCode, 7); assert.equal(child.signalCode, null);
    assert.deepEqual(fs.readFileSync(markerFile), before, 'preflight must preserve the original official marker bytes');
    assert.throws(() => process.kill(child.pid, 0), /ESRCH/);
  } finally { if (child?.exitCode === null && child.signalCode === null) child.kill('SIGKILL'); f.close(); }
});
for (const [name, marker] of [
  ['missing-newline', 'marlin-electron-build-v1'], ['CR-only', 'marlin-electron-build-v1\r'],
  ['extra-LF', 'marlin-electron-build-v1\n\n'], ['extra-CRLF', 'marlin-electron-build-v1\r\n\r\n'],
  ['leading-space', ' marlin-electron-build-v1\n'], ['trailing-space', 'marlin-electron-build-v1 \r\n'],
  ['BOM', '\ufeffmarlin-electron-build-v1\r\n'], ['NUL', 'marlin-electron-build-v1\r\n\0'],
  ['mixed-extra-newline', 'marlin-electron-build-v1\n\r\n'], ['unknown-version', 'marlin-electron-build-v2\r\n']
]) test('unofficial build marker ' + name + ' is rejected without spawn or normalization', async () => {
  const f = fixture();
  try {
    const file = path.join(f.work, '.marlin-build'); put(file, marker); const before = fs.readFileSync(file);
    await rejectsBeforeSpawn(['--work-dir', f.work], /目录不属于当前 Electron 构建/);
    assert.deepEqual(fs.readFileSync(file), before);
  } finally { f.close(); }
});
