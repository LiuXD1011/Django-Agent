import { randomUUID } from 'node:crypto';
import type { AuthContext, JsonObject } from '../contracts.js';
import type { AuthService } from '../auth/index.js';
import type { CoreDatabase, Row } from '../storage/database.js';
import { CredentialVault } from '../storage/credentials.js';
import type { JobQueue, JobContext, Job } from '../jobs/queue.js';
import { LegacyEvaluationReports } from './legacy-reports.js';
import { corpusFingerprint } from './fingerprint.js';
import { fail, object, now, digest } from './common.js';

export class EvaluationStore {
  private readonly vault: CredentialVault;
  readonly legacy: LegacyEvaluationReports;
  publicFreshness?: (ctx: AuthContext, fingerprint: JsonObject) => boolean;
  constructor(readonly db: CoreDatabase, readonly auth: AuthService, readonly jobs: JobQueue, legacyCacheRoot?: string) { this.vault = new CredentialVault(db.dataRoot); this.legacy = new LegacyEvaluationReports(db, legacyCacheRoot); }
  row(ctx: AuthContext, id: string, type = 'rag_eval_runs'): Row {
    this.auth.assertCan(ctx, 'read'); const row = this.db.read('generic_resources', id);
    if (!row || row.deleted_at !== null || String(row.tenant_id) !== ctx.tenantId || row.resource_type !== type) return fail(404, type === 'rag_eval_reports' ? 'report_not_found' : 'evaluation_run_not_found', 'Evaluation resource not found');
    return row;
  }
  checkpoint(row: Row): JsonObject {
    const id = String(object(row.data).checkpoint_id || ''), checkpoint = this.db.read('generic_resources', id);
    if (!checkpoint || checkpoint.deleted_at !== null || checkpoint.resource_type !== 'rag_eval_checkpoints' || String(checkpoint.tenant_id) !== String(row.tenant_id)) return fail(409, 'checkpoint_unavailable', 'Evaluation checkpoint is unavailable');
    try { return object(JSON.parse(String(this.vault.decrypt(object(checkpoint.data)).secret))); } catch { return fail(409, 'checkpoint_unavailable', 'Evaluation checkpoint cannot be read; restore the original key'); }
  }
  save(row: Row, state: JsonObject, context?: JobContext): void {
    const work = () => { this.db.update('generic_resources', String(object(row.data).checkpoint_id), { data: this.vault.encrypt({ secret: JSON.stringify(state) }), updated_at: now() }); };
    if (context) context.publish(work); else this.db.transaction(work);
  }
  private invocationId(row: Row, state: JsonObject, key: string): string { return `eval-call-${digest([row.tenant_id, state.ledger_id || row.id, key])}`; }
  invocation(row: Row, state: JsonObject, key: string): JsonObject {
    const value = this.db.read('generic_resources', this.invocationId(row, state, key));
    if (!value) return object(object(state.calls)[key]);
    if (value.tenant_id !== row.tenant_id || value.resource_type !== 'rag_eval_invocations') return fail(409, 'checkpoint_mismatch', 'Invocation ledger scope does not match');
    const data = object(value.data); let result: JsonObject = {};
    if (data.secret) { try { result = object(JSON.parse(String(this.vault.decrypt(object(data.secret)).secret))); } catch { return fail(409, 'checkpoint_unavailable', 'Invocation result cannot be decrypted'); } }
    return { ...data, result };
  }
  saveInvocation(row: Row, state: JsonObject, key: string, value: JsonObject, context: JobContext): void {
    context.publish(() => {
      const id = this.invocationId(row, state, key), { result, ...safe } = value;
      const data: JsonObject = { ...safe, ledger_id: String(state.ledger_id || row.id), secret: result ? this.vault.encrypt({ secret: JSON.stringify(result) }) : null };
      if (this.db.read('generic_resources', id)) this.db.update('generic_resources', id, { data, status: String(value.status), updated_at: now() });
      else this.db.insert('generic_resources', { id, tenant_id: row.tenant_id, resource_type: 'rag_eval_invocations', name: 'Private evaluation invocation', status: String(value.status), data });
    });
  }
  unknown(row: Row, state: JsonObject): boolean {
    return Object.values(object(state.calls)).some(call => ['pending', 'unknown'].includes(String(object(call).status))) || !!this.db.get("SELECT id FROM generic_resources WHERE tenant_id=? AND resource_type='rag_eval_invocations' AND json_extract(data,'$.ledger_id')=? AND status IN ('pending','unknown') LIMIT 1", String(row.tenant_id), String(state.ledger_id || row.id));
  }
  acknowledge(row: Row, state: JsonObject): void {
    const calls = object(state.calls); for (const [key, raw] of Object.entries(calls)) if (['pending', 'unknown', 'failed'].includes(String(object(raw).status))) delete calls[key];
    this.db.run("UPDATE generic_resources SET status='acknowledged',data=json_set(data,'$.status','acknowledged'),updated_at=? WHERE tenant_id=? AND resource_type='rag_eval_invocations' AND json_extract(data,'$.ledger_id')=? AND status IN ('pending','unknown','failed')", now(), String(row.tenant_id), String(state.ledger_id || row.id));
  }
  invocationCount(row: Row, state: JsonObject): number { return Number(this.db.get("SELECT count(*) AS total FROM generic_resources WHERE tenant_id=? AND resource_type='rag_eval_invocations' AND json_extract(data,'$.ledger_id')=? AND status='completed'", String(row.tenant_id), String(state.ledger_id || row.id))?.total || 0) + Object.values(object(state.calls)).filter(call => object(call).status === 'completed').length; }
  create(ctx: AuthContext, input: JsonObject, state: JsonObject, requestId: string): JsonObject {
    this.auth.assertCan(ctx, 'eval.write');
    return this.db.transaction(() => {
      const job = this.jobs.create({ scope: { tenantId: ctx.tenantId, userId: ctx.userId }, requestId, kind: 'rag_evaluation', payload: { configuration: input }, recoveryPolicy: 'manual' });
      if (!this.db.read('generic_resources', job.id)) {
        const checkpoint = this.db.insert('generic_resources', { tenant_id: ctx.tenantId, resource_type: 'rag_eval_checkpoints', name: 'Private evaluation checkpoint', status: 'active', data: this.vault.encrypt({ secret: JSON.stringify({ ...state, ledger_id: state.ledger_id || job.id, context: { userId: ctx.userId, tenantId: ctx.tenantId, deviceId: ctx.deviceId, role: '', isSystemAdmin: false }, calls: {}, rows: [] }) }) });
        this.db.insert('generic_resources', { id: job.id, tenant_id: ctx.tenantId, resource_type: 'rag_eval_runs', name: 'RAG evaluation', status: job.status, data: { requested_configuration: input, checkpoint_id: String(checkpoint.id), fingerprint: state.fingerprint!, effective_pipeline: state.effective_pipeline!, source: input.source!, sample_size: Array.isArray(state.entries) ? state.entries.length : 0, report_id: null } });
      }
      return this.dto(ctx, this.row(ctx, job.id), job);
    });
  }
  freshness(ctx: AuthContext, row: Row): string {
    const data = object(row.data), snapshot = object(data.fingerprint);
    if (snapshot.public_dataset_id) return this.publicFreshness?.(ctx, snapshot) ? 'current' : 'stale';
    if (snapshot.corpus_hash && digest(corpusFingerprint(this.db, ctx, String(snapshot.knowledge_base_id))) !== digest({ knowledge_base_id: snapshot.knowledge_base_id, corpus_hash: snapshot.corpus_hash, documents: snapshot.documents })) return 'stale';
    if (snapshot.corpus_hash && !snapshot.dataset_id) return 'current';
    const dataset = this.db.read('generic_resources', String(snapshot.dataset_id || ''));
    if (!dataset || dataset.deleted_at !== null || String(dataset.tenant_id) !== ctx.tenantId || object(dataset.data).dataset_hash !== snapshot.dataset_hash) return snapshot.dataset_id ? 'stale' : 'unknown';
    if (!Array.isArray(snapshot.documents)) return 'unknown';
    return snapshot.documents.some(raw => { const item = object(raw), doc = this.db.read('knowledges', String(item.id)); return !doc || doc.deleted_at !== null || String(doc.tenant_id) !== ctx.tenantId || doc.file_hash !== item.file_hash || (object(doc.metadata).source_generation ?? null) !== item.source_generation; }) ? 'stale' : 'current';
  }
  dto(ctx: AuthContext, row: Row, job?: Job): JsonObject {
    const data = object(row.data), reportId = String(data.report_id || ''), report = reportId ? this.db.read('generic_resources', reportId) : undefined;
    const available = !!report && report.deleted_at === null && String(report.tenant_id) === ctx.tenantId && report.resource_type === 'rag_eval_reports';
    const result = available ? object(report?.data) : data;
    const persisted = this.db.get('SELECT status,progress,attempt,started_at,finished_at FROM desktop_jobs WHERE id=? AND tenant_id=?', String(row.id), ctx.tenantId);
    const status = String(job?.status ?? persisted?.status ?? row.status), progress = Number(job?.progress ?? persisted?.progress ?? 0);
    let completed = 0; try { completed = (object(this.checkpoint(row).scores).rows as JsonObject[] || []).length; } catch {}
    const stageEvent = this.db.get("SELECT data FROM desktop_job_events WHERE job_id=? AND type='evaluation.stage' ORDER BY seq DESC LIMIT 1", String(row.id));
    let stage: JsonObject = {}; try { stage = object(JSON.parse(String(stageEvent?.data || '{}'))); } catch {}
    const start = Date.parse(String(persisted?.started_at || '')), finish = Date.parse(String(persisted?.finished_at || ''));
    const elapsed = Number.isFinite(start) ? Math.max(0, ((Number.isFinite(finish) ? finish : Date.now()) - start) / 1000) : null;
    let unknown = false;
    if (['cancelled', 'failed', 'interrupted'].includes(status) && data.checkpoint_id) {
      try { unknown = this.unknown(row, this.checkpoint(row)); } catch { unknown = true; }
    }
    return { run_id: String(row.id), task_run_id: String(row.id), report_id: reportId || null, available, report_url: available ? `/api/v1/rag-eval/reports/${reportId}` : null, run_status: status, status, progress, stage: stage.stage ?? null, completed_questions: completed, valid_coverage: data.sample_size ? completed / Number(data.sample_size) : null, elapsed_seconds: elapsed, eta_seconds: null, started_at: persisted?.started_at ?? null, completed_at: persisted?.finished_at ?? null, attempt: job?.attempt ?? persisted?.attempt ?? 0, evaluation_type: 'rag', dataset: { ...object(object(data.requested_configuration).source), entries: data.sample_size ?? 0 }, verified: result.verification_status === 'verified', requested_configuration: data.requested_configuration ?? {}, effective_pipeline: data.effective_pipeline ?? {}, verification_status: result.verification_status ?? (status === 'failed' ? 'failed' : 'unverified'), freshness_status: this.freshness(ctx, row), metrics: result.metrics ?? null, report: reportId ? { id: reportId, url: `/api/v1/rag-eval/reports/${reportId}`, available } : null, created_at: row.created_at!, updated_at: row.updated_at!, result_unknown: unknown, sample_size: data.sample_size ?? 0, total_questions: data.sample_size ?? 0 };
  }
  status(ctx: AuthContext, id: string): JsonObject { const row = this.row(ctx, id); let job; try { job = this.jobs.get(id, { tenantId: ctx.tenantId, userId: ctx.userId }); } catch {} return this.dto(ctx, row, job); }
  deterministicDto(ctx: AuthContext, row: Row): JsonObject {
    this.auth.assertCan(ctx, 'read'); const data = object(row.data), reportId = String(data.report_id || ''), report = reportId ? this.db.read('generic_resources', reportId) : undefined;
    const available = !!report && report.deleted_at === null && String(report.tenant_id) === ctx.tenantId;
    return { ...data, run_id: String(row.id), status: String(row.status), run_status: String(row.status), completed_questions: row.status === 'completed' ? data.sample_size ?? 0 : 0, total_questions: data.sample_size ?? 0, available, report: reportId ? { id: reportId, available, url: available ? `/api/v1/rag-eval/reports/${reportId}` : null } : null, dataset: { entries: data.sample_size ?? 0 }, created_at: row.created_at!, freshness_status: this.freshness(ctx, row) };
  }
  history(ctx: AuthContext): JsonObject {
    this.auth.assertCan(ctx, 'read'); return { history: [...this.legacy.list(ctx), ...this.db.all("SELECT id FROM generic_resources WHERE tenant_id=? AND resource_type='rag_eval_deterministic_runs' AND deleted_at IS NULL ORDER BY created_at DESC,id LIMIT 100", ctx.tenantId).map(value => this.deterministicDto(ctx, this.row(ctx, String(value.id), 'rag_eval_deterministic_runs'))), ...this.db.all("SELECT id FROM generic_resources WHERE tenant_id=? AND resource_type='rag_eval_runs' AND deleted_at IS NULL ORDER BY created_at DESC,id LIMIT 100", ctx.tenantId).filter(value => !!object(this.db.read('generic_resources', String(value.id))?.data).checkpoint_id).map(value => this.status(ctx, String(value.id)))].sort((left, right) => String(right.created_at || '').localeCompare(String(left.created_at || ''))) };
  }
  report(ctx: AuthContext, id: string): JsonObject { this.auth.assertCan(ctx, 'read'); const legacy = this.legacy.find(ctx, id); if (legacy) return legacy; const row = this.row(ctx, id, 'rag_eval_reports'); return { ...object(row.data), report_id: id, freshness_status: object(row.data).run_id ? this.freshness(ctx, this.row(ctx, String(object(row.data).run_id), object(row.data).run_resource_type === 'rag_eval_deterministic_runs' ? 'rag_eval_deterministic_runs' : 'rag_eval_runs')) : 'unknown' }; }
  download(ctx: AuthContext, id: string): { bytes: Buffer; mimeType: string; filename: string } { this.auth.assertCan(ctx, 'export'); return { bytes: Buffer.from(JSON.stringify(this.report(ctx, id), null, 2)), mimeType: 'application/json; charset=utf-8', filename: `rag-evaluation-${id}.json` }; }
  deleteReport(ctx: AuthContext, id: string): JsonObject { this.auth.assertCan(ctx, 'eval.write'); if (this.legacy.find(ctx, id)) { this.legacy.delete(ctx, id); return { deleted: true, report_id: id }; } this.row(ctx, id, 'rag_eval_reports'); this.db.update('generic_resources', id, { deleted_at: now(), updated_at: now() }); return { deleted: true, report_id: id }; }
  publish(ctx: AuthContext, row: Row, metrics: JsonObject, context: JobContext): JsonObject {
    return context.publish(() => {
      this.auth.assertCan(ctx, 'eval.write'); if (this.freshness(ctx, row) !== 'current') return fail(409, 'evaluation_source_changed', 'Source changed during evaluation');
      const reportId = randomUUID(), data = object(row.data), report = { schema_version: 'evaluation_report_v2', run_id: String(row.id), report_id: reportId, created_at: now(), verification_status: 'verified', requested_configuration: data.requested_configuration!, effective_pipeline: data.effective_pipeline!, source_fingerprint: data.fingerprint!, metrics, report_hash: digest(metrics) };
      this.db.insert('generic_resources', { id: reportId, tenant_id: ctx.tenantId, resource_type: 'rag_eval_reports', name: 'RAG evaluation report', status: 'verified', data: report });
      this.db.update('generic_resources', String(row.id), { status: 'completed', updated_at: now(), data: { ...data, report_id: reportId, verification_status: 'verified', metrics } }); return { report_id: reportId, verification_status: 'verified' };
    });
  }
}
