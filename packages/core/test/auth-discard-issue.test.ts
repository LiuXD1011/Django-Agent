import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { AuthService, type AuthIssue } from '../src/auth/index.js';
import { CoreDatabase } from '../src/storage/database.js';

function fixture() {
  const directory = mkdtempSync(join(tmpdir(), 'marlin-discard-issue 中文 '));
  const db = new CoreDatabase(directory), auth = new AuthService(db);
  const account = { username: 'discard', email: 'discard@example.invalid', password: 'DiscardFixture✓' };
  const issue = auth.register(account);
  return { directory, db, auth, account, issue, close() { db.close(); rmSync(directory, { recursive: true, force: true }); } };
}

test('trusted discard revokes only its issued device after membership removal and does not weaken ordinary logout', () => {
  const f = fixture();
  try {
    const survivor = f.auth.login({ login: f.account.username, password: f.account.password });
    f.db.run('DELETE FROM tenant_members WHERE user_id=? AND tenant_id=?', f.issue.context.userId, f.issue.context.tenantId);
    assert.throws(() => f.auth.logout(f.issue.context), { code: 'unauthorized' });
    f.auth.discardIssue(f.issue);
    assert.equal(f.db.read('device_sessions', f.issue.context.deviceId)?.revoke_reason, 'auth_superseded');
    assert.ok(f.db.read('device_sessions', f.issue.context.deviceId)?.revoked_at);
    assert.equal(f.db.read('device_sessions', survivor.context.deviceId)?.revoked_at, null);
    f.db.insert('tenant_members', { user_id: f.issue.context.userId, tenant_id: f.issue.context.tenantId, role: 'owner', status: 'active' });
    assert.throws(() => f.auth.authenticateAccess(f.issue.credentials.access), { code: 'unauthorized' });
    assert.throws(() => f.auth.refresh(f.issue.credentials.refresh), { code: 'invalid_refresh' });
    assert.equal(f.auth.authenticateAccess(survivor.credentials.access).deviceId, survivor.context.deviceId);
    const revoked = f.db.read('device_sessions', f.issue.context.deviceId)?.revoked_at;
    f.auth.discardIssue(f.issue); assert.equal(f.db.read('device_sessions', f.issue.context.deviceId)?.revoked_at, revoked);
  } finally { f.close(); }
});

test('trusted legacy discard revokes the exact access/refresh pair after removal while preserving other families', () => {
  const f = fixture();
  try {
    const stale = f.auth.login({ login: f.account.username, password: f.account.password, mode: 'bearer' });
    const survivor = f.auth.login({ login: f.account.username, password: f.account.password, mode: 'bearer' });
    f.db.run('DELETE FROM tenant_members WHERE user_id=? AND tenant_id=?', stale.context.userId, stale.context.tenantId);
    assert.throws(() => f.auth.logout(stale.context), { code: 'unauthorized' });
    f.auth.discardIssue(stale);
    for (const token of [stale.credentials.access, stale.credentials.refresh]) assert.equal(f.db.get('SELECT is_revoked FROM auth_tokens WHERE token=?', token)?.is_revoked, 1);
    for (const token of [survivor.credentials.access, survivor.credentials.refresh]) assert.equal(f.db.get('SELECT is_revoked FROM auth_tokens WHERE token=?', token)?.is_revoked, 0);
    assert.equal(f.db.read('device_sessions', f.issue.context.deviceId)?.revoked_at, null);
    f.db.insert('tenant_members', { user_id: stale.context.userId, tenant_id: stale.context.tenantId, role: 'owner', status: 'active' });
    assert.throws(() => f.auth.authenticateLegacyBearer(stale.credentials.access), { code: 'unauthorized' });
    assert.throws(() => f.auth.refreshLegacy(stale.credentials.refresh), { code: 'invalid_refresh' });
    assert.equal(f.auth.authenticateLegacyBearer(survivor.credentials.access).deviceId, survivor.context.deviceId);
  } finally { f.close(); }
});

test('discard ownership conditions and synchronous transaction rollback never revoke unrelated credentials', () => {
  const f = fixture();
  try {
    const other = f.auth.register({ username: 'another', email: 'another@example.invalid', password: 'AnotherFixture✓' });
    const forged: AuthIssue = { ...f.issue, context: { ...f.issue.context, userId: other.context.userId } };
    f.auth.discardIssue(forged);
    assert.equal(f.db.read('device_sessions', f.issue.context.deviceId)?.revoked_at, null);
    const stale = f.auth.login({ login: f.account.username, password: f.account.password, mode: 'bearer' });
    f.auth.discardIssue({ ...stale, context: { ...stale.context, userId: other.context.userId } });
    assert.equal(f.db.get('SELECT is_revoked FROM auth_tokens WHERE token=?', stale.credentials.access)?.is_revoked, 0);
    assert.equal(f.db.get('SELECT is_revoked FROM auth_tokens WHERE token=?', stale.credentials.refresh)?.is_revoked, 0);
    f.db.run("CREATE TRIGGER discard_fault BEFORE UPDATE ON auth_tokens WHEN NEW.token_type='refresh' BEGIN SELECT RAISE(ABORT,'discard rollback fixture'); END");
    assert.throws(() => f.auth.discardIssue(stale), /discard rollback fixture/);
    assert.equal(f.db.get('SELECT is_revoked FROM auth_tokens WHERE token=?', stale.credentials.access)?.is_revoked, 0);
    assert.equal(f.db.get('SELECT is_revoked FROM auth_tokens WHERE token=?', stale.credentials.refresh)?.is_revoked, 0);
    assert.equal(f.auth.authenticateAccess(other.credentials.access).userId, other.context.userId);
  } finally { f.close(); }
});

test('discard of an old issue never revokes a newer refresh generation in the same stable device family', () => {
  const f = fixture();
  try {
    const current = f.auth.refresh(f.issue.credentials.refresh);
    assert.equal(current.context.deviceId, f.issue.context.deviceId);
    f.auth.discardIssue(f.issue);
    assert.equal(f.db.read('device_sessions', current.context.deviceId)?.revoked_at, null);
    assert.equal(f.auth.authenticateAccess(current.credentials.access).deviceId, current.context.deviceId);
    f.auth.discardIssue(current);
    assert.equal(f.db.read('device_sessions', current.context.deviceId)?.revoke_reason, 'auth_superseded');
  } finally { f.close(); }
});
