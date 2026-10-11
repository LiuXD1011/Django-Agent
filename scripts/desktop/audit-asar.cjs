'use strict';
// Build-only inspection of the actual electron-builder output. No application launch.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { createRequire } = require('node:module');

const assets = ['main.cjs', 'runtime.cjs', 'ipc.cjs', 'preload.cjs', 'protocol.cjs',
  'langfuse.cjs', 'loading.html', 'package.json', 'LICENSE', 'icon.png'];
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');
function rejectLinks(target) {
  for (let candidate = path.resolve(target);;) {
    if (fs.existsSync(candidate)) assert.equal(fs.lstatSync(candidate).isSymbolicLink(), false, 'Linked audit path refused');
    const parent = path.dirname(candidate); if (parent === candidate) break; candidate = parent;
  }
}
function inventory(directory) {
  rejectLinks(directory); assert.ok(fs.statSync(directory).isDirectory(), 'Runtime inventory directory missing');
  const files = {};
  function visit(folder) {
    for (const item of fs.readdirSync(folder, { withFileTypes: true })) {
      const target = path.join(folder, item.name); rejectLinks(target);
      if (item.isDirectory()) visit(target);
      else {
        assert.ok(item.isFile(), 'Unexpected runtime inventory entry');
        const name = path.relative(directory, target).split(path.sep).join('/');
        if (name !== 'source-manifest.json') files[name] = sha256(fs.readFileSync(target));
      }
    }
  }
  visit(directory); return files;
}
function auditAsar(app, asar = createRequire(path.join(path.resolve(app), 'package.json'))('@electron/asar')) {
  app = path.resolve(app); rejectLinks(app);
  const metadata = JSON.parse(fs.readFileSync(path.join(app, 'package.json'), 'utf8'));
  const output = metadata.build?.directories?.output;
  assert.ok(typeof output === 'string' && !path.isAbsolute(output) && !output.split(/[\\/]/).includes('..'), 'Invalid output directory');
  assert.deepEqual([...metadata.build.files].sort(), [...assets].sort(), 'Application asset allowlist changed');
  const resources = path.join(app, output, 'win-unpacked', 'resources');
  const archive = path.join(resources, 'app.asar'); rejectLinks(archive);
  asar.uncache(archive);
  const entries = asar.listPackage(archive, { isPack: false }).map(name => name.replace(/^[\\/]/, ''));
  assert.deepEqual([...entries].sort(), [...assets].sort(), 'ASAR asset allowlist differs');
  const packed = JSON.parse(asar.extractFile(archive, 'package.json').toString('utf8'));
  const cleaned = { ...metadata };
  for (const name of ['build', 'scripts', 'devDependencies']) delete cleaned[name];
  assert.deepEqual(packed, cleaned, 'Packaged metadata differs from documented upstream cleanup');
  const hashes = {};
  for (const name of assets) {
    const bytes = asar.extractFile(archive, name);
    if (name !== 'package.json') assert.ok(bytes.equals(fs.readFileSync(path.join(app, name))), `ASAR bytes differ: ${name}`);
    hashes[name] = sha256(bytes);
  }
  const payload = path.join(app, 'payload'), runtime = path.join(resources, 'runtime');
  const manifestPath = path.join(payload, 'source-manifest.json'); rejectLinks(manifestPath);
  const manifestBytes = fs.readFileSync(manifestPath), manifest = JSON.parse(manifestBytes);
  assert.equal(manifest.format, 'marlin-electron-payload-v1', 'Runtime inventory manifest format');
  assert.ok(manifest.files && typeof manifest.files === 'object' && !Array.isArray(manifest.files), 'Runtime inventory manifest files');
  assert.deepEqual(inventory(payload), manifest.files, 'Staged runtime inventory changed');
  assert.deepEqual(inventory(runtime), manifest.files, 'Packaged runtime inventory differs (added/deleted/changed files)');
  assert.ok(fs.readFileSync(path.join(runtime, 'source-manifest.json')).equals(manifestBytes), 'Packaged runtime manifest bytes differ');
  return { format: 'marlin-asar-audit-v1', state: 'verified', asar_entries: entries,
    asar_sha256: sha256(fs.readFileSync(archive)), asset_sha256: hashes, runtime_files: Object.keys(manifest.files).length,
    runtime_manifest_sha256: sha256(manifestBytes), staged_asar_code_files_match: true,
    package_metadata_matches_documented_cleanup: true, complete_runtime_inventory_matches: true,
    installer_executed: false, gui_started: false };
}
if (require.main === module) {
  try {
    const args = process.argv.slice(2);
    assert.equal(args.length, 4, 'Use --app <staged app> --report <report>');
    assert.equal(args[0], '--app'); assert.equal(args[2], '--report'); rejectLinks(args[3]);
    const report = auditAsar(args[1]);
    fs.writeFileSync(args[3], JSON.stringify(report, null, 2) + '\n');
    console.log('ASAR_BOUNDARY_VERIFIED');
  } catch (error) { console.error(`ASAR_AUDIT_ERROR=${error.message}`); process.exitCode = 1; }
}
module.exports = { auditAsar, inventory };
