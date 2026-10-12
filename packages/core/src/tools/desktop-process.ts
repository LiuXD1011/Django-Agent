import { parseArgs } from 'node:util';
import { resolve } from 'node:path';
import { errorResponse, type CoreFrame } from '../application.js';
import type { IpcResponse } from '../adapters/ipc.js';
import { AppError } from '../errors.js';
import { CoreOwner } from '../runtime/owner-client.js';
import { decodeDesktopInput, encodeDesktopResponse, type DesktopInput } from './desktop-wire.js';
import { isDocumentCancelRequest } from '../runtime/document-cancel-preflight.js';

interface PendingAck { sequence: number; resolve(): void; reject(error: Error): void; timer: NodeJS.Timeout }
interface RequestLifetime { controller: AbortController; control: boolean; ack?: PendingAck }
function send(value: Record<string, unknown>): Promise<void> {
  if (value.response !== undefined) value = { ...value, response: encodeDesktopResponse(value.response as IpcResponse) };
  return new Promise((resolveSent, reject) => {
    if (!process.connected || !process.send) { reject(new AppError(503, 'desktop_disconnected', '桌面窗口连接已结束。')); return; }
    process.send(value, error => error ? reject(error) : resolveSent());
  });
}
async function main(): Promise<void> {
  if (!process.send) throw new AppError(400, 'private_ipc_required', '桌面核心必须由应用通过私有进程连接启动。');
  const { values } = parseArgs({ options: { 'data-root': { type: 'string' }, python: { type: 'string' }, 'parser-worker': { type: 'string' }, 'ragas-worker': { type: 'string' } }, strict: true });
  if (!values['data-root'] || Boolean(values.python) !== Boolean(values['parser-worker']) || values['ragas-worker'] && !values.python) throw new AppError(400, 'invalid_desktop_runtime', '桌面数据目录或解析器配置不完整。');
  const parser = values.python ? { pythonExecutable: resolve(values.python), workerPath: resolve(values['parser-worker']!) } : undefined;
  const evaluation = values['ragas-worker'] ? { ragas: { pythonExecutable: resolve(values.python!), workerPath: resolve(values['ragas-worker']) } } : undefined;
  const ipc = await CoreOwner.start({ dataRoot: resolve(values['data-root']), allowAutoSetup: true, parser, evaluation });
  const requests = new Map<string, RequestLifetime>(), executions = new Set<Promise<void>>();
  let closing: Promise<void> | undefined;
  const finish = () => closing ??= (async () => {
    for (const request of requests.values()) request.controller.abort();
    try { await ipc.close(); }
    finally {
      await Promise.allSettled([...executions]);
      await send({ type: 'stopped', protocol: 1 }).catch(() => {});
      if (process.connected) process.disconnect();
    }
  })();
  function ack(id: string, sequence: number) {
    const current = requests.get(id)?.ack;
    if (!current || current.sequence !== sequence) return;
    clearTimeout(current.timer); current.resolve();
    const request = requests.get(id); if (request) delete request.ack;
  }
  async function frame(id: string, sequence: number, value: CoreFrame, lifetime: RequestLifetime): Promise<void> {
    if (lifetime.controller.signal.aborted) throw new AppError(409, 'stream_closed', '流订阅已结束。');
    if (!/^[a-zA-Z0-9_/-]{1,100}$/.test(value.event) || Buffer.byteLength(JSON.stringify(value.data)) > 2 * 1024 * 1024) throw new AppError(500, 'invalid_stream_frame', '流事件超过限制或格式不正确。');
    let abort!: () => void;
    const acknowledged = new Promise<void>((resolveAck, reject) => {
      const timer = setTimeout(() => reject(new AppError(408, 'stream_ack_timeout', '窗口未确认流数据，订阅已断开。')), 30000);
      lifetime.ack = { sequence, resolve: resolveAck, reject, timer };
      abort = () => reject(new AppError(409, 'stream_closed', '流订阅已结束。'));
      lifetime.controller.signal.addEventListener('abort', abort, { once: true });
    });
    // Attach rejection immediately, including while send waits for IPC capacity.
    void acknowledged.catch(() => {});
    try { await send({ type: 'stream-frame', id, sequence, frame: value }); await acknowledged; }
    finally { lifetime.controller.signal.removeEventListener('abort', abort); if (lifetime.ack) clearTimeout(lifetime.ack.timer); delete lifetime.ack; }
  }
  async function execute(message: Extract<DesktopInput, { type: 'invoke' | 'stream' | 'langfuse' }>): Promise<void> {
    const id = message.id;
    let lifetime: RequestLifetime | undefined;
    try {
      if (closing) throw new AppError(503, 'app_closing', '应用正在退出。');
      if (message.request.id !== id || requests.has(id)) throw new AppError(409, 'duplicate_desktop_request', '桌面请求标识不明确。');
      const control = message.type === 'invoke' && isDocumentCancelRequest(message.request);
      const admitted = [...requests.values()].filter(item => item.control === control).length;
      if (admitted >= (control ? 8 : 64)) throw new AppError(429, 'desktop_busy', '桌面请求过多，请稍后重试。');
      lifetime = { controller: new AbortController(), control }; requests.set(id, lifetime);
      if (message.type === 'langfuse') {
        const result = await ipc.nativeLangfuse(message.request, lifetime.controller.signal);
        await send({ type: 'langfuse-response', id, ...result });
      } else if (message.type === 'invoke') {
        const response = await ipc.invoke(message.request, message.options, lifetime.controller.signal);
        await send({ type: 'response', id, response });
      } else if (message.type === 'stream') {
        const result = await ipc.openStream(message.request, message.options, lifetime.controller.signal);
        await send({ type: 'stream-open', id, response: result.response });
        if (result.frames) { let sequence = 0; for await (const item of result.frames) await frame(id, sequence++, item, lifetime); }
        await send({ type: 'stream-end', id });
      } else throw new AppError(400, 'invalid_desktop_request', '桌面请求类型不正确。');
    } catch (error) {
      // A caller disconnect can reject invoke before the actual task settles.
      // Keep the JSON fork/Electron control slot until the owner's durable ACK
      // or terminal owner failure, rather than sending a misleading early reply.
      if (lifetime?.control) await ipc.waitForCancellation(id);
      const response = errorResponse(id, error);
      if (message.type === 'stream') await send({ type: 'stream-error', id, response }).catch(() => {});
      else await send({ type: message.type === 'langfuse' ? 'langfuse-response' : 'response', id, response }).catch(() => {});
    } finally { if (lifetime?.ack) clearTimeout(lifetime.ack.timer); if (lifetime) requests.delete(id); }
  }
  process.on('message', input => {
    let message: DesktopInput;
    try { message = decodeDesktopInput(input); }
    catch (error) {
      const raw = input as Record<string, unknown> | null;
      if (raw && typeof raw.id === 'string' && raw.id.length <= 200 && !/[\x00-\x1f\x7f]/.test(raw.id) && ['invoke', 'stream', 'langfuse'].includes(String(raw.type))) {
        void send({ type: raw.type === 'stream' ? 'stream-error' : raw.type === 'langfuse' ? 'langfuse-response' : 'response', id: raw.id, response: errorResponse(raw.id, error) }).catch(() => {});
      }
      return;
    }
    if (message.type === 'shutdown') { void finish().catch(() => { process.exitCode = 1; if (process.connected) process.disconnect(); }); return; }
    if (message.type === 'cancel') { requests.get(message.id)?.controller.abort(); return; }
    if (message.type === 'ack') { ack(message.id, message.sequence); return; }
    const work = execute(message); executions.add(work); void work.finally(() => executions.delete(work)).catch(() => {});
  });
  process.once('disconnect', () => { void finish().catch(() => { process.exitCode = 1; }); });
  process.once('SIGINT', () => { void finish().catch(() => { process.exitCode = 1; }); });
  process.once('SIGTERM', () => { void finish().catch(() => { process.exitCode = 1; }); });
  await send({ type: 'ready', protocol: 1, runtime: 'typescript', http_listener: false, service_id: ipc.serviceId, version: '0.7.0' });
}
main().catch(async error => { await send({ type: 'startup-error', protocol: 1, response: errorResponse('startup', error) }).catch(() => {}); process.exitCode = 1; if (process.connected) process.disconnect(); });
