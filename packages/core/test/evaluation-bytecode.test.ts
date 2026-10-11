import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { isAbsolute, join, relative } from 'node:path';
import { test } from 'node:test';
import { RagasBridge } from '../src/evaluation/ragas.js';

// Windows acceptance supplies MARLIN_TEST_PYTHON from an independent owned helper copy.
// No stage/runtime or model credentials are required by this protocol fixture.
test('Ragas helper imports preserve worker inventory and explicitly disable bytecode writes', async () => {
  const pythonExecutable = process.env.MARLIN_TEST_PYTHON ?? (process.platform === 'win32' ? '' : '/usr/bin/python3');
  assert.ok(isAbsolute(pythonExecutable), 'An absolute trusted Python executable is required; on Windows set MARLIN_TEST_PYTHON to an owned helper copy');
  const root = mkdtempSync(join(tmpdir(), 'marlin-evaluation-bytecode-'));
  const workerPath = join(root, 'bytecode fixture.py');
  writeFileSync(join(root, 'owned_fixture_module.py'), 'VALUE = "actual import 中文 😀"\n');
  writeFileSync(workerPath, `import json,sys,pathlib\nsys.path.insert(0,str(pathlib.Path(__file__).parent))\nimport owned_fixture_module\nr=json.loads(sys.stdin.readline())\nprint(json.dumps({'protocol':1,'id':r['id'],'type':'result','operation':'capabilities','result':{'ragas_version':'0.4.3','django_imported':False,'dont_write_bytecode':sys.dont_write_bytecode,'module_value':owned_fixture_module.VALUE}},ensure_ascii=False),flush=True)\n`);
  const inventory = (directory: string): { path: string; sha256: string }[] => readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const file = join(directory, entry.name);
    return entry.isDirectory() ? inventory(file) : [{ path: relative(root, file), sha256: createHash('sha256').update(readFileSync(file)).digest('hex') }];
  }).sort((left, right) => left.path.localeCompare(right.path));
  const before = inventory(root), bridge = new RagasBridge({ pythonExecutable, workerPath });
  try {
    const capabilities = await bridge.capabilities({ timeoutMs: 10000 });
    assert.equal(capabilities.module_value, 'actual import 中文 😀', 'A real Python import must occur, not a spawn/mock assertion');
    assert.deepEqual(inventory(root), before, 'Imports must neither add pyc files nor mutate existing worker files');
    assert.equal(capabilities.dont_write_bytecode, true, 'The owned runtime must explicitly disable bytecode writes');
  } finally { await bridge.close(); rmSync(root, { recursive: true, force: true }); }
});
