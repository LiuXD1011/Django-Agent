import { createHash, randomUUID } from 'node:crypto';
import type { Json, JsonObject } from '../contracts.js';
import type { CoreDatabase, Row } from '../storage/database.js';
import { decoded, freezeJson, JobError, notFound, object, type JobScope } from './common.js';
import { AttemptControl, requestCancel, type AttemptControlBridge, type DocumentAttemptIdentity, type DocumentQueuedIdentity } from './attempt-control.js';
import { OwnedProcessRegistry, type OwnedProcess, type OwnedProcessOptions } from './owned-process.js';
export type JobStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'interrupted';
export interface Job { id: string; scope: JobScope; requestId: string; kind: string; status: JobStatus; progress: number; payload: JsonObject; result: Json; error: string; attempt: number; recoveryPolicy: 'safe' | 'manual'; createdAt: string; updatedAt: string }
export interface CreateJob { scope: JobScope; requestId: string; kind: string; payload: JsonObject; recoveryPolicy: 'safe' | 'manual' }
export interface JobEvent { seq: number; type: string; data: JsonObject; createdAt: string }
export interface JobClaim { jobId: string; attempt: number; ownerToken: string }
export interface JobContext extends JobClaim {
  signal: AbortSignal;
  checkpoint(): void;
  onOutcome(work: (outcome: JobOutcome) => void): void;
  emit(type: string, data: JsonObject): JobEvent;
  progress(value: number): void;
  publish<T>(work: () => T): T;
  step<T extends Json>(name: string, work: () => Promise<T>): Promise<T>;
  spawnOwned(file: string, args: string[], options?: OwnedProcessOptions): OwnedProcess;
}
export interface JobOutcome { status: 'completed' | 'cancelled' | 'failed' | 'interrupted' | 'queued'; result: Json; errorCode: string }
export interface CancelClaimResult { jobId: string; attempt: number; status: JobStatus | 'superseded' }
export type JobInitializer = (context: JobContext, payload: JsonObject) => void;
export type JobHandler = (context: JobContext, payload: JsonObject) => Promise<Json>;
interface Execution { controller: AbortController; children: OwnedProcessRegistry; claim: JobClaim; settled: Promise<void>; control?: AttemptControl; identity?: DocumentAttemptIdentity; depth: number; initializing: boolean; outcomeFailed?: boolean; outcome?: (outcome: JobOutcome) => void }
const terminal = new Set<JobStatus>(['completed', 'failed', 'cancelled', 'interrupted']);
/** One core owns scheduling; each claim/publish also fences other SQLite connections. */
export class JobQueue {
  private readonly handlers = new Map<string, { handler: JobHandler; initialize?: JobInitializer }>();
  private readonly executions = new Map<string, Execution>();
  private readonly now: () => number;
  private readonly leaseMs: number;
  private readonly heartbeatMs: number;
  constructor(readonly database: CoreDatabase, options: { now?: () => number; leaseMs?: number; heartbeatMs?: number; attemptControl?: AttemptControlBridge } = {}) {
    this.attemptBridge = options.attemptControl;
    this.now = options.now ?? Date.now; this.leaseMs = options.leaseMs ?? 90000; this.heartbeatMs = options.heartbeatMs ?? 15000;
    if (!Number.isFinite(this.leaseMs) || this.leaseMs <= 0 || !Number.isFinite(this.heartbeatMs) || this.heartbeatMs <= 0) throw new JobError(400, 'invalid_lease', 'Lease interval must be positive');
  }
  private readonly attemptBridge?: AttemptControlBridge;
  private iso() { return new Date(this.now()).toISOString(); }
  register(kind: string, handler: JobHandler, initialize?: JobInitializer): void { if (!kind || this.handlers.has(kind)) throw new JobError(409, 'handler_exists', 'Job handler already registered'); this.handlers.set(kind, { handler, initialize }); }
  private row(id: string): Row { const row = this.database.get('select * from desktop_jobs where id=?', id); if (!row) notFound(); return decoded(row); }
  private publicJob(row: Row): Job {
    const payload = object(row.payload);
    return { id: String(row.id), scope: { tenantId: String(row.tenant_id), userId: String(row.user_id) }, requestId: String(row.request_id), kind: String(row.kind), status: row.status as JobStatus, progress: Number(row.progress), payload: object(payload.input), result: row.result ?? null, error: String(row.error), attempt: Number(row.attempt), recoveryPolicy: row.recovery_policy as 'safe' | 'manual', createdAt: String(row.created_at), updatedAt: String(row.updated_at) };
  }
  get(id: string, scope: JobScope): Job { const row = this.row(id); if (String(row.tenant_id) !== scope.tenantId || String(row.user_id) !== scope.userId) notFound(); return this.publicJob(row); }
  list(scope: JobScope): Job[] { return this.database.all('select * from desktop_jobs where tenant_id=? and user_id=? order by created_at desc limit 100', scope.tenantId, scope.userId).map(r => this.publicJob(decoded(r))); }
  private cancelKey(requestId: string, scope: JobScope) { return `jobs.cancel:${createHash('sha256').update(JSON.stringify([scope.tenantId, scope.userId, requestId])).digest('hex')}`; }
  private cleanupCancellation() { this.database.run("delete from desktop_meta where key like 'jobs.cancel:%' and json_extract(value,'$.expiresAt')<=?", this.now()); }
  private append(id: string, type: string, data: JsonObject): JobEvent {
    const seq = Number(this.database.get('select coalesce(max(seq),0)+1 as seq from desktop_job_events where job_id=?', id)?.seq);
    const createdAt = this.iso(); this.database.run('insert into desktop_job_events(job_id,seq,type,data,created_at) values(?,?,?,?,?)', id, seq, type, JSON.stringify(freezeJson(data)), createdAt);
    return { seq, type, data: freezeJson(data), createdAt };
  }
  private stopSteps(id: string, attempt: number, status: string): void {
    const steps = this.database.all("select name from desktop_job_steps where job_id=? and attempt=? and status='running'", id, attempt);
    this.database.run("update desktop_job_steps set status=?,finished_at=? where job_id=? and attempt=? and status='running'", status, this.iso(), id, attempt);
    for (const step of steps) this.append(id, `step.${status}`, { name: String(step.name), attempt });
  }
  create(input: CreateJob): Job {
    if (!input.scope.userId || !input.requestId || !input.kind || !['safe', 'manual'].includes(input.recoveryPolicy)) throw new JobError(400, 'invalid_job', 'Invalid job fields');
    const payload = freezeJson(input.payload);
    return this.database.transaction(() => {
      this.cleanupCancellation();
      const existing = this.database.get('select * from desktop_jobs where request_id=?', input.requestId);
      if (existing) {
        const job = this.get(String(existing.id), input.scope);
        if (job.kind !== input.kind || JSON.stringify(job.payload) !== JSON.stringify(payload)) throw new JobError(409, 'request_conflict', 'Request already belongs to another operation');
        return job;
      }
      const key = this.cancelKey(input.requestId, input.scope); const cancelled = !!this.database.get('select key from desktop_meta where key=?', key);
      const id = randomUUID(), status = cancelled ? 'cancelled' : 'queued', now = this.iso();
      this.database.run('insert into desktop_jobs(id,tenant_id,user_id,request_id,kind,status,payload,recovery_policy,cancel_requested_at,finished_at,created_at,updated_at) values(?,?,?,?,?,?,?,?,?,?,?,?)', id, input.scope.tenantId, input.scope.userId, input.requestId, input.kind, status, JSON.stringify({ input: payload, claim: null }), input.recoveryPolicy, cancelled ? now : null, cancelled ? now : null, now, now);
      this.database.run('delete from desktop_meta where key=?', key); this.append(id, status, {}); return this.get(id, input.scope);
    });
  }
  events(id: string, scope: JobScope, afterSeq = 0): JobEvent[] { this.get(id, scope); return this.database.all('select * from desktop_job_events where job_id=? and seq>? order by seq limit 2000', id, Math.max(0, afterSeq)).map(r => ({ seq: Number(r.seq), type: String(r.type), data: object(decoded(r).data), createdAt: String(r.created_at) })); }
  cancelByRequest(requestId: string, scope: JobScope): boolean {
    const id = this.database.transaction(() => {
      this.cleanupCancellation(); const row = this.database.get('select * from desktop_jobs where request_id=? and tenant_id=? and user_id=?', requestId, scope.tenantId, scope.userId);
      if (!row) { this.database.run('insert into desktop_meta(key,value) values(?,?) on conflict(key) do update set value=excluded.value', this.cancelKey(requestId, scope), JSON.stringify({ expiresAt: this.now() + 300000 })); return null; }
      if (terminal.has(row.status as JobStatus)) return null;
      const execution = this.executions.get(String(row.id));
      if (execution?.control) {
        const cancellation = requestCancel(execution.control.shared);
        if (cancellation.disposition === 'requested' || cancellation.disposition === 'after_local_commit') execution.controller.abort(new JobError(409, 'job_cancelled', 'Job cancelled'));
        return null;
      }
      this.database.run("update desktop_jobs set status='cancelled',cancel_requested_at=?,finished_at=?,updated_at=? where id=? and status in ('queued','running')", this.iso(), this.iso(), this.iso(), String(row.id));
      this.stopSteps(String(row.id), Number(row.attempt), 'cancelled'); this.append(String(row.id), 'cancelled', {}); return String(row.id);
    });
    if (id) this.executions.get(id)?.controller.abort(new JobError(409, 'job_cancelled', 'Job cancelled'));
    return true;
  }
  private claimed(claim: JobClaim): Row {
    const row = this.row(claim.jobId), metadata = object(object(row.payload).claim);
    if (!Number.isFinite(Number(metadata.leaseUntil)) || row.cancel_requested_at != null || Number(row.attempt) !== claim.attempt || metadata.ownerToken !== claim.ownerToken || Number(metadata.leaseUntil) <= this.now()) throw new JobError(409, 'ownership_lost', 'Job ownership lost');
    return row;
  }
  private owned(claim: JobClaim): Row { const row = this.claimed(claim); if (row.status !== 'running') throw new JobError(409, 'ownership_lost', 'Job ownership lost'); return row; }
  private outcome(execution: Execution, value: JobOutcome): void {
    const result: unknown = execution.outcome?.(value);
    if (result && typeof (result as { then?: unknown }).then === 'function') { void Promise.resolve(result).catch(() => undefined); throw new JobError(400, 'invalid_outcome', 'Outcome publisher must be synchronous'); }
  }
  publish<T>(claim: JobClaim, work: () => T): T {
    const execution = this.executions.get(claim.jobId);
    if (!execution?.control || execution.claim.ownerToken !== claim.ownerToken) return this.database.transaction(() => {
      this.owned(claim);
      this.database.run("UPDATE desktop_jobs SET updated_at=? WHERE id=? AND status='running' AND attempt=? AND json_extract(payload,'$.claim.ownerToken')=?", this.iso(), claim.jobId, claim.attempt, claim.ownerToken);
      if (work.constructor.name === 'AsyncFunction') throw new JobError(400, 'async_publish', 'Publish callback must be synchronous');
      return work();
    });
    return this.documentPublication(execution, work, false);
  }
  private documentPublication<T>(execution: Execution, work: () => T, final: boolean): T {
    if (execution.initializing) throw new JobError(400, 'invalid_initializer', 'Initializer may only register terminal publication');
    execution.controller.signal.throwIfAborted(); execution.control!.checkpoint();
    if (work.constructor.name === 'AsyncFunction') throw new JobError(400, 'async_publish', 'Publish callback must be synchronous');
    const nested = execution.depth > 0;
    if (!nested && this.database.sqlite.inTransaction) throw new JobError(409, 'foreign_transaction', 'Document publication must own the outer transaction');
    execution.depth++;
    try {
      const result = this.database.transaction(() => {
        this.owned(execution.claim); execution.control!.checkpoint();
        this.database.run("UPDATE desktop_jobs SET updated_at=? WHERE id=? AND status='running' AND attempt=? AND json_extract(payload,'$.claim.ownerToken')=?", this.iso(), execution.claim.jobId, execution.claim.attempt, execution.claim.ownerToken);
        const value = work();
        if (value && typeof (value as { then?: unknown }).then === 'function') { void Promise.resolve(value).catch(() => undefined); throw new JobError(400, 'async_publish', 'Publish callback must be synchronous'); }
        execution.controller.signal.throwIfAborted(); if (final) this.claimed(execution.claim); else this.owned(execution.claim);
        if (!nested) execution.control!.beginCommit(final); else execution.control!.checkpoint();
        return value;
      });
      if (!nested) execution.control!.committed(final);
      return result;
    } catch (error) { if (!nested) execution.control!.rolledBack(); throw error; }
    finally { execution.depth--; }
  }
  private matchesDocument(row: Row, expected: DocumentAttemptIdentity | DocumentQueuedIdentity): boolean {
    const payload = object(object(row.payload).input);
    const doc = this.database.read('knowledges', expected.knowledgeId), kb = this.database.read('knowledge_bases', expected.knowledgeBaseId);
    return row.kind === 'process_knowledge' && String(row.tenant_id) === expected.tenantId && String(row.user_id) === expected.jobUserId &&
      payload.tenant_id === expected.tenantId && payload.knowledge_id === expected.knowledgeId && payload.knowledge_base_id === expected.knowledgeBaseId &&
      !!doc && doc.deleted_at === null && String(doc.tenant_id) === expected.tenantId && doc.knowledge_base_id === expected.knowledgeBaseId && object(doc.metadata as Json).workflow_job_id === expected.jobId &&
      !!kb && kb.deleted_at === null && String(kb.tenant_id) === expected.tenantId;
  }
  /** Trusted owner only. Authorization/preflight occurs before this exact tuple reaches the queue. */
  async cancelClaim(expected: DocumentAttemptIdentity | DocumentQueuedIdentity, onQueuedCancel?: () => void): Promise<CancelClaimResult> {
    const result = (): CancelClaimResult => { const row = this.row(expected.jobId); return { jobId: expected.jobId, attempt: Number(row.attempt), status: row.status as JobStatus }; };
    const superseded = (): CancelClaimResult => ({ jobId: expected.jobId, attempt: 'attempt' in expected ? expected.attempt : expected.previousAttempt, status: 'superseded' });
    const row = this.row(expected.jobId);
    if (!this.matchesDocument(row, expected)) return superseded();
    const execution = this.executions.get(expected.jobId), metadata = object(object(row.payload).claim);
    if (row.status === 'queued') {
      if ('attempt' in expected || Number(row.attempt) !== expected.previousAttempt || Object.keys(metadata).length) return superseded();
      this.database.transaction(() => {
        const current = this.row(expected.jobId);
        if (!this.matchesDocument(current, expected) || current.status !== 'queued' || Number(current.attempt) !== expected.previousAttempt || Object.keys(object(object(current.payload).claim)).length) throw new JobError(409, 'ownership_lost', 'Queued attempt changed');
        this.database.run("UPDATE desktop_jobs SET status='cancelled',cancel_requested_at=?,finished_at=?,updated_at=? WHERE id=?", this.iso(), this.iso(), this.iso(), expected.jobId);
        this.stopSteps(expected.jobId, expected.previousAttempt, 'cancelled'); this.append(expected.jobId, 'cancelled', {});
        if (onQueuedCancel?.constructor.name === 'AsyncFunction') throw new JobError(400, 'async_publish', 'Queued cancellation must be synchronous');
        const value: unknown = onQueuedCancel?.(); if (value && typeof (value as { then?: unknown }).then === 'function') { void Promise.resolve(value).catch(() => undefined); throw new JobError(400, 'async_publish', 'Queued cancellation must be synchronous'); }
      });
      return result();
    }
    if (!('attempt' in expected) && terminal.has(row.status as JobStatus) && Number(row.attempt) === expected.previousAttempt && !Object.keys(metadata).length) return result();
    const attempt = 'attempt' in expected ? expected.attempt : expected.previousAttempt + 1;
    if (Number(row.attempt) !== attempt || 'attempt' in expected && (expected.previousAttempt !== attempt - 1 || metadata.ownerToken !== expected.ownerToken)) return superseded();
    if (terminal.has(row.status as JobStatus)) { if (execution) await execution.settled; return result(); }
    if (row.status !== 'running' || Number(metadata.leaseUntil) <= this.now() || !execution?.control || execution.claim.attempt !== attempt || execution.claim.ownerToken !== metadata.ownerToken) return superseded();
    const cancellation = requestCancel(execution.control.shared);
    if (cancellation.disposition === 'invalid') throw new JobError(409, 'attempt_control_invalid', 'Attempt registry is invalid');
    if (cancellation.disposition === 'requested' || cancellation.disposition === 'after_local_commit') execution.controller.abort(new JobError(409, 'job_cancelled', 'Job cancelled'));
    await execution.settled;
    if (execution.outcomeFailed) throw new JobError(503, 'job_outcome_failed', 'Document outcome could not be confirmed');
    return result();
  }
  retry(id: string, scope: JobScope): Job {
    return this.database.transaction(() => { const job = this.get(id, scope); if (!['failed', 'interrupted'].includes(job.status)) throw new JobError(409, 'retry_forbidden', 'Only failed or interrupted jobs can be retried'); this.database.run("update desktop_jobs set status='queued',error='',cancel_requested_at=null,finished_at=null,payload=?,updated_at=? where id=?", JSON.stringify({ input: job.payload, claim: null }), this.iso(), id); this.append(id, 'retry', {}); return this.get(id, scope); });
  }
  recover(): { safe: number; manual: number } {
    return this.database.transaction(() => {
      this.cleanupCancellation(); const result = { safe: 0, manual: 0 };
      for (const row of this.database.all("select * from desktop_jobs where status='running' and coalesce(json_extract(payload,'$.claim.leaseUntil'),0)<=?", this.now())) {
        const safe = row.recovery_policy === 'safe', status = safe ? 'queued' : 'interrupted';
        const updated = this.database.run("update desktop_jobs set status=?,payload=?,updated_at=?,finished_at=? where id=? and status='running' and attempt=? and payload=?", status, JSON.stringify({ input: object(object(decoded(row).payload).input), claim: null }), this.iso(), safe ? null : this.iso(), String(row.id), Number(row.attempt), String(row.payload));
        if (Number(updated.changes)) { result[safe ? 'safe' : 'manual']++; this.stopSteps(String(row.id), Number(row.attempt), 'interrupted'); this.append(String(row.id), safe ? 'recovered' : 'interrupted', {}); this.executions.get(String(row.id))?.controller.abort(new JobError(409, 'ownership_lost', 'Job ownership lost')); }
      }
      return result;
    });
  }
  async run(id: string, options: { timeoutMs?: number } = {}): Promise<Job> {
    const initial = this.publicJob(this.row(id)); const registration = this.handlers.get(initial.kind);
    if (initial.status !== 'queued') return initial;
    if (!registration) {
      return this.database.transaction(() => {
        const changed = this.database.run("update desktop_jobs set status='failed',error=?,finished_at=?,updated_at=? where id=? and status='queued'", 'No handler registered for this job type', this.iso(), this.iso(), id);
        if (Number(changed.changes)) { this.stopSteps(id, initial.attempt, 'failed'); this.append(id, 'failed', { code: 'unknown_job_kind' }); }
        return this.publicJob(this.row(id));
      });
    }
    const controller = new AbortController(), children = new OwnedProcessRegistry();
    const claim = this.database.transaction(() => {
      const row = this.row(id); if (row.status !== 'queued') return null;
      const claim: JobClaim = { jobId: id, attempt: Number(row.attempt) + 1, ownerToken: randomUUID() };
      this.database.run("update desktop_jobs set status='running',attempt=?,payload=?,started_at=?,updated_at=?,progress=0 where id=? and status='queued'", claim.attempt, JSON.stringify({ input: initial.payload, claim: { ownerToken: claim.ownerToken, leaseUntil: this.now() + this.leaseMs } }), this.iso(), this.iso(), id);
      this.append(id, 'running', { attempt: claim.attempt }); return claim;
    });
    if (!claim) return this.publicJob(this.row(id));
    let settle!: () => void; const settled = new Promise<void>(resolve => { settle = resolve; });
    const document = initial.kind === 'process_knowledge';
    const identity: DocumentAttemptIdentity | undefined = document ? { ...claim, previousAttempt: claim.attempt - 1, tenantId: initial.scope.tenantId, jobUserId: initial.scope.userId, knowledgeId: String(initial.payload.knowledge_id), knowledgeBaseId: String(initial.payload.knowledge_base_id) } : undefined;
    const execution: Execution = { controller, children, claim, settled, identity, control: document ? new AttemptControl() : undefined, depth: 0, initializing: false }; this.executions.set(id, execution);
    const emit = (type: string, data: JsonObject) => this.publish(claim, () => this.append(id, type, data));
    const context: JobContext = {
      ...claim, signal: controller.signal,
      checkpoint: () => { if (execution.initializing) throw new JobError(400, 'invalid_initializer', 'Initializer may only register terminal publication'); controller.signal.throwIfAborted(); execution.control?.checkpoint(); this.owned(claim); },
      onOutcome: work => { if (execution.outcome || work.constructor.name === 'AsyncFunction') throw new JobError(400, 'invalid_outcome', 'Register one synchronous outcome publisher'); execution.outcome = work; },
      publish: work => this.publish(claim, work), emit,
      progress: value => { if (!Number.isFinite(value) || value < 0 || value > 1) throw new JobError(400, 'invalid_progress', 'Progress must be between zero and one'); this.publish(claim, () => { this.database.run('update desktop_jobs set progress=? where id=?', value, id); this.append(id, 'progress', { progress: value }); }); },
      step: async (name, work) => {
        this.publish(claim, () => { this.database.run("insert into desktop_job_steps(job_id,attempt,name,status,data,started_at) values(?,?,?,'running','{}',?)", id, claim.attempt, name, this.iso()); this.append(id, 'step.started', { name, attempt: claim.attempt }); });
        try { const value = freezeJson(await work()); this.publish(claim, () => { this.database.run("update desktop_job_steps set status='completed',data=?,finished_at=? where job_id=? and attempt=? and name=? and status='running'", JSON.stringify(value), this.iso(), id, claim.attempt, name); this.append(id, 'step.completed', { name, attempt: claim.attempt }); }); return value; }
        catch (error) { try { this.publish(claim, () => { this.database.run("update desktop_job_steps set status='failed',finished_at=? where job_id=? and attempt=? and name=? and status='running'", this.iso(), id, claim.attempt, name); this.append(id, 'step.failed', { name, attempt: claim.attempt }); }); } catch {} throw error; }
      },
      spawnOwned: (file, args, processOptions) => { context.checkpoint(); return children.spawn(file, args, controller.signal, processOptions); },
    };
    const heartbeat = setInterval(() => {
      try { context.checkpoint(); this.database.transaction(() => { this.owned(claim); return this.database.run("update desktop_jobs set payload=json_set(payload,'$.claim.leaseUntil',?),updated_at=? where id=?", this.now() + this.leaseMs, this.iso(), id); }); }
      catch { controller.abort(new JobError(409, 'ownership_lost', 'Job ownership lost')); }
    }, this.heartbeatMs);
    const timeout = options.timeoutMs === undefined ? undefined : setTimeout(() => controller.abort(new JobError(504, 'job_timeout', 'Job timed out')), options.timeoutMs);
    let abortListener: () => void = () => {};
    const aborted = new Promise<never>((_, reject) => { abortListener = () => reject(controller.signal.reason); controller.signal.addEventListener('abort', abortListener, { once: true }); });
    // Registration ACK may still be awaited when shutdown/cancellation arrives.
    // Consume the early rejection now; the later race retains its actual reason.
    void aborted.catch(() => undefined);
    let handlerTask: Promise<Json> | undefined, registered = false;
    try {
      if (registration.initialize) {
        if (registration.initialize.constructor.name === 'AsyncFunction') throw new JobError(400, 'invalid_initializer', 'Initializer must be synchronous');
        execution.initializing = true;
        try { const value: unknown = registration.initialize(context, freezeJson(initial.payload)); if (value && typeof (value as { then?: unknown }).then === 'function') { void Promise.resolve(value).catch(() => undefined); throw new JobError(400, 'invalid_initializer', 'Initializer must be synchronous'); } }
        finally { execution.initializing = false; }
      }
      if (identity && this.attemptBridge) { await this.attemptBridge.register(identity, execution.control!.shared); registered = true; }
      context.checkpoint();
      handlerTask = Promise.resolve().then(() => { context.checkpoint(); return registration.handler(context, freezeJson(initial.payload)); });
      const result = freezeJson(await Promise.race([handlerTask, aborted]));
      const complete = () => {
        this.outcome(execution, { status: 'completed', result, errorCode: '' });
        this.database.run("update desktop_jobs set status='completed',result=?,progress=1,error='',finished_at=?,updated_at=? where id=?", JSON.stringify(result), this.iso(), this.iso(), id);
        if (document) this.append(id, 'progress', { progress: 1 });
        this.append(id, 'completed', {});
      };
      if (document) this.documentPublication(execution, complete, true); else this.publish(claim, complete);
    } catch (error) {
      // Document cancellation ACK includes parser/chunk/helper and pipeline cleanup.
      if (document && handlerTask) { await children.close(); await handlerTask.catch(() => undefined); }
      try {
        const finish = () => {
          this.owned(claim);
          const reason = error instanceof JobError && error.code === 'job_cancelled' ? 'job_cancelled' : controller.signal.reason instanceof JobError ? controller.signal.reason.code : '';
          const unknown = initial.recoveryPolicy === 'manual' && (reason === 'job_timeout' || (error instanceof Error && 'resultUnknown' in error && error.resultUnknown === true));
          const status: JobOutcome['status'] = reason === 'job_shutdown' ? initial.recoveryPolicy === 'safe' ? 'queued' : 'interrupted' : reason === 'job_cancelled' || controller.signal.aborted && reason !== 'job_timeout' && reason !== 'ownership_lost' ? 'cancelled' : unknown ? 'interrupted' : 'failed';
          const errorCode = unknown ? 'model_result_unknown' : reason === 'job_timeout' ? 'job_timeout' : status === 'failed' ? identity && !handlerTask ? 'attempt_registration_failed' : 'document_processing_failed' : '';
          this.outcome(execution, { status, result: null, errorCode });
          this.database.run('update desktop_jobs set status=?,error=?,finished_at=?,updated_at=? where id=?', status, unknown && status === 'interrupted' ? 'Upstream result unknown; explicit retry required' : reason === 'job_timeout' ? 'Job timed out' : status === 'failed' ? 'Job execution failed' : '', status === 'queued' ? null : this.iso(), this.iso(), id);
          this.stopSteps(id, claim.attempt, status === 'queued' ? 'interrupted' : status);
          if (reason === 'job_shutdown') this.database.run('update desktop_jobs set payload=? where id=?', JSON.stringify({ input: initial.payload, claim: null }), id);
          if (status === 'cancelled') this.database.run('UPDATE desktop_jobs SET cancel_requested_at=? WHERE id=?', this.iso(), id);
          this.append(id, status, unknown && status === 'interrupted' ? { result_unknown: true } : {});
          return status;
        };
        const status = this.database.transaction(finish);
        execution.control?.terminal(status);
      } catch {
        // Only a durable ownership change justifies suppressing a stale writer.
        // A still-owned terminal transaction fault is an unconfirmed result.
        let stillOwned = false;
        try { this.owned(claim); stillOwned = true; } catch { }
        execution.control?.invalidate();
        if (document && stillOwned) { execution.outcomeFailed = true; throw new JobError(503, 'job_outcome_failed', 'Document outcome could not be confirmed'); }
      }
    } finally {
      clearInterval(heartbeat); clearTimeout(timeout); controller.signal.removeEventListener('abort', abortListener); await children.close();
      // unregister only after durable terminal publication and all owned cleanup settled.
      try { if (registered && identity && !execution.outcomeFailed) this.attemptBridge!.unregister(identity, execution.control!.shared); }
      finally { if (this.executions.get(id) === execution) this.executions.delete(id); settle(); }
    }
    return this.publicJob(this.row(id));
  }
  async close(): Promise<void> { const running = [...this.executions.values()]; running.forEach(e => e.controller.abort(new JobError(409, 'job_shutdown', 'Job interrupted by shutdown'))); await Promise.all(running.map(e => e.settled)); }
}
