import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { AuthService } from '../src/auth/index.js';
import { CoreDatabase } from '../src/storage/database.js';
import { CredentialVault } from '../src/storage/credentials.js';
import { ModelConfigurationService } from '../src/settings/model-configuration.js';
import { SettingsService } from '../src/settings/index.js';
import { IntegrationService } from '../src/integrations/index.js';
import { ChatService } from '../src/chat/index.js';
import { AgentService } from '../src/agents/index.js';

async function fixture() {
  const module = await import('../src/memory/index.js').catch(() => null); assert.ok(module, 'MemoryService must implement owner-scoped factual memory');
  const root = mkdtempSync(join(tmpdir(), 'marlin-memory-')), db = new CoreDatabase(root), auth = new AuthService(db);
  const ctx = auth.register({ username: 'alice', password: 'Memory✓Password' }).context, bob = auth.register({ username: 'bob', password: 'Memory✓Password' }).context;
  const session = db.insert('sessions', { tenant_id: ctx.tenantId, user_id: ctx.userId, title: '来源对话' });
  let calls = 0, response: string | undefined, pause = false, disconnected = false, release: (() => void) | undefined; const requests: any[] = [];
  const server = createServer(async (req, res) => {
    assert.equal(db.sqlite.inTransaction, false); let raw = ''; for await (const p of req) raw += p; const body = JSON.parse(raw); requests.push(body); calls++;
    if (pause) await new Promise<void>(resolve => { release = resolve; });
    if (disconnected) { res.destroy(); return; }
    if (body.stream) {
      res.setHeader('content-type', 'text/event-stream');
      res.end(`data: ${JSON.stringify({ choices: [{ delta: { content: '主回答继续✓', reasoning_content: '既有主推理' }, finish_reason: 'stop' }], usage: { prompt_tokens: 11, completion_tokens: 4, total_tokens: 15, completion_tokens_details: { reasoning_tokens: 2 } } })}\n\ndata: [DONE]\n\n`); return;
    }
    const extraction = !JSON.stringify(body.messages).includes('MEMORY_KEYWORDS');
    const content = response ?? JSON.stringify(extraction ? { summary: '用户研究预算与合同风险', entities: [{ title: '预算', type: 'Concept', description: '研究内容' }, { title: '合同', type: 'Concept', description: '资料' }], relationships: [{ source: '预算', target: '合同', description: '预算约束', weight: 1 }] } : { keywords: ['预算'] });
    res.setHeader('content-type', 'application/json'); res.end(JSON.stringify({ choices: [{ message: { content }, finish_reason: 'stop' }], usage: { prompt_tokens: 11, completion_tokens: 4, total_tokens: 15, completion_tokens_details: { reasoning_tokens: 2 } } }));
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve)); const address = server.address(); assert.ok(address && typeof address !== 'string');
  const models = new ModelConfigurationService(db, auth, new CredentialVault(root)); models.create(ctx, { name: 'fixture', type: 'KnowledgeQA', source: 'openai', is_default: true, parameters: { model: 'fixture', base_url: `http://127.0.0.1:${address.port}/v1` } });
  const memory = new module.MemoryService(db, auth, { models });
  return { ...module, root, db, auth, ctx, bob, session, models, memory, requests, calls: () => calls, invalid: (v: boolean) => { response = v ? '{bad json' : undefined; }, response: (v: string) => { response = v; }, disconnect: () => { disconnected = true; }, pause: () => { pause = true; }, release: () => release?.(), close: async () => { release?.(); await memory.close(); await new Promise<void>(resolve => { server.closeAllConnections(); server.close(() => resolve()); }); db.close(); rmSync(root, { recursive: true, force: true }); } };
}
const messages = [{ role: 'user' as const, content: '研究预算' }, { role: 'assistant' as const, content: '关注合同风险' }];
const waitFor = async (work: () => boolean) => { for (let n = 0; n < 100 && !work(); n++) await new Promise(resolve => setTimeout(resolve, 10)); assert.ok(work()); };

test('real extraction stores entities/relations, keywords retrieve across owned sessions, usage remains actual', async () => {
  const f = await fixture(); try {
    const result = await f.memory.addEpisode(f.ctx, f.session.id, messages, { requestId: 'memory-one' });
    assert.equal(result.state, 'stored'); assert.equal(result.graph_state, 'not_configured');
    assert.equal(f.memory.list(f.ctx).items[0].summary, '用户研究预算与合同风险');
    const found = await f.memory.retrieve(f.ctx, '预算', { requestId: 'retrieve-one' }); assert.equal(found.related_episodes.length, 1); assert.ok(found.context.includes('用户研究预算与合同风险'));
    assert.equal(f.calls(), 2); assert.equal(f.db.all('select * from model_usage').length, 2);
    assert.ok(f.db.all('select success from model_usage').every(row => row.success === 1));
    assert.equal(f.db.all('select * from model_usage')[0]?.reasoning_tokens, 2);
    assert.equal((await f.memory.addEpisode(f.ctx, f.session.id, messages, { requestId: 'memory-one' })).idempotent, true); assert.equal(f.calls(), 2);
    assert.equal(f.memory.list(f.bob).items.length, 0);
  } finally { await f.close(); }
});

test('user switch and explicit disabled memory issue no paid calls and owner isolation rejects foreign sessions', async () => {
  const f = await fixture(); try {
    assert.equal((await f.memory.addEpisode(f.ctx, f.session.id, messages, { enabled: false })).state, 'disabled');
    f.db.update('users', f.ctx.userId, { preferences: { enable_memory: false } });
    assert.equal((await f.memory.retrieve(f.ctx, '预算')).state, 'disabled'); assert.equal(f.calls(), 0);
    await assert.rejects(f.memory.addEpisode(f.bob, f.session.id, messages), (e: any) => e.status === 404);
  } finally { await f.close(); }
});

test('malformed paid extraction reports error without fallback/replay and retains unsuccessful source state', async () => {
  const f = await fixture(); try {
    f.invalid(true); await assert.rejects(f.memory.addEpisode(f.ctx, f.session.id, messages, { requestId: 'invalid-extract' }), (e: any) => e.code === 'memory_response_invalid');
    assert.equal(f.calls(), 1); assert.equal(f.memory.list(f.ctx).items.length, 0); assert.equal(f.db.all('select * from model_usage').length, 1);
    const audit = f.db.all('select * from model_usage')[0]!;
    assert.equal(audit.success, 0); assert.equal(audit.error_message, 'memory_response_invalid');
    assert.equal(audit.prompt_tokens, 11); assert.equal(audit.completion_tokens, 4); assert.equal(audit.reasoning_tokens, 2);
    await assert.rejects(f.memory.addEpisode(f.ctx, f.session.id, messages, { requestId: 'invalid-extract' }), (e: any) => e.code === 'memory_retry_required'); assert.equal(f.calls(), 1);
  } finally { await f.close(); }
});

for (const [name, response] of [['bad JSON', '{bad json'], ['empty content', ''], ['invalid fields', '{"keywords":[123]}']] as const) {
  test(`invalid memory keywords ${name} retain failed usage and direct retrieval remains an explicit 502`, async () => {
    const f = await fixture(); try {
      await f.memory.addEpisode(f.ctx, f.session.id, messages, { requestId: 'keywords-source' }); f.response(response);
      await assert.rejects(f.memory.retrieve(f.ctx, '预算', { requestId: 'bad-keywords' }), (e: any) => e.status === 502 && e.code === 'memory_response_invalid');
      const usage = f.db.all("select * from model_usage where scenario='memory_keywords'");
      assert.equal(usage.length, 1); assert.equal(usage[0]!.success, 0); assert.equal(usage[0]!.error_message, 'memory_response_invalid');
      assert.equal(usage[0]!.prompt_tokens, 11); assert.equal(usage[0]!.completion_tokens, 4); assert.equal(usage[0]!.total_tokens, 15); assert.equal(usage[0]!.reasoning_tokens, 2);
      assert.equal(f.requests[1].max_tokens, 256); assert.equal(f.calls(), 2, 'no automatic paid retry');
    } finally { await f.close(); }
  });
}

for (const agent of [false, true]) {
  test(`optional malformed memory permits the subsequent actual ${agent ? 'Agent' : 'plain chat'} model call with a warning`, async () => {
    const f = await fixture(), agents = new AgentService(f.db, f.auth), chat = new ChatService(f.db, f.auth, { models: f.models, hooks: { memory: e => f.memory.chatContext(e), agent: e => agents.execute(e) } });
    try {
      await f.memory.addEpisode(f.ctx, f.session.id, messages, { requestId: 'chat-source' }); f.invalid(true);
      const start = chat.start(f.ctx, f.session.id, { query: '预算', knowledge_base_ids: [], allowed_tools: [] }, 'optional-invalid-memory', agent);
      await chat.run(f.ctx, f.session.id, start.request_id);
      const answer = chat.response(f.ctx, f.session.id, start.request_id);
      assert.equal(answer.answer, '主回答继续✓'); assert.equal(answer.message.is_fallback, false);
      assert.equal(chat.jobs.get(start.job_id, { tenantId: f.ctx.tenantId, userId: f.ctx.userId }).status, 'completed');
      assert.ok(JSON.stringify(answer.message.agent_steps).includes('既有主推理'));
      const events = chat.events(f.ctx, f.session.id).items as any[];
      const warning = events.find(e => e.type === 'maintenance/step' && e.data.stage === 'memory_retrieval');
      assert.equal(warning.data.warnings[0].code, 'memory_response_invalid');
      const audits = f.db.all('select scenario,success from model_usage order by rowid');
      assert.deepEqual(audits.map(row => [row.scenario, row.success]), [['memory_extraction', 1], ['memory_keywords', 0], [agent ? 'agent_chat' : 'chat', 1]]);
      assert.equal(f.requests[1].max_tokens, 256); assert.equal(f.calls(), 3, 'exactly one keywords request and one main request');
    } finally { await chat.close(); await chat.jobs.close(); await agents.close(); await f.close(); }
  });
}

for (const action of ['cancel', 'revoke', 'source-delete', 'unknown-upstream'] as const) {
  test(`optional memory never swallows ${action} or starts a late main request`, async () => {
    const f = await fixture(), chat = new ChatService(f.db, f.auth, { models: f.models, hooks: { memory: e => f.memory.chatContext(e) } });
    try {
      await f.memory.addEpisode(f.ctx, f.session.id, messages, { requestId: 'fenced-source' }); f.invalid(true);
      if (action === 'unknown-upstream') f.disconnect(); else f.pause();
      const start = chat.start(f.ctx, f.session.id, { query: '预算', knowledge_base_ids: [] }, `fenced-${action}`);
      const running = chat.run(f.ctx, f.session.id, start.request_id); const settled = running.then(() => null, error => error);
      await waitFor(() => f.calls() === 2);
      if (action === 'cancel') chat.stop(f.ctx, f.session.id, start.request_id);
      else if (action === 'revoke') f.db.run("UPDATE tenant_members SET status='revoked' WHERE user_id=?", f.ctx.userId);
      else if (action === 'source-delete') f.db.update('sessions', f.session.id, { deleted_at: new Date().toISOString() });
      f.release(); await settled;
      assert.equal(f.calls(), 2); assert.equal(f.requests.some(body => body.stream), false);
      const job = chat.jobs.get(start.job_id, { tenantId: f.ctx.tenantId, userId: f.ctx.userId }); assert.notEqual(job.status, 'completed');
      if (action === 'cancel') assert.equal(job.status, 'cancelled');
      if (action === 'unknown-upstream') assert.equal(job.status, 'interrupted');
    } finally { f.release(); await chat.close(); await chat.jobs.close(); await f.close(); }
  });
}

test('source deletion and preference/revocation during model await fence publication and retain billing facts', async () => {
  const f = await fixture(); try {
    f.pause(); const work = f.memory.addEpisode(f.ctx, f.session.id, messages, { requestId: 'raced' }); await waitFor(() => f.calls() === 1);
    await f.memory.deleteSession(f.ctx, f.session.id); f.release();
    await assert.rejects(work, (e: any) => e.status === 409); assert.equal(f.memory.list(f.ctx).items.length, 0); assert.equal(f.db.all('select * from model_usage').length, 1);
  } finally { await f.close(); }
});

test('deleting session memory is scoped, leaves other session facts, and remote cleanup is explicit pending', async () => {
  const f = await fixture(); try {
    await f.memory.addEpisode(f.ctx, f.session.id, messages, { requestId: 'source-one' });
    const another = f.db.insert('sessions', { tenant_id: f.ctx.tenantId, user_id: f.ctx.userId, title: '另一对话' }); await f.memory.addEpisode(f.ctx, another.id, messages, { requestId: 'source-two' });
    const result = await f.memory.deleteSession(f.ctx, f.session.id); assert.equal(result.state, 'deleted'); assert.equal(f.memory.list(f.ctx).items.length, 1); assert.equal(f.memory.list(f.ctx).items[0].session_id, another.id);
    assert.equal(f.db.all("select * from desktop_meta where key like 'memory.graph.pending:%'").length, 1);
  } finally { await f.close(); }
});

test('ordinary owner retains local facts while real administrator-only graph adapter reports permission explicitly', async () => {
  const f = await fixture(), integrations = new IntegrationService(f.db, f.auth, new SettingsService(f.db, f.auth, new CredentialVault(f.root)));
  try {
    f.memory.dependencies.graph = integrations;
    const empty = await f.memory.retrieve(f.ctx, '预算'); assert.equal(empty.state, 'empty'); assert.equal(empty.graph_state, 'forbidden'); assert.equal(f.calls(), 0);
    const saved = await f.memory.addEpisode(f.ctx, f.session.id, messages, { requestId: 'ordinary-local' });
    assert.equal(saved.state, 'stored'); assert.equal(saved.graph_state, 'forbidden'); assert.equal(saved.warnings[0].code, 'memory_graph_permission_denied');
    const result = await f.memory.retrieve(f.ctx, '预算'); assert.equal(result.related_episodes.length, 1); assert.equal(result.graph_state, 'forbidden'); assert.equal(result.warnings[0].code, 'memory_graph_permission_denied');
    const deleted = await f.memory.deleteSession(f.ctx, f.session.id); assert.equal(deleted.graph_state, 'forbidden'); assert.equal(f.memory.list(f.ctx).total, 0);
    assert.equal(f.calls(), 2);
  } finally { await integrations.close(); await f.close(); }
});
