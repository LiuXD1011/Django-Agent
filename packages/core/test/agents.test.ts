import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { createServer } from 'node:http';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { test } from 'node:test';
import { AuthService } from '../src/auth/index.js';
import { CoreDatabase } from '../src/storage/database.js';
import { CredentialVault } from '../src/storage/credentials.js';
import { ModelConfigurationService } from '../src/settings/model-configuration.js';
import { SearchIndex } from '../src/retrieval/search-index.js';
import { JobQueue } from '../src/jobs/queue.js';
import { ChatService } from '../src/chat/index.js';
import { CoreApplication } from '../src/application.js';

async function fixture() {
  const module = await import('../src/agents/index.js').catch(() => null); assert.ok(module, 'AgentService must preserve real tool and actor business');
  const root = mkdtempSync(join(tmpdir(), 'marlin-agents-')), db = new CoreDatabase(root), auth = new AuthService(db), jobs = new JobQueue(db), index = new SearchIndex(db);
  const ctx = auth.register({ username: 'alice', password: 'Agent✓Password' }).context, bob = auth.register({ username: 'bob', password: 'Agent✓Password' }).context;
  const requests: any[] = [], childConnections = new Set<object>(); let mode = 'search', release: (() => void) | undefined;
  const server = createServer(async (req, res) => {
    assert.equal(db.sqlite.inTransaction, false); let raw = ''; for await (const p of req) raw += p; const body = JSON.parse(raw); requests.push(body);
    if (mode === 'pause' && requests.length === 1) await new Promise<void>(resolve => { release = resolve; res.on('close', resolve); });
    const done = body.messages.some((m: any) => m.role === 'tool');
    const isChild = String(body.messages[0].content).includes('文档检索子 Agent');
    if (isChild) { childConnections.add(res); res.on('close', () => childConnections.delete(res)); }
    if ((mode.startsWith('spawn') || mode === 'actor-pause') && isChild) await new Promise<void>(resolve => { release = resolve; res.on('close', resolve); });
    let calls: any[] = [];
    if (!done && !isChild) {
      if (mode.startsWith('actor') || mode.startsWith('spawn')) calls = [{ id: 'delegate-1', type: 'function', function: { name: 'actor', arguments: JSON.stringify({ action: mode.startsWith('actor') ? 'run' : 'spawn', subagent_type: 'doc_retriever', prompt: '查找预算证据' }) } }];
      else if (mode === 'forbidden') calls = [{ id: 'blocked-1', type: 'function', function: { name: 'web_search', arguments: JSON.stringify({ query: '未经用户选择' }) } }];
      else calls = [{ id: 'search-1', type: 'function', function: { name: 'knowledge_search', arguments: JSON.stringify({ query: '预算', top_k: 5 }) } }];
    }
    if (body.stream) {
      res.setHeader('content-type', 'text/event-stream');
      const frames = calls.length ? [{ tool_calls: calls.map((c: any, index: number) => ({ index, id: c.id, type: c.type, function: { name: c.function.name, arguments: c.function.arguments.slice(0, 8) } })) }, { tool_calls: calls.map((c: any, index: number) => ({ index, function: { arguments: c.function.arguments.slice(8) } })) }] : [{ reasoning_content: '有证据再回答' }, { content: isChild ? '子任务证据✓' : '根据预算证据回答✓' }];
      for (const delta of frames) res.write(`data: ${JSON.stringify({ choices: [{ delta }] })}\n\n`);
      if (mode === 'spawn-cut' && isChild) { res.end(); return; }
      res.end(`data: ${JSON.stringify({ choices: [{ delta: {}, finish_reason: calls.length ? 'tool_calls' : 'stop' }], usage: { prompt_tokens: 10, completion_tokens: 2, total_tokens: 12 } })}\n\ndata: [DONE]\n\n`);
    } else { res.setHeader('content-type', 'application/json'); res.end(JSON.stringify({ choices: [{ message: { content: isChild ? '子任务证据✓' : '根据预算证据回答✓', tool_calls: calls, reasoning_content: '有证据再回答' }, finish_reason: calls.length ? 'tool_calls' : 'stop' }], usage: { prompt_tokens: 10, completion_tokens: 2, total_tokens: 12 } })); }
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve)); const a = server.address(); assert.ok(a && typeof a !== 'string');
  const models = new ModelConfigurationService(db, auth, new CredentialVault(root)); models.create(ctx, { name: 'fixture', type: 'KnowledgeQA', source: 'openai', is_default: true, parameters: { model: 'fixture', base_url: `http://127.0.0.1:${a.port}/v1` } });
  const agents = new module.AgentService(db, auth); const chat = new ChatService(db, auth, { models, jobs, index, hooks: { agent: execution => agents.execute(execution) } });
  const kb = db.insert('knowledge_bases', { tenant_id: ctx.tenantId, name: '预算' }); const doc = db.insert('knowledges', { tenant_id: ctx.tenantId, knowledge_base_id: kb.id, title: '预算文件', type: 'file', source: 'file' }); const chunk = db.insert('chunks', { tenant_id: ctx.tenantId, knowledge_base_id: kb.id, knowledge_id: doc.id, content: '预算真实证据', seq_id: '1152921504606846975' }); index.indexKeyword({ tenantId: ctx.tenantId }, chunk.id);
  return { ...module, root, db, auth, jobs, index, models, ctx, bob, agents, chat, kb, doc, requests, childConnections, mode: (v: string) => { mode = v; }, release: () => release?.(), close: async () => { release?.(); await chat.close(); await agents.close(); await jobs.close(); await new Promise<void>(resolve => { server.closeAllConnections(); server.close(() => resolve()); }); db.close(); rmSync(root, { recursive: true, force: true }); } };
}

test('Agent resource CRUD, copy, legacy config, builtin list and secrets projection are scoped', async () => {
  const f = await fixture(); try {
    const a = f.agents.create(f.ctx, { name: '研究', knowledge_base_ids: [f.kb.id], allowed_tools: ['knowledge_search', 'thinking'], opaque: { kept: true }, token: 'test-only-secret' });
    assert.deepEqual(a.allowed_tools, ['knowledge_search', 'thinking']); assert.equal(JSON.stringify(a).includes('test-only-secret'), false);
    assert.ok(f.agents.list(f.ctx).items.some((v: any) => v.id.startsWith('builtin-')));
    assert.equal(f.agents.get(f.ctx, a.id).opaque.kept, true);
    const copy = f.agents.copy(f.ctx, a.id); assert.equal(copy.copied_from, a.id);
    assert.throws(() => f.agents.get(f.bob, a.id), (e: any) => e.status === 404);
    f.agents.delete(f.ctx, copy.id); assert.throws(() => f.agents.get(f.ctx, copy.id), (e: any) => e.status === 404);
  } finally { await f.close(); }
});

async function until(check: () => boolean, timeout = 2000): Promise<void> {
  const end = Date.now() + timeout; while (!check() && Date.now() < end) await new Promise(resolve => setTimeout(resolve, 10)); assert.ok(check(), 'condition did not settle');
}

test('spawn remains a real independent manual actor job after parent completion and isolates another owned session', async () => {
  const f = await fixture(); try {
    f.mode('spawn'); const session = f.chat.create(f.ctx, {}), other = f.chat.create(f.ctx, {});
    const start = f.chat.start(f.ctx, session.id, { query: '后台查找预算', knowledge_base_ids: [f.kb.id] }, 'detached-parent', true);
    let parentDone = false; const parent = f.chat.run(f.ctx, session.id, start.request_id).then(() => { parentDone = true; });
    await until(() => f.requests.length >= 3); await new Promise(resolve => setTimeout(resolve, 150)); const completedBeforeChild = parentDone;
    const running = f.db.read('agent_actors', String(f.db.get('select id from agent_actors where session_id=?', session.id)!.id))!;
    f.release(); await parent; await until(() => f.db.read('agent_actors', String(running.id))?.last_outcome === 'success');
    assert.equal(completedBeforeChild, true, 'parent must complete while its actual child HTTP request remains paused');
    assert.equal(running.status, 'running'); assert.equal(running.background, true); assert.equal(f.chat.response(f.ctx, session.id, start.request_id).answer, '根据预算证据回答✓');
    const actor = (f.chat as any).actor(f.ctx, session.id, running.actor_id); assert.equal(actor.output, '子任务证据✓');
    const job = f.jobs.get(actor.metadata.job_id, { tenantId: f.ctx.tenantId, userId: f.ctx.userId }); assert.equal(job.recoveryPolicy, 'manual'); await until(() => f.jobs.get(job.id, job.scope).status === 'completed');
    assert.throws(() => (f.chat as any).actor(f.ctx, other.id, actor.actor_id), (e: any) => e.status === 404);
    await assert.rejects(() => (f.chat as any).cancelActor(f.ctx, other.id, actor.actor_id), (e: any) => e.status === 404);
    assert.throws(() => (f.chat as any).actor(f.bob, session.id, actor.actor_id), (e: any) => e.status === 404);
    const events = f.chat.events(f.ctx, session.id).items; const completed = events.find((v: any) => v.type === 'turn/completed');
    assert.ok(events.some((v: any) => v.type === 'agent/actor' && v.data.event === 'completed' && v.seq > completed.seq));
    assert.equal(f.db.all('select * from messages where visible_to_user=0').length, 2); assert.equal(f.db.all('select * from model_usage').length, 3);
  } finally { await f.close(); }
});

async function pausedSpawn(f: Awaited<ReturnType<typeof fixture>>, request = 'spawn-cancel') {
  f.mode('spawn'); const session = f.chat.create(f.ctx, {}), start = f.chat.start(f.ctx, session.id, { query: '后台实际请求', knowledge_base_ids: [] }, request, true);
  await f.chat.run(f.ctx, session.id, start.request_id); await until(() => f.requests.length >= 3 && f.childConnections.size === 1);
  return { session, start, actor: (f.chat as any).actors(f.ctx, session.id).items[0] };
}

test('clear and close cancel actual detached provider work after the parent is already complete', async () => {
  for (const operation of ['clear', 'chat-close', 'agent-close']) {
    const f = await fixture(); try {
      const { session, actor } = await pausedSpawn(f, `detached-${operation}`);
      let settled = false; const pending = (operation === 'clear' ? f.chat.clearMessages(f.ctx, session.id) : operation === 'chat-close' ? f.chat.close() : f.agents.close()).then(() => { settled = true; });
      await new Promise(resolve => setTimeout(resolve, 180)); const stoppedWithoutRelease = settled; f.release(); await pending;
      assert.equal(stoppedWithoutRelease, true, operation); await until(() => f.childConnections.size === 0);
      assert.equal(f.db.all("select * from messages where visible_to_user=0 and role='assistant'").length, 0);
      assert.equal(f.jobs.get(actor.metadata.job_id, { tenantId: f.ctx.tenantId, userId: f.ctx.userId }).status, 'cancelled');
      const count = f.db.all('select * from model_usage').length; assert.equal(count, 3); await new Promise(resolve => setTimeout(resolve, 130)); assert.equal(f.db.all('select * from model_usage').length, count);
    } finally { await f.close(); }
  }
});

test('completed-parent deletion cancels detached work before deleting its actor and never publishes a late result', async () => {
  const f = await fixture(); try {
    const { session, start } = await pausedSpawn(f, 'detached-delete-message');
    await f.chat.deleteMessage(f.ctx, session.id, start.assistant_message_id);
    assert.equal(f.db.all('select * from model_usage').length, 3, 'deletion must await the actual worker and its audit');
    await until(() => f.childConnections.size === 0); f.release(); await new Promise(resolve => setTimeout(resolve, 150));
    assert.equal(f.db.all('select * from agent_actors').length, 0); assert.equal(f.db.all("select * from messages where visible_to_user=0 and role='assistant'").length, 0);
  } finally { await f.close(); }
});

test('source fingerprint and attempt lease fence prevent detached stale writes while retaining provider audit facts', async () => {
  for (const interference of ['source', 'owner']) {
    const f = await fixture(); try {
      const { session, actor } = await pausedSpawn(f, `detached-${interference}`);
      if (interference === 'source') { const id = f.db.get("select id from messages where session_id=? and visible_to_user=1 and role='user'", session.id)!.id; f.db.update('messages', String(id), { content: '被修改的源消息' }); }
      else { const raw = f.db.get('select payload from desktop_jobs where id=?', actor.metadata.job_id)!; const payload = JSON.parse(String(raw.payload)); payload.claim.ownerToken = 'another-attempt-owner'; f.db.run('update desktop_jobs set payload=?,attempt=attempt+1 where id=?', JSON.stringify(payload), actor.metadata.job_id); }
      await until(() => f.childConnections.size === 0); f.release(); await new Promise(resolve => setTimeout(resolve, 120));
      assert.equal(f.db.all("select * from messages where visible_to_user=0 and role='assistant'").length, 0); assert.notEqual(f.db.read('agent_actors', actor.id)!.last_outcome, 'success');
      assert.equal(f.db.all('select * from model_usage').length, 3); assert.equal(f.chat.loadMessages(f.ctx, session.id).items.length, 2);
      if (interference === 'owner') assert.equal(f.jobs.get(actor.metadata.job_id, { tenantId: f.ctx.tenantId, userId: f.ctx.userId }).status, 'running', 'an old worker cannot cancel the new owner');
    } finally { await f.close(); }
  }
});

test('uncertain detached model result stays interrupted across restart and orphan callbacks never trigger another paid request', async () => {
  const f = await fixture(); let next: ChatService | undefined; try {
    const { session, actor } = await pausedSpawn(f, 'detached-unknown'); f.mode('spawn-cut'); f.release();
    await until(() => f.jobs.get(actor.metadata.job_id, { tenantId: f.ctx.tenantId, userId: f.ctx.userId }).status === 'interrupted');
    await until(() => f.db.read('agent_actors', actor.id)!.last_outcome === 'interrupted'); const count = f.requests.length;
    await f.chat.close(); await f.agents.close(); const queue = new JobQueue(f.db); next = new ChatService(f.db, f.auth, { models: f.models, index: f.index, jobs: queue });
    queue.recover(); (next as any).recoverActors(); await queue.run(actor.metadata.job_id); assert.equal(f.requests.length, count);
    const orphan = f.db.insert('agent_actors', { session_id: session.id, actor_id: 'orphan-1', agent_type: 'doc_retriever', parent_message_id: actor.parent_message_id, background: true, status: 'running' });
    const source = f.jobs.get(actor.metadata.job_id, { tenantId: f.ctx.tenantId, userId: f.ctx.userId }); const lost = queue.create({ scope: source.scope, requestId: 'trusted-lost-callback', kind: 'chat.actor', recoveryPolicy: 'manual', payload: { ...source.payload, actor_row_id: orphan.id!, actor_id: 'orphan-1' } }); f.db.update('agent_actors', String(orphan.id), { metadata: { job_id: lost.id } });
    assert.equal((next as any).recoverActors().interrupted, 1); await queue.run(lost.id); assert.equal(f.requests.length, count); assert.equal(queue.get(lost.id, source.scope).status, 'interrupted'); assert.equal((next as any).actor(f.ctx, session.id, 'orphan-1').last_outcome, 'interrupted');
  } finally { await next?.close(); await f.close(); }
});

test('actual CoreApplication.close waits its detached worker and preserves an independent application worker', async () => {
  const f = await fixture(); let app: CoreApplication | undefined; try {
    const { actor: foreign } = await pausedSpawn(f, 'foreign-application'); app = new CoreApplication(f.root);
    const session = app.chat.create(f.ctx, {}), start = app.chat.start(f.ctx, session.id, { query: '另一个应用后台任务', knowledge_base_ids: [], enable_memory: false }, 'owned-application', true);
    await app.runTask(() => app!.chat.run(f.ctx, session.id, start.request_id)); await until(() => f.childConnections.size === 2);
    const actor = app.chat.actors(f.ctx, session.id).items[0]; await app.close(); app = undefined;
    await until(() => f.childConnections.size === 1); assert.equal(f.jobs.get(actor.metadata.job_id, { tenantId: f.ctx.tenantId, userId: f.ctx.userId }).status, 'cancelled');
    assert.equal(f.jobs.get(foreign.metadata.job_id, { tenantId: f.ctx.tenantId, userId: f.ctx.userId }).status, 'running');
    assert.equal(f.db.all('select * from model_usage').length, 5); await new Promise(resolve => setTimeout(resolve, 120)); assert.equal(f.db.all('select * from model_usage').length, 5);
    await f.chat.cancelActor(f.ctx, foreign.session_id, foreign.actor_id); await until(() => f.childConnections.size === 0); assert.equal(f.db.all('select * from model_usage').length, 6);
  } finally { await app?.close(); await f.close(); }
});

test('a branch snapshots a running actor without gaining its source job binding or result', async () => {
  const f = await fixture(); try {
    const { session, actor } = await pausedSpawn(f, 'detached-branch'); const branch = f.chat.branch(f.ctx, session.id);
    const snapshot = f.chat.actor(f.ctx, branch.id, actor.actor_id); assert.equal(snapshot.last_outcome, 'interrupted'); assert.equal(snapshot.metadata.job_id, undefined);
    await f.chat.cancelActor(f.ctx, branch.id, actor.actor_id); assert.equal(f.jobs.get(actor.metadata.job_id, { tenantId: f.ctx.tenantId, userId: f.ctx.userId }).status, 'running');
    f.release(); await until(() => f.chat.actor(f.ctx, session.id, actor.actor_id).last_outcome === 'success'); assert.equal(f.chat.actor(f.ctx, branch.id, actor.actor_id).output, '');
  } finally { await f.close(); }
});

test('public actor cancellation also aborts an actual foreground actor request without cancelling its parent', async () => {
  const f = await fixture(); try {
    f.mode('actor-pause'); const session = f.chat.create(f.ctx, {}), start = f.chat.start(f.ctx, session.id, { query: '取消指定前台子任务', knowledge_base_ids: [] }, 'foreground-cancel', true);
    const parent = f.chat.run(f.ctx, session.id, start.request_id); await until(() => f.childConnections.size === 1);
    const actor = f.chat.actors(f.ctx, session.id).items[0]; await f.chat.cancelActor(f.ctx, session.id, actor.actor_id);
    await new Promise(resolve => setTimeout(resolve, 180)); const endedWithoutRelease = f.childConnections.size === 0; f.release(); await parent;
    assert.equal(endedWithoutRelease, true); assert.equal(f.chat.actor(f.ctx, session.id, actor.actor_id).last_outcome, 'cancelled'); assert.equal(f.chat.response(f.ctx, session.id, start.request_id).answer, '根据预算证据回答✓');
    assert.equal(f.db.all('select * from model_usage').length, 3); assert.equal(f.db.all("select * from messages where visible_to_user=0 and role='assistant'").length, 0);
  } finally { await f.close(); }
});

test('closing between queue claim and handler entry cannot start a new owned provider request', async () => {
  const f = await fixture(); try {
    const session = f.chat.create(f.ctx, {}), start = f.chat.start(f.ctx, session.id, { query: '退出时不得新付费', knowledge_base_ids: [] }, 'close-before-handler', true);
    const pending = f.chat.run(f.ctx, session.id, start.request_id); await f.chat.close(); await pending;
    assert.equal(f.requests.length, 0); assert.equal(f.db.all('select * from model_usage').length, 0);
  } finally { await f.close(); }
});

test('actual streamed tool fragments run real scoped FTS then resume model with result, preserving references and trajectory', async () => {
  const f = await fixture(); try {
    const session = f.chat.create(f.ctx, {}), start = f.chat.start(f.ctx, session.id, { query: '研究预算', knowledge_base_ids: [f.kb.id], max_rounds: 4 }, 'agent-search', true);
    await f.chat.run(f.ctx, session.id, start.request_id); const response = f.chat.response(f.ctx, session.id, start.request_id);
    assert.equal(response.answer, '根据预算证据回答✓'); assert.equal(f.requests.length, 2); assert.equal(response.references[0].seq_id, '1152921504606846975');
    assert.equal(response.message.agent_steps[0].tool_calls[0].id, 'search-1'); assert.ok(response.message.agent_steps[0].tool_calls[0].result.output.includes('预算真实证据'));
    assert.ok(f.requests[1].messages.some((v: any) => v.role === 'tool' && v.tool_call_id === 'search-1'));
    const trajectory = f.chat.trajectory(f.ctx, session.id); assert.equal(trajectory.turns[0].usage.total_tokens, 24); assert.equal(trajectory.turns[0].steps[0].tools[0].tool_call_id, 'search-1');
  } finally { await f.close(); }
});

test('explicit [] stays empty even for Agent and tools cannot widen context scope through arguments', async () => {
  const f = await fixture(); try {
    const session = f.chat.create(f.ctx, {}), start = f.chat.start(f.ctx, session.id, { query: '研究预算', knowledge_base_ids: [] }, 'agent-none', true);
    await f.chat.run(f.ctx, session.id, start.request_id); const response = f.chat.response(f.ctx, session.id, start.request_id);
    assert.deepEqual(response.references, []); assert.equal(response.message.agent_steps[0].tool_calls[0].result.output.includes('预算真实证据'), false);
  } finally { await f.close(); }
});

test('subagent execution creates real hidden history, actor trace and attributed usage without nested actor permission', async () => {
  const f = await fixture(); try {
    f.mode('actor'); const session = f.chat.create(f.ctx, {}), start = f.chat.start(f.ctx, session.id, { query: '委派预算研究', knowledge_base_ids: [f.kb.id] }, 'actor-request', true);
    await f.chat.run(f.ctx, session.id, start.request_id); const response = f.chat.response(f.ctx, session.id, start.request_id);
    assert.equal(response.message.actor_traces.length, 1); assert.equal(response.message.actor_traces[0].last_outcome, 'success'); assert.equal(response.message.actor_traces[0].output, '子任务证据✓');
    assert.equal(f.db.all('select * from messages where visible_to_user=0').length, 2); assert.equal(f.chat.loadMessages(f.ctx, session.id).items.length, 2);
    assert.ok(f.chat.trajectory(f.ctx, session.id).turns[0].actors.some((v: any) => v.actor_id === 'doc_retriever-1'));
    const child = f.requests.find(v => String(v.messages[0].content).includes('文档检索子 Agent')); assert.equal(child.tools.some((v: any) => v.function.name === 'actor'), false);
  } finally { await f.close(); }
});

test('unselected external tool fails explicitly and never performs uncontrolled network access', async () => {
  const f = await fixture(); try {
    f.mode('forbidden'); const session = f.chat.create(f.ctx, {}), start = f.chat.start(f.ctx, session.id, { query: '普通问题', knowledge_base_ids: [] }, 'no-web', true);
    await f.chat.run(f.ctx, session.id, start.request_id); const response = f.chat.response(f.ctx, session.id, start.request_id);
    assert.equal(response.message.agent_steps[0].tool_calls[0].result.error_type, 'PERMISSION_DENIED'); assert.equal(response.message.agent_steps[0].tool_calls[0].result.retryable, false);
  } finally { await f.close(); }
});

test('Agent prompt includes memory supplied by the authenticated chat hook', async () => {
  const f = await fixture(); try {
    f.chat.dependencies.hooks!.memory = async () => ({ context: '<relevant_memory>已保存的个人事实</relevant_memory>' });
    const session = f.chat.create(f.ctx, {}), start = f.chat.start(f.ctx, session.id, { query: '请使用个人记忆', knowledge_base_ids: [] }, 'agent-memory', true);
    await f.chat.run(f.ctx, session.id, start.request_id); assert.ok(JSON.stringify(f.requests[0].messages).includes('已保存的个人事实'));
  } finally { await f.close(); }
});

test('closing AgentService aborts its own provider lifetime while keeping billing facts', async () => {
  const f = await fixture(); try {
    f.mode('pause'); const session = f.chat.create(f.ctx, {}), start = f.chat.start(f.ctx, session.id, { query: '取消实际请求', knowledge_base_ids: [] }, 'agent-closing', true);
    const work = f.chat.run(f.ctx, session.id, start.request_id); for (let n = 0; n < 100 && !f.requests.length; n++) await new Promise(resolve => setTimeout(resolve, 10)); assert.equal(f.requests.length, 1);
    let closed = false; const closing = f.agents.close().then(() => { closed = true; }); await new Promise(resolve => setTimeout(resolve, 150)); const abortedBeforeRelease = closed; f.release(); await closing; await work;
    assert.equal(abortedBeforeRelease, true); assert.equal(f.db.all('select * from model_usage').length, 1); assert.equal(f.db.all('select * from model_usage')[0]?.success, 0);
  } finally { await f.close(); }
});
