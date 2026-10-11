import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { AuthService } from '../src/auth/index.js';
import { MemoryService } from '../src/memory/index.js';
import { ModelRuntime } from '../src/models/runtime.js';
import { ModelConfigurationService } from '../src/settings/model-configuration.js';
import { CoreDatabase } from '../src/storage/database.js';
import { CredentialVault } from '../src/storage/credentials.js';

// R-MEMORY-AUXILIARY: actual GLM memory extraction exhausted its 2048-token budget.
// Only HTTP routing is redirected to loopback; runtime, policy, audit and storage are real.
test('GLM structured memory uses the auxiliary policy and retains budgets and ordinary Chat high effort', async () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-memory-thinking-'));
  const db = new CoreDatabase(root), auth = new AuthService(db);
  const ctx = auth.register({ username: 'memory-thinking', password: 'MemoryFixturePassword✓' }).context;
  const models = new ModelConfigurationService(db, auth, new CredentialVault(root));
  const cfg = models.create(ctx, { name: 'controlled GLM', source: 'zhipu', type: 'chat', is_default: true,
    parameters: { base_url: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-5.3-flash' } });
  models.updateThinking(ctx, String(cfg.id), { revision: models.thinking(ctx, String(cfg.id)).revision!,
    role: 'model', policy: { mode: 'on', effort: 'high' } });
  const session = db.insert('sessions', { tenant_id: ctx.tenantId, user_id: ctx.userId, title: '记忆来源' });
  const memory = new MemoryService(db, auth, { models });
  const bodies: any[] = [];
  const server = createServer(async (req, res) => {
    assert.equal(db.sqlite.inTransaction, false);
    let raw = ''; for await (const bytes of req) raw += bytes;
    const body = JSON.parse(raw); bodies.push(body);
    const prompt = body.messages.map((message: any) => message.content).join('\n');
    const auxiliary = prompt.includes('MEMORY_');
    const lightweight = body.thinking?.type === 'enabled' && body.reasoning_effort === 'low';
    const content = auxiliary && !lightweight ? '{"summary":"unfinished' : prompt.includes('MEMORY_KEYWORDS')
      ? '{"keywords":["晨星"]}' : prompt.includes('MEMORY_EXTRACT')
        ? JSON.stringify({ summary: '晨星 P1 响应时限为15分钟', entities: [{ title: '晨星', type: 'Project', description: '验收项目' }], relationships: [] })
        : '普通对话保持原策略';
    res.setHeader('content-type', 'application/json');
    res.end(JSON.stringify({ choices: [{ message: { content }, finish_reason: lightweight || !auxiliary ? 'stop' : 'length' }],
      usage: { prompt_tokens: 13, completion_tokens: lightweight ? 40 : 2048,
        total_tokens: lightweight ? 53 : 2061, completion_tokens_details: { reasoning_tokens: lightweight ? 8 : 1458 } } }));
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = server.address(); assert.ok(address && typeof address !== 'string');
  const realFetch = globalThis.fetch;
  globalThis.fetch = ((input, options) => {
    const url = new URL(String(input)); assert.equal(url.origin, 'https://open.bigmodel.cn');
    return realFetch(`http://127.0.0.1:${address.port}${url.pathname}`, options);
  }) as typeof fetch;
  try {
    const saved = await memory.addEpisode(ctx, String(session.id), [{ role: 'user', content: '晨星的P1时限？' },
      { role: 'assistant', content: '15分钟。' }], { modelId: String(cfg.id), requestId: 'controlled-memory-source' });
    assert.equal(saved.state, 'stored');
    const found = await memory.retrieve(ctx, '晨星', { modelId: String(cfg.id), requestId: 'controlled-memory-query' });
    assert.equal((found.related_episodes as unknown[]).length, 1);
    assert.match(String(found.context), /15分钟/);
    assert.equal(bodies[0].max_tokens, 2048);
    assert.equal(bodies[1].max_tokens, 256);
    for (const body of bodies) {
      assert.deepEqual(body.thinking, { type: 'enabled' });
      assert.equal(body.reasoning_effort, 'low');
    }
    const audits = db.all('SELECT scenario,success,total_tokens FROM model_usage ORDER BY rowid');
    assert.deepEqual(audits.map(row => [row.scenario, row.success, row.total_tokens]),
      [['memory_extraction', 1, 53], ['memory_keywords', 1, 53]]);
    await new ModelRuntime(models.configuration(ctx, String(cfg.id))).complete([{ role: 'user', content: '普通对话' }]);
    assert.equal(bodies.length, 3);
    assert.equal(bodies[2].reasoning_effort, 'high');
    assert.deepEqual(models.configuration(ctx, String(cfg.id)).parameters.thinking, { mode: 'on', effort: 'high' });
  } finally {
    globalThis.fetch = realFetch;
    await memory.close(); server.closeAllConnections();
    await new Promise<void>(resolve => server.close(() => resolve()));
    db.close(); rmSync(root, { recursive: true, force: true });
  }
});
