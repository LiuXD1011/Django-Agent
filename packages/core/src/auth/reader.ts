import { createHash } from 'node:crypto';
import type { AuthContext, Json, JsonObject } from '../contracts.js';
import type { Row } from '../storage/row-codec.js';
import type { DatabaseReader } from '../storage/read-database.js';

export class AuthError extends Error {
  constructor(readonly status: number, readonly code: string, message: string) { super(message); this.name = 'AuthError'; }
}
function fail(status = 401, code = 'unauthorized', message = 'Authentication required'): never { throw new AuthError(status, code, message); }
const digest = (raw: string) => createHash('sha256').update(raw).digest('hex');
const active = (row: Row | undefined) => !!row && row.deleted_at == null && (row.is_active === true || row.is_active === 1);
const bool = (value: Json | undefined) => value === true || value === 1;
const future = (value: Json | undefined, now: number) => typeof value === 'string' && Date.parse(value) > now;
const preferences = (u: Row): JsonObject => {
  const p = u.preferences && typeof u.preferences === 'object' && !Array.isArray(u.preferences) ? u.preferences : {};
  return typeof p.enable_memory === 'boolean' ? { enable_memory: p.enable_memory } : {};
};
export type AuthAction = 'read' | 'write' | 'admin' | 'import' | 'export' | 'kb.write' | 'kb.delete' | 'document.write' | 'document.delete' | 'document.move' | 'chunk.write' | 'wiki.write' | 'agent.write' | 'eval.write' | 'task.write' | 'credentials.manage' | 'member.manage' | 'tenant.admin' | 'tenant.create';
export interface PublicIdentity extends JsonObject { user: JsonObject; tenant: JsonObject; memberships: JsonObject[]; device: JsonObject | null; auth_mode: string }

export class AuthReader {
  protected readonly now: () => number;
  private channelAuthority?: (context: AuthContext) => AuthContext;
  /** Trusted core registration. A public grant is never accepted by authenticateAccess/Bearer. */
  registerChannelAuthority(validate: (context: AuthContext) => AuthContext): () => void {
    if (this.channelAuthority) fail(409, 'channel_authority_exists', 'Channel authority is already registered');
    this.channelAuthority = validate;
    return () => { if (this.channelAuthority === validate) this.channelAuthority = undefined; };
  }
  constructor(readonly database: DatabaseReader, options: { now?: () => number } = {}) { this.now = options.now ?? Date.now; }
  protected iso(time = this.now()) { return new Date(time).toISOString(); }
  protected user(id: string): Row { const user = this.database.read('users', id); if (!active(user)) fail(); return user!; }
  protected tenant(id: string): Row { const t = this.database.read('tenants', id); if (!t || t.deleted_at != null || t.status !== 'active') fail(); return t; }
  protected role(u: Row, t: Row): string | null {
    if (!active(u) || t.deleted_at != null || t.status !== 'active') return null;
    const m = this.database.get('select * from tenant_members where user_id=? and tenant_id=?', String(u.id), String(t.id));
    if (t.space_type === 'personal') return String(t.personal_owner_id) === String(u.id) && m?.status === 'active' && m.deleted_at == null ? 'owner' : null;
    // A retained revocation marker always defeats primary-tenant compatibility.
    if (m && (m.status !== 'active' || m.deleted_at != null)) return null;
    if (bool(u.is_system_admin) || bool(u.can_access_all_tenants)) return 'owner';
    if (m) return ['owner', 'admin', 'editor', 'viewer'].includes(String(m.role)) ? String(m.role) : 'viewer';
    return String(u.tenant_id) === String(t.id) ? 'owner' : null;
  }
  protected context(user: Row, tenantId: string, deviceId: string): AuthContext {
    const t = this.tenant(tenantId), role = this.role(user, t);
    if (!role) fail();
    return { userId: String(user.id), tenantId: String(t.id), role: role!, deviceId, isSystemAdmin: bool(user.is_system_admin) };
  }
  protected validSession(s: Row | undefined, access = false): s is Row {
    return !!s && s.revoked_at == null && future(s.idle_expires_at, this.now()) && future(s.absolute_expires_at, this.now()) && (!access || future(s.access_expires_at, this.now()));
  }
  /** Revalidate authoritative state on every domain call, including long-running stream checks. */
  protected validate(ctx: AuthContext): AuthContext {
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
  protected publicIdentity(ctx: AuthContext): PublicIdentity {
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
  listDevices(ctx: AuthContext): JsonObject[] {
    const c = this.validate(ctx); if (!c.userId || c.channel) fail();
    return this.database.all('select * from device_sessions where user_id=? order by last_seen_at desc limit 100', c.userId).map(s => this.deviceDto(s, c.deviceId));
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

export { fail as authFail, digest as authDigest, active as authActive, bool as authBoolean, future as authFuture };
