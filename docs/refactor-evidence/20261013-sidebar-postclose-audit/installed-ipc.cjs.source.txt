'use strict';
const { isLocal, isDocumentCancel, canAdmit } = require('./runtime.cjs');
const { validatePublicRequest, invalidatesLangfuse } = require('./langfuse.cjs');

function assertSender(event, allowed, origin) {
  if (!allowed.has(event.sender) || !event.senderFrame || event.senderFrame !== event.sender.mainFrame || !isLocal(event.senderFrame.url, origin)) throw new Error('桌面请求来源不受信任。');
}
function json(value, seen = new Set()) {
  if (value === null || ['string', 'boolean'].includes(typeof value) || typeof value === 'number' && Number.isFinite(value)) return;
  if (!value || typeof value !== 'object' || !(Array.isArray(value) || Object.getPrototypeOf(value) === Object.prototype) || seen.has(value)) throw new Error('请求必须是有效 JSON。');
  seen.add(value); for (const child of Object.values(value)) json(child, seen); seen.delete(value);
}
function validateInvocation(request, options = {}) {
  if (!request || Object.getPrototypeOf(request) !== Object.prototype || Object.keys(request).some(key => !['protocol', 'id', 'method', 'path', 'body'].includes(key)) || request.protocol !== 1 ||
    typeof request.id !== 'string' || !request.id || request.id.length > 200 || /[\x00-\x1f\x7f]/.test(request.id) || !['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method) ||
    typeof request.path !== 'string' || !request.path.startsWith('/api/v1/') || request.path.length > 8192 || /[\x00-\x20\x7f\\#]/.test(request.path)) throw new Error('桌面请求协议不正确。');
  json(request); if (Buffer.byteLength(JSON.stringify(request)) > 2 * 1024 * 1024) throw new Error('桌面请求正文超过限制。');
  if (!options || Object.getPrototypeOf(options) !== Object.prototype || Object.keys(options).some(key => !['tenantId', 'upload'].includes(key))) throw new Error('桌面请求选项不正确。');
  if (options.tenantId !== undefined && (typeof options.tenantId !== 'string' || !options.tenantId || options.tenantId.length > 128)) throw new Error('空间标识不正确。');
  if (options.upload !== undefined) {
    const file = options.upload;
    if (request.method !== 'POST' || !/^\/api\/v1\/(?:knowledge-bases\/[^/?]+\/knowledge\/file|sessions\/[^/?]+\/uploads)$/.test(request.path) || !file || Object.getPrototypeOf(file) !== Object.prototype ||
      Object.keys(file).some(key => !['name', 'bytes'].includes(key)) || typeof file.name !== 'string' || !file.name || ['.', '..'].includes(file.name) || /[\x00-\x1f\x7f/\\]/.test(file.name) || Buffer.byteLength(file.name) > 255 ||
      !(file.bytes instanceof Uint8Array) || file.bytes.byteLength > 64 * 1024 * 1024) throw new Error('桌面上传文件名或内容不正确。');
  }
}

function installIpc(ipcMain, runtime, allowed, origin, langfuse) {
  const requests = new Map();
  const keyOf = (sender, id) => `${sender.id}:${id}`;
  const begin = (event, request, options, allowControl = false) => {
    assertSender(event, allowed, origin); validateInvocation(request, options);
    const key = keyOf(event.sender, request.id);
    const control = allowControl && isDocumentCancel(request);
    if (requests.has(key) || !canAdmit(requests, control)) throw new Error('桌面请求重复或过多。');
    const value = { controller: new AbortController(), sender: event.sender, id: request.id, control }; requests.set(key, value);
    return { key, value };
  };
  ipcMain.handle('marlin:invoke', async (event, request, options = {}) => {
    const { key, value } = begin(event, request, options, true);
    try { if (langfuse && invalidatesLangfuse(request)) await langfuse.invalidate(); return await runtime.invoke(request, options, value.controller.signal); }
    finally {
      if (value.control && runtime.waitForRequest) void runtime.waitForRequest(request.id).finally(() => requests.delete(key)).catch(() => {});
      else requests.delete(key);
    }
  });
  ipcMain.handle('marlin:langfuse', async (event, input) => {
    assertSender(event, allowed, origin); validatePublicRequest(input);
    if (!langfuse) throw new Error('Langfuse 桌面窗口不可用。');
    const key = keyOf(event.sender, input.id);
    if (requests.has(key) || !canAdmit(requests, false)) throw new Error('桌面请求重复或过多。');
    const value = { controller: new AbortController(), sender: event.sender, id: input.id }; requests.set(key, value);
    try { return await langfuse.handle(input, value.controller.signal); }
    finally { requests.delete(key); }
  });
  ipcMain.handle('marlin:stream-open', async (event, request, options = {}) => {
    const { key, value } = begin(event, request, options);
    try {
      const opened = await runtime.openStream(request, options, value.controller.signal);
      if (!opened.frames) { requests.delete(key); return opened.response; }
      const pump = async () => {
        try {
          let sequence = 0;
          for await (const frame of opened.frames) {
            if (value.controller.signal.aborted || event.sender.isDestroyed()) break;
            let abort;
            const acknowledged = new Promise((resolve, reject) => {
              const timer = setTimeout(() => reject(new Error('窗口未确认流数据，订阅已断开。')), 30000);
              value.ack = { sequence, resolve, timer };
              abort = () => reject(new Error('流订阅已取消。'));
              value.controller.signal.addEventListener('abort', abort, { once: true });
            });
            void acknowledged.catch(() => {});
            try { event.sender.send('marlin:stream-event', { id: request.id, type: 'frame', sequence, frame }); await acknowledged; }
            finally { value.controller.signal.removeEventListener('abort', abort); if (value.ack) clearTimeout(value.ack.timer); delete value.ack; }
            sequence++;
          }
          if (!event.sender.isDestroyed() && !value.controller.signal.aborted) event.sender.send('marlin:stream-event', { id: request.id, type: 'end' });
        } catch { if (!event.sender.isDestroyed() && !value.controller.signal.aborted) event.sender.send('marlin:stream-event', { id: request.id, type: 'error', message: '桌面流已断开，请重新连接会话。' }); }
        finally { value.controller.abort(); requests.delete(key); }
      };
      void pump(); return opened.response;
    } catch (error) { requests.delete(key); throw error; }
  });
  ipcMain.on('marlin:stream-ack', (event, id, sequence) => {
    try {
      assertSender(event, allowed, origin); const value = requests.get(keyOf(event.sender, id));
      if (!value?.ack || !Number.isSafeInteger(sequence) || value.ack.sequence !== sequence) return;
      clearTimeout(value.ack.timer); value.ack.resolve(); delete value.ack;
    } catch {}
  });
  ipcMain.on('marlin:cancel', (event, id) => {
    try { assertSender(event, allowed, origin); requests.get(keyOf(event.sender, id))?.controller.abort(); } catch {}
  });
  return { detach(sender) { for (const value of requests.values()) if (value.sender === sender) value.controller.abort(); }, close() { for (const value of requests.values()) value.controller.abort(); } };
}
module.exports = { assertSender, validateInvocation, installIpc };
