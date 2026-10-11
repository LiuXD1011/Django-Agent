import type { Json, JsonObject } from '../contracts.js';
import type { CoreDatabase, Row } from '../storage/database.js';
export interface JobScope { tenantId: string; userId: string }
export class JobError extends Error {
  constructor(readonly status: number, readonly code: string, message: string) { super(message); this.name = 'JobError'; }
}
export function notFound(): never { throw new JobError(404, 'not_found', 'Resource not found'); }
export function freezeJson<T extends Json>(value: T): T {
  function check(v: unknown): void {
    if (v === null || typeof v === 'string' || typeof v === 'boolean') return;
    if (typeof v === 'number' && Number.isFinite(v)) return;
    if (Array.isArray(v)) { for (const child of v) check(child); return; }
    if (v && typeof v === 'object' && Object.getPrototypeOf(v) === Object.prototype) { for (const child of Object.values(v)) check(child); return; }
    throw new JobError(400, 'invalid_json', 'Expected finite JSON data');
  }
  try { check(value); return JSON.parse(JSON.stringify(value)) as T; } catch (error) { if (error instanceof JobError) throw error; throw new JobError(400, 'invalid_json', 'Expected finite JSON data'); }
}
export function decoded(row: Row): Row {
  const result = { ...row };
  for (const key of ['payload', 'result', 'data']) if (typeof result[key] === 'string') result[key] = JSON.parse(result[key]);
  return result;
}
export function sessionFor(db: CoreDatabase, id: string, scope: JobScope): Row {
  const s = db.read('sessions', id);
  if (!scope.userId || !s || s.deleted_at != null || String(s.tenant_id) !== scope.tenantId || String(s.user_id) !== scope.userId) notFound();
  return s;
}
export function messageFor(db: CoreDatabase, id: string, scope: JobScope): Row {
  const m = db.read('messages', id); if (!m || m.deleted_at != null) notFound();
  sessionFor(db, String(m.session_id), scope); return m;
}
export const object = (value: Json | undefined): JsonObject => value && typeof value === 'object' && !Array.isArray(value) ? value : {};
