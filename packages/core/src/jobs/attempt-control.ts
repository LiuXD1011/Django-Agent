import { JobError } from './common.js';

export interface DocumentAttemptIdentity {
  jobId: string;
  attempt: number;
  ownerToken: string;
  tenantId: string;
  jobUserId: string;
  knowledgeId: string;
  knowledgeBaseId: string;
  previousAttempt: number;
}
/** A queued preflight may acknowledge only the immediately following claim. */
export type DocumentQueuedIdentity = Omit<DocumentAttemptIdentity, 'attempt' | 'ownerToken'>;
export interface AttemptControlBridge {
  register(identity: DocumentAttemptIdentity, shared: SharedArrayBuffer): Promise<void>;
  unregister(identity: DocumentAttemptIdentity, shared: SharedArrayBuffer): void;
}
export enum AttemptState {
  ACTIVE = 0,
  CANCEL_REQUESTED = 1,
  COMMITTING_LOCAL = 2,
  LOCAL_CANCEL_AFTER_COMMIT = 3,
  COMMITTING_FINAL = 4,
  DONE = 5,
  CANCELLED_DURABLE = 6,
  FAILED = 7,
  INVALID = 8,
}
const mask = 255n, maximumOrdinal = (1n << 56n) - 1n;
type CommitObserver = (event: { final: boolean; state: AttemptState; ordinal: bigint }) => void;
const commitObservers = new WeakMap<SharedArrayBuffer, CommitObserver>();
const checkpointObservers = new WeakMap<SharedArrayBuffer, () => void>();
function observe<T extends Function>(observers: WeakMap<SharedArrayBuffer, T>, shared: SharedArrayBuffer, observer: T): () => void {
  view(shared);
  if (observers.has(shared) || observer.constructor.name === 'AsyncFunction') throw new JobError(400, 'invalid_observer', 'Register one synchronous trusted observer');
  observers.set(shared, observer);
  return () => { if (observers.get(shared) === observer) observers.delete(shared); };
}
/** Node test capability only, with no configuration or serialized request entry. */
export function observeAttemptCommits(shared: SharedArrayBuffer, observer: CommitObserver): () => void { return observe(commitObservers, shared, observer); }
export function observeAttemptCheckpoints(shared: SharedArrayBuffer, observer: () => void): () => void { return observe(checkpointObservers, shared, observer); }
function view(shared: SharedArrayBuffer): BigUint64Array {
  if (!(shared instanceof SharedArrayBuffer) || shared.byteLength !== 8) throw new JobError(400, 'attempt_control_invalid', 'Attempt control must be an eight-byte shared buffer');
  return new BigUint64Array(shared);
}
export function createAttemptControl(): SharedArrayBuffer { return new SharedArrayBuffer(8); }
export function readAttemptControl(shared: SharedArrayBuffer): { state: AttemptState; ordinal: bigint } {
  const word = Atomics.load(view(shared), 0), state = Number(word & mask);
  return { state: state <= AttemptState.INVALID ? state : AttemptState.INVALID, ordinal: word >> 8n };
}
export interface CancelDisposition {
  disposition: 'requested' | 'after_local_commit' | 'finalizing' | 'terminal' | 'invalid';
  state: AttemptState;
  ordinal: bigint;
}
/** Trusted coordinator only: this is a request, never a durable cancellation ACK. */
export function requestCancel(shared: SharedArrayBuffer): CancelDisposition {
  const control = view(shared);
  for (;;) {
    const old = Atomics.load(control, 0), ordinal = old >> 8n, state = Number(old & mask);
    let next: AttemptState, disposition: CancelDisposition['disposition'];
    if (state === AttemptState.ACTIVE) { next = AttemptState.CANCEL_REQUESTED; disposition = 'requested'; }
    else if (state === AttemptState.COMMITTING_LOCAL) { next = AttemptState.LOCAL_CANCEL_AFTER_COMMIT; disposition = 'after_local_commit'; }
    else if (state === AttemptState.CANCEL_REQUESTED) return { disposition: 'requested', state, ordinal };
    else if (state === AttemptState.LOCAL_CANCEL_AFTER_COMMIT) return { disposition: 'after_local_commit', state, ordinal };
    else if (state === AttemptState.COMMITTING_FINAL) return { disposition: 'finalizing', state, ordinal };
    else if (state >= AttemptState.DONE && state <= AttemptState.FAILED) return { disposition: 'terminal', state, ordinal };
    else return { disposition: 'invalid', state: AttemptState.INVALID, ordinal };
    if (Atomics.compareExchange(control, 0, old, ordinal << 8n | BigInt(next)) === old) return { disposition, state: next, ordinal };
  }
}

/** Owner-only implementation; commit gates may not span an await. */
export class AttemptControl {
  constructor(readonly shared = createAttemptControl()) { view(shared); }
  checkpoint(): void {
    const { state } = readAttemptControl(this.shared);
    if (state === AttemptState.CANCEL_REQUESTED || state === AttemptState.LOCAL_CANCEL_AFTER_COMMIT) throw new JobError(409, 'job_cancelled', 'Job cancelled');
    if (state !== AttemptState.ACTIVE) throw new JobError(409, 'ownership_lost', 'Attempt cannot publish');
    const result: unknown = checkpointObservers.get(this.shared)?.();
    if (result && typeof (result as { then?: unknown }).then === 'function') { void Promise.resolve(result).catch(() => undefined); throw new JobError(400, 'invalid_observer', 'Observer must be synchronous'); }
    // An observer may pause while the coordinator changes the atomic state.
    if (readAttemptControl(this.shared).state !== AttemptState.ACTIVE) {
      if (readAttemptControl(this.shared).state === AttemptState.CANCEL_REQUESTED) throw new JobError(409, 'job_cancelled', 'Job cancelled');
      throw new JobError(409, 'ownership_lost', 'Attempt cannot publish');
    }
  }
  beginCommit(final: boolean): void {
    this.checkpoint();
    const control = view(this.shared), old = Atomics.load(control, 0);
    if (old >> 8n === maximumOrdinal) throw new JobError(409, 'attempt_control_exhausted', 'Attempt commit ordinal exhausted');
    const next = old & ~mask | BigInt(final ? AttemptState.COMMITTING_FINAL : AttemptState.COMMITTING_LOCAL);
    if (Number(old & mask) !== AttemptState.ACTIVE || Atomics.compareExchange(control, 0, old, next) !== old) { this.checkpoint(); throw new JobError(409, 'ownership_lost', 'Attempt commit gate changed'); }
    const result: unknown = commitObservers.get(this.shared)?.({ final, ...readAttemptControl(this.shared) });
    if (result && typeof (result as { then?: unknown }).then === 'function') { void Promise.resolve(result).catch(() => undefined); throw new JobError(400, 'invalid_observer', 'Observer must be synchronous'); }
  }
  /** Called only after the outer driver COMMIT has returned successfully. */
  committed(final: boolean): void {
    const control = view(this.shared);
    for (;;) {
      const old = Atomics.load(control, 0), state = Number(old & mask), ordinal = old >> 8n;
      if (final ? state !== AttemptState.COMMITTING_FINAL : state !== AttemptState.COMMITTING_LOCAL && state !== AttemptState.LOCAL_CANCEL_AFTER_COMMIT) throw new JobError(409, 'attempt_control_invalid', 'Attempt commit gate was lost');
      const nextState = final ? AttemptState.DONE : state === AttemptState.LOCAL_CANCEL_AFTER_COMMIT ? AttemptState.CANCEL_REQUESTED : AttemptState.ACTIVE;
      const next = (ordinal + 1n) << 8n | BigInt(nextState);
      if (Atomics.compareExchange(control, 0, old, next) === old) return;
    }
  }
  rolledBack(): void {
    const control = view(this.shared);
    for (;;) {
      const old = Atomics.load(control, 0), state = Number(old & mask);
      if (state !== AttemptState.COMMITTING_LOCAL && state !== AttemptState.LOCAL_CANCEL_AFTER_COMMIT && state !== AttemptState.COMMITTING_FINAL) return;
      const next = old & ~mask | BigInt(state === AttemptState.LOCAL_CANCEL_AFTER_COMMIT ? AttemptState.CANCEL_REQUESTED : AttemptState.ACTIVE);
      if (Atomics.compareExchange(control, 0, old, next) === old) return;
    }
  }
  terminal(status: 'completed' | 'cancelled' | 'failed' | 'interrupted' | 'queued'): void {
    const control = view(this.shared), target = status === 'completed' ? AttemptState.DONE : status === 'cancelled' ? AttemptState.CANCELLED_DURABLE : AttemptState.FAILED;
    for (;;) { const old = Atomics.load(control, 0); if (Atomics.compareExchange(control, 0, old, old & ~mask | BigInt(target)) === old) return; }
  }
  invalidate(): void {
    const control = view(this.shared);
    for (;;) { const old = Atomics.load(control, 0); if (Atomics.compareExchange(control, 0, old, old & ~mask | BigInt(AttemptState.INVALID)) === old) return; }
  }
}

const trustedPublications = new WeakSet<Function>();
/** Capability for internal publication that owns the outer transaction. Never serialized. */
export function trustedAttemptPublication<T extends Function>(publication: T): T { trustedPublications.add(publication); return publication; }
export function isTrustedAttemptPublication(publication: Function): boolean { return trustedPublications.has(publication); }
