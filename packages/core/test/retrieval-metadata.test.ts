import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { CoreDatabase } from '../src/storage/database.js';
import { SearchIndex } from '../src/retrieval/search-index.js';
import { RetrievalService } from '../src/retrieval/service.js';
import type { EmbeddingBinding } from '../src/retrieval/types.js';

// R-VECTOR-METADATA: the real five-gold run lost unchanged chunks after auxiliary document updates.
test('summary and workflow metadata updates keep unchanged source vectors searchable', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'marlin-vector-metadata-'));
  const db = new CoreDatabase(directory);
  try {
    const tenant = db.insert('tenants', { name: '独立回归空间', api_key: 'fixture-only' });
    const kb = db.insert('knowledge_bases', { tenant_id: tenant.id, name: '独立回归库' });
    const doc = db.insert('knowledges', { tenant_id: tenant.id, knowledge_base_id: kb.id,
      title: '手册', type: 'file', source: 'upload', metadata: { content: '负责人林青，预算128000元。', source_generation: 'source-v1', workflow_status: 'processing' } });
    const chunk = db.insert('chunks', { tenant_id: tenant.id, knowledge_base_id: kb.id,
      knowledge_id: doc.id, content: '负责人林青，预算128000元。', context_header: '晨星A', chunk_index: 0 });
    const scope = { tenantId: String(tenant.id), knowledgeBaseIds: [String(kb.id)] };
    let embeddingCalls = 0;
    const binding: EmbeddingBinding = { signature: 'controlled-embedding:2', dimension: 2,
      runtime: { async embed(texts) { embeddingCalls++; return { vectors: texts.map(() => [1, 0]),
        usage: { prompt_tokens: texts.length, completion_tokens: 0, total_tokens: texts.length, cached_tokens: 0, reasoning_tokens: 0 } }; } } };
    const index = new SearchIndex(db);
    await index.rebuild(scope, binding);
    assert.deepEqual(index.vector(scope, [1, 0], binding, 10).map(hit => hit.chunk_id), [chunk.id]);
    db.update('knowledges', String(doc.id), { description: '生成的摘要', metadata: {
      content: '负责人林青，预算128000元。', source_generation: 'source-v1', workflow_status: 'completed',
      vector_status: 'ready', summary: '生成的摘要', wiki_status: 'completed' } });
    assert.equal(index.state(scope)[0]?.status, 'ready');
    assert.deepEqual(index.vector(scope, [1, 0], binding, 10).map(hit => hit.chunk_id), [chunk.id],
      'Unchanged embedding input must remain searchable after summary/wiki/workflow bookkeeping');
    assert.equal(embeddingCalls, 1);
    db.update('knowledges', String(doc.id), { metadata: { source_generation: 'source-v2' } });
    assert.deepEqual(index.vector(scope, [1, 0], binding, 10), [], 'A different source generation must remain fenced');
    const stale = await new RetrievalService(index).search(scope, '负责人', {
      strategy: 'vector', embedding: binding, rerankTopK: 0 });
    assert(stale.meta.degradations.some(item => item.reason === 'vector_reindex_required'),
      'A stale generation must explicitly request rebuilding instead of silently returning no candidates');
    assert.equal(embeddingCalls, 1, 'A known stale generation must be rejected before paid query embedding');
  } finally { db.close(); rmSync(directory, { recursive: true, force: true }); }
});
