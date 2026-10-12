import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import type { JsonObject } from '../src/contracts.js';
import { SessionEventJournal } from '../src/jobs/journal.js';
import { CoreDatabase } from '../src/storage/database.js';

function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'marlin-maintenance-trajectory-'));
  const database = new CoreDatabase(root);
  const tenant = database.insert('tenants', { name: 'Maintenance fixture', api_key: 'fixture-only-key' });
  const user = database.insert('users', { username: 'maintenance-fixture', email: 'maintenance@example.invalid', password_hash: 'unusable-fixture', tenant_id: tenant.id });
  const scope = { tenantId: String(tenant.id), userId: String(user.id) };
  const session = database.insert('sessions', { tenant_id: tenant.id, user_id: user.id, title: 'Maintenance fixture' });
  const journal = new SessionEventJournal(database);
  return {
    add: (data: JsonObject) => journal.append(String(session.id), 'fixture-turn', 'maintenance/step', data, scope),
    raw: () => journal.read(String(session.id), scope),
    fold: () => journal.fold(String(session.id), scope).turns[0]!.maintenance as JsonObject[],
    close: () => { database.close(); rmSync(root, { recursive: true, force: true }); },
  };
}

test('persisted current maintenance events keep actual stage, result and warnings without fabricated success', () => {
  const f = fixture();
  const warnings = [{ code: 'memory_response_invalid', message: 'Optional memory was skipped' }];
  try {
    f.add({ stage: 'memory_retrieval', warnings });
    f.add({ stage: 'memory_extraction', state: 'stored', graph_state: 'forbidden', warnings: [{ code: 'graph_forbidden' }] });
    f.add({ stage: 'post_turn', status: 'completed' });
    assert.deepEqual(f.raw()[0]!.data, { stage: 'memory_retrieval', warnings });
    assert.deepEqual(f.fold(), [
      { step: '', stage: 'memory_retrieval', status: '', state: '', graph_state: '', success: null, duration_ms: null, error: '', warnings },
      { step: '', stage: 'memory_extraction', status: '', state: 'stored', graph_state: 'forbidden', success: null, duration_ms: null, error: '', warnings: [{ code: 'graph_forbidden' }] },
      { step: '', stage: 'post_turn', status: 'completed', state: '', graph_state: '', success: null, duration_ms: null, error: '', warnings: [] },
    ]);
  } finally { f.close(); }
});

test('legacy maintenance success and failure remain explicit while an absent result remains unknown', () => {
  const f = fixture();
  try {
    f.add({ step: 'legacy-success', success: true, duration_ms: 12 });
    f.add({ step: 'legacy-failure', success: false, error: 'fixture failure' });
    f.add({ step: 'legacy-unconfirmed' });
    const rows = f.fold();
    assert.deepEqual(rows.map(row => [row.step, row.success, row.duration_ms, row.error]), [
      ['legacy-success', true, 12, ''],
      ['legacy-failure', false, null, 'fixture failure'],
      ['legacy-unconfirmed', null, null, ''],
    ]);
  } finally { f.close(); }
});
