import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { CoreApplication } from '../src/application.js';
import type { HttpMethod, JsonObject } from '../src/contracts.js';

test('application exposes scoped real evaluation review, configuration failures, graph state and actor routes', async () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-application-evaluation-'));
  const app = new CoreApplication(root, { allowAutoSetup: true });
  try {
    const issue = app.auth.autoSetup({ password: 'application-evaluation-fixture-password' });
    const request = (method: HttpMethod, path: string, body?: JsonObject) => app.dispatch({ protocol: 1, id: randomUUID(), method, path, ...(body ? { body } : {}) }, { transport: 'http', access: issue.credentials.access });
    const data = (value: Awaited<ReturnType<typeof request>>) => (value.response.body as JsonObject).data as JsonObject;
    const datasets = await request('GET', '/api/v1/rag-eval/datasets');
    assert.equal(datasets.response.status, 200); assert.deepEqual(data(datasets).datasets, []);
    const kb = app.knowledge.knowledgeBases.create(issue.context, { name: '真实审核资料' });
    const source = '海盐项目的维护负责人是林明。';
    const doc = app.database.insert('knowledges', { tenant_id: issue.context.tenantId, knowledge_base_id: kb.id, title: '标准资料', parse_status: 'completed', metadata: { content: source, source_generation: 'qa-v1' } });
    const chunk = app.database.insert('chunks', { tenant_id: issue.context.tenantId, knowledge_base_id: kb.id, knowledge_id: doc.id, content: source, seq_id: '1', start_at: 0, end_at: Array.from(source).length });
    const entries = Array.from({ length: 5 }, (_, index) => ({ question: `海盐项目负责人核对问题 ${index + 1}？`, answer: '林明', evidence: [{ chunk_id: chunk.id!, knowledge_id: doc.id!, source_start: 0, source_end: Array.from(source).length, source_quote: source }] }));
    const created = await request('POST', '/api/v1/rag-eval/datasets', { knowledge_base_id: kb.id!, review_mode: 'manual', entries });
    assert.equal(created.response.status, 200); const dataset = data(created);
    assert.equal((dataset.entries as JsonObject[]).length, 5);
    const published = await request('POST', `/api/v1/rag-eval/datasets/${dataset.id}/review`, { entry_ids: (dataset.entries as JsonObject[]).map(entry => entry.id!), status: 'approved', publish: true });
    assert.equal(published.response.status, 200); assert.equal(data(published).status, 'published');
    const run = await request('POST', '/api/v1/rag-eval/runs', { source: { type: 'tenant_dataset', dataset_id: dataset.id!, knowledge_base_id: kb.id! }, retrieval_strategy: 'keyword', rerank_enabled: false });
    assert.equal(run.response.status, 422); assert.equal(((run.response.body as JsonObject).error as JsonObject).code, 'needs_configuration');
    const active = await request('GET', '/api/v1/rag-eval/runs?active=true');
    assert.equal(active.response.status, 200); assert.deepEqual(data(active).runs, []); assert.equal(data(active).active_run, null);
    const graph = await request('GET', `/api/v1/knowledge-bases/${kb.id}/graph`);
    assert.equal(graph.response.status, 200); assert.equal(data(graph).state, 'disabled');
    assert.deepEqual(data(graph).nodes, []); assert.ok((data(graph).warnings as JsonObject[]).length > 0);
    const session = app.chat.create(issue.context, { title: 'Actor 权限核验', knowledge_base_ids: [] });
    const actors = await request('GET', `/api/v1/sessions/${session.id}/actors`);
    assert.equal(actors.response.status, 200); assert.deepEqual(data(actors).items, []);
    const other = app.auth.register({ email: 'other-evaluation@example.invalid', password: 'other-evaluation-password' });
    const denied = await app.dispatch({ protocol: 1, id: randomUUID(), method: 'GET', path: `/api/v1/rag-eval/datasets/${dataset.id}` }, { transport: 'ipc', access: other.credentials.access });
    assert.equal(denied.response.status, 404);
    assert.equal(app.database.get('select count(*) as n from model_usage')?.n, 0, 'missing configuration must not dispatch paid work');
  } finally { await app.close(); rmSync(root, { recursive: true, force: true }); }
});
