import { randomBytes } from 'node:crypto';
import type { MessagePort } from 'node:worker_threads';
import { errorResponse, success, type CoreApplication, type CoreFrame } from '../application.js';
import type { CoreIpcAdapter } from '../adapters/ipc.js';
import { AppError } from '../errors.js';
import { parseStoredJson } from '../storage/json.js';
import type { OwnerFailure, OwnerInput, OwnerOutput, OwnerSessionState, OwnerValue } from './owner-contracts.js';

interface Lifetime { controller: AbortController; ack?: { sequence: number; resolve(): void; reject(error: unknown): void; timer: NodeJS.Timeout } }
/** The same private message pump serves the formal worker and controlled integration fixtures. */
export function runCoreOwner(port: MessagePort, application: CoreApplication, ipc: CoreIpcAdapter, authority: BigUint64Array, generation: string): void {
  const send = (message: OwnerOutput) => port.postMessage(message);
  const session = (): OwnerSessionState => ({ epoch: Atomics.load(authority, 0).toString(), access: ipc.privateSessionAccess() });
  const current = (message: Extract<OwnerInput, { type: 'call' }>) => message.epoch === Atomics.load(authority, 0).toString();
  const safeError = (error: unknown): OwnerFailure => {
    const result = errorResponse('', error), body = result.body as { error: { code: string; message: string } };
    return { status: result.status, code: body.error.code, message: body.error.message };
  };
  const active = new Map<string, Lifetime>(), queue: Extract<OwnerInput, { type: 'call' }>[] = [], executions = new Set<Promise<void>>();
  const cancellationControls = new Set<string>();
  let closing: Promise<void> | undefined;
  let csrfKey: string | undefined;
  const csrf = () => csrfKey ??= application.database.transaction(() => {
    const name = 'http.csrf-secret', row = application.database.get('select value from desktop_meta where key=?', name);
    if (row) {
      const value = application.vault.decrypt(parseStoredJson(String(row.value)));
      if (!value || typeof value !== 'object' || Array.isArray(value) || typeof value.token !== 'string') throw new Error('Stored CSRF secret is invalid');
      return value.token;
    }
    const token = randomBytes(32).toString('base64url');
    application.database.run('insert into desktop_meta(key,value) values(?,?)', name, JSON.stringify(application.vault.encrypt({ token })));
    return token;
  });
  const pump = () => {
    while (!closing && active.size < 64 && queue.length) {
      const message = queue.shift()!, lifetime: Lifetime = { controller: new AbortController() };
      active.set(message.id, lifetime);
      const pending = execute(message, lifetime); executions.add(pending);
      void pending.finally(() => { executions.delete(pending); active.delete(message.id); pump(); }).catch(() => {});
    }
  };
  async function frame(id: string, sequence: number, value: CoreFrame, lifetime: Lifetime): Promise<void> {
    const signal = lifetime.controller.signal;
    signal.throwIfAborted();
    if (!/^[a-zA-Z0-9_/-]{1,100}$/.test(value.event) || Buffer.byteLength(JSON.stringify(value.data)) > 2 * 1024 * 1024) throw new AppError(500, 'invalid_stream_frame', '流事件超过限制或格式不正确。');
    let abort!: () => void;
    const acknowledged = new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => reject(new AppError(408, 'stream_ack_timeout', '窗口未确认流数据，订阅已断开。')), 30000);
      lifetime.ack = { sequence, resolve, reject, timer };
      abort = () => reject(new AppError(409, 'stream_closed', '流订阅已结束。'));
      signal.addEventListener('abort', abort, { once: true });
    });
    void acknowledged.catch(() => {});
    try { send({ protocol: 1, type: 'frame', id, sequence, frame: value }); await acknowledged; }
    finally { signal.removeEventListener('abort', abort); if (lifetime.ack) clearTimeout(lifetime.ack.timer); delete lifetime.ack; }
  }
  async function execute(message: Extract<OwnerInput, { type: 'call' }>, lifetime: Lifetime): Promise<void> {
    let ipcCommit: string | undefined;
    try {
      const call = message.call, signal = lifetime.controller.signal;
      signal.throwIfAborted();
      let value: OwnerValue, frames: AsyncIterable<CoreFrame> | undefined;
      if (call.operation === 'dispatch') {
        const result = await application.dispatch(call.request, call.binding, signal);
        if (result.authChange?.issue && !current(message)) {
          application.auth.discardIssue(result.authChange.issue);
          throw new AppError(409, 'auth_superseded', '登录状态已改变，请重新操作。');
        }
        const { stream, ...rest } = result; value = rest; frames = stream?.frames;
      } else if (call.operation === 'invoke') {
        const result = await ipc.invokeForOwner(call.input, call.options, signal, { isCurrent: () => current(message) });
        value = result.response; ipcCommit = result.commit;
      }
      else if (call.operation === 'stream') {
        const result = await ipc.openStream(call.input, call.options, signal);
        value = { response: result.response }; frames = result.frames;
      } else if (call.operation === 'langfuse') value = await ipc.nativeLangfuse(call.input, signal);
      else if (call.operation === 'http') value = { csrfKey: csrf() };
      else if (call.operation === 'discard-issue') { application.auth.discardIssue(call.issue); value = null; }
      else if (call.operation === 'settle-ipc') { ipc.settleInvocation(call.commit, call.accept); value = null; }
      else if (call.operation === 'upload-preflight') {
        if (!['document', 'chat'].includes(call.kind) || typeof call.resourceId !== 'string' || !call.resourceId) throw new AppError(400, 'invalid_upload_preflight', '上传目标不正确。');
        const context = application.authorize(call.binding);
        application.auth.assertCan(context, call.kind === 'document' ? 'document.write' : 'write');
        if (call.kind === 'document') application.knowledge.knowledgeBases.get(context, call.resourceId);
        else application.chat.get(context, call.resourceId);
        value = null;
      } else if (call.operation === 'log') { application.settings.startup.log(call.level, call.event); value = null; }
      else throw new AppError(400, 'invalid_owner_call', '核心私有请求不正确。');
      signal.throwIfAborted();
      send({ protocol: 1, type: 'response', id: message.id, value, streaming: !!frames, session: session(), ...(ipcCommit ? { ipcCommit } : {}) });
      if (frames) {
        try { let sequence = 0; for await (const item of frames) await frame(message.id, sequence++, item, lifetime); }
        finally { lifetime.controller.abort(); }
        send({ protocol: 1, type: 'end', id: message.id });
      }
    } catch (error) {
      if (ipcCommit) ipc.settleInvocation(ipcCommit, false);
      send({ protocol: 1, type: 'error', id: message.id, error: safeError(error), session: session() });
    }
  }
  const close = () => closing ??= (async () => {
    let error: OwnerFailure | undefined;
    for (const lifetime of active.values()) lifetime.controller.abort();
    try { ipc.discardPendingInvocations(); } catch (reason) { error = safeError(reason); }
    for (const message of queue.splice(0)) send({ protocol: 1, type: 'error', id: message.id, error: safeError(new AppError(503, 'owner_closed', '核心服务已关闭。')), session: session() });
    try { await application.close(); }
    catch (reason) { error = safeError(reason); }
    await Promise.allSettled([...executions]);
    send({ protocol: 1, type: 'closed', ...(error ? { error } : {}) }); port.close();
  })();
  port.on('message', (message: OwnerInput) => {
    if (!message || message.protocol !== 1) return;
    if (message.type === 'close') { void close(); return; }
    if (message.type === 'cancel-attempt') {
      if (closing || cancellationControls.size >= 64 || cancellationControls.has(message.id)) {
        send({ protocol: 1, type: 'cancel-response', id: message.id, response: errorResponse(message.requestId, new AppError(closing ? 503 : 429, closing ? 'owner_closed' : 'document_cancel_busy', '核心服务暂时无法接受取消请求。')) }); return;
      }
      cancellationControls.add(message.id);
      const pending = (async () => {
        try {
          if (!application.documents) throw new AppError(503, 'parser_not_configured', '文档解析器尚未配置，请检查应用运行环境。');
          const result = await application.documents.cancelAttempt(message.identity);
          send({ protocol: 1, type: 'cancel-response', id: message.id, response: { protocol: 1, id: message.requestId, status: 200, body: success(result) } });
        } catch (error) { send({ protocol: 1, type: 'cancel-response', id: message.id, response: errorResponse(message.requestId, error) }); }
      })();
      executions.add(pending);
      void pending.finally(() => { executions.delete(pending); cancellationControls.delete(message.id); }).catch(() => {});
      return;
    }
    if (message.type === 'abort') {
      const index = queue.findIndex(item => item.id === message.id);
      if (index !== -1) { queue.splice(index, 1); send({ protocol: 1, type: 'error', id: message.id, error: safeError(new AppError(499, 'owner_cancelled', '核心请求已取消。')), session: session() }); }
      active.get(message.id)?.controller.abort(); return;
    }
    if (message.type === 'ack') {
      const lifetime = active.get(message.id), ack = lifetime?.ack;
      if (ack?.sequence === message.sequence) { clearTimeout(ack.timer); ack.resolve(); if (lifetime) delete lifetime.ack; }
      return;
    }
    if (message.type !== 'call') return;
    if (closing || active.has(message.id) || queue.some(item => item.id === message.id) || active.size >= 64 && queue.length >= 64) {
      send({ protocol: 1, type: 'error', id: message.id, error: safeError(new AppError(closing ? 503 : 429, closing ? 'owner_closed' : 'owner_busy', '核心服务暂时无法接受请求。')), session: session() }); return;
    }
    queue.push(message); pump();
  });
  port.once('close', () => { void close(); });
  send({ protocol: 1, type: 'ready', serviceId: application.serviceId, bootstrap: {
    databasePath: application.database.path, dataRoot: application.database.dataRoot, generation,
    parserEnabled: !!application.documents, startupActive: application.settings.startup.active,
    environmentOverrides: [...application.settings.startup.environmentOverrides], session: session(),
  } });
}
