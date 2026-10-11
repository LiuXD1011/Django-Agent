import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import test from 'node:test';
import { CoreApplication } from '../src/application.js';
import { AuthService } from '../src/auth/index.js';
import { DocumentParser } from '../src/documents/parser.js';
import { JobQueue } from '../src/jobs/queue.js';
import { CoreDatabase } from '../src/storage/database.js';

// Persisted crash-state fixtures; no model provider or successful output is simulated.
for (const scenario of ['new-upload', 'published-content', 'already-interrupted', 'superseded-attempt'] as const) {
  test(`application startup reconciles ${scenario} document telemetry without replaying manual work`, async () => {
    const directory = mkdtempSync(join(tmpdir(), 'marlin-document-startup-recovery-'));
    let app: CoreApplication | undefined;
    const db = new CoreDatabase(directory), auth = new AuthService(db), queue = new JobQueue(db);
    const ctx = auth.register({ username: 'recovery-fixture', password: 'Recovery unit fixture password #1' }).context;
    const kb = db.insert('knowledge_bases', { tenant_id: ctx.tenantId, name: 'Recovery fixture' });
    const published = scenario === 'published-content';
    const doc = db.insert('knowledges', {
      tenant_id: ctx.tenantId, knowledge_base_id: kb.id, title: 'Interrupted source',
      parse_status: published ? 'completed' : 'processing', processed_at: published ? new Date().toISOString() : null,
      pending_subtasks_count: 1, metadata: { content: published ? 'Preserved original source😀' : '', source_generation: 'original-generation' },
    });
    const job = queue.create({ scope: { tenantId: ctx.tenantId, userId: ctx.userId }, kind: 'process_knowledge',
      requestId: randomUUID(), recoveryPolicy: 'manual', payload: { knowledge_id: doc.id!, knowledge_base_id: kb.id!, auth: ctx as any } });
    db.run('UPDATE desktop_jobs SET status=?,attempt=1,payload=? WHERE id=?',
      scenario === 'already-interrupted' ? 'interrupted' : 'running',
      JSON.stringify({ input: job.payload, claim: { ownerToken: 'expired-fixture-owner', leaseUntil: 1 } }), job.id);
    db.update('knowledges', String(doc.id), { metadata: { ...doc.metadata as object,
      workflow_job_id: scenario === 'superseded-attempt' ? 'newer-active-job' : job.id, workflow_status: 'processing' } });
    db.insert('task_records', { id: job.id, task_type: 'process_knowledge', status: 'running', payload: { knowledge_id: doc.id! } });
    const span = db.insert('knowledge_processing_spans', { knowledge_id: doc.id, attempt: 1,
      span_id: randomUUID(), name: 'process_knowledge', kind: 'root', status: 'running',
      started_at: new Date(Date.now() - 1000).toISOString(), metadata: { job_id: job.id, queue_attempt: 1 } });
    const before = db.read('knowledges', String(doc.id))!;
    db.close();
    try {
      app = new CoreApplication(directory, { parser: new DocumentParser({
        pythonExecutable: '/tmp/marlin-parser-isolation-20261010/bin/python', workerPath: resolve('../../workers/document/worker.py'),
      }) });
      const recovered = app.database.read('knowledges', String(doc.id))!;
      assert.equal(app.jobs.get(job.id, job.scope).status, 'interrupted');
      assert.equal(app.database.read('knowledge_processing_spans', String(span.id))?.status, 'interrupted');
      assert.ok(app.database.read('knowledge_processing_spans', String(span.id))?.finished_at);
      assert.equal(app.database.read('task_records', job.id)?.status, 'interrupted');
      assert.equal((recovered.metadata as any).content, (before.metadata as any).content);
      assert.equal((recovered.metadata as any).source_generation, 'original-generation');
      if (scenario === 'superseded-attempt') assert.deepEqual(recovered, before);
      else {
        assert.equal((recovered.metadata as any).workflow_status, 'interrupted');
        assert.equal(recovered.parse_status, published ? 'completed' : 'failed');
        assert.equal(recovered.pending_subtasks_count, 0);
      }
      const after = app.database.read('knowledges', String(doc.id));
      app.documents!.recover();
      assert.deepEqual(app.database.read('knowledges', String(doc.id)), after);
      assert.equal(app.database.get('SELECT count(*) AS n FROM model_usage')?.n, 0);
      assert.equal(app.jobs.get(job.id, job.scope).attempt, 1);
    } finally {
      await app?.close(); rmSync(directory, { recursive: true, force: true });
    }
  });
}
