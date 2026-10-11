import { createHash, randomBytes, randomUUID } from 'node:crypto';
import type { AuthContext, ChannelPrincipal, JsonObject } from '../contracts.js';
import type { CoreDatabase } from '../storage/database.js';
import { AuthError, type AuthService } from './index.js';

export interface ChannelGrant extends JsonObject { userId: string; tenantId: string; channel: ChannelPrincipal }
const denied = (): never => { throw new AuthError(401, 'invalid_channel_grant', '公开渠道凭证无效或已过期。'); };
const digest = (raw: string) => createHash('sha256').update(raw).digest('hex');
const key = (id: string) => `channel.grant:${id}`;
/** Hash-only, one-hour guest credentials. The callback must recheck the live channel/version/scope. */
export class ChannelGrantAuthority {
  private readonly release: () => void; private closed = false;
  constructor(readonly db: CoreDatabase, readonly auth: AuthService, readonly current: (grant: ChannelGrant) => boolean, readonly now: () => number = Date.now) {
    this.release = auth.registerChannelAuthority(context => this.validate(context));
  }
  /** Exchange already verified the channel's actual owner; no creator device is needed thereafter. */
  issueOwned(userId: string, tenantId: string, channelId: string, version: string, origin: string, knowledgeBaseIds: string[]): JsonObject {
    if (this.closed) denied();
    const token = randomBytes(36).toString('base64url'), channel: ChannelPrincipal = { id: channelId, grantId: digest(token), guestId: randomUUID(), version, origin, expiresAt: this.now() + 3600000, knowledgeBaseIds: [...knowledgeBaseIds] };
    const grant: ChannelGrant = { userId, tenantId, channel }; const context = this.context(grant);
    if (!this.current(grant)) denied();
    this.db.run('INSERT INTO desktop_meta(key,value) VALUES(?,?)', key(channel.grantId), JSON.stringify(grant));
    try { this.auth.assertCan(context, 'write'); } catch (e) { this.db.run('DELETE FROM desktop_meta WHERE key=?', key(channel.grantId)); throw e; }
    return { token, expires_in: 3600, expires_at: new Date(channel.expiresAt).toISOString(), guest_id: channel.guestId };
  }
  private context(grant: ChannelGrant): AuthContext { return { userId: grant.userId, tenantId: grant.tenantId, deviceId: `channel:${grant.channel.grantId}`, role: 'channel', isSystemAdmin: false, channel: structuredClone(grant.channel) }; }
  private read(id: string): ChannelGrant {
    if (this.closed || !/^[a-f0-9]{64}$/.test(id)) denied();
    const row = this.db.get('SELECT value FROM desktop_meta WHERE key=?', key(id)); if (!row) return denied();
    let grant: ChannelGrant; try { grant = JSON.parse(String(row.value)) as ChannelGrant; } catch { return denied(); }
    if (!grant.channel || grant.channel.grantId !== id || !Number.isFinite(grant.channel.expiresAt) || grant.channel.expiresAt <= this.now() || !this.current(grant)) denied();
    return grant;
  }
  private validate(ctx: AuthContext): AuthContext {
    if (!ctx.channel) return denied(); const grant = this.read(ctx.channel.grantId);
    if (ctx.userId !== grant.userId || ctx.tenantId !== grant.tenantId || ctx.deviceId !== `channel:${grant.channel.grantId}` || JSON.stringify(ctx.channel) !== JSON.stringify(grant.channel)) denied();
    return this.context(grant);
  }
  authenticate(token: string, channelId: string, origin: string): AuthContext {
    if (!/^[\w-]{48}$/.test(token)) return denied(); const grant = this.read(digest(token));
    if (grant.channel.id !== channelId || grant.channel.origin !== origin) denied();
    const ctx = this.context(grant); this.auth.assertCan(ctx, 'read'); return ctx;
  }
  close(): void { this.closed = true; this.release(); }
}
