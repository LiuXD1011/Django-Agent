import assert from 'node:assert/strict';
import { once } from 'node:events';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { isAbsolute, join } from 'node:path';
import { test } from 'node:test';
import { RagasBridge } from '../src/evaluation/ragas.js';
import { ModelRuntime } from '../src/models/runtime.js';

const pythonExecutable = process.env.MARLIN_TEST_PYTHON ?? (process.platform === 'win32' ? '' : '/usr/bin/python3');
assert.ok(isAbsolute(pythonExecutable), 'An absolute trusted Python executable is required; on Windows set MARLIN_TEST_PYTHON to an owned helper copy');

async function within<T>(promise: Promise<T>, milliseconds: number): Promise<T> {
  let timer: NodeJS.Timeout | undefined;
  try { return await Promise.race([promise, new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error('Fixture deadline expired')), milliseconds); })]); }
  finally { clearTimeout(timer); }
}

// This standard-library Python helper exercises the real bridge protocol, not Ragas algorithms or vendor quality.
const prefix = "import json,sys,uuid,time\nr=json.loads(sys.stdin.readline())\nprint(json.dumps(dict(protocol=1,id=r['id'],type='model_call',call_id=str(uuid.uuid4()),example_id=r['rows'][0]['example_id'],call_index=1,operation='chat',prompt='fixture',schema=dict(type='object'))),flush=True)\n";
const row = { example_id: 'example', question: 'question', answer: 'answer', reference: 'reference', contexts: ['evidence'] };

for (const mode of ['deadline', 'worker_exit', 'protocol_fault'] as const) {
  test(`${mode} aborts the real in-flight HTTP request and waits for callback audit without replacing the first error`, async () => {
    const root = mkdtempSync(join(tmpdir(), 'marlin-evaluation-deadline-')), path = join(root, 'fixture.py');
    const ending = mode === 'deadline' ? 'sys.stdin.readline()\n' : mode === 'worker_exit' ? 'time.sleep(0.7)\nsys.exit(7)\n' : "time.sleep(0.7)\nprint('invalid-json',flush=True)\nsys.stdin.readline()\n";
    writeFileSync(path, prefix + ending);
    let requests = 0, disconnected = false, auditStarted!: () => void, releaseAudit!: () => void, audited = 0, settled = false;
    const auditing = new Promise<void>(resolve => { auditStarted = resolve; }), auditGate = new Promise<void>(resolve => { releaseAudit = resolve; });
    const server = createServer(async (req, res) => { for await (const _chunk of req) {} requests++; res.on('close', () => { disconnected = true; }); if (mode === 'deadline') { res.setHeader('content-type', 'application/json'); res.write('{'); } });
    server.listen(0, '127.0.0.1'); await once(server, 'listening');
    const runtime = new ModelRuntime({ id: 'fixture', name: 'fixture', type: 'KnowledgeQA', source: 'openai', parameters: { base_url: `http://127.0.0.1:${(server.address() as any).port}/v1`, timeoutMs: 20000, api_key: 'fixture-only-key' } });
    const bridge = new RagasBridge({ pythonExecutable, workerPath: path }), signals: AbortSignal[] = [];
    const work = bridge.evaluate([row], async (_request, signal) => {
      signals.push(signal);
      try { const value = await runtime.complete([{ role: 'user', content: 'fixture' }], { signal }); return { content: value.content }; }
      finally { auditStarted(); await auditGate; audited++; }
    }, { timeoutMs: 2000 });
    void work.then(() => { settled = true; }, () => { settled = true; });
    try {
      await within(auditing, 6000);
      assert.equal(requests, 1); assert.equal(signals[0]?.aborted, true); assert.equal(settled, false); assert.equal(audited, 0);
      releaseAudit();
      const expected = mode === 'deadline' ? 'evaluation_timeout' : mode === 'worker_exit' ? 'evaluation_worker_failed' : 'ragas_protocol_invalid';
      await assert.rejects(work, (error: any) => error.code === expected);
      assert.equal(audited, 1); assert.equal(requests, 1);
      await within(new Promise<void>(resolve => { const check = () => disconnected ? resolve() : setTimeout(check, 10); check(); }), 1000);
    } finally { releaseAudit(); await bridge.close(); await work.catch(() => {}); server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); rmSync(root, { recursive: true, force: true }); }
  });
}

test('external cancellation still aborts model RPC and awaits its audit', async () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-evaluation-external-cancel-')), path = join(root, 'fixture.py'); writeFileSync(path, prefix + 'sys.stdin.readline()\n');
  const bridge = new RagasBridge({ pythonExecutable, workerPath: path }), controller = new AbortController();
  let entered!: () => void, audited = false;
  const entering = new Promise<void>(resolve => { entered = resolve; });
  const work = bridge.evaluate([row], async (_request, signal) => {
    entered();
    await new Promise<void>(resolve => signal.addEventListener('abort', () => resolve(), { once: true }));
    audited = true;
    throw Object.assign(new Error('cancelled fixture'), { code: 'model_cancelled' });
  }, { signal: controller.signal, timeoutMs: 2000 });
  void work.catch(() => {});
  try { await within(entering, 5000); controller.abort(); await assert.rejects(work, (error: any) => error.code === 'model_cancelled'); assert.equal(audited, true); }
  finally { await bridge.close(); rmSync(root, { recursive: true, force: true }); }
});
