import { createHash, randomBytes } from 'node:crypto';
import type { AuthContext, Json, JsonObject } from '../contracts.js';
import type { CoreDatabase, Row } from '../storage/database.js';
import { hashPassword, verifyPassword } from './passwords.js';
export { hashPassword, verifyPassword } from './passwords.js';

export class AuthError extends Error {
  constructor(readonly status: number, readonly code: string, message: string) { super(message); this.name = 'AuthError'; }
}
function fail(status = 401, code = 'unauthorized', message = 'Authentication required'): never { throw new AuthError(status, code, message); }
const digest = (raw: string) => createHash('sha256').update(raw).digest('hex');
const secret = (size: number) => randomBytes(size).toString('base64url');
const ACCESS_TTL = 600000, IDLE_TTL = 30 * 86400000, ABSOLUTE_TTL = 90 * 86400000;
const active = (row: Row | undefined) => !!row && row.deleted_at == null && (row.is_active === true || row.is_active === 1);
const bool = (value: Json | undefined) => value === true || value === 1;
const future = (value: Json | undefined, now: number) => typeof value === 'string' && Date.parse(value) > now;
const preferences = (u: Row): JsonObject => {
  const p = u.preferences && typeof u.preferences === 'object' && !Array.isArray(u.preferences) ? u.preferences : {};
  return typeof p.enable_memory === 'boolean' ? { enable_memory: p.enable_memory } : {};
};
export type AuthAction = 'read' | 'write' | 'admin' | 'import' | 'export' | 'kb.write' | 'kb.delete' | 'document.write' | 'document.delete' | 'document.move' | 'chunk.write' | 'wiki.write' | 'agent.write' | 'eval.write' | 'task.write' | 'credentials.manage' | 'member.manage' | 'tenant.admin' | 'tenant.create';
export interface RegisterInput { username?: string; email?: string; password: string; mode?: 'device' | 'bearer'; deviceName?: string; clientType?: 'web' | 'desktop' }
export interface LoginInput { login: string; password: string; mode?: 'device' | 'bearer'; deviceName?: string; clientType?: 'web' | 'desktop' }
export interface PublicIdentity extends JsonObject { user: JsonObject; tenant: JsonObject; memberships: JsonObject[]; device: JsonObject | null; auth_mode: string }
/** Credentials and context are exclusively for trusted adapters. Send only `public` to renderer. */
export interface AuthIssue { public: PublicIdentity; context: AuthContext; credentials: { access: string; refresh: string; accessExpiresAt: string; refreshExpiresAt: string } }

export class AuthService {
  private readonly now: () => number;
  private channelAuthority?: (context: AuthContext) => AuthContext;
  /** Trusted core registration. A public grant is never accepted by authenticateAccess/Bearer. */
  registerChannelAuthority(validate: (context: AuthContext) => AuthContext): () => void {
    if (this.channelAuthority) fail(409, 'channel_authority_exists', 'Channel authority is already registered');
    this.channelAuthority = validate;
    return () => { if (this.channelAuthority === validate) this.channelAuthority = undefined; };
  }
  constructor(readonly database: CoreDatabase, private readonly options: { now?: () => number; allowAutoSetup?: boolean } = {}) { this.now = options.now ?? Date.now; }
  private iso(time = this.now()) { return new Date(time).toISOString(); }
  private user(id: string): Row { const user = this.database.read('users', id); if (!active(user)) fail(); return user!; }
  private tenant(id: string): Row { const t = this.database.read('tenants', id); if (!t || t.deleted_at != null || t.status !== 'active') fail(); return t; }
  private role(u: Row, t: Row): string | null {
    if (!active(u) || t.deleted_at != null || t.status !== 'active') return null;
    const m = this.database.get('select * from tenant_members where user_id=? and tenant_id=?', String(u.id), String(t.id));
    if (t.space_type === 'personal') return String(t.personal_owner_id) === String(u.id) && m?.status === 'active' && m.deleted_at == null ? 'owner' : null;
    // A retained revocation marker always defeats primary-tenant compatibility.
    if (m && (m.status !== 'active' || m.deleted_at != null)) return null;
    if (bool(u.is_system_admin) || bool(u.can_access_all_tenants)) return 'owner';
    if (m) return ['owner', 'admin', 'editor', 'viewer'].includes(String(m.role)) ? String(m.role) : 'viewer';
    return String(u.tenant_id) === String(t.id) ? 'owner' : null;
  }
  private context(user: Row, tenantId: string, deviceId: string): AuthContext {
    const t = this.tenant(tenantId), role = this.role(user, t);
    if (!role) fail();
    return { userId: String(user.id), tenantId: String(t.id), role: role!, deviceId, isSystemAdmin: bool(user.is_system_admin) };
  }
  private validSession(s: Row | undefined, access = false): s is Row {
    return !!s && s.revoked_at == null && future(s.idle_expires_at, this.now()) && future(s.absolute_expires_at, this.now()) && (!access || future(s.access_expires_at, this.now()));
  }
  /** Revalidate authoritative state on every domain call, including long-running stream checks. */
  private validate(ctx: AuthContext): AuthContext {
    if (ctx.channel || ctx.deviceId.startsWith('channel:')) {
      if (!ctx.channel || !this.channelAuthority) fail();
      const c = this.channelAuthority!(ctx), u = this.user(c.userId), t = this.tenant(c.tenantId);
      if (!['owner', 'admin', 'editor'].includes(this.role(u, t) ?? '') || !c.channel || c.deviceId !== `channel:${c.channel.grantId}`) fail();
      return { ...c, role: 'channel', isSystemAdmin: false };
    }
    if (!ctx.userId) {
      const t = this.tenant(ctx.tenantId);
      if (t.space_type === 'personal' || ctx.deviceId !== `api:${digest(String(t.api_key))}`) fail();
      return { userId: '', tenantId: String(t.id), role: 'service', deviceId: ctx.deviceId, isSystemAdmin: false };
    }
    const u = this.user(ctx.userId);
    if (ctx.deviceId.startsWith('legacy:')) {
      const token = this.database.read('auth_tokens', ctx.deviceId.slice(7));
      if (!token || String(token.user_id) !== ctx.userId || token.token_type !== 'access' || bool(token.is_revoked) || token.deleted_at != null || !future(token.expires_at, this.now())) fail();
    } else {
      const s = this.database.read('device_sessions', ctx.deviceId);
      if (!this.validSession(s) || String(s.user_id) !== ctx.userId) fail();
    }
    return this.context(u, ctx.tenantId, ctx.deviceId);
  }
  authenticateAccess(raw: string, tenantId?: string): AuthContext {
    if (!raw) fail();
    const s = this.database.get('select * from device_sessions where access_digest=?', digest(raw));
    if (!this.validSession(s, true)) fail();
    const u = this.user(String(s.user_id));
    return this.context(u, tenantId ?? String(u.tenant_id), String(s.id));
  }
  authenticateLegacyBearer(raw: string, tenantId?: string): AuthContext {
    if (!raw) fail();
    const t = this.database.get('select * from auth_tokens where token=? and token_type=?', raw, 'access');
    if (!t || bool(t.is_revoked) || t.deleted_at != null || !future(t.expires_at, this.now())) fail();
    const u = this.user(String(t.user_id));
    return this.context(u, tenantId ?? String(u.tenant_id), `legacy:${String(t.id)}`);
  }
  authenticateApiKey(raw: string, tenantId?: string): AuthContext {
    if (!raw) fail();
    const t = this.database.get('select * from tenants where api_key=?', raw);
    if (!t || t.status !== 'active' || t.deleted_at != null || t.space_type === 'personal' || (tenantId !== undefined && tenantId !== String(t.id))) fail();
    return { userId: '', tenantId: String(t.id), role: 'service', deviceId: `api:${digest(raw)}`, isSystemAdmin: false };
  }
  private deviceDto(s: Row, current: string): JsonObject {
    return { id: String(s.id), name: s.name!, client_type: s.client_type!, created_at: s.created_at!, last_seen_at: s.last_seen_at!, absolute_expires_at: s.absolute_expires_at!, expires_at: s.idle_expires_at!, is_revoked: s.revoked_at != null, current: String(s.id) === current };
  }
  private publicIdentity(ctx: AuthContext): PublicIdentity {
    const u = this.user(ctx.userId), t = this.tenant(ctx.tenantId);
    const memberships = this.database.all('select * from tenant_members where user_id=? and status=? and deleted_at is null', ctx.userId, 'active').filter(m => {
      const tenant = this.database.read('tenants', String(m.tenant_id));
      return tenant && tenant.status === 'active' && tenant.deleted_at == null && (tenant.space_type !== 'personal' || String(tenant.personal_owner_id) === ctx.userId);
    }).map(m => ({ id: String(m.id), tenant_id: String(m.tenant_id), user_id: ctx.userId, role: m.role!, status: m.status! }));
    const s = ctx.deviceId.startsWith('legacy:') ? undefined : this.database.read('device_sessions', ctx.deviceId);
    return {
      user: { id: String(u.id), username: u.username!, email: u.email!, avatar: u.avatar!, tenant_id: u.tenant_id === null ? null : String(u.tenant_id), is_active: true, can_access_all_tenants: bool(u.can_access_all_tenants), is_system_admin: bool(u.is_system_admin), preferences: preferences(u), created_at: u.created_at!, updated_at: u.updated_at! },
      tenant: { id: String(t.id), name: t.name!, description: t.description!, space_type: t.space_type!, personal_owner_id: t.personal_owner_id!, status: t.status!, api_key_configured: Boolean(t.api_key) },
      memberships, auth_mode: s ? 'cookie' : 'bearer', device: s ? this.deviceDto(s, ctx.deviceId) : null,
      ...(s ? { access_expires_at: s.access_expires_at! } : {}),
    };
  }
  me(ctx: AuthContext): PublicIdentity { const current = this.validate(ctx); if (!current.userId || current.channel) fail(); return this.publicIdentity(current); }
  private issue(u: Row, input: Pick<RegisterInput, 'mode' | 'deviceName' | 'clientType'>): AuthIssue {
    if (input.mode !== undefined && !['device', 'bearer'].includes(input.mode)) fail(400, 'invalid_auth_mode', 'Unsupported authentication mode');
    const now = this.now(), access = secret(36), refresh = secret(48);
    let ctx: AuthContext, accessExpiresAt: string, refreshExpiresAt: string;
    if (input.mode === 'bearer') {
      accessExpiresAt = this.iso(now + 8 * 3600000); refreshExpiresAt = this.iso(now + IDLE_TTL);
      const t = this.database.insert('auth_tokens', { user_id: u.id, token: access, token_type: 'access', expires_at: accessExpiresAt });
      this.database.insert('auth_tokens', { user_id: u.id, token: refresh, token_type: 'refresh', expires_at: refreshExpiresAt });
      ctx = this.context(u, String(u.tenant_id), `legacy:${String(t.id)}`);
    } else {
      accessExpiresAt = this.iso(now + ACCESS_TTL); refreshExpiresAt = this.iso(now + IDLE_TTL);
      const s = this.database.insert('device_sessions', { user_id: u.id, name: String(input.deviceName || (input.clientType === 'desktop' ? '桌面设备' : '网页设备')).slice(0, 100), client_type: input.clientType === 'desktop' ? 'desktop' : 'web', access_digest: digest(access), access_expires_at: accessExpiresAt, idle_expires_at: refreshExpiresAt, absolute_expires_at: this.iso(now + ABSOLUTE_TTL), last_seen_at: this.iso(), created_at: this.iso() });
      this.database.insert('device_refresh_tokens', { digest: digest(refresh), session_id: s.id, expires_at: refreshExpiresAt, created_at: this.iso() });
      ctx = this.context(u, String(u.tenant_id), String(s.id));
    }
    return { public: this.publicIdentity(ctx), context: ctx, credentials: { access, refresh, accessExpiresAt, refreshExpiresAt } };
  }
  private password(raw: string) { if (typeof raw !== 'string' || !raw || raw.length > 4096) fail(400, 'invalid_password', 'Password is required'); }
  private create(input: RegisterInput, admin = false): AuthIssue {
    this.password(input.password);
    const username = input.username || input.email?.split('@')[0] || `user-${secret(6)}`;
    const email = input.email || `${username}@local`;
    if (typeof username !== 'string' || typeof email !== 'string' || username.length > 150 || email.length > 254 || !email.includes('@')) fail(400, 'invalid_account', 'Invalid account fields');
    if (this.database.get('select id from users where username=? or email=?', username, email)) fail(409, 'user_exists', 'User already exists');
    const u = this.database.insert('users', { username, email, password_hash: hashPassword(input.password), is_system_admin: admin });
    const t = this.database.insert('tenants', { name: `${username} 的空间`, api_key: secret(24), space_type: 'personal', personal_owner_id: u.id });
    this.database.insert('tenant_members', { user_id: u.id, tenant_id: t.id, role: 'owner', status: 'active' });
    const updated = this.database.update('users', String(u.id), { tenant_id: t.id })!;
    return this.issue(updated, input);
  }
  register(input: RegisterInput): AuthIssue { return this.database.transaction(() => this.create(input)); }
  autoSetup(input: RegisterInput): AuthIssue {
    if (this.options.allowAutoSetup !== true) fail(401, 'auto_setup_disabled', 'Auto setup is disabled');
    return this.database.transaction(() => {
      if (this.database.get('select id from users where is_active=1 and deleted_at is null limit 1')) fail(401, 'setup_already_completed', 'Setup already completed');
      return this.create(input, true);
    });
  }
  login(input: LoginInput): AuthIssue {
    return this.database.transaction(() => {
      const row = this.database.get('select id from users where (username=? or email=?) and deleted_at is null', input.login, input.login);
      const u = row ? this.database.read('users', String(row.id)) : undefined;
      if (!active(u) || !verifyPassword(input.password, String(u?.password_hash)) || !u?.tenant_id || !this.role(u, this.tenant(String(u.tenant_id)))) fail(401, 'invalid_credentials', 'Invalid credentials');
      return this.issue(u!, input);
    });
  }
  private revoke(id: string, reason: string) { this.database.run('update device_sessions set revoked_at=?, revoke_reason=? where id=? and revoked_at is null', this.iso(), reason, id); }
  refresh(raw: string): AuthIssue {
    // Return null inside transaction so replay revocation commits before the error is raised.
    const result = this.database.transaction(() => {
      const token = raw ? this.database.read('device_refresh_tokens', digest(raw)) : undefined;
      if (!token) return null;
      const s = this.database.read('device_sessions', String(token.session_id));
      if (!s) return null;
      if (token.consumed_at != null) { this.revoke(String(s.id), 'refresh_replay'); return null; }
      if (!this.validSession(s) || !future(token.expires_at, this.now())) return null;
      const u = this.database.read('users', String(s.user_id));
      const t = u?.tenant_id == null ? undefined : this.database.read('tenants', String(u.tenant_id));
      if (!u || !t || !this.role(u, t)) { this.revoke(String(s.id), 'principal_disabled'); return null; }
      if (Number(this.database.run('update device_refresh_tokens set consumed_at=? where digest=? and consumed_at is null', this.iso(), String(token.digest)).changes) !== 1) { this.revoke(String(s.id), 'refresh_replay'); return null; }
      const access = secret(36), refresh = secret(48), absolute = Date.parse(String(s.absolute_expires_at));
      const accessExpiresAt = this.iso(Math.min(this.now() + ACCESS_TTL, absolute)), refreshExpiresAt = this.iso(Math.min(this.now() + IDLE_TTL, absolute));
      this.database.update('device_sessions', String(s.id), { access_digest: digest(access), access_expires_at: accessExpiresAt, idle_expires_at: refreshExpiresAt, last_seen_at: this.iso() });
      this.database.insert('device_refresh_tokens', { digest: digest(refresh), session_id: s.id, expires_at: refreshExpiresAt, created_at: this.iso() });
      const ctx = this.context(u, String(u.tenant_id), String(s.id));
      return { public: this.publicIdentity(ctx), context: ctx, credentials: { access, refresh, accessExpiresAt, refreshExpiresAt } };
    });
    if (!result) fail(401, 'invalid_refresh', 'Invalid refresh token');
    return result!;
  }
  refreshLegacy(raw: string): AuthIssue {
    return this.database.transaction(() => {
      const t = this.database.get('select * from auth_tokens where token=? and token_type=?', raw, 'refresh');
      if (!t || bool(t.is_revoked) || t.deleted_at != null || !future(t.expires_at, this.now())) fail(401, 'invalid_refresh', 'Invalid refresh token');
      const u = this.user(String(t.user_id)); this.context(u, String(u.tenant_id), `legacy:${String(t.id)}`);
      if (Number(this.database.run('update auth_tokens set is_revoked=1,updated_at=? where id=? and is_revoked=0', this.iso(), String(t.id)).changes) !== 1) fail(401, 'invalid_refresh', 'Invalid refresh token');
      return this.issue(u, { mode: 'bearer' });
    });
  }
  listDevices(ctx: AuthContext): JsonObject[] {
    const c = this.validate(ctx); if (!c.userId || c.channel) fail();
    return this.database.all('select * from device_sessions where user_id=? order by last_seen_at desc limit 100', c.userId).map(s => this.deviceDto(s, c.deviceId));
  }
  revokeDevice(ctx: AuthContext, id: string): void {
    this.database.transaction(() => {
      const c = this.validate(ctx); if (!c.userId || c.channel) fail();
      const s = this.database.read('device_sessions', id); if (!s || String(s.user_id) !== c.userId) fail(404, 'device_not_found', 'Device not found');
      this.revoke(id, 'user_revoked');
    });
  }
  logout(ctx: AuthContext): void {
    this.database.transaction(() => {
      const c = this.validate(ctx); if (!c.userId || c.channel) fail();
      if (c.deviceId.startsWith('legacy:')) this.database.update('auth_tokens', c.deviceId.slice(7), { is_revoked: true, updated_at: this.iso() });
      else this.revoke(c.deviceId, 'logout');
    });
  }
  /** Enables cookie logout after access expiry without issuing a new session. */
  logoutRefresh(raw: string): void {
    this.database.transaction(() => {
      const t = raw ? this.database.read('device_refresh_tokens', digest(raw)) : undefined;
      if (t) this.revoke(String(t.session_id), 'logout');
    });
  }
  private revokeAll(userId: string, reason: string) {
    this.database.run('update device_sessions set revoked_at=?,revoke_reason=? where user_id=? and revoked_at is null', this.iso(), reason, userId);
    this.database.run('update auth_tokens set is_revoked=1,updated_at=? where user_id=? and is_revoked=0', this.iso(), userId);
  }
  logoutAll(ctx: AuthContext): void { this.database.transaction(() => { const c = this.validate(ctx); if (!c.userId || c.channel) fail(); this.revokeAll(c.userId, 'logout_all'); }); }
  changePassword(ctx: AuthContext, oldPassword: string, newPassword: string): void {
    this.password(newPassword);
    this.database.transaction(() => {
      const c = this.validate(ctx); if (!c.userId || c.channel) fail(); const u = this.user(c.userId);
      if (!verifyPassword(oldPassword, String(u.password_hash))) fail(400, 'old_password_mismatch', 'Old password mismatch');
      this.database.update('users', c.userId, { password_hash: hashPassword(newPassword), updated_at: this.iso() });
      this.revokeAll(c.userId, 'password_changed');
    });
  }
  updatePreferences(ctx: AuthContext, patch: JsonObject): PublicIdentity {
    if (!patch || typeof patch !== 'object' || Array.isArray(patch) || Object.keys(patch).some(k => k !== 'enable_memory') || ('enable_memory' in patch && typeof patch.enable_memory !== 'boolean')) fail(400, 'invalid_preferences', 'Unsupported preference field');
    return this.database.transaction(() => {
      const c = this.validate(ctx); if (!c.userId || c.channel) fail(); const u = this.user(c.userId);
      this.database.update('users', c.userId, { preferences: { ...(u.preferences as JsonObject), ...patch }, updated_at: this.iso() });
      return this.publicIdentity(c);
    });
  }
  assertCan(ctx: AuthContext, action: AuthAction, tenantId = ctx.tenantId, ownerId?: string): void {
    const c = this.validate(ctx);
    if (c.channel) {
      if (tenantId !== c.tenantId || (ownerId !== undefined && ownerId !== c.userId) || !['read', 'write', 'agent.write'].includes(action)) fail(403, 'channel_action_forbidden', 'Channel grant cannot access this operation');
      return;
    }
    let scoped: AuthContext;
    try { scoped = c.userId ? this.context(this.user(c.userId), tenantId, c.deviceId) : c; } catch { fail(403, 'action_forbidden', 'Action forbidden'); }
    if (!c.userId && tenantId !== c.tenantId) fail(403, 'action_forbidden', 'Action forbidden');
    if (ownerId !== undefined && (!c.userId || ownerId !== c.userId)) fail(403, 'user_principal_required', 'User resource owner required');
    const reads = ['read', 'export'], writes = ['write', 'import', 'kb.write', 'document.write', 'document.delete', 'document.move', 'chunk.write', 'wiki.write', 'agent.write', 'eval.write', 'task.write'];
    const admins = ['admin', 'kb.delete', 'credentials.manage', 'member.manage', 'tenant.admin'];
    const role = scoped!.role;
    const allowed = reads.includes(action) || (['editor', 'admin', 'owner'].includes(role) && writes.includes(action)) || (['admin', 'owner'].includes(role) && admins.includes(action)) || (action === 'tenant.create' && !!c.userId);
    if (!allowed) fail(403, 'action_forbidden', 'Action forbidden');
  }
  sessionIsActive(deviceId: string, userId: string, tenantId: string): boolean {
    try { this.validate({ deviceId, userId, tenantId, role: '', isSystemAdmin: false }); return !!userId; } catch { return false; }
  }
}
