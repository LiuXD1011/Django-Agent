import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { AuthService } from '../src/auth/index.js';
import type { ParsedDocument } from '../src/contracts.js';
import { DocumentParser } from '../src/documents/parser.js';
import { DocumentWorkflow } from '../src/documents/workflow.js';
import { JobQueue } from '../src/jobs/queue.js';
import { SearchIndex } from '../src/retrieval/search-index.js';
import { ModelConfigurationService } from '../src/settings/model-configuration.js';
import { CredentialVault } from '../src/storage/credentials.js';
import { CoreDatabase, type BindValue, type Row } from '../src/storage/database.js';
import { tableDefinitions } from '../src/storage/schema-manifest.js';

const sha = (value: string) => createHash('sha256').update(value).digest('hex');
const repeated = 'repeat budget ' + '中文😀资料'.repeat(15);
function source(texts: string[]): ParsedDocument {
  const canonical = texts.join('\n\n'); let offset = 0;
  return {
    document: { name: 'publication.txt', input_sha256: sha(canonical), canonical_sha256: sha(canonical), parser_version: 'publication-fixture-v1',
      canonicalization_version: 'blocks-double-newline-v1', offset_unit: 'unicode_code_point', canonical_text: canonical },
    blocks: texts.map((text, i) => {
      if (i) offset += 2;
      const start = offset; offset += Array.from(text).length;
      return { id: `source-${i}`, kind: 'text', block_index: i, block_type: 'text', text,
        canonical_range: { start, end: offset }, provenance: { page_index: i, source_ref: `page:${i}` }, metadata: { opaque_source: `meta-${i}` } };
    }), warnings: [], diagnostics: { fixture: 'real SQLite publication; deterministic parser output' },
  };
}
function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'marlin-bulk-publication-'));
  const db = new CoreDatabase(root), auth = new AuthService(db), jobs = new JobQueue(db), index = new SearchIndex(db);
  const ctx = auth.register({ username: 'bulk-owner', password: 'BulkPublication✓Password' }).context;
  const models = new ModelConfigurationService(db, auth, new CredentialVault(root));
  const kb = db.insert('knowledge_bases', { tenant_id: ctx.tenantId, name: 'publication',
    indexing_strategy: { keyword_enabled: true, vector_enabled: false, wiki_enabled: false, graph_enabled: false },
    chunking_config: { strategy: 'layout', parent_chunk_size: 512, child_chunk_size: 128, child_chunk_overlap: 0 } });
  let parsed = source([...Array.from({ length: 42 }, (_, i) => `record${String(i).padStart(3, '0')} budget😀 ` + '中文😀资料'.repeat(15)), '同文', '同文', repeated, repeated]);
  let beforeParseReturn: (() => void | Promise<void>) | undefined;
  const parser = new DocumentParser({ pythonExecutable: '/tmp/unused-publication-python', workerPath: '/tmp/unused-publication-worker.py' });
  parser.parse = async () => { await beforeParseReturn?.(); return parsed; };
  const workflow = new DocumentWorkflow(db, auth, jobs, models, undefined, { parser, index, scheduler: () => undefined });
  const upload = (name = 'publication.txt') => workflow.upload(ctx, String(kb.id), { name, bytes: Buffer.from('owned upload fixture') }, randomUUID());
  return { db, auth, jobs, index, ctx, kb, workflow, upload, scope: { tenantId: ctx.tenantId, knowledgeBaseIds: [String(kb.id)] },
    get parsed() { return parsed; }, set parsed(value: ParsedDocument) { parsed = value; },
    set beforeParseReturn(value: (() => void | Promise<void>) | undefined) { beforeParseReturn = value; },
    close: async () => { await jobs.close(); await workflow.close(); db.close(); rmSync(root, { recursive: true, force: true }); } };
}
const chunks = (db: CoreDatabase, id: string) => db.all('SELECT id FROM chunks WHERE knowledge_id=? ORDER BY chunk_index,id', id).map(row => db.read('chunks', row.id!)!);
function assertLinks(rows: Row[]) {
  const children = rows.filter(row => row.chunk_type === 'text');
  for (let i = 0; i < children.length; i++) {
    assert.equal(children[i]!.pre_chunk_id, children[i - 1]?.id ?? '');
    assert.equal(children[i]!.next_chunk_id, children[i + 1]?.id ?? '');
  }
}

test('first publication batches inserts, writes final neighbours once and preserves deduplication, parent sources and FTS', async t => {
  const f = fixture();
  try {
    const created = await f.upload();
    f.db.update('knowledges', created.knowledge.id!, { title: 'current title😀', tag_id: 'current-tag' });
    const run = f.db.run.bind(f.db), get = f.db.get.bind(f.db);
    const inserts: number[] = []; let rereads = 0, relinks = 0;
    f.db.run = ((sql: string, ...args: BindValue[]) => {
      if (sql.startsWith('INSERT INTO "chunks"')) inserts.push(args.length);
      if (/^UPDATE chunks SET pre_chunk_id=/.test(sql)) relinks++;
      return run(sql, ...args);
    }) as typeof f.db.run;
    f.db.get = ((sql: string, ...args: BindValue[]) => { if (/SELECT \* FROM "chunks"/.test(sql)) rereads++; return get(sql, ...args); }) as typeof f.db.get;
    const done = await f.jobs.run(created.task_id);
    f.db.run = run; f.db.get = get;
    assert.equal(done.status, 'completed', done.error);
    const rows = chunks(f.db, String(created.knowledge.id)), parents = rows.filter(row => row.chunk_type === 'parent_text'), children = rows.filter(row => row.chunk_type === 'text');
    assert.equal(parents.length, 46); assert.equal(children.length, 45);
    assert.equal(children.filter(row => row.content === '同文').length, 1, 'Only duplicate tiny child is skipped; both parents remain');
    assert.equal(children.filter(row => row.content === repeated).length, 2, 'Long repeated children are deliberately retained');
    const columns = tableDefinitions.find(table => table.name === 'chunks')!.columns.length;
    assert.equal(inserts.length, Math.ceil(rows.length / Math.floor(900 / columns)), 'Each insert must cover a bounded group, rather than one row');
    assert.equal(rereads, 0, 'First publication already knows IDs and must not SELECT * for each inserted row');
    assert.equal(relinks, 0, 'Deduplicated children already know their final adjacency before insertion');
    assert.ok(inserts.every(parameters => parameters <= 900));
    assertLinks(rows);
    assert.deepEqual(rows.map(row => row.chunk_index), Array.from({ length: rows.length }, (_, i) => i));
    const metadata = f.db.read('knowledges', created.knowledge.id!)!.metadata as any;
    assert.equal(metadata.content, f.parsed.document.canonical_text);
    assert.equal(metadata.workflow_status, 'completed');
    assert.equal(metadata.parser_blocks.length, 46);
    for (const row of rows) {
      const meta = row.metadata as any;
      assert.equal(row.tenant_id, Number(f.ctx.tenantId)); assert.equal(row.knowledge_base_id, f.kb.id);
      assert.equal(row.tag_id, 'current-tag'); assert.equal(row.content_hash, sha(String(row.content)));
      assert.equal(row.chunking_version, 'parent-child-v1'); assert.equal(meta.title, 'current title😀');
      assert.equal(meta.parser_version, 'publication-fixture-v1'); assert.equal(meta.offset_unit, 'unicode_code_point');
      assert.equal(meta.source_generation, metadata.source_generation);
      assert.ok(meta.source_refs.every((ref: any) => ref.opaque_source === `meta-${ref.block_index}` && ref.source_ref === `page:${ref.block_index}`));
      assert.equal(Array.from(metadata.content).slice(Number(row.start_at), Number(row.end_at)).join(''), row.content);
      if (row.chunk_type === 'parent_text') { assert.equal(row.is_enabled, false); assert.equal(row.pre_chunk_id, ''); assert.equal(row.next_chunk_id, ''); }
      else {
        const parent = parents.find(parent => parent.id === row.context_parent_id);
        assert.ok(parent); assert.ok(Number(parent.start_at) <= Number(row.start_at) && Number(parent.end_at) >= Number(row.end_at));
      }
    }
    assert.equal(f.db.get('SELECT count(*) AS n FROM chunks_fts')?.n, children.length);
    assert.equal(f.index.keyword(f.scope, 'record041', 10).length, 1);
    assert.equal(f.db.get('SELECT count(*) AS n FROM model_usage')?.n, 0);
    assert.deepEqual(f.db.all('PRAGMA foreign_key_check'), []);
    t.diagnostic(JSON.stringify({ parents: parents.length, retained_children: children.length, insert_statements: inserts.length,
      max_parameters: Math.max(...inserts), chunk_rereads: rereads, initial_neighbour_updates: relinks, model_calls: 0 }));
  } finally { await f.close(); }
});

test('flat chunk publication retains null parents and reads current keyword configuration at publication', async () => {
  const f = fixture();
  try {
    f.db.update('knowledge_bases', f.kb.id!, { chunking_config: { strategy: 'layout', enable_parent_child: false, chunk_size: 128, chunk_overlap: 0 } });
    f.beforeParseReturn = () => { f.db.update('knowledge_bases', f.kb.id!, { indexing_strategy: { keyword_enabled: false, vector_enabled: false, graph_enabled: false, wiki_enabled: false } }); };
    const created = await f.upload();
    assert.equal((await f.jobs.run(created.task_id)).status, 'completed');
    const rows = chunks(f.db, String(created.knowledge.id));
    assert.equal(rows.length, 45); assert.ok(rows.every(row => row.context_parent_id === null && row.chunk_type === 'text'));
    assertLinks(rows);
    assert.equal(f.db.get('SELECT count(*) AS n FROM chunks_fts')?.n, 0);
    assert.equal(f.db.get('SELECT count(*) AS n FROM model_usage')?.n, 0);
  } finally { await f.close(); }
});

test('a real fault after a completed insert batch rolls replacement chunks, canonical body and FTS back to the active generation', async () => {
  const f = fixture();
  try {
    const created = await f.upload(); assert.equal((await f.jobs.run(created.task_id)).status, 'completed');
    const id = String(created.knowledge.id), before = chunks(f.db, id), old = f.db.read('knowledges', id)!.metadata as any;
    const previousHit = f.index.keyword(f.scope, 'record041', 10).map(hit => hit.id);
    assert.equal(previousHit.length, 1);
    f.parsed = source(Array.from({ length: 48 }, (_, i) => `replacement${String(i).padStart(3, '0')} new publication😀 ` + '新内容'.repeat(20)));
    f.db.sqlite.exec("CREATE TRIGGER publication_late_batch_fault BEFORE INSERT ON chunks WHEN NEW.chunk_index=40 BEGIN SELECT RAISE(ABORT,'publication_late_batch_failure'); END");
    const reparse = await f.workflow.reparse(f.ctx, id, {}, randomUUID());
    assert.equal((await f.jobs.run(reparse.task_id)).status, 'failed');
    assert.deepEqual(chunks(f.db, id), before);
    const after = f.db.read('knowledges', id)!.metadata as any;
    assert.equal(after.source_generation, old.source_generation); assert.equal(after.content, old.content);
    assert.equal(after.workflow_status, 'failed');
    assert.deepEqual(f.index.keyword(f.scope, 'record041', 10).map(hit => hit.id), previousHit);
    assert.equal(f.index.keyword(f.scope, 'replacement047', 10).length, 0);
    assert.equal(f.db.get('SELECT count(*) AS n FROM chunks_fts')?.n, before.filter(row => row.chunk_type === 'text').length);
    assert.deepEqual(f.db.all('PRAGMA foreign_key_check'), []);
    assert.equal(f.db.get('SELECT count(*) AS n FROM model_usage')?.n, 0);
  } finally { await f.close(); }
});

test('a real deferred outer COMMIT fault after new FTS insertion rolls back the entire replacement generation', async () => {
  const f = fixture();
  try {
    const created = await f.upload(); assert.equal((await f.jobs.run(created.task_id)).status, 'completed');
    const id = String(created.knowledge.id), before = chunks(f.db, id), original = f.db.read('knowledges', id)!.metadata as any;
    const oldHit = f.index.keyword(f.scope, 'record041', 1)[0]!;
    f.parsed = source(Array.from({ length: 40 }, (_, i) => `newcommit${String(i).padStart(3, '0')} budget😀 ` + '新文'.repeat(25)));
    f.db.sqlite.exec(`CREATE TABLE publication_commit_fault(document_id TEXT REFERENCES knowledges(id), missing_base TEXT REFERENCES knowledge_bases(id));
      CREATE TRIGGER bulk_deferred_publication AFTER UPDATE ON knowledges
      WHEN json_extract(NEW.metadata,'$.source_generation') <> json_extract(OLD.metadata,'$.source_generation')
      BEGIN INSERT INTO publication_commit_fault(document_id,missing_base) VALUES(NEW.id,'missing-publication-base'); END`);
    const transaction = f.db.transaction.bind(f.db), run = f.db.run.bind(f.db);
    let newFtsRows = 0;
    f.db.transaction = work => transaction(() => { f.db.sqlite.pragma('defer_foreign_keys=ON'); return work(); });
    f.db.run = ((sql: string, ...args: BindValue[]) => {
      const result = run(sql, ...args);
      if (sql.startsWith('INSERT INTO chunks_fts')) newFtsRows += Number(result.changes);
      return result;
    }) as typeof f.db.run;
    const reparse = await f.workflow.reparse(f.ctx, id, {}, randomUUID());
    assert.equal((await f.jobs.run(reparse.task_id)).status, 'failed');
    assert.ok(newFtsRows > 0, 'The new FTS must actually have been written before the outer COMMIT fails');
    assert.deepEqual(chunks(f.db, id), before);
    const after = f.db.read('knowledges', id)!.metadata as any;
    assert.equal(after.content, original.content); assert.equal(after.source_generation, original.source_generation);
    assert.equal(f.index.keyword(f.scope, 'record041', 1)[0]!.id, oldHit.id);
    assert.equal(f.index.keyword(f.scope, 'newcommit039', 1).length, 0);
    assert.equal(f.db.get('SELECT count(*) AS n FROM chunks_fts')?.n, before.filter(row => row.chunk_type === 'text').length);
    assert.deepEqual(f.db.all('PRAGMA foreign_key_check'), []);
    assert.equal(f.db.get('SELECT count(*) AS n FROM model_usage')?.n, 0);
  } finally { await f.close(); }
});

for (const fence of ['cancel', 'revoked', 'pointer', 'owner'] as const)
  test(`the initial bulk publication rejects a late ${fence} fence without replacing existing content`, async () => {
    const f = fixture();
    try {
      const created = await f.upload(); assert.equal((await f.jobs.run(created.task_id)).status, 'completed');
      const id = String(created.knowledge.id), before = chunks(f.db, id), original = f.db.read('knowledges', id)!.metadata as any;
      const reparse = await f.workflow.reparse(f.ctx, id, {}, randomUUID());
      let cancellation: Promise<unknown> | undefined;
      f.beforeParseReturn = async () => {
        // cancel waits for this parser/handler to settle, so await it after run.
        if (fence === 'cancel') cancellation = f.workflow.cancel(f.ctx, id);
        if (fence === 'revoked') f.db.run("UPDATE tenant_members SET status='revoked' WHERE user_id=?", f.ctx.userId);
        if (fence === 'pointer') {
          const row = f.db.read('knowledges', id)!;
          f.db.update('knowledges', id, { metadata: { ...(row.metadata as any), workflow_job_id: 'replacement-pointer' } });
        }
        if (fence === 'owner') {
          const row = f.db.get('SELECT payload FROM desktop_jobs WHERE id=?', reparse.task_id)!;
          const payload = JSON.parse(String(row.payload));
          payload.claim.ownerToken = 'a-different-lease-owner';
          f.db.run('UPDATE desktop_jobs SET payload=? WHERE id=?', JSON.stringify(payload), reparse.task_id);
        }
      };
      const result = await f.jobs.run(reparse.task_id);
      await cancellation;
      assert.notEqual(result.status, 'completed');
      assert.deepEqual(chunks(f.db, id), before);
      const after = f.db.read('knowledges', id)!.metadata as any;
      assert.equal(after.source_generation, original.source_generation); assert.equal(after.content, original.content);
      assert.equal(f.db.get('SELECT count(*) AS n FROM chunks_fts')?.n, before.filter(row => row.chunk_type === 'text').length);
      assert.equal(f.db.get('SELECT count(*) AS n FROM model_usage')?.n, 0);
    } finally { await f.close(); }
  });
