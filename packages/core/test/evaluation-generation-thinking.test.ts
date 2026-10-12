import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtempSync, rmSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { AuthService } from '../src/auth/index.js';
import { EvaluationDatasets } from '../src/evaluation/datasets.js';
import { EvaluationGeneration } from '../src/evaluation/generation.js';
import { ModelConfigurationService } from '../src/settings/model-configuration.js';
import { CoreDatabase } from '../src/storage/database.js';
import { CredentialVault } from '../src/storage/credentials.js';

// Network fixture only: real provider serialization, scoped SQLite candidates,
// source validation and model usage run unchanged. No vendor/key is contacted.
async function fixture(endpoint: 'glm' | 'deepseek' | 'lookalike', response: (body: any, count: number) => any) {
  const root = mkdtempSync(join(tmpdir(), 'marlin-eval-thinking-'));
  const db = new CoreDatabase(root), auth = new AuthService(db);
  const ctx = auth.register({ username: 'generation-fixture', password: 'GenerationFixturePassword✓' }).context;
  const models = new ModelConfigurationService(db, auth, new CredentialVault(root));
  const requests: any[] = [];
  const server = createServer(async (req, res) => {
    let raw = ''; for await (const bytes of req) raw += bytes;
    const body = JSON.parse(raw); requests.push(body);
    assert.equal(db.sqlite.inTransaction, false);
    res.setHeader('content-type', 'application/json'); res.end(JSON.stringify(response(body, requests.length)));
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = server.address(); assert.ok(address && typeof address !== 'string');
  const origin = `http://127.0.0.1:${address.port}`;
  const base = endpoint === 'glm' ? 'https://open.bigmodel.cn/api/paas/v4' : endpoint === 'deepseek' ? 'https://api.deepseek.com/v1' : `${origin}/v1`;
  const model = endpoint === 'deepseek' ? 'deepseek-v4-pro' : 'glm-5.3-flash';
  const configured = models.create(ctx, { name: model, source: endpoint === 'deepseek' ? 'deepseek' : 'zhipu', type: 'KnowledgeQA', is_default: true, parameters: { model, base_url: base } });
  if (endpoint !== 'lookalike') models.updateThinking(ctx, String(configured.id), { revision: models.thinking(ctx, String(configured.id)).revision!, role: 'model', policy: { mode: 'on', effort: 'high' } });
  const before = models.configuration(ctx, String(configured.id));
  const kb = db.insert('knowledge_bases', { tenant_id: ctx.tenantId, name: 'Actual evidence' });
  const source = '晨星项目现行手册：P1 故障首次响应为15分钟，复核负责人为林青。';
  const document = db.insert('knowledges', { tenant_id: ctx.tenantId, knowledge_base_id: kb.id, file_hash: createHash('sha256').update(source).digest('hex'), metadata: { content: source, source_generation: 'fixture-generation' } });
  db.insert('chunks', { tenant_id: ctx.tenantId, knowledge_base_id: kb.id, knowledge_id: document.id, chunk_type: 'text', content: source, start_at: 0, end_at: Array.from(source).length, is_enabled: true });
  const datasets = new EvaluationDatasets(db, auth), generation = new EvaluationGeneration(db, auth, models, datasets);
  const realFetch = globalThis.fetch;
  globalThis.fetch = ((input, options) => {
    const url = new URL(String(input)); assert.equal(url.origin, new URL(base).origin);
    return realFetch(origin + url.pathname, options);
  }) as typeof fetch;
  return { db, ctx, kb, models, before, datasets, generation, requests, async close() {
    globalThis.fetch = realFetch; server.closeAllConnections();
    await new Promise<void>(resolve => server.close(() => resolve()));
    db.close(); rmSync(root, { recursive: true, force: true });
  } };
}

const output = (content: string, finish = 'stop') => ({ choices: [{ message: { content, reasoning_content: 'Controlled reasoning fixture' }, finish_reason: finish }], usage: { prompt_tokens: 112, completion_tokens: 1024, total_tokens: 1136, completion_tokens_details: { reasoning_tokens: 964 } } });
const valid = () => output(JSON.stringify({ question: 'P1故障首次响应是多少分钟？', answer: '15分钟' }));

// Orca H01: actual second generation failed with 1024 completion / 964 reasoning tokens.
test('GLM candidate generation uses existing low auxiliary effort and bounded reasoning budget without changing Chat policy', async () => {
  const f = await fixture('glm', body => body.reasoning_effort === 'low' && body.max_tokens >= 4096 ? valid() : output('', 'length'));
  try {
    const result = await f.generation.generate(f.ctx, { knowledge_base_id: f.kb.id, testset_size: 1, review_mode: 'manual', question_types: ['simple'] }, new AbortController().signal, 'testsets');
    assert.equal((result.entries as any[]).length, 1);
    assert.equal(f.requests.length, 1);
    assert.equal(f.requests[0].max_tokens, 4096);
    assert.deepEqual(f.requests[0].thinking, { type: 'enabled' });
    assert.equal(f.requests[0].reasoning_effort, 'low');
    assert.deepEqual(f.models.configuration(f.ctx, f.before.id), f.before);
    assert.equal((result.entries as any[])[0].status, 'pending_review');
    assert.equal(f.db.get('SELECT count(*) n FROM model_usage')!.n, 1);
  } finally { await f.close(); }
});

test('candidate auxiliary policy remains endpoint exact and retains nonreasoning request budgets', async () => {
  for (const endpoint of ['deepseek', 'lookalike'] as const) {
    const f = await fixture(endpoint, valid);
    try {
      await f.generation.generate(f.ctx, { knowledge_base_id: f.kb.id, testset_size: 1 }, new AbortController().signal, 'testsets');
      assert.equal(f.requests.length, 1);
      assert.equal(f.requests[0].max_tokens, 1024);
      assert.equal(f.requests[0].reasoning_effort, undefined);
      assert.deepEqual(f.requests[0].thinking, endpoint === 'deepseek' ? { type: 'disabled' } : undefined);
      assert.deepEqual(f.models.configuration(f.ctx, f.before.id), f.before);
    } finally { await f.close(); }
  }
});

test('truncated candidate stops once, preserves the previous candidate and audits actual finish reason and usage', async () => {
  const f = await fixture('glm', (_body, count) => count === 1 ? valid() : output('{"question":"incomplete', 'length'));
  try {
    await assert.rejects(f.generation.generate(f.ctx, { knowledge_base_id: f.kb.id, testset_size: 5, review_mode: 'manual' }, new AbortController().signal, 'testsets'), { code: 'evaluation_generation_invalid' });
    assert.equal(f.requests.length, 2, 'failed generation never repeats a paid request');
    const rows = f.db.all("SELECT * FROM generic_resources WHERE resource_type='rag_eval_testsets'");
    assert.equal(rows.length, 1);
    const draft = f.datasets.dto(f.datasets.row(f.ctx, String(rows[0].id)));
    assert.equal((draft.entries as any[]).length, 1);
    assert.equal((draft.generation as any).status, 'failed');
    assert.equal((draft.generation as any).completed_count, 1);
    const usage = f.db.all('SELECT * FROM model_usage ORDER BY created_at,id');
    assert.equal(usage.length, 2);
    const failed = usage.find(row => row.success === 0)!;
    assert.equal(failed.total_tokens, 1136); assert.equal(failed.reasoning_tokens, 964);
    assert.equal(failed.error_message, 'evaluation_generation_invalid');
    assert.equal(JSON.parse(String(failed.metadata)).finish_reason, 'length');
    assert.equal(JSON.parse(String(failed.metadata)).result_unknown, false);
    assert.deepEqual(f.models.configuration(f.ctx, f.before.id), f.before);
  } finally { await f.close(); }
});

test('finish reason audit accepts only public enums and never stores raw model output', async () => {
  const f = await fixture('glm', valid);
  try {
    const usage = { prompt_tokens: 1, completion_tokens: 2, total_tokens: 3, cached_tokens: 0, reasoning_tokens: 1 };
    const accepted = f.models.recordUsage(f.ctx, f.before, usage, { scenario: 'evaluation_generation', success: false, durationMs: 1, metadata: { finish_reason: 'length', raw_response: 'fixture raw output' } });
    assert.deepEqual(accepted.metadata, { finish_reason: 'length' });
    const rejected = f.models.recordUsage(f.ctx, f.before, usage, { scenario: 'evaluation_generation', success: false, durationMs: 1, metadata: { finish_reason: 'not_a_vendor_enum', raw_response: 'fixture raw output' } });
    assert.deepEqual(rejected.metadata, {});
  } finally { await f.close(); }
});
