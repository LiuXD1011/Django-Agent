import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync } from 'node:fs';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { promisify } from 'node:util';
import test from 'node:test';

const execute = promisify(execFile);
test('compiled JS starts its sibling Worker without tsx from a Chinese space directory', { timeout: 90000 }, async context => {
  assert.ok(existsSync(resolve('src/documents/chunking-workers.ts')), 'the pure chunking Worker bridge is not implemented');
  const dir = await mkdtemp(join(process.env.MARLIN_TEST_COMPILED_ROOT || tmpdir(), 'Marlin 分块 Worker 编译 '));
  try {
    const output = join(dir, 'dist');
    const project = join(dir, 'tsconfig.json');
    // Compile the complete computational import graph with the real core options.
    // Unrelated application modules do not belong to this isolated execution proof.
    await writeFile(project, JSON.stringify({ extends: resolve('tsconfig.json'),
      compilerOptions: { outDir: output, declaration: false, sourceMap: false, typeRoots: [resolve('node_modules/@types')] },
      include: [resolve('src/documents/chunking-workers.ts'), resolve('src/documents/chunking-worker.ts')] }));
    try {
      await execute(process.execPath, [resolve('node_modules/typescript/lib/tsc.js'), '-p', project],
        { timeout: 60000, maxBuffer: 1024 * 1024 });
    } catch (error) {
      const failure = error as { code?: unknown; signal?: unknown; killed?: unknown; stdout?: unknown; stderr?: unknown };
      context.diagnostic(JSON.stringify({ phase: 'compile', code: failure.code, signal: failure.signal,
        killed: failure.killed, stdout: failure.stdout, stderr: failure.stderr }));
      throw error;
    }
    const compiledHashes: Record<string, string> = {};
    for (const relative of ['documents/chunking-workers.js', 'documents/chunking-worker.js', 'documents/chunker.js', 'knowledge/config.js', 'errors.js'])
      compiledHashes[relative] = createHash('sha256').update(await readFile(join(output, relative))).digest('hex');
    context.diagnostic(JSON.stringify({ compiledHashes }));
    await writeFile(join(dir, 'package.json'), '{"type":"module"}\n');
    const script = join(dir, 'compiled-smoke.mjs');
    await writeFile(script,
      "import assert from 'node:assert/strict';\n" +
      "import { ChunkingWorkers } from './dist/documents/chunking-workers.js';\n" +
      "assert.deepEqual(process.execArgv,[]);\n" +
      "const content='季度😀收入100\\n'.repeat(200),parsed={document:{name:'编译.txt',input_sha256:'',parser_version:'fixture',canonicalization_version:'blocks-double-newline-v1',offset_unit:'unicode_code_point',canonical_text:content,canonical_sha256:''},blocks:[{id:'b0',kind:'text',block_index:0,block_type:'paragraph',text:content,canonical_range:{start:0,end:Array.from(content).length},provenance:{},metadata:{}}],warnings:[],diagnostics:{}};\n" +
      "const workers=new ChunkingWorkers();let started=0;try{const result=await workers.split(parsed,{}, {title:'编译😀',onProgress:()=>started++});assert.equal(started,1);assert.equal(result.parents.map(p=>p.content).join(''),content);assert.ok(result.children.length>0);for(const c of result.children)assert.equal(c.content,Array.from(content).slice(c.start_at,c.end_at).join(''));console.log(JSON.stringify({platform:process.platform,node:process.version,parents:result.parents.length,children:result.children.length,started,compiled:true}));}finally{await workers.close();}\n");
    const { stdout, stderr } = await execute(process.execPath, [script], { cwd: dir, timeout: 10000, maxBuffer: 1024 * 1024 });
    assert.equal(stderr, '');
    const result = JSON.parse(stdout);
    assert.equal(result.compiled, true); assert.equal(result.started, 1);
    assert.ok(result.parents > 0 && result.children > 0);
    context.diagnostic(JSON.stringify({ platform: process.platform, ...result }));
    if (process.env.MARLIN_TEST_WINDOWS_NODE) {
      assert.equal(process.platform, 'linux', 'this explicit Windows interoperability check requires WSL');
      const executable = process.env.MARLIN_TEST_WINDOWS_NODE;
      const version = await execute(executable, ['--version'], { timeout: 10000 });
      assert.equal(version.stdout.trim(), 'v22.23.2');
      const { stdout: windowsPath } = await execute('wslpath', ['-w', script]);
      const windows = await execute(executable, [windowsPath.trim()], { cwd: dir, timeout: 10000, maxBuffer: 1024 * 1024 });
      assert.equal(windows.stderr, '');
      const windowsResult = JSON.parse(windows.stdout);
      assert.equal(windowsResult.platform, 'win32');
      assert.equal(windowsResult.compiled, true); assert.equal(windowsResult.started, 1);
      assert.equal(windowsResult.parents, result.parents); assert.equal(windowsResult.children, result.children);
      context.diagnostic(JSON.stringify({ platform: 'win32', ...windowsResult }));
    }
  } finally { await rm(dir, { recursive: true, force: true }); }
});
