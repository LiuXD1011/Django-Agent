import { randomBytes } from 'node:crypto';
import type { AuthContext, JsonObject } from '../contracts.js';
import type { CoreDatabase, Row } from '../storage/database.js';
import { AuthReader, authFail as fail, authDigest as digest, authActive as active, authBoolean as bool, authFuture as future, type PublicIdentity } from './reader.js';
import { hashPassword, verifyPassword } from './passwords.js';
export { hashPassword, verifyPassword } from './passwords.js';
export { AuthError, type AuthAction, type PublicIdentity } from './reader.js';

const secret = (size: number) => randomBytes(size).toString('base64url');
const ACCESS_TTL = 600000, IDLE_TTL = 30 * 86400000, ABSOLUTE_TTL = 90 * 86400000;
export interface RegisterInput { username?: string; email?: string; password: string; mode?: 'device' | 'bearer'; deviceName?: string; clientType?: 'web' | 'desktop' }
export interface LoginInput { login: string; password: string; mode?: 'device' | 'bearer'; deviceName?: string; clientType?: 'web' | 'desktop' }
/** Credentials and context are exclusively for trusted adapters. Send only `public` to renderer. */
export interface AuthIssue { public: PublicIdentity; context: AuthContext; credentials: { access: string; refresh: string; accessExpiresAt: string; refreshExpiresAt: string } }

export class AuthService extends AuthReader {
  constructor(override readonly database: CoreDatabase, private readonly options: { now?: () => number; allowAutoSetup?: boolean } = {}) { super(database, options); }
  /** Trusted owner cleanup for an issue superseded by a later auth intent. */
  discardIssue(issue: AuthIssue): void {
    this.database.transaction(() => {
      const { userId, deviceId } = issue.context;
      if (deviceId.startsWith('legacy:')) {
        for (const [type, token] of [['access', issue.credentials.access], ['refresh', issue.credentials.refresh]]) {
          this.database.run('UPDATE auth_tokens SET is_revoked=1,updated_at=? WHERE user_id=? AND token_type=? AND token=? AND is_revoked=0', this.iso(), userId, type!, token!);
        }
      } else this.database.run('UPDATE device_sessions SET revoked_at=?,revoke_reason=? WHERE id=? AND user_id=? AND access_digest=? AND revoked_at IS NULL', this.iso(), 'auth_superseded', deviceId, userId, digest(issue.credentials.access));
    });
  }
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
}
