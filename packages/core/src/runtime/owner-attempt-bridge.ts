import { randomUUID } from 'node:crypto';
import type { MessagePort } from 'node:worker_threads';
import { AppError } from '../errors.js';
import type { AttemptControlBridge } from '../jobs/attempt-control.js';
import type { OwnerInput, OwnerOutput } from './owner-contracts.js';

/** Construct before Application: startup recovery can claim before owner-ready. */
export function createOwnerAttemptBridge(port: MessagePort, generation: string): AttemptControlBridge {
  const pending = new Map<string, { resolve(): void; reject(error: unknown): void; timer: NodeJS.Timeout }>();
  port.on('message', (message: OwnerInput) => {
    if (message?.protocol !== 1 || message.type !== 'attempt-registration-result' || message.generation !== generation) return;
    const registration = pending.get(message.id); if (!registration) return;
    clearTimeout(registration.timer); pending.delete(message.id);
    if (message.error) registration.reject(new AppError(message.error.status, message.error.code, message.error.message));
    else registration.resolve();
  });
  port.once('close', () => { for (const item of pending.values()) { clearTimeout(item.timer); item.reject(new AppError(503, 'owner_closed', '核心服务已关闭。')); } pending.clear(); });
  return {
    register(identity, shared) {
      if (pending.size >= 64) return Promise.reject(new AppError(429, 'document_cancel_busy', '取消控制注册过多。'));
      return new Promise((resolve, reject) => {
        const discard = () => { try { port.postMessage({ protocol: 1, type: 'attempt-unregister', generation, identity } satisfies OwnerOutput); } catch {} };
        const id = randomUUID(), timer = setTimeout(() => { pending.delete(id); discard(); reject(new AppError(503, 'attempt_registration_timeout', '文档取消控制注册超时。')); }, 10000);
        pending.set(id, { resolve, reject: error => { discard(); reject(error); }, timer });
        try { port.postMessage({ protocol: 1, type: 'attempt-register', id, generation, identity, shared } satisfies OwnerOutput); }
        catch (error) { clearTimeout(timer); pending.delete(id); discard(); reject(error); }
      });
    },
    unregister(identity) { port.postMessage({ protocol: 1, type: 'attempt-unregister', generation, identity } satisfies OwnerOutput); },
  };
}
