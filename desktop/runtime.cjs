'use strict';
const path = require('node:path');
const { fork } = require('node:child_process');
const { randomUUID } = require('node:crypto');
const { RuntimeLifetime, loadWindowsJob } = require('./owned-runtime.cjs');
function isDocumentCancel(request) {
  if (request?.method !== 'POST' || typeof request.path !== 'string') return false;
  try { const url = new URL(request.path, 'http://core.invalid'); return url.origin === 'http://core.invalid' && /^\/api\/v1\/knowledge\/[^/]+\/cancel-parse$/.test(url.pathname); }
  catch { return false; }
}
function canAdmit(records, control) {
  let count = 0; for (const item of records.values()) if (!!item.control === control) count++;
  return count < (control ? 8 : 64);
}

const byteLimit = 64 * 1024 * 1024;
function wireInvalid() { throw new Error('桌面私有进程协议不正确。'); }
function wireRecord(value, fields) {
  if (!value || typeof value !== 'object' || Object.getPrototypeOf(value) !== Object.prototype || Object.keys(value).some(key => !fields.includes(key))) wireInvalid();
  return value;
}
function wireJson(value, seen = new Set(), depth = 0) {
  if (value === null || ['string', 'boolean'].includes(typeof value) || typeof value === 'number' && Number.isFinite(value)) return;
  if (!value || typeof value !== 'object' || !(Array.isArray(value) || Object.getPrototypeOf(value) === Object.prototype) || seen.has(value) || depth > 256) wireInvalid();
  seen.add(value); for (const child of Object.values(value)) wireJson(child, seen, depth + 1); seen.delete(value);
}
function wireId(value) { if (typeof value !== 'string' || !value || value.length > 200 || /[\x00-\x1f\x7f]/.test(value)) wireInvalid(); }
const sessionCookieName = /^(?:__Secure-)?next-auth\.session-token(?:\.\d+)?$/;
function cookieValues(input) {
  wireRecord(input, Object.keys(input || {}));
  if (Object.keys(input).length > 20 || Buffer.byteLength(JSON.stringify(input)) > 32768 || Object.entries(input).some(([name, value]) => !sessionCookieName.test(name) || typeof value !== 'string' || /[\s;,]/.test(value))) wireInvalid();
  return input;
}
function langfuseRequest(input) {
  const value = wireRecord(input, ['id', 'action', 'ticket', 'existingCookies', 'tenantId']); wireId(value.id);
  if (!['prepare', 'session', 'validate', 'clear'].includes(value.action)) wireInvalid();
  if (value.tenantId !== undefined && (typeof value.tenantId !== 'string' || !value.tenantId || value.tenantId.length > 128)) wireInvalid();
  if (['session', 'validate'].includes(value.action) ? typeof value.ticket !== 'string' || !/^[a-f0-9-]{36}$/.test(value.ticket) : value.ticket !== undefined) wireInvalid();
  if (value.existingCookies !== undefined) { if (value.action !== 'session') wireInvalid(); cookieValues(value.existingCookies); }
  return value;
}
function langfusePlan(input) {
  const value = wireRecord(input, ['ticket', 'ownerScope', 'origin', 'projectPath', 'open_url', 'mode', 'reason']);
  if (typeof value.ticket !== 'string' || !/^[a-f0-9-]{36}$/.test(value.ticket) || typeof value.ownerScope !== 'string' || !/^[a-f0-9]{64}$/.test(value.ownerScope) || !['automatic', 'manual'].includes(value.mode) || !['', 'auto_login_disabled', 'credentials_missing', 'local_host_required'].includes(value.reason)) wireInvalid();
  if (typeof value.origin !== 'string' || typeof value.projectPath !== 'string' || typeof value.open_url !== 'string' || value.open_url.length > 8192 || /[\s\\]/.test(value.open_url)) wireInvalid();
  let url; try { url = new URL(value.open_url); } catch { wireInvalid(); }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash || url.origin !== value.origin || url.pathname !== value.projectPath + 'traces' || !/\/project\/[^/]+\/$/.test(value.projectPath)) wireInvalid();
  return value;
}
function langfuseCookies(input) {
  if (!Array.isArray(input) || input.length > 20 || Buffer.byteLength(JSON.stringify(input)) > 32768) wireInvalid();
  const names = new Set();
  for (const cookie of input) {
    wireRecord(cookie, ['name', 'value', 'secure', 'maxAge']);
    if (typeof cookie.name !== 'string' || !sessionCookieName.test(cookie.name) || names.has(cookie.name) || typeof cookie.value !== 'string' || /[\s;,]/.test(cookie.value) || typeof cookie.secure !== 'boolean' || cookie.name.startsWith('__Secure-') && !cookie.secure || !Number.isSafeInteger(cookie.maxAge) || cookie.maxAge < 0 || cookie.maxAge > 3600) wireInvalid();
    names.add(cookie.name);
  }
  return input;
}
function encodeBytes(bytes) {
  if (!(bytes instanceof Uint8Array)) wireInvalid();
  if (bytes.byteLength > byteLimit) throw new Error('桌面传输文件超过限制。');
  return { encoding: 'base64', size_bytes: bytes.byteLength, data: Buffer.from(bytes.buffer, bytes.byteOffset, bytes.byteLength).toString('base64') };
}
function decodeBytes(input) {
  const value = wireRecord(input, ['encoding', 'size_bytes', 'data']);
  if (value.encoding !== 'base64' || !Number.isSafeInteger(value.size_bytes) || value.size_bytes < 0 || typeof value.data !== 'string') wireInvalid();
  if (value.size_bytes > byteLimit || value.data.length > 4 * Math.ceil(byteLimit / 3)) throw new Error('桌面传输文件超过限制。');
  if (value.data.length !== 4 * Math.ceil(value.size_bytes / 3) || !/^[A-Za-z0-9+/]*={0,2}$/.test(value.data)) wireInvalid();
  const bytes = Buffer.from(value.data, 'base64');
  if (bytes.length !== value.size_bytes || bytes.toString('base64') !== value.data) wireInvalid();
  return new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength);
}
function encodeInput(input) {
  const message = wireRecord(input, ['type', 'id', 'request', 'options', 'sequence']);
  if (message.type === 'shutdown') { wireRecord(message, ['type']); return message; }
  wireId(message.id);
  if (message.type === 'cancel') { wireRecord(message, ['type', 'id']); return message; }
  if (message.type === 'ack') { wireRecord(message, ['type', 'id', 'sequence']); if (!Number.isSafeInteger(message.sequence) || message.sequence < 0) wireInvalid(); return message; }
  if (message.type === 'langfuse') { wireRecord(message, ['type', 'id', 'request']); langfuseRequest(message.request); if (message.request.id !== message.id) wireInvalid(); return message; }
  if (!['invoke', 'stream'].includes(message.type)) wireInvalid();
  wireRecord(message, ['type', 'id', 'request', 'options']);
  const request = wireRecord(message.request, ['protocol', 'id', 'method', 'path', 'body']);
  if (request.protocol !== 1 || request.id !== message.id || !['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method) || typeof request.path !== 'string' || !request.path.startsWith('/api/v1/') || request.path.length > 8192 || /[\x00-\x20\x7f\\#]/.test(request.path)) wireInvalid();
  wireJson(request); if (Buffer.byteLength(JSON.stringify(request)) > 2 * 1024 * 1024) throw new Error('桌面请求正文超过限制。');
  const options = wireRecord(message.options === undefined ? {} : message.options, ['tenantId', 'upload']), encoded = {};
  if (options.tenantId !== undefined) { if (typeof options.tenantId !== 'string' || !options.tenantId || options.tenantId.length > 128) wireInvalid(); encoded.tenantId = options.tenantId; }
  if (options.upload !== undefined) {
    const file = wireRecord(options.upload, ['name', 'bytes']);
    if (typeof file.name !== 'string' || !file.name || ['.', '..'].includes(file.name) || /[\x00-\x1f\x7f/\\]/.test(file.name) || Buffer.byteLength(file.name) > 255) wireInvalid();
    encoded.upload = { name: file.name, bytes: encodeBytes(file.bytes) };
  }
  return { ...message, options: encoded };
}
function decodeResponse(input, id, binaryAllowed = false) {
  const response = wireRecord(input, binaryAllowed ? ['protocol', 'id', 'status', 'body', 'binary'] : ['protocol', 'id', 'status', 'body']);
  if (response.protocol !== 1 || response.id !== id || !Number.isSafeInteger(response.status) || response.status < 100 || response.status > 599) wireInvalid();
  wireJson(response.body);
  if (response.binary === undefined) return response;
  const file = wireRecord(response.binary, ['bytes', 'name', 'mimeType', 'sha256']);
  if (typeof file.name !== 'string' || typeof file.mimeType !== 'string' || typeof file.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(file.sha256)) wireInvalid();
  return { ...response, binary: { ...file, bytes: decodeBytes(file.bytes) } };
}
function decodeMessage(input) {
  if (!input || typeof input !== 'object' || typeof input.type !== 'string') wireInvalid();
  if (input.type === 'ready') {
    wireRecord(input, ['type', 'protocol', 'runtime', 'http_listener', 'service_id', 'version']);
    if (input.protocol !== 1 || input.runtime !== 'typescript' || input.http_listener !== false || typeof input.service_id !== 'string' || !input.service_id || typeof input.version !== 'string') wireInvalid();
  } else if (input.type === 'stopped') { wireRecord(input, ['type', 'protocol']); if (input.protocol !== 1) wireInvalid(); }
  else if (input.type === 'startup-error') { wireRecord(input, ['type', 'protocol', 'response']); if (input.protocol !== 1) wireInvalid(); return { ...input, response: decodeResponse(input.response, 'startup') }; }
  else {
    wireId(input.id);
    if (input.type === 'langfuse-response') {
      wireRecord(input, ['type', 'id', 'response', 'plan', 'cookies']);
      const response = decodeResponse(input.response, input.id);
      if (response.status >= 400 && (input.plan !== undefined || input.cookies !== undefined)) wireInvalid();
      if (input.plan !== undefined) langfusePlan(input.plan);
      if (input.cookies !== undefined) { if (!input.plan) wireInvalid(); langfuseCookies(input.cookies); }
      return { ...input, response };
    }
    if (['response', 'stream-open', 'stream-error'].includes(input.type)) { wireRecord(input, ['type', 'id', 'response']); return { ...input, response: decodeResponse(input.response, input.id, input.type === 'response') }; }
    if (input.type === 'stream-end') wireRecord(input, ['type', 'id']);
    else if (input.type === 'stream-frame') {
      wireRecord(input, ['type', 'id', 'sequence', 'frame']); wireRecord(input.frame, ['event', 'data']);
      if (!Number.isSafeInteger(input.sequence) || input.sequence < 0 || typeof input.frame.event !== 'string' || !/^[a-zA-Z0-9_/-]{1,100}$/.test(input.frame.event)) wireInvalid();
      wireJson(input.frame.data); if (Buffer.byteLength(JSON.stringify(input.frame.data)) > 2 * 1024 * 1024) wireInvalid();
    } else wireInvalid();
  }
  return input;
}

// Never inherit developer database URLs, Python paths, API keys or service flags.
function runtimeEnv(source = process.env) {
  const names = new Set(['systemroot', 'windir', 'systemdrive', 'comspec',
    'pathext', 'temp', 'tmp', 'userprofile', 'localappdata', 'appdata']);
  return Object.fromEntries(Object.entries(source).filter(([key]) => names.has(key.toLowerCase())));
}
function isLocal(url, origin) {
  try { const u = new URL(url); return u.origin === origin && !u.username && !u.password; }
  catch { return false; }
}
function isExternal(url) {
  try { const u = new URL(url); return ['https:', 'http:'].includes(u.protocol) && !u.username && !u.password; }
  catch { return false; }
}
class Runtime {
  constructor(root, dataDir, onFailure = () => {}, options = {}) {
    Object.assign(this, { root, dataDir, onFailure, options, child: null, stopping: false, requests: new Map() });
  }
  start() {
    if (this.lifetime && !this.lifetime.closed) return Promise.reject(new Error('上一代桌面核心尚未完整退出。'));
    if (this.child && this.child.exitCode === null && this.child.signalCode === null) return Promise.reject(new Error('桌面核心已经启动。'));
    this.stopping = false;
    this.stopPromise = null;
    const coreDirectory = this.options.coreDirectory || path.join(this.root, 'core');
    const nodeExecutable = this.options.nodeExecutable || path.join(this.root, 'node', process.platform === 'win32' ? 'node.exe' : 'bin/node');
    const entryPoint = this.options.entryPoint || path.join(coreDirectory, 'dist/tools/desktop-process.js');
    const nativePath = this.options.nativeModulePath || path.join(this.root, 'owned-runtime', 'runtime-job.node');
    const generation = randomUUID(), windows = process.platform === 'win32';
    let native;
    try { if (windows) native = loadWindowsJob(this.root, nativePath); }
    catch { return Promise.reject(new Error('本地进程管理组件缺失或损坏，请重新安装。')); }
    const args = ['--data-root', this.dataDir];
    if (this.options.parser !== false) args.push('--python', path.join(this.root, 'python', process.platform === 'win32' ? 'python.exe' : 'bin/python3'),
      '--parser-worker', path.join(this.root, 'workers/document/worker.py'),
      '--ragas-worker', path.join(this.root, 'workers/evaluation/worker.py'));
    return new Promise((resolve, reject) => {
      let settled = false;
      const finish = (error, ready) => {
        if (settled) return; settled = true; clearTimeout(timer);
        if (error) {
          reject(error);
          if (this.lifetime?.generation === generation) void this.stop().catch(() => {});
        } else resolve(ready);
      };
      const timer = setTimeout(() => finish(new Error('本地核心启动超时，请重试。')), 30000);
      let child;
      try {
        child = fork(windows ? path.join(__dirname, 'runtime-bootstrap.cjs') : entryPoint,
          windows ? [entryPoint, generation, nativePath, ...args] : args,
          { cwd: coreDirectory, execPath: nodeExecutable,
          execArgv: this.options.execArgv || [], env: { ...runtimeEnv(), PYTHONUTF8: '1',
            TIKTOKEN_CACHE_DIR: path.join(this.root, 'tokenizer-cache') },
          serialization: 'json', windowsHide: true, stdio: ['ignore', 'pipe', 'pipe', 'ipc'] });
      } catch { finish(new Error('本地运行环境启动失败，请重新安装。')); return; }
      this.child = child;
      const lifetime = this.lifetime = new RuntimeLifetime(child, generation);
      lifetime.authorized = !windows;
      child.stdout.on('data', () => {}); child.stderr.on('data', () => {});
      child.once('error', () => finish(new Error('本地运行环境启动失败，请重新安装。')));
      child.once('exit', code => {
        if (this.lifetime !== lifetime) return;
        const error = new Error(`本地核心已退出（代码 ${code}），用户数据已保留。`);
        this.failRequests(error);
        if (!settled) finish(error);
        else if (!this.stopping) { this.onFailure(error.message); void this.stop().catch(() => {}); }
      });
      child.on('message', input => {
        if (this.lifetime !== lifetime || this.stopping) return;
        let message;
        try {
          if (windows && input?.type === 'owned-bootstrap') {
            wireRecord(input, ['type', 'protocol', 'generation', 'pid', 'createdAt']);
            if (lifetime.authorized || input.protocol !== 1 || input.generation !== generation || input.pid !== child.pid
              || typeof input.createdAt !== 'string' || !/^[1-9][0-9]{0,19}$/.test(input.createdAt)) wireInvalid();
            lifetime.job = native.bindRoot(child.pid, input.createdAt, nodeExecutable);
            lifetime.authorized = true;
            child.send({ type: 'owned-start', protocol: 1, generation }, error => { if (error) finish(new Error('桌面核心授权失败。')); });
            return;
          }
          if (!lifetime.authorized) wireInvalid();
          message = decodeMessage(input);
        }
        catch { const error = new Error('桌面核心启动身份或协议校验失败。'); this.failRequests(error); if (!settled) finish(error); else { this.onFailure(error.message); void this.stop().catch(() => {}); } return; }
        if (message.type === 'ready') {
          if (message.protocol !== 1 || message.runtime !== 'typescript' || message.http_listener !== false || typeof message.service_id !== 'string') finish(new Error('桌面核心协议校验失败。'));
          else finish(null, message);
        } else if (message.type === 'startup-error') finish(new Error(message.response?.body?.message || '桌面核心初始化失败。'));
        else this.receive(message);
      });
    });
  }
  send(message) {
    return new Promise((resolve, reject) => {
      if (!this.child?.connected) return reject(new Error('桌面核心连接已经结束。'));
      let encoded; try { encoded = encodeInput(message); } catch (error) { reject(error); return; }
      this.child.send(encoded, error => error ? reject(error) : resolve());
    });
  }
  failRequests(error) {
    for (const pending of this.requests.values()) {
      clearTimeout(pending.timer); pending.cleanup?.(); pending.reject(error);
      pending.settle?.();
      pending.error = error; pending.wake?.();
    }
    this.requests.clear();
  }
  receive(message) {
    const pending = this.requests.get(message.id); if (!pending) return;
    if (message.type === 'langfuse-response' && pending.kind === 'langfuse') {
      this.requests.delete(message.id); clearTimeout(pending.timer); pending.cleanup?.();
      const { type, id, ...result } = message; pending.resolve(result);
    } else if (message.type === 'response' && pending.kind === 'invoke') {
      this.requests.delete(message.id); clearTimeout(pending.timer); pending.cleanup?.(); pending.settle?.(); pending.resolve(message.response);
    } else if (message.type === 'stream-open' && pending.kind === 'stream') {
      clearTimeout(pending.timer); pending.opened = true; pending.resolve({ response: message.response,
        ...(message.response.status < 400 ? { frames: this.frames(message.id, pending) } : {}) });
    } else if (message.type === 'stream-frame' && pending.kind === 'stream') {
      if (pending.frame || message.sequence !== pending.sequence || !message.frame || typeof message.frame.event !== 'string') {
        pending.error = new Error('桌面流事件顺序不正确。'); void this.send({ type: 'cancel', id: message.id }).catch(() => {});
      } else pending.frame = message;
      pending.wake?.();
    } else if (message.type === 'stream-end' || message.type === 'stream-error') {
      pending.ended = true; clearTimeout(pending.timer); pending.cleanup?.();
      if (message.type === 'stream-error') { pending.error = new Error(message.response?.body?.message || '桌面流请求失败。'); if (!pending.opened) pending.reject(pending.error); }
      this.requests.delete(message.id); pending.wake?.();
    }
  }
  async *frames(id, pending) {
    try {
      while (true) {
        if (pending.error) throw pending.error;
        if (pending.frame) {
          const message = pending.frame; pending.frame = null;
          yield message.frame;
          pending.sequence++;
          await this.send({ type: 'ack', id, sequence: message.sequence });
        } else if (pending.ended) return;
        else await new Promise(resolve => { pending.wake = resolve; });
      }
    } finally { pending.cleanup?.(); clearTimeout(pending.timer); this.requests.delete(id); if (!pending.ended) await this.send({ type: 'cancel', id }).catch(() => {}); }
  }
  request(kind, request, options = {}, signal) {
    if (this.stopping || !this.child?.connected) return Promise.reject(new Error('桌面核心不可用。'));
    if (!request || typeof request.id !== 'string' || this.requests.has(request.id)) return Promise.reject(new Error('桌面请求标识无效或重复。'));
    const control = kind === 'invoke' && isDocumentCancel(request);
    if (!canAdmit(this.requests, control)) return Promise.reject(new Error('桌面请求过多，请稍后重试。'));
    if (signal?.aborted) return Promise.reject(new Error('桌面请求已取消。'));
    return new Promise((resolve, reject) => {
      const pending = { kind, resolve, reject, sequence: 0, opened: false, ended: false, frame: null, control };
      if (control) pending.settled = new Promise(settle => { pending.settle = settle; });
      const abort = () => {
        const error = new Error('桌面请求已取消。'); pending.error = error; pending.ended = true;
        clearTimeout(pending.timer); pending.cleanup?.(); if (!control) this.requests.delete(request.id); reject(error); pending.wake?.();
        void this.send({ type: 'cancel', id: request.id }).catch(() => {});
      };
      pending.cleanup = () => signal?.removeEventListener('abort', abort);
      pending.timer = setTimeout(abort, kind === 'stream' ? 30000 : 120000);
      signal?.addEventListener('abort', abort, { once: true });
      this.requests.set(request.id, pending);
      void this.send({ type: kind, id: request.id, request, ...(kind === 'langfuse' ? {} : { options }) }).catch(error => {
        clearTimeout(pending.timer); pending.cleanup(); this.requests.delete(request.id); pending.settle?.(); reject(error);
      });
    });
  }
  invoke(request, options, signal) { return this.request('invoke', request, options, signal); }
  waitForRequest(id) { return this.requests.get(id)?.settled || Promise.resolve(); }
  openStream(request, options, signal) { return this.request('stream', request, options, signal); }
  langfuse(request, signal) { return this.request('langfuse', request, undefined, signal); }
  stop() {
    if (this.stopPromise) return this.stopPromise;
    this.stopping = true; this.failRequests(new Error('应用正在退出。'));
    const lifetime = this.lifetime;
    if (!lifetime) return this.stopPromise = Promise.resolve();
    return this.stopPromise = lifetime.stop(callback => {
      if (!lifetime.child.connected) { callback(new Error('桌面核心连接已经结束。')); return; }
      lifetime.child.send(encodeInput({ type: 'shutdown' }), callback);
    });
  }
}
module.exports = { Runtime, runtimeEnv, isLocal, isExternal, isDocumentCancel, canAdmit };
