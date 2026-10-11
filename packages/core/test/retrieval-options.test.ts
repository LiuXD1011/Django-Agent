import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { CoreApplication } from '../src/application.js';
import { retrievalOptions } from '../src/adapters/retrieval-options.js';
import { RetrievalService } from '../src/retrieval/index.js';

test('actual application retrieval applies persisted legacy stage thresholds and defaults to scoped FTS results', async () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-retrieval-options-'));
  const app = new CoreApplication(root, { allowAutoSetup: true });
  try {
    const ctx = app.auth.autoSetup({ password: 'retrieval-options-only-password' }).context;
    const kb = app.knowledge.knowledgeBases.create(ctx, { name: '阈值回归' });
    const scope = { tenantId: ctx.tenantId, knowledgeBaseIds: [String(kb.id)] };
    const defaults = retrievalOptions(app, ctx, scope);
    assert.equal(defaults.vectorTopK, 10); assert.equal(defaults.vectorThreshold, 0.15);
    assert.equal(defaults.keywordThreshold, 0.3); assert.equal(defaults.rerankTopK, 5); assert.equal(defaults.rerankThreshold, 0.3);
    const doc = app.database.insert('knowledges', { tenant_id: ctx.tenantId, knowledge_base_id: kb.id, title: '阈值资料', parse_status: 'completed' });
    for (let n = 0; n < 3; n++) {
      const chunk = app.database.insert('chunks', { tenant_id: ctx.tenantId, knowledge_base_id: kb.id, knowledge_id: doc.id, seq_id: String(n + 1), content: `海盐阈值记录 ${n}` });
      app.searchIndex.indexKeyword(scope, String(chunk.id));
    }
    app.settings.setKV(ctx, 'retrieval', { keyword_threshold: 1, vector_threshold: 0.7, rerank_threshold: 0.9, embedding_top_k: 8, keyword_top_k: 3, rerank_enabled: false });
    const options = retrievalOptions(app, ctx, scope), service = new RetrievalService(app.searchIndex), result = await service.search(scope, '海盐阈值', options);
    assert.equal(options.vectorTopK, 8); assert.equal(options.rerankTopK, 0);
    assert.deepEqual(result.meta.thresholds, { keyword: 1, vector: 0.7, rerank: 0.9 });
    assert.equal(result.results.length, 1); assert.equal(result.meta.filtered_counts.keyword, 2);
    const empty = { tenantId: ctx.tenantId, knowledgeBaseIds: [] };
    assert.equal((await service.search(empty, '海盐阈值', retrievalOptions(app, ctx, empty))).results.length, 0);
  } finally { await app.close(); rmSync(root, { recursive: true, force: true }); }
});
