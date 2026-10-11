import { createHash, randomUUID } from 'node:crypto';
import { existsSync, unlinkSync } from 'node:fs';
import type { AuthContext, JsonObject } from '../contracts.js';
import { fileHash, safeDataPath } from '../storage/files.js';
import type { Row } from '../storage/database.js';
import { object } from './config.js';
import { KnowledgeDomain, now, warning, type Warning } from './domain.js';

interface Artifact extends JsonObject { path: string; sha256: string; document_id: string }
const fingerprint = (row: Row) => createHash('sha256').update(JSON.stringify(row)).digest('hex');
/** Explicit ownership and expected hashes are mandatory, including for old imported source files. */
export function planCleanup(domain: KnowledgeDomain, ctx: AuthContext, docs: Row[], includeSources: boolean): string | undefined {
  const files: Artifact[] = [];
  for (const d of docs) {
    if (includeSources && object(d.metadata).storage_owned === true && d.file_path) files.push({ path: String(d.file_path), sha256: String(d.file_hash), document_id: String(d.id) });
    for (const id of domain.db.all('SELECT id FROM knowledge_images WHERE tenant_id=? AND knowledge_base_id=? AND knowledge_id=?', ctx.tenantId, String(d.knowledge_base_id), String(d.id))) {
      const image = domain.db.read('knowledge_images', String(id.id))!;
      if (image.storage_owned === true && image.storage_path) files.push({ path: String(image.storage_path), sha256: String(image.content_hash), document_id: String(d.id) });
    }
  }
  if (!files.length) return undefined;
  const key = `knowledge.cleanup:${randomUUID()}`;
  domain.db.run('INSERT INTO desktop_meta(key,value) VALUES(?,?)', key, JSON.stringify({ tenant_id: ctx.tenantId, document_ids: docs.map(d => String(d.id)), files, created_at: now() }));
  return key;
}
/** Seal against the final retirement rows in the same transaction as the manifest. */
export function sealCleanup(domain: KnowledgeDomain, key?: string): void {
  if (!key) return;
  const plan = domain.db.get('SELECT value FROM desktop_meta WHERE key=?', key); if (!plan) return;
  const value = object(JSON.parse(String(plan.value))), snapshots: JsonObject = {};
  for (const id of Array.isArray(value.document_ids) ? value.document_ids : []) {
    const row = domain.db.read('knowledges', String(id)); if (row) snapshots[String(id)] = fingerprint(row);
  }
  domain.db.run('UPDATE desktop_meta SET value=? WHERE key=?', JSON.stringify({ ...value, schema_version: 1, document_snapshots: snapshots }), key);
}
export function recoverCleanup(domain: KnowledgeDomain, ctx: AuthContext, key?: string): Warning[] {
  domain.assert(ctx, 'document.delete'); const warnings: Warning[] = [];
  const plans = key ? domain.db.all('SELECT key,value FROM desktop_meta WHERE key=?', key) : domain.db.all("SELECT key,value FROM desktop_meta WHERE key LIKE 'knowledge.cleanup:%'");
  for (const plan of plans) {
    const value = object(JSON.parse(String(plan.value))); if (value.tenant_id !== ctx.tenantId) continue;
    const docIds = Array.isArray(value.document_ids) ? value.document_ids.map(String) : [], pending: Artifact[] = [];
    for (const entry of Array.isArray(value.files) ? value.files : []) {
      const file = object(entry) as Artifact;
      try {
        domain.db.transaction(() => {
          domain.assert(ctx, 'document.delete');
          const doc = domain.db.read('knowledges', file.document_id);
          if (!doc || String(doc.tenant_id) !== ctx.tenantId) throw new Error('ownership');
          if (object(value.document_snapshots)[file.document_id] !== fingerprint(doc)) throw new Error('changed');
          if (doc.deleted_at === null && domain.db.get('SELECT id FROM knowledge_images WHERE knowledge_id=? AND storage_path=?', file.document_id, file.path)) throw new Error('live');
          // A resumed document retaining a source path must never lose its source.
          if (doc.deleted_at === null && doc.file_path === file.path) throw new Error('live');
          const placeholders = docIds.map(() => '?').join(',') || "''";
          const shared = domain.db.get(`SELECT id FROM knowledges WHERE file_path=? AND id NOT IN (${placeholders}) LIMIT 1`, file.path, ...docIds) || domain.db.get('SELECT id FROM knowledge_images WHERE storage_path=? LIMIT 1', file.path);
          if (shared) { warnings.push(warning('shared_file_retained', 'artifacts', 'A shared media file was retained')); return; }
          if (!file.path.replaceAll('\\', '/').startsWith('media/') || !/^[a-f0-9]{64}$/.test(file.sha256)) throw new Error('ownership');
          const path = safeDataPath(domain.db.dataRoot, file.path);
          if (existsSync(path)) { if (fileHash(path) !== file.sha256) throw new Error('changed'); unlinkSync(path); }
        });
      } catch { pending.push(file); warnings.push(warning('artifact_cleanup_pending', 'artifacts', 'Media cleanup requires review or retry; a changed or unsafe file was retained')); }
    }
    if (pending.length) domain.db.run('UPDATE desktop_meta SET value=? WHERE key=?', JSON.stringify({ ...value, files: pending }), String(plan.key));
    else domain.db.run('DELETE FROM desktop_meta WHERE key=?', String(plan.key));
  }
  return warnings;
}
