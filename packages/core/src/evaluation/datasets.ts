import { randomUUID } from 'node:crypto';
import type { AuthContext, JsonObject } from '../contracts.js';
import type { AuthService } from '../auth/index.js';
import type { CoreDatabase, Row } from '../storage/database.js';
import { clone, digest, fail, now, object, text } from './common.js';
import { sampledIndices } from './selection.js';

export class EvaluationDatasets {
  constructor(readonly db: CoreDatabase, readonly auth: AuthService) {}
  /** Core startup only: an earlier process cannot confirm its unfinished paid request. Never retries it. */
  recoverGeneration(): void {
    this.db.transaction(() => {
      for (const item of this.db.all("SELECT id FROM generic_resources WHERE resource_type IN ('rag_eval_datasets','rag_eval_testsets') AND status='draft' AND deleted_at IS NULL")) {
        const row = this.db.read('generic_resources', String(item.id))!, data = object(row.data), generation = object(data.generation);
        if (generation.status !== 'running') continue;
        this.db.update('generic_resources', String(row.id), { data: { ...data, generation: { ...generation, status: 'interrupted', error_code: 'paid_result_unknown', result_unknown: true } }, updated_at: now() });
      }
    });
  }
  kb(ctx: AuthContext, id: string): Row {
    this.auth.assertCan(ctx, 'read'); const kb = this.db.read('knowledge_bases', id);
    if (!kb || kb.deleted_at !== null || String(kb.tenant_id) !== ctx.tenantId) return fail(404, 'knowledge_base_not_found', 'Knowledge base not found');
    return kb;
  }
  row(ctx: AuthContext, id: string): Row {
    this.auth.assertCan(ctx, 'read'); const row = this.db.read('generic_resources', id);
    if (!row || row.deleted_at !== null || String(row.tenant_id) !== ctx.tenantId || !['rag_eval_datasets', 'rag_eval_testsets'].includes(String(row.resource_type))) return fail(404, 'dataset_not_found', 'Evaluation dataset not found');
    return row;
  }
  private mutable(ctx: AuthContext, id: string, generation = false): Row { this.auth.assertCan(ctx, 'eval.write'); const row = this.row(ctx, id); if (row.status === 'published') return fail(409, 'dataset_immutable', 'Published datasets are immutable; create a new version'); if (!generation && object(object(row.data).generation).status === 'running') return fail(409, 'dataset_generating', 'Candidate generation is still running'); return row; }
  validation(ctx: AuthContext, entry: JsonObject, kbId: string): string[] {
    this.kb(ctx, kbId); const errors = new Set<string>();
    if (typeof entry.question !== 'string' || !entry.question.trim() || Array.from(entry.question).length > 16384) errors.add('question');
    if (typeof entry.answer !== 'string' || !entry.answer.trim() || typeof entry.reference_answer !== 'string' || !entry.reference_answer.trim() || Array.from(entry.answer).length > 16384 || Array.from(entry.reference_answer).length > 16384) errors.add('answer');
    if (!Array.isArray(entry.evidence) || !entry.evidence.length || entry.evidence.length > 50) return [...errors, 'evidence'];
    for (const raw of entry.evidence) {
      const item = object(raw), chunk = this.db.read('chunks', String(item.chunk_id || ''));
      if (!chunk || chunk.deleted_at !== null || String(chunk.tenant_id) !== ctx.tenantId || chunk.knowledge_base_id !== kbId || chunk.is_enabled !== true) { errors.add('evidence'); continue; }
      const doc = this.db.read('knowledges', String(chunk.knowledge_id)), start = item.source_start, end = item.source_end;
      if (!doc || doc.deleted_at !== null || doc.enable_status !== 'enabled' || String(doc.tenant_id) !== ctx.tenantId || doc.knowledge_base_id !== kbId || item.knowledge_id !== chunk.knowledge_id) { errors.add('evidence'); continue; }
      if (typeof start !== 'number' || typeof end !== 'number' || !Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < Number(chunk.start_at) || end > Number(chunk.end_at) || start >= end) { errors.add('source_span'); continue; }
      const meta = object(doc.metadata), source = typeof meta.content === 'string' ? meta.content : typeof object(meta.parser_document).canonical_text === 'string' ? String(object(meta.parser_document).canonical_text) : undefined;
      if (source === undefined) errors.add('canonical_source');
      if (source !== undefined && end > Array.from(source).length) errors.add('source_span');
      if (item.file_hash !== undefined && item.file_hash !== doc.file_hash || item.source_generation !== undefined && item.source_generation !== (meta.source_generation ?? null)) errors.add('document_version');
      if (typeof item.source_quote === 'string' && (source === undefined || item.source_quote !== Array.from(source).slice(start, end).join(''))) errors.add('source_quote');
    }
    return [...errors].sort();
  }
  private normalize(ctx: AuthContext, raw: unknown, kbId: string, mode: string, index: number): JsonObject {
    const input = object(raw), evidence = Array.isArray(input.evidence) ? clone(input.evidence) : [];
    const answer = typeof input.answer === 'string' ? input.answer : String(input.reference_answer || input.ground_truth || '');
    for (const row of evidence) {
      if (!row || typeof row !== 'object' || Array.isArray(row)) continue;
      const chunk = this.db.read('chunks', String(row.chunk_id || '')), doc = chunk ? this.db.read('knowledges', String(chunk.knowledge_id)) : undefined;
      if (chunk && doc && String(chunk.tenant_id) === ctx.tenantId && chunk.knowledge_base_id === kbId && String(doc.tenant_id) === ctx.tenantId && doc.knowledge_base_id === kbId) {
        row.knowledge_id ??= String(chunk.knowledge_id); row.file_hash ??= String(doc.file_hash || '');
        const generation = object(doc.metadata).source_generation; if (generation !== undefined) row.source_generation ??= generation;
      }
    }
    const item: JsonObject = { schema_version: 'evaluation_v2', id: typeof input.id === 'string' && input.id.length <= 128 && input.id ? input.id : randomUUID(), question: input.question ?? '', answer,
      reference_answer: input.reference_answer ?? input.ground_truth ?? answer, ground_truth: input.ground_truth ?? input.reference_answer ?? answer,
      question_type: ['simple', 'reasoning', 'multi-context'].includes(String(input.question_type)) ? input.question_type! : 'simple', evidence,
      documents: evidence.filter(value => value && typeof value === 'object' && !Array.isArray(value) && value.knowledge_id).map(value => ({ knowledge_id: object(value).knowledge_id!, file_hash: object(value).file_hash ?? '', source_generation: object(value).source_generation ?? null })),
      review_sampled: false };
    item.validation_errors = this.validation(ctx, item, kbId);
    item.status = mode === 'manual' ? 'pending_review' : (item.validation_errors as string[]).length ? 'rejected' : 'approved';
    return item;
  }
  private data(entries: JsonObject[], existing: JsonObject): JsonObject {
    return { ...existing, entries, dataset_hash: digest(entries.map(entry => ({ id: entry.id!, question: entry.question!, reference_answer: entry.reference_answer!, documents: entry.documents!, evidence: entry.evidence! }))),
      review_summary: { total: entries.length, approved: entries.filter(entry => entry.status === 'approved').length, rejected: entries.filter(entry => entry.status === 'rejected').length, pending: entries.filter(entry => entry.status === 'pending_review').length } };
  }
  dto(row: Row): JsonObject {
    const data = object(row.data), entries = Array.isArray(data.entries) ? data.entries : [];
    return clone({ id: String(row.id), name: String(row.name), status: String(row.status), review_mode: data.review_mode ?? 'manual', question_types: data.question_types ?? [], knowledge_base_id: data.knowledge_base_id ?? '', schema_version: data.schema_version ?? 'legacy', version: data.version ?? 1, dataset_hash: data.dataset_hash ?? '', published_at: data.published_at ?? null, review_summary: data.review_summary ?? {}, entries, generated: entries.length, generation: data.generation ?? null, created_at: String(row.created_at), updated_at: String(row.updated_at) });
  }
  list(ctx: AuthContext, kind = 'datasets'): JsonObject {
    this.auth.assertCan(ctx, 'read'); const type = kind === 'testsets' ? 'rag_eval_testsets' : 'rag_eval_datasets';
    return { [kind === 'testsets' ? 'testsets' : 'datasets']: this.db.all('SELECT id FROM generic_resources WHERE tenant_id=? AND resource_type=? AND deleted_at IS NULL ORDER BY created_at DESC,id', ctx.tenantId, type).map(row => this.dto(this.row(ctx, String(row.id)))) };
  }
  create(ctx: AuthContext, input: JsonObject, type = 'rag_eval_datasets'): JsonObject {
    this.auth.assertCan(ctx, 'eval.write'); const kbId = String(input.knowledge_base_id || ''); this.kb(ctx, kbId);
    const mode = String(input.review_mode || 'auto'); if (!['auto', 'manual', 'sample'].includes(mode)) return fail(400, 'invalid_review_mode', 'Unsupported review mode');
    if (!Array.isArray(input.entries) || input.entries.length > 100 || Buffer.byteLength(JSON.stringify(input)) > 2 * 1024 * 1024) return fail(400, 'invalid_evaluation_input', 'A bounded candidate entries array is required');
    const sampled = new Set(mode === 'sample' ? sampledIndices(input.entries.length, Math.ceil(input.entries.length / 10)) : []);
    const entries: JsonObject[] = input.entries.map((entry, index) => ({ ...this.normalize(ctx, entry, kbId, mode, index), review_sampled: sampled.has(index) }));
    if (new Set(entries.map(entry => entry.id)).size !== entries.length) return fail(400, 'duplicate_entry_id', 'Candidate entry IDs must be unique');
    const data = this.data(entries, { schema_version: 'evaluation_v2', version: 1, review_mode: mode, knowledge_base_id: kbId, published_at: null, question_types: input.question_types ?? [] });
    return this.dto(this.db.insert('generic_resources', { tenant_id: ctx.tenantId, resource_type: type, name: text(input.name || 'RAG evaluation dataset', 255), status: 'draft', data }));
  }
  edit(ctx: AuthContext, id: string, entryId: string, patch: JsonObject): JsonObject {
    return this.db.transaction(() => {
      const row = this.mutable(ctx, id), data = object(row.data), entries = clone(data.entries as JsonObject[]), index = entries.findIndex(entry => entry.id === entryId);
      if (index < 0) return fail(404, 'dataset_entry_not_found', 'Candidate entry not found');
      if (!Object.keys(patch).length || Object.keys(patch).some(key => !['question', 'answer', 'reference_answer', 'ground_truth', 'evidence', 'question_type'].includes(key))) return fail(400, 'invalid_evaluation_input', 'Unsupported candidate field');
      const value = { ...entries[index], ...patch }; if (patch.answer !== undefined && patch.reference_answer === undefined) value.reference_answer = patch.answer;
      const entry = this.normalize(ctx, value, String(data.knowledge_base_id), 'manual', index); entries[index] = entry;
      this.db.update('generic_resources', id, { data: this.data(entries, data), updated_at: now() }); return this.dto(this.row(ctx, id));
    });
  }
  /** Trusted generator only; each candidate has its own scoped atomic publication. */
  startGeneration(ctx: AuthContext, id: string, count: number): void {
    const row = this.mutable(ctx, id), data = object(row.data); this.kb(ctx, String(data.knowledge_base_id));
    this.db.update('generic_resources', id, { data: { ...data, generation: { status: 'running', requested_count: count, completed_count: 0, owner_user_id: ctx.userId, error_code: '', result_unknown: false } }, updated_at: now() });
  }
  appendGenerated(ctx: AuthContext, id: string, candidate: JsonObject): void {
    this.db.transaction(() => {
      const row = this.mutable(ctx, id, true), data = object(row.data), generation = object(data.generation);
      if (generation.owner_user_id !== ctx.userId || generation.status !== 'running') return fail(409, 'evaluation_generation_owner', 'Candidate generation owner or state changed');
      const entries = clone(data.entries as JsonObject[]), entry = this.normalize(ctx, candidate, String(data.knowledge_base_id), String(data.review_mode), entries.length);
      if ((entry.validation_errors as string[]).length) return fail(409, 'evaluation_source_changed', 'Generated source evidence changed');
      entries.push(entry); const sampled = new Set(data.review_mode === 'sample' ? sampledIndices(entries.length, Math.ceil(entries.length / 10)) : []);
      entries.forEach((value, index) => { value.review_sampled = sampled.has(index); });
      this.db.update('generic_resources', id, { data: this.data(entries, { ...data, generation: { ...generation, completed_count: entries.length } }), updated_at: now() });
    });
  }
  /** Terminal audit facts may be recorded after revocation; never appends business content. */
  finishGeneration(ctx: AuthContext, id: string, status: 'completed' | 'failed' | 'cancelled', errorCode = '', resultUnknown = false): void {
    const row = this.db.read('generic_resources', id), data = object(row?.data), generation = object(data.generation);
    if (!row || row.deleted_at !== null || row.status !== 'draft' || String(row.tenant_id) !== ctx.tenantId || !['rag_eval_datasets', 'rag_eval_testsets'].includes(String(row.resource_type)) || generation.owner_user_id !== ctx.userId || generation.status !== 'running') return;
    const safeCode = /^[a-z][a-z0-9_.-]{0,63}$/.test(errorCode) ? errorCode : '';
    this.db.update('generic_resources', id, { data: { ...data, generation: { ...generation, status, error_code: safeCode, result_unknown: resultUnknown } }, updated_at: now() });
  }
  delete(ctx: AuthContext, id: string, entryId: string): JsonObject {
    return this.db.transaction(() => { const row = this.mutable(ctx, id), data = object(row.data), entries = data.entries as JsonObject[], rest = entries.filter(entry => entry.id !== entryId); if (rest.length === entries.length) return fail(404, 'dataset_entry_not_found', 'Candidate entry not found'); this.db.update('generic_resources', id, { data: this.data(rest, data), updated_at: now() }); return this.dto(this.row(ctx, id)); });
  }
  review(ctx: AuthContext, id: string, input: JsonObject): JsonObject {
    return this.db.transaction(() => {
      const row = this.mutable(ctx, id), data = object(row.data), entries = clone(data.entries as JsonObject[]);
      if (!['approved', 'rejected', 'pending_review'].includes(String(input.status)) || !Array.isArray(input.entry_ids) || !input.entry_ids.length || input.entry_ids.some(value => typeof value !== 'string')) return fail(400, 'invalid_review', 'Review requires valid status and entry IDs');
      const selected = new Set(input.entry_ids); if ([...selected].some(value => !entries.some(entry => entry.id === value))) return fail(404, 'dataset_entry_not_found', 'Candidate entry not found');
      for (const entry of entries.filter(entry => selected.has(entry.id!))) { const errors = this.validation(ctx, entry, String(data.knowledge_base_id)); if (input.status === 'approved' && errors.length) return fail(422, 'unverified_eval_dataset', 'Candidate source evidence is invalid or stale'); entry.validation_errors = errors; entry.status = input.status!; }
      this.db.update('generic_resources', id, { data: this.data(entries, data), updated_at: now() });
      return input.publish === true ? this.publish(ctx, id) : this.dto(this.row(ctx, id));
    });
  }
  publish(ctx: AuthContext, id: string): JsonObject {
    return this.db.transaction(() => {
      const row = this.mutable(ctx, id), data = object(row.data), entries = (data.entries as JsonObject[]).filter(entry => entry.status === 'approved');
      if (!entries.length || entries.some(entry => this.validation(ctx, entry, String(data.knowledge_base_id)).length)) return fail(422, 'unverified_eval_dataset', 'Dataset has no valid approved entries');
      const published = this.data(entries, { ...data, published_at: now() });
      this.db.update('generic_resources', id, { status: 'published', data: published, updated_at: now() }); return this.dto(this.row(ctx, id));
    });
  }
  version(ctx: AuthContext, id: string): JsonObject {
    this.auth.assertCan(ctx, 'eval.write'); const row = this.row(ctx, id), data = clone(object(row.data));
    if (row.status !== 'published') return fail(409, 'dataset_not_published', 'Only a published dataset can create a new version');
    data.version = Number(data.version || 1) + 1; data.parent_dataset_id = id; data.published_at = null; data.review_mode = 'manual';
    const entries = (data.entries as JsonObject[]).map(entry => ({ ...entry, status: 'pending_review' }));
    return this.dto(this.db.insert('generic_resources', { tenant_id: ctx.tenantId, resource_type: row.resource_type, name: row.name, status: 'draft', data: this.data(entries, data) }));
  }
}
