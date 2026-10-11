import { createHash, randomUUID } from 'node:crypto';
import { constants } from 'node:fs';
import { lstat, mkdir, open, realpath, rm, unlink, type FileHandle } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import type { AuthContext, Json, JsonObject } from '../contracts.js';
import type { AuthService } from '../auth/index.js';
import type { CoreDatabase } from '../storage/database.js';
import type { DocumentParser } from '../documents/parser.js';
import { array, fail, object } from './internal.js';
import type { ChatExecution, ChatHooks } from './types.js';

const sha = (bytes: Uint8Array) => createHash('sha256').update(bytes).digest('hex');
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
const bounded = (value: number | undefined, fallback: number, max: number) => { const n = value ?? fallback; if (!Number.isSafeInteger(n) || n < 1 || n > max) fail(400, 'upload_limit_invalid', 'Invalid upload limit'); return n; };
async function readBounded(file: FileHandle, max: number): Promise<Buffer> { const parts: Buffer[] = []; let total = 0; while (true) { const buffer = Buffer.alloc(Math.min(65536, max - total + 1)); const { bytesRead } = await file.read(buffer, 0, buffer.length, null); if (!bytesRead) break; total += bytesRead; if (total > max) fail(413, 'upload_limit_exceeded', 'Upload exceeds byte limit'); parts.push(buffer.subarray(0, bytesRead)); } return Buffer.concat(parts, total); }
function name(value: unknown): string { if (typeof value !== 'string' || !value.trim() || value.length > 255 || /[\/\\\x00-\x1f]/.test(value) || ['.', '..'].includes(value)) fail(400, 'upload_name_invalid', 'Invalid upload name'); return value as string; }
function decoded(value: unknown, max: number): Buffer {
  if (typeof value !== 'string' || value.length > Math.ceil(max / 3) * 4 || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value)) fail(400, 'upload_data_invalid', 'Invalid uploaded base64 bytes');
  const bytes = Buffer.from(value as string, 'base64'); if (bytes.length > max) fail(413, 'upload_limit_exceeded', 'Upload exceeds byte limit'); return bytes;
}
function imageMime(bytes: Buffer): string {
  if (bytes.subarray(0, 8).equals(Buffer.from([137,80,78,71,13,10,26,10]))) return 'image/png';
  if (bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255) return 'image/jpeg';
  if (/^GIF8[79]a$/.test(bytes.subarray(0, 6).toString())) return 'image/gif';
  if (bytes.subarray(0,4).toString() === 'RIFF' && bytes.subarray(8,12).toString() === 'WEBP') return 'image/webp';
  if (bytes.subarray(0,2).toString() === 'BM') return 'image/bmp';
  if (bytes.subarray(0,4).equals(Buffer.from([73,73,42,0])) || bytes.subarray(0,4).equals(Buffer.from([77,77,0,42]))) return 'image/tiff';
  if (/^\s*(?:<\?xml[^>]*>\s*)?<svg(?:\s|>)/i.test(bytes.subarray(0,4096).toString('utf8'))) return 'image/svg+xml';
  return '';
}
export interface ChatUploadInput { name: string; bytes: Uint8Array; mimeType?: string; kind?: 'file' | 'image'; fileSize?: number }
export interface ChatUploadBytes { bytes: Buffer; name: string; mimeType: string; sha256: string }
/** Persisted manifests contain paths only in core-owned metadata. Renderer references are opaque UUIDs. */
export class ManagedChatUploads {
  readonly maxFileBytes: number; readonly root: string;
  constructor(readonly db: CoreDatabase, readonly auth: AuthService, options: { maxFileBytes?: number } = {}) { this.root = join(resolve(db.dataRoot), 'media', 'chat'); this.maxFileBytes = bounded(options.maxFileBytes, 24 * 1024 * 1024, 64 * 1024 * 1024); }
  private session(ctx: AuthContext, id: string, write = false, deleted = false) {
    this.auth.assertCan(ctx, write ? 'write' : 'read', ctx.tenantId, ctx.userId); const row = this.db.read('sessions', id);
    if (!ctx.userId || !row || (!deleted && row.deleted_at !== null) || row.user_id !== ctx.userId || String(row.tenant_id) !== ctx.tenantId) fail(404, 'upload_not_found', 'Upload not found'); return row!;
  }
  private key(id: string) { if (!uuid.test(id)) fail(404, 'upload_not_found', 'Upload not found'); return `chat.upload:${id}`; }
  private manifest(ctx: AuthContext, sessionId: string, id: string): JsonObject {
    this.session(ctx, sessionId); const row = this.db.get('select value from desktop_meta where key=?', this.key(id)), value = row ? object(JSON.parse(String(row.value))) : {};
    if (value.user_id !== ctx.userId || value.tenant_id !== ctx.tenantId || !array(value.session_ids).includes(sessionId) || value.state !== 'ready') fail(404, 'upload_not_found', 'Upload not found'); return value;
  }
  private async directory(path: string, create = false): Promise<void> {
    const base = resolve(this.db.dataRoot); if (await realpath(base) !== base) fail(400, 'upload_source_changed', 'Upload root changed');
    const pieces = path.slice(base.length + 1).split(/[\/\\]/); let current = base;
    if (!path.startsWith(base + '/') && !path.startsWith(base + '\\')) fail(400, 'upload_source_changed', 'Upload directory changed');
    for (const piece of pieces) { if (!piece || ['.', '..'].includes(piece)) fail(400, 'upload_source_changed', 'Upload directory changed'); current = join(current, piece); if (create) await mkdir(current, { mode: 0o700 }).catch((e: NodeJS.ErrnoException) => { if (e.code !== 'EEXIST') throw e; }); const info = await lstat(current).catch(() => fail(400, 'upload_source_changed', 'Upload directory changed')); if (!info.isDirectory() || info.isSymbolicLink() || await realpath(current) !== current) fail(400, 'upload_source_changed', 'Upload directory changed'); }
  }
  private path(id: string, manifest: JsonObject): string { const expected = `media/chat/${id}/source`; if (manifest.asset_path !== expected) fail(400, 'upload_source_changed', 'Upload source changed'); return join(this.root, id, 'source'); }
  private dto(id: string, m: JsonObject): JsonObject { return { upload_id: id, file_name: m.file_name!, file_size: m.file_size!, mime_type: m.mime_type!, sha256: m.sha256!, kind: m.kind! }; }
  async store(ctx: AuthContext, sessionId: string, input: ChatUploadInput, guard: () => void = () => {}): Promise<JsonObject> {
    this.session(ctx, sessionId, true); guard(); const fileName = name(input.name);
    if (!(input.bytes instanceof Uint8Array)) fail(400, 'upload_data_invalid', 'Uploaded bytes are required'); const bytes = Buffer.from(input.bytes);
    if (bytes.length > this.maxFileBytes) fail(413, 'upload_limit_exceeded', 'Upload exceeds byte limit');
    if (input.fileSize !== undefined && input.fileSize !== bytes.length) fail(400, 'upload_size_mismatch', 'Upload size differs from its bytes');
    const mime = input.kind === 'image' ? imageMime(bytes) : input.mimeType ?? 'application/octet-stream'; if (input.kind === 'image' && !mime) fail(400, 'image_format_invalid', 'Uploaded image bytes are invalid');
    const id = randomUUID(), directory = join(this.root, id), path = join(directory, 'source'); await this.directory(directory, true); guard();
    const file = await open(path, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | (constants.O_NOFOLLOW ?? 0), 0o600);
    try { await file.writeFile(bytes); await file.sync(); } finally { await file.close(); }
    try {
      await this.directory(directory); guard(); const m: JsonObject = { tenant_id: ctx.tenantId, user_id: ctx.userId, session_ids: [sessionId], asset_path: `media/chat/${id}/source`, file_name: fileName, file_size: bytes.length, mime_type: mime, sha256: sha(bytes), kind: input.kind ?? 'file', state: 'ready' };
      this.db.transaction(() => { guard(); this.session(ctx, sessionId, true); this.db.run('insert into desktop_meta(key,value) values(?,?)', this.key(id), JSON.stringify(m)); }); return this.dto(id, m);
    } catch (error) { await unlink(path).catch(() => {}); await rm(directory, { recursive: true, force: true }); throw error; }
  }
  async read(ctx: AuthContext, sessionId: string, id: string, guard: () => void = () => {}): Promise<ChatUploadBytes> {
    guard(); const m = this.manifest(ctx, sessionId, id), path = this.path(id, m); await this.directory(dirname(path));
    const file = await open(path, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0)).catch(() => fail(400, 'upload_source_changed', 'Upload source changed'));
    let bytes: Buffer; try { const stat = await file.stat(); if (!stat.isFile() || stat.nlink !== 1 || stat.size > this.maxFileBytes || stat.size !== m.file_size) fail(400, 'upload_source_changed', 'Upload source changed'); bytes = await readBounded(file, this.maxFileBytes); if (bytes.length !== m.file_size || sha(bytes) !== m.sha256) fail(400, 'upload_source_changed', 'Upload source changed'); } finally { await file.close(); }
    await this.directory(dirname(path));
    guard(); this.manifest(ctx, sessionId, id); return { bytes, name: String(m.file_name), mimeType: String(m.mime_type), sha256: String(m.sha256) };
  }
  async parserInput(ctx: AuthContext, sessionId: string, id: string, guard: () => void) {
    const input = await this.read(ctx, sessionId, id, guard), m = this.manifest(ctx, sessionId, id); return { path: this.path(id, m), name: input.name, size_bytes: input.bytes.length, sha256: input.sha256 };
  }
  async artifacts(id: string): Promise<string> { this.key(id); const path = join(this.root, id, `parse-${randomUUID()}`); await this.directory(path, true); return path; }
  async artifact(path: string, expectedHash: string): Promise<Buffer> { await this.directory(dirname(path)); if (!path.startsWith(this.root + '/') && !path.startsWith(this.root + '\\')) fail(400, 'upload_source_changed', 'Parsed image changed'); const file = await open(path, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0)); try { const stat = await file.stat(); if (!stat.isFile() || stat.nlink !== 1 || stat.size > this.maxFileBytes) fail(400, 'upload_source_changed', 'Parsed image changed'); const bytes = await readBounded(file, this.maxFileBytes); if (sha(bytes) !== expectedHash || !imageMime(bytes)) fail(400, 'upload_source_changed', 'Parsed image changed'); return bytes; } finally { await file.close(); } }
  branch(ctx: AuthContext, source: string, target: string): void {
    this.session(ctx, source, true); this.session(ctx, target, true);
    for (const row of this.db.all("select key,value from desktop_meta where key like 'chat.upload:%'")) { const m = object(JSON.parse(String(row.value))), id = String(row.key).slice('chat.upload:'.length); if (m.user_id !== ctx.userId || m.tenant_id !== ctx.tenantId || !array(m.session_ids).includes(source) || !this.referenced(target, id)) continue; m.session_ids = [...new Set([...array(m.session_ids), target])]; this.db.run('update desktop_meta set value=? where key=?', JSON.stringify(m), String(row.key)); }
  }
  private referenced(sessionId: string, id: string): boolean { return !!this.db.get("select m.id from messages m join sessions s on s.id=m.session_id where m.session_id=? and m.deleted_at is null and s.deleted_at is null and (exists(select 1 from json_each(m.attachments) where json_extract(value,'$.upload_id')=?) or exists(select 1 from json_each(m.images) where json_extract(value,'$.upload_id')=? or json_extract(value,'$.original_upload_id')=?)) limit 1", sessionId, id, id, id); }
  async cleanup(ctx: AuthContext, sessionId: string): Promise<{ warnings?: Json[] }> {
    this.session(ctx, sessionId, true, true); const garbage: Array<{ id: string; m: JsonObject }> = [];
    this.db.transaction(() => { this.session(ctx, sessionId, true, true); for (const row of this.db.all("select key,value from desktop_meta where key like 'chat.upload:%'")) { const m = object(JSON.parse(String(row.value))), id = String(row.key).slice('chat.upload:'.length); if (m.user_id !== ctx.userId || m.tenant_id !== ctx.tenantId || !array(m.session_ids).includes(sessionId) || this.referenced(sessionId, id)) continue; m.session_ids = array(m.session_ids).filter(value => value !== sessionId); if (!array(m.session_ids).length) { m.state = 'cleanup_pending'; garbage.push({ id, m }); } this.db.run('update desktop_meta set value=? where key=?', JSON.stringify(m), String(row.key)); } });
    const warnings: Json[] = []; for (const { id, m } of garbage) { try { const path = this.path(id, m); await this.directory(dirname(path)); await rm(dirname(path), { recursive: true, force: true }); this.db.transaction(() => { const r = this.db.get('select value from desktop_meta where key=?', this.key(id)); if (r && String(r.value) === JSON.stringify(m)) this.db.run('delete from desktop_meta where key=?', this.key(id)); }); } catch { warnings.push({ code: 'upload_cleanup_pending', upload_id: id }); } } return warnings.length ? { warnings } : {};
  }
}

export interface ChatAttachmentOptions { parser?: DocumentParser; uploads?: ManagedChatUploads; maxFileBytes?: number; maxTextChars?: number; maxImages?: number }
export interface ChatAttachmentHooks extends ChatHooks { uploads: ManagedChatUploads }
export function createChatAttachmentHooks(db: CoreDatabase, auth: AuthService, options: ChatAttachmentOptions = {}): ChatAttachmentHooks {
  const uploads = options.uploads ?? new ManagedChatUploads(db, auth, options), maxText = bounded(options.maxTextChars, 100000, 1000000), maxImages = bounded(options.maxImages, 5, 20);
  const guard = (e: ChatExecution) => { const source = db.get("select id from messages where session_id=? and request_id=? and role='user' and visible_to_user=1 and deleted_at is null", e.sessionId, e.requestId); if (!source) fail(409, 'attachment_source_changed', 'Attachment source changed'); const fingerprint = JSON.stringify(db.read('messages', String(source!.id))); return () => e.publish(() => { if (JSON.stringify(db.read('messages', String(source!.id))) !== fingerprint) fail(409, 'attachment_source_changed', 'Attachment source changed'); }); };
  const rejectPath = (a: JsonObject) => { for (const key of ['path', 'file_path', 'source', 'artifact_dir']) if (a[key] !== undefined) fail(400, 'upload_path_forbidden', 'Renderer file paths are not accepted'); };
  const visionPrompt = (query: string) => `请识别用户上传的图片，为后续对话提供准确的文字上下文。逐字转写可读文字，描述主体、颜色、形状和相对位置。特别关注下面的用户问题；无法辨认时明确说明，不要猜测。\n\n用户问题：${query}`;
  return { uploads, branchUploads: (ctx, source, target) => uploads.branch(ctx, source, target), cleanupUploads: (ctx, sessionId) => uploads.cleanup(ctx, sessionId),
    images: async (e, images) => {
      const check = guard(e), prepared: Json[] = [];
      for (const value of images) { check(); const a = object(value); rejectPath(a); let ref: JsonObject = a, modelUrl = String(a.url ?? '');
        if (a.upload_id) { const input = await uploads.read(e.context, e.sessionId, String(a.upload_id), check); if (!imageMime(input.bytes)) fail(400, 'image_format_invalid', 'Uploaded image bytes are invalid'); modelUrl = `data:${input.mimeType};base64,${input.bytes.toString('base64')}`; ref = { ...a, file_name: input.name, file_size: input.bytes.length, mime_type: input.mimeType }; }
        else if (modelUrl.startsWith('data:')) { const match = /^data:(image\/[\w.+-]+);base64,(.*)$/s.exec(modelUrl); if (!match) fail(400, 'invalid_image', 'Invalid uploaded image'); const bytes = decoded(match![2], uploads.maxFileBytes), extension = imageMime(bytes).split('/')[1]?.split('+')[0] ?? 'image'; ref = await uploads.store(e.context, e.sessionId, { name: `image-${prepared.length + 1}.${extension}`, bytes, kind: 'image' }, check); modelUrl = `data:${String(ref.mime_type)};base64,${bytes.toString('base64')}`; }
        else if (!/^https?:\/\//.test(modelUrl)) fail(400, 'invalid_image', 'Invalid uploaded image');
        if (ref.upload_id && ['image/svg+xml', 'image/bmp', 'image/tiff'].includes(String(ref.mime_type))) {
          if (!options.parser) fail(501, 'image_normalization_pending', 'This image requires the document parser');
          const original = String(ref.upload_id), originalMime = String(ref.mime_type), artifactDir = await uploads.artifacts(original);
          try { const input = await uploads.parserInput(e.context, e.sessionId, original, check), extension = originalMime === 'image/svg+xml' ? 'svg' : originalMime.split('/')[1]; const parsed = await options.parser!.parse({ input: { ...input, name: `image.${extension}` }, artifact_dir: artifactDir, limits: { max_input_bytes: uploads.maxFileBytes, max_artifact_bytes: uploads.maxFileBytes, max_images: 1 } }, { signal: e.signal }); check(); const block = parsed.blocks.find(b => b.kind === 'image'); if (!block || block.kind !== 'image') fail(400, 'image_format_invalid', 'Image normalization returned no image'); const bytes = await uploads.artifact(join(artifactDir, block!.artifact_path), block!.sha256); ref = { ...await uploads.store(e.context, e.sessionId, { name: 'image.png', bytes, kind: 'image' }, check), original_upload_id: original, original_mime_type: originalMime }; modelUrl = `data:${block!.mime_type};base64,${bytes.toString('base64')}`; } finally { await rm(artifactDir, { recursive: true, force: true }); }
        }
        const caption = typeof a.caption === 'string' && a.caption.trim() ? a.caption.trim() : (await e.calls.vision('VLLM', modelUrl, visionPrompt(e.query), { signal: e.signal })).content.trim(); check(); if (!caption) fail(502, 'image_caption_empty', 'Vision model returned an empty caption');
        prepared.push({ ...ref, url: ref.upload_id ? `/api/v1/sessions/${encodeURIComponent(e.sessionId)}/uploads/${String(ref.upload_id)}` : modelUrl, caption });
      } return { images: prepared };
    },
    attachments: async (e, attachments) => {
      const check = guard(e), prepared: Json[] = [], warnings: Json[] = []; let remaining = maxText, imageCount = 0; const excerpts: string[] = [];
      for (const value of attachments) {
        check(); const a = typeof value === 'string' ? { file_name: value } : object(value); rejectPath(a); const fileName = name(a.file_name ?? a.name ?? 'attachment'); let ref: JsonObject = { ...a, file_name: fileName, file_size: a.file_size ?? a.size ?? 0 }, source: ChatUploadBytes | undefined;
        if (a.upload_id) source = await uploads.read(e.context, e.sessionId, String(a.upload_id), check);
        else if (a.data !== undefined) { const bytes = decoded(a.data, uploads.maxFileBytes); ref = await uploads.store(e.context, e.sessionId, { name: fileName, bytes, fileSize: a.file_size === undefined && a.size === undefined ? undefined : Number(a.file_size ?? a.size) }, check); source = { bytes, name: fileName, mimeType: String(ref.mime_type), sha256: String(ref.sha256) }; }
        delete ref.data; delete ref.path; let content = '', state = source ? 'pending' : 'metadata_only';
        if (source && /\.(txt|md|csv|json|log)$/i.test(source.name)) { try { content = new TextDecoder('utf-8', { fatal: true }).decode(source.bytes); state = 'ready'; } catch { fail(400, 'attachment_encoding_invalid', 'Attachment is not valid UTF-8'); } }
        else if (source && options.parser) {
          const artifactDir = await uploads.artifacts(String(ref.upload_id));
          try {
            const parsed = await options.parser.parse({ input: await uploads.parserInput(e.context, e.sessionId, String(ref.upload_id), check), artifact_dir: artifactDir, limits: { max_input_bytes: uploads.maxFileBytes, max_artifact_bytes: uploads.maxFileBytes, max_images: maxImages } }, { signal: e.signal }); check(); content = parsed.document.canonical_text; warnings.push(...parsed.warnings); state = 'ready'; ref.parser_version = parsed.document.parser_version; ref.provenance = { input_sha256: parsed.document.input_sha256, canonical_sha256: parsed.document.canonical_sha256, offset_unit: parsed.document.offset_unit }; ref.parsed_images = [];
            for (const block of parsed.blocks) if (block.kind === 'image') { if (imageCount >= maxImages) { warnings.push({ code: 'attachment_image_limit', file_name: fileName }); break; } imageCount++; const bytes = await uploads.artifact(join(artifactDir, block.artifact_path), block.sha256); check(); const caption = await e.calls.vision('VLLM', `data:${block.mime_type};base64,${bytes.toString('base64')}`, visionPrompt(e.query), { signal: e.signal }); check(); if (!caption.content.trim()) fail(502, 'image_caption_empty', 'Vision model returned an empty caption'); array(ref.parsed_images).push({ block_id: block.id, block_index: block.block_index, sha256: block.sha256, provenance: block.provenance, width: block.width, height: block.height, caption: caption.content.trim() }); content += `\n\n[附件图片 ${imageCount}]\n${caption.content.trim()}`; }
          } finally { await rm(artifactDir, { recursive: true, force: true }); }
        } else if (source) warnings.push({ code: 'attachment_parser_pending', file_name: fileName });
        const chars = Array.from(content), truncated = chars.length > remaining, excerpt = chars.slice(0, remaining).join(''); remaining -= Array.from(excerpt).length; if (truncated) warnings.push({ code: 'attachment_context_truncated', file_name: fileName, max_characters: maxText });
        ref.preparation_state = state; ref.truncated = truncated; if (excerpt) excerpts.push(`[${fileName}]\n${excerpt}${truncated ? '\n[附件上下文已截断]' : ''}`); prepared.push(ref);
      }
      check(); return { text: excerpts.join('\n\n'), attachments: prepared, warnings };
    },
  };
}
