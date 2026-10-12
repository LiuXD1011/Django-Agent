import { AppError } from '../errors.js';
import type { AuthContext, JsonObject } from '../contracts.js';
import type { AuthReader } from '../auth/reader.js';
import type { DocumentAttemptIdentity, DocumentQueuedIdentity } from '../jobs/attempt-control.js';
import { coreRequestUrl } from '../routing.js';
import type { CoreRequest } from '../contracts.js';
import type { ReadDatabase } from '../storage/read-database.js';

export type CancelTarget = { state: 'running'; identity: DocumentAttemptIdentity } | { state: 'terminal'; identity: DocumentAttemptIdentity | DocumentQueuedIdentity } | { state: 'queued'; identity: DocumentQueuedIdentity };
export type CancelProjection = { target: CancelTarget; noJob?: never } | { target?: never; noJob: JsonObject };
const matcher = /^\/api\/v1\/knowledge\/([^/]+)\/cancel-parse$/;
export function isDocumentCancelRequest(request: CoreRequest): boolean { return request.method === 'POST' && matcher.test(coreRequestUrl(request.path).pathname); }
const superseded = () => new AppError(409, 'document_attempt_superseded', '文档处理状态已改变，请刷新后重试。');

/** Private exact claim projection in the same readonly authentication snapshot. */
export function readCancelProjection(database: ReadDatabase, auth: AuthReader, context: AuthContext, request: CoreRequest): CancelProjection {
  const match = matcher.exec(coreRequestUrl(request.path).pathname);
  if (request.method !== 'POST' || !match) throw new AppError(404, 'not_found', '接口不存在。');
  let id: string;
  try { id = decodeURIComponent(match[1]!); } catch { throw new AppError(400, 'invalid_path', '请求路径编码不正确。'); }
  auth.assertCan(context, 'document.write');
  const doc = database.get("SELECT d.id,d.tenant_id,d.knowledge_base_id,d.parse_status,d.metadata -> '$.workflow_status' AS workflow_json,json_extract(d.metadata,'$.workflow_job_id') AS job_id FROM knowledges d JOIN knowledge_bases b ON b.id=d.knowledge_base_id AND b.tenant_id=d.tenant_id WHERE d.id=? AND d.tenant_id=? AND d.deleted_at IS NULL AND b.deleted_at IS NULL", id, context.tenantId);
  if (!doc) throw new AppError(404, 'knowledge_not_found', 'Document not found');
  if (typeof doc.job_id !== 'string' || !doc.job_id) return { noJob: { knowledge_id: id, task_id: '', status: String(JSON.parse(String(doc.workflow_json)) || doc.parse_status) } };
  const job = database.get(`SELECT id,tenant_id,user_id,kind,status,attempt,cancel_requested_at,
    json_extract(payload,'$.input.tenant_id') AS input_tenant,json_extract(payload,'$.input.knowledge_id') AS input_document,
    json_extract(payload,'$.input.knowledge_base_id') AS input_base,json_type(payload,'$.claim') AS claim_type,
    json_extract(payload,'$.claim.ownerToken') AS owner_token,json_extract(payload,'$.claim.leaseUntil') AS lease_until
    FROM desktop_jobs WHERE id=?`, doc.job_id);
  if (!job || job.kind !== 'process_knowledge' || String(job.tenant_id) !== context.tenantId || job.input_tenant !== context.tenantId || job.input_document !== id || job.input_base !== doc.knowledge_base_id) throw superseded();
  const attempt = Number(job.attempt);
  if (!Number.isSafeInteger(attempt) || attempt < 0 || typeof job.user_id !== 'string' || !job.user_id) throw superseded();
  const identity: DocumentQueuedIdentity = { jobId: String(job.id), previousAttempt: attempt, tenantId: context.tenantId, jobUserId: job.user_id, knowledgeId: id, knowledgeBaseId: String(doc.knowledge_base_id) };
  if (job.status === 'queued') {
    if (job.claim_type !== 'null' || job.cancel_requested_at !== null) throw superseded();
    return { target: { state: 'queued', identity } };
  }
  if (job.status === 'running') {
    if (attempt <= 0 || job.claim_type !== 'object' || typeof job.owner_token !== 'string' || !job.owner_token || typeof job.lease_until !== 'number' || job.lease_until <= Date.now()) throw superseded();
    return { target: { state: 'running', identity: { ...identity, previousAttempt: attempt - 1, attempt, ownerToken: job.owner_token } } };
  }
  if (!['completed', 'cancelled', 'failed', 'interrupted'].includes(String(job.status))) throw superseded();
  // Recovered terminal rows may have no claim. The owner still returns their
  // durable status, and this preflight never registers a new running attempt.
  if (job.claim_type === 'null') return { target: { state: 'terminal', identity } };
  if (attempt <= 0 || typeof job.owner_token !== 'string' || !job.owner_token) throw superseded();
  return { target: { state: 'terminal', identity: { ...identity, previousAttempt: attempt - 1, attempt, ownerToken: job.owner_token } } };
}
