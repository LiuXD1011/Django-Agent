import { CoreApplication, errorResponse, validateCoreRequest, type CoreFrame, type PrivateBinding, type PrivateDispatch } from '../application.js';
import type { CoreRequest, CoreResponse, JsonObject } from '../contracts.js';
import { AppError } from '../errors.js';
import type { DocumentUpload } from '../documents/workflow.js';
import { parseStoredJson } from '../storage/json.js';
import { validateNativeLangfuseRequest, type NativeLangfuseRequest, type NativeLangfusePlan, type SessionCookie } from '../integrations/langfuse-login.js';
import { coreRequestUrl, isSessionChange } from '../routing.js';
import { createHash, randomUUID } from 'node:crypto';
import type { AuthIssue } from '../auth/index.js';

interface PrivateSession { access: string; refresh: string; }
interface RefreshUndo {
  device: { id: string; userId: string; accessDigest: string; accessExpiresAt: string; idleExpiresAt: string; lastSeenAt: string; revokeReason: string };
  refresh: { digest: string; consumedAt: string | null };
}
interface PendingInvocation { issue: AuthIssue; previous?: PrivateSession; replacement: PrivateSession; undo?: RefreshUndo }
interface InvocationState { session?: PrivateSession; commits: Map<string, PendingInvocation> }
interface IpcExecution extends PrivateDispatch { commit?: string }
export interface IpcOptions { tenantId?: string; upload?: { name: string; bytes: Uint8Array }; }
export interface IpcResponse extends CoreResponse { binary?: { bytes: Uint8Array; name: string; mimeType: string; sha256: string }; }
export interface IpcStream { response: CoreResponse; frames?: AsyncIterable<CoreFrame> }
export interface NativeLangfuseResponse { response: CoreResponse; plan?: NativeLangfusePlan; cookies?: SessionCookie[] }
/** Constructed by the trusted owner runtime; never accepted in renderer options. */
export interface IpcInvocationFence { isCurrent(): boolean }
const sessionKey = 'ipc.session';
const receiptsKey = 'ipc.receipts';
const digest = (value: string) => createHash('sha256').update(value).digest('hex');
const sameSession = (a?: PrivateSession, b?: PrivateSession) => a === b || !!a && !!b && a.access === b.access && a.refresh === b.refresh;
const undoUnavailable = Symbol('refresh_undo_unavailable');
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid private IPC record');
  return value as Record<string, unknown>;
}
function sessionValue(value: unknown): PrivateSession {
  const record = object(value);
  if (Object.keys(record).some(key => !['access', 'refresh'].includes(key)) || typeof record.access !== 'string' || !record.access || typeof record.refresh !== 'string' || !record.refresh) throw new Error('Invalid private IPC session');
  return { access: record.access, refresh: record.refresh };
}

/** Transport adapter without Electron imports. Main/preload still check sender/frame. */
export class CoreIpcAdapter {
  #session?: PrivateSession;
  #epoch = 0;
  #commits = new Map<string, PendingInvocation>();
  constructor(readonly app: CoreApplication) {
    const saved = app.database.get('SELECT value FROM desktop_meta WHERE key=?', sessionKey);
    if (saved) {
      try { this.#session = sessionValue(this.decrypt(String(saved.value))); }
      catch { throw new AppError(503, 'ipc_credentials_unavailable', '桌面登录凭据无法解密，请检查数据目录和密钥。'); }
    }
    const journal = app.database.get('SELECT value FROM desktop_meta WHERE key=?', receiptsKey);
    if (journal) {
      try {
        const record = object(this.decrypt(String(journal.value), true));
        if (record.version !== 1 || !Array.isArray(record.pending) || !record.pending.length || record.pending.length > 128) throw new Error();
        const current = record.current === undefined ? undefined : sessionValue(record.current);
        if (!sameSession(current, this.#session)) throw new Error();
        for (const entry of record.pending) {
          const receipt = object(entry), issue = object(receipt.issue), context = object(issue.context), credentials = object(issue.credentials);
          if (typeof receipt.commit !== 'string' || !/^[0-9a-f-]{36}$/.test(receipt.commit) || this.#commits.has(receipt.commit) ||
            !['userId', 'tenantId', 'deviceId', 'role'].every(key => typeof context[key] === 'string' && !!context[key]) || typeof context.isSystemAdmin !== 'boolean' ||
            !['access', 'refresh', 'accessExpiresAt', 'refreshExpiresAt'].every(key => typeof credentials[key] === 'string' && !!credentials[key])) throw new Error();
          object(issue.public);
          const replacement = sessionValue(receipt.replacement), previous = receipt.previous === undefined ? undefined : sessionValue(receipt.previous);
          if (replacement.access !== credentials.access || replacement.refresh !== credentials.refresh || sameSession(previous, replacement)) throw new Error();
          let undo: RefreshUndo | undefined;
          if (receipt.undo !== undefined) {
            const value = object(receipt.undo), device = object(value.device), refresh = object(value.refresh);
            if (!previous || !['id', 'userId', 'accessDigest', 'accessExpiresAt', 'idleExpiresAt', 'lastSeenAt'].every(key => typeof device[key] === 'string' && !!device[key]) ||
              typeof device.revokeReason !== 'string' || device.id !== context.deviceId || device.userId !== context.userId ||
              device.accessDigest !== digest(previous.access) || refresh.digest !== digest(previous.refresh) || refresh.consumedAt !== null) throw new Error();
            undo = value as unknown as RefreshUndo;
          }
          this.#commits.set(receipt.commit, { issue: issue as unknown as AuthIssue, previous, replacement, undo });
        }
      } catch { throw new AppError(503, 'ipc_receipts_unavailable', '桌面登录确认记录无法解密或校验，请检查数据目录和密钥。'); }
      // Decode every entry before any write; recovery and both stored records commit together.
      const state = app.database.transaction(() => {
        let next: InvocationState = { session: this.#session, commits: this.#commits };
        for (const commit of [...next.commits.keys()]) next = this.settledState(next, commit, false);
        this.writeState(next); return next;
      });
      this.#session = state.session; this.#commits = state.commits;
    }
  }
  private decrypt(text: string, encrypted = false): unknown {
    const envelope = object(parseStoredJson(text));
    if (typeof envelope.token !== 'string' || encrypted && !envelope.token.startsWith('enc:v1:')) throw new Error();
    const opened = object(this.app.vault.decrypt(envelope as JsonObject));
    if (typeof opened.token !== 'string') throw new Error();
    return parseStoredJson(opened.token);
  }
  /** Core coordinator mirror only. Refresh credentials remain inside this adapter. */
  privateSessionAccess(): string | undefined { return this.#session?.access; }
  /** Owner-only acknowledgment. Refresh tokens never leave this adapter. */
  settleInvocation(commit: string, accept: boolean): void {
    if (!this.#commits.has(commit)) return;
    const state = this.app.database.transaction(() => {
      const next = this.settledState({ session: this.#session, commits: this.#commits }, commit, accept);
      this.writeState(next); return next;
    });
    this.#session = state.session; this.#commits = state.commits;
  }
  discardPendingInvocations(): void { for (const commit of [...this.#commits.keys()]) this.settleInvocation(commit, false); }
  private settledState(state: InvocationState, commit: string, accept: boolean): InvocationState {
    const pending = state.commits.get(commit)!;
    const next: InvocationState = { session: state.session, commits: new Map(state.commits) };
    if (!accept) {
      this.discard(pending);
      if (sameSession(next.session, pending.replacement)) next.session = pending.previous;
      // Also rebase same-family refresh undo when its predecessor was provisional.
      for (const [id, receipt] of next.commits) if (id !== commit && sameSession(receipt.previous, pending.replacement)) {
        next.commits.set(id, { ...receipt, previous: pending.previous,
          ...(receipt.undo && receipt.issue.context.deviceId === pending.issue.context.deviceId ? { undo: pending.undo } : {}) });
      }
    }
    next.commits.delete(commit); return next;
  }
  private discard(pending: PendingInvocation): void {
    const { issue, undo } = pending;
    const row = undo ? this.app.database.read('device_sessions', undo.device.id) : undefined;
    const restore = !!undo && row?.access_digest === digest(issue.credentials.access) && row.revoked_at == null &&
      this.app.auth.sessionIsActive(issue.context.deviceId, issue.context.userId, issue.context.tenantId);
    this.app.auth.discardIssue(issue);
    if (!restore || !undo) return;
    try {
      // This savepoint can reject an expired original family without undoing its discard.
      this.app.database.transaction(() => {
        const result = this.app.database.run('UPDATE device_sessions SET access_digest=?,access_expires_at=?,idle_expires_at=?,last_seen_at=?,revoked_at=NULL,revoke_reason=? WHERE id=? AND user_id=? AND access_digest=? AND revoke_reason=?',
          undo.device.accessDigest, undo.device.accessExpiresAt, undo.device.idleExpiresAt, undo.device.lastSeenAt, undo.device.revokeReason,
          undo.device.id, undo.device.userId, digest(issue.credentials.access), 'auth_superseded');
        if (Number(result.changes) !== 1 || !this.app.auth.sessionIsActive(issue.context.deviceId, issue.context.userId, issue.context.tenantId)) throw undoUnavailable;
        this.app.database.run('UPDATE device_refresh_tokens SET consumed_at=? WHERE digest=? AND session_id=?', undo.refresh.consumedAt, undo.refresh.digest, undo.device.id);
        this.app.database.run('DELETE FROM device_refresh_tokens WHERE digest=? AND session_id=? AND consumed_at IS NULL', digest(issue.credentials.refresh), undo.device.id);
      });
    } catch (error) { if (error !== undoUnavailable) throw error; }
  }
  private refreshUndo(): RefreshUndo | undefined {
    if (!this.#session) return;
    const token = this.app.database.read('device_refresh_tokens', digest(this.#session.refresh));
    const row = token ? this.app.database.read('device_sessions', String(token.session_id)) : undefined;
    if (!token || token.consumed_at != null || !row || row.revoked_at != null || row.access_digest !== digest(this.#session.access)) return;
    return { device: { id: String(row.id), userId: String(row.user_id), accessDigest: String(row.access_digest), accessExpiresAt: String(row.access_expires_at),
      idleExpiresAt: String(row.idle_expires_at), lastSeenAt: String(row.last_seen_at), revokeReason: String(row.revoke_reason) }, refresh: { digest: String(token.digest), consumedAt: null } };
  }
  private writeState(state: InvocationState): void {
    if (state.session) {
      const value = JSON.stringify(this.app.vault.encrypt({ token: JSON.stringify(state.session) }));
      this.app.database.run('INSERT INTO desktop_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', sessionKey, value);
    } else this.app.database.run('DELETE FROM desktop_meta WHERE key=?', sessionKey);
    if (state.commits.size) {
      const payload = { version: 1, current: state.session, pending: [...state.commits].map(([commit, receipt]) => ({ commit, ...receipt })) };
      const value = JSON.stringify(this.app.vault.encrypt({ token: JSON.stringify(payload) }));
      this.app.database.run('INSERT INTO desktop_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', receiptsKey, value);
    } else this.app.database.run('DELETE FROM desktop_meta WHERE key=?', receiptsKey);
  }
  private save(session?: PrivateSession): void {
    this.app.database.transaction(() => this.writeState({ session, commits: this.#commits }));
    this.#session = session;
  }
  private binding(options: IpcOptions, request: CoreRequest): PrivateBinding {
    if (!options || typeof options !== 'object' || Array.isArray(options) || Object.keys(options).some(key => !['tenantId', 'upload'].includes(key))) throw new AppError(400, 'invalid_ipc_options', '桌面请求选项不正确。');
    if (options.tenantId !== undefined && (typeof options.tenantId !== 'string' || !options.tenantId || options.tenantId.length > 128)) throw new AppError(400, 'invalid_tenant', '空间标识不正确。');
    const binding: PrivateBinding = { transport: 'ipc', ...this.#session, selectedTenant: options.tenantId };
    if (options.upload !== undefined) {
      const file = options.upload;
      const documentUpload = /^\/api\/v1\/knowledge-bases\/[^/?]+\/knowledge\/file$/.test(request.path);
      const chatUpload = /^\/api\/v1\/sessions\/([^/?]+)\/uploads$/.exec(request.path);
      if ((!documentUpload && !chatUpload) || request.method !== 'POST' ||
        !file || typeof file !== 'object' || Object.keys(file).some(key => !['name', 'bytes'].includes(key)) ||
        typeof file.name !== 'string' || !(file.bytes instanceof Uint8Array)) throw new AppError(400, 'invalid_ipc_upload', '桌面上传必须包含文件名和文件字节。');
      if (file.bytes.byteLength > 64 * 1024 * 1024) throw new AppError(413, 'upload_limit_exceeded', '上传文件超过限制。');
      const context = this.app.authorize(binding);
      this.app.auth.assertCan(context, documentUpload ? 'document.write' : 'write');
      if (chatUpload) {
        let sessionId: string;
        try { sessionId = decodeURIComponent(chatUpload[1]!); } catch { throw new AppError(400, 'invalid_path', '会话路径编码不正确。'); }
        this.app.chat.get(context, sessionId);
      }
      const body = request.body as JsonObject | undefined;
      const upload: DocumentUpload = { name: file.name, bytes: file.bytes };
      if (body?.tag_id !== undefined) {
        if (typeof body.tag_id !== 'string') throw new AppError(400, 'invalid_tag', '标签格式不正确。');
        upload.tag_id = body.tag_id;
      }
      if (body?.process_config !== undefined) {
        const config = body.process_config;
        if (!config || typeof config !== 'object' || Array.isArray(config)) throw new AppError(400, 'invalid_process_config', '解析配置必须是对象。');
        upload.process_config = config;
      }
      binding.upload = upload;
    }
    return binding;
  }
  private isStream(input: CoreRequest): boolean {
    const path = coreRequestUrl(input.path).pathname;
    return input.method === 'GET' && /^\/api\/v1\/sessions\/continue-stream\/[^/]+$/.test(path) || input.method === 'POST' && /^\/api\/v1\/(?:knowledge-chat|agent-chat)\/[^/]+$/.test(path) && (input.body as JsonObject | undefined)?.stream === true;
  }
  private async execute(input: unknown, options: IpcOptions, signal?: AbortSignal, fence?: IpcInvocationFence, retainCommit = false): Promise<IpcExecution> {
    const id = input && typeof input === 'object' && 'id' in input && typeof input.id === 'string' ? input.id : '';
    try {
      validateCoreRequest(input);
      if (Buffer.byteLength(JSON.stringify(input)) > 2 * 1024 * 1024) throw new AppError(413, 'body_too_large', '请求正文超过限制。');
      const binding = this.binding(options, input);
      const authOperation = isSessionChange(input);
      const epoch = authOperation ? ++this.#epoch : this.#epoch;
      const checkCurrent = () => {
        if (epoch !== this.#epoch || fence && !fence.isCurrent()) throw new AppError(409, 'auth_superseded', '登录状态已改变，请重新操作。');
      };
      if (authOperation) checkCurrent();
      const undo = retainCommit && input.method === 'POST' && coreRequestUrl(input.path).pathname === '/api/v1/auth/refresh' ? this.refreshUndo() : undefined;
      const result: IpcExecution = await this.app.dispatch(input, binding, signal);
      if (result.authChange) {
        const issue = result.authChange.issue;
        const previous = this.#session;
        let replacement: PrivateSession | undefined;
        try {
          if (signal?.aborted) throw new AppError(499, 'owner_cancelled', '核心请求已取消。');
          checkCurrent();
          if (result.authChange.clear) this.save();
          if (issue) {
            replacement = { access: issue.credentials.access, refresh: issue.credentials.refresh };
            if (retainCommit) {
              if (this.#commits.size >= 128) throw new AppError(429, 'owner_busy', '核心请求过多，请稍后重试。');
              const commit = randomUUID(), commits = new Map(this.#commits);
              commits.set(commit, { issue, previous, replacement, ...(undo ? { undo } : {}) });
              this.app.database.transaction(() => this.writeState({ session: replacement, commits }));
              this.#session = replacement; this.#commits = commits; result.commit = commit;
            } else this.save(replacement);
          }
          // An atomic epoch load and SQLite COMMIT are separate operations.
          // Recheck the save boundary before exposing any private session.
          checkCurrent();
        } catch (error) {
          if (result.commit) this.settleInvocation(result.commit, false);
          else {
            if (issue) this.app.database.transaction(() => this.discard({ issue, previous, replacement: replacement ?? { access: issue.credentials.access, refresh: issue.credentials.refresh }, ...(undo ? { undo } : {}) }));
            if (replacement && sameSession(this.#session, replacement)) this.save(previous);
          }
          throw error;
        }
      }
      return result;
    } catch (error) { return { response: errorResponse(id, error) }; }
  }
  private async invokeResult(input: unknown, options: IpcOptions, signal?: AbortSignal, fence?: IpcInvocationFence, retainCommit = false): Promise<{ response: IpcResponse; commit?: string }> {
    const id = input && typeof input === 'object' && 'id' in input && typeof input.id === 'string' ? input.id : '';
    try {
      validateCoreRequest(input);
      if (this.isStream(input)) throw new AppError(406, 'stream_transport_required', '此请求需要使用桌面流传输。');
      const result = await this.execute(input, options, signal, fence, retainCommit);
      return { response: { ...result.response, ...(result.binary ? { binary: { bytes: result.binary.bytes, name: result.binary.name, mimeType: result.binary.mimeType, sha256: result.binary.sha256 } } : {}) }, ...(result.commit ? { commit: result.commit } : {}) };
    } catch (error) { return { response: errorResponse(id, error) }; }
  }
  async invoke(input: unknown, options: IpcOptions = {}, signal?: AbortSignal, fence?: IpcInvocationFence): Promise<IpcResponse> { return (await this.invokeResult(input, options, signal, fence)).response; }
  /** Only the private owner protocol can settle this opaque receipt. */
  invokeForOwner(input: unknown, options: IpcOptions, signal: AbortSignal, fence: IpcInvocationFence): Promise<{ response: IpcResponse; commit?: string }> { return this.invokeResult(input, options, signal, fence, true); }
  /** Private main-process capability. Never called by arbitrary renderer invoke DTOs. */
  async nativeLangfuse(input: NativeLangfuseRequest | unknown, signal?: AbortSignal): Promise<NativeLangfuseResponse> {
    const id = input && typeof input === 'object' && 'id' in input && typeof input.id === 'string' ? input.id : '';
    try {
      const check = () => { if (signal?.aborted) throw new AppError(499, 'integration_cancelled', 'Langfuse 桌面请求已取消。'); };
      validateNativeLangfuseRequest(input); check();
      const ctx = this.app.authorize({ transport: 'ipc', ...this.#session, selectedTenant: input.tenantId });
      let data: JsonObject, plan: NativeLangfusePlan | undefined, cookies: SessionCookie[] | undefined;
      if (input.action === 'clear') data = this.app.integrations.clearNativeLangfuse(ctx);
      else {
        plan = input.action === 'prepare' ? this.app.integrations.prepareNativeLangfuse(ctx) : this.app.integrations.assertNativeLangfuse(ctx, input.ticket!);
        if (input.action === 'session') { const result = await this.app.integrations.nativeLangfuseSession(ctx, plan.ticket, input.existingCookies, { signal }); data = result.result; cookies = result.cookies; }
        else data = { state: plan.mode === 'manual' ? 'manual' : 'ready', open_url: plan.open_url, ...(plan.reason ? { manual_reason: plan.reason, message: '已打开 Langfuse，请在新页面手动登录。' } : {}) };
        check(); this.app.integrations.assertNativeLangfuse(ctx, plan.ticket);
      }
      return { response: { protocol: 1, id, status: 200, body: { success: true, data } }, ...(plan ? { plan } : {}), ...(cookies ? { cookies } : {}) };
    } catch (error) { return { response: errorResponse(id, error) }; }
  }
  /** Trusted native transport consumes these frames with acknowledgements/backpressure. */
  async openStream(input: unknown, options: IpcOptions = {}, signal?: AbortSignal): Promise<IpcStream> {
    const id = input && typeof input === 'object' && 'id' in input && typeof input.id === 'string' ? input.id : '';
    try {
      validateCoreRequest(input);
      if (!this.isStream(input)) throw new AppError(400, 'invalid_stream_request', '桌面流通道仅接受对话或继续流请求。');
      const result = await this.execute(input, options, signal);
      return { response: result.response, ...(result.stream ? { frames: result.stream.frames } : {}) };
    } catch (error) { return { response: errorResponse(id, error) }; }
  }
}
