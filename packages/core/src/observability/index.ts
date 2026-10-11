import { createHash, randomBytes } from 'node:crypto';
import type { AuthContext, Json, JsonObject } from '../contracts.js';
import type { AuthService } from '../auth/index.js';
import type { ChatExecution } from '../chat/types.js';
import { AppError } from '../errors.js';
import type { IntegrationService, TraceEvent } from '../integrations/index.js';
import { endpoint } from '../integrations/network.js';
import { SessionEventJournal } from '../jobs/journal.js';
import { CredentialVault } from '../storage/credentials.js';
import type { CoreDatabase, Row } from '../storage/database.js';
import { withObservation } from './context.js';
import type { ChatObserver, ObservationContext } from './types.js';
export type { ChatObserver, ModelObservation } from './types.js';

const object = (value: unknown): JsonObject => value && typeof value === 'object' && !Array.isArray(value) ? value as JsonObject : {};
const decode = (value: unknown): JsonObject => object(typeof value === 'string' ? JSON.parse(value) : value);
const hash = (value: unknown) => createHash('sha256').update(JSON.stringify(value)).digest('hex');
const stamp = (value: unknown) => typeof value === 'string' ? Date.parse(value) : NaN;
const ident = (bytes: number) => randomBytes(bytes).toString('hex');
interface Snapshot { signature: string; config: JsonObject }
interface Source {
  context: AuthContext; jobId: string; attempt: number; token: string; inputHash: string; configuration: Snapshot;
  sessionId?: string; messageId?: string; requestId?: string; knowledgeId?: string; knowledgeBaseId?: string;
  signal?: AbortSignal;
}
interface Delivery { source: Source; event: TraceEvent; link: boolean }

/** Optional telemetry never waits inside a business transaction or repeats a model invocation. */
export class ObservabilityService {
  readonly chatObserver: ChatObserver;
  private readonly vault: CredentialVault;
  private readonly journal: SessionEventJournal;
  private readonly timeoutMs: number;
  private readonly maxQueue: number;
  private readonly queue: Delivery[] = [];
  private readonly active = new Set<Promise<void>>();
  private readonly controllers = new Set<AbortController>();
  private closed = false;
  private closing?: Promise<void>;
  constructor(readonly db: CoreDatabase, readonly auth: AuthService, readonly integrations: Pick<IntegrationService, 'recordTrace'>, options: { timeoutMs?: number; maxQueue?: number } = {}) {
    this.timeoutMs = options.timeoutMs ?? 1500; this.maxQueue = options.maxQueue ?? 128;
    if (!Number.isSafeInteger(this.timeoutMs) || this.timeoutMs < 1 || this.timeoutMs > 60000 || !Number.isSafeInteger(this.maxQueue) || this.maxQueue < 1 || this.maxQueue > 1000) throw new AppError(400, 'observability_invalid_options', 'Invalid telemetry limits');
    this.vault = new CredentialVault(db.dataRoot); this.journal = new SessionEventJournal(db);
    this.chatObserver = { run: (execution, work, kind) => this.observeChat(execution, work, kind ?? 'chat.turn'), projectTrajectory: (ctx, id, trajectory) => this.projectTrajectory(ctx, id, trajectory) };
  }
  private snapshot(ctx: AuthContext): Snapshot {
    this.auth.assertCan(ctx, 'read'); const row = this.db.read('integration_configs', 'langfuse');
    const config = row && row.deleted_at === null ? object(this.vault.decrypt(object(row.parameters))) : {};
    return { signature: hash(row ? [row.parameters, row.deleted_at] : null), config };
  }
  private source(ctx: AuthContext, job: Row, configuration: Snapshot, fields: Partial<Source>): Source {
    const payload = decode(job.payload), claim = object(payload.claim);
    return { context: { ...ctx }, jobId: String(job.id), attempt: Number(job.attempt), token: String(claim.ownerToken ?? ''), inputHash: hash(payload.input), configuration, ...fields };
  }
  /** Recheck the real principal, exact claim, source and saved configuration on both sides of HTTP. */
  private fence(source: Source): void {
    if (this.closed) throw new AppError(503, 'observability_closed', 'Telemetry is closed');
    if (source.signal?.aborted) throw new AppError(499, 'observability_cancelled', 'Telemetry source stopped');
    const ctx = source.context; this.auth.assertCan(ctx, 'read'); const job = this.db.get('SELECT * FROM desktop_jobs WHERE id=?', source.jobId);
    const payload = job ? decode(job.payload) : {}, claim = object(payload.claim), input = object(payload.input);
    if (!job || String(job.tenant_id) !== ctx.tenantId || job.user_id !== ctx.userId || !['running', 'completed', 'failed'].includes(String(job.status)) || job.cancel_requested_at !== null || Number(job.attempt) !== source.attempt || !source.token || claim.ownerToken !== source.token || hash(payload.input) !== source.inputHash || job.status === 'running' && Number(claim.leaseUntil) <= Date.now()) throw new AppError(409, 'observability_source_changed', 'Telemetry source changed');
    if (this.snapshot(ctx).signature !== source.configuration.signature) throw new AppError(409, 'observability_configuration_changed', 'Telemetry configuration changed');
    if (source.sessionId) {
      const session = this.db.read('sessions', source.sessionId), message = this.db.read('messages', source.messageId!);
      if (!session || session.deleted_at !== null || String(session.tenant_id) !== ctx.tenantId || session.user_id !== ctx.userId || !message || message.deleted_at !== null || message.role !== 'assistant' || message.session_id !== source.sessionId || message.request_id !== source.requestId || input.session_id !== source.sessionId || input.message_id !== source.messageId || input.request_id !== source.requestId) throw new AppError(409, 'observability_source_changed', 'Telemetry source changed');
      if (input.user_message_id) {
        const user = this.db.read('messages', String(input.user_message_id));
        if (!user || user.deleted_at !== null || user.role !== 'user' || user.session_id !== source.sessionId || user.request_id !== source.requestId || user.content !== object(input.input).query) throw new AppError(409, 'observability_source_changed', 'Telemetry user source changed');
      }
      if (Array.isArray(input.source_ids)) for (let i = 0; i < input.source_ids.length; i++) {
        const row = this.db.read('messages', String(input.source_ids[i]));
        if (!row || row.deleted_at !== null || row.session_id !== source.sessionId || !Array.isArray(input.source_fingerprints) || JSON.stringify(row) !== input.source_fingerprints[i]) throw new AppError(409, 'observability_source_changed', 'Telemetry source changed');
      }
      for (const id of Array.isArray(input.knowledge_base_ids) ? input.knowledge_base_ids : []) { const kb = this.db.read('knowledge_bases', String(id)); if (!kb || kb.deleted_at !== null || String(kb.tenant_id) !== ctx.tenantId) throw new AppError(409, 'observability_source_changed', 'Telemetry scope changed'); }
      if (job.kind === 'chat.actor') {
        const actor = this.db.read('agent_actors', String(input.actor_row_id)), parent = this.db.get('SELECT status FROM desktop_jobs WHERE id=?', String(input.parent_job_id));
        if (!actor || actor.deleted_at !== null || actor.session_id !== source.sessionId || actor.parent_message_id !== source.messageId || object(actor.metadata).job_id !== source.jobId || !parent || ['cancelled', 'interrupted', 'failed'].includes(String(parent.status))) throw new AppError(409, 'observability_source_changed', 'Telemetry actor changed');
      }
    } else if (source.knowledgeId) {
      const doc = this.db.read('knowledges', source.knowledgeId), kb = this.db.read('knowledge_bases', source.knowledgeBaseId!);
      if (!doc || !kb || doc.deleted_at !== null || kb.deleted_at !== null || String(doc.tenant_id) !== ctx.tenantId || String(kb.tenant_id) !== ctx.tenantId || doc.knowledge_base_id !== source.knowledgeBaseId || input.knowledge_id !== source.knowledgeId || input.knowledge_base_id !== source.knowledgeBaseId || object(doc.metadata).workflow_job_id && object(doc.metadata).workflow_job_id !== source.jobId) throw new AppError(409, 'observability_source_changed', 'Telemetry document changed');
    }
  }
  private diagnostic(source: Source | undefined, state: string): void {
    if (this.closed) return;
    try { this.db.run('INSERT INTO desktop_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', `observability.last:${source ? hash([source.context.tenantId, source.context.userId, source.jobId]) : 'service'}`, JSON.stringify({ state, ...(source ? { tenant_id: source.context.tenantId, job_id: source.jobId, attempt: source.attempt } : {}), at: new Date().toISOString() })); } catch { /* Closing storage must not affect business results. */ }
  }
  private enqueue(source: Source, event: TraceEvent, link = false): void {
    if (this.closed) return;
    if (this.queue.length + this.active.size >= this.maxQueue) { this.diagnostic(source, 'queue_full'); return; }
    this.queue.push({ source, event, link }); this.pump();
  }
  private pump(): void {
    while (!this.closed && this.queue.length && this.active.size < 2) {
      const item = this.queue.shift()!, controller = new AbortController(); this.controllers.add(controller);
      const pending = Promise.resolve().then(() => this.deliver(item, controller)); this.active.add(pending);
      void pending.finally(() => { this.active.delete(pending); this.controllers.delete(controller); this.pump(); }).catch(() => {});
    }
  }
  private async deliver(item: Delivery, controller: AbortController): Promise<void> {
    const { source, event } = item; let timer: ReturnType<typeof setTimeout> | undefined, abortListener: (() => void) | undefined;
    try {
      this.fence(source); timer = setTimeout(() => controller.abort(), this.timeoutMs);
      const cancelled = new Promise<never>((_, reject) => { abortListener = () => reject(new AppError(504, 'observability_timeout', 'Telemetry stopped')); controller.signal.addEventListener('abort', abortListener, { once: true }); if (controller.signal.aborted) abortListener(); });
      const signal = source.signal ? AbortSignal.any([controller.signal, source.signal]) : controller.signal;
      const result = await Promise.race([this.integrations.recordTrace(source.context, event, { signal, timeoutMs: this.timeoutMs }), cancelled]);
      this.fence(source); this.diagnostic(source, String(result.state ?? 'invalid_response'));
      if (result.state !== 'accepted' || result.trace_id !== event.traceId || result.span_id !== event.spanId) return;
      if (item.link && source.sessionId) this.db.transaction(() => {
        this.fence(source);
        const key = `observability.receipt:${hash([source.context.tenantId, source.context.userId, source.sessionId, source.requestId])}`;
        this.db.run('INSERT INTO desktop_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', key, JSON.stringify({ trace_id: event.traceId, span_id: event.spanId, configuration_signature: source.configuration.signature, message_id: source.messageId, job_id: source.jobId, attempt: source.attempt, owner_token: source.token }));
        this.journal.append(source.sessionId!, source.requestId!, 'observability/trace-linked', { provider: 'langfuse', trace_id: event.traceId, root_observation_id: event.spanId }, { tenantId: source.context.tenantId, userId: source.context.userId });
      });
    } catch (error) {
      const code = error instanceof AppError ? error.code : 'observability_delivery_failed';
      this.diagnostic(source, /^[a-z][a-z0-9_]{0,127}$/.test(code) ? code : 'observability_delivery_failed');
    } finally { clearTimeout(timer); if (abortListener) controller.signal.removeEventListener('abort', abortListener); }
  }
  private async observeChat<T>(execution: ChatExecution, work: () => Promise<T>, kind: 'chat.turn' | 'agent.run' | 'chat.maintenance'): Promise<T> {
    let candidate: Source | undefined;
    try {
      const configuration = this.snapshot(execution.context), job = this.db.get('SELECT * FROM desktop_jobs WHERE id=?', execution.job.jobId)!;
      if (!this.closed && configuration.config.enabled === true) { candidate = this.source(execution.context, job, configuration, { sessionId: execution.sessionId, messageId: execution.messageId, requestId: execution.requestId, signal: execution.signal }); this.fence(candidate); }
    } catch { candidate = undefined; }
    // Business work sits outside the setup catch, so even a synchronous failure runs exactly once.
    if (!candidate) return work(); const source = candidate;
    const traceId = ident(16), spanId = ident(8), startedAt = Date.now(), metadata: JsonObject = { session_id: execution.sessionId, message_id: execution.messageId, request_id: execution.requestId, job_id: source.jobId, attempt: source.attempt };
    const openTools = new Map<string, { startedAt: number; spanId: string; input: Json }>(), retrievals: Array<{ startedAt: number; spanId: string; input: Json }> = [];
    const actors = new Map<string, { startedAt: number; spanId: string; input: Json }>();
    const observation: ObservationContext = {
      context: execution.context,
      model: event => this.enqueue(source, { name: event.scenario === 'chat' || event.scenario.startsWith('agent') ? 'llm.chat' : 'llm.call', traceId, spanId: ident(8), parentSpanId: actors.get(String(event.metadata.actor_id))?.spanId ?? spanId, startedAt: event.startedAt, endedAt: event.endedAt, success: event.success, type: event.scenario.includes('embedding') ? 'embedding' : 'generation', sessionId: execution.sessionId, metadata: { ...metadata, ...event.metadata, model_call_id: event.invocationId, scenario: event.scenario }, usage: event.usage }),
      journal: (type, data) => {
        const at = Date.now();
        const toolKey = `${data.actor_id ?? ''}:${data.tool_call_id ?? ''}`;
        if (type === 'tool/call' && typeof data.tool_call_id === 'string') openTools.set(toolKey, { startedAt: at, spanId: ident(8), input: data.arguments ?? null });
        else if (type === 'tool/result' && typeof data.tool_call_id === 'string') { const tool = openTools.get(toolKey); if (tool) { openTools.delete(toolKey); this.enqueue(source, { name: 'agent.tool', traceId, spanId: tool.spanId, parentSpanId: actors.get(String(data.actor_id))?.spanId ?? spanId, startedAt: tool.startedAt, endedAt: at, success: !data.error, type: 'tool', sessionId: execution.sessionId, metadata, input: tool.input, output: data.output ?? null }); } }
        else if (type === 'retrieval/search') retrievals.push({ startedAt: at, spanId: ident(8), input: data.query ?? null });
        else if (type === 'retrieval/result') { const retrieval = retrievals.pop(); if (retrieval) this.enqueue(source, { name: 'retrieval.search', traceId, spanId: retrieval.spanId, parentSpanId: spanId, startedAt: retrieval.startedAt, endedAt: at, success: true, type: 'retriever', sessionId: execution.sessionId, metadata, input: retrieval.input, output: { count: data.count ?? 0 } }); }
        else if (type === 'agent/actor' && typeof data.actor_id === 'string') {
          if (data.event === 'spawned') actors.set(data.actor_id, { startedAt: at, spanId: ident(8), input: data.input_prompt ?? null });
          else if (['completed', 'failed', 'cancelled', 'interrupted'].includes(String(data.event))) {
            const actor = actors.get(data.actor_id); if (actor) { actors.delete(data.actor_id); this.enqueue(source, { name: 'agent.run', traceId, spanId: actor.spanId, parentSpanId: spanId, startedAt: actor.startedAt, endedAt: at, success: data.event === 'completed', type: 'agent', sessionId: execution.sessionId, metadata, input: actor.input, output: data.output_excerpt ?? null }); }
          }
        }
      },
    };
    let success = false, output: Json = null;
    try { const result = await withObservation(observation, work); success = true; const value = object(result); output = value.content ?? value.answer ?? null; return result; }
    finally { this.enqueue(source, { name: kind, traceId, spanId, startedAt, endedAt: Date.now(), success, type: kind === 'agent.run' ? 'agent' : 'chain', sessionId: execution.sessionId, metadata, input: execution.query, output }, kind === 'chat.turn'); }
  }
  private projectTrajectory(ctx: AuthContext, id: string, trajectory: JsonObject): JsonObject {
    const result = structuredClone(trajectory);
    try {
      this.auth.assertCan(ctx, 'read'); const session = this.db.read('sessions', id);
      if (!session || session.deleted_at !== null || String(session.tenant_id) !== ctx.tenantId || session.user_id !== ctx.userId) return result;
      const { signature, config } = this.snapshot(ctx);
      if (!ctx.userId || this.auth.me(ctx).user.is_system_admin !== true || config.enabled !== true || config.trace_links_enabled !== true || !config.ui_project_id || typeof config.ui_project_id !== 'string') return result;
      const base = endpoint(config.ui_base_url || config.base_url); const project = config.ui_project_id;
      if (project.length > 256) return result;
      for (const turn of Array.isArray(result.turns) ? result.turns : []) {
        const value = object(turn), linked = object(value.observability);
        if (!/^[0-9a-f]{32}$/.test(String(linked.trace_id)) || linked.link_state !== 'recorded') continue;
        const receipt = this.db.get('SELECT value FROM desktop_meta WHERE key=?', `observability.receipt:${hash([ctx.tenantId, ctx.userId, id, value.request_id])}`); if (!receipt) continue;
        const saved = decode(receipt.value), message = this.db.read('messages', String(saved.message_id)), job = this.db.get('SELECT * FROM desktop_jobs WHERE id=?', String(saved.job_id));
        if (saved.trace_id !== linked.trace_id || saved.configuration_signature !== signature || !message || message.deleted_at !== null || message.session_id !== id || message.request_id !== value.request_id || !job || String(job.tenant_id) !== ctx.tenantId || job.user_id !== ctx.userId || !['running', 'completed'].includes(String(job.status)) || job.cancel_requested_at !== null || Number(job.attempt) !== saved.attempt || object(decode(job.payload).claim).ownerToken !== saved.owner_token) continue;
        linked.trace_url = `${base.href.replace(/\/$/, '')}/project/${encodeURIComponent(project)}/traces/${linked.trace_id}`;
      }
    } catch { /* Optional links never block an already authorized trajectory. */ }
    return result;
  }
  async observeDocumentJob<T>(jobId: string, work: () => Promise<T>): Promise<T> {
    // Repeated scheduling of an already terminal job must not produce a new parse trace.
    let eligible = false; try { eligible = !this.closed && this.db.get('SELECT status FROM desktop_jobs WHERE id=?', jobId)?.status === 'queued'; } catch { /* Optional telemetry cannot prevent scheduling. */ }
    const pending = work(); let claim: { attempt: number; token: string } | undefined;
    if (eligible) try { const started = this.db.get('SELECT attempt,payload,status FROM desktop_jobs WHERE id=?', jobId); if (started?.status === 'running') claim = { attempt: Number(started.attempt), token: String(object(decode(started.payload).claim).ownerToken ?? '') }; } catch {}
    try { return await pending; }
    finally { if (claim) try { this.documentFacts(jobId, claim); } catch { this.diagnostic(undefined, 'document_observation_unavailable'); } }
  }
  private documentFacts(jobId: string, claim: { attempt: number; token: string }): void {
    if (this.closed) return; const job = this.db.get('SELECT * FROM desktop_jobs WHERE id=?', jobId); if (!job || job.kind !== 'process_knowledge') return;
    if (Number(job.attempt) !== claim.attempt || object(decode(job.payload).claim).ownerToken !== claim.token) return;
    const input = object(decode(job.payload).input), ctx = (input.auth ?? input.context) as unknown as AuthContext;
    const configuration = this.snapshot(ctx); if (configuration.config.enabled !== true) return;
    const source = this.source(ctx, job, configuration, { knowledgeId: String(input.knowledge_id), knowledgeBaseId: String(input.knowledge_base_id) }); this.fence(source);
    const spans = this.db.all('SELECT id FROM knowledge_processing_spans WHERE knowledge_id=? ORDER BY started_at,id', source.knowledgeId!).map(row => this.db.read('knowledge_processing_spans', String(row.id))!).filter(row => object(row.metadata).job_id === jobId && Number(object(row.metadata).queue_attempt) === source.attempt && Number.isFinite(stamp(row.started_at)) && Number.isFinite(stamp(row.finished_at)) && stamp(row.finished_at) >= stamp(row.started_at));
    const root = spans.find(row => row.kind === 'root'), startedAt = root ? stamp(root.started_at) : stamp(job.started_at), endedAt = root ? stamp(root.finished_at) : stamp(job.finished_at);
    if (!Number.isFinite(startedAt) || !Number.isFinite(endedAt) || endedAt < startedAt) return;
    const traceId = ident(16), spanId = ident(8), metadata: JsonObject = { knowledge_id: source.knowledgeId!, knowledge_base_id: source.knowledgeBaseId!, job_id: jobId, attempt: source.attempt };
    this.enqueue(source, { name: 'knowledge.parse', traceId, spanId, startedAt, endedAt, success: job.status === 'completed', type: 'chain', metadata });
    const persisted = spans.filter(row => row.kind !== 'root');
    if (persisted.length) for (const row of persisted.slice(0, 100)) this.enqueue(source, { name: 'knowledge.stage', traceId, spanId: ident(8), parentSpanId: spanId, startedAt: stamp(row.started_at), endedAt: stamp(row.finished_at), success: row.status === 'done' || row.status === 'completed', type: 'span', metadata: { ...metadata, operation: String(row.name).replace(/[^a-z0-9_.-]/g, '_').slice(0, 64) } });
    else for (const row of this.db.all('SELECT * FROM desktop_job_steps WHERE job_id=? AND attempt=? AND finished_at IS NOT NULL ORDER BY id LIMIT 100', jobId, source.attempt)) {
      const start = stamp(row.started_at), end = stamp(row.finished_at); if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) continue;
      this.enqueue(source, { name: 'knowledge.stage', traceId, spanId: ident(8), parentSpanId: spanId, startedAt: start, endedAt: end, success: row.status === 'completed', type: 'span', metadata: { ...metadata, operation: String(row.name).replace(/[^a-z0-9_.-]/g, '_').slice(0, 64) } });
    }
  }
  async flush(): Promise<void> { while (this.queue.length || this.active.size) { this.pump(); await Promise.allSettled([...this.active]); } }
  close(): Promise<void> {
    if (this.closing) return this.closing;
    this.closed = true; this.queue.length = 0; for (const controller of this.controllers) controller.abort();
    this.closing = Promise.allSettled([...this.active]).then(() => {}); return this.closing;
  }
}
