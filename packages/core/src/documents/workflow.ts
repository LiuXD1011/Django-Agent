import { randomUUID } from 'node:crypto';
import { extname } from 'node:path';
import type { AuthService } from '../auth/index.js';
import type { AuthContext, JsonObject } from '../contracts.js';
import { AppError } from '../errors.js';
import type { Job, JobContext, JobQueue } from '../jobs/queue.js';
import { effectiveChunking, input, object } from '../knowledge/config.js';
import { SearchIndex } from '../retrieval/search-index.js';
import type { ModelConfigurationService } from '../settings/model-configuration.js';
import type { CoreDatabase, Row } from '../storage/database.js';
import { publicParameters } from '../storage/credentials.js';
import type { DocumentParser } from './parser.js';
import { ChunkingWorkers } from './chunking-workers.js';
import { executePipeline, mayCallModel, embeddingBinding, type PipelineHost, type WorkflowHook } from './pipeline.js';
import { digest, readControlled, removeOwned, writeOwned } from './workflow/files.js';
export type { WorkflowHook, WorkflowHookContext, WorkflowHookResult } from './pipeline.js';
export interface OwnedSourceReference {
    readonly kind: 'owned_source';
    readonly id: string;
}
export interface DocumentUpload {
    name: string;
    bytes?: Uint8Array;
    source?: OwnedSourceReference;
    tag_id?: string;
    process_config?: JsonObject;
}
export interface DocumentWorkflowResult {
    knowledge: JsonObject;
    task_id: string;
    repeated: boolean;
}
export interface OwnedSource {
    name: string;
    bytes: Buffer;
    mimeType: string;
    sha256: string;
    source: OwnedSourceReference;
}
export interface DocumentMedia {
    name: string;
    bytes: Buffer;
    mimeType: string;
    sha256: string;
}
export interface DocumentWorkflowOptions {
    parser: DocumentParser;
    index?: SearchIndex;
    scheduler?: (jobId: string) => void | Promise<unknown>;
    hooks?: {
        graph?: WorkflowHook;
        wiki?: WorkflowHook;
    };
    maxUploadBytes?: number;
}
interface Registration {
    current: DocumentWorkflow;
}
const registrations = new WeakMap<JobQueue, Registration>();
const kind = 'process_knowledge';
const now = () => new Date().toISOString();
function fail(status: number, code: string, message: string): never { throw new AppError(status, code, message); }
const mime = (name: string) => ({ png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif', webp: 'image/webp', pdf: 'application/pdf', csv: 'text/csv', md: 'text/markdown', txt: 'text/plain' }[extname(name).slice(1).toLowerCase()] ?? 'application/octet-stream');
/** Core-only service. Callers must pass an AuthService-issued context; no renderer path is accepted. */
export class DocumentWorkflow implements PipelineHost {
    readonly parser: DocumentParser;
    readonly chunker = new ChunkingWorkers();
    readonly index: SearchIndex;
    readonly hooks?: DocumentWorkflowOptions['hooks'];
    private readonly options: DocumentWorkflowOptions;
    private readonly references = new WeakMap<OwnedSourceReference, {
        knowledgeId: string;
        tenantId: string;
        hash: string;
    }>();
    private readonly handlers = new Map<string, Set<Promise<unknown>>>();
    private readonly scheduled = new Set<Promise<unknown>>();
    private closed = false;
    constructor(readonly db: CoreDatabase, readonly auth: AuthService, readonly jobs: JobQueue, readonly models: ModelConfigurationService, _knowledge?: unknown, options?: DocumentWorkflowOptions) {
        if (!options?.parser)
            fail(400, 'parser_required', 'Document parser must be configured');
        this.options = options;
        this.parser = options.parser;
        this.index = options.index ?? new SearchIndex(db);
        this.hooks = options.hooks;
        if (options.maxUploadBytes !== undefined && (!Number.isSafeInteger(options.maxUploadBytes) || options.maxUploadBytes < 1 || options.maxUploadBytes > 64 * 1024 * 1024))
            fail(400, 'upload_limit_invalid', 'Upload byte limit is outside parser limits');
        const previous = registrations.get(jobs);
        if (previous) {
            if (!previous.current.closed)
                fail(409, 'workflow_exists', 'A document workflow already owns this queue');
            previous.current = this;
        }
        else {
            const registration = { current: this };
            registrations.set(jobs, registration);
            jobs.register(kind, (context, payload) => registration.current.handle(context, payload));
        }
    }
    private open(): void { if (this.closed)
        fail(503, 'workflow_closed', 'Document workflow is closed'); }
    private kb(ctx: AuthContext, id: string, write = false): Row {
        this.auth.assertCan(ctx, 'read');
        const row = this.db.read('knowledge_bases', id);
        if (!row || row.deleted_at !== null || String(row.tenant_id) !== ctx.tenantId)
            fail(404, 'knowledge_base_not_found', 'Knowledge base not found');
        if (write)
            this.auth.assertCan(ctx, 'document.write');
        return row;
    }
    private doc(ctx: AuthContext, id: string, write = false): Row {
        this.auth.assertCan(ctx, 'read');
        const row = this.db.read('knowledges', id);
        if (!row || row.deleted_at !== null || String(row.tenant_id) !== ctx.tenantId)
            fail(404, 'knowledge_not_found', 'Document not found');
        this.kb(ctx, String(row.knowledge_base_id), write);
        return row;
    }
    private dto(row: Row): JsonObject { return publicParameters(row); }
    private process(kb: Row, raw: unknown): JsonObject {
        const config = raw == null ? {} : input(raw), engine = config.parser_engine ?? '';
        if (typeof engine !== 'string' || !['', 'builtin', 'plain'].includes(engine))
            fail(400, 'invalid_process_config', 'Unsupported parser engine');
        for (const alias of ['chunking_config', 'chunkingConfig'])
            if (alias in config)
                input(config[alias]);
        effectiveChunking(kb.chunking_config, config);
        return structuredClone(config);
    }
    private tag(ctx: AuthContext, kbId: string, id: string): void {
        if (!id)
            return;
        const tag = this.db.read('knowledge_tags', id);
        if (!tag || tag.deleted_at !== null || String(tag.tenant_id) !== ctx.tenantId || tag.knowledge_base_id !== kbId)
            fail(404, 'tag_not_found', 'Tag not found in this knowledge base');
    }
    private request(ctx: AuthContext, requestId: string, identity: JsonObject): DocumentWorkflowResult | undefined {
        if (typeof requestId !== 'string' || !requestId || requestId.length > 128)
            fail(400, 'invalid_request_id', 'A bounded request identifier is required');
        const row = this.db.get('SELECT id FROM desktop_jobs WHERE request_id=?', requestId);
        if (!row) {
            const reference = this.db.get('SELECT value FROM desktop_meta WHERE key=?', `workflow.upload:${digest(requestId)}`);
            if (!reference)
                return;
            const saved = object(JSON.parse(String(reference.value)));
            if (saved.tenant_id !== ctx.tenantId || saved.user_id !== ctx.userId)
                fail(404, 'request_not_found', 'Request not found');
            if (JSON.stringify(saved.identity) !== JSON.stringify(identity))
                fail(409, 'request_conflict', 'Request already belongs to another operation');
            return { knowledge: this.dto(this.doc(ctx, String(saved.knowledge_id), true)), task_id: String(saved.task_id ?? ''), repeated: true };
        }
        const job = this.jobs.get(String(row.id), { tenantId: ctx.tenantId, userId: ctx.userId });
        if (job.kind !== kind || JSON.stringify(job.payload.identity) !== JSON.stringify(identity))
            fail(409, 'request_conflict', 'Request already belongs to another operation');
        const doc = this.doc(ctx, String(job.payload.knowledge_id), true);
        return { knowledge: this.dto(doc), task_id: job.id, repeated: true };
    }
    private create(ctx: AuthContext, doc: Row, config: JsonObject, requestId: string, identity: JsonObject): Job {
        const kb = this.kb(ctx, String(doc.knowledge_base_id), true);
        const paid = mayCallModel(this, ctx, kb, config);
        const job = this.jobs.create({ scope: { tenantId: ctx.tenantId, userId: ctx.userId }, requestId, kind, recoveryPolicy: paid ? 'manual' : 'safe', payload: { knowledge_id: doc.id!, knowledge_base_id: doc.knowledge_base_id!, tenant_id: ctx.tenantId, request_id: requestId, process_config: config, allow_model_calls: paid, identity, auth: { userId: ctx.userId, tenantId: ctx.tenantId, role: ctx.role, deviceId: ctx.deviceId, isSystemAdmin: ctx.isSystemAdmin } } });
        this.db.insert('task_records', { id: job.id, task_type: kind, status: job.status === 'cancelled' ? 'cancelled' : 'pending', payload: { tenant_id: ctx.tenantId, knowledge_id: doc.id!, knowledge_base_id: doc.knowledge_base_id!, job_id: job.id, user_id: ctx.userId }, queue_name: 'desktop' });
        const metadata = { ...object(doc.metadata), process_config: config, workflow_job_id: job.id, workflow_status: job.status === 'cancelled' ? 'cancelled' : 'pending' };
        this.db.update('knowledges', String(doc.id), { parse_status: doc.processed_at ? 'completed' : job.status === 'cancelled' ? 'cancelled' : 'pending', pending_subtasks_count: job.status === 'cancelled' ? 0 : 1, metadata, updated_at: now() });
        return job;
    }
    async upload(ctx: AuthContext, kbId: string, upload: DocumentUpload, requestId: string): Promise<DocumentWorkflowResult> {
        this.open();
        const kb = this.kb(ctx, kbId, true);
        if (!upload || typeof upload.name !== 'string' || !upload.name.trim() || upload.name.length > 255 || /[\/\\\0]/.test(upload.name) || upload.name === '.' || upload.name === '..')
            fail(400, 'invalid_file_name', 'A bounded filename is required');
        if ((upload.bytes !== undefined) === (upload.source !== undefined))
            fail(400, 'invalid_source', 'Provide uploaded bytes or a trusted owned source');
        let bytes: Buffer;
        if (upload.bytes !== undefined) {
            if (!(upload.bytes instanceof Uint8Array))
                fail(400, 'invalid_source', 'Upload must contain bytes');
            bytes = Buffer.from(upload.bytes);
        }
        else {
            const ref = upload.source!, owned = ref && this.references.get(ref);
            if (!owned || owned.tenantId !== ctx.tenantId)
                fail(400, 'invalid_source', 'Source must be issued by this workflow');
            const original = this.doc(ctx, owned.knowledgeId);
            if (original.file_hash !== owned.hash)
                fail(409, 'source_changed', 'Owned source changed');
            bytes = this.sourceBytes(original);
        }
        if (bytes.length > (this.options.maxUploadBytes ?? 64 * 1024 * 1024))
            fail(413, 'upload_limit_exceeded', 'Upload exceeds the supported byte limit');
        const config = this.process(kb, upload.process_config), tag = upload.tag_id ?? '';
        if (typeof tag !== 'string')
            fail(400, 'invalid_tag', 'Invalid tag');
        this.tag(ctx, kbId, tag);
        const hash = digest(bytes), identity: JsonObject = { operation: 'upload', knowledge_base_id: kbId, name: upload.name, hash, tag_id: tag, process_config: config };
        const retry = this.request(ctx, requestId, identity);
        if (retry)
            return retry;
        const existing = this.db.get("SELECT id FROM knowledges WHERE tenant_id=? AND knowledge_base_id=? AND type='file' AND file_name=? AND file_hash=? AND deleted_at IS NULL", ctx.tenantId, kbId, upload.name, hash);
        if (existing) {
            const doc = this.doc(ctx, String(existing.id), true), taskId = String(object(doc.metadata).workflow_job_id ?? '');
            this.db.transaction(() => this.db.run('INSERT INTO desktop_meta(key,value) VALUES(?,?)', `workflow.upload:${digest(requestId)}`, JSON.stringify({ tenant_id: ctx.tenantId, user_id: ctx.userId, identity, knowledge_id: doc.id, task_id: taskId })));
            return { knowledge: this.dto(doc), task_id: taskId, repeated: true };
        }
        const id = randomUUID(), suffix = extname(upload.name).slice(1).toLowerCase(), reference = `media/documents/${id}/source/${randomUUID()}${suffix ? '.' + suffix : ''}`;
        writeOwned(this.db.dataRoot, reference, bytes);
        let job: Job, doc: Row;
        try {
            ({ job, doc } = this.db.transaction(() => { this.open(); this.kb(ctx, kbId, true); this.tag(ctx, kbId, tag); const doc = this.db.insert('knowledges', { id, tenant_id: ctx.tenantId, knowledge_base_id: kbId, type: 'file', title: upload.name, source: upload.name, file_name: upload.name, file_type: suffix, file_size: bytes.length, file_path: reference, file_hash: hash, storage_size: bytes.length, embedding_model_id: kb.embedding_model_id ?? '', tag_id: tag, channel: 'desktop', metadata: { storage_owned: true, process_config: config }, parse_status: 'pending' }); const job = this.create(ctx, doc, config, requestId, identity); return { job, doc: this.db.read('knowledges', id)! }; }));
        }
        catch (error) {
            removeOwned(this.db.dataRoot, reference, hash);
            throw error;
        }
        this.dispatch(job!);
        return { knowledge: this.dto(doc!), task_id: job!.id, repeated: false };
    }
    async reparse(ctx: AuthContext, knowledgeId: string, processConfig?: JsonObject, requestId: string = randomUUID()): Promise<DocumentWorkflowResult> {
        this.open();
        const doc = this.doc(ctx, knowledgeId, true), kb = this.kb(ctx, String(doc.knowledge_base_id));
        if (doc.type !== 'file')
            fail(400, 'invalid_document_type', 'Only file documents can be reparsed');
        const config = this.process(kb, processConfig ?? object(doc.metadata).process_config ?? {}), identity: JsonObject = { operation: 'reparse', knowledge_id: knowledgeId, hash: doc.file_hash!, process_config: config };
        const retry = this.request(ctx, requestId, identity);
        if (retry)
            return retry;
        // Cancel the old attempt before changing the active job pointer; its valid content remains published.
        this.cancelJobs(ctx, doc);
        const job = this.db.transaction(() => this.create(ctx, this.doc(ctx, knowledgeId, true), config, requestId, identity));
        this.dispatch(job);
        return { knowledge: this.dto(this.doc(ctx, knowledgeId)), task_id: job.id, repeated: false };
    }
    private cancelJobs(ctx: AuthContext, doc: Row): string[] {
        const ids: string[] = [];
        for (const row of this.db.all("SELECT id,request_id,user_id,payload FROM desktop_jobs WHERE tenant_id=? AND kind=? AND status IN ('queued','running')", ctx.tenantId, kind)) {
            const payload = object(object(JSON.parse(String(row.payload))).input);
            if (payload.knowledge_id !== doc.id)
                continue;
            this.jobs.cancelByRequest(String(row.request_id), { tenantId: ctx.tenantId, userId: String(row.user_id) });
            ids.push(String(row.id));
            this.finishCancelled(String(row.id), String(doc.id));
        }
        return ids;
    }
    private finishCancelled(jobId: string, docId: string): void {
        const date = now();
        this.db.update('task_records', jobId, { status: 'cancelled', cancel_requested_at: date, claimed_by: '', lease_expires_at: null, updated_at: date });
        this.db.run("UPDATE knowledge_processing_spans SET status='cancelled',finished_at=?,duration_ms=max(0,cast((julianday(?)-julianday(started_at))*86400000 as integer)) WHERE knowledge_id=? AND status='running' AND json_extract(metadata,'$.job_id')=?", date, date, docId, jobId);
    }
    async cancel(ctx: AuthContext, knowledgeId: string, _requestId?: string): Promise<JsonObject> {
        const doc = this.doc(ctx, knowledgeId, true), ids = this.cancelJobs(ctx, doc);
        const meta = object(doc.metadata);
        this.db.transaction(() => { const current = this.doc(ctx, knowledgeId, true); this.db.update('knowledges', knowledgeId, { parse_status: current.processed_at ? 'completed' : 'cancelled', pending_subtasks_count: 0, metadata: { ...object(current.metadata), workflow_status: 'cancelled' }, updated_at: now() }); });
        await Promise.all(ids.flatMap(id => [...(this.handlers.get(id) ?? [])]).map(p => p.catch(() => undefined)));
        return { knowledge_id: knowledgeId, task_id: String(meta.workflow_job_id ?? ''), status: 'cancelled' };
    }
    stages(ctx: AuthContext, knowledgeId: string): JsonObject {
        this.doc(ctx, knowledgeId);
        const spans = this.db.all('SELECT id FROM knowledge_processing_spans WHERE knowledge_id=? ORDER BY attempt,started_at,id', knowledgeId).map(r => this.db.read('knowledge_processing_spans', String(r.id))!).map(r => ({ id: r.span_id!, parent_id: r.parent_span_id!, name: r.name!, kind: r.kind!, status: r.status!, attempt: r.attempt!, input: r.input_data!, output: r.output_data!, metadata: r.metadata!, error_code: r.error_code!, error_message: r.error_message!, started_at: r.started_at!, finished_at: r.finished_at!, duration_ms: r.duration_ms! }));
        return { knowledge_id: knowledgeId, spans };
    }
    private sourceBytes(doc: Row): Buffer { if (object(doc.metadata).storage_owned !== true)
        fail(409, 'source_not_owned', 'Source is not owned by this application'); return readControlled(this.db.dataRoot, String(doc.file_path), String(doc.file_hash), 64 * 1024 * 1024); }
    async readOwnedSource(ctx: AuthContext, knowledgeId: string): Promise<OwnedSource> {
        const doc = this.doc(ctx, knowledgeId), bytes = this.sourceBytes(doc), source = Object.freeze({ kind: 'owned_source' as const, id: randomUUID() });
        this.references.set(source, { knowledgeId, tenantId: ctx.tenantId, hash: String(doc.file_hash) });
        return { name: String(doc.file_name), bytes, mimeType: mime(String(doc.file_name)), sha256: String(doc.file_hash), source };
    }
    async getMedia(ctx: AuthContext, knowledgeId: string, imageId: string): Promise<DocumentMedia> {
        const doc = this.doc(ctx, knowledgeId), image = this.db.read('knowledge_images', imageId);
        if (!image || image.deleted_at !== null || String(image.tenant_id) !== ctx.tenantId || image.knowledge_id !== knowledgeId || image.knowledge_base_id !== doc.knowledge_base_id)
            fail(404, 'image_not_found', 'Document image not found');
        const bytes = readControlled(this.db.dataRoot, String(image.storage_path), String(image.content_hash));
        return { name: `${imageId}.${extname(String(image.storage_path)).slice(1)}`, bytes, mimeType: String(image.mime_type), sha256: String(image.content_hash) };
    }
    embeddingBinding(ctx: AuthContext, kbId: string) { const kb = this.kb(ctx, kbId); return embeddingBinding(this.models.configuration(ctx, String(kb.embedding_model_id || 'Embedding'))); }
    assertActive(ctx: AuthContext, job: JobContext, payload: JsonObject): Row {
        this.open();
        job.signal.throwIfAborted();
        const doc = this.doc(ctx, String(payload.knowledge_id), true);
        if (doc.knowledge_base_id !== payload.knowledge_base_id || object(doc.metadata).workflow_job_id !== job.jobId || object(doc.metadata).workflow_status === 'cancelled')
            fail(409, 'document_changed', 'Document changed during processing');
        return doc;
    }
    publish<T>(ctx: AuthContext, job: JobContext, payload: JsonObject, work: () => T): T { return job.publish(() => { this.assertActive(ctx, job, payload); return work(); }); }
    private handle(job: JobContext, payload: JsonObject): Promise<JsonObject> {
        this.open();
        const ctx = object(payload.auth) as unknown as AuthContext;
        const running = Promise.resolve().then(() => executePipeline(this, ctx, job, payload)).catch(error => {
            // Audit terminal telemetry even after user revocation. This owner fence can
            // finish its own task/spans, but never changes document content or new attempts.
            const unknown = error instanceof Error && 'resultUnknown' in error && error.resultUnknown === true;
            try {
                job.publish(() => this.finishAudit(job.jobId, String(payload.knowledge_id), job.attempt, unknown ? 'interrupted' : 'failed', unknown ? 'model_result_unknown' : 'document_processing_failed'));
            }
            catch {
                const row = this.db.get('SELECT status,attempt FROM desktop_jobs WHERE id=?', job.jobId);
                if (row && Number(row.attempt) === job.attempt && ['cancelled', 'interrupted', 'failed'].includes(String(row.status)))
                    this.db.transaction(() => this.finishAudit(job.jobId, String(payload.knowledge_id), job.attempt, String(row.status), 'document_processing_failed'));
            }
            throw error;
        });
        const executions = this.handlers.get(job.jobId) ?? new Set<Promise<unknown>>();
        executions.add(running);
        this.handlers.set(job.jobId, executions);
        void running.finally(() => { executions.delete(running); if (!executions.size && this.handlers.get(job.jobId) === executions)
            this.handlers.delete(job.jobId); }).catch(() => undefined);
        return running;
    }
    private finishAudit(jobId: string, docId: string, attempt: number, status: string, errorCode = ''): void {
        const date = now();
        this.db.run("UPDATE task_records SET status=?,error_message=?,claimed_by='',lease_expires_at=NULL,updated_at=? WHERE id=? AND status IN ('pending','running') AND json_extract(payload,'$.knowledge_id')=?", status, errorCode, date, jobId, docId);
        this.db.run("UPDATE knowledge_processing_spans SET status=?,error_code=?,error_message=?,finished_at=?,duration_ms=max(0,cast((julianday(?)-julianday(started_at))*86400000 as integer)) WHERE knowledge_id=? AND status='running' AND json_extract(metadata,'$.job_id')=? AND json_extract(metadata,'$.queue_attempt')=?", status, errorCode, errorCode, date, date, docId, jobId, attempt);
    }
    private dispatch(job: Job): void {
        if (this.closed || job.status !== 'queued')
            return;
        try {
            const result = this.options.scheduler ? this.options.scheduler(job.id) : this.jobs.run(job.id);
            if (result && typeof (result as Promise<unknown>).then === 'function') {
                const running = Promise.resolve(result).catch(() => this.schedulerFailed(job));
                this.scheduled.add(running);
                void running.finally(() => this.scheduled.delete(running)).catch(() => undefined);
            }
        }
        catch {
            this.schedulerFailed(job);
        }
    }
    private schedulerFailed(job: Job): void {
        if (this.closed)
            return;
        this.db.transaction(() => { const row = this.db.get('SELECT status FROM desktop_jobs WHERE id=?', job.id); if (row?.status !== 'queued')
            return; this.db.run("UPDATE desktop_jobs SET status='failed',error='Document scheduling failed',finished_at=?,updated_at=? WHERE id=? AND status='queued'", now(), now(), job.id); this.db.update('task_records', job.id, { status: 'failed', error_message: 'scheduling_failed', updated_at: now() }); const doc = this.db.read('knowledges', String(job.payload.knowledge_id)); if (doc && object(doc.metadata).workflow_job_id === job.id)
            this.db.update('knowledges', String(doc.id), { parse_status: doc.processed_at ? 'completed' : 'failed', pending_subtasks_count: 0, error_message: 'scheduling_failed', metadata: { ...object(doc.metadata), workflow_status: 'failed' }, updated_at: now() }); });
    }
    recover(): {
        safe: number;
        manual: number;
    } {
        this.open();
        const expired = this.db.all("SELECT id,tenant_id,attempt,payload FROM desktop_jobs WHERE kind=? AND status IN ('running','interrupted')", kind);
        const result = this.jobs.recover();
        for (const before of expired) {
            const payload = object(object(JSON.parse(String(before.payload))).input), docId = String(payload.knowledge_id);
            this.db.transaction(() => {
                const row = this.db.get('SELECT status,attempt FROM desktop_jobs WHERE id=?', String(before.id));
                if (!row || Number(row.attempt) !== Number(before.attempt) || !['queued', 'interrupted'].includes(String(row.status)))
                    return;
                this.finishAudit(String(before.id), docId, Number(before.attempt), 'interrupted', 'ownership_lost');
                if (row.status === 'queued')
                    this.db.update('task_records', String(before.id), { status: 'pending', error_message: '', updated_at: now() });
                const doc = this.db.read('knowledges', docId), meta = object(doc?.metadata);
                if (doc && doc.deleted_at === null && String(doc.tenant_id) === String(before.tenant_id)
                    && doc.knowledge_base_id === payload.knowledge_base_id && meta.workflow_job_id === before.id
                    && ['pending','processing'].includes(String(meta.workflow_status)))
                    this.db.update('knowledges', docId, {
                        parse_status: doc.processed_at ? 'completed' : row.status === 'queued' ? 'pending' : 'failed',
                        pending_subtasks_count: row.status === 'queued' ? 1 : 0,
                        error_message: row.status === 'queued' ? '' : '处理已中断，请手动重解析。',
                        metadata: { ...meta, workflow_status: row.status === 'queued' ? 'pending' : 'interrupted' }, updated_at: now(),
                    });
            });
        }
        for (const row of this.db.all("SELECT id,tenant_id,user_id FROM desktop_jobs WHERE kind=? AND status='queued' AND recovery_policy='safe'", kind))
            this.dispatch(this.jobs.get(String(row.id), { tenantId: String(row.tenant_id), userId: String(row.user_id) }));
        return result;
    }
    async close(): Promise<void> {
        if (!this.closed) {
            this.closed = true;
            for (const row of this.db.all("SELECT id,request_id,tenant_id,user_id,payload FROM desktop_jobs WHERE kind=? AND status IN ('queued','running')", kind)) {
                this.jobs.cancelByRequest(String(row.request_id), { tenantId: String(row.tenant_id), userId: String(row.user_id) });
                const docId = String(object(object(JSON.parse(String(row.payload))).input).knowledge_id);
                this.finishCancelled(String(row.id), docId);
                const doc = this.db.read('knowledges', docId);
                if (doc && object(doc.metadata).workflow_job_id === row.id)
                    this.db.update('knowledges', docId, { parse_status: doc.processed_at ? 'completed' : 'cancelled', pending_subtasks_count: 0, metadata: { ...object(doc.metadata), workflow_status: 'cancelled' }, updated_at: now() });
            }
        }
        await this.chunker.close();
        await Promise.allSettled([...this.handlers.values()].flatMap(promises => [...promises]).concat([...this.scheduled]));
    }
}
