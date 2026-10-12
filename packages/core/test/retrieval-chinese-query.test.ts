import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { SearchIndex } from '../src/retrieval/search-index.js';
import { RetrievalService } from '../src/retrieval/service.js';
import { CoreDatabase } from '../src/storage/database.js';

function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'marlin-chinese-query-'));
  const db = new CoreDatabase(root);
  const tenant = db.insert('tenants', { name: 'Query fixture', api_key: 'fixture-only' });
  const kb = db.insert('knowledge_bases', { tenant_id: tenant.id, name: 'Query namespace' });
  const document = db.insert('knowledges', { tenant_id: tenant.id, knowledge_base_id: kb.id, title: 'Source' });
  const index = new SearchIndex(db), scope = { tenantId: String(tenant.id), knowledgeBaseIds: [String(kb.id)] };
  let sequence = 1152921504606846976n;
  const chunk = (id: string, content: string, values: Record<string, unknown> = {}) => db.insert('chunks', {
    id, tenant_id: tenant.id, knowledge_base_id: kb.id, knowledge_id: document.id,
    seq_id: sequence++, chunk_index: 0, content, ...values,
  });
  const add = (id: string, content: string) => { const row = chunk(id, content); index.indexKeyword(scope, id); return row; };
  return { db, tenant, kb, document, index, scope, chunk, add,
    close() { db.close(); rmSync(root, { recursive: true, force: true }); } };
}
const ids = (rows: Array<{ chunk_id: string }>) => rows.map(row => row.chunk_id);

// Regression: real Chinese evaluation questions returned zero FTS candidates despite current source evidence.
test('Chinese questions recall answer-bearing source phrases rather than require the entire question', async () => {
  const f = fixture();
  try {
    f.add('target', 'P1故障首次响应须在15分钟内完成。');
    f.add('distractor', '现行手册中列出了其他项目的故障处理方式。');
    const query = '按照晨星项目现行手册，P1故障首次响应应在多少分钟内？';
    assert.equal(f.index.keyword(f.scope, query, 1)[0]?.chunk_id, 'target');
    const result = await new RetrievalService(f.index).search(f.scope, query, { strategy: 'keyword', rerankTopK: 0 });
    assert.equal(result.results[0]?.chunk_id, 'target');
    assert.equal(result.results[0]?.seq_id, '1152921504606846976');
    assert.equal(result.meta.score_metrics.keyword, 'fts5_bm25');
    assert.deepEqual(result.meta.usage, {});
  } finally { f.close(); }
});

test('mixed Chinese entity and version queries preserve consecutive letters and digits', () => {
  const f = fixture();
  try {
    f.add('a', '晨星A项目交付80套。'); f.add('b', '晨星B项目交付40套。');
    assert.deepEqual(ids(f.index.keyword(f.scope, '请问晨星A具体有多少套？', 1)), ['a']);
    f.add('version', 'v3.2于2026年09月30日生效。');
    assert.deepEqual(ids(f.index.keyword(f.scope, 'v3.2', 1)), ['version']);
  } finally { f.close(); }
});

test('Unicode query windows use codepoints and retain punctuation and short literal behavior', () => {
  const f = fixture();
  try {
    f.add('astral', '𠮷野家预算为10元。');
    assert.deepEqual(ids(f.index.keyword(f.scope, '𠮷野家预算是多少？', 1)), ['astral']);
    f.add('literal', '预算%_\\😀。');
    for (const query of ['预算', '%', '_', '\\', '😀', '。']) assert.ok(ids(f.index.keyword(f.scope, query, 10)).includes('literal'), query);
    assert.deepEqual(f.index.keyword(f.scope, '完全不同内容', 10), []);
  } finally { f.close(); }
});

test('Chinese question scope and live source filters apply before the requested limit', () => {
  const f = fixture();
  try {
    const foreignTenant = f.db.insert('tenants', { name: 'Foreign', api_key: 'foreign-fixture-only' });
    const foreignKb = f.db.insert('knowledge_bases', { tenant_id: foreignTenant.id, name: 'Foreign' });
    const foreignDoc = f.db.insert('knowledges', { tenant_id: foreignTenant.id, knowledge_base_id: foreignKb.id, title: 'Source' });
    const excludedKb = f.db.insert('knowledge_bases', { tenant_id: f.tenant.id, name: 'Excluded' });
    const excludedDoc = f.db.insert('knowledges', { tenant_id: f.tenant.id, knowledge_base_id: excludedKb.id, title: 'Source' });
    for (let i = 0; i < 12; i++) {
      const id = `foreign-${i}`;
      f.chunk(id, '故障首次响应'.repeat(6), { tenant_id: foreignTenant.id, knowledge_base_id: foreignKb.id, knowledge_id: foreignDoc.id });
      f.index.indexKeyword({ tenantId: String(foreignTenant.id) }, id);
    }
    f.chunk('excluded', '故障首次响应'.repeat(6), { knowledge_base_id: excludedKb.id, knowledge_id: excludedDoc.id });
    f.index.indexKeyword({ tenantId: String(f.tenant.id) }, 'excluded');
    f.add('enabled', '故障首次响应在15分钟内。');
    f.add('disabled', '故障首次响应'.repeat(6)); f.db.update('chunks', 'disabled', { is_enabled: false });
    f.add('deleted', '故障首次响应'.repeat(6)); f.db.update('chunks', 'deleted', { deleted_at: new Date().toISOString() });
    f.add('parent', '故障首次响应'.repeat(6)); f.db.update('chunks', 'parent', { chunk_type: 'parent_text' });
    f.add('mismatched', '故障首次响应'.repeat(6)); f.db.update('chunks', 'mismatched', { knowledge_id: foreignDoc.id });
    const query = '故障首次响应应该多久完成？';
    assert.deepEqual(ids(f.index.keyword(f.scope, query, 1)), ['enabled']);
    assert.deepEqual(f.index.keyword({ ...f.scope, knowledgeBaseIds: [] }, query, 1), []);
    f.db.update('knowledges', String(f.document.id), { enable_status: 'disabled' });
    assert.deepEqual(f.index.keyword(f.scope, query, 1), []);
  } finally { f.close(); }
});

test('reindexed source changes remove obsolete Chinese query matches', () => {
  const f = fixture();
  try {
    f.add('edited', '故障首次响应在15分钟内。');
    const query = '故障首次响应应该多久完成？';
    assert.deepEqual(ids(f.index.keyword(f.scope, query, 10)), ['edited']);
    f.db.update('chunks', 'edited', { content: '本季度采购清单。' }); f.index.indexKeyword(f.scope, 'edited');
    assert.deepEqual(f.index.keyword(f.scope, query, 10), []);
    assert.deepEqual(ids(f.index.keyword(f.scope, '季度采购清单有哪些？', 10)), ['edited']);
  } finally { f.close(); }
});

test('English natural-language terms still use FTS while short literals use scoped LIKE', async () => {
  const f = fixture();
  try {
    f.add('english', 'Paris is the capital of France.'); f.add('short', 'go');
    for (const [query, expected, metric] of [['What is the capital of France?', 'english', 'fts5_bm25'], ['go', 'short', 'scoped_like']] as const) {
      const result = await new RetrievalService(f.index).search(f.scope, query, { strategy: 'keyword', rerankTopK: 0 });
      assert.deepEqual(ids(result.results), [expected]); assert.equal(result.meta.score_metrics.keyword, metric);
    }
  } finally { f.close(); }
});
