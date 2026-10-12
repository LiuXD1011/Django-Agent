import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { once } from 'node:events';
import { createServer } from 'node:http';
import { test } from 'node:test';
import { CoreDatabase } from '../src/storage/database.js';
import { ModelRuntime } from '../src/models/runtime.js';
import { setTimeout as delay } from 'node:timers/promises';
async function fixture() {
  const m = await import('../src/jobs/index.js').catch(() => null); assert.ok(m, 'Persistent job, journal and stream implementation must exist');
  const root = mkdtempSync(join(tmpdir(), 'marlin-jobs-')); const db = new CoreDatabase(root);
  const tenant = db.insert('tenants', { name: 'Fixture', api_key: 'fixture-key' }); const user = db.insert('users', { username: 'fixture', email: 'fixture@example.invalid', password_hash: 'synthetic-unusable', tenant_id: tenant.id });
  const scope = { tenantId: String(tenant.id), userId: String(user.id) }; const session = db.insert('sessions', { tenant_id: tenant.id, user_id: user.id, title: 'Fixture' });
  const message = db.insert('messages', { session_id: session.id, request_id: 'turn', role: 'assistant', content: '' });
  let now = Date.now(); const queue = new m.JobQueue(db, { now: () => now, leaseMs: 5000, heartbeatMs: 1000 });
  return { ...m, db, root, scope, sessionId: String(session.id), messageId: String(message.id), queue, advance: (n: number) => { now += n; }, close: () => { db.close(); rmSync(root, { recursive: true, force: true }); } };
}
const jobInput = (scope: {tenantId: string; userId: string}, requestId: string, recoveryPolicy: 'safe' | 'manual' = 'safe') => ({ scope, requestId, kind: 'fixture', payload: { query: 'synthetic' }, recoveryPolicy });
test('early scoped cancellation is durable and prevents handler execution before job ID is returned', async () => {
  const f = await fixture();
  try {
    f.queue.cancelByRequest('early', f.scope); let calls = 0; f.queue.register('fixture', async () => { calls++; return {}; });
    const job = f.queue.create(jobInput(f.scope, 'early')); assert.equal(job.status, 'cancelled'); await f.queue.run(job.id); assert.equal(calls, 0);
    const other = f.db.insert('tenants', { name: 'Other', api_key: 'other-key' });
    const scoped = f.queue.create(jobInput({ ...f.scope, tenantId: String(other.id) }, 'unrelated')); assert.equal(scoped.status, 'queued');
    assert.throws(() => f.queue.get(scoped.id, f.scope), (e: any) => e.status === 404);
    assert.equal(f.queue.events(job.id, f.scope)[0]?.type, 'cancelled');
  } finally { f.close(); }
});
test('real handlers persist steps, progress, result and contiguous events then reopen without cache', async () => {
  const f = await fixture();
  try {
    f.queue.register('fixture', async ctx => { ctx.progress(0.3); await ctx.step('parse', async () => { ctx.emit('parsed', { count: 1 }); return { count: 1 }; }); return { done: true }; });
    const job = f.queue.create(jobInput(f.scope, 'durable')); const done = await f.queue.run(job.id);
    assert.equal(done.status, 'completed'); assert.deepEqual(done.result, { done: true }); assert.equal(done.attempt, 1);
    const events = f.queue.events(job.id, f.scope); assert.deepEqual(events.map(e => e.seq), events.map((_, i) => i + 1));
    assert.equal(f.db.get('select status from desktop_job_steps where job_id=?', job.id)?.status, 'completed');
    const second = new CoreDatabase(f.root); try { assert.equal(new f.JobQueue(second).get(job.id, f.scope).status, 'completed'); } finally { second.close(); }
    assert.equal(JSON.stringify(done).includes('ownerToken'), false);
  } finally { f.close(); }
});
test('cancel aborts owned real child and timeout terminates it without touching unrelated child', async () => {
  const { spawn } = await import('node:child_process'); const f = await fixture();
  const unrelated = spawn(process.execPath, ['--import', 'tsx', 'test/job-child-fixture.ts', 'hang'], { stdio: ['ignore', 'pipe', 'pipe'] });
  let owned: any; let ready!: () => void; const started = new Promise<void>(r => { ready = r; });
  try {
    f.queue.register('fixture', async ctx => { const p = ctx.spawnOwned(process.execPath, ['--import', 'tsx', 'test/job-child-fixture.ts', 'hang']); owned = p.child; await once(owned.stdout, 'data'); ready(); return await p.completion; });
    const job = f.queue.create(jobInput(f.scope, 'child')); const running = f.queue.run(job.id); await started;
    const closed = once(owned, 'close'); f.queue.cancelByRequest('child', f.scope); await closed;
    assert.equal((await running).status, 'cancelled'); assert.equal(unrelated.exitCode, null); assert.equal(unrelated.signalCode, null);
    const timeout = f.queue.create(jobInput(f.scope, 'timeout')); assert.equal((await f.queue.run(timeout.id, { timeoutMs: 60 })).status, 'failed');
  } finally { unrelated.kill('SIGKILL'); await once(unrelated, 'close'); f.close(); }
});
test('expired safe jobs recover with new attempt; paid/manual jobs remain interrupted and are never replayed automatically', async () => {
  const f = await fixture();
  let release!: () => void; const gate = new Promise<void>(r => { release = r; }); let started!: () => void; const entered = new Promise<void>(r => { started = r; }); let old: any;
  try {
    f.queue.register('fixture', async ctx => { old = ctx; started(); await gate; return { writer: 'A' }; });
    const job = f.queue.create(jobInput(f.scope, 'recover')); const running = f.queue.run(job.id); await entered;
    f.advance(6000); const q2 = new f.JobQueue(f.db, { now: () => Date.now() + 6000 }); assert.equal(q2.recover().safe, 1);
    q2.register('fixture', async ctx => { ctx.publish(() => f.db.run('update sessions set title=? where id=?', 'B', f.sessionId)); return { writer: 'B' }; });
    assert.equal((await q2.run(job.id)).attempt, 2);
    assert.throws(() => old.publish(() => f.db.run('update sessions set title=? where id=?', 'late A', f.sessionId)), /ownership/i);
    assert.throws(() => old.emit('late', {}), /ownership/i); release(); await running;
    assert.deepEqual(q2.get(job.id, f.scope).result, { writer: 'B' }); assert.equal(f.db.read('sessions', f.sessionId)?.title, 'B');
    const paid = q2.create(jobInput(f.scope, 'paid', 'manual')); const payload = JSON.stringify({ input: paid.payload, claim: { ownerToken: 'synthetic-crashed', leaseUntil: 1 } });
    f.db.run("update desktop_jobs set status='running',attempt=1,payload=? where id=?", payload, paid.id);
    assert.equal(q2.recover().manual, 1); assert.equal((await q2.run(paid.id)).status, 'interrupted');
    q2.retry(paid.id, f.scope); assert.equal((await q2.run(paid.id)).attempt, 2);
  } finally { release?.(); f.close(); }
});
test('journal rejects unknown events, freezes JSON and rolls back the session counter on insertion failure', async () => {
  const f = await fixture(); const journal = new f.SessionEventJournal(f.db);
  try {
    const data = { content: 'original', nested: { a: 1 } }; journal.append(f.sessionId, 'turn', 'turn/user-message', data, f.scope); data.nested.a = 2;
    assert.equal((journal.read(f.sessionId, f.scope)[0]?.data.nested as any).a, 1);
    assert.throws(() => journal.append(f.sessionId, 'turn', 'unknown', {}, f.scope));
    f.db.run("create trigger block_event before insert on session_events begin select raise(abort,'planned'); end");
    assert.throws(() => journal.append(f.sessionId, 'turn', 'turn/completed', {}, f.scope)); assert.equal(f.db.read('sessions', f.sessionId)?.event_seq, 1);
    f.db.run('drop trigger block_event'); journal.append(f.sessionId, 'turn', 'turn/completed', { content: 'answer' }, f.scope);
    assert.equal(journal.fold(f.sessionId, f.scope).version, 3); assert.equal(journal.fold(f.sessionId, f.scope).turns[0]?.assistant.content, 'answer');
    assert.throws(() => journal.read(f.sessionId, { ...f.scope, userId: 'other' }), (e: any) => e.status === 404);
  } finally { f.close(); }
});
test('stream offsets, terminal message and result survive reopen, late errors cannot overwrite completion, deleting session cleans streams', async () => {
  const f = await fixture(); const streams = new f.StreamStore(f.db);
  try {
    streams.ensure(f.messageId, f.sessionId, f.scope); streams.append(f.messageId, 'delta', { content: 'hello' }, f.scope);
    streams.append(f.messageId, 'delta', { content: ' world' }, f.scope); assert.equal(streams.finish(f.messageId, { content: 'hello world', refs: [], steps: [], durationMs: 12 }, f.scope), true);
    assert.equal(streams.append(f.messageId, 'error', { content: 'late error' }, f.scope), null);
    assert.equal(f.db.read('messages', f.messageId)?.content, 'hello world'); assert.equal(f.db.read('messages', f.messageId)?.is_fallback, false);
    const second = new CoreDatabase(f.root); try { const restored = new f.StreamStore(second); assert.deepEqual(restored.events(f.messageId, f.scope, 1).map(e => e.offset), [1, 2]); assert.equal(restored.read(f.messageId, f.scope)?.final_content, 'hello world'); } finally { second.close(); }
    streams.deleteSession(f.sessionId, f.scope); assert.equal(f.db.get('select count(*) as n from stream_states')?.n, 0); assert.equal(f.db.get('select count(*) as n from stream_events')?.n, 0);
  } finally { f.close(); }
});

test('graceful close settles in-flight handlers and preserves manual interruption without replay', async () => {
  const f = await fixture();
  try {
    let entered!: () => void; const ready = new Promise<void>(r => { entered = r; });
    f.queue.register('fixture', async ctx => { entered(); await new Promise<void>(r => ctx.signal.addEventListener('abort', () => r(), { once: true })); ctx.signal.throwIfAborted(); return {}; });
    const job = f.queue.create(jobInput(f.scope, 'shutdown', 'manual')); const running = f.queue.run(job.id); await ready;
    await f.queue.close(); assert.equal(f.queue.get(job.id, f.scope).status, 'interrupted'); assert.equal((await running).status, 'interrupted');
  } finally { f.close(); }
});

test('cancellation between claim and handler scheduling prevents even the first provider operation', async () => {
  const f = await fixture();
  try {
    let calls = 0; f.queue.register('fixture', async () => { calls++; return {}; });
    const job = f.queue.create(jobInput(f.scope, 'before-handler')); const running = f.queue.run(job.id);
    f.queue.cancelByRequest('before-handler', f.scope); await running; assert.equal(calls, 0);
  } finally { f.close(); }
});

test('two actual journal writer processes allocate gap-free unique session sequence numbers', { timeout: 15000 }, async () => {
  const { spawn } = await import('node:child_process'); const f = await fixture(); const children: ReturnType<typeof spawn>[] = [];
  try {
    const writer = (request: string) => {
      const child = spawn(process.execPath, ['--import', 'tsx', 'test/job-child-fixture.ts', 'journal', f.root, f.sessionId, f.scope.tenantId, f.scope.userId, request], { stdio: ['pipe', 'pipe', 'pipe'] }); children.push(child);
      let output = '', errors = ''; child.stderr!.on('data', b => { errors += b.toString(); });
      const done = new Promise<void>((resolve, reject) => { child.once('error', reject); child.once('close', code => code === 0 ? resolve() : reject(new Error(`writer failed: ${errors}`))); });
      const ready = new Promise<void>((resolve, reject) => { child.stdout!.on('data', b => { output += b.toString(); if (output.includes('ready\n')) resolve(); }); child.once('error', reject); child.once('exit', code => { if (!output.includes('ready\n')) reject(new Error(`writer startup failed: ${code} ${errors}`)); }); });
      return { child, done, ready };
    };
    const a = writer('writer-a'), b = writer('writer-b'); await Promise.all([a.ready, b.ready]); a.child.stdin!.end(); b.child.stdin!.end(); await Promise.all([a.done, b.done]);
    const events = new f.SessionEventJournal(f.db).read(f.sessionId, f.scope); assert.equal(events.length, 40); assert.deepEqual(events.map(e => e.seq), Array.from({ length: 40 }, (_, i) => i + 1));
    assert.equal(f.db.read('sessions', f.sessionId)?.event_seq, 40);
  } finally { for (const child of children) if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL'); f.close(); }
});

test('SIGKILL of a real job core leaves safe jobs recoverable and manual work interrupted on reopened SQLite', { timeout: 15000 }, async () => {
  const { spawn } = await import('node:child_process'); const f = await fixture(); let child: ReturnType<typeof spawn> | undefined;
  try {
    const safe = f.queue.create(jobInput(f.scope, 'crash-safe')), paid = f.queue.create(jobInput(f.scope, 'crash-paid', 'manual'));
    child = spawn(process.execPath, ['--import', 'tsx', 'test/job-child-fixture.ts', 'crash', f.root, safe.id, paid.id], { stdio: ['ignore', 'pipe', 'pipe'] });
    await new Promise<void>((resolve, reject) => { let output = ''; child!.stdout!.on('data', b => { output += b.toString(); if (output.includes('ready\n')) resolve(); }); child!.once('error', reject); child!.once('exit', code => { if (!output.includes('ready\n')) reject(new Error(`worker exited early ${code}`)); }); });
    const closed = once(child, 'close'); child.kill('SIGKILL'); await closed;
    const reopened = new CoreDatabase(f.root);
    try {
      const restored = new f.JobQueue(reopened, { now: () => Date.now() + 10000 }); const recovery = restored.recover(); assert.deepEqual(recovery, { safe: 1, manual: 1 });
      let calls = 0; restored.register('fixture', async () => { calls++; return { recovered: true }; });
      assert.equal((await restored.run(safe.id)).attempt, 2); assert.equal((await restored.run(paid.id)).status, 'interrupted'); assert.equal(calls, 1);
    } finally { reopened.close(); }
  } finally { if (child && child.exitCode === null && child.signalCode === null) child.kill('SIGKILL'); f.close(); }
});

test('cancelled work leaves no running steps and early cancellation tombstones expire and never leak across scopes', async () => {
  const f = await fixture(); let release!: () => void;
  try {
    let started!: () => void; const entered = new Promise<void>(r => { started = r; });
    f.queue.register('fixture', async ctx => { await ctx.step('blocked', async () => { started(); await new Promise<void>(r => { release = r; }); return {}; }); return {}; });
    const job = f.queue.create(jobInput(f.scope, 'cancel-step')); const running = f.queue.run(job.id); await entered;
    f.queue.cancelByRequest('cancel-step', f.scope); release(); await running;
    assert.equal(f.db.get('select status from desktop_job_steps where job_id=?', job.id)?.status, 'cancelled');
    f.queue.cancelByRequest('expired', f.scope); f.advance(300001); assert.equal(f.queue.create(jobInput(f.scope, 'expired')).status, 'queued');
    assert.equal(f.db.get("select count(*) as n from desktop_meta where key like 'jobs.cancel:%'")?.n, 0);
    const t = f.db.insert('tenants', { name: 'Other', api_key: 'fixture-other' });
    const scope = { ...f.scope, tenantId: String(t.id) }; f.queue.cancelByRequest('scope-only', f.scope);
    assert.equal(f.queue.create(jobInput(scope, 'scope-only')).status, 'queued');
  } finally { release?.(); f.close(); }
});

test('pure trajectory fold preserves reasoning/tools/actors and counts model usage once with thinking fallback', async () => {
  const f = await fixture();
  try {
    const j = new f.SessionEventJournal(f.db); const add = (type: string, data: any, request = 'turn') => j.append(f.sessionId, request, type, data, f.scope);
    add('session/started', {}, ''); add('turn/user-message', { content: 'question' }); add('turn/assistant-created', { mode: 'agent', model_id: 'synthetic' });
    add('agent/iteration', { iteration: 1 }); add('agent/thinking', { iteration: 1, content: 'thought', reasoning_content: 'reasoning', usage: { prompt_tokens: 100, completion_tokens: 20 } });
    add('tool/call', { iteration: 1, name: 'search', tool_call_id: 'tool-1', arguments: { query: 'synthetic' } }); add('tool/result', { iteration: 1, name: 'search', tool_call_id: 'tool-1', output: 'result', duration_ms: 12 });
    add('llm/call', { actor_id: 'worker-1', prompt_tokens: 100, completion_tokens: 20 }); add('observability/trace-linked', { provider: 'synthetic', trace_id: 'trace-reference' }); add('turn/completed', { content: 'answer', duration_ms: 15 });
    add('turn/error', { message: 'late failure' }); add('agent/thinking', { iteration: 1, content: 'old thought', usage: { prompt_tokens: 3, completion_tokens: 4 } }, 'legacy-turn');
    const fold = j.fold(f.sessionId, f.scope); assert.equal(fold.turns.length, 2); const t = fold.turns[0] as any;
    assert.equal(t.steps[0].reasoning, 'reasoning'); assert.equal(t.steps[0].tools[0].output_excerpt, 'result'); assert.equal(t.usage.total_tokens, 120); assert.equal(t.usage.llm_calls, 1); assert.equal(t.actors[0].usage.prompt_tokens, 100);
    assert.equal(t.stopped_reason, 'completed'); assert.equal(t.observability.link_state, 'recorded'); assert.equal(t.interrupted, false);
    assert.equal((fold.turns[1] as any).usage.total_tokens, 7); assert.equal(fold.turns[1]?.interrupted, true);
  } finally { f.close(); }
});

test('owned helper-specific timeout and output limits kill only registered children and await actual exit', async () => {
  const f = await fixture();
  try {
    f.queue.register('fixture', async ctx => {
      const child = ctx.spawnOwned(process.execPath, ['--import', 'tsx', 'test/job-child-fixture.ts', 'hang'], { timeoutMs: 80 });
      await assert.rejects(child.completion, (e: any) => e.code === 'child_timeout');
      assert.ok(child.child.exitCode !== null || child.child.signalCode !== null); return { stopped: true };
    });
    assert.equal((await f.queue.run(f.queue.create(jobInput(f.scope, 'helper-timeout')).id)).status, 'completed');
    const registry = new f.OwnedProcessRegistry();
    try { const child = registry.spawn(process.execPath, ['--import', 'tsx', 'test/job-child-fixture.ts', 'hang'], new AbortController().signal, { maxOutputBytes: 1 }); await assert.rejects(child.completion, (e: any) => e.code === 'child_output_limit'); assert.ok(child.child.exitCode !== null || child.child.signalCode !== null); }
    finally { await registry.close(); }
  } finally { f.close(); }
});

test('terminal stream append returns its actual newest offset even beyond the resume page size', async () => {
  const f = await fixture();
  try {
    const streams = new f.StreamStore(f.db); streams.ensure(f.messageId, f.sessionId, f.scope);
    f.db.transaction(() => { for (let i = 0; i < 2001; i++) f.db.insert('stream_events', { message_id: f.messageId, session_id: f.sessionId, event_type: 'delta', offset: i, data: {} }); });
    const complete = streams.append(f.messageId, 'complete', { content: 'done' }, f.scope); assert.equal(complete?.offset, 2001); assert.equal(complete?.event_type, 'complete');
  } finally { f.close(); }
});

test('terminal stream append persists citations, steps and duration without losing them on reopen', async () => {
  const f = await fixture();
  try {
    const streams = new f.StreamStore(f.db), refs = [{ chunk_id: 'fixture-chunk', title: '来源' }], steps = [{ name: 'lookup', output: '事实' }];
    const event = streams.append(f.messageId, 'complete', { content: '回答', refs, steps, duration_ms: 321 }, f.scope);
    assert.deepEqual(event?.data, { content: '回答', refs, steps, duration_ms: 321 });
    const message = f.db.read('messages', f.messageId)!;
    assert.deepEqual(message.knowledge_references, refs); assert.deepEqual(message.agent_steps, steps); assert.equal(message.agent_duration_ms, 321);
    const reopened = new CoreDatabase(f.root);
    try { const state = new f.StreamStore(reopened).read(f.messageId, f.scope)!; assert.deepEqual(state.final_refs, refs); assert.deepEqual(state.final_steps, steps); assert.equal(state.final_duration_ms, 321); }
    finally { reopened.close(); }
    assert.equal(streams.append(f.messageId, 'error', { content: '迟到失败', refs: [], steps: [], duration_ms: 0 }, f.scope), null);
    assert.deepEqual(f.db.read('messages', f.messageId)?.knowledge_references, refs);
  } finally { f.close(); }
});

test('ensure restores every completed message result field when persistent stream state is absent', async () => {
  const f = await fixture();
  try {
    const refs = [{ chunk_id: 'history-citation' }], steps = [{ name: 'history-tool' }];
    f.db.update('messages', f.messageId, { content: '历史回答', is_completed: true, knowledge_references: refs, agent_steps: steps, agent_duration_ms: 123 });
    const streams = new f.StreamStore(f.db), state = streams.ensure(f.messageId, f.sessionId, f.scope);
    assert.equal(state.is_complete, true); assert.equal(state.final_content, '历史回答');
    assert.deepEqual(state.final_refs, refs); assert.deepEqual(state.final_steps, steps); assert.equal(state.final_duration_ms, 123);
    assert.equal(streams.finish(f.messageId, { content: 'overwrite' }, f.scope), false);
    assert.deepEqual(f.db.read('messages', f.messageId)?.knowledge_references, refs);
  } finally { f.close(); }
});

test('unregistered persisted job kind becomes visibly failed exactly once with a safe error', async () => {
  const f = await fixture();
  try {
    const job = f.queue.create({ ...jobInput(f.scope, 'unknown-kind'), kind: 'untrusted-secret-kind' });
    const result = await f.queue.run(job.id);
    assert.equal(result.status, 'failed'); assert.match(result.error, /handler|unsupported/i); assert(!result.error.includes('untrusted-secret-kind'));
    assert.deepEqual(f.queue.events(job.id, f.scope).map(e => e.type), ['queued', 'failed']);
    assert.equal(f.queue.events(job.id, f.scope).at(-1)?.data.code, 'unknown_job_kind');
    await f.queue.run(job.id); assert.equal(f.queue.events(job.id, f.scope).length, 2);
    const reopened = new CoreDatabase(f.root); try { assert.equal(new f.JobQueue(reopened).get(job.id, f.scope).status, 'failed'); } finally { reopened.close(); }
  } finally { f.close(); }
});

test('manual paid request with a real disconnected HTTP result remains interrupted until explicit retry', async () => {
  const f = await fixture(); let requests = 0;
  const server = createServer(async (req, res) => { for await (const _chunk of req) {} requests++; res.destroy(); });
  server.listen(0, '127.0.0.1'); await once(server, 'listening'); const address = server.address(); assert(address && typeof address !== 'string');
  try {
    const runtime = new ModelRuntime({ id: 'fixture', name: 'fixture', type: 'KnowledgeQA', source: 'openai', parameters: { base_url: `http://127.0.0.1:${address.port}/v1`, api_key: 'fixture-only-secret', model: 'fixture' } });
    f.queue.register('fixture', async ctx => (await runtime.complete([{ role: 'user', content: 'small fixture' }], { signal: ctx.signal })).content);
    const job = f.queue.create(jobInput(f.scope, 'unknown-paid', 'manual'));
    const result = await f.queue.run(job.id); assert.equal(result.status, 'interrupted'); assert.match(result.error, /unknown|unconfirmed/i); assert(!result.error.includes('fixture-only-secret'));
    assert.equal(f.queue.events(job.id, f.scope).at(-1)?.data.result_unknown, true);
    assert.equal((await f.queue.run(job.id)).status, 'interrupted'); assert.equal(f.queue.recover().manual, 0); assert.equal(requests, 1);
    f.queue.retry(job.id, f.scope); const retried = await f.queue.run(job.id); assert.equal(retried.attempt, 2); assert.equal(retried.status, 'interrupted'); assert.equal(requests, 2);
  } finally { server.closeAllConnections(); server.close(); await once(server, 'close'); await f.queue.close(); f.close(); }
});

test('manual job deadline aborts an in-flight HTTP request as an unknown interrupted result', { timeout: 10000 }, async t => {
  const f = await fixture(); let requests = 0, disconnected = false;
  let entered!: () => void; const requestEntered = new Promise<void>(resolve => { entered = resolve; });
  const realTimeout = setTimeout, realClearTimeout = clearTimeout;
  let requestTimer: NodeJS.Timeout | undefined;
  const server = createServer(async (req, res) => {
    for await (const _chunk of req) {} requests++;
    res.on('close', () => { disconnected = true; }); res.setHeader('Content-Type', 'application/json'); res.write('{'); entered();
  });
  server.listen(0, '127.0.0.1'); await once(server, 'listening'); const address = server.address(); assert(address && typeof address !== 'string');
  try {
    const runtime = new ModelRuntime({ id: 'fixture', name: 'fixture', type: 'KnowledgeQA', source: 'openai', parameters: { base_url: `http://127.0.0.1:${address.port}/v1`, model: 'fixture' } });
    f.queue.register('fixture', async ctx => (await runtime.complete([{ role: 'user', content: 'fixture' }], { signal: ctx.signal })).content);
    const job = f.queue.create(jobInput(f.scope, 'paid-deadline', 'manual'));
    // Control only the tested deadline; wait for actual HTTP admission before expiry.
    t.mock.timers.enable({ apis: ['setTimeout'] });
    const running = f.queue.run(job.id, { timeoutMs: 300 });
    try {
      await Promise.race([requestEntered, new Promise<never>((_, reject) => {
        requestTimer = realTimeout(() => reject(new Error('Actual HTTP fixture request did not enter')), 5000);
      })]);
    } finally { realClearTimeout(requestTimer); }
    assert.equal(requests, 1); assert.equal(f.queue.get(job.id, f.scope).status, 'running');
    t.mock.timers.tick(299); assert.equal(f.queue.get(job.id, f.scope).status, 'running');
    t.mock.timers.tick(1);
    assert.equal((await running).status, 'interrupted'); assert.match(f.queue.get(job.id, f.scope).error, /unknown/i);
    t.mock.timers.reset();
    await until(() => disconnected); await f.queue.run(job.id); assert.equal(requests, 1);
  } finally { realClearTimeout(requestTimer); t.mock.timers.reset(); server.closeAllConnections(); server.close(); await once(server, 'close'); await f.queue.close(); f.close(); }
});

test('owned output preserves split multibyte UTF8 separately on stdout and stderr', async () => {
  const f = await fixture(), registry = new f.OwnedProcessRegistry();
  try {
    const child = registry.spawn(process.execPath, ['-e', "const b=Buffer.from('你🙂');process.stdout.write(b.subarray(0,1));process.stderr.write(b.subarray(0,2));setTimeout(()=>{process.stdout.write(b.subarray(1));process.stderr.write(b.subarray(2));},80)"], new AbortController().signal);
    const result = await child.completion; assert.equal(result.stdout, '你🙂'); assert.equal(result.stderr, '你🙂');
  } finally { await registry.close(); f.close(); }
});

test('owned supervisor preserves payload stdin, cwd, explicit environment and successful exit code', async () => {
  const f = await fixture(), registry = new f.OwnedProcessRegistry();
  try {
    const child = registry.spawn(process.execPath, ['-e', "let input='';process.stdin.setEncoding('utf8');process.stdin.on('data',s=>input+=s);process.stdin.on('end',()=>process.stdout.write(JSON.stringify({input,cwd:process.cwd(),env:process.env.FIXTURE_FLAG,nodeMode:process.env.ELECTRON_RUN_AS_NODE})))"], new AbortController().signal, { cwd: f.root, env: { FIXTURE_FLAG: 'isolated' } });
    child.child.stdin.end('输入🙂');
    const result = await child.completion;
    assert.equal(result.code, 0); assert.equal(result.signal, null);
    assert.deepEqual(JSON.parse(result.stdout), { input: '输入🙂', cwd: f.root, env: 'isolated', nodeMode: '1' });
  } finally { await registry.close(); f.close(); }
});

test('owned supervisor reports unavailable payload startup safely and closes its process handle', async () => {
  const f = await fixture(), registry = new f.OwnedProcessRegistry();
  try {
    const child = registry.spawn(join(f.root, 'missing-executable'), ['fixture-only-sensitive-argument'], new AbortController().signal);
    await assert.rejects(child.completion, (e: any) => e.code === 'child_start_failed' && !String(e).includes('fixture-only-sensitive-argument'));
    assert.ok(child.child.exitCode !== null || child.child.signalCode !== null);
  } finally { await registry.close(); f.close(); }
});

function processRunning(pid: number): boolean {
  try {
    process.kill(pid, 0);
    if (process.platform === 'linux' && /\) Z /.test(readFileSync(`/proc/${pid}/stat`, 'utf8'))) return false;
    return true;
  } catch { return false; }
}
async function until(check: () => boolean, timeoutMs = 5000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (!check()) { if (Date.now() >= deadline) throw new Error('Fixture condition timed out'); await delay(10); }
}
async function within<T>(promise: Promise<T>, timeoutMs: number): Promise<T> {
  let timer: NodeJS.Timeout | undefined;
  try { return await Promise.race([promise, new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error('Owned tree cleanup exceeded deadline')), timeoutMs); })]); }
  finally { clearTimeout(timer); }
}

for (const action of ['abort', 'timeout', 'close', 'parent-exit'] as const) {
  test(`owned tree ${action} kills actual TERM-resistant descendants with shared pipes and preserves an unrelated child`, { timeout: 12000 }, async () => {
    const { spawn } = await import('node:child_process'); const f = await fixture(), registry = new f.OwnedProcessRegistry();
    const unrelated = spawn(process.execPath, ['--import', 'tsx', 'test/job-child-fixture.ts', 'hang'], { stdio: ['ignore', 'pipe', 'pipe'] });
    const unrelatedClosed = once(unrelated, 'close'); const controller = new AbortController(); let descendant = 0;
    const marker = join(f.root, 'owned-descendant.json');
    const owned = registry.spawn(process.execPath, ['test/job-tree-fixture.cjs', 'tree', marker, action === 'parent-exit' ? 'exit' : 'hang'], controller.signal, action === 'timeout' ? { timeoutMs: 3000 } : {});
    try {
      await until(() => { try { descendant = JSON.parse(readFileSync(marker, 'utf8')).pid; return descendant > 0; } catch { return false; } });
      if (action === 'abort') controller.abort();
      if (action === 'close') await within(registry.close(), 2000);
      await within(owned.completion.catch(() => undefined), action === 'timeout' ? 5000 : 2000);
      await until(() => !processRunning(descendant), 1000);
      assert.equal(unrelated.exitCode, null); assert.equal(unrelated.signalCode, null);
      assert.ok(owned.child.exitCode !== null || owned.child.signalCode !== null);
    } finally {
      // Only these fixture-created handles/PIDs are eligible for emergency teardown after a red assertion.
      if (descendant && processRunning(descendant)) process.kill(descendant, 'SIGKILL');
      owned.child.kill('SIGKILL'); await within(registry.close(), 2000);
      unrelated.kill('SIGKILL'); await unrelatedClosed; f.close();
    }
  });
}

test('SIGKILL of the owning core closes its private supervisor channel and kills the actual descendant tree', { timeout: 12000 }, async () => {
  const { spawn } = await import('node:child_process'); const f = await fixture();
  const marker = join(f.root, 'crash-descendant.json'), supervisorMarker = join(f.root, 'crash-supervisor.json');
  const core = spawn(process.execPath, ['--import', 'tsx', 'test/job-child-fixture.ts', 'owned-core', marker, supervisorMarker], { stdio: ['ignore', 'pipe', 'pipe'] });
  const closed = once(core, 'close'); let descendant = 0, supervisor = 0;
  try {
    await until(() => { try { descendant = JSON.parse(readFileSync(marker, 'utf8')).pid; supervisor = JSON.parse(readFileSync(supervisorMarker, 'utf8')).pid; return descendant > 0 && supervisor > 0; } catch { return false; } });
    core.kill('SIGKILL'); await within(closed, 2000);
    await until(() => !processRunning(descendant) && !processRunning(supervisor), 2000);
  } finally {
    for (const pid of [descendant, supervisor]) if (pid && processRunning(pid)) process.kill(pid, 'SIGKILL');
    if (core.exitCode === null && core.signalCode === null) core.kill('SIGKILL'); await closed; f.close();
  }
});
