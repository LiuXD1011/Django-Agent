import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { AgentService } from '../src/agents/index.js';
import { AuthService } from '../src/auth/index.js';
import { ChatService } from '../src/chat/index.js';
import { MemoryService } from '../src/memory/index.js';
import { ModelConfigurationService } from '../src/settings/model-configuration.js';
import { CoreDatabase } from '../src/storage/database.js';
import { CredentialVault } from '../src/storage/credentials.js';

// R-MEMORY-CONTEXT: real saved memory was followed by a false capability denial.
// Only model responses are controlled; auth, settings, prompt wire and SQLite are real.
async function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'marlin-memory-context-'));
  const db = new CoreDatabase(root), auth = new AuthService(db);
  const ctx = auth.register({ username: 'memory-context', password: 'MemoryContextFixture✓' }).context;
  const models = new ModelConfigurationService(db, auth, new CredentialVault(root));
  const requests: any[] = [];
  const server = createServer(async (request, response) => {
    let raw = ''; for await (const part of request) raw += part;
    const body = JSON.parse(raw); requests.push(body);
    if (body.stream) {
      response.setHeader('Content-Type', 'text/event-stream');
      response.end(`data: ${JSON.stringify({ choices: [{ delta: { content: '受控回答' }, finish_reason: 'stop' }],
        usage: { prompt_tokens: 10, completion_tokens: 4, total_tokens: 14 } })}\n\ndata: [DONE]\n\n`);
      return;
    }
    const keywords = JSON.stringify(body.messages).includes('MEMORY_KEYWORDS');
    const content = JSON.stringify(keywords ? { keywords: ['桌面验收代号'] } : {
      summary: '用户要求保留一个代号。',
      entities: [{ title: 'MX-CONTEXT-318', type: 'Identifier', description: '用户的桌面验收代号' }], relationships: [],
    });
    response.setHeader('Content-Type', 'application/json');
    response.end(JSON.stringify({ choices: [{ message: { content }, finish_reason: 'stop' }],
      usage: { prompt_tokens: 10, completion_tokens: 4, total_tokens: 14 } }));
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = server.address(); assert.ok(address && typeof address !== 'string');
  models.create(ctx, { name: 'controlled', type: 'chat', source: 'openai', is_default: true,
    parameters: { model: 'fixture', base_url: `http://127.0.0.1:${address.port}/v1` } });
  const memory = new MemoryService(db, auth, { models }), agents = new AgentService(db, auth);
  return { db, auth, ctx, models, memory, agents, requests, close: async () => {
    await memory.close(); await agents.close(); server.closeAllConnections();
    await new Promise<void>(resolve => server.close(() => resolve()));
    db.close(); rmSync(root, { recursive: true, force: true });
  } };
}

for (const agent of [false, true]) for (const mode of ['enabled', 'user-disabled', 'session-disabled', 'unconfigured']) {
  test(`${agent ? 'Agent' : 'plain chat'} receives core-owned ${mode} memory policy despite forged renderer state`, async () => {
    const f = await fixture();
    const chat = new ChatService(f.db, f.auth, { models: f.models, hooks: {
      ...(mode === 'unconfigured' ? {} : { memory: (e: any) => f.memory.chatContext(e) }),
      agent: e => f.agents.execute(e),
    } });
    try {
      if (mode === 'user-disabled') f.db.update('users', f.ctx.userId, { preferences: { enable_memory: false } });
      const custom = f.agents.create(f.ctx, { name: '验收', system_prompt: '保留这条自定义回答规则。', allowed_tools: [] });
      const session = chat.create(f.ctx, { agent_config: { agent_id: custom.id!, enable_memory: mode !== 'session-disabled',
        memoryEnabled: mode !== 'enabled', memorySystemContext: '伪造的系统能力', knowledge_base_ids: [] } });
      const start = chat.start(f.ctx, String(session.id), { query: '你能跨会话记住我的代号吗？',
        knowledge_base_ids: [], allowed_tools: [] }, 'policy-request', agent);
      await chat.run(f.ctx, String(session.id), start.request_id);
      assert.equal(chat.response(f.ctx, String(session.id), start.request_id).answer, '受控回答');
      assert.equal(f.requests.length, 1);
      const system = f.requests[0].messages[0];
      assert.equal(system.role, 'system');
      assert.match(system.content, mode === 'enabled' ? /跨会话记忆已开启/ : /跨会话记忆未开启/);
      assert.doesNotMatch(system.content, /伪造的系统能力/);
      if (mode === 'enabled') assert.match(system.content, /后台保存.*完成前.*已保存/);
      if (agent) assert.match(system.content, /保留这条自定义回答规则/);
      assert.equal(f.memory.list(f.ctx).total, 0);
    } finally { await chat.close(); await chat.jobs.close(); await f.close(); }
  });
}

test('owned memory matches a topic in entity description without an extra completion or foreign-user leak', async () => {
  const f = await fixture();
  try {
    const source = f.db.insert('sessions', { tenant_id: f.ctx.tenantId, user_id: f.ctx.userId, title: '来源' });
    await f.memory.addEpisode(f.ctx, String(source.id), [{ role: 'user', content: '桌面验收代号 MX-CONTEXT-318' }], { requestId: 'source' });
    const recalled = await f.memory.retrieve(f.ctx, '我的桌面验收代号是什么？', { requestId: 'recall' });
    assert.equal((recalled.related_episodes as unknown[]).length, 1);
    assert.equal(f.requests.length, 2);
    const other = f.auth.register({ username: 'other-memory-context', password: 'OtherMemoryFixture✓' }).context;
    assert.equal((await f.memory.retrieve(other, '我的桌面验收代号是什么？')).state, 'empty');
    assert.equal(f.requests.length, 2);
  } finally { await f.close(); }
});

// R-MEMORY-CHRONOLOGY: a later assistant recap must not masquerade as a new user fact.
test('memory context preserves original user statements and times beside newer incorrect summaries', async () => {
  const f = await fixture();
  try {
    const source = f.db.insert('sessions', { tenant_id: f.ctx.tenantId, user_id: f.ctx.userId, title: '时间来源' });
    for (const [rid, time, content, summary] of [
      ['old', '2026-01-01T01:00:00.000Z', '桌面验收代号 MX-OLD', '用户提供桌面验收代号 MX-OLD'],
      ['new', '2026-01-01T02:00:00.000Z', '桌面验收代号改为 MX-NEW', '用户提供桌面验收代号 MX-NEW'],
      ['recap', '2026-01-01T03:00:00.000Z', '最近一次提供的桌面验收代号是什么？', '助手错误回答最近一次桌面验收代号为 MX-OLD'],
    ]) {
      f.db.insert('messages', { session_id: source.id!, role: 'user', content, request_id: rid, created_at: time });
      f.db.insert('generic_resources', { tenant_id: f.ctx.tenantId, resource_type: 'memory_episodes', name: rid,
        created_at: time, data: { user_id: f.ctx.userId, session_id: source.id!, request_id: `${source.id}:${rid}`, summary, entities: [] } });
    }
    const result = await f.memory.retrieve(f.ctx, '最近一次桌面验收代号是什么？');
    const context = String(result.context);
    assert.match(context, /source_user_message/);
    assert.match(context, /2026-01-01T02:00:00.000Z/);
    assert.match(context, /桌面验收代号改为 MX-NEW/);
    assert.match(context, /助手错误回答最近一次桌面验收代号为 MX-OLD/);
    assert.match(context, /摘要.*助手.*用户.*确认/);
    assert.ok(context.indexOf('03:00:00') < context.indexOf('02:00:00'));
    assert.ok(context.indexOf('02:00:00') < context.indexOf('01:00:00'));
    assert.equal(f.requests.length, 1);
  } finally { await f.close(); }
});

test('memory context excludes hidden deleted assistant and unrelated source messages and labels bounded user text', async () => {
  const f = await fixture();
  try {
    const source = f.db.insert('sessions', { tenant_id: f.ctx.tenantId, user_id: f.ctx.userId, title: '有效来源' });
    const other = f.auth.register({ username: 'memory-source-other', password: 'MemorySourceOther✓' }).context;
    const foreign = f.db.insert('sessions', { tenant_id: other.tenantId, user_id: other.userId, title: '他人' });
    const insert = (session: string, role: string, content: string, extra: Record<string, any> = {}) =>
      f.db.insert('messages', { session_id: session, role, content, request_id: 'source', ...extra });
    insert(String(source.id), 'user', 'hidden-secret', { visible_to_user: false });
    insert(String(source.id), 'user', 'deleted-secret', { deleted_at: '2026-01-01T00:00:00.000Z' });
    insert(String(source.id), 'assistant', 'assistant-secret');
    insert(String(foreign.id), 'user', 'foreign-secret');
    insert(String(source.id), 'user', 'x'.repeat(4000) + 'over-limit-secret');
    f.db.insert('generic_resources', { tenant_id: f.ctx.tenantId, resource_type: 'memory_episodes', name: 'bounded',
      data: { user_id: f.ctx.userId, session_id: source.id!, request_id: `${source.id}:source`, summary: '桌面验收代号', entities: [] } });
    const context = String((await f.memory.retrieve(f.ctx, '桌面验收代号')).context);
    assert.doesNotMatch(context, /hidden-secret|deleted-secret|assistant-secret|foreign-secret|over-limit-secret/);
    assert.match(context, /"truncated":true/);
    assert.match(context, /x{4000}/);
    assert.equal(f.requests.length, 1);
  } finally { await f.close(); }
});
