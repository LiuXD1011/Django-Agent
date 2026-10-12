import { createHmac, randomBytes, randomUUID, timingSafeEqual } from 'node:crypto';
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import type { AddressInfo } from 'node:net';
import { once } from 'node:events';
import type { HttpMethod, Json, JsonObject } from '../contracts.js';
import { CoreApplication, errorResponse, success, type PrivateBinding } from '../application.js';
import type { DocumentUpload } from '../documents/workflow.js';
import { AppError } from '../errors.js';
import { parseStoredJson } from '../storage/json.js';
import type { CoreHttpTransport } from '../runtime/owner-contracts.js';

const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);
function cookies(request: IncomingMessage): Map<string, string> {
  const values = new Map<string, string>();
  for (const item of (request.headers.cookie ?? '').split(';')) {
    const index = item.indexOf('='); if (index <= 0) continue;
    const name = item.slice(0, index).trim();
    if (values.has(name)) throw new AppError(400, 'duplicate_cookie', '会话 Cookie 不明确。');
    values.set(name, item.slice(index + 1).trim());
  }
  return values;
}
function header(request: IncomingMessage, name: string): string { const value = request.headers[name]; return typeof value === 'string' ? value : ''; }
function json(response: ServerResponse, status: number, body: Json, cookieValues?: string[]): void {
  response.statusCode = status;
  response.setHeader('Content-Type', 'application/json; charset=utf-8');
  response.setHeader('Cache-Control', 'no-store');
  response.setHeader('X-Content-Type-Options', 'nosniff');
  if (cookieValues?.length) response.setHeader('Set-Cookie', cookieValues);
  response.end(JSON.stringify(body));
}
function safeOrigin(value: string): URL {
  let url: URL;
  try { url = new URL(value); } catch { throw new Error('Browser origin must be a loopback HTTP origin'); }
  if (url.protocol !== 'http:' || !['localhost', '127.0.0.1', '[::1]'].includes(url.hostname) || url.username || url.password || url.pathname !== '/' || url.search || url.hash) throw new Error('Browser origin must be a loopback HTTP origin');
  return url;
}
async function readBody(request: IncomingMessage, limit: number): Promise<Json | undefined> {
  const bytes = await readBytes(request, limit);
  if (!bytes.length) return;
  if (!/^application\/json(?:\s*;|$)/i.test(header(request, 'content-type')) || header(request, 'content-encoding')) throw new AppError(415, 'unsupported_body', '请求正文必须使用 JSON。');
  try { return parseStoredJson(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); }
  catch { throw new AppError(400, 'invalid_json', '请求正文不是有效 JSON。'); }
}
async function readBytes(request: IncomingMessage, limit: number): Promise<Buffer> {
  const length = Number(request.headers['content-length']);
  if (Number.isFinite(length) && length > limit) throw new AppError(413, 'body_too_large', '请求正文超过限制。');
  const parts: Buffer[] = []; let size = 0;
  for await (const part of request) {
    const bytes = Buffer.isBuffer(part) ? part : Buffer.from(part);
    size += bytes.length; if (size > limit) throw new AppError(413, 'body_too_large', '请求正文超过限制。');
    parts.push(bytes);
  }
  return Buffer.concat(parts, size);
}
async function readUpload(request: IncomingMessage, limit: number): Promise<DocumentUpload> {
  if (!/^multipart\/form-data\s*;/i.test(header(request, 'content-type')) || header(request, 'content-encoding')) throw new AppError(415, 'unsupported_upload', '上传必须使用表单文件。');
  // Materialize only a bounded body, after authentication/CSRF preflight. A global
  // upload cap below limits concurrent allocations; native formData never sees
  // an unbounded network stream or a renderer-supplied filesystem path.
  const bytes = await readBytes(request, limit + 256 * 1024);
  let form: FormData;
  try { form = await new Request('http://upload.invalid/', { method: 'POST', headers: { 'Content-Type': header(request, 'content-type') }, body: new Uint8Array(bytes).buffer }).formData(); }
  catch { throw new AppError(400, 'invalid_upload', '上传表单不完整或格式错误。'); }
  const fields = new Set<string>();
  for (const [name, value] of form) {
    if (!['file', 'tag_id', 'process_config'].includes(name) || fields.has(name)) throw new AppError(400, 'invalid_upload', '上传字段不明确。');
    fields.add(name);
    if (name !== 'file' && (typeof value !== 'string' || Buffer.byteLength(value) > 65536)) throw new AppError(400, 'invalid_upload', '上传配置超过限制或格式错误。');
  }
  const file = form.get('file');
  if (!file || typeof file === 'string') throw new AppError(400, 'file_required', '请选择要上传的文件。');
  if (file.size > limit) throw new AppError(413, 'upload_limit_exceeded', '上传文件超过限制。');
  let process_config: JsonObject | undefined;
  const raw = form.get('process_config');
  if (typeof raw === 'string') {
    let value: Json;
    try { value = parseStoredJson(raw); } catch { throw new AppError(400, 'invalid_process_config', '解析配置不是有效 JSON。'); }
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new AppError(400, 'invalid_process_config', '解析配置必须是对象。');
    process_config = value;
  }
  const tag = form.get('tag_id');
  return { name: file.name, bytes: new Uint8Array(await file.arrayBuffer()), ...(typeof tag === 'string' ? { tag_id: tag } : {}), ...(process_config ? { process_config } : {}) };
}

/** Loopback development/Orca bridge. Native installed applications use the IPC adapter. */
export function createCoreHttpServer(application: CoreApplication | CoreHttpTransport, options: { port?: number; host?: '127.0.0.1' | '::1'; browserOrigins?: string[]; maxBodyBytes?: number; maxUploadBytes?: number } = {}) {
  const host = options.host ?? '127.0.0.1'; const port = options.port ?? 8000; const maxBodyBytes = options.maxBodyBytes ?? 2 * 1024 * 1024;
  if (!['127.0.0.1', '::1'].includes(host) || !Number.isInteger(port) || port < 0 || port > 65535 || !Number.isSafeInteger(maxBodyBytes) || maxBodyBytes <= 0) throw new Error('Invalid HTTP adapter configuration');
  const maxUploadBytes = options.maxUploadBytes ?? 64 * 1024 * 1024;
  if (!Number.isSafeInteger(maxUploadBytes) || maxUploadBytes < 1 || maxUploadBytes > 64 * 1024 * 1024) throw new Error('Invalid upload limit');
  let activeUploads = 0;
  const origins = new Set((options.browserOrigins ?? []).map(value => safeOrigin(value).origin));
  const secretName = 'http.csrf-secret';
  const csrfKey = application instanceof CoreApplication ? application.database.transaction(() => {
    const saved = application.database.get('select value from desktop_meta where key=?', secretName);
    if (saved) {
      const value = application.vault.decrypt(parseStoredJson(String(saved.value)));
      if (!value || typeof value !== 'object' || Array.isArray(value) || typeof value.token !== 'string') throw new Error('Stored CSRF secret is invalid');
      return value.token;
    }
    const token = randomBytes(32).toString('base64url');
    application.database.run('insert into desktop_meta(key,value) values(?,?)', secretName, JSON.stringify(application.vault.encrypt({ token })));
    return token;
  }) : application.csrfKey;
  const sign = (value: string) => createHmac('sha256', csrfKey).update(value).digest('base64url');
  const validCsrf = (token: string) => {
    const parts = token.split('.'); if (parts.length !== 3) return false;
    const [timestamp, nonce, signature] = parts;
    if (!/^\d+$/.test(timestamp!) || !/^[a-zA-Z0-9_-]{32}$/.test(nonce!) || !/^[a-zA-Z0-9_-]{43}$/.test(signature!)) return false;
    const age = Date.now() - Number(timestamp);
    return age >= 0 && age < 86400000 && timingSafeEqual(Buffer.from(signature!), Buffer.from(sign(`${timestamp}.${nonce}`)));
  };
  const makeCsrf = () => { const value = `${Date.now()}.${randomBytes(24).toString('base64url')}`; return `${value}.${sign(value)}`; };
  let origin = ''; let started = false;
  const server = createServer({ requestTimeout: 30000, headersTimeout: 10000, maxHeaderSize: 16384 }, (request, response) => {
    const controller = new AbortController();
    const disconnect = () => { if (!response.writableEnded) controller.abort(); };
    response.once('close', disconnect);
    void (async () => {
      const requestId = header(request, 'x-request-id') || randomUUID();
      try {
        const requestHost = header(request, 'host');
        if (![...origins].some(value => new URL(value).host === requestHost)) throw new AppError(403, 'invalid_host', '请求主机不受信任。');
        const requestOrigin = header(request, 'origin');
        if (requestOrigin && !origins.has(requestOrigin)) throw new AppError(403, 'invalid_origin', '请求来源不受信任。');
        if (header(request, 'sec-fetch-site') === 'cross-site') throw new AppError(403, 'cross_site_request', '禁止跨站请求。');
        const method = request.method ?? 'GET'; const path = request.url ?? '';
        if (method === 'GET' && path === '/health') {
          if (!application.isAlive) throw new AppError(503, 'owner_failed', '核心服务已退出，请重新启动应用。');
          json(response, 200, { status: 'ok', runtime: 'typescript', service_id: application.serviceId }); return;
        }
        if (!['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) throw new AppError(405, 'method_not_allowed', '不支持该请求方法。');
        const values = cookies(request);
        const bearer = /^Bearer (\S+)$/i.exec(header(request, 'authorization'))?.[1];
        if (header(request, 'authorization') && !bearer) throw new AppError(401, 'invalid_authorization', '认证请求格式不正确。');
        if (UNSAFE.has(method)) {
          const csrfRequired = !bearer || Boolean(values.get('marlin_access') || values.get('marlin_refresh')) || /^\/api\/v1\/auth\/(?:login|register|auto-setup|refresh|logout)/.test(path);
          if (csrfRequired) {
            const referer = header(request, 'referer');
            let refererOrigin = ''; if (referer) { try { refererOrigin = new URL(referer).origin; } catch {} }
            if (!requestOrigin && !origins.has(refererOrigin)) throw new AppError(403, 'origin_required', '需要同源请求验证。');
            const token = values.get('csrftoken') ?? '';
            if (!token || token !== header(request, 'x-csrftoken') || !validCsrf(token)) throw new AppError(403, 'csrf_failed', '登录保护验证失败，请刷新页面。');
          }
        }
        if (method === 'GET' && path === '/api/v1/auth/csrf') {
          const prior = values.get('csrftoken') ?? ''; const token = validCsrf(prior) ? prior : makeCsrf();
          json(response, 200, success({ csrf_token: token }), [`csrftoken=${token}; Path=/; SameSite=Strict; Max-Age=86400`]); return;
        }
        const binding: PrivateBinding = { transport: 'http', access: values.get('marlin_access'), refresh: values.get('marlin_refresh'), bearer, origin: requestOrigin || undefined, embedToken: header(request, 'x-embed-token') || undefined, apiKey: header(request, 'x-api-key') || undefined, selectedTenant: header(request, 'x-tenant-id') || undefined,
          localSession: { requestOrigin: requestOrigin || `http://${requestHost}`, remoteAddress: request.socket.remoteAddress ?? '', existingCookies: Object.fromEntries(values) },
        };
        let body: Json | undefined;
        const upload = method === 'POST' ? /^\/api\/v1\/knowledge-bases\/([^/?]+)\/knowledge\/file$/.exec(path) : null;
        const chatUpload = method === 'POST' ? /^\/api\/v1\/sessions\/([^/?]+)\/uploads$/.exec(path) : null;
        if (upload || chatUpload) {
          let resourceId: string;
          try { resourceId = decodeURIComponent((upload ?? chatUpload)![1]!); } catch { throw new AppError(400, 'invalid_path', '上传路径编码不正确。'); }
          if (application instanceof CoreApplication) {
            const context = application.authorize(binding);
            application.auth.assertCan(context, upload ? 'document.write' : 'write');
            if (upload) application.knowledge.knowledgeBases.get(context, resourceId);
            else application.chat.get(context, resourceId);
          } else await application.preflightUpload(binding, upload ? 'document' : 'chat', resourceId, controller.signal);
          if (activeUploads >= 3) throw new AppError(429, 'uploads_busy', '已有多个文件正在上传，请稍后重试。');
          activeUploads++;
          try { binding.upload = await readUpload(request, maxUploadBytes); }
          finally { activeUploads--; }
        } else body = await readBody(request, maxBodyBytes);
        const result = await application.dispatch({ protocol: 1, id: requestId, method: method as HttpMethod, path, ...(body === undefined ? {} : { body }) }, binding, controller.signal);
        if (result.stream) {
          response.statusCode = result.response.status;
          response.setHeader('Content-Type', 'text/event-stream; charset=utf-8');
          response.setHeader('Cache-Control', 'no-store'); response.setHeader('X-Content-Type-Options', 'nosniff');
          response.setHeader('X-Accel-Buffering', 'no'); response.flushHeaders();
          try {
            for await (const frame of result.stream.frames) {
              if (controller.signal.aborted || response.destroyed) break;
              if (!/^[a-zA-Z0-9_/-]{1,100}$/.test(frame.event)) throw new AppError(500, 'invalid_stream_event', '流事件格式不正确。');
              const data = JSON.stringify(frame.data);
              if (Buffer.byteLength(data) > maxBodyBytes) throw new AppError(500, 'stream_event_too_large', '流事件超过大小限制。');
              if (!response.write(`event: ${frame.event}\ndata: ${data}\n\n`)) await once(response, 'drain', { signal: controller.signal });
            }
          } catch (error) {
            if (!controller.signal.aborted && !response.destroyed) response.write(`event: error\ndata: ${JSON.stringify(errorResponse(requestId, error).body)}\n\n`);
          } finally { if (!response.destroyed) response.end(); }
          return;
        }
        if (result.binary) {
          const file = result.binary;
          response.statusCode = result.response.status;
          response.setHeader('Content-Type', file.mimeType);
          response.setHeader('Content-Length', file.bytes.byteLength);
          response.setHeader('Content-Disposition', `inline; filename*=UTF-8''${encodeURIComponent(file.name)}`);
          response.setHeader('Cache-Control', 'no-store');
          response.setHeader('X-Content-Type-Options', 'nosniff');
          response.end(file.bytes); return;
        }
        const changed: string[] = [];
        for (const cookie of result.cookies ?? []) {
          if (!/^(?:__Secure-)?next-auth\.session-token(?:\.\d+)?$/.test(cookie.name) || /[\s;,\r\n]/.test(cookie.value)) throw new AppError(500, 'invalid_session_cookie', '本地集成返回了无效会话。');
          changed.push(`${cookie.name}=${cookie.value}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${cookie.maxAge}${cookie.secure ? '; Secure' : ''}`);
        }
        if (result.authChange?.clear) for (const name of ['marlin_access', 'marlin_refresh']) changed.push(`${name}=; Path=/api/v1/; HttpOnly; SameSite=Strict; Max-Age=0`);
        if (result.authChange?.issue) {
          const c = result.authChange.issue.credentials;
          changed.push(`marlin_access=${c.access}; Path=/api/v1/; HttpOnly; SameSite=Strict; Expires=${new Date(c.accessExpiresAt).toUTCString()}`);
          changed.push(`marlin_refresh=${c.refresh}; Path=/api/v1/; HttpOnly; SameSite=Strict; Expires=${new Date(c.refreshExpiresAt).toUTCString()}`);
        }
        json(response, result.response.status, result.response.body, changed);
      } catch (error) { const result = errorResponse(requestId, error); if (!response.writableEnded && !response.destroyed) json(response, result.status, result.body); }
      finally { response.removeListener('close', disconnect); }
    })();
  });
  return {
    server,
    async listen(): Promise<{ origin: string }> {
      if (started) return { origin };
      await new Promise<void>((resolve, reject) => { server.once('error', reject); server.listen(port, host, () => { server.removeListener('error', reject); resolve(); }); });
      const address = server.address() as AddressInfo;
      origin = `http://${host === '::1' ? '[::1]' : host}:${address.port}`;
      origins.add(origin); origins.add(`http://localhost:${address.port}`); started = true;
      return { origin };
    },
    async close(): Promise<void> {
      if (!started) return;
      await new Promise<void>((resolve, reject) => { server.close(error => error ? reject(error) : resolve()); server.closeAllConnections(); });
      started = false;
    },
  };
}
