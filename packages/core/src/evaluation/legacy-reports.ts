import { existsSync, lstatSync, readFileSync, readdirSync } from 'node:fs';
import { join, resolve } from 'node:path';
import type { AuthContext, Json, JsonObject } from '../contracts.js';
import type { CoreDatabase } from '../storage/database.js';
import { digest, object, now } from './common.js';
const contentKeys = new Set(['answer', 'content', 'context', 'contexts', 'ground_truth', 'file_path', 'question', 'query', 'prompt', 'input', 'raw_error', 'traceback']);
function sanitize(value: Json, depth = 0): Json {
  if (depth > 32) return null;
  if (Array.isArray(value)) return value.map(item => sanitize(item, depth + 1));
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).filter(([key, item]) => !contentKeys.has(key.toLowerCase()) && !(key === 'source' && typeof item === 'string')).map(([key, item]) => [key, /api_key|token|password|secret|credential|authorization/i.test(key) ? '******' : sanitize(item, depth + 1)]));
  return value;
}
/** Compatibility is read-only: deleting an old cache report creates a tenant-scoped tombstone in the new DB. */
export class LegacyEvaluationReports {
  constructor(readonly db: CoreDatabase, readonly cacheRoot = join(db.dataRoot, '.cache')) {}
  private marker(ctx: AuthContext, id: string): string { return `eval-legacy-${digest([ctx.tenantId, id])}`; }
  hidden(ctx: AuthContext, id: string): boolean { const marker = this.db.read('generic_resources', this.marker(ctx, id)); return !!marker && String(marker.tenant_id) === ctx.tenantId && marker.resource_type === 'rag_eval_legacy_tombstones'; }
  list(ctx: AuthContext): JsonObject[] {
    const values: JsonObject[] = [];
    for (const item of this.db.all("SELECT id FROM generic_resources WHERE tenant_id=? AND resource_type='rag_eval_runs' AND deleted_at IS NULL ORDER BY created_at DESC", ctx.tenantId)) {
      const row = this.db.read('generic_resources', String(item.id))!, data = object(row.data);
      if (!data.checkpoint_id) values.push({ ...data, report_id: String(data.report_id || row.id), created_at: row.created_at! });
    }
    if (/^[a-zA-Z0-9_-]{1,128}$/.test(ctx.tenantId)) {
      const directory = join(resolve(this.cacheRoot), 'eval-reports', ctx.tenantId);
      if (existsSync(directory) && lstatSync(directory).isDirectory() && !lstatSync(directory).isSymbolicLink()) {
        const names = readdirSync(directory).filter(name => /^[a-zA-Z0-9_.-]+\.json$/.test(name)).sort();
        for (const name of names.slice(0, 10000)) {
          try { const path = join(directory, name), stat = lstatSync(path); if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 16 * 1024 * 1024) continue; const raw = object(JSON.parse(readFileSync(path, 'utf8'))); values.push({ ...raw, report_id: String(raw.report_id || raw.run_id || name.slice(0, -5)) }); } catch {}
        }
      }
    }
    const seen = new Set<string>(); return values.filter(item => { const id = String(item.report_id); if (seen.has(id) || this.hidden(ctx, id) || !/^[a-zA-Z0-9_.-]{1,128}$/.test(id)) return false; seen.add(id); return true; }).map(item => {
      const safe = object(sanitize(item)), status = ['verified', 'degraded', 'unverified', 'failed'].includes(String(safe.verification_status)) ? String(safe.verification_status) : safe.verified === true ? 'verified' : 'unverified';
      return { ...safe, verification_status: status, freshness_status: 'unknown', legacy_import: true, report_url: `/api/v1/rag-eval/reports/${safe.report_id}`, available: true, created_at: safe.created_at ?? object(safe.provenance).created_at ?? null };
    });
  }
  find(ctx: AuthContext, id: string): JsonObject | undefined { return this.list(ctx).find(item => item.report_id === id); }
  delete(ctx: AuthContext, id: string): void { const marker = this.marker(ctx, id); if (!this.db.read('generic_resources', marker)) this.db.insert('generic_resources', { id: marker, tenant_id: ctx.tenantId, resource_type: 'rag_eval_legacy_tombstones', name: 'Hidden legacy evaluation report', status: 'deleted', data: { report_id: id, deleted_at: now() } }); }
}
