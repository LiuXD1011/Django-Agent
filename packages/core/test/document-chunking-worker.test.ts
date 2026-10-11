import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import test from 'node:test';
import { AuthService } from '../src/auth/index.js';
import type { ParsedDocument } from '../src/contracts.js';
import { ChunkingWorkers } from '../src/documents/chunking-workers.js';
import { DocumentParser } from '../src/documents/parser.js';
import { DocumentWorkflow } from '../src/documents/workflow.js';
import { JobQueue } from '../src/jobs/queue.js';
import { SearchIndex } from '../src/retrieval/search-index.js';
import { ModelConfigurationService } from '../src/settings/model-configuration.js';
import { CoreDatabase } from '../src/storage/database.js';
import { CredentialVault } from '../src/storage/credentials.js';

const sha = (content: string) => createHash('sha256').update(content).digest('hex');
function parsed(content: string): ParsedDocument {
  return {
    document: { name: '线程分块.txt', input_sha256: sha(content), parser_version: 'explicit-test-parser',
      canonicalization_version: 'blocks-double-newline-v1', offset_unit: 'unicode_code_point',
      canonical_text: content, canonical_sha256: sha(content) },
    blocks: [{ id: 'text-1', kind: 'text', block_index: 0, block_type: 'text', text: content,
      canonical_range: { start: 0, end: Array.from(content).length }, provenance: {}, metadata: {} }],
    warnings: [], diagnostics: {},
  };
}
async function fixture(content: string) {
  const root = mkdtempSync(join(tmpdir(), 'marlin-workflow-chunk-worker-'));
  const db = new CoreDatabase(root), auth = new AuthService(db), jobs = new JobQueue(db);
  const ctx = auth.register({ username: 'worker-owner', password: 'WorkerFixture✓Password' }).context;
  const models = new ModelConfigurationService(db, auth, new CredentialVault(root));
  const index = new SearchIndex(db);
  const kb = db.insert('knowledge_bases', { tenant_id: ctx.tenantId, name: 'Worker 资料',
    indexing_strategy: { keyword_enabled: true, vector_enabled: false, graph_enabled: false, wiki_enabled: false } });
  // Parser is an explicitly labelled test substitute; SQLite, queue, chunking
  // thread, publication and cancellation below are the actual implementations.
  const parser = new DocumentParser({ pythonExecutable: process.env.MARLIN_TEST_PYTHON ?? '/tmp/marlin-parser-isolation-20261010/bin/python',
    workerPath: resolve('../../workers/document/worker.py') });
  parser.parse = async () => parsed(content);
  const workflow = new DocumentWorkflow(db, auth, jobs, models, undefined, { parser, index, scheduler: () => undefined });
  const owned = (workflow as unknown as { chunker?: ChunkingWorkers }).chunker;
  const scope = { tenantId: ctx.tenantId, userId: ctx.userId };
  return { root, db, auth, jobs, ctx, index, kb, workflow, owned, scope,
    upload: () => workflow.upload(ctx, String(kb.id), { name: '线程分块.txt', bytes: Buffer.from(content) }, randomUUID()),
    close: async () => { await Promise.all([workflow.close(), jobs.close()]); db.close(); rmSync(root, { recursive: true, force: true }); },
  };
}
async function started(f: Awaited<ReturnType<typeof fixture>>, task: string) {
  for (let i = 0; i < 1000; i++) {
    if (f.jobs.events(task, f.scope).some(event => event.type === 'chunking.progress' && event.data.progress === 0)) return;
    assert.equal(f.jobs.get(task, f.scope).status, 'running', 'job must still be running while awaiting real Worker start');
    await delay(5);
  }
  assert.fail('actual chunking Worker did not report its start');
}

test('DocumentWorkflow owns the real chunking worker and publishes exact Unicode sources and FTS', async () => {
  const content = '# 可信来源😀\n\nQ1=100，Q2=200。\n\nuniqueWorkerFact20261011';
  const f = await fixture(content);
  try {
    assert.ok(f.owned instanceof ChunkingWorkers, 'DocumentWorkflow must own a ChunkingWorkers instance');
    const created = await f.upload(), result = await f.jobs.run(created.task_id);
    assert.equal(result.status, 'completed', result.error);
    const row = f.db.read('knowledges', String(created.knowledge.id))!;
    assert.equal((row.metadata as any).content, content);
    assert.equal((row.metadata as any).workflow_status, 'completed');
    assert.ok(f.jobs.events(created.task_id, f.scope).some(event => event.type === 'chunking.progress'));
    const hits = f.index.keyword({ tenantId: f.ctx.tenantId, knowledgeBaseIds: [String(f.kb.id)] }, 'uniqueWorkerFact20261011', 1);
    assert.equal(hits[0]?.knowledge_id, row.id);
    assert.match(hits[0]!.content, /uniqueWorkerFact20261011/);
    assert.equal(f.db.get('SELECT count(*) AS n FROM model_usage')?.n, 0);
  } finally { await f.close(); }
});

for (const operation of ['cancel', 'close'] as const) {
  test(`actual computation start allows ${operation} before publication and ends owned work`, async () => {
    const content = Array.from({ length: 12000 }, (_, i) => `${i} 原始收入😀 Q1=100; preserved Unicode source.\n`).join('');
    const f = await fixture(content);
    try {
      assert.ok(f.owned instanceof ChunkingWorkers, 'DocumentWorkflow must own a ChunkingWorkers instance');
      const created = await f.upload(), running = f.jobs.run(created.task_id);
      await started(f, created.task_id);
      // This callback runs in the core after the Worker has actually started.
      // Cancellation reaching this point proves it can run during computation.
      if (operation === 'cancel') await f.workflow.cancel(f.ctx, String(created.knowledge.id));
      else await f.workflow.close();
      const result = await running;
      assert.equal(result.status, 'cancelled');
      assert.equal(f.db.get('SELECT count(*) AS n FROM chunks WHERE knowledge_id=?', created.knowledge.id!)?.n, 0);
      const row = f.db.read('knowledges', String(created.knowledge.id))!;
      assert.equal((row.metadata as any).workflow_status, 'cancelled');
      assert.equal(row.pending_subtasks_count, 0);
      assert.equal(f.db.get("SELECT count(*) AS n FROM knowledge_processing_spans WHERE knowledge_id=? AND status='running'", row.id!)?.n, 0);
      assert.equal(f.db.get('SELECT count(*) AS n FROM model_usage')?.n, 0);
      if (operation === 'close') {
        await assert.rejects(f.owned.split(parsed('next'), {}, { title: 'next' }), (error: any) => error.code === 'chunking_closed');
      } else {
        const next = await f.workflow.reparse(f.ctx, String(row.id), {}, randomUUID());
        assert.equal((await f.jobs.run(next.task_id)).status, 'completed');
        assert.equal((f.db.read('knowledges', String(row.id))!.metadata as any).content, content);
      }
    } finally { await f.close(); }
  });
}

test('an unavailable owned chunking service fails the job without publishing empty content', async () => {
  const f = await fixture('valid original text');
  try {
    assert.ok(f.owned instanceof ChunkingWorkers, 'DocumentWorkflow must own a ChunkingWorkers instance');
    await f.owned.close();
    const created = await f.upload(), result = await f.jobs.run(created.task_id);
    assert.equal(result.status, 'failed');
    assert.equal(f.db.get('SELECT count(*) AS n FROM chunks WHERE knowledge_id=?', created.knowledge.id!)?.n, 0);
    assert.equal((f.db.read('knowledges', String(created.knowledge.id))!.metadata as any).workflow_status, 'failed');
    assert.equal(f.db.get('SELECT count(*) AS n FROM model_usage')?.n, 0);
  } finally { await f.close(); }
});
