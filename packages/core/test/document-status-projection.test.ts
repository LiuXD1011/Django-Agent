import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { AuthService } from '../src/auth/index.js';
import { KnowledgeDomain } from '../src/knowledge/domain.js';
import { KnowledgeService } from '../src/knowledge/index.js';
import { CoreDatabase } from '../src/storage/database.js';

test('authorized document lists expose the current workflow without copying source metadata', () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-document-status-'));
  const db = new CoreDatabase(root);
  try {
    const auth = new AuthService(db), ctx = auth.register({ username: 'status-owner', password: 'StatusFixture✓Password' }).context;
    const domain = new KnowledgeDomain(db, auth);
    const kb = db.insert('knowledge_bases', { tenant_id: ctx.tenantId, name: '状态验收' });
    const row = db.insert('knowledges', { tenant_id: ctx.tenantId, knowledge_base_id: kb.id, title: '已发布文档', parse_status: 'completed', summary_status: 'needs_configuration',
      metadata: { content: 'private-source-text'.repeat(10000), api_key: 'fixture-secret', source_generation: 'generation-one', workflow_status: 'processing', processing_warnings: [{ code: 'postprocess_source_empty', stage: 'postprocess' }, { code: 'postprocess_source_empty' }, { message: 'not-a-code' }, null] } });
    for (const status of ['pending', 'processing', 'cancelled', 'interrupted', 'failed', 'completed']) {
      db.update('knowledges', String(row.id), { metadata: { ...(row.metadata as object), workflow_status: status } });
      const projected = domain.docs(ctx, String(kb.id)).map(doc => domain.docDto(doc, true))[0]!;
      assert.equal(projected.workflow_status, status);
      assert.equal(projected.parse_status, 'completed', 'Published parsing status must remain independent of the active workflow');
      assert.deepEqual(projected.processing_warning_codes, ['postprocess_source_empty']);
      assert.equal(projected.source_generation, 'generation-one');
      assert.equal(projected.metadata, undefined);
      assert.ok(!JSON.stringify(projected).includes('private-source-text'));
      assert.ok(!JSON.stringify(projected).includes('fixture-secret'));
    }
    const detailed = domain.docDto(db.read('knowledges', String(row.id))!);
    assert.equal(detailed.workflow_status, 'completed');
    assert.deepEqual(detailed.processing_warning_codes, ['postprocess_source_empty']);
  } finally { db.close(); rmSync(root, { recursive: true, force: true }); }
});

test('legacy document status projections have explicit empty workflow fields', () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-legacy-document-status-'));
  const db = new CoreDatabase(root);
  try {
    const auth = new AuthService(db), domain = new KnowledgeDomain(db, auth);
    const tenant = db.insert('tenants', { name: '旧状态', api_key: 'fixture-only-key' });
    const kb = db.insert('knowledge_bases', { tenant_id: tenant.id, name: '旧资料' });
    const row = db.insert('knowledges', { tenant_id: tenant.id, knowledge_base_id: kb.id, title: '旧文档', metadata: {} });
    const dto = domain.docDto(row, true);
    assert.equal(dto.workflow_status, '');
    assert.equal(dto.source_generation, '');
    assert.deepEqual(dto.processing_warning_codes, []);
  } finally { db.close(); rmSync(root, { recursive: true, force: true }); }
});

test('document filters and whole-library counters match current workflows while preserving published parsing results', () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-document-filter-status-'));
  const db = new CoreDatabase(root);
  try {
    const auth = new AuthService(db), ctx = auth.register({ username: 'filter-owner', password: 'StatusFilterFixture✓Password' }).context;
    const service = new KnowledgeService(db, auth), kb = db.insert('knowledge_bases', { tenant_id: ctx.tenantId, name: '状态筛选验收' });
    const ids = new Map<string, string>();
    for (const workflow of ['completed', 'cancelled', 'failed', 'interrupted', 'pending', 'processing', '']) {
      const row = db.insert('knowledges', { tenant_id: ctx.tenantId, knowledge_base_id: kb.id, title: workflow || 'legacy', parse_status: 'completed',
        metadata: { content: 'Published source is retained', workflow_status: workflow } });
      ids.set(workflow, String(row.id));
    }
    db.insert('knowledges', { tenant_id: ctx.tenantId, knowledge_base_id: kb.id, title: 'removed', parse_status: 'failed', deleted_at: new Date().toISOString(), metadata: { workflow_status: 'failed' } });
    const other = auth.register({ username: 'other-filter-owner', password: 'OtherStatusFilterFixture✓Password' }).context;
    const otherKb = db.insert('knowledge_bases', { tenant_id: other.tenantId, name: '隔离空间' });
    db.insert('knowledges', { tenant_id: other.tenantId, knowledge_base_id: otherKb.id, title: 'private failure', parse_status: 'failed', metadata: { workflow_status: 'failed' } });
    for (const [status, workflows] of [['cancelled', ['cancelled']], ['failed', ['failed', 'interrupted']], ['pending', ['pending']], ['processing', ['processing']], ['completed', ['completed', '']]] as const) {
      const list = service.list(ctx, String(kb.id), { parse_status: status });
      assert.deepEqual((list.items as any[]).map(row => row.id).sort(), workflows.map(value => ids.get(value)).sort(), 'Current displayed state must be discoverable by its filter');
      assert.ok((list.items as any[]).every(row => row.parse_status === 'completed'), 'Published parsing result remains independent');
      assert.equal((list.status_counts as any)[status], workflows.length, 'Whole-library counts ignore the active filter');
    }
    const stats = service.stats(ctx, String(kb.id));
    assert.equal(stats.completed, 2); assert.equal(stats.failed, 2); assert.equal(stats.cancelled, 1); assert.equal(stats.pending, 1);
    assert.deepEqual(stats.status_counts, { pending: 1, processing: 1, finalizing: 0, completed: 2, failed: 2, cancelled: 1 });
    for (const id of ids.values()) assert.equal((db.read('knowledges', id)!.metadata as any).content, 'Published source is retained');
  } finally { db.close(); rmSync(root, { recursive: true, force: true }); }
});
