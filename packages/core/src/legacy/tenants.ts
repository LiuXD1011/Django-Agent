import { randomBytes } from 'node:crypto';
import type { AuthContext, Json, JsonObject } from '../contracts.js';
import type { AuthService } from '../auth/index.js';
import type { CoreDatabase, Row } from '../storage/database.js';
import { AppError } from '../errors.js';

const fail = (status: number, code: string, message: string): never => { throw new AppError(status, code, message); };
const now = () => new Date().toISOString();
function text(value: Json | undefined, fallback: string, max = 255): string { if (value === undefined) return fallback; if (typeof value !== 'string' || value.length > max) fail(400, 'invalid_tenant', '空间字段格式不正确。'); return value as string; }
function role(value: Json | undefined): string { const result = value ?? 'viewer'; if (!['owner', 'admin', 'editor', 'viewer'].includes(String(result))) fail(400, 'invalid_member_role', '成员角色不受支持。'); return String(result); }
function tenantDto(row: Row): JsonObject { return Object.fromEntries(['id', 'name', 'description', 'space_type', 'personal_owner_id', 'status', 'business', 'storage_quota', 'storage_used', 'created_at', 'updated_at'].map(k => [k, row[k] ?? null]).concat([['api_key_configured', Boolean(row.api_key)]])); }
function memberDto(row: Row): JsonObject { return { tenant_id: row.tenant_id!, user_id: row.user_id!, role: row.role!, status: row.status!, joined_at: row.joined_at! }; }
function userDto(row: Row): JsonObject { return Object.fromEntries(['id', 'username', 'email', 'avatar', 'tenant_id', 'is_active', 'can_access_all_tenants', 'is_system_admin', 'created_at', 'updated_at'].map(k => [k, row[k] ?? null])); }
function safeDetails(value: Json | undefined): JsonObject {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  const keys = ['resource_id', 'member_id', 'user_id', 'tenant_id', 'knowledge_base_id', 'knowledge_id', 'request_id', 'role', 'status', 'code'];
  return Object.fromEntries(Object.entries(value).filter(([key, item]) => keys.includes(key) && (typeof item === 'number' && Number.isSafeInteger(item) || typeof item === 'string' && /^[\w.:-]{0,128}$/.test(item))));
}

/** Existing legacy-space management only; no invitation or cloud provisioning placeholders. */
export class LegacyTenantService {
  constructor(readonly db: CoreDatabase, readonly auth: AuthService) {}
  private target(ctx: AuthContext, id: string): Row {
    this.auth.assertCan(ctx, 'read'); const row = this.db.read('tenants', id);
    if (!row || row.deleted_at !== null || row.status !== 'active') fail(404, 'tenant_not_found', '空间不存在。');
    try { this.auth.assertCan(ctx, 'read', id); } catch { return fail(404, 'tenant_not_found', '空间不存在。'); }
    return row!;
  }
  private admin(ctx: AuthContext, id: string, member = false): Row { const row = this.target(ctx, id); this.auth.assertCan(ctx, member ? 'member.manage' : 'tenant.admin', id); return row; }
  private audit(ctx: AuthContext, id: string, action: string, targetId: string, details: JsonObject = {}): void {
    this.db.insert('audit_logs', { tenant_id: id, actor_user_id: ctx.userId, actor_role: ctx.role, action, target_type: 'tenant', target_id: targetId, outcome: 'success', details: safeDetails(details) });
  }
  list(ctx: AuthContext, query: JsonObject = {}): JsonObject {
    this.auth.assertCan(ctx, 'read'); const needle = text(query.keyword ?? query.query ?? query.q, '', 4096).toLocaleLowerCase();
    const items: JsonObject[] = [];
    for (const item of this.db.all("SELECT id FROM tenants WHERE deleted_at IS NULL AND status='active' ORDER BY created_at,id")) {
      try { const row = this.target(ctx, String(item.id)); if (!needle || `${row.name} ${row.description}`.toLocaleLowerCase().includes(needle)) items.push(tenantDto(row)); } catch (e) { if (!(e instanceof AppError) || e.status !== 404) throw e; }
    }
    return { items, tenants: items };
  }
  get(ctx: AuthContext, id: string): JsonObject { return tenantDto(this.target(ctx, id)); }
  create(ctx: AuthContext, input: JsonObject): JsonObject {
    this.auth.assertCan(ctx, 'tenant.create');
    return this.db.transaction(() => {
      this.auth.assertCan(ctx, 'tenant.create');
      const row = this.db.insert('tenants', { name: text(input.name, '新空间'), description: text(input.description, '', 16384), business: text(input.business, 'default'), space_type: 'legacy', personal_owner_id: null, api_key: randomBytes(24).toString('base64url') });
      this.db.insert('tenant_members', { user_id: ctx.userId, tenant_id: row.id, role: 'owner', status: 'active', invited_by: ctx.userId });
      this.audit(ctx, String(row.id), 'tenant.created', String(row.id)); return tenantDto(row);
    });
  }
  update(ctx: AuthContext, id: string, input: JsonObject): JsonObject {
    return this.db.transaction(() => {
      const previous = this.admin(ctx, id), values: JsonObject = { updated_at: now() };
      for (const key of ['name', 'description', 'business']) if (input[key] !== undefined) values[key] = text(input[key], String(previous[key]), key === 'description' ? 16384 : 255);
      if (input.status !== undefined) { if (!['active', 'disabled'].includes(String(input.status))) fail(400, 'invalid_tenant_status', '空间状态不受支持。'); values.status = input.status!; }
      const next = this.db.update('tenants', id, values)!; this.audit(ctx, id, 'tenant.updated', id); return tenantDto(next);
    });
  }
  delete(ctx: AuthContext, id: string): JsonObject {
    return this.db.transaction(() => { this.admin(ctx, id); this.db.update('tenants', id, { deleted_at: now(), updated_at: now() }); this.audit(ctx, id, 'tenant.deleted', id); return {}; });
  }
  switch(ctx: AuthContext, id: string): JsonObject {
    this.auth.assertCan(ctx, 'read'); this.auth.assertCan(ctx, 'read', id);
    const row = this.target(ctx, id); if (!ctx.userId) fail(403, 'user_principal_required', '切换空间需要用户身份。');
    return { tenant: tenantDto(row), user: userDto(this.db.read('users', ctx.userId)!) };
  }
  members(ctx: AuthContext, id: string): JsonObject {
    const tenant = this.target(ctx, id);
    const items = this.db.all("SELECT id FROM tenant_members WHERE tenant_id=? AND status='active' AND deleted_at IS NULL ORDER BY joined_at,id", id).map(item => this.db.read('tenant_members', String(item.id))!).filter(item => tenant.space_type !== 'personal' || item.user_id === tenant.personal_owner_id).map(item => ({ ...memberDto(item), user: userDto(this.db.read('users', String(item.user_id))!) }));
    return { items };
  }
  setMember(ctx: AuthContext, id: string, input: JsonObject, userId?: string): JsonObject {
    return this.db.transaction(() => {
      const tenant = this.admin(ctx, id, true); if (tenant.space_type === 'personal') fail(409, 'personal_space_not_shareable', '个人空间不能共享。');
      const targetId = userId ?? (typeof input.user_id === 'string' ? input.user_id : undefined);
      const found = targetId ? this.db.read('users', targetId) : this.db.get('SELECT id FROM users WHERE email=? AND deleted_at IS NULL', text(input.email, '', 254));
      const user = found ? this.db.read('users', String(found.id)) : undefined;
      if (!user || user.deleted_at !== null || user.is_active !== true) fail(404, 'user_not_found', '用户不存在。');
      const previous = this.db.get('SELECT id FROM tenant_members WHERE tenant_id=? AND user_id=?', id, String(user!.id));
      if (userId && !previous) fail(404, 'member_not_found', '成员不存在。');
      const current = previous ? this.db.read('tenant_members', String(previous.id))! : undefined;
      const nextRole = role(input.role ?? current?.role);
      const row = previous ? this.db.update('tenant_members', String(previous.id), { role: nextRole, status: 'active', deleted_at: null, updated_at: now() })! : this.db.insert('tenant_members', { tenant_id: id, user_id: user!.id, role: nextRole, status: 'active', invited_by: ctx.userId });
      this.audit(ctx, id, 'tenant.member_updated', String(user!.id), { member_id: String(user!.id), role: nextRole }); return memberDto(row);
    });
  }
  removeMember(ctx: AuthContext, id: string, userId: string): JsonObject {
    return this.db.transaction(() => {
      const tenant = this.admin(ctx, id, true); if (tenant.space_type === 'personal') fail(409, 'personal_space_not_shareable', '个人空间不能共享。');
      const member = this.db.get('SELECT id FROM tenant_members WHERE tenant_id=? AND user_id=?', id, userId); if (!member) fail(404, 'member_not_found', '成员不存在。');
      this.db.update('tenant_members', String(member!.id), { status: 'revoked', updated_at: now() }); this.audit(ctx, id, 'tenant.member_revoked', userId, { member_id: userId }); return {};
    });
  }
  /** Trusted adapter chooses revealKey. IPC callers never choose this option. */
  rotateApiKey(ctx: AuthContext, id: string, options: { revealKey: boolean }): JsonObject {
    return this.db.transaction(() => { this.admin(ctx, id); this.auth.assertCan(ctx, 'credentials.manage', id); const key = randomBytes(24).toString('base64url'); const row = this.db.update('tenants', id, { api_key: key, updated_at: now() })!; this.audit(ctx, id, 'tenant.api_key_rotated', id); return { ...tenantDto(row), rotated: true, ...(options.revealKey ? { api_key: key } : {}) }; });
  }
  auditLog(ctx: AuthContext, id?: string): JsonObject {
    this.auth.assertCan(ctx, 'read'); const global = id === undefined && !!ctx.userId && this.auth.me(ctx).user.is_system_admin === true;
    const tenantId = id ?? ctx.tenantId; if (!global) this.target(ctx, tenantId);
    const rows = this.db.all(`SELECT id FROM audit_logs ${global ? '' : 'WHERE tenant_id=?'} ORDER BY created_at DESC,id DESC LIMIT 100`, ...(global ? [] : [tenantId]));
    return { items: rows.map(item => { const row = this.db.read('audit_logs', String(item.id))!; return { id: row.id!, action: row.action!, outcome: row.outcome!, created_at: row.created_at!, details: safeDetails(row.details) }; }) };
  }
}
