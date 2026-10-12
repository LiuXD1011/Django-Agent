import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtempSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import type { AuthContext, JsonObject, ParsedDocument } from '../src/contracts.js';
import { splitDocument } from '../src/documents/chunker.js';
import { IsolatedEvaluationIndex } from '../src/evaluation/isolated-index.js';
import { SearchIndex } from '../src/retrieval/search-index.js';
import { CoreDatabase } from '../src/storage/database.js';

const hash = (text: string) => createHash('sha256').update(text).digest('hex');
function textBlock(text: string, index: number, start = 0) {
  return { id: `text-${index}`, kind: 'text', block_index: index, block_type: 'paragraph', text,
    canonical_range: { start, end: start + Array.from(text).length }, provenance: {}, metadata: {} };
}

function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'marlin-eval-image-source-')), db = new CoreDatabase(root);
  const tenant = db.insert('tenants', { name: 'Source boundary fixture', space_type: 'legacy' });
  const ctx: AuthContext = { userId: 'trusted-fixture', tenantId: String(tenant.id), deviceId: 'fixture', role: 'owner', isSystemAdmin: false };
  const kb = db.insert('knowledge_bases', { tenant_id: ctx.tenantId, name: 'Actual full corpus fixture' });
  const content = '晨星项目负责人林青 😀，P1故障首次响应为15分钟。';
  const text = db.insert('knowledges', { tenant_id: ctx.tenantId, knowledge_base_id: kb.id, title: '真实手册', parse_status: 'completed',
    file_hash: hash(content), metadata: { content, parser_blocks: [textBlock(content, 0)], parser_image_block_indices: [], source_generation: 'text-current' } });
  const chunk = db.insert('chunks', { tenant_id: ctx.tenantId, knowledge_base_id: kb.id, knowledge_id: text.id, chunk_type: 'text',
    content, start_at: 0, end_at: Array.from(content).length, is_enabled: true });
  const image = db.insert('knowledges', { tenant_id: ctx.tenantId, knowledge_base_id: kb.id, title: '合法纯图片.png', parse_status: 'completed',
    file_hash: hash('isolated-image-fixture'), metadata: { content: '', parser_blocks: [], parser_image_block_indices: [0], source_generation: 'image-current' } });
  const index = new SearchIndex(db), scope = { tenantId: ctx.tenantId, knowledgeBaseIds: [String(kb.id)] };
  index.indexKeyword(scope, String(chunk.id));
  return { root, db, ctx, kbId: String(kb.id), textId: String(text.id), imageId: String(image.id), content, index, scope,
    close() { db.close(); rmSync(root, { recursive: true, force: true }); } };
}

// Orca H-03: recursive/keyword/no-rerank failed on legal image-only source with image block 0.
test('full corpus keeps legal image-only documents without inventing a text block that collides with image zero', async () => {
  const f = fixture();
  try {
    const documents = f.db.all('SELECT * FROM knowledges ORDER BY id'), chunks = f.db.all('SELECT * FROM chunks ORDER BY id');
    const originalHits = f.index.keyword(f.scope, '林青', 10);
    for (const strategy of ['recursive', 'heading', 'layout', 'record', 'auto_parent_child']) {
      const derived = await IsolatedEvaluationIndex.build(f.db, f.ctx, f.kbId, strategy);
      try {
        assert.equal(derived.diagnostics.corpus_documents, 2);
        assert.equal(derived.diagnostics.full_corpus, true);
        assert.equal(derived.db.read('knowledges', f.imageId)?.metadata && (derived.db.read('knowledges', f.imageId)!.metadata as JsonObject).content, '');
        assert.equal(derived.db.get('SELECT count(*) n FROM chunks WHERE knowledge_id=?', f.imageId)!.n, 0);
        assert.ok(derived.index.keyword(f.scope, '林青', 10).some(hit => hit.knowledge_id === f.textId));
        for (const chunk of derived.db.all('SELECT * FROM chunks WHERE knowledge_id=?', f.textId)) {
          assert.equal(Array.from(f.content).slice(Number(chunk.start_at), Number(chunk.end_at)).join(''), chunk.content);
        }
      } finally { await derived.close(); }
    }
    assert.deepEqual(f.db.all('SELECT * FROM knowledges ORDER BY id'), documents);
    assert.deepEqual(f.db.all('SELECT * FROM chunks ORDER BY id'), chunks);
    assert.deepEqual(f.index.keyword(f.scope, '林青', 10), originalHits);
    assert.equal(f.db.get('SELECT count(*) n FROM model_usage')!.n, 0);
    assert.deepEqual(readdirSync(join(f.root, '.cache', 'evaluation-isolated')), []);
  } finally { f.close(); }
});

test('duplicate persisted image barrier indices fail explicitly instead of becoming two invented copies of one image', async () => {
  const f = fixture();
  let unexpected: IsolatedEvaluationIndex | undefined;
  try {
    f.db.update('knowledges', f.imageId, { metadata: { content: '', parser_blocks: [], parser_image_block_indices: [2, 2] } });
    await assert.rejects(async () => { unexpected = await IsolatedEvaluationIndex.build(f.db, f.ctx, f.kbId, 'recursive'); }, { code: 'evaluation_parser_blocks_invalid', status: 422 });
    assert.deepEqual(readdirSync(join(f.root, '.cache', 'evaluation-isolated')), []);
  } finally { await unexpected?.close(); f.close(); }
});

test('real mixed text-image-text barriers retain separate parents and exact Unicode source offsets', async () => {
  const f = fixture();
  try {
    f.db.update('knowledges', f.imageId, { enable_status: 'disabled' });
    const first = '左侧说明😀', second = '右侧说明林青', content = `${first}\n\n${second}`, secondStart = Array.from(first).length + 2;
    f.db.update('knowledges', f.textId, { metadata: { content, parser_blocks: [textBlock(first, 0), textBlock(second, 2, secondStart)], parser_image_block_indices: [1] } });
    const derived = await IsolatedEvaluationIndex.build(f.db, f.ctx, f.kbId, 'recursive');
    try {
      const parents = derived.db.all('SELECT content,start_at,end_at FROM chunks WHERE chunk_type=? ORDER BY start_at', 'parent_text');
      assert.deepEqual(parents.map(row => row.content), [first, second]);
      for (const row of parents) assert.equal(Array.from(content).slice(Number(row.start_at), Number(row.end_at)).join(''), row.content);
      assert.equal(derived.diagnostics.corpus_documents, 1);
    } finally { await derived.close(); }
  } finally { f.close(); }
});

test('invalid negative, fractional and text-colliding image indices still reject the full corpus', async () => {
  const f = fixture();
  try {
    for (const indices of [[-1], [0.5], [0]]) {
      f.db.update('knowledges', f.imageId, { enable_status: 'disabled' });
      f.db.update('knowledges', f.textId, { metadata: { content: f.content, parser_blocks: [textBlock(f.content, 0)], parser_image_block_indices: indices } });
      await assert.rejects(IsolatedEvaluationIndex.build(f.db, f.ctx, f.kbId, 'recursive'), { code: 'evaluation_parser_blocks_invalid', status: 422 });
      assert.deepEqual(readdirSync(join(f.root, '.cache', 'evaluation-isolated')), []);
    }
  } finally { f.close(); }
});

test('empty text and nonempty legacy canonical fallback preserve their previous text-only semantics', async () => {
  const f = fixture();
  try {
    f.db.update('knowledges', f.imageId, { title: '空TXT', metadata: { content: '', parser_blocks: [], parser_image_block_indices: [] } });
    f.db.update('knowledges', f.textId, { metadata: { content: f.content, parser_blocks: [], parser_image_block_indices: [] } });
    const derived = await IsolatedEvaluationIndex.build(f.db, f.ctx, f.kbId, 'recursive');
    try {
      assert.equal(derived.diagnostics.corpus_documents, 2);
      assert.equal(derived.db.get('SELECT count(*) n FROM chunks WHERE knowledge_id=?', f.imageId)!.n, 0);
      assert.ok(derived.index.keyword(f.scope, '林青', 10).some(hit => hit.knowledge_id === f.textId));
    } finally { await derived.close(); }
    assert.throws(() => IsolatedEvaluationIndex.sourceDocuments(f.db, { ...f.ctx, tenantId: '999' }, f.kbId), { code: 'knowledge_base_not_found' });
  } finally { f.close(); }
});

test('semantic full corpus with empty text and image-only documents does not dispatch empty embedding callbacks', async () => {
  const f = fixture(), batches: string[][] = [];
  try {
    f.db.update('knowledges', f.textId, { metadata: { content: '', parser_blocks: [], parser_image_block_indices: [] } });
    const derived = await IsolatedEvaluationIndex.build(f.db, f.ctx, f.kbId, 'semantic_parent_child', {
      semanticDimension: 2, semanticSignature: 'deterministic-test-vectors',
      semanticEmbed: async texts => { batches.push([...texts]); return texts.map(() => [1, 0]); },
    });
    try {
      assert.deepEqual(batches, [], 'empty sources must not enter a model callback or its invocation ledger');
      assert.equal(derived.diagnostics.corpus_documents, 2);
      assert.equal(derived.db.get('SELECT count(*) n FROM knowledges')!.n, 2);
      assert.equal(derived.diagnostics.chunk_count, 0);
      assert.equal(derived.diagnostics.parent_count, 0);
      assert.deepEqual(derived.diagnostics.selected_strategies, ['semantic']);
      assert.equal(f.db.get('SELECT count(*) n FROM model_usage')!.n, 0);
    } finally { await derived.close(); }
  } finally { f.close(); }
});

test('nonempty semantic source uses actual deterministic vectors while its image-only neighbor requires no callback', async () => {
  const f = fixture(), batches: string[][] = [];
  try {
    const derived = await IsolatedEvaluationIndex.build(f.db, f.ctx, f.kbId, 'semantic_parent_child', {
      semanticDimension: 2, semanticSignature: 'deterministic-test-vectors',
      semanticEmbed: async texts => { batches.push([...texts]); return texts.map(() => [1, 0]); },
    });
    try {
      assert.equal(batches.length, 1, 'only the nonempty text document is embedded');
      assert.ok(batches[0]!.length > 0 && batches[0]!.every(text => text.trim()));
      assert.equal(derived.diagnostics.corpus_documents, 2);
      assert.deepEqual(derived.diagnostics.selected_strategies, ['semantic']);
      assert.ok(derived.index.keyword(f.scope, '林青', 10).some(hit => hit.knowledge_id === f.textId));
      assert.equal(derived.db.get('SELECT count(*) n FROM chunks WHERE knowledge_id=?', f.imageId)!.n, 0);
      assert.equal(f.db.get('SELECT count(*) n FROM model_usage')!.n, 0);
    } finally { await derived.close(); }
  } finally { f.close(); }
});

test('empty semantic splitter validates configuration and cancellation while reporting that no embedding was needed', async () => {
  for (const content of ['', ' \n\t']) {
    const parsed: ParsedDocument = {
      document: { name: 'empty-source', input_sha256: hash(content), parser_version: 'parser-empty-source-fixture',
        canonicalization_version: 'blocks-double-newline-v1', offset_unit: 'unicode_code_point',
        canonical_text: content, canonical_sha256: hash(content) },
      blocks: [], warnings: [], diagnostics: {},
    };
    const result = await splitDocument(parsed, { strategy: 'semantic' }, { title: '空来源' });
    assert.deepEqual(result.parents, []); assert.deepEqual(result.children, []);
    assert.deepEqual(result.diagnostics.fallback_chain, []);
    assert.equal(result.diagnostics.requested_strategy, 'semantic');
    assert.equal(result.diagnostics.selected_strategy, 'semantic');
    assert.equal(result.diagnostics.semantic_embedding_skipped, 'empty_text_source');
    await assert.rejects(splitDocument(parsed, { strategy: 'semantic', token_limit: -1 }, { title: '' }), { code: 'invalid_chunking_config' });
    const controller = new AbortController(), reason = new Error('cancel empty semantic source'); controller.abort(reason);
    await assert.rejects(splitDocument(parsed, { strategy: 'semantic' }, { title: '', signal: controller.signal }), error => error === reason);
  }
});
