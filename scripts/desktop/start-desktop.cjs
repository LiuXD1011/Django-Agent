'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { createHash } = require('node:crypto');
const { runtimeEnv } = require('../../desktop/runtime.cjs');

const root = path.resolve(__dirname, '../..');
const markerValues = ['marlin-electron-build-v1\n', 'marlin-electron-build-v1\r\n'];
const appFiles = ['main.cjs', 'runtime.cjs', 'owned-runtime.cjs', 'runtime-bootstrap.cjs', 'ipc.cjs', 'preload.cjs', 'protocol.cjs', 'langfuse.cjs', 'loading.html', 'package.json', 'LICENSE', 'icon.png'];
const inputs = ['desktop/package-lock.json', 'packages/core/package-lock.json', 'frontend/package-lock.json', 'scripts/desktop/python-runtime-lock-windows-x64.txt', 'scripts/desktop/python-runtime-lock-native.txt'];
const runtimeJobPins = { headersArchiveSha256: 'daaf13ec5d45a38bbcfcff06d0723f72a6813b89ab27bb5af2ac8e1f6259dde0',
  nodeLibSha256: 'ac15f1e9d7c8279353723a77f6319967f1a41c06026521094a8234c2e6fbe052',
  shasumsSha256: '778ac5b2fcdbd68d9c0ae9f4310674faa3af0910bd0d18e7f6597787c40a3e39' };
const sourceFolders = ['frontend/src/', 'frontend/public/', 'packages/core/src/', 'packages/core/test/', 'workers/document/', 'workers/evaluation/', 'scripts/desktop/', 'desktop/native/runtime-job/'];
const sourceFiles = new Set(['LICENSE', 'scripts/build_windows.py', 'scripts/bundle_windows_native.py', 'scripts/test_build_windows.py', 'desktop/runtime.test.cjs', 'desktop/runtime-shutdown.test.cjs', 'desktop/runtime-bootstrap.test.cjs', 'desktop/runtime-quit.test.cjs', 'desktop/langfuse-electron-test.cjs', ...appFiles.filter(name => !['LICENSE', 'icon.png'].includes(name)).map(name => 'desktop/' + name), 'desktop/package-lock.json', 'frontend/package.json', 'frontend/package-lock.json', 'frontend/index.html', 'frontend/vite.config.ts', 'packages/core/package.json', 'packages/core/package-lock.json', 'packages/core/tsconfig.json', 'packages/core/scripts/prepare-native.mjs']);
const requiredPayload = ['LICENSE', 'owned-runtime/runtime-job.node', 'frontend/index.html', 'core/package.json', 'core/package-lock.json', 'core/dist/index.js', 'core/dist/application.js', 'core/dist/tools/desktop-process.js', 'core/node_modules/better-sqlite3/prebuilds/win32-x64.node', 'core/node_modules/sqlite-vec-windows-x64/vec0.dll', 'node/node.exe', 'node/LICENSE', 'python/python.exe', 'python/LICENSE.txt', 'workers/document/worker.py', 'workers/document/requirements.txt', 'workers/document/LICENSE', 'workers/evaluation/worker.py', 'workers/evaluation/requirements.txt', 'workers/evaluation/LICENSE'];
const buildHint = '请在 Windows x64 使用 Python 3.13 先准备：python scripts/build_windows.py --work-dir "C:\\MarlinBuild" --prepare-only；再传入该 --work-dir。';
function fail(message) { throw new Error(message + '\n' + buildHint); }
function requireCondition(value, message) { if (!value) fail(message); }
function record(value) { return !!value && typeof value === 'object' && !Array.isArray(value); }
function sameKeys(value, names) { return record(value) && Object.keys(value).length === names.length && names.every(name => Object.hasOwn(value, name)); }

function parseArguments(argv) {
  const values = {};
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i];
    requireCondition(['--work-dir', '--data-dir', '--smoke-test'].includes(key) && !Object.hasOwn(values, key), '参数未知或重复。');
    if (key === '--smoke-test') values[key] = true;
    else {
      const value = argv[++i];
      requireCondition(typeof value === 'string' && value.length > 0 && !value.startsWith('--') && !/[\x00-\x1f\x7f]/.test(value), `参数 ${key} 缺少有效值。`);
      requireCondition(!/^\\\\|^\/\//.test(value), '构建及数据目录必须位于本地磁盘，不能使用 UNC 路径。');
      values[key] = path.resolve(value);
    }
  }
  requireCondition(values['--work-dir'], '必须明确提供 --work-dir 构建目录。');
  requireCondition(!values['--smoke-test'] || values['--data-dir'], '--smoke-test 必须提供独立空目录 --data-dir。');
  return { workDir: values['--work-dir'], dataDir: values['--data-dir'], smoke: !!values['--smoke-test'] };
}

function checkedStat(file, allowMissing = false) {
  let stat;
  try { stat = fs.lstatSync(file); }
  catch (error) { if (allowMissing && error.code === 'ENOENT') return undefined; fail('构建或数据路径缺少必要文件/目录。'); }
  requireCondition(!stat.isSymbolicLink(), '拒绝 symlink/junction 链接路径。');
  requireCondition(stat.isDirectory() || stat.isFile(), '构建目录含有非常规文件。');
  return stat;
}
function rejectParentLinks(file, allowMissing = false) {
  for (let candidate = path.resolve(file); ; candidate = path.dirname(candidate)) {
    checkedStat(candidate, allowMissing);
    if (candidate === path.dirname(candidate)) break;
  }
}
function inventory(directory) {
  requireCondition(checkedStat(directory).isDirectory(), '构建目录类型不正确。');
  const files = [];
  const visit = location => {
    for (const name of fs.readdirSync(location)) {
      const file = path.join(location, name), stat = checkedStat(file);
      if (stat.isDirectory()) visit(file); else files.push(file);
    }
  };
  visit(directory); return files;
}
function sourceNames() {
  const names = new Set(sourceFiles);
  for (const folder of sourceFolders) for (const file of inventory(path.join(root, folder))) {
    const name = path.relative(root, file).split(path.sep).join('/');
    if (name.split('/').some(part => ['.env', '.secrets', '.settings', '.git', 'credentials', 'secrets', '__pycache__'].includes(part) || part.startsWith('.env.')) || /\.(?:sqlite|sqlite3|db|key|p12|pfx|secret|log|pyc)$/i.test(name)) continue;
    names.add(name);
  }
  return [...names];
}
function digest(file) {
  requireCondition(checkedStat(file).isFile(), '清单中缺少必要文件。');
  const hash = createHash('sha256'), bytes = Buffer.allocUnsafe(64 * 1024);
  const descriptor = fs.openSync(file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0));
  try { let length; while ((length = fs.readSync(descriptor, bytes, 0, bytes.length, null)) > 0) hash.update(bytes.subarray(0, length)); }
  finally { fs.closeSync(descriptor); }
  return hash.digest('hex');
}
function json(file) {
  requireCondition(checkedStat(file).isFile(), '构建准备文件缺失。');
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { fail('构建清单不是有效 JSON。'); }
}
function manifestPath(name) {
  requireCondition(typeof name === 'string' && name.length > 0 && !/[\\:\x00-\x1f\x7f]/.test(name) && !name.startsWith('/') && name.split('/').every(part => part && !['.', '..'].includes(part) && !/[. ]$/.test(part) && !/^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(part)), '清单路径不安全。');
  return name;
}
function verifyHashMap(directory, expected, actualNames, allowed = () => true) {
  requireCondition(record(expected) && Object.keys(expected).length > 0, '构建哈希清单缺失。');
  const seen = new Set();
  for (const [name, hash] of Object.entries(expected)) {
    manifestPath(name);
    requireCondition(allowed(name) && typeof hash === 'string' && /^[a-f0-9]{64}$/.test(hash) && !seen.has(name.toLowerCase()), '构建哈希清单字段不正确或路径重名。');
    seen.add(name.toLowerCase());
    const file = path.join(directory, ...name.split('/'));
    rejectParentLinks(file);
    requireCondition(digest(file) === hash, `构建文件 SHA256 已变化：${name}`);
  }
  if (actualNames) requireCondition(actualNames.length === Object.keys(expected).length && actualNames.every(name => Object.hasOwn(expected, name)), '构建文件清单与实际目录不一致。');
}
function equal(left, right) {
  if (left === right) return true;
  if (Array.isArray(left) && Array.isArray(right)) return left.length === right.length && left.every((value, index) => equal(value, right[index]));
  return record(left) && record(right) && sameKeys(left, Object.keys(right)) && Object.keys(left).every(name => equal(left[name], right[name]));
}
function electronDistribution(app, expectedVersion) {
  const module = path.join(app, 'node_modules/electron'), dist = path.join(module, 'dist');
  const version = json(path.join(module, 'package.json')).version;
  requireCondition(version === expectedVersion && fs.readFileSync(path.join(dist, 'version'), 'utf8').replace(/^v/, '') === expectedVersion && fs.readFileSync(path.join(module, 'path.txt'), 'utf8') === 'electron.exe', 'Electron 分发版本或执行路径不正确。');
  return { format: 'marlin-electron-distribution-v1', version, package_sha256: digest(path.join(module, 'package.json')), path_sha256: digest(path.join(module, 'path.txt')),
    files: Object.fromEntries(inventory(dist).map(file => [path.relative(dist, file).split(path.sep).join('/'), digest(file)])) };
}
function verifyRuntimeJob(report, payload, snapshot) {
  const hash = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
  requireCondition(record(report) && report.schemaVersion === 1 && report.actualExitCode === 0 &&
    equal(report.target, { platform: 'win32', arch: 'x64', napiVersion: 8, nodeVersion: '22.23.2' }), 'Runtime Job 构建目标或结果不正确。');
  const prefix = 'desktop/native/runtime-job/';
  const expected = Object.fromEntries(Object.entries(snapshot).filter(([name]) => name.startsWith(prefix)).map(([name, sha]) => [name.slice(prefix.length), sha]));
  const rows = report.sourceFiles;
  requireCondition(Array.isArray(rows) && rows.length > 0 && rows.every(row => record(row) && typeof row.path === 'string' && Object.hasOwn(expected, row.path) && hash(row.sha256) && Number.isSafeInteger(row.size) && row.size > 0) &&
    new Set(rows.map(row => row.path)).size === rows.length && equal(Object.fromEntries(rows.map(row => [row.path, row.sha256])), expected), 'Runtime Job 源文件清单不正确。');
  for (const [field, name] of [['artifact', 'owned-runtime/runtime-job.node'], ['nodeExecutable', 'node/node.exe']]) {
    const value = report[field], file = path.join(payload, name); rejectParentLinks(file);
    requireCondition(record(value) && value.path === file && value.sha256 === digest(file), 'Runtime Job 产物或 Node SHA256 已变化。');
    if (field === 'artifact') requireCondition(Number.isSafeInteger(value.size) && value.size > 0 && value.size === checkedStat(file).size, 'Runtime Job 产物长度不正确。');
    else requireCondition(value.platform === 'win32' && value.arch === 'x64' && record(value.versions) && value.versions.node === '22.23.2' && typeof value.versions.napi === 'string' && /^\d+$/.test(value.versions.napi) && Number(value.versions.napi) >= 8, 'Runtime Job Node 版本不正确。');
  }
  const smoke = report.identitySmoke;
  requireCondition(report.ownedRunnerSha256 === snapshot['scripts/desktop/windows-job.py'] && record(smoke) && Number.isSafeInteger(smoke.pid) && smoke.pid > 0 &&
    typeof smoke.createdAt === 'string' && /^[1-9][0-9]{0,19}$/.test(smoke.createdAt) && typeof smoke.executable === 'string' && smoke.executable.toLowerCase() === path.join(payload, 'node/node.exe').toLowerCase(), 'Runtime Job 构建loader/runner原生身份不正确。');
  requireCondition(record(report.compiler) && typeof report.compiler.path === 'string' && report.compiler.path.length > 0 && hash(report.compiler.sha256) &&
    record(report.inputs) && Object.entries(runtimeJobPins).every(([name, pin]) => report.inputs[name] === pin), 'Runtime Job 编译器或输入绑定不正确。');
  requireCondition(Array.isArray(report.commands) && report.commands.length > 0 && report.commands.every(row => record(row) && row.exitCode === 0 && Array.isArray(row.argv) && row.argv.length > 0 && row.argv.every(arg => typeof arg === 'string') && typeof row.log === 'string'), 'Runtime Job 编译命令失败或不完整。');
  requireCondition(Array.isArray(report.imports) && report.imports.length > 0 && new Set(report.imports).size === report.imports.length &&
    report.imports.every(name => typeof name === 'string' && ['kernel32.dll', 'node.exe'].includes(name.toLowerCase())) && report.imports.some(name => name.toLowerCase() === 'node.exe'), 'Runtime Job DLL 导入不正确。');
}
function verifyGates(work, app, manifest, prepared, version) {
  const gates = json(path.join(work, 'windows-gates.json')), payload = path.join(app, 'payload');
  requireCondition(record(gates) && gates.format === 'marlin-windows-build-gates-v1' && gates.state === 'verified' && gates.scope === 'frozen_source' && gates.source_before_after_equal === true && gates.paid_model_calls === 0, 'Windows gate 验证报告状态或范围不正确。');
  for (const [name, minimum] of [['core_tests', 24], ['runtime_tests', 6]]) {
    const result = gates[name];
    requireCondition(record(result) && ['tests', 'passed', 'failed', 'skipped'].every(field => Number.isSafeInteger(result[field]) && result[field] >= 0) && result.tests === result.passed && result.passed >= minimum && result.failed === 0 && result.skipped === 0 && typeof result.duration_ms === 'number' && Number.isFinite(result.duration_ms) && result.duration_ms >= 0, 'Windows gate 必要测试计数或耗时不正确。');
  }
  const distribution = electronDistribution(app, version);
  requireCondition(equal(gates.electron_distribution, distribution) && equal(prepared.electron_distribution, distribution), 'Electron 分发 SHA256 或完整文件清单已变化。');
  requireCondition(equal(gates.source_sha256, manifest.source_sha256) && equal(gates.desktop_sha256, prepared.desktop_sha256) && gates.core_entry_sha256 === digest(path.join(payload, 'core/dist/tools/desktop-process.js')) && gates.frontend_index_sha256 === digest(path.join(payload, 'frontend/index.html')), 'Windows gate 来源或产物绑定清单不正确。');
  requireCondition(['manual_gui_verified', 'real_external_vendor_verified', 'installer_executed'].every(name => gates[name] === false), 'Windows gate 验证范围声明不正确。');
  const report = (name, field) => {
    const file = path.join(work, name); rejectParentLinks(file);
    requireCondition(digest(file) === gates[field], 'Windows gate 引用验证报告 SHA256 已变化。');
    const value = json(file); requireCondition(record(value), 'Windows gate 引用验证报告格式不正确。'); return value;
  };
  const window = report('controlled-gates/langfuse-native.json', 'langfuse_report_sha256');
  const fields = ['real_nextauth_protocol', 'actual_private_child_json', 'renderer_cookie_secret_absent', 'isolated_memory_session', 'httponly_host_only_lax', 'sandbox_no_preload_node', 'popups_denied', 'owned_cookie_clear', 'unrelated_browser_cookie_preserved', 'public_cancel_no_window', 'public_cancel_pending_navigation', 'public_logout_clears_window', 'public_configuration_change_clears_window'];
  requireCondition(equal(window, gates.langfuse) && window.format === 'marlin-langfuse-native-test-v1' && window.state === 'verified' && window.platform === 'win32' && window.electron === distribution.version && window.paid_model_calls === 0 && window.owned_core_exit_code === 0 && window.foreign_project_requests === 0 && fields.every(name => window[name] === true), 'Windows gate 原生 Electron 验证事实不正确。');
  const native = report('core-verification.json', 'native_report_sha256'), database = native.native, ipc = native.ipc;
  const runtimeJob = report('runtime-job-build.json', 'runtime_job_build_report_sha256');
  requireCondition(equal(runtimeJob, gates.runtime_job_build), 'Runtime Job 引用报告不一致。');
  verifyRuntimeJob(runtimeJob, payload, manifest.source_sha256);
  const owned = native.owned_runtime;
  requireCondition(record(owned) && owned.node_version === 'v22.23.2' && owned.platform === 'win32' && owned.arch === 'x64' &&
    typeof owned.napi_version === 'string' && /^\d+$/.test(owned.napi_version) && Number(owned.napi_version) >= 8 && owned.addon_sha256 === runtimeJob.artifact.sha256 &&
    owned.identity_verified === true && owned.api_verified === true && record(ipc) && ipc.owned_runtime_job_bound === true, 'Windows gate Runtime Job loader/IPC 验证事实不正确。');
  const electronLoader = report('controlled-gates/owned-runtime-electron.json', 'owned_runtime_electron_report_sha256');
  const versions = electronLoader.versions, electronOwned = electronLoader.owned_runtime;
  requireCondition(equal(electronLoader, gates.owned_runtime_electron) && electronLoader.format === 'marlin-owned-runtime-loader-v1' && electronLoader.state === 'verified' &&
    record(versions) && versions.electron === distribution.version && versions.node === '24.21.0' && typeof versions.napi === 'string' && /^\d+$/.test(versions.napi) && Number(versions.napi) >= 8 &&
    record(electronOwned) && electronOwned.node_version === 'v24.21.0' && electronOwned.platform === 'win32' && electronOwned.arch === 'x64' && electronOwned.napi_version === versions.napi &&
    electronOwned.addon_sha256 === runtimeJob.artifact.sha256 && electronOwned.identity_verified === true && electronOwned.api_verified === true &&
    electronLoader.paid_model_calls === 0 && electronLoader.gui_started === false && electronLoader.core_started === false, 'Runtime Job Electron loader 验证事实不正确。');
  for (const [projection, executable] of [[owned, path.join(payload, 'node/node.exe')], [electronOwned, path.join(app, 'node_modules/electron/dist/electron.exe')]]) {
    const identity = projection.identity;
    requireCondition(record(identity) && Number.isSafeInteger(identity.pid) && identity.pid > 0 && typeof identity.createdAt === 'string' && /^[1-9][0-9]{0,19}$/.test(identity.createdAt) &&
      typeof identity.executable === 'string' && identity.executable.toLowerCase() === executable.toLowerCase(), 'Runtime Job loader 原生身份不正确。');
  }
  requireCondition(equal(native, gates.native) && native.format === 'marlin-core-payload-verification-v1' && native.state === 'verified' && native.paid_model_calls === 0 && native.gui_verified === false && native.installer_verified === false && record(database) && database.node_version === 'v22.23.2' && database.platform === 'win32' && database.arch === 'x64' && database.vector_version === 'v0.1.9' && database.paid_model_calls === 0 && typeof database.fts_id === 'string' && /^[1-9][0-9]*$/.test(database.fts_id) && database.vector_id === database.fts_id && BigInt(database.fts_id) > 2n ** 53n && record(ipc) && ipc.protocol === 1 && ipc.runtime === 'typescript' && ipc.http_listener === false && ipc.capabilities_status === 200 && ipc.setup_required === true && ipc.exit_code === 0 && ipc.paid_model_calls === 0, 'Windows gate 原生 SQLite/FTS/vector/IPC 验证事实不正确。');
  const python = report('python-verification.json', 'python_report_sha256'), runtime = python.python, ragas = python.ragas, fixtures = python.fixtures;
  requireCondition(python.state === 'verified' && python.paid_model_calls === 0 && python.system_python_required_at_runtime === false && python.django_import === 'ModuleNotFoundError' && record(runtime) && typeof runtime.version === 'string' && runtime.version.startsWith('3.13.16 ') && runtime.isolated === 1 && runtime.no_site === 1 && runtime.django_spec === false && record(ragas) && ragas.ragas_version === '0.4.3' && ragas.django_imported === false && ragas.model_transport === 'core_rpc' && Array.isArray(fixtures) && fixtures.length >= 11 && fixtures.length === gates.python_fixture_count && fixtures.every(row => record(row) && typeof row.name === 'string' && typeof row.canonical_sha256 === 'string' && /^[a-f0-9]{64}$/.test(row.canonical_sha256)) && new Set(fixtures.map(row => row.name)).size === fixtures.length, 'Windows gate Python/文档/Ragas/隔离验证事实不正确。');
  const dependencies = rows => {
    requireCondition(Array.isArray(rows) && rows.length > 0 && rows.every(row => record(row) && typeof row.name === 'string' && typeof row.version === 'string'), 'Python 验证依赖清单不正确。');
    const values = Object.fromEntries(rows.map(row => [row.name.replace(/[-_.]+/g, '-').toLowerCase(), row.version]));
    requireCondition(Object.keys(values).length === rows.length, 'Python 验证依赖清单重名。'); return values;
  };
  const pythonManifest = json(path.join(payload, 'python/runtime-manifest.json')), pins = pythonManifest.inputs;
  requireCondition(pythonManifest.format === 'marlin-python-runtime-v1' && pythonManifest.platform === 'win_amd64' && record(pins) && pins.python_version === '3.13.16' && pins.dependency_lock_sha256 === manifest.input_sha256['scripts/desktop/python-runtime-lock-windows-x64.txt'] && pins.native_lock_sha256 === manifest.input_sha256['scripts/desktop/python-runtime-lock-native.txt'] && equal(dependencies(runtime.dependencies), dependencies(pythonManifest.dependencies)), 'Python 验证依赖版本或锁文件清单不正确。');
}
function overlaps(left, right) {
  const within = (parent, child) => { const relative = path.relative(parent, child); return relative === '' || relative !== '..' && !relative.startsWith('..' + path.sep) && !path.isAbsolute(relative); };
  return within(left, right) || within(right, left);
}

function preflight(options, platform = process.platform, arch = process.arch) {
  requireCondition(platform === 'win32' && arch === 'x64', '当前只交付 Windows x64 桌面启动；不支持此平台。');
  rejectParentLinks(options.workDir);
  requireCondition(checkedStat(path.join(options.workDir, '.marlin-build')).isFile(), '构建标记文件缺失。');
  requireCondition(markerValues.includes(fs.readFileSync(path.join(options.workDir, '.marlin-build'), 'utf8')), '目录不属于当前 Electron 构建，请重新准备。');
  const app = path.join(options.workDir, 'app'), payload = path.join(app, 'payload');
  const allowed = new Set([...appFiles, 'package-lock.json', 'payload', 'node_modules', 'release']);
  requireCondition(checkedStat(app).isDirectory() && fs.readdirSync(app).every(name => allowed.has(name)), '应用目录含白名单以外文件。');
  for (const name of appFiles) requireCondition(checkedStat(path.join(app, name)).isFile(), '应用构建文件缺失。');
  // Traverse executable/dependency paths as well as payload; a regular file behind a junction is unsafe.
  inventory(app);
  const metadata = json(path.join(app, 'package.json'));
  requireCondition(metadata.name === 'marlin-desktop' && metadata.main === 'main.cjs' && Array.isArray(metadata.build?.files) && metadata.build.files.length === appFiles.length && appFiles.every(name => metadata.build.files.includes(name)), '应用 package.json 白名单或入口不正确。');
  requireCondition(JSON.stringify(metadata.build.extraResources) === JSON.stringify([{ from: 'payload', to: 'runtime', filter: ['**/*', '!**/__pycache__/**', '!**/*.pyc'] }]), '应用 payload 资源配置不正确。');
  const executable = path.join(app, 'node_modules/electron/dist/electron.exe');
  requireCondition(checkedStat(executable).isFile() && json(path.join(app, 'node_modules/electron/package.json')).version === metadata.devDependencies.electron, '准备目录缺少匹配的 native Electron.exe。');
  const manifestFile = path.join(payload, 'source-manifest.json'), manifest = json(manifestFile);
  requireCondition(manifest.format === 'marlin-electron-payload-v1' && manifest.platform === 'win32-x64' && manifest.node_version === '22.23.2', '构建清单不是目标 Windows x64 版本。');
  requireCondition(manifest.system_node_required_at_runtime === false && manifest.system_python_required_at_runtime === false && manifest.django_packaged === false, '构建清单依赖系统运行时或包含 Django。');
  requireCondition(manifest.versions?.desktop === metadata.version && manifest.versions?.core === json(path.join(payload, 'core/package.json')).version, '构建版本清单不一致。');
  requireCondition(sameKeys(manifest.input_sha256, inputs), '构建输入清单缺失。');
  verifyHashMap(root, manifest.input_sha256, inputs);
  const names = inventory(payload).filter(file => file !== manifestFile).map(file => path.relative(payload, file).split(path.sep).join('/'));
  requireCondition(requiredPayload.every(name => names.includes(name)) && !names.some(name => name.split('/').includes('django') || /(?:^|\/)manage\.py$/.test(name)), '构建缺少 TS/helper 必要文件或包含 Django。');
  verifyHashMap(payload, manifest.files, names);
  const prepared = json(path.join(options.workDir, 'prepared-build.json'));
  requireCondition(prepared.format === 'marlin-prepared-windows-build-v1' && prepared.state === 'verified' && prepared.payload_manifest_sha256 === digest(manifestFile) && prepared.gates_sha256 === digest(path.join(options.workDir, 'windows-gates.json')), '构建准备状态或验证报告已变化，请重新准备。');
  verifyHashMap(app, prepared.desktop_sha256, appFiles);
  verifyGates(options.workDir, app, manifest, prepared, metadata.devDependencies.electron);
  requireCondition(record(manifest.source_sha256) && sameKeys(prepared.source_sha256, Object.keys(manifest.source_sha256)) && Object.entries(manifest.source_sha256).every(([name, hash]) => prepared.source_sha256[name] === hash), '构建来源清单不一致。');
  const sources = sourceNames(), allowedSources = new Set(sources);
  verifyHashMap(root, manifest.source_sha256, sources, name => allowedSources.has(name));
  requireCondition(Object.hasOwn(manifest.source_sha256, 'scripts/desktop/start-desktop.cjs') && Object.hasOwn(manifest.source_sha256, 'desktop/main.cjs'), '构建来源缺少启动入口，请重新准备。');
  if (options.dataDir) {
    rejectParentLinks(options.dataDir, true);
    requireCondition(!overlaps(options.workDir, options.dataDir), '数据目录必须独立于构建目录。');
    const stat = checkedStat(options.dataDir, true);
    requireCondition(!stat || stat.isDirectory(), '数据路径必须是目录。');
    requireCondition(!options.smoke || !stat || fs.readdirSync(options.dataDir).length === 0, 'smoke 只接受显式隔离空数据目录。');
  }
  return { executable, app, argv: [app, ...(options.dataDir ? ['--data-dir', options.dataDir] : []), ...(options.smoke ? ['--smoke-test'] : [])] };
}

// Dependencies are supplied by trusted program tests only, never exposed as CLI flags.
async function main(argv = process.argv.slice(2), dependencies = {}) {
  const parsed = parseArguments(argv), plan = preflight(parsed, dependencies.platform ?? process.platform, dependencies.arch ?? process.arch);
  const env = runtimeEnv(dependencies.env ?? process.env), start = dependencies.spawn ?? spawn;
  if (dependencies.signal?.aborted) return 143;
  const supervised = process.platform === 'win32' && !dependencies.spawn;
  let child;
  try {
    if (supervised) {
      const system = Object.entries(env).find(([name]) => name.toLowerCase() === 'systemroot')?.[1];
      requireCondition(system, 'Windows SystemRoot 缺失，不能安全启动所属进程。');
      const helper = path.join(__dirname, 'windows-launch-supervisor.ps1'); rejectParentLinks(helper);
      child = start(path.join(system, 'System32/WindowsPowerShell/v1.0/powershell.exe'), ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', helper], { cwd: plan.app, shell: false, env, stdio: ['pipe', 'inherit', 'inherit'], windowsHide: true });
      child.stdin.on('error', () => {}); // An already closed guard must not cause an unhandled pipe error.
      child.stdin.write(JSON.stringify({ format: 'marlin-electron-launch-v1', executable: plan.executable, argv: plan.argv, cwd: plan.app, env }) + '\n');
    } else child = start(plan.executable, plan.argv, { cwd: plan.app, shell: false, env, stdio: 'inherit', detached: process.platform !== 'win32', windowsHide: false });
  }
  catch { fail('Electron 子进程未能启动。'); }
  return new Promise((resolve, reject) => {
    let timer, graceTimer, cancelling = false, closed = false, result, cleanupExpired = false;
    const terminate = force => {
      if (supervised) { child.stdin.end('CANCEL\n'); return; }
      if (!child.pid) return;
      if (process.platform === 'win32' && (child.exitCode !== null || child.signalCode !== null)) return;
      if (process.platform === 'win32') {
        const system = Object.entries(env).find(([name]) => name.toLowerCase() === 'systemroot')?.[1];
        if (!system) { child.kill(force ? 'SIGKILL' : 'SIGTERM'); return; }
        const killer = spawn(path.join(system, 'System32/taskkill.exe'), ['/PID', String(child.pid), '/T', ...(force ? ['/F'] : [])], { shell: false, env, stdio: 'ignore', windowsHide: true, timeout: 2000 });
        killer.once('error', () => { if (child.exitCode === null && child.signalCode === null) child.kill(force ? 'SIGKILL' : 'SIGTERM'); });
      } else {
        try { process.kill(-child.pid, force ? 'SIGKILL' : 'SIGTERM'); }
        catch (error) { if (error.code !== 'ESRCH') child.kill(force ? 'SIGKILL' : 'SIGTERM'); }
      }
    };
    const finish = () => { if (closed) { cleanup(); resolve(result); } };
    const cancel = () => { if (cancelling) return; cancelling = true; terminate(false); if (supervised) { timer = setTimeout(() => { cleanupExpired = true; child.kill('SIGKILL'); }, 7000); return; } timer = setTimeout(() => { terminate(true); graceTimer = setTimeout(() => { if (!closed) { cleanup(); reject(new Error('所属 Electron 子进程未在清理期限内退出。')); } else finish(); }, 250); }, 2000); };
    const cleanup = () => { clearTimeout(timer); clearTimeout(graceTimer); dependencies.signal?.removeEventListener('abort', cancel); process.removeListener('SIGINT', cancel); process.removeListener('SIGTERM', cancel); };
    process.once('SIGINT', cancel); process.once('SIGTERM', cancel); dependencies.signal?.addEventListener('abort', cancel, { once: true });
    child.once('error', () => { cleanup(); reject(new Error('Electron 子进程未能启动。\n' + buildHint)); });
    child.once('close', (code, signal) => { closed = true; if (cleanupExpired) { cleanup(); reject(new Error('Windows 所属进程清理超时，无法确认正常退出。')); return; } result = cancelling && !supervised ? 143 : code ?? (signal === 'SIGINT' ? 130 : 143); if (!cancelling || supervised) finish(); });
    if (dependencies.signal?.aborted) cancel();
  });
}
if (require.main === module) main().then(code => { process.exitCode = code; }).catch(error => { console.error(error.message?.includes(buildHint) ? error.message : '桌面启动预检失败；构建未准备完整。\n' + buildHint); process.exitCode = 1; });
module.exports = { main };
