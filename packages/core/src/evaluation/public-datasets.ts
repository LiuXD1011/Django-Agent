import { createHash, randomUUID } from 'node:crypto';
import { existsSync, lstatSync, mkdirSync, readFileSync, readdirSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import type { AuthContext, JsonObject } from '../contracts.js';
import type { AuthService } from '../auth/index.js';
import type { CoreDatabase, Row } from '../storage/database.js';
import { publicDatasetSpecs } from './public-registry.js';
import { digest, fail, object, now } from './common.js';
import { shuffled } from './selection.js';
export interface PublicDatasetSpec { id: string; version: string; label: string; repository: string; revision: string; basePath: string; sourceUrl: string; license: string; expectedQueries: number; artifactExpectedQueries: number; expectedDocuments: number; corpusTreeOid: string; files: Record<string, string>; manifestSha256: string; artifactManifestSha256: string; queryIds: string[] }
export interface PublicDatasetOptions { publicCacheRoot?: string; publicDatasetSpecs?: readonly PublicDatasetSpec[]; publicOrigin?: string; legacyCacheRoot?: string }
export interface PublicPreparationOptions { signal?: AbortSignal; onProgress?: (value: number) => void; check?: () => void }
const sha = (bytes: Buffer) => createHash('sha256').update(bytes).digest('hex');
const blob = (bytes: Buffer) => createHash('sha1').update(`blob ${bytes.length}\0`).update(bytes).digest('hex');
function treeOid(corpus: JsonObject): string {
  const entries = Object.entries(corpus).sort(([left], [right]) => Buffer.compare(Buffer.from(left), Buffer.from(right))).map(([name, oid]) => { if (!/^[a-zA-Z0-9_.-]+\.json$/.test(name) || !/^[a-f0-9]{40}$/.test(String(oid))) throw new Error('Invalid corpus tree'); return Buffer.concat([Buffer.from(`100644 ${name}\0`), Buffer.from(String(oid), 'hex')]); });
  const bytes = Buffer.concat(entries); return createHash('sha1').update(`tree ${bytes.length}\0`).update(bytes).digest('hex');
}
const coreFiles = ['queries.json', 'qrels.json', 'answers.json', 'pdf_urls.json'];
/** Public files live in an independent immutable cache. No tenant document, chunk or model index is created during preparation. */
export class PublicEvaluationDatasets {
  private readonly specs: readonly PublicDatasetSpec[];
  private readonly preparations = new Map<string, Promise<JsonObject>>();
  private readonly controllers = new Set<AbortController>();
  private closed = false;
  private readonly verifiedCache = new Map<string, { signature: string; state: JsonObject }>();
  readonly legacyCacheRoot: string;
  readonly cacheRoot: string;
  readonly origin: string;
  constructor(readonly db: CoreDatabase, readonly auth: AuthService, options: PublicDatasetOptions = {}) {
    this.legacyCacheRoot = resolve(options.legacyCacheRoot ?? join(db.dataRoot, '.cache'));
    this.specs = structuredClone(options.publicDatasetSpecs ?? publicDatasetSpecs); this.cacheRoot = resolve(options.publicCacheRoot ?? join(db.dataRoot, '.cache', 'eval-datasets')); this.origin = options.publicOrigin ?? 'https://huggingface.co';
    const url = new URL(this.origin); if (url.username || url.password || url.search || url.hash || url.pathname !== '/' || (url.protocol !== 'https:' && !(url.protocol === 'http:' && ['127.0.0.1', '[::1]', 'localhost'].includes(url.hostname)))) return fail(400, 'invalid_configuration', 'Public data origin must be HTTPS or a trusted local fixture origin');
    if (new Set(this.specs.map(spec => spec.id)).size !== this.specs.length) return fail(400, 'invalid_configuration', 'Duplicate public dataset IDs');
    for (const spec of this.specs) if (!/^[a-zA-Z0-9_.-]{1,100}$/.test(spec.id) || !/^[a-zA-Z0-9_.-]{1,100}$/.test(spec.version) || !/^[a-zA-Z0-9_.-]+\/[a-zA-Z0-9_.-]+$/.test(spec.repository) || !/^[a-f0-9]{40}$/.test(spec.revision) || !/^[a-f0-9]{40}$/.test(spec.corpusTreeOid) || !/^[a-zA-Z0-9_/-]+$/.test(spec.basePath) || spec.basePath.split('/').some(part => !part || part === '..') || coreFiles.some(name => !/^[a-f0-9]{64}$/.test(spec.files[name] || '')) || !Number.isSafeInteger(spec.expectedDocuments) || spec.expectedDocuments < 1 || spec.expectedDocuments > 10000 || !Number.isSafeInteger(spec.artifactExpectedQueries) || spec.artifactExpectedQueries < 1 || spec.artifactExpectedQueries > 100000 || spec.queryIds.length && (new Set(spec.queryIds).size !== spec.expectedQueries || spec.queryIds.length !== spec.expectedQueries)) return fail(400, 'invalid_configuration', 'Public dataset manifest is invalid');
  }
  spec(id: string): PublicDatasetSpec { const alias = id === 'open_rag_benchmark' ? 'open_rag_benchmark_full' : id === 'open_rag_benchmark_100' ? 'open_rag_benchmark_180' : id; const spec = this.specs.find(item => item.id === alias); if (!spec) return fail(404, 'open_dataset_not_found', 'Public evaluation dataset not found'); return spec; }
  private path(spec: PublicDatasetSpec): string { return join(this.cacheRoot, spec.repository.replace('/', '-'), spec.version); }
  private directory(path: string): void { const target = resolve(path); let current = target; for (;;) { if (existsSync(current) && lstatSync(current).isSymbolicLink()) throw new Error('Symlink cache directory'); const parent = resolve(current, '..'); if (parent === current) break; current = parent; } }
  private cacheSignature(spec: PublicDatasetSpec): string { const path = this.path(spec); this.directory(path); const corpus = join(path, 'corpus'); if (!existsSync(corpus)) throw new Error('Corpus unavailable'); const names = readdirSync(corpus).sort(); return digest([spec.artifactManifestSha256, spec.corpusTreeOid, ['state.json', ...coreFiles, ...names.map(name => `corpus/${name}`)].map(name => { const stat = lstatSync(join(path, name), { bigint: true }); if (!stat.isFile() || stat.isSymbolicLink()) throw new Error('Invalid cache file'); return [name, stat.dev.toString(), stat.ino.toString(), stat.size.toString(), stat.mtimeNs.toString(), stat.ctimeNs.toString()]; })]); }
  private file(path: string): Buffer { if (!existsSync(path) || !lstatSync(path).isFile() || lstatSync(path).isSymbolicLink() || lstatSync(path).size > 16 * 1024 * 1024) throw new Error('Invalid cache artifact'); return readFileSync(path); }
  private verified(spec: PublicDatasetSpec): JsonObject {
    const path = this.path(spec), signature = this.cacheSignature(spec), cached = this.verifiedCache.get(`${path}:${spec.id}`); if (cached?.signature === signature) return cached.state; if (!existsSync(path) || !lstatSync(path).isDirectory() || lstatSync(path).isSymbolicLink()) throw new Error('Invalid cache root');
    const state = object(JSON.parse(this.file(join(path, 'state.json')).toString('utf8'))); if (state.revision !== spec.revision || state.manifest_sha256 !== spec.artifactManifestSha256 || state.status !== 'ready') throw new Error('Unverified cache');
    for (const name of coreFiles) if (sha(this.file(join(path, name))) !== spec.files[name]) throw new Error('Pinned core checksum mismatch');
    const payloads = coreFiles.slice(0, 3).map(name => object(JSON.parse(this.file(join(path, name)).toString('utf8'))));
    if (payloads.some(value => Object.keys(value).length !== spec.artifactExpectedQueries) || Object.keys(payloads[0]!).some(id => !Object.hasOwn(payloads[1]!, id) || !Object.hasOwn(payloads[2]!, id)) || spec.queryIds.some(id => !Object.hasOwn(payloads[0]!, id))) throw new Error('Core row count mismatch');
    const corpus = object(state.corpus); if (treeOid(corpus) !== spec.corpusTreeOid) throw new Error('Pinned corpus tree mismatch'); if (Object.keys(corpus).length !== spec.expectedDocuments || !existsSync(join(path, 'corpus')) || lstatSync(join(path, 'corpus')).isSymbolicLink() || readdirSync(join(path, 'corpus')).filter(name => name.endsWith('.json')).length !== spec.expectedDocuments) throw new Error('Corpus count mismatch');
    const ids = new Set<string>();
    for (const [name, oid] of Object.entries(corpus)) { if (!/^[a-zA-Z0-9_.-]+\.json$/.test(name)) throw new Error('Invalid corpus name'); const bytes = this.file(join(path, 'corpus', name)), value = object(JSON.parse(bytes.toString('utf8'))); if (blob(bytes) !== oid || typeof value.id !== 'string' || !value.id || ids.has(value.id) || !Array.isArray(value.sections)) throw new Error('Invalid corpus artifact'); ids.add(value.id); }
    this.verifiedCache.set(`${path}:${spec.id}`, { signature, state }); return state;
  }
  status(ctx: AuthContext, id: string): JsonObject {
    this.auth.assertCan(ctx, 'read'); const spec = this.spec(id); let state: JsonObject = {}, ready = false;
    try { state = this.verified(spec); ready = true; } catch { try { state = object(JSON.parse(this.file(join(this.path(spec), 'state.json')).toString('utf8'))); } catch {} }
    return { id: spec.id, version: spec.version, name: spec.label, label: spec.label, count: spec.expectedQueries, documents: spec.expectedDocuments, source_url: spec.sourceUrl, license: spec.license, revision: spec.revision, manifest_sha256: spec.manifestSha256, ready, status: ready ? 'ready' : this.preparations.has(this.path(spec)) ? 'preparing' : state.status === 'failed' ? 'failed' : 'not_prepared', progress: ready ? 1 : typeof state.progress === 'number' && Number.isFinite(state.progress) ? Math.max(0, Math.min(1, state.progress)) : 0, capabilities: ready ? ['keyword'] : [], error_code: ready ? '' : typeof state.error_code === 'string' && /^[a-z][a-z0-9_.-]{0,63}$/.test(state.error_code) ? state.error_code : '', actual_queries: ready ? spec.expectedQueries : 0, actual_documents: ready ? spec.expectedDocuments : 0 };
  }
  catalog(ctx: AuthContext): JsonObject { this.auth.assertCan(ctx, 'read'); return { datasets: this.specs.map(spec => this.status(ctx, spec.id)) }; }
  prepare(ctx: AuthContext, id: string, options: PublicPreparationOptions = {}): Promise<JsonObject> {
    this.auth.assertCan(ctx, 'eval.write'); if (this.closed) return Promise.reject(new Error('Evaluation is closed')); const spec = this.spec(id), path = this.path(spec);
    if (this.status(ctx, id).ready) return Promise.resolve(this.status(ctx, id));
    const existing = this.preparations.get(path); if (existing) return existing.then(() => this.status(ctx, id));
    const controller = new AbortController(), abort = () => controller.abort(); this.controllers.add(controller); options.signal?.addEventListener('abort', abort, { once: true }); if (options.signal?.aborted) abort();
    const work = this.download(ctx, spec, controller.signal, options).finally(() => { options.signal?.removeEventListener('abort', abort); this.preparations.delete(path); this.controllers.delete(controller); }); this.preparations.set(path, work); return work;
  }
  private async bytes(relative: string, signal: AbortSignal, limit = 16 * 1024 * 1024): Promise<Buffer> {
    let url = new URL(relative, this.origin);
    for (let redirects = 0; redirects <= 5; redirects++) {
      const response = await fetch(url, { signal: AbortSignal.any([signal, AbortSignal.timeout(120000)]), redirect: 'manual', headers: { 'user-agent': 'Marlin/OpenRAGEvaluator' } });
      if (response.status >= 300 && response.status < 400) { const location = response.headers.get('location'); await response.body?.cancel(); if (!location) break; const next = new URL(location, url); const official = this.origin === 'https://huggingface.co' && next.protocol === 'https:' && (next.hostname === 'huggingface.co' || next.hostname.endsWith('.huggingface.co') || next.hostname.endsWith('.hf.co')); if (next.username || next.password || next.origin !== this.origin && !official) return fail(502, 'public_dataset_redirect_rejected', 'Public data redirect was not trusted'); url = next; continue; }
      if (!response.ok || !response.body) { await response.body?.cancel(); return fail(502, 'public_dataset_http_failed', 'Public dataset request failed'); }
      const chunks: Buffer[] = [], reader = response.body.getReader(); let count = 0;
      try { for (;;) { const item = await reader.read(); if (item.done) break; count += item.value.length; if (count > limit) return fail(413, 'public_dataset_artifact_limit', 'Public dataset artifact is too large'); chunks.push(Buffer.from(item.value)); } } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
      return Buffer.concat(chunks);
    }
    return fail(502, 'public_dataset_redirect_rejected', 'Public data redirect limit exceeded');
  }
  private async download(ctx: AuthContext, spec: PublicDatasetSpec, signal: AbortSignal, options: PublicPreparationOptions): Promise<JsonObject> {
    const path = this.path(spec); this.directory(path); mkdirSync(path, { recursive: true, mode: 0o700 }); if (lstatSync(path).isSymbolicLink()) return fail(400, 'public_dataset_path_invalid', 'Public dataset cache directory is invalid');
    const statePath = join(path, 'state.json'); const update = (value: JsonObject) => { signal.throwIfAborted(); options.check?.(); this.auth.assertCan(ctx, 'eval.write'); const temporary = `${statePath}.${randomUUID()}.part`; writeFileSync(temporary, JSON.stringify(value), { mode: 0o600, flag: 'wx' }); renameSync(temporary, statePath); options.onProgress?.(Number(value.progress ?? 0)); };
    let completed = 0, artifactBytes = 0; const total = spec.expectedDocuments + 4; const corpus: JsonObject = {};
    const state = () => ({ status: 'preparing', progress: completed / total, revision: spec.revision, manifest_sha256: spec.artifactManifestSha256, updated_at: now(), corpus });
    update(state());
    const artifact = async (relative: string, target: string, expected: string, git = false) => { signal.throwIfAborted(); this.auth.assertCan(ctx, 'eval.write'); let bytes: Buffer | undefined; try { const saved = this.file(target); if ((git ? blob(saved) : sha(saved)) === expected) bytes = saved; } catch {} if (!bytes && spec.repository === 'vectara/open_ragbench') { try { const legacy = join(this.legacyCacheRoot, 'eval-datasets', 'open_rag_benchmark', spec.version, target.slice(path.length + 1)); this.directory(legacy); const saved = this.file(legacy); if ((git ? blob(saved) : sha(saved)) === expected) bytes = saved; } catch {} } bytes ??= await this.bytes(relative, signal); artifactBytes += bytes.length; if (artifactBytes > 1024 * 1024 * 1024) return fail(413, 'public_dataset_corpus_limit', 'Public dataset exceeds the cache byte budget'); if ((git ? blob(bytes) : sha(bytes)) !== expected) return fail(502, 'public_dataset_checksum_mismatch', 'Public dataset artifact failed its pinned checksum'); signal.throwIfAborted(); options.check?.(); this.auth.assertCan(ctx, 'eval.write'); const temporary = `${target}.${randomUUID()}.part`; writeFileSync(temporary, bytes, { mode: 0o600, flag: 'wx' }); renameSync(temporary, target); completed++; update(state()); };
    try {
      const treeRoot = `/api/datasets/${spec.repository}/tree/${spec.revision}/${spec.basePath}`;
      const rootTree = JSON.parse((await this.bytes(`${treeRoot}?recursive=false`, signal, 2 * 1024 * 1024)).toString('utf8')) as JsonObject[];
      if (!Array.isArray(rootTree) || !rootTree.some(item => item.type === 'directory' && item.path === `${spec.basePath}/corpus` && item.oid === spec.corpusTreeOid)) return fail(502, 'public_dataset_tree_mismatch', 'Public corpus tree failed its pinned identity');
      const tree = JSON.parse((await this.bytes(`${treeRoot}/corpus?recursive=false&limit=1000`, signal, 4 * 1024 * 1024)).toString('utf8')) as JsonObject[];
      if (!Array.isArray(tree)) return fail(502, 'public_dataset_tree_invalid', 'Public corpus tree is malformed');
      const files = tree.filter(item => item.type === 'file' && typeof item.path === 'string' && item.path.startsWith(`${spec.basePath}/corpus/`) && item.path.endsWith('.json'));
      if (files.length !== spec.expectedDocuments) return fail(502, 'public_dataset_count_mismatch', 'Public corpus document count does not match the manifest');
      const pinnedCorpus: JsonObject = {};
      for (const item of files) { const name = String(item.path).slice(`${spec.basePath}/corpus/`.length); if (Object.hasOwn(pinnedCorpus, name)) return fail(502, 'public_dataset_tree_invalid', 'Duplicate corpus tree entry'); pinnedCorpus[name] = item.oid!; }
      if (treeOid(pinnedCorpus) !== spec.corpusTreeOid) return fail(502, 'public_dataset_tree_mismatch', 'Corpus file list failed its pinned Git tree checksum');
      mkdirSync(join(path, 'corpus'), { recursive: true, mode: 0o700 }); if (lstatSync(join(path, 'corpus')).isSymbolicLink()) return fail(400, 'public_dataset_path_invalid', 'Public corpus directory is invalid');
      for (const name of coreFiles) await artifact(`/datasets/${spec.repository}/resolve/${spec.revision}/${spec.basePath}/${name}`, join(path, name), spec.files[name]!);
      for (const item of files) { const name = String(item.path).slice(`${spec.basePath}/corpus/`.length); if (!/^[a-zA-Z0-9_.-]+\.json$/.test(name) || !/^[a-f0-9]{40}$/.test(String(item.oid)) || Object.hasOwn(corpus, name)) return fail(502, 'public_dataset_tree_invalid', 'Public corpus path is invalid'); await artifact(`/datasets/${spec.repository}/resolve/${spec.revision}/${item.path}`, join(path, 'corpus', name), String(item.oid), true); corpus[name] = item.oid!; }
      update({ ...state(), status: 'ready', progress: 1 }); this.verified(spec); return this.status(ctx, spec.id);
    } catch (error) { try { update({ ...state(), status: 'failed', error_code: typeof object(error).code === 'string' ? object(error).code! : 'public_dataset_prepare_failed' }); } catch {} if (object(error).code) throw error; return fail(502, 'public_dataset_prepare_failed', 'Public dataset preparation failed; no cache was declared ready'); }
  }
  materialize(ctx: AuthContext, id: string, sampleSize?: number, seed = 20260819): { spec: PublicDatasetSpec; documents: Row[]; entries: JsonObject[]; fingerprint: JsonObject } {
    this.auth.assertCan(ctx, 'read'); const spec = this.spec(id); sampleSize ??= spec.expectedQueries; if (this.status(ctx, id).ready !== true) return fail(422, 'public_dataset_not_prepared', 'Public evaluation dataset must be prepared and verified');
    if (!Number.isSafeInteger(sampleSize) || sampleSize < 5 || sampleSize > 3045 || sampleSize > spec.expectedQueries || !Number.isSafeInteger(seed)) return fail(400, 'invalid_evaluation_input', 'Public evaluation requires five to 3045 real questions within the pinned variant');
    const path = this.path(spec), documents: Row[] = [], spans = new Map<string, Map<string, [number, number]>>(); let canonicalBytes = 0;
    for (const filename of readdirSync(join(path, 'corpus')).filter(name => name.endsWith('.json')).sort()) {
      const raw = object(JSON.parse(this.file(join(path, 'corpus', filename)).toString('utf8'))), pieces: string[] = [], blocks: JsonObject[] = [], sections = new Map<string, [number, number]>(); let cursor = 0;
      for (const [index, value] of (raw.sections as JsonObject[]).entries()) { const section = object(value), parts = [String(section.text || '').trim()]; let tables = section.tables; if (typeof tables === 'string') { const rawTables = tables; try { tables = JSON.parse(rawTables); } catch { tables = { table: rawTables }; } } parts.push(...Object.values(object(tables)).map(String).filter(value => value.trim())); const images = object(section.images); if (Object.keys(images).length) parts.push(`[embedded images: ${Object.keys(images).sort().join(', ')}]`); const content = parts.filter(value => value.trim()).join('\n\n'); if (!content) continue; if (pieces.length) cursor += 2; const start = cursor; pieces.push(content); cursor += Array.from(content).length; const sectionId = String(section.section_id ?? index); sections.set(sectionId, [start, cursor]); blocks.push({ id: `section-${index}`, kind: 'text', block_index: index, block_type: 'paragraph', text: content, canonical_range: { start, end: cursor }, provenance: { section_id: sectionId }, metadata: {} }); }
      const content = pieces.join('\n\n'); canonicalBytes += Buffer.byteLength(content); if (canonicalBytes > 256 * 1024 * 1024) return fail(413, 'evaluation_corpus_limit', 'Public canonical text exceeds the supported byte budget'); const docId = String(raw.id); spans.set(docId, sections); documents.push({ id: docId, tenant_id: ctx.tenantId, title: String(raw.title || ''), file_hash: sha(this.file(join(path, 'corpus', filename))), metadata: { content, parser_blocks: blocks, source_generation: spec.revision }, enable_status: 'enabled' });
    }
    const queries = object(JSON.parse(this.file(join(path, 'queries.json')).toString('utf8'))), qrels = object(JSON.parse(this.file(join(path, 'qrels.json')).toString('utf8'))), answers = object(JSON.parse(this.file(join(path, 'answers.json')).toString('utf8')));
    const ids = shuffled(spec.queryIds.length ? spec.queryIds : Object.keys(queries).sort(), seed).slice(0, sampleSize);
    const entries = ids.map(id => {
      const evidence: JsonObject[] = [], qrel = object(qrels[id]);
      const documentId = String(qrel.doc_id || ''), span = spans.get(documentId)?.get(String(qrel.section_id));
      if (span) evidence.push({ knowledge_id: documentId, source_start: span[0], source_end: span[1] });
      const answer = typeof answers[id] === 'string' ? answers[id] : String(object(answers[id]).answer || ''); const question = String(object(queries[id]).query || '');
      if (!question.trim() || !answer.trim() || !evidence.length) return fail(422, 'public_dataset_question_invalid', 'A public question lacks reference answer or relevant source spans');
      return { id, question, answer, reference_answer: answer, evidence, status: 'approved', schema_version: 'evaluation_v2', approval_source: 'immutable_public_benchmark' };
    });
    return { spec, documents, entries, fingerprint: { public_dataset_id: spec.id, dataset_hash: spec.manifestSha256, dataset_version: spec.version, revision: spec.revision } };
  }
  async close(): Promise<void> { this.closed = true; this.controllers.forEach(controller => controller.abort()); await Promise.allSettled([...this.preparations.values()]); }
}
