import { AppError } from '../errors.js';
import { AttemptState, readAttemptControl, requestCancel, type DocumentAttemptIdentity, type DocumentQueuedIdentity } from '../jobs/attempt-control.js';
import type { CancelTarget } from './document-cancel-preflight.js';

const stale = () => new AppError(409, 'document_attempt_superseded', '文档处理状态已改变，请刷新后重试。');
const busy = () => new AppError(429, 'document_cancel_busy', '取消请求过多，请稍后重试。');
const fields = ['jobId', 'tenantId', 'jobUserId', 'knowledgeId', 'knowledgeBaseId'] as const;
function sameDocument(a: DocumentQueuedIdentity, b: DocumentQueuedIdentity): boolean { return fields.every(key => a[key] === b[key]); }
export function validAttemptIdentity(value: unknown): value is DocumentAttemptIdentity {
  if (!value || typeof value !== 'object') return false;
  const row = value as DocumentAttemptIdentity;
  return fields.every(key => typeof row[key] === 'string' && !!row[key] && row[key].length <= 200)
    && typeof row.ownerToken === 'string' && !!row.ownerToken && row.ownerToken.length <= 200
    && Number.isSafeInteger(row.attempt) && row.attempt > 0 && row.previousAttempt === row.attempt - 1;
}
interface Registered { identity: DocumentAttemptIdentity; shared: SharedArrayBuffer }
interface Intent { target: CancelTarget; waiters: number }
const key = (target: CancelTarget) => JSON.stringify([target.identity.jobId, target.identity.previousAttempt, 'ownerToken' in target.identity ? target.identity.ownerToken : '']);

/** Coordinator-only bounded registry. Nothing in it crosses the renderer/fork JSON wire. */
export class AttemptRegistry {
  readonly #attempts = new Map<string, Registered>();
  readonly #intents = new Map<string, Intent>();
  #closed = false;
  register(identity: DocumentAttemptIdentity, shared: SharedArrayBuffer): void {
    if (this.#closed) throw new AppError(503, 'owner_closed', '核心服务已关闭。');
    if (!validAttemptIdentity(identity) || !(shared instanceof SharedArrayBuffer) || shared.byteLength !== 8 || readAttemptControl(shared).state !== AttemptState.ACTIVE) throw stale();
    if (this.#attempts.has(identity.jobId) || this.#attempts.size >= 64) throw busy();
    this.#attempts.set(identity.jobId, { identity: { ...identity }, shared });
    // A previously authorized queued intent covers exactly its next claim.
    for (const intent of this.#intents.values()) {
      if (intent.target.state === 'queued' && sameDocument(intent.target.identity, identity) && intent.target.identity.previousAttempt === identity.previousAttempt) requestCancel(shared);
    }
  }
  unregister(identity: DocumentAttemptIdentity): void {
    const entry = this.#attempts.get(identity.jobId);
    if (entry && sameDocument(entry.identity, identity) && entry.identity.attempt === identity.attempt && entry.identity.ownerToken === identity.ownerToken) this.#attempts.delete(identity.jobId);
  }
  request(target: CancelTarget): () => void {
    if (this.#closed) throw new AppError(503, 'owner_closed', '核心服务已关闭。');
    const intentKey = key(target), intent = this.#intents.get(intentKey);
    if (intent ? intent.waiters >= 8 : this.#intents.size >= 8) throw busy();
    const entry = this.#attempts.get(target.identity.jobId);
    if (target.state === 'running' && (!entry || !sameDocument(entry.identity, target.identity) || entry.identity.attempt !== target.identity.attempt || entry.identity.ownerToken !== target.identity.ownerToken)) throw stale();
    if (target.state === 'queued' && entry && (!sameDocument(entry.identity, target.identity) || entry.identity.previousAttempt !== target.identity.previousAttempt)) throw stale();
    if (target.state !== 'terminal' && entry && requestCancel(entry.shared).disposition === 'invalid') throw stale();
    if (intent) intent.waiters++; else this.#intents.set(intentKey, { target, waiters: 1 });
    let released = false;
    return () => { if (released) return; released = true; const current = this.#intents.get(intentKey); if (current && --current.waiters === 0) this.#intents.delete(intentKey); };
  }
  close(invalidate = true): void {
    this.#closed = true;
    for (const entry of invalidate ? this.#attempts.values() : []) {
      const view = new BigUint64Array(entry.shared);
      for (;;) { const old = Atomics.load(view, 0); if (Atomics.compareExchange(view, 0, old, old & ~255n | BigInt(AttemptState.INVALID)) === old) break; }
    }
    this.#attempts.clear(); this.#intents.clear();
  }
}
