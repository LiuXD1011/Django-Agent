import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync } from 'node:fs';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { Worker } from 'node:worker_threads';
import test from 'node:test';
import type { JsonObject, ParsedDocument } from '../src/contracts.js';
import { splitDocument, type ChunkingResult } from '../src/documents/chunker.js';

function document(content: string): ParsedDocument {
  const hash = createHash('sha256').update(content).digest('hex');
  return {
    document: { name: '真实分块.txt', input_sha256: hash, parser_version: 'worker-fixture',
      canonicalization_version: 'blocks-double-newline-v1', offset_unit: 'unicode_code_point',
      canonical_text: content, canonical_sha256: hash },
    blocks: [{ id: 'b0', kind: 'text', block_index: 0, block_type: 'paragraph', text: content,
      canonical_range: { start: 0, end: Array.from(content).length },
      provenance: { source_ref: '真实来源😀', page_index: 0 }, metadata: { record_group: '季度' } }],
    warnings: [], diagnostics: {},
  };
}
const content = Array.from({ length: 160 }, (_, i) => '季度😀' + i + ' 收入100，利润20。\n').join('');
function stable(result: ChunkingResult) {
  const { duration: _seconds, duration_ms: _ms, ...diagnostics } = result.diagnostics;
  return { ...result, diagnostics };
}
async function client(options: Record<string, unknown> = {}) {
  assert.ok(existsSync(resolve('src/documents/chunking-workers.ts')), 'the pure chunking Worker bridge is not implemented');
  const { ChunkingWorkers } = await import('../src/documents/chunking-workers.js');
  return new ChunkingWorkers(options);
}
async function fixture(source: string, run: (url: URL) => Promise<void>) {
  const dir = await mkdtemp(join(tmpdir(), 'marlin-chunking-协议 '));
  const path = join(dir, 'worker.mjs');
  try { await writeFile(path, source); await run(pathToFileURL(path)); }
  finally { await rm(dir, { recursive: true, force: true }); }
}
const fixturePrefix = "import { parentPort, workerData } from 'node:worker_threads';\nconst r=workerData;\n";
const emptyResult = "{parents:[],children:[],diagnostics:{}}";

for (const strategy of ['auto', 'recursive', 'heading', 'layout', 'record']) {
  test('real Worker preserves ' + strategy + ' chunks and complete Unicode parent-child sources', async () => {
    const workers = await client(), parsed = document(content), config = { strategy };
    try {
      const actual = await workers.split(parsed, config, { title: '报告😀' });
      assert.deepEqual(stable(actual), stable(await splitDocument(parsed, config, { title: '报告😀' })));
      const source = Array.from(content);
      assert.equal(actual.parents.map(chunk => chunk.content).join(''), content);
      for (const chunk of actual.children) {
        assert.equal(chunk.content, source.slice(chunk.start_at, chunk.end_at).join(''));
        const parent = actual.parents[chunk.context_parent_index!];
        assert.ok(parent && parent.start_at <= chunk.start_at && chunk.end_at <= parent.end_at);
        assert.ok(Array.isArray(chunk.metadata.source_refs));
      }
    } finally { await workers.close(); }
  });
}

test('real Worker keeps empty input empty without claiming generated text', async () => {
  const workers = await client();
  try {
    for (const value of ['', ' \n\t']) {
      const result = await workers.split(document(value), {}, { title: '空正文' });
      assert.deepEqual(result.parents, []); assert.deepEqual(result.children, []);
      assert.deepEqual(result.diagnostics.fallback_chain, []);
    }
  } finally { await workers.close(); }
});

test('real Worker preserves a genuine heading validation fallback to recursive', async () => {
  const workers = await client();
  const parsed = document(Array.from({ length: 12 }, (_, i) => '# A' + i + '\n收入😀abcd\n\n').join(''));
  const config = { strategy: 'heading', enable_parent_child: false, chunk_size: 128, chunk_overlap: 0, token_limit: 10 };
  try {
    const expected = await splitDocument(parsed, config, { title: '标题' });
    assert.equal(expected.diagnostics.selected_strategy, 'recursive');
    assert.ok((expected.diagnostics.fallback_chain as unknown[]).length > 0, 'the fixture must exercise a real fallback');
    assert.deepEqual(stable(await workers.split(parsed, config, { title: '标题' })), stable(expected));
  } finally { await workers.close(); }
});

test('semantic callbacks and custom token counters retain their original in-process path', async () => {
  const workers = await client();
  let calls = 0, progress = 0;
  const parsed = document(content);
  try {
    const custom = await workers.split(parsed, {}, {
      title: '自定义', tokenCounter: text => { calls++; return Array.from(text).length; },
      onProgress: () => progress++,
    });
    assert.ok(calls > 0); assert.equal(custom.diagnostics.token_counter_source, 'custom');
    let embedded = 0;
    const config = { strategy: 'semantic' };
    const options = { title: '语义', semanticDimension: 2, semanticSignature: 'fixture',
      semanticEmbed: async (texts: string[]) => { embedded++; return texts.map(() => [1, 0]); },
      onProgress: () => progress++ };
    assert.equal((await workers.split(parsed, config, options)).diagnostics.selected_strategy, 'semantic');
    assert.equal(embedded, 1); assert.equal(progress, 0, 'direct callbacks must not be serialized or impersonate a Worker');
    const fallback = await workers.split(parsed, config, { title: '未配置' });
    assert.equal((fallback.diagnostics.fallback_chain as JsonObject[])[0]?.reason, 'missing_embedding_callable');
  } finally { await workers.close(); }
});

test('the main event loop runs while a real Worker is doing chunk computation', { timeout: 20000 }, async () => {
  const workers = await client();
  const parsed = document(Array.from({ length: 8000 }, (_, i) => String(i).padStart(6, '0') + ' fixture revenue😀 Q1=100; document source.\n').join(''));
  let settled = false, heartbeatDuringComputation = false;
  let started!: () => void;
  const ready = new Promise<void>(resolveReady => started = resolveReady);
  try {
    const call = workers.split(parsed, {}, { title: '响应性', onProgress: () => started() });
    void call.then(() => { settled = true; }, () => { settled = true; });
    await Promise.race([ready, call]);
    await new Promise<void>(resolveBeat => setImmediate(() => {
      heartbeatDuringComputation = !settled; resolveBeat();
    }));
    const result = await call;
    assert.equal(heartbeatDuringComputation, true, 'a main-loop callback must execute after actual Worker start and before its result');
    assert.equal(result.parents.map(chunk => chunk.content).join(''), parsed.document.canonical_text);
  } finally { await workers.close(); }
});

test('bounded concurrency queues later jobs and a queued cancellation never starts', async () => {
  await fixture(fixturePrefix +
    "parentPort.postMessage({protocol:1,id:r.id,type:'started'});\nsetTimeout(()=>{parentPort.postMessage({protocol:1,id:r.id,type:'result',result:" + emptyResult + "});parentPort.close();},120);\n",
  async workerUrl => {
    const workers = await client({ workerUrl, concurrency: 1, maxQueued: 2 });
    const controller = new AbortController(), reason = new Error('queued fixture cancelled');
    const starts: string[] = [];
    let firstStarted!: () => void;
    const ready = new Promise<void>(resolveReady => firstStarted = resolveReady);
    try {
      const first = workers.split(document(''), {}, { title: 'first', onProgress: () => { starts.push('first'); firstStarted(); } });
      await Promise.race([ready, first]);
      const cancelled = workers.split(document(''), {}, { title: 'cancel', signal: controller.signal, onProgress: () => starts.push('cancel') });
      const rejection = assert.rejects(cancelled, error => error === reason);
      const third = workers.split(document(''), {}, { title: 'third', onProgress: () => starts.push('third') });
      const overflow = workers.split(document(''), {}, { title: 'overflow' });
      await assert.rejects(overflow, { code: 'chunking_busy' });
      controller.abort(reason);
      await rejection;
      assert.deepEqual(starts, ['first']);
      await first; await third;
      assert.deepEqual(starts, ['first', 'third']);
    } finally { await workers.close(); }
  });
});

test('already cancelled calls never start a Worker and preserve the caller abort reason', async () => {
  const workers = await client({ workerUrl: pathToFileURL('/does/not/exist.mjs') });
  const controller = new AbortController(), reason = new Error('already cancelled');
  controller.abort(reason);
  try { await assert.rejects(workers.split(document(content), {}, { title: '', signal: controller.signal }), error => error === reason); }
  finally { await workers.close(); }
});

test('active cancellation rejects after its actual Worker exits and leaves unrelated Workers alive', async context => {
  const workers = await client(), controller = new AbortController(), reason = new Error('active cancelled');
  const unrelated = new Worker("setInterval(()=>{},1000)", { eval: true });
  let owned: Worker | undefined;
  const terminate = Worker.prototype.terminate;
  context.mock.method(Worker.prototype, 'terminate', function (this: Worker) { owned = this; return terminate.call(this); });
  try {
    const parsed = document(content.repeat(30));
    await assert.rejects(workers.split(parsed, {}, { title: '取消', signal: controller.signal, onProgress: () => controller.abort(reason) }), error => error === reason);
    assert.ok(owned); assert.equal(owned.threadId, -1, 'promise settlement must wait for actual owned thread exit');
    assert.notEqual(unrelated.threadId, -1);
    assert.ok((await workers.split(document(content), {}, { title: '后续正常' })).children.length > 0);
  } finally { await workers.close(); await terminate.call(unrelated); }
});

test('a result already posted after started cannot turn an aborted call into success', async () => {
  await fixture(fixturePrefix +
    "parentPort.postMessage({protocol:1,id:r.id,type:'started'});parentPort.postMessage({protocol:1,id:r.id,type:'result',result:" + emptyResult + "});parentPort.close();\n",
  async workerUrl => {
    const workers = await client({ workerUrl }), controller = new AbortController(), reason = new Error('race cancelled');
    try {
      await assert.rejects(workers.split(document(''), {}, { title: '', signal: controller.signal, onProgress: () => controller.abort(reason) }), error => error === reason);
    } finally { await workers.close(); }
  });
});

test('an earlier caller cancellation remains authoritative when service close follows immediately', async () => {
  const workers = await client(), controller = new AbortController(), reason = new Error('original cancellation');
  let closed: Promise<void> | undefined;
  try {
    await assert.rejects(workers.split(document(content.repeat(30)), {}, {
      title: '', signal: controller.signal,
      onProgress: () => { controller.abort(reason); closed = workers.close(); },
    }), error => error === reason);
    await closed;
  } finally { await workers.close(); }
});

test('a nullable abort reason retains the standard AbortSignal rejection semantics', async () => {
  const workers = await client(), controller = new AbortController();
  try {
    await assert.rejects(workers.split(document(content.repeat(30)), {}, {
      title: '', signal: controller.signal, onProgress: () => controller.abort(null),
    }), error => error === null);
  } finally { await workers.close(); }
});

test('close rejects active and queued jobs, waits for threads and permanently closes the service', async context => {
  await fixture(fixturePrefix + "parentPort.postMessage({protocol:1,id:r.id,type:'started'});setInterval(()=>{},1000);\n", async workerUrl => {
    let owned: Worker | undefined;
    const terminate = Worker.prototype.terminate;
    context.mock.method(Worker.prototype, 'terminate', function (this: Worker) { owned = this; return terminate.call(this); });
    const workers = await client({ workerUrl });
    let started!: () => void;
    const ready = new Promise<void>(resolveReady => started = resolveReady);
    const active = workers.split(document(''), {}, { title: '', onProgress: () => started() });
    const rejectsActive = assert.rejects(active, { code: 'chunking_closed' });
    await Promise.race([ready, active]);
    const queued = workers.split(document(''), {}, { title: '' });
    const rejectsQueued = assert.rejects(queued, { code: 'chunking_closed' });
    await workers.close(); await Promise.all([rejectsActive, rejectsQueued]);
    assert.ok(owned); assert.equal(owned.threadId, -1);
    await workers.close();
    await assert.rejects(workers.split(document(''), {}, { title: '' }), { code: 'chunking_closed' });
    await assert.rejects(workers.split(document(''), { strategy: 'semantic' }, { title: '' }), { code: 'chunking_closed' });
  });
});

test('an explicit startup-inclusive timeout terminates its Worker before releasing capacity', async () => {
  await fixture(fixturePrefix + "parentPort.postMessage({protocol:1,id:r.id,type:'started'});setInterval(()=>{},1000);\n", async workerUrl => {
    const workers = await client({ workerUrl, timeoutMs: 100 });
    try {
      await assert.rejects(workers.split(document(''), {}, { title: '' }), { code: 'chunking_timeout' });
    } finally { await workers.close(); }
  });
});

for (const [name, source, code] of [
  ['wrong nonce', "parentPort.postMessage({protocol:1,id:'wrong',type:'result',result:" + emptyResult + "});parentPort.close();", 'chunking_protocol_invalid'],
  ['malformed result', "parentPort.postMessage({protocol:1,id:r.id,type:'result',result:{parents:[],children:[{}],diagnostics:{}}});parentPort.close();", 'chunking_protocol_invalid'],
  ['crash', "throw new Error('private fixture crash detail');", 'chunking_worker_failed'],
  ['early exit', "parentPort.close();", 'chunking_worker_failed'],
] as const) {
  test('real Worker ' + name + ' fails explicitly and releases its slot', async () => {
    await fixture(fixturePrefix + source, async workerUrl => {
      const workers = await client({ workerUrl, maxQueued: 0 });
      try {
        await assert.rejects(workers.split(document(''), {}, { title: '' }), { code });
        await assert.rejects(workers.split(document(''), {}, { title: '' }), { code });
      } finally { await workers.close(); }
    });
  });
}

test('constructor limits and normal configuration errors fail without creating Workers', async () => {
  for (const options of [{ concurrency: 0 }, { concurrency: 5 }, { maxQueued: -1 }, { timeoutMs: 0 }])
    await assert.rejects(client(options), { code: 'invalid_chunking_worker_config' });
  const workers = await client({ workerUrl: pathToFileURL('/does/not/exist.mjs') });
  try {
    await assert.rejects(workers.split(document(''), { strategy: 'invalid' }, { title: '' }), { code: 'invalid_chunking_config' });
    await assert.rejects(workers.split(document(''), {}, { title: '' }), { code: 'chunking_worker_failed' });
  } finally { await workers.close(); }
});

test('Worker computation receives no inherited environment, opaque config or provider callback', async () => {
  await fixture(fixturePrefix +
    "parentPort.postMessage({protocol:1,id:r.id,type:'result',result:{parents:[],children:[],diagnostics:{env:process.env.MARLIN_CHUNKING_ENV_FIXTURE??null,argv:process.execArgv,opaque:r.config.opaque_credentials??null}}});parentPort.close();\n",
  async workerUrl => {
    const old = process.env.MARLIN_CHUNKING_ENV_FIXTURE;
    process.env.MARLIN_CHUNKING_ENV_FIXTURE = 'fabricated-parent-marker';
    const workers = await client({ workerUrl });
    try {
      const result = await workers.split(document(''), { opaque_credentials: 'fabricated-config-marker' }, {
        title: '', semanticEmbed: async () => { throw new Error('unused provider must never be called'); },
      });
      assert.deepEqual(result.diagnostics, { env: null, argv: [], opaque: null });
    } finally {
      await workers.close();
      if (old === undefined) delete process.env.MARLIN_CHUNKING_ENV_FIXTURE;
      else process.env.MARLIN_CHUNKING_ENV_FIXTURE = old;
    }
  });
});

test('real Worker retains algorithm validation failures rather than returning empty successful chunks', async () => {
  const workers = await client(), parsed = document('```txt\n' + content + '```\n');
  try {
    await assert.rejects(workers.split(parsed, { token_limit: 1 }, { title: '保护范围' }), error => {
      assert.equal((error as { code: string }).code, 'chunking_failed');
      assert.match((error as Error).message, /token_limit_exceeded:unsplittable_protected_range/);
      return true;
    });
  } finally { await workers.close(); }
});
