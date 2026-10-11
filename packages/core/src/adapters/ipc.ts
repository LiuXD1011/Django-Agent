import { CoreApplication, errorResponse, validateCoreRequest, type CoreFrame, type PrivateBinding, type PrivateDispatch } from '../application.js';
import type { CoreRequest, CoreResponse, JsonObject } from '../contracts.js';
import { AppError } from '../errors.js';
import type { DocumentUpload } from '../documents/workflow.js';
import { parseStoredJson } from '../storage/json.js';
import { validateNativeLangfuseRequest, type NativeLangfuseRequest, type NativeLangfusePlan, type SessionCookie } from '../integrations/langfuse-login.js';

interface PrivateSession { access: string; refresh: string; }
export interface IpcOptions { tenantId?: string; upload?: { name: string; bytes: Uint8Array }; }
export interface IpcResponse extends CoreResponse { binary?: { bytes: Uint8Array; name: string; mimeType: string; sha256: string }; }
export interface IpcStream { response: CoreResponse; frames?: AsyncIterable<CoreFrame> }
export interface NativeLangfuseResponse { response: CoreResponse; plan?: NativeLangfusePlan; cookies?: SessionCookie[] }
const sessionKey = 'ipc.session';

/** Transport adapter without Electron imports. Main/preload still check sender/frame. */
export class CoreIpcAdapter {
  #session?: PrivateSession;
  #epoch = 0;
  constructor(readonly app: CoreApplication) {
    const saved = app.database.get('SELECT value FROM desktop_meta WHERE key=?', sessionKey);
    if (!saved) return;
    try {
      const value = app.vault.decrypt(parseStoredJson(String(saved.value))) as JsonObject;
      if (typeof value.token !== 'string') throw new Error();
      const session = JSON.parse(value.token) as PrivateSession;
      if (typeof session.access !== 'string' || typeof session.refresh !== 'string' || !session.access || !session.refresh) throw new Error();
      this.#session = { access: session.access, refresh: session.refresh };
    } catch { throw new AppError(503, 'ipc_credentials_unavailable', '桌面登录凭据无法解密，请检查数据目录和密钥。'); }
  }
  private save(session?: PrivateSession): void {
    this.app.database.transaction(() => {
      if (session) {
        const value = JSON.stringify(this.app.vault.encrypt({ token: JSON.stringify(session) }));
        this.app.database.run('INSERT INTO desktop_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', sessionKey, value);
      } else this.app.database.run('DELETE FROM desktop_meta WHERE key=?', sessionKey);
    });
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
    const path = new URL(input.path, 'http://core.invalid').pathname;
    return input.method === 'GET' && /^\/api\/v1\/sessions\/continue-stream\/[^/]+$/.test(path) || input.method === 'POST' && /^\/api\/v1\/(?:knowledge-chat|agent-chat)\/[^/]+$/.test(path) && (input.body as JsonObject | undefined)?.stream === true;
  }
  private async execute(input: unknown, options: IpcOptions, signal?: AbortSignal): Promise<PrivateDispatch> {
    const id = input && typeof input === 'object' && 'id' in input && typeof input.id === 'string' ? input.id : '';
    try {
      validateCoreRequest(input);
      if (Buffer.byteLength(JSON.stringify(input)) > 2 * 1024 * 1024) throw new AppError(413, 'body_too_large', '请求正文超过限制。');
      const binding = this.binding(options, input);
      const authOperation = input.method === 'POST' && /^\/api\/v1\/auth\/(?:login|register|auto-setup|refresh|logout|logout-all|change-password)$/.test(input.path);
      const epoch = authOperation ? ++this.#epoch : this.#epoch;
      const result = await this.app.dispatch(input, binding, signal);
      if (result.authChange) {
        const issue = result.authChange.issue;
        if (epoch !== this.#epoch) {
          // A later logout or explicit login must defeat the earlier result. The
          // newly issued device itself is revoked, not just hidden in the UI.
          if (issue) { try { this.app.auth.logout(issue.context); } catch {} }
          throw new AppError(409, 'auth_superseded', '登录状态已改变，请重新操作。');
        }
        if (result.authChange.clear) this.save();
        if (issue) this.save({ access: issue.credentials.access, refresh: issue.credentials.refresh });
      }
      return result;
    } catch (error) { return { response: errorResponse(id, error) }; }
  }
  async invoke(input: unknown, options: IpcOptions = {}, signal?: AbortSignal): Promise<IpcResponse> {
    const id = input && typeof input === 'object' && 'id' in input && typeof input.id === 'string' ? input.id : '';
    try {
      validateCoreRequest(input);
      if (this.isStream(input)) throw new AppError(406, 'stream_transport_required', '此请求需要使用桌面流传输。');
      const result = await this.execute(input, options, signal);
      return { ...result.response, ...(result.binary ? { binary: { bytes: result.binary.bytes, name: result.binary.name, mimeType: result.binary.mimeType, sha256: result.binary.sha256 } } : {}) };
    } catch (error) { return errorResponse(id, error); }
  }
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
