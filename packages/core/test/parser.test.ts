import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync } from 'node:fs';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync, spawn } from 'node:child_process';
import { setTimeout as delay } from 'node:timers/promises';
import test from 'node:test';

const root = resolve('../..');
const workerPath = join(root, 'workers/document/worker.py');
const pythonExecutable = process.env.MARLIN_TEST_PYTHON ?? spawnSync('python', ['-c', 'import sys; print(sys.executable)'], { encoding: 'utf8' }).stdout.trim();
const fixture = join(root, 'workers/document/tests/fixtures');
const sha = (data: string | Buffer) => createHash('sha256').update(data).digest('hex');
async function parser(options: Record<string, unknown> = {}) {
  assert.ok(existsSync(resolve('src/documents/parser.ts')), 'independent parser bridge must exist');
  const { DocumentParser } = await import('../src/documents/parser.js');
  return new DocumentParser({ pythonExecutable, workerPath, ...options });
}
async function input(name: string) {
  const path = join(fixture, name); const data = await readFile(path);
  return { path, name, sha256: sha(data), size_bytes: data.length };
}
async function temporary(fn: (dir: string) => Promise<void>) {
  const dir = await mkdtemp(join(tmpdir(), 'marlin-parser-test-'));
  try { await fn(dir); } finally { await rm(dir, { recursive: true, force: true }); }
}
async function fake(dir: string, source: string) {
  const path = join(dir, 'worker.py'); await writeFile(path, source); return path;
}
const prefix = 'import sys,json,time,os\nr=json.loads(sys.stdin.readline())\n';
// The setup watchdog stays real while a test controls only the parser deadline.
const realTimeout = setTimeout, clearRealTimeout = clearTimeout;
async function waitForHandshake(ready: Promise<void>, maximumMs = 1000): Promise<void> {
  let timer!: ReturnType<typeof setTimeout>;
  try { await Promise.race([ready, new Promise<void>((_resolve, reject) => { timer = realTimeout(() => reject(new Error('actual worker handshake did not arrive before the setup deadline')), maximumMs); })]); }
  finally { clearRealTimeout(timer); }
}

test('parser bridge exists and reports real capabilities', async () => {
  const p = await parser(); const caps = await p.capabilities();
  assert.equal((caps.format_status as Record<string, boolean>).txt, true); assert.equal(caps.ocr_available, false);
});
test('real parser verifies unicode ranges and SVG artifacts', async () => {
  await temporary(async dir => {
    const p = await parser(); const r = await p.parse({ input: await input('unicode.txt'), artifact_dir: dir });
    assert.equal(r.document.canonical_text, '季度收入😀\nQ1 100\n');
    assert.equal(r.blocks[0]?.kind, 'text');
    if (r.blocks[0]?.kind === 'text') assert.equal(r.blocks[0].canonical_range.end, 13);
  });
  await temporary(async dir => {
    const p = await parser(); const r = await p.parse({ input: await input('image.svg'), artifact_dir: dir });
    const b = r.blocks[0]; assert.equal(b?.kind, 'image');
    if (b?.kind === 'image') { assert.equal(b.mime_type, 'image/png'); assert.equal(b.original_mime_type, 'image/svg+xml'); assert.ok((await readFile(join(dir,b.artifact_path))).subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10]))); }
  });
});
test('owned subprocess timeout, cancellation and crash isolate subsequent requests', async () => {
  await temporary(async dir => {
    const stalled = await fake(dir, prefix + "time.sleep(30)\n");
    const p = await parser({ workerPath: stalled, timeoutMs: 80 });
    const started = Date.now();
    await assert.rejects(p.capabilities(), { code: 'parser_timeout' });
    assert.ok(Date.now() - started < 600, 'the real startup-inclusive timeout must settle without waiting for worker startup');
    const controller = new AbortController(); const cancelled = p.capabilities({ signal: controller.signal, timeoutMs: 1000 });
    setTimeout(() => controller.abort(), 30); await assert.rejects(cancelled, { code: 'parser_cancelled' });
    const unrelated = spawn(pythonExecutable,['-c','import time; time.sleep(30)']);
    try { await assert.rejects(p.capabilities(), { code: 'parser_timeout' }); assert.equal(unrelated.exitCode,null); } finally { unrelated.kill('SIGKILL'); }
    await writeFile(stalled, prefix + 'os._exit(17)\n'); await assert.rejects(p.capabilities({ timeoutMs: 1000 }), { code: 'parser_crashed' });
    await writeFile(stalled, prefix + 'print(json.dumps({"protocol":1,"id":r["id"],"type":"result","operation":"capabilities","result":{"recovered":True}}))\n');
    assert.equal((await p.capabilities({ timeoutMs: 1000 })).recovered,true);
  });
});
test('bridge rejects invalid protocol, mismatch IDs, duplicate results and oversized streams', async () => {
  await temporary(async dir => {
    const path = await fake(dir, prefix + 'print("not-json")\n'); const p = await parser({workerPath:path,maxOutputBytes:1024});
    await assert.rejects(p.capabilities(), { code: 'parser_protocol_invalid' });
    await writeFile(path,prefix + 'print(json.dumps({"protocol":2,"id":r["id"],"type":"result","operation":"capabilities","result":{}}))\n'); await assert.rejects(p.capabilities(), { code:'parser_protocol_invalid' });
    await writeFile(path,prefix + 'print(json.dumps({"protocol":1,"id":"wrong","type":"result","operation":"capabilities","result":{}}))\n'); await assert.rejects(p.capabilities(), { code:'parser_protocol_invalid' });
    await writeFile(path,prefix + 'm={"protocol":1,"id":r["id"],"type":"result","operation":"capabilities","result":{}}\nprint(json.dumps(m)); print(json.dumps(m))\n'); await assert.rejects(p.capabilities(),{ code:'parser_protocol_invalid' });
    await writeFile(path,prefix + 'print("x"*2048)\n'); await assert.rejects(p.capabilities(), { code:'parser_output_limit' });
  });
});
test('bridge rejects input mismatch, worker errors, artifact traversal, hash mismatch and symlinks', async () => {
  await temporary(async dir => {
    const p = await parser(); const i=await input('unicode.txt');
    await assert.rejects(p.parse({input:{...i,sha256:'0'.repeat(64)},artifact_dir:dir}),{code:'input_hash_mismatch'});
    await assert.rejects(p.parse({input:await input('bad.pdf'),artifact_dir:dir}),{code:'parse_failed'});
    for (const artifactPath of ['../outside.png','/tmp/outside.png','link.png','wrong.png']) {
      const script = prefix + `from pathlib import Path\nimport hashlib\nroot=Path(r['artifact_dir'])\nroot.joinpath('wrong.png').write_bytes(b'wrong')\nif ${JSON.stringify(artifactPath)} == 'link.png': root.joinpath('link.png').symlink_to(r['input']['path'])\nb={'id':'b0','kind':'image','block_index':0,'artifact_path':${JSON.stringify(artifactPath)},'sha256':'0'*64,'original_mime_type':'image/png','mime_type':'image/png','width':96,'height':96,'provenance':{},'metadata':{}}\nd={'name':r['input']['name'],'input_sha256':r['input']['sha256'],'parser_version':'1','canonicalization_version':'blocks-double-newline-v1','offset_unit':'unicode_code_point','canonical_text':'','canonical_sha256':hashlib.sha256(b'').hexdigest()}\nprint(json.dumps({'protocol':1,'id':r['id'],'type':'result','operation':'parse','result':{'document':d,'blocks':[b],'warnings':[],'diagnostics':{}}}))\n`;
      const path=await fake(dir,script); const bad=await parser({workerPath:path}); await assert.rejects(bad.parse({input:i,artifact_dir:dir}),{code:'parser_artifact_invalid'});
    }
  });
});
test('already cancelled requests never spawn',async()=> {
  const p=await parser({pythonExecutable:'/does/not/exist'}); const controller=new AbortController();controller.abort();
  await assert.rejects(p.capabilities({signal:controller.signal}),{code:'parser_cancelled'});
});
test('bridge rejects start failures and excessive request/input sizes',async()=> {
  const missing=await parser({pythonExecutable:'/does/not/exist'});
  await assert.rejects(missing.capabilities(),{code:'parser_start_failed'});
  const limited=await parser({maxRequestBytes:1}); await assert.rejects(limited.capabilities(),{code:'parser_request_limit'});
  await temporary(async dir=> {
    const limitedInput=await parser({maxInputBytes:1}); await assert.rejects(limitedInput.parse({input:await input('unicode.txt'),artifact_dir:dir}),{code:'input_limit_exceeded'});
  });
});
test('stderr is bounded and never included in public parser errors',async()=> {
  await temporary(async dir=> {
    const path=await fake(dir,prefix+'sys.stderr.write("sensitive-value"*2048)\nos._exit(2)\n');const p=await parser({workerPath:path,maxOutputBytes:512});
    await assert.rejects(p.capabilities(),(error:unknown)=> {
      assert.equal((error as {code:string}).code,'parser_output_limit');assert.ok(!(error as Error).message.includes('sensitive-value'));return true;
    });
  });
});

async function alive(pid: number): Promise<boolean> {
  try { process.kill(pid, 0); } catch { return false; }
  if (process.platform === 'linux') {
    const state = await readFile(`/proc/${pid}/stat`, 'utf8').catch(() => '');
    return Boolean(state) && state.slice(state.lastIndexOf(')') + 2).split(' ')[0] !== 'Z';
  }
  return true;
}
async function eventually(predicate: () => Promise<boolean>, maximumMs = 1000, controlledClock = false): Promise<void> {
  const deadline = Date.now() + maximumMs;
  while (!(await predicate())) {
    assert.ok(Date.now() < deadline, 'owned subprocess state must converge before deadline');
    if (controlledClock) await new Promise<void>(resolve => setImmediate(resolve));
    else await delay(10);
  }
}
for (const operation of ['timeout', 'cancel'] as const) {
  test(`${operation} settles promptly after worker exits with a descendant retaining output pipes`, async context => {
    await temporary(async dir => {
      const marker = join(dir, 'processes.json');
      const source = prefix + `import subprocess\nfrom pathlib import Path\np=subprocess.Popen([sys.executable,'-c','import time; time.sleep(2)'])\nPath(${JSON.stringify(marker)}).write_text(json.dumps({'worker':os.getpid(),'descendant':p.pid}))\nprint(json.dumps({'protocol':1,'id':r['id'],'type':'progress','stage':'fixture_ready','progress':0.5}),flush=True)\nos._exit(0)\n`;
      const path = await fake(dir, source); const p = await parser({ workerPath: path });
      const unrelated = spawn(pythonExecutable, ['-c', 'import time; time.sleep(30)']);
      const controller = new AbortController();
      // Freeze only the deadline until a real worker/descendant handshake proves
      // the retained-pipe condition. The separate real 80 ms startup budget test
      // must also pass when startup is too slow for this worker to have spawned.
      const controlledClock = operation === 'timeout';
      if (controlledClock) context.mock.timers.enable({ apis: ['setTimeout'] });
      let ready!: () => void, settled = false;
      const started = new Promise<void>(resolve => ready = resolve);
      const result = p.capabilities({ timeoutMs: controlledClock ? 80 : 5000, signal: controller.signal, onProgress: () => ready() });
      void result.finally(() => { settled = true; }).catch(() => {});
      // Attach a rejection handler before awaiting process markers.
      const rejected = assert.rejects(result, { code: operation === 'timeout' ? 'parser_timeout' : 'parser_cancelled' });
      void rejected.catch(() => {});
      try {
        await waitForHandshake(started);
        assert.ok(existsSync(marker));
        const ids = JSON.parse(await readFile(marker, 'utf8')) as { worker: number; descendant: number };
        await eventually(async () => !(await alive(ids.worker)), 1000, controlledClock);
        assert.ok(await alive(ids.descendant));
        if (controlledClock) { context.mock.timers.tick(79); assert.equal(settled, false, 'the configured deadline must not fire early'); }
        const cancellationStarted = Date.now();
        if (controlledClock) context.mock.timers.tick(1);
        else controller.abort();
        await rejected;
        const elapsed = Date.now() - cancellationStarted;
        assert.ok(elapsed < 600, `settled after ${elapsed}ms while descendant held pipes`);
        await eventually(async () => !(await alive(ids.descendant)), 1000, controlledClock);
        assert.equal(unrelated.exitCode, null);
        assert.ok(unrelated.pid && await alive(unrelated.pid), 'unrelated process must remain alive');
      } finally {
        controller.abort(); unrelated.kill('SIGKILL'); await rejected.catch(() => {});
      }
    });
  });
}

test('cancel rejection waits until its owned supervisor has been reaped before an application may close storage', async () => {
  await temporary(async dir => {
    const marker = join(dir, 'supervisor.json');
    const path = await fake(dir, prefix + `from pathlib import Path\nPath(${JSON.stringify(marker)}).write_text(json.dumps({'supervisor':os.getppid()}))\ntime.sleep(30)\n`);
    const p = await parser({ workerPath: path });
    const controller = new AbortController();
    const call = p.capabilities({ signal: controller.signal, timeoutMs: 5000 });
    const rejected = assert.rejects(call, { code: 'parser_cancelled' });
    await eventually(async () => existsSync(marker));
    const { supervisor } = JSON.parse(await readFile(marker, 'utf8')) as { supervisor: number };
    controller.abort();
    await rejected;
    assert.throws(() => process.kill(supervisor, 0), { code: 'ESRCH' }, 'the parser promise must not reject while its supervisor still exists');
  });
});

test('malformed output without a final newline still settles after the process close event', { timeout: 5000 }, async context => {
  await temporary(async dir => {
    // Test EOF protocol settlement independently of interpreter startup. Keep
    // the configured 500 ms timer, and require a real <500 ms close after ready.
    context.mock.timers.enable({ apis: ['setTimeout'] });
    const progress = 'print(json.dumps({"protocol":1,"id":r["id"],"type":"progress","stage":"fixture_ready","progress":0.5}),flush=True)\n';
    const path = await fake(dir, prefix + progress + 'sys.stdout.write("invalid-without-newline")\n');
    const p = await parser({ workerPath: path, timeoutMs: 500 });
    const rejectsAfterReady = async (message?: string) => {
      let ready!: () => void, readyAt = 0;
      const handshake = new Promise<void>(resolve => ready = resolve);
      const controller = new AbortController();
      const result = p.capabilities({ signal: controller.signal, onProgress: () => { readyAt = Date.now(); ready(); } });
      const rejected = assert.rejects(result, { code: 'parser_protocol_invalid' }, message); void rejected.catch(() => {});
      try {
        await waitForHandshake(handshake); await rejected;
        assert.ok(Date.now() - readyAt < 500, 'malformed EOF must settle promptly after the real worker starts');
      } finally { controller.abort(); await result.catch(() => {}); }
    };
    await rejectsAfterReady();
    await writeFile(path, prefix + progress + 'print(json.dumps({"protocol":1,"id":r["id"],"type":"result","operation":"capabilities","result":{}}))\nsys.stdout.write("extra-without-newline")\n');
    await rejectsAfterReady('trailing corruption must not be accepted just because a result arrived first');
  });
});
