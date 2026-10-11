import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve, win32 } from 'node:path';
import test from 'node:test';
import { DocumentParser } from '../src/documents/parser.js';

const pythonExecutable = process.env.MARLIN_TEST_PYTHON ?? spawnSync('python', ['-c', 'import sys; print(sys.executable)'], { encoding: 'utf8' }).stdout.trim();

// Embeddable Windows Python could not locate Cairo DLLs after desktop removed PATH.
test('real parser subprocess receives UTF-8 and trusted PATH without developer keys or Python import overrides', async () => {
  const root = await mkdtemp(join(tmpdir(), 'marlin-python-env-海盐-'));
  const keys = ['PATH', 'PYTHONUTF8', 'PYTHONPATH', 'PYTHONHOME', 'DJANGO_SETTINGS_MODULE', 'OPENAI_API_KEY', 'DATABASE_URL', 'CAIROCFFI_DLL_DIRECTORIES'];
  const saved = Object.fromEntries(keys.map(key => [key, process.env[key]]));
  try {
    const workerPath = join(root, '环境诊断.py');
    await writeFile(workerPath, `import sys,json,os\nr=json.loads(sys.stdin.readline())\nresult={'utf8':sys.flags.utf8_mode,'no_user_site':sys.flags.no_user_site,'path':os.environ.get('PATH'),'private':any(k in os.environ for k in ['OPENAI_API_KEY','DATABASE_URL']),'overrides':any(k in os.environ for k in ['PYTHONHOME','PYTHONPATH','DJANGO_SETTINGS_MODULE','CAIROCFFI_DLL_DIRECTORIES']),'text':'海盐🙂'}\nprint(json.dumps({'protocol':1,'id':r['id'],'type':'result','operation':'capabilities','result':result},ensure_ascii=False))\n`, 'utf8');
    for (const key of keys) process.env[key] = key === 'PYTHONUTF8' ? '0' : 'fixture-untrusted-value';
    const parser = new DocumentParser({ pythonExecutable, workerPath });
    const result = await parser.capabilities();
    assert.equal(result.private, false, 'private developer environment must never enter the real parser worker');
    assert.equal(result.overrides, false); assert.equal(result.utf8, 1); assert.equal(result.no_user_site, 1); assert.equal(result.text, '海盐🙂');
    if (process.platform === 'win32') assert.equal(result.path, `${win32.dirname(pythonExecutable)};${win32.join(process.env.SystemRoot!, 'System32')}`);
    else assert.equal(result.path, `${dirname(pythonExecutable)}:/usr/bin:/bin`);
  } finally {
    for (const [key, value] of Object.entries(saved)) { if (value === undefined) delete process.env[key]; else process.env[key] = value; }
    await rm(root, { recursive: true, force: true });
  }
});

test('Windows Python DLL PATH uses win32 paths, spaces and Unicode and ignores all developer PATH casing', async () => {
  const { pythonWorkerEnv } = await import('../src/tools/python-env.js');
  const executable = 'C:\\Program Files\\Marlin 数据\\runtime\\python\\python.exe';
  const env = pythonWorkerEnv(executable, { PATH: 'C:\\private-one', Path: 'C:\\private-two', SYSTEMROOT: 'D:\\Windows', temp: 'D:\\临时 文件', PYTHONPATH: 'private', PYTHONHOME: 'private', DJANGO_SETTINGS_MODULE: 'private', OPENAI_API_KEY: 'private', CAIROCFFI_DLL_DIRECTORIES: 'C:\\private-dlls' }, 'win32');
  assert.equal(env.PATH, 'C:\\Program Files\\Marlin 数据\\runtime\\python;D:\\Windows\\System32');
  assert.equal(env.SystemRoot, 'D:\\Windows'); assert.equal(env.TEMP, 'D:\\临时 文件');
  assert.equal(env.PYTHONUTF8, '1'); assert.equal(env.PYTHONIOENCODING, 'utf-8'); assert.equal(env.PYTHONNOUSERSITE, '1');
  assert.equal(Object.keys(env).filter(key => key.toLowerCase() === 'path').length, 1);
  for (const key of ['PYTHONPATH', 'PYTHONHOME', 'DJANGO_SETTINGS_MODULE', 'OPENAI_API_KEY', 'CAIROCFFI_DLL_DIRECTORIES']) assert.equal(Object.hasOwn(env, key), false);
  const unc = pythonWorkerEnv('\\\\server\\share\\应用\\python.exe', { SystemRoot: 'C:/Windows' }, 'win32');
  assert.equal(unc.PATH, '\\\\server\\share\\应用;C:\\Windows\\System32');
  for (const [python, source] of [
    ['python.exe', { SystemRoot: 'C:\\Windows' }], ['\\python.exe', { SystemRoot: 'C:\\Windows' }],
    [executable, {}], [executable, { SystemRoot: 'Windows' }],
    ['C:\\private;D:\\injected\\python.exe', { SystemRoot: 'C:\\Windows' }],
    [executable, { SystemRoot: 'C:\\Windows;D:\\injected' }],
  ] as const) assert.throws(() => pythonWorkerEnv(python, source, 'win32'), /环境/);
});

test('real SVG parser still creates a verified PNG under the controlled Linux Python environment', async () => {
  const root = await mkdtemp(join(tmpdir(), 'marlin-python-env-svg-'));
  try {
    const { createHash } = await import('node:crypto');
    const { readFile } = await import('node:fs/promises');
    const path = resolve('../../workers/document/tests/fixtures/image.svg'), bytes = await readFile(path);
    const parser = new DocumentParser({ pythonExecutable, workerPath: resolve('../../workers/document/worker.py') });
    const parsed = await parser.parse({ input: { path, name: 'image.svg', size_bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex') }, artifact_dir: root });
    const image = parsed.blocks[0]; assert.equal(image?.kind, 'image');
    if (image?.kind === 'image') {
      assert.equal(image.mime_type, 'image/png'); assert.equal(image.original_mime_type, 'image/svg+xml');
      assert.ok((await readFile(join(root, image.artifact_path))).subarray(0, 8).equals(Buffer.from([137,80,78,71,13,10,26,10])));
    }
  } finally { await rm(root, { recursive: true, force: true }); }
});
