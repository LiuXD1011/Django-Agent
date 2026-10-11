import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdtempSync, rmSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import test from 'node:test';
import { AuthService } from '../src/auth/index.js';
import { DocumentParser } from '../src/documents/parser.js';
import { DocumentWorkflow } from '../src/documents/workflow.js';
import { JobQueue } from '../src/jobs/queue.js';
import { ModelRuntime } from '../src/models/runtime.js';
import * as thinking from '../src/models/thinking.js';
import { SearchIndex } from '../src/retrieval/search-index.js';
import { ModelConfigurationService } from '../src/settings/model-configuration.js';
import { CoreDatabase } from '../src/storage/database.js';
import { CredentialVault } from '../src/storage/credentials.js';
import { WikiService } from '../src/wiki/index.js';

// The real provider adapter retains the verified GLM identity. Only network routing
// is redirected to a bounded loopback HTTP fixture; no vendor request or key is used.
test('GLM short auxiliary tasks and Wiki avoid reasoning-only results, while Chat preserves high effort', async () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-auxiliary-'));
  const db = new CoreDatabase(root), auth = new AuthService(db), jobs = new JobQueue(db), index = new SearchIndex(db);
  const ctx = auth.register({ username: 'auxiliary-owner', password: 'AuxiliaryFixturePassword✓' }).context;
  const models = new ModelConfigurationService(db, auth, new CredentialVault(root));
  const cfg = models.create(ctx, { name: 'controlled GLM', source: 'zhipu', type: 'chat', is_default: true, parameters: { base_url: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-5.3-flash' } });
  models.updateThinking(ctx, String(cfg.id), { revision: models.thinking(ctx, String(cfg.id)).revision!, role: 'model', policy: { mode: 'on', effort: 'high' } });
  const kb = db.insert('knowledge_bases', { tenant_id: ctx.tenantId, name: 'auxiliary', indexing_strategy: { vector_enabled: false, wiki_enabled: false, graph_enabled: false } });
  const bodies: any[] = [];
  let badOutput = false;
  const server = createServer(async (req, res) => {
    assert.equal(db.sqlite.inTransaction, false);
    let raw = ''; for await (const bytes of req) raw += bytes;
    const body = JSON.parse(raw); bodies.push(body);
    const prompt = body.messages.at(-1).content;
    const lightweight = body.thinking?.type === 'enabled' && body.reasoning_effort === 'low';
    const auxiliary = prompt.includes('摘要') || prompt.includes('WIKI_') || prompt.includes('5个用户问题') || prompt.includes('关键词');
    let content = auxiliary && !lightweight || badOutput ? '' : prompt.includes('WIKI_CANDIDATES')
      ? JSON.stringify({ entities: [{ name: 'Orca', description: '实际证据' }], concepts: [] })
      : prompt.includes('WIKI_PAGES') ? JSON.stringify({ pages: [{ slug: 'entity/orca', summary: '实际摘要', content: '# Orca\n实际证据正文' }] })
      : prompt.includes('5个用户问题') ? '["真实问题"]' : prompt.includes('关键词') ? '{"title":"Orca","keywords":["证据"]}' : '实际摘要正文';
    if (badOutput && prompt.includes('5个用户问题')) content = '{"questions":"bad shape"}';
    if (badOutput && prompt.includes('关键词')) content = '[]';
    res.setHeader('content-type', 'application/json');
    res.end(JSON.stringify({ choices: [{ message: { content, reasoning_content: 'controlled reasoning' }, finish_reason: content ? 'stop' : 'length' }], usage: { prompt_tokens: 13, completion_tokens: 400, total_tokens: 413, completion_tokens_details: { reasoning_tokens: content ? 190 : 397 } } }));
  });
  await new Promise<void>(r => server.listen(0, '127.0.0.1', r));
  const address = server.address(); assert.ok(address && typeof address !== 'string');
  const realFetch = globalThis.fetch;
  globalThis.fetch = ((input, options) => {
    const url = new URL(String(input));
    assert.equal(url.origin, 'https://open.bigmodel.cn');
    return realFetch(`http://127.0.0.1:${address.port}${url.pathname}`, options);
  }) as typeof fetch;
  const parser = new DocumentParser({ pythonExecutable: process.env.MARLIN_TEST_PYTHON ?? '/tmp/marlin-parser-isolation-20261010/bin/python', workerPath: resolve('../../workers/document/worker.py') });
  const workflow = new DocumentWorkflow(db, auth, jobs, models, undefined, { parser, index, scheduler: () => {} });
  const wiki = new WikiService(db, auth, models);
  try {
    const upload = async (name: string) => {
      const created = await workflow.upload(ctx, String(kb.id), { name, bytes: Buffer.from('Orca 的实际知识证据。😀') }, randomUUID());
      const done = await jobs.run(String(created.task_id)); assert.equal(done.status, 'completed', done.error);
      return db.read('knowledges', String(created.knowledge.id))!;
    };
    const valid = await upload('valid.txt');
    assert.equal(valid.summary_status, 'completed');
    assert.equal(valid.description, '实际摘要正文');
    assert.equal(bodies[0].max_tokens, 400, 'preserve the old summary budget');
    assert.equal(bodies[0].reasoning_effort, 'low');
    // R-AUXILIARY-QUESTIONS: real question generation consumed 1022/1024 tokens on reasoning.
    assert.deepEqual((valid.metadata as any).generated_questions, ['真实问题']);
    assert.deepEqual((valid.metadata as any).extracted_metadata, { title: 'Orca', keywords: ['证据'] });
    assert.equal(bodies[1].reasoning_effort, 'low', 'questions use the existing lightweight auxiliary policy');
    assert.equal(bodies[2].reasoning_effort, 'low', 'metadata uses the same short-task policy');
    db.update('knowledge_bases', kb.id, { indexing_strategy: { vector_enabled: false, wiki_enabled: true, graph_enabled: false }, summary_model_id: cfg.id });
    const generated = await wiki.ingest(ctx, String(kb.id), String(valid.id));
    assert.equal(generated.status, 'completed');
    for (const body of bodies.slice(3)) assert.equal(body.reasoning_effort, 'low');
    assert.ok(String(wiki.get(ctx, String(kb.id), 'entity/orca').content).includes('实际证据正文'));
    await new ModelRuntime(models.configuration(ctx, String(cfg.id))).complete([{ role: 'user', content: '普通对话' }]);
    assert.equal(bodies.at(-1).reasoning_effort, 'high');
    assert.deepEqual(models.configuration(ctx, String(cfg.id)).parameters.thinking, { mode: 'on', effort: 'high' });

    db.update('knowledge_bases', kb.id, { indexing_strategy: { vector_enabled: false, wiki_enabled: false, graph_enabled: false } });
    badOutput = true;
    const invalid = await upload('invalid.txt');
    assert.equal(invalid.summary_status, 'failed'); assert.equal(invalid.description, '');
    const invalidUsage = db.all('SELECT * FROM model_usage').filter(row => JSON.parse(String(row.metadata)).knowledge_id === invalid.id);
    assert.equal(invalidUsage.length, 3);
    assert.ok(invalidUsage.every(row => row.success === 0));
    assert.ok(invalidUsage.every(row => row.completion_tokens === 400 && row.total_tokens === 413));
    const before = db.get('SELECT count(*) AS n FROM model_usage')!.n;
    db.update('knowledge_bases', kb.id, { indexing_strategy: { wiki_enabled: true } });
    await assert.rejects(wiki.ingest(ctx, String(kb.id), String(invalid.id)), (error: any) => error.code === 'model_output_invalid' && !error.resultUnknown);
    assert.equal(db.get('SELECT count(*) AS n FROM model_usage')!.n, Number(before) + 1);
    const receipt = db.all('SELECT * FROM model_usage ORDER BY created_at DESC').find(row => row.scenario === 'wiki_candidate_slugs' && JSON.parse(String(row.metadata)).knowledge_id === invalid.id)!;
    assert.equal(receipt.success, 0); assert.equal(receipt.reasoning_tokens, 397);
  } finally {
    globalThis.fetch = realFetch;
    await Promise.all([workflow.close(), jobs.close(), wiki.close()]);
    server.closeAllConnections(); await new Promise<void>(r => server.close(() => r()));
    db.close(); rmSync(root, { recursive: true, force: true });
  }
});

test('auxiliary policy is endpoint exact and never changes stored Chat thinking', () => {
  const policy = (thinking as any).auxiliaryThinking;
  assert.equal(typeof policy, 'function');
  assert.deepEqual(policy('https://open.bigmodel.cn/api/paas/v4', 'glm-5.3-flash'), { mode: 'on', effort: 'low' });
  assert.deepEqual(policy('https://api.deepseek.com/v1', 'deepseek-v4-pro'), { mode: 'off', effort: null });
  assert.equal(policy('http://127.0.0.1/v1', 'glm-5.3-flash'), undefined);
  assert.equal(policy('https://open.bigmodel.cn/api/paas/v4', 'glm-4.7'), undefined);
});
