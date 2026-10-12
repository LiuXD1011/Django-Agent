import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { AuthError, AuthService, type AuthAction } from '../src/auth/index.js';
import { AuthReader } from '../src/auth/reader.js';
import type { AuthContext } from '../src/contracts.js';
import { CoreDatabase } from '../src/storage/database.js';
import { ReadDatabase } from '../src/storage/read-database.js';

const account = (username: string) => ({ username, email: `${username}@example.invalid`, password: 'ReadFixturePassword✓' });
function fixture() {
  const directory = mkdtempSync(join(tmpdir(), 'marlin-auth-reader 中文 '));
  const writer = new CoreDatabase(directory); let now = Date.now();
  const owner = new AuthService(writer, { now: () => now, allowAutoSetup: true });
  const db = new ReadDatabase(writer.path, directory);
  const reader = new AuthReader(db, { now: () => now });
  return { directory, writer, owner, db, reader, advance(ms: number) { now += ms; }, close() { db.close(); writer.close(); rmSync(directory, { recursive: true, force: true }); } };
}
const denied = (work: () => unknown, code = 'unauthorized', status = 401) => assert.throws(work, (error: unknown) => error instanceof AuthError && error.status === status && error.code === code);

test('same AuthReader implementation projects actual device and bearer identities without credentials or writes', () => {
  const f = fixture();
  try {
    const issue = f.owner.register(account('identity'));
    const second = f.owner.login({ login: 'identity', password: account('identity').password, clientType: 'desktop' });
    const bearer = f.owner.login({ login: 'identity', password: account('identity').password, mode: 'bearer' });
    const before = f.writer.all('SELECT * FROM device_sessions ORDER BY id');
    assert.equal(f.owner instanceof AuthReader, true);
    for (const operation of ['authenticateAccess', 'authenticateLegacyBearer', 'authenticateApiKey', 'assertCan', 'me', 'listDevices', 'sessionIsActive']) {
      assert.equal(Object.prototype.hasOwnProperty.call(AuthService.prototype, operation), false, `${operation} must be inherited, not copied`);
    }
    const ctx = f.reader.authenticateAccess(issue.credentials.access);
    assert.deepEqual(ctx, f.owner.authenticateAccess(issue.credentials.access));
    const publicIdentity = f.reader.me(ctx);
    assert.deepEqual(publicIdentity, f.owner.me(ctx));
    assert.deepEqual(f.reader.listDevices(ctx), f.owner.listDevices(ctx));
    assert.equal(f.reader.listDevices(ctx).length, 2);
    assert.equal(f.reader.listDevices(ctx).filter(device => device.current).length, 1);
    assert.ok(f.reader.listDevices(ctx).some(device => device.id === second.context.deviceId));
    assert.deepEqual(f.reader.me(f.reader.authenticateLegacyBearer(bearer.credentials.access)), f.owner.me(bearer.context));
    assert.equal(f.reader.sessionIsActive(ctx.deviceId, ctx.userId, ctx.tenantId), true);
    for (const secret of [issue.credentials.access, issue.credentials.refresh, String(f.writer.read('users', ctx.userId)?.password_hash), String(f.writer.read('tenants', ctx.tenantId)?.api_key)]) assert.equal(JSON.stringify(publicIdentity).includes(secret), false);
    for (const method of ['login', 'register', 'refresh', 'logout', 'updatePreferences', 'changePassword']) assert.equal(method in f.reader, false);
    assert.deepEqual(f.writer.all('SELECT * FROM device_sessions ORDER BY id'), before);
  } finally { f.close(); }
});

test('authenticate, authorize and hydrate share one deferred snapshot across an owner revocation commit', () => {
  const f = fixture();
  try {
    const issue = f.owner.register(account('snapshot'));
    const doc = f.writer.insert('integration_configs', { name: 'readonly-snapshot', parameters: { content: 'old😀' } });
    const result = f.db.snapshot(() => {
      const ctx = f.reader.authenticateAccess(issue.credentials.access);
      f.writer.transaction(() => {
        f.writer.update('device_sessions', ctx.deviceId, { revoked_at: new Date().toISOString() });
        f.writer.update('integration_configs', String(doc.name), { parameters: { content: 'new😀' } });
      });
      f.reader.assertCan(ctx, 'read');
      return { identity: f.reader.me(ctx), document: f.db.read('integration_configs', String(doc.name)) };
    });
    assert.equal(result.identity.user.username, 'snapshot');
    assert.deepEqual(result.document?.parameters, { content: 'old😀' });
    denied(() => f.db.snapshot(() => f.reader.authenticateAccess(issue.credentials.access)));
    assert.deepEqual(f.db.read('integration_configs', String(doc.name))?.parameters, { content: 'new😀' });
  } finally { f.close(); }
});

test('readonly personal-space scope requires its actual owner and active membership, including system admins', () => {
  const f = fixture();
  try {
    const alice = f.owner.register(account('alice')), bob = f.owner.register(account('bob'));
    f.writer.update('users', bob.context.userId, { is_system_admin: true, can_access_all_tenants: true });
    denied(() => f.reader.authenticateAccess(bob.credentials.access, alice.context.tenantId));
    denied(() => f.reader.assertCan(bob.context, 'read', alice.context.tenantId), 'action_forbidden', 403);
    denied(() => f.reader.assertCan(alice.context, 'read', alice.context.tenantId, bob.context.userId), 'user_principal_required', 403);
    denied(() => f.reader.authenticateApiKey(String(f.writer.read('tenants', alice.context.tenantId)?.api_key)));
    f.writer.run("UPDATE tenant_members SET status='revoked' WHERE user_id=?", alice.context.userId);
    denied(() => f.reader.authenticateAccess(alice.credentials.access));
    assert.equal(f.reader.sessionIsActive(alice.context.deviceId, alice.context.userId, alice.context.tenantId), false);
  } finally { f.close(); }
});

test('readonly role matrix, retained revocation markers, selected scope and API-key rotation retain original errors', () => {
  const f = fixture();
  try {
    const issue = f.owner.register(account('roles'));
    const tenant = f.writer.insert('tenants', { name: 'shared', api_key: 'readonly-shared-key' });
    const member = f.writer.insert('tenant_members', { user_id: issue.context.userId, tenant_id: tenant.id, role: 'viewer', status: 'active' });
    const reads: AuthAction[] = ['read', 'export'], writes: AuthAction[] = ['write', 'import', 'kb.write', 'document.write', 'document.delete', 'document.move', 'chunk.write', 'wiki.write', 'agent.write', 'eval.write', 'task.write'];
    const admins: AuthAction[] = ['admin', 'kb.delete', 'credentials.manage', 'member.manage', 'tenant.admin'];
    for (const role of ['viewer', 'editor', 'admin', 'owner']) {
      f.writer.update('tenant_members', member.id as number, { role });
      const ctx = f.reader.authenticateAccess(issue.credentials.access, String(tenant.id));
      assert.deepEqual(ctx, f.owner.authenticateAccess(issue.credentials.access, String(tenant.id)));
      for (const action of [...reads, ...writes, ...admins, 'tenant.create'] as AuthAction[]) {
        const permitted = reads.includes(action) || action === 'tenant.create' || role !== 'viewer' && writes.includes(action) || ['admin', 'owner'].includes(role) && admins.includes(action);
        if (permitted) f.reader.assertCan(ctx, action); else denied(() => f.reader.assertCan({ ...ctx, role: 'owner', isSystemAdmin: true }, action), 'action_forbidden', 403);
      }
    }
    const api = f.reader.authenticateApiKey('readonly-shared-key'); f.reader.assertCan(api, 'read'); f.reader.assertCan(api, 'export');
    denied(() => f.reader.me(api)); denied(() => f.reader.listDevices(api));
    denied(() => f.reader.assertCan(api, 'read', api.tenantId, issue.context.userId), 'user_principal_required', 403);
    denied(() => f.reader.assertCan(api, 'read', issue.context.tenantId), 'action_forbidden', 403);
    denied(() => f.reader.authenticateApiKey('readonly-shared-key', issue.context.tenantId));
    f.writer.update('tenants', tenant.id as number, { api_key: 'readonly-rotated-key' }); denied(() => f.reader.assertCan(api, 'read'));
    f.writer.update('users', issue.context.userId, { tenant_id: tenant.id, is_system_admin: true });
    f.writer.update('tenant_members', member.id as number, { deleted_at: new Date().toISOString() }); denied(() => f.reader.authenticateAccess(issue.credentials.access));
    f.writer.run('DELETE FROM tenant_members WHERE id=?', member.id as number);
    assert.equal(f.reader.authenticateAccess(issue.credentials.access).role, 'owner');
  } finally { f.close(); }
});

test('readonly revalidation fails disabled/deleted users, tenants, memberships and expired/revoked tokens in original order', () => {
  const f = fixture();
  try {
    const issue = f.owner.register(account('lifetime'));
    f.advance(600000); denied(() => f.reader.authenticateAccess(issue.credentials.access));
    assert.equal(f.reader.sessionIsActive(issue.context.deviceId, issue.context.userId, issue.context.tenantId), true);
    const fresh = f.owner.refresh(issue.credentials.refresh);
    for (const field of ['idle_expires_at', 'absolute_expires_at']) {
      const original = f.writer.read('device_sessions', issue.context.deviceId)![field];
      f.writer.update('device_sessions', issue.context.deviceId, { [field]: '2000-01-01T00:00:00Z' }); denied(() => f.reader.assertCan(issue.context, 'write', 'missing-tenant'), 'unauthorized');
      f.writer.update('device_sessions', issue.context.deviceId, { [field]: original });
    }
    for (const patch of [{ is_active: false }, { deleted_at: new Date().toISOString() }]) {
      f.writer.update('users', issue.context.userId, patch); denied(() => f.reader.authenticateAccess(fresh.credentials.access));
      f.writer.update('users', issue.context.userId, { is_active: true, deleted_at: null });
    }
    for (const patch of [{ status: 'disabled' }, { deleted_at: new Date().toISOString() }]) {
      f.writer.update('tenants', issue.context.tenantId, patch); denied(() => f.reader.authenticateAccess(fresh.credentials.access));
      f.writer.update('tenants', issue.context.tenantId, { status: 'active', deleted_at: null });
    }
    const bearer = f.owner.login({ login: 'lifetime', password: account('lifetime').password, mode: 'bearer' });
    const tokenId = bearer.context.deviceId.slice(7);
    for (const patch of [{ is_revoked: true }, { deleted_at: new Date().toISOString() }, { expires_at: '2000-01-01T00:00:00Z' }]) {
      const original = f.writer.read('auth_tokens', tokenId)!;
      f.writer.update('auth_tokens', tokenId, patch); denied(() => f.reader.authenticateLegacyBearer(bearer.credentials.access)); denied(() => f.reader.me(bearer.context));
      f.writer.update('auth_tokens', tokenId, { is_revoked: original.is_revoked, deleted_at: original.deleted_at, expires_at: original.expires_at });
    }
    for (const raw of ['', 'not-a-token']) { denied(() => f.reader.authenticateAccess(raw)); denied(() => f.reader.authenticateLegacyBearer(raw)); denied(() => f.reader.authenticateApiKey(raw)); }
    f.owner.logoutAll(issue.context); denied(() => f.reader.authenticateAccess(fresh.credentials.access)); denied(() => f.reader.authenticateLegacyBearer(bearer.credentials.access));
  } finally { f.close(); }
});

test('channel authority and delegated action validation remain shared without granting ordinary credential access', () => {
  const f = fixture();
  try {
    const issue = f.owner.register(account('channel'));
    const principal = { id: 'guest', grantId: 'grant', guestId: 'guest', version: '1', origin: 'https://fixture.invalid', expiresAt: Date.now() + 10000, knowledgeBaseIds: [] };
    const context: AuthContext = { ...issue.context, deviceId: 'channel:grant', role: 'owner', channel: principal };
    denied(() => f.reader.assertCan(context, 'read'));
    const unregister = f.reader.registerChannelAuthority(ctx => ctx);
    denied(() => f.reader.registerChannelAuthority(ctx => ctx), 'channel_authority_exists', 409);
    for (const action of ['read', 'write', 'agent.write'] as const) f.reader.assertCan(context, action);
    denied(() => f.reader.assertCan(context, 'document.write'), 'channel_action_forbidden', 403);
    denied(() => f.reader.assertCan(context, 'read', 'another'), 'channel_action_forbidden', 403);
    denied(() => f.reader.me(context)); denied(() => f.reader.listDevices(context));
    unregister(); denied(() => f.reader.assertCan(context, 'read'));
  } finally { f.close(); }
});
