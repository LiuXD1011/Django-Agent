import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { CoreDatabase } from '../src/storage/database.js';
import { SearchIndex } from '../src/retrieval/index.js';

for (const query of ['晨星A', 'policy', '预']) {
  test(`keyword recall excludes unindexed chunks with NULL seq_id: ${query}`, () => {
    const directory = mkdtempSync(join(tmpdir(), 'marlin-fts-null-'));
    const db = new CoreDatabase(directory);
    try {
      const tenant = db.insert('tenants', { name: '验收空间', api_key: 'fixture-only' });
      const kb = db.insert('knowledge_bases', { tenant_id: tenant.id, name: '验收资料' });
      const doc = db.insert('knowledges', { tenant_id: tenant.id, knowledge_base_id: kb.id,
        title: '测试手册', type: 'file', source: 'upload' });
      const values = { tenant_id: tenant.id, knowledge_base_id: kb.id, knowledge_id: doc.id };
      const indexed = db.insert('chunks', { ...values, content: '晨星A policy 预算128000元', chunk_index: 0 });
      const unpublished = db.insert('chunks', { ...values, content: '完全无关的尚未索引内容', chunk_index: 1 });
      const matching = db.insert('chunks', { ...values, content: '晨星A policy 预算96000元', chunk_index: 2 });
      const scope = { tenantId: String(tenant.id), knowledgeBaseIds: [String(kb.id)] };
      const index = new SearchIndex(db);
      index.indexKeyword(scope, String(indexed.id));
      assert.equal(db.read('chunks', String(unpublished.id))?.seq_id, null);
      assert.equal(db.read('chunks', String(matching.id))?.seq_id, null);
      assert.equal(db.get('SELECT count(*) AS n FROM chunks_fts')?.n, 1);
      assert.deepEqual(index.keyword(scope, query, 10).map(hit => hit.chunk_id), [indexed.id]);
      index.indexKeyword(scope, String(matching.id));
      assert.deepEqual(new Set(index.keyword(scope, query, 10).map(hit => hit.chunk_id)),
        new Set([indexed.id, matching.id]));
    } finally {
      db.close();
      rmSync(directory, { recursive: true, force: true });
    }
  });
}
