import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { CoreDatabase } from '../src/storage/database.js';
import { verifyPassword } from '../src/auth/passwords.js';

interface PasswordVector {
  algorithm: 'pbkdf2_sha256' | 'pbkdf2_sha1'; password: string; wrong_password: string;
  salt: string; iterations: number; encoded: string; id: string;
}
const golden = JSON.parse(readFileSync(new URL('./fixtures/django-pbkdf2.json', import.meta.url), 'utf8')) as {
  generated_with: { Django: string; django_settings_configured: boolean }; cases: PasswordVector[];
};

// Independent RFC 8018 section 5.2 oracle. Both stored password algorithms use
// exactly one PRF block; do not call the production PBKDF2/verify implementation.
function specificationPbkdf2(password: string, salt: string, iterations: number, digest: 'sha256' | 'sha1'): Buffer {
  const key = Buffer.from(password, 'utf8'), block = Buffer.alloc(4); block.writeUInt32BE(1);
  let previous = createHmac(digest, key).update(Buffer.from(salt, 'utf8')).update(block).digest();
  const result = Buffer.from(previous);
  for (let iteration = 1; iteration < iterations; iteration++) {
    previous = createHmac(digest, key).update(previous).digest();
    for (let byte = 0; byte < result.length; byte++) result[byte] = result[byte]! ^ previous[byte]!;
  }
  return result;
}

test('frozen synthetic Django PBKDF2 vectors retain unicode, encoded work factors, SHA1 and wrong-password behavior without Python', () => {
  assert.equal(golden.generated_with.Django, '5.2.15'); assert.equal(golden.generated_with.django_settings_configured, false);
  assert.equal(golden.cases.length, 5);
  for (const vector of golden.cases) {
    assert.equal(verifyPassword(vector.password, vector.encoded), true, vector.id);
    assert.equal(verifyPassword(vector.wrong_password, vector.encoded), false, vector.id);
    if (vector.iterations <= 4096) {
      const digest = vector.algorithm === 'pbkdf2_sha256' ? 'sha256' : 'sha1';
      assert.equal(specificationPbkdf2(vector.password, vector.salt, vector.iterations, digest).toString('base64'), vector.encoded.split('$')[3], vector.id);
    }
  }
});

async function fixture() {
  const m = await import('../src/auth/index.js').catch(() => null);
  assert.ok(m, 'AuthService must implement the approved authentication behavior');
  const root = mkdtempSync(join(tmpdir(), 'marlin-auth-'));
  const db = new CoreDatabase(root);
  let time = Date.now();
  return { ...m, db, root, auth: new m.AuthService(db, { now: () => time }), advance: (ms: number) => { time += ms; }, close: () => { db.close(); rmSync(root, { recursive: true, force: true }); } };
}
const account = (username: string) => ({ username, email: `${username}@example.invalid`, password: 'GoodPassword✓' });
const denied = (fn: () => unknown, status = 401) => assert.throws(fn, (e: any) => e.status === status);
test('private account creation is atomic and public DTO excludes all credentials', async () => {
  const f = await fixture();
  try {
    const x = f.auth.register(account('alice'));
    const u = f.db.read('users', x.context.userId)!; const t = f.db.read('tenants', x.context.tenantId)!;
    assert.equal(t.space_type, 'personal'); assert.equal(t.personal_owner_id, u.id);
    assert.equal(f.db.get('select count(*) as n from tenant_members')?.n, 1);
    assert.equal(x.context.role, 'owner'); assert.equal(typeof x.context.tenantId, 'string');
    for (const secret of [x.credentials.access, x.credentials.refresh, t.api_key, u.password_hash]) assert.equal(JSON.stringify(x.public).includes(String(secret)), false);
    f.db.run("create trigger block_member before insert on tenant_members begin select raise(abort,'planned'); end");
    assert.throws(() => f.auth.register(account('failed')));
    assert.equal(f.db.get('select count(*) as n from users')?.n, 1); assert.equal(f.db.get('select count(*) as n from tenants')?.n, 1);
    denied(() => f.auth.register(account('alice')), 409);
  } finally { f.close(); }
});
test('actual Django unicode PBKDF2 fixture verifies without resetting password and bad password issues nothing', async () => {
  const f = await fixture();
  try {
    const x = f.auth.register(account('old'));
    const django = 'pbkdf2_sha256$260000$fixtureSalt2026$/JWBBute1JewIrQ1fXbtSUNUgST4EwcvVlOB7qkos9c=';
    f.db.update('users', x.context.userId, { password_hash: django });
    assert.equal(f.verifyPassword('迁移Password✓', django), true); assert.equal(f.verifyPassword('wrong', django), false);
    denied(() => f.auth.login({ login: 'old', password: 'wrong' }));
    assert.equal(f.db.get('select count(*) as n from device_sessions')?.n, 1);
    assert.equal(f.auth.login({ login: 'old', password: '迁移Password✓' }).context.userId, x.context.userId);
    assert.equal(f.db.read('users', x.context.userId)?.password_hash, django);
  } finally { f.close(); }
});
test('refresh single consumption across connections preserves stable family; replay revokes only that family', async () => {
  const f = await fixture(); const second = new CoreDatabase(f.root);
  try {
    const x = f.auth.register(account('refresh')); const other = f.auth.login({ login: 'refresh', password: account('refresh').password });
    const rotated = new f.AuthService(second).refresh(x.credentials.refresh);
    assert.equal(rotated.context.deviceId, x.context.deviceId); denied(() => f.auth.authenticateAccess(x.credentials.access));
    assert.equal(f.auth.sessionIsActive(x.context.deviceId, x.context.userId, x.context.tenantId), true);
    denied(() => f.auth.refresh(x.credentials.refresh)); denied(() => f.auth.authenticateAccess(rotated.credentials.access));
    assert.equal(f.auth.authenticateAccess(other.credentials.access).userId, x.context.userId);
    assert.equal(f.db.read('device_sessions', x.context.deviceId)?.revoke_reason, 'refresh_replay');
  } finally { second.close(); f.close(); }
});
test('access, idle, absolute expiry and disabled principal each fail closed', async () => {
  const f = await fixture();
  try {
    const x = f.auth.register(account('expiry')); f.advance(600000); denied(() => f.auth.authenticateAccess(x.credentials.access));
    assert.equal(f.auth.sessionIsActive(x.context.deviceId, x.context.userId, x.context.tenantId), true);
    const y = f.auth.refresh(x.credentials.refresh); f.advance(30 * 86400000); denied(() => f.auth.refresh(y.credentials.refresh));
    const z = f.auth.login({ login: 'expiry', password: account('expiry').password });
    f.db.update('device_sessions', z.context.deviceId, { absolute_expires_at: '2026-01-01T00:00:00Z' }); denied(() => f.auth.refresh(z.credentials.refresh));
    const a = f.auth.login({ login: 'expiry', password: account('expiry').password });
    f.db.update('users', a.context.userId, { is_active: false }); denied(() => f.auth.authenticateAccess(a.credentials.access)); denied(() => f.auth.refresh(a.credentials.refresh));
  } finally { f.close(); }
});
test('device revoke respects owner; changing password and logout-all revoke every user credential', async () => {
  const f = await fixture();
  try {
    const x = f.auth.register(account('device')); const y = f.auth.login({ login: 'device', password: account('device').password }); const bob = f.auth.register(account('bob'));
    denied(() => f.auth.revokeDevice(x.context, bob.context.deviceId), 404); f.auth.revokeDevice(x.context, y.context.deviceId); denied(() => f.auth.authenticateAccess(y.credentials.access));
    const old = f.auth.login({ login: 'device', password: account('device').password, mode: 'bearer' });
    assert.equal(f.auth.authenticateLegacyBearer(old.credentials.access).userId, x.context.userId);
    f.auth.changePassword(x.context, account('device').password, 'ChangedPassword'); denied(() => f.auth.authenticateAccess(x.credentials.access)); denied(() => f.auth.authenticateLegacyBearer(old.credentials.access));
    assert.equal(f.auth.authenticateAccess(bob.credentials.access).userId, bob.context.userId);
    const z = f.auth.login({ login: 'device', password: 'ChangedPassword' }); f.auth.logoutAll(z.context); denied(() => f.auth.authenticateAccess(z.credentials.access));
  } finally { f.close(); }
});
test('private ACL requires true owner and active member, even for admin, and protects user sessions', async () => {
  const f = await fixture();
  try {
    const a = f.auth.register(account('private-a')); const b = f.auth.register(account('private-b'));
    f.db.update('users', b.context.userId, { is_system_admin: true, can_access_all_tenants: true });
    denied(() => f.auth.authenticateAccess(b.credentials.access, a.context.tenantId)); denied(() => f.auth.assertCan(b.context, 'read', a.context.tenantId), 403);
    denied(() => f.auth.assertCan(a.context, 'write', a.context.tenantId, b.context.userId), 403);
    denied(() => f.auth.authenticateApiKey(f.db.read('tenants', a.context.tenantId)?.api_key as string));
    f.db.run("update tenant_members set status='revoked' where user_id=?", a.context.userId); denied(() => f.auth.authenticateAccess(a.credentials.access));
    assert.equal(f.auth.sessionIsActive(a.context.deviceId, a.context.userId, a.context.tenantId), false);
  } finally { f.close(); }
});
test('legacy membership overrides primary fallback; viewer/editor/admin and API-key action matrix', async () => {
  const f = await fixture();
  try {
    const x = f.auth.register(account('roles')); const t = f.db.insert('tenants', { name: 'Legacy', api_key: 'legacy-fixture-key' });
    f.db.update('users', x.context.userId, { tenant_id: t.id });
    const m = f.db.insert('tenant_members', { user_id: x.context.userId, tenant_id: t.id, role: 'viewer', status: 'active' });
    for (const role of ['viewer', 'editor', 'admin']) {
      f.db.update('tenant_members', m.id as number, { role }); const ctx = f.auth.authenticateAccess(x.credentials.access, String(t.id));
      for (const action of ['read', 'write', 'admin', 'import', 'export'] as const) {
        const allow = action === 'read' || action === 'export' || (role !== 'viewer' && action !== 'admin') || role === 'admin';
        if (allow) f.auth.assertCan(ctx, action); else denied(() => f.auth.assertCan(ctx, action), 403);
      }
    }
    const service = f.auth.authenticateApiKey('legacy-fixture-key'); f.auth.assertCan(service, 'read');
    denied(() => f.auth.assertCan(service, 'write', service.tenantId, x.context.userId), 403); denied(() => f.auth.authenticateApiKey('legacy-fixture-key', x.context.tenantId));
    f.db.update('tenant_members', m.id as number, { status: 'revoked' }); denied(() => f.auth.authenticateAccess(x.credentials.access));
    f.db.run('delete from tenant_members where id=?', m.id as number); assert.equal(f.auth.authenticateAccess(x.credentials.access).role, 'owner');
  } finally { f.close(); }
});
test('setup requires explicit flag and is single use; preference updates cannot escalate role', async () => {
  const f = await fixture();
  try {
    denied(() => f.auth.autoSetup(account('admin'))); const enabled = new f.AuthService(f.db, { allowAutoSetup: true }); const x = enabled.autoSetup(account('admin'));
    assert.equal(x.context.isSystemAdmin, true); denied(() => enabled.autoSetup(account('another')));
    enabled.updatePreferences(x.context, { enable_memory: false });
    const preferences = enabled.me(x.context).user.preferences;
    assert.ok(preferences && typeof preferences === 'object' && !Array.isArray(preferences));
    assert.equal(preferences.enable_memory, false);
    denied(() => enabled.updatePreferences(x.context, { is_system_admin: true }), 400); enabled.logout(x.context); denied(() => enabled.me(x.context));
  } finally { f.close(); }
});

test('two real processes racing the same refresh issue once, then commit replay family revocation', async () => {
  const { spawn } = await import('node:child_process');
  const { writeFileSync } = await import('node:fs');
  const { pathToFileURL } = await import('node:url');
  const f = await fixture();
  const worker = join(f.root, 'refresh-worker.mjs');
  writeFileSync(worker, `import {CoreDatabase} from ${JSON.stringify(pathToFileURL(join(process.cwd(), 'src/storage/database.ts')).href)};\nimport {AuthService} from ${JSON.stringify(pathToFileURL(join(process.cwd(), 'src/auth/index.ts')).href)};\nconst db=new CoreDatabase(process.argv[2]); const auth=new AuthService(db);process.stdout.write('ready\\n'); let raw='';for await(const chunk of process.stdin){raw+=chunk;}try {const result=auth.refresh(raw);process.stdout.write(JSON.stringify({ok:true,device:result.context.deviceId}));}catch(e){process.stdout.write(JSON.stringify({ok:false,status:e.status}));}finally{db.close();}\n`);
  const processes: ReturnType<typeof spawn>[] = [];
  try {
    const x = f.auth.register(account('race'));
    const start = () => {
      const p = spawn(process.execPath, ['--import', 'tsx', worker, f.root], { stdio: ['pipe', 'pipe', 'pipe'] }); processes.push(p);
      let output = '', errors = '';
      const ready = new Promise<void>((resolve, reject) => {
        p.stdout!.on('data', b => { output += b.toString(); if (output.startsWith('ready\n')) resolve(); });
        p.on('error', reject); p.once('exit', code => { if (!output.startsWith('ready\n')) reject(new Error(`worker failed: ${code} ${errors}`)); });
      });
      p.stderr!.on('data', b => { errors += b.toString(); });
      const done = new Promise<{ ok: boolean; status?: number; device?: string }>((resolve, reject) => {
        p.once('exit', code => { if (code !== 0) reject(new Error(`worker failed: ${code} ${errors}`)); else resolve(JSON.parse(output.slice(6))); });
        p.on('error', reject);
      });
      return { p, ready, done };
    };
    const a = start(), b = start(); await Promise.all([a.ready, b.ready]);
    a.p.stdin!.end(x.credentials.refresh); b.p.stdin!.end(x.credentials.refresh);
    const results = await Promise.all([a.done, b.done]);
    assert.equal(results.filter(r => r.ok).length, 1); assert.equal(results.filter(r => r.status === 401).length, 1);
    assert.equal(f.db.get('select count(*) as n from device_refresh_tokens where session_id=?', x.context.deviceId)?.n, 2);
    assert.equal(f.db.read('device_sessions', x.context.deviceId)?.revoke_reason, 'refresh_replay');
    assert.equal(f.auth.sessionIsActive(x.context.deviceId, x.context.userId, x.context.tenantId), false);
  } finally { for (const p of processes) if (p.exitCode === null) p.kill(); f.close(); }
});

test('legacy refresh consumes once; refresh logout works after access expiry, and authoritative roles override stale context', async () => {
  const f = await fixture();
  try {
    const x = f.auth.register(account('legacy'));
    const y = f.auth.login({ login: 'legacy', password: account('legacy').password, mode: 'bearer' });
    const z = f.auth.refreshLegacy(y.credentials.refresh); denied(() => f.auth.refreshLegacy(y.credentials.refresh));
    assert.equal(f.auth.authenticateLegacyBearer(z.credentials.access).userId, x.context.userId);
    f.advance(600000); f.auth.logoutRefresh(x.credentials.refresh); denied(() => f.auth.refresh(x.credentials.refresh));
    const t = f.db.insert('tenants', { name: 'shared', api_key: 'service-key' });
    f.db.insert('tenant_members', { user_id: x.context.userId, tenant_id: t.id, role: 'viewer', status: 'active' });
    const ctx = f.auth.authenticateLegacyBearer(z.credentials.access, String(t.id));
    denied(() => f.auth.assertCan({ ...ctx, role: 'owner', isSystemAdmin: true }, 'admin'), 403);
    const service = f.auth.authenticateApiKey('service-key'); f.db.update('tenants', t.id as number, { api_key: 'changed-key' });
    denied(() => f.auth.assertCan(service, 'read'));
    const devices = f.auth.listDevices(ctx); assert.equal(devices.length, 1); assert.equal(devices[0]?.is_revoked, true);
  } finally { f.close(); }
});

test('TS generated passwords match independent PBKDF2 specification, malformed encodings fail safely, and refresh never extends absolute lifetime', async () => {
  const f = await fixture();
  try {
    const raw = '新Password✓', hash = f.hashPassword(raw), parts = hash.split('$');
    assert.equal(parts.length, 4);
    const [algorithm, iterations, salt, expected] = parts;
    assert.equal(algorithm, 'pbkdf2_sha256'); assert.equal(iterations, '1000000');
    assert.ok(salt); assert.match(salt, /^[A-Za-z0-9_-]{24}$/);
    assert.equal(Buffer.from(salt, 'base64url').length, 18);
    assert.ok(expected); assert.equal(Buffer.from(expected, 'base64').length, 32);
    assert.equal(Buffer.from(expected, 'base64').toString('base64'), expected);
    assert.equal(specificationPbkdf2(raw, salt, Number(iterations), 'sha256').toString('base64'), expected);
    assert.equal(f.verifyPassword(raw, hash), true); assert.equal(f.verifyPassword('wrong', hash), false);
    assert.notEqual(f.hashPassword(raw).split('$')[2], salt, 'fresh hashes must use independent salts');
    for (const malformed of ['!', 'unknown$100$salt$hash', 'pbkdf2_sha256$0$salt$hash', 'pbkdf2_sha256$1e8$salt$hash', 'pbkdf2_sha256$1000000000$salt$hash']) assert.equal(f.verifyPassword('password', malformed), false);
    const x = f.auth.register(account('absolute'));
    const absolute = new Date(Date.parse(x.credentials.accessExpiresAt) + 3000000).toISOString();
    f.db.update('device_sessions', x.context.deviceId, { absolute_expires_at: absolute });
    const rotated = f.auth.refresh(x.credentials.refresh);
    assert.equal(rotated.credentials.refreshExpiresAt, absolute);
    assert.ok(Date.parse(rotated.credentials.accessExpiresAt) <= Date.parse(absolute));
    f.advance(3600001); denied(() => f.auth.refresh(rotated.credentials.refresh));
    denied(() => f.auth.updatePreferences(rotated.context, { enable_memory: 'true' }), 400);
  } finally { f.close(); }
});
