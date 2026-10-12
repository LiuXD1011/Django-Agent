import { randomUUID } from 'node:crypto';
import type { AuthService } from '../auth/index.js';
import type { AuthContext, Json, JsonObject, ModelConfiguration, ModelUsage, ParsedDocument, ParsedImageBlock } from '../contracts.js';
import { trustedAttemptPublication } from '../jobs/attempt-control.js';
import type { JobContext } from '../jobs/queue.js';
import { effectiveChunking, enabled, indexing, object } from '../knowledge/config.js';
import { ModelRuntime, ModelRuntimeError } from '../models/runtime.js';
import { resolveProvider } from '../models/providers.js';
import { auxiliaryThinking } from '../models/thinking.js';
import type { SearchIndex } from '../retrieval/search-index.js';
import type { EmbeddingBinding } from '../retrieval/types.js';
import type { ModelConfigurationService } from '../settings/model-configuration.js';
import type { CoreDatabase, Row } from '../storage/database.js';
import type { DocumentParser } from './parser.js';
import type { ChunkDraft } from './chunker.js';
import type { ChunkingWorkers } from './chunking-workers.js';
import { controlled, digest, readControlled, removeOwned, removeTemporary, temporary, writeOwned } from './workflow/files.js';
export interface WorkflowHookContext {
    db: CoreDatabase;
    auth: AuthContext;
    knowledgeId: string;
    knowledgeBaseId: string;
    jobId: string;
    attempt: number;
    signal: AbortSignal;
    content: string;
    chunks: JsonObject[];
    processConfig: JsonObject;
    publish<T>(work: () => T): T;
}
export interface WorkflowHookResult {
    status: 'completed' | 'pending' | 'needs_configuration' | 'failed';
    output?: JsonObject;
    warnings?: JsonObject[];
}
export type WorkflowHook = (context: WorkflowHookContext) => Promise<WorkflowHookResult>;
export interface PipelineHost {
    db: CoreDatabase;
    auth: AuthService;
    models: ModelConfigurationService;
    index: SearchIndex;
    parser: DocumentParser;
    chunker: ChunkingWorkers;
    hooks?: {
        graph?: WorkflowHook;
        wiki?: WorkflowHook;
    };
    assertActive(ctx: AuthContext, job: JobContext, payload: JsonObject): Row;
    publish<T>(ctx: AuthContext, job: JobContext, payload: JsonObject, work: () => T): T;
}
interface ImageDraft {
    id: string;
    block: ParsedImageBlock;
    path: string;
    ocr: string;
    caption: string;
    status: string;
    error: string;
}
const now = () => new Date().toISOString();
const codepoints = (value: string, cap: number) => Array.from(value).slice(0, cap).join('');
const zeroUsage = (): ModelUsage => ({ prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, cached_tokens: 0, reasoning_tokens: 0 });
const warning = (code: string, stage: string): JsonObject => ({ code, stage, message: code.replaceAll('_', ' ') });
const resultUnknown = (error: unknown): boolean => error instanceof Error && 'resultUnknown' in error && error.resultUnknown === true;
const mimeExtension: Record<string, string> = { 'image/png': 'png', 'image/jpeg': 'jpg', 'image/gif': 'gif', 'image/bmp': 'bmp', 'image/tiff': 'tiff', 'image/webp': 'webp' };
/** Hash only stable nonsecret provider identity. This is shared with semantic cache and vector generation checks. */
export function embeddingBinding(configuration: ModelConfiguration, runtime = new ModelRuntime(configuration)): EmbeddingBinding {
    const provider = resolveProvider(configuration);
    if (!provider.dimension)
        throw new ModelRuntimeError('model_configuration_invalid', 'Embedding dimension must be configured');
    return { modelId: configuration.id, dimension: provider.dimension, signature: `${digest(JSON.stringify([configuration.id, configuration.type, configuration.source, provider.baseUrl, provider.model]))}:${provider.dimension}`, runtime };
}
function configuration(host: PipelineHost, ctx: AuthContext, id: string, role: string): ModelConfiguration | undefined {
    try {
        const result = host.models.configuration(ctx, id || role);
        new ModelRuntime(result);
        return result;
    }
    catch (error) {
        if (error instanceof Error && 'status' in error && [401, 403].includes(Number(error.status)))
            throw error;
        return undefined;
    }
}
export function mayCallModel(host: PipelineHost, ctx: AuthContext, kb: Row, config: JsonObject): boolean {
    const strategy = indexing(kb.indexing_strategy, String(kb.type));
    // Hooks may call external services. An unavailable hook cannot fabricate a paid success.
    if ((enabled(config.graph_enabled, strategy.graph_enabled === true) && host.hooks?.graph) || (enabled(config.wiki_enabled, strategy.wiki_enabled === true) && host.hooks?.wiki))
        return true;
    return !!configuration(host, ctx, String(kb.summary_model_id ?? ''), 'KnowledgeQA') || !!configuration(host, ctx, String(object(kb.vlm_config).model_id ?? ''), 'VLLM') ||
        (strategy.vector_enabled === true || effectiveChunking(kb.chunking_config, config).strategy === 'semantic') && !!configuration(host, ctx, String(kb.embedding_model_id ?? ''), 'Embedding');
}
/** Models and parser calls never run inside a write transaction; every publication rechecks queue ownership and document scope. */
export async function executePipeline(host: PipelineHost, ctx: AuthContext, job: JobContext, payload: JsonObject): Promise<JsonObject> {
    const docId = String(payload.knowledge_id), kbId = String(payload.knowledge_base_id), process = object(payload.process_config), scope = { tenantId: ctx.tenantId, knowledgeBaseIds: [kbId] }, allowModels = payload.allow_model_calls === true;
    const pub = trustedAttemptPublication(<T>(work: () => T) => host.publish(ctx, job, payload, work)), active = () => host.assertActive(ctx, job, payload);
    let initial = active(), kb = host.db.read('knowledge_bases', kbId)!;
    const config = effectiveChunking(kb.chunking_config, process), warnings: JsonObject[] = [], workspace = temporary(host.db.dataRoot), publishedFiles: Array<{
        path: string;
        hash: string;
    }> = [], retiredFiles: Array<{ path: string; hash: string }> = [];
    let parsed: ParsedDocument | undefined, published = false, attempt = 0, root: Row | undefined, deferredModelError: ModelRuntimeError | undefined;
    const span = (name: string, kind = 'stage'): Row => pub(() => host.db.insert('knowledge_processing_spans', { knowledge_id: docId, attempt, span_id: randomUUID(), parent_span_id: kind === 'root' ? '' : String(root?.span_id ?? ''), name, kind, status: 'running', started_at: now(), metadata: { job_id: job.jobId, queue_attempt: job.attempt } }));
    const end = (row: Row, status: string, output: JsonObject = {}, error = '') => pub(() => host.db.update('knowledge_processing_spans', String(row.id), { status, output_data: output, error_code: error, error_message: error, finished_at: now(), duration_ms: Math.max(0, Date.now() - Date.parse(String(row.started_at))) }));
    const stage = async <T>(name: string, work: () => Promise<T>, describe: (value: T) => JsonObject): Promise<T> => {
        active();
        const s = span(name);
        try {
            let value!: T;
            await job.step(name, async () => { value = await work(); const out = describe(value); end(s, out.status === 'pending' || out.status === 'needs_configuration' || out.status === 'skipped' ? 'skipped' : out.status === 'failed' ? 'failed' : 'done', out); return out; });
            return value;
        }
        catch (error) {
            try {
                end(s, resultUnknown(error) ? 'interrupted' : 'failed', {}, error instanceof ModelRuntimeError ? error.code : 'stage_failed');
            }
            catch { }
            throw error;
        }
    };
    const call = async <T extends {
        usage: ModelUsage;
    }>(cfg: ModelConfiguration, scenario: string, work: (runtime: ModelRuntime) => Promise<T>, validate?: (result: T) => void): Promise<T> => {
        active();
        const runtime = new ModelRuntime(cfg), started = Date.now(), invocation = randomUUID();
        let usage = zeroUsage(), success = false, errorCode = '', unknown = false;
        try {
            const result = await work(runtime);
            usage = result.usage;
            validate?.(result);
            success = true;
            return result;
        }
        catch (error) {
            errorCode = error instanceof ModelRuntimeError ? error.code : 'model_call_failed';
            unknown = resultUnknown(error);
            throw error;
        }
        finally {
            host.models.recordUsage(ctx, cfg, usage, { scenario, success, durationMs: Math.max(0, Date.now() - started), errorCode: errorCode || undefined, invocationId: invocation, metadata: { knowledge_id: docId, knowledge_base_id: kbId, job_id: job.jobId, request_id: String(payload.request_id), attempt: job.attempt, result_unknown: unknown } });
        }
    };
    try {
        pub(() => { attempt = Number(host.db.get('SELECT coalesce(max(attempt),0)+1 AS n FROM knowledge_processing_spans WHERE knowledge_id=?', docId)?.n); root = span('process_knowledge', 'root'); initial = active(); host.db.update('knowledges', docId, { parse_status: initial.processed_at ? 'completed' : 'processing', metadata: { ...object(initial.metadata), workflow_status: 'processing', workflow_attempt: attempt }, updated_at: now() }); host.db.update('task_records', job.jobId, { status: 'running', attempt_count: job.attempt, claimed_by: job.ownerToken, updated_at: now() }); });
        parsed = await stage('docreader', async () => { const row = active(); readControlled(host.db.dataRoot, String(row.file_path), String(row.file_hash), 64 * 1024 * 1024); return host.parser.parse({ input: { name: String(row.file_name), path: controlled(host.db.dataRoot, String(row.file_path)), sha256: String(row.file_hash), size_bytes: Number(row.file_size) }, artifact_dir: workspace.path, options: { engine: String(process.parser_engine || 'builtin') } }, { signal: job.signal, onProgress: event => { active(); job.emit('parser.progress', { stage: event.stage, progress: event.progress }); } }); }, p => ({ content_length: Array.from(p.document.canonical_text).length, image_count: p.blocks.filter(b => b.kind === 'image').length, warning_count: p.warnings.length, ocr_performed: false }));
        for (const w of parsed.warnings)
            warnings.push({ ...w, stage: 'docreader' });
        const embeddingConfig = allowModels ? configuration(host, ctx, String(initial.embedding_model_id || kb.embedding_model_id || ''), 'Embedding') : undefined;
        let binding: EmbeddingBinding | undefined;
        try {
            if (embeddingConfig)
                binding = embeddingBinding(embeddingConfig);
        }
        catch {
            warnings.push(warning('embedding_needs_configuration', 'embedding'));
        }
        const chunks = await stage('chunking', async () => host.chunker.split(parsed!, config, { title: String(initial.title), signal: job.signal, onProgress: event => { active(); job.emit('chunking.progress', event); }, semanticSignature: binding?.signature, semanticDimension: binding?.dimension, semanticEmbed: binding && embeddingConfig ? async (texts) => {
                const hash = digest(JSON.stringify([ctx.tenantId, texts]));
                const existing = host.db.get('SELECT id FROM semantic_chunk_cache WHERE content_hash=? AND model_signature=? AND algorithm_version=? AND window_size=? AND percentile=?', hash, binding!.signature, 'semantic-boundaries-v2', Number(config.semantic_window_size), Number(config.semantic_breakpoint_percentile));
                if (existing) {
                    const row = host.db.read('semantic_chunk_cache', String(existing.id))!;
                    if (JSON.stringify(row.window_inputs) === JSON.stringify(texts))
                        return row.vectors as unknown as number[][];
                }
                let result;
                try {
                    result = await call(embeddingConfig, 'semantic_chunking', r => r.embed(texts, { signal: job.signal }));
                }
                catch (error) {
                    if (error instanceof ModelRuntimeError && error.resultUnknown && !job.signal.aborted) {
                        deferredModelError = error;
                        warnings.push(warning('semantic_result_unknown', 'chunking'));
                        throw new Error('embedding_result_unknown');
                    }
                    throw error;
                }
                if (result.vectors.some(v => v.length !== binding!.dimension || v.some(n => !Number.isFinite(n)) || !Math.hypot(...v)))
                    throw new Error('invalid_embedding_vectors');
                pub(() => host.db.insert('semantic_chunk_cache', { content_hash: hash, model_signature: binding!.signature, algorithm_version: 'semantic-boundaries-v2', window_size: Number(config.semantic_window_size), percentile: Number(config.semantic_breakpoint_percentile), window_inputs: texts, vectors: result.vectors }));
                return result.vectors;
            } : undefined }), r => ({ parent_count: r.parents.length, chunk_count: r.children.length, diagnostics: r.diagnostics }));
        if (Array.isArray(chunks.diagnostics.fallback_chain) && chunks.diagnostics.fallback_chain.length)
            warnings.push(warning('chunking_strategy_fallback', 'chunking'));
        const images: ImageDraft[] = parsed.blocks.filter((b): b is ParsedImageBlock => b.kind === 'image').map(block => ({ id: randomUUID(), block, path: `media/documents/${docId}/generations/${randomUUID()}/${block.id}.${mimeExtension[block.mime_type] ?? 'bin'}`, ocr: '', caption: '', status: 'needs_configuration', error: '' }));
        await stage('publish_local', async () => {
            for (const image of images) {
                active();
                const bytes = readControlled(workspace.path, image.block.artifact_path, image.block.sha256);
                writeOwned(host.db.dataRoot, image.path, bytes);
                publishedFiles.push({ path: image.path, hash: image.block.sha256 });
            }
            pub(() => {
                const d = active(), oldImages = host.db.all('SELECT * FROM knowledge_images WHERE tenant_id=? AND knowledge_base_id=? AND knowledge_id=?', ctx.tenantId, kbId, docId), oldChunks = host.db.all('SELECT id,seq_id FROM chunks WHERE tenant_id=? AND knowledge_base_id=? AND knowledge_id=?', ctx.tenantId, kbId, docId);
                for (const [i, c] of oldChunks.entries()) {
                    if (i % 64 === 0) job.checkpoint();
                    host.index.deleteChunk(scope, String(c.id), c.seq_id == null ? undefined : String(c.seq_id));
                }
                job.checkpoint();
                host.db.run('DELETE FROM chunks WHERE tenant_id=? AND knowledge_base_id=? AND knowledge_id=?', ctx.tenantId, kbId, docId);
                host.db.run('DELETE FROM knowledge_images WHERE tenant_id=? AND knowledge_base_id=? AND knowledge_id=?', ctx.tenantId, kbId, docId);
                const retained: ChunkDraft[] = [], tiny = new Set<string>(), minimum = Math.max(8, Math.min(64, Math.floor(Number(config.enable_parent_child ? config.child_chunk_size : config.chunk_size) / 4)));
                for (const [i, c] of chunks.children.entries()) {
                    if (i % 64 === 0) job.checkpoint();
                    const key = digest(c.content.trim());
                    if (Array.from(c.content.trim()).length < minimum && tiny.has(key))
                        continue;
                    tiny.add(key);
                    retained.push(c);
                }
                // Allocate after deduplication so first insertion already has
                // final parent references and neighbours, with no row readback.
                const parentIds = chunks.parents.map(() => randomUUID()), childIds = retained.map(() => randomUUID());
                const create = (draft: ChunkDraft, id: string, index: number, previous = '', next = '') => ({ id, tenant_id: ctx.tenantId, knowledge_base_id: kbId, knowledge_id: docId, content: draft.content, context_header: draft.context_header, start_at: draft.start_at, end_at: draft.end_at, chunk_index: index, chunk_type: draft.chunk_type, is_enabled: draft.chunk_type === 'text', context_parent_id: draft.context_parent_index == null ? null : parentIds[draft.context_parent_index], pre_chunk_id: previous, next_chunk_id: next, content_hash: digest(draft.content), chunking_version: 'parent-child-v1', metadata: { title: d.title!, ...draft.metadata, source_generation: String(root!.span_id), parser_version: parsed!.document.parser_version, offset_unit: 'unicode_code_point' }, tag_id: d.tag_id });
                host.db.insertMany('chunks', [
                    ...chunks.parents.map((draft, i) => create(draft, parentIds[i]!, i)),
                    ...retained.map((draft, i) => create(draft, childIds[i]!, chunks.parents.length + i, childIds[i - 1], childIds[i + 1])),
                ], job.checkpoint);
                for (const image of images) {
                    job.checkpoint();
                    const b = image.block;
                    host.db.insert('knowledge_images', { id: image.id, tenant_id: ctx.tenantId, knowledge_base_id: kbId, knowledge_id: docId, content_hash: b.sha256, storage_path: image.path, storage_owned: true, mime_type: b.mime_type, width: b.width, height: b.height, source_type: String(b.provenance.source_type ?? 'embedded'), source_ref: String(b.provenance.source_ref ?? ''), page_index: b.provenance.page_index ?? null, block_index: b.block_index, status: 'needs_configuration', metadata: { ...b.metadata, provenance: b.provenance, original_mime_type: b.original_mime_type, parser_version: parsed!.document.parser_version, source_generation: String(root!.span_id) } });
                }
                host.db.update('knowledges', docId, { parse_status: 'completed', processed_at: now(), summary_status: 'needs_configuration', error_message: '', storage_size: Number(d.file_size) + images.reduce((n, x) => n + readControlled(host.db.dataRoot, x.path, x.block.sha256).length, 0), metadata: { ...object(d.metadata), process_config: process, content: parsed!.document.canonical_text, content_length: Array.from(parsed!.document.canonical_text).length, parser_document: parsed!.document as unknown as JsonObject, parser_blocks: parsed!.blocks.filter(b => b.kind === 'text') as unknown as JsonObject[], parser_image_block_indices: parsed!.blocks.filter(b => b.kind === 'image').map(b => b.block_index), parser_diagnostics: parsed!.diagnostics, image_count: images.length, effective_chunking_config: config, chunking_diagnostics: chunks.diagnostics, source_generation: String(root!.span_id), vector_status: 'needs_rebuild', workflow_status: 'processing' }, updated_at: now() });
                if (indexing(host.db.read('knowledge_bases', kbId)?.indexing_strategy).keyword_enabled)
                    host.index.indexKeywords(scope, childIds, undefined, job.checkpoint);
                host.db.run("UPDATE search_index_meta SET status='needs_rebuild',updated_at=? WHERE tenant_id=? AND knowledge_base_id=?", now(), ctx.tenantId, kbId);
                // Queue file cleanup only after publication succeeds; all paths are hashed and exclusive owned references.
                for (const old of oldImages)
                    if (old.storage_owned === 1 || old.storage_owned === true)
                        retiredFiles.push({ path: String(old.storage_path), hash: String(old.content_hash) });
            });
            published = true;
            return { status: 'completed' };
        }, r => r);
        if (deferredModelError)
            throw deferredModelError;
        const vlmConfig = allowModels && images.length ? configuration(host, ctx, String(object(kb.vlm_config).model_id ?? ''), 'VLLM') : undefined;
        await stage('multimodal', async () => {
            const cache = new Map<string, {
                ocr: string;
                caption: string;
                error: string;
            }>();
            if (images.length && !vlmConfig)
                warnings.push(warning('vlm_needs_configuration', 'multimodal'));
            for (const image of images) {
                active();
                if (!vlmConfig)
                    continue;
                const cached = cache.get(image.block.sha256);
                if (cached) {
                    image.ocr = cached.ocr;
                    image.caption = cached.caption;
                    image.error = cached.error;
                }
                else {
                    const url = `data:${image.block.mime_type};base64,${readControlled(host.db.dataRoot, image.path, image.block.sha256).toString('base64')}`;
                    for (const [scenario, prompt] of [['image_ocr', '请对图片执行精确 OCR。输出 Markdown，保留表格和布局。没有可识别文字时返回空字符串。'], ['image_caption', '请用中文描述图片中可用于知识库检索的客观信息，不要猜测不可见信息。']] as const)
                        try {
                            const result = await call(vlmConfig, scenario, r => r.vision(url, prompt, { signal: job.signal, maxTokens: 2048 }));
                            if (scenario === 'image_ocr')
                                image.ocr = result.content.trim();
                            else
                                image.caption = result.content.trim();
                        }
                        catch (error) {
                            if (resultUnknown(error) || job.signal.aborted)
                                throw error;
                            image.error = error instanceof ModelRuntimeError ? error.code : 'model_call_failed';
                            warnings.push(warning(image.error, 'multimodal'));
                        }
                    cache.set(image.block.sha256, { ocr: image.ocr, caption: image.caption, error: image.error });
                }
                image.status = image.ocr && image.caption ? 'completed' : image.ocr || image.caption ? 'partial' : 'failed';
                pub(() => { host.db.update('knowledge_images', image.id, { ocr_text: image.ocr, caption: image.caption, status: image.status, error_message: image.error, updated_at: now() }); persistMediaChunks(host, ctx, docId, kbId, image); relinkAndIndex(host, ctx, docId, kbId, job.checkpoint); });
            }
            return { image_count: images.length, image_chunk_count: images.reduce((n, x) => n + Number(!!x.ocr) + Number(!!x.caption), 0), status: images.length && !vlmConfig ? 'needs_configuration' : 'completed' };
        }, r => r);
        await stage('embedding', async () => {
            const strategy = indexing(kb.indexing_strategy, String(kb.type));
            let status = 'skipped';
            let indexed = 0;
            if (strategy.vector_enabled) {
                if (binding && embeddingConfig) {
                    const audited: EmbeddingBinding = { ...binding, runtime: { embed: texts => call(embeddingConfig, 'embedding', r => r.embed(texts, { signal: job.signal })) } };
                    try {
                        indexed = (await host.index.rebuild(scope, audited, { signal: job.signal, publish: trustedAttemptPublication(write => pub(() => { const d = active(), currentBase = host.db.read('knowledge_bases', kbId)!, current = configuration(host, ctx, String(d.embedding_model_id || currentBase.embedding_model_id || ''), 'Embedding'); if (!current || embeddingBinding(current).signature !== binding.signature)
                                throw new ModelRuntimeError('embedding_configuration_changed', 'Embedding configuration changed before publication'); write(); })) })).indexed;
                        status = 'completed';
                    }
                    catch (error) {
                        if (resultUnknown(error) || job.signal.aborted)
                            throw error;
                        status = 'failed';
                        warnings.push(warning('embedding_failed', 'embedding'));
                    }
                }
                else {
                    status = 'needs_configuration';
                    warnings.push(warning('embedding_needs_configuration', 'embedding'));
                }
            }
            pub(() => { const d = active(); host.db.update('knowledges', docId, { metadata: { ...object(d.metadata), vector_status: status }, updated_at: now() }); });
            return { status, indexed };
        }, r => r);
        // Keep canonical text unchanged: media recognition has separate source
        // references and must not invalidate text chunk offsets.
        const auxiliaryContent = [String(object(active().metadata).content ?? ''), ...images.flatMap(image => [image.ocr, image.caption])].filter(value => value.trim()).join('\n\n');
        await stage('postprocess', async () => {
            const cfg = allowModels ? configuration(host, ctx, String(kb.summary_model_id ?? ''), 'KnowledgeQA') : undefined;
            if (!cfg) {
                warnings.push(warning('summary_needs_configuration', 'summary'));
                warnings.push(warning('questions_needs_configuration', 'questions'));
                warnings.push(warning('metadata_needs_configuration', 'metadata'));
                return { status: 'needs_configuration' };
            }
            if (!auxiliaryContent.trim()) {
                const status = images.length && !vlmConfig ? 'needs_configuration' : 'failed';
                warnings.push(warning('postprocess_source_empty', 'postprocess'));
                pub(() => { host.db.update('knowledges', docId, { summary_status: status, updated_at: now() }); });
                return { status };
            }
            const d = active(), local = codepoints(auxiliaryContent, 8000);
            let summary = '', questions: Json[] = [], extracted: JsonObject = {}, summaryStatus = 'failed';
            const requests = [['summary', `请为以下知识内容生成不超过120字的中文摘要。\n标题：${d.title}\n内容：${local}`], ['questions', `根据知识内容生成5个用户问题，只输出JSON字符串数组。\n${local}`], ['metadata', `从知识内容提取标题、主题和关键词，只输出JSON对象。\n${local}`]] as const;
            const provider = resolveProvider(cfg), taskThinking = auxiliaryThinking(provider.baseUrl, provider.model);
            for (const [scenario, prompt] of requests) {
                try {
                    let value: unknown;
                    const response = await call(cfg, scenario, r => r.complete([{ role: 'user', content: prompt }], { signal: job.signal, maxTokens: scenario === 'summary' ? 400 : 1024, ...(taskThinking ? { thinking: taskThinking } : {}) }), result => {
                        if (!result.content.trim() || !/[\p{L}\p{N}]/u.test(result.content))
                            throw new ModelRuntimeError('model_output_invalid', 'Model returned no usable task content');
                        if (result.finish_reason === 'length')
                            throw new ModelRuntimeError('model_output_truncated', 'Model task output exhausted its token budget');
                        if (scenario === 'summary') return;
                        try { value = JSON.parse(result.content.replace(/^```(?:json)?\s*/, '').replace(/\s*```$/, '')); }
                        catch { throw new ModelRuntimeError(`${scenario}_output_invalid`, 'Model returned invalid task JSON'); }
                        if (scenario === 'questions' ? !Array.isArray(value) || !value.length || !value.every(x => typeof x === 'string' && x.trim()) : !value || typeof value !== 'object' || Array.isArray(value) || !Object.keys(value).length)
                            throw new ModelRuntimeError(`${scenario}_output_invalid`, 'Model returned an invalid task result');
                    });
                    if (scenario === 'summary') {
                        summary = response.content.trim();
                        summaryStatus = summary ? 'completed' : 'failed';
                    }
                    else {
                        if (scenario === 'questions') questions = value as Json[];
                        else extracted = value as JsonObject;
                    }
                }
                catch (error) {
                    if (resultUnknown(error) || job.signal.aborted)
                        throw error;
                    warnings.push(warning(error instanceof ModelRuntimeError && error.code === `${scenario}_output_invalid` ? error.code : `${scenario}_failed`, scenario));
                }
            }
            pub(() => {
                const row = active(), metadata = object(row.metadata);
                const generatedDescription = !row.description || typeof metadata.summary === 'string' && row.description === codepoints(metadata.summary, 300);
                host.db.update('knowledges', docId, { summary_status: summaryStatus, description: generatedDescription && summary ? codepoints(summary, 300) : row.description, metadata: { ...metadata, summary, generated_questions: questions, extracted_metadata: extracted }, updated_at: now() });
            });
            return { status: summaryStatus, summary_length: Array.from(summary).length, questions_count: questions.length };
        }, r => r as JsonObject);
        for (const name of ['graph', 'wiki'] as const)
            await stage(name, async () => {
                const strategy = indexing(kb.indexing_strategy, String(kb.type));
                if (!enabled(process[`${name}_enabled`], strategy[`${name}_enabled`] === true)) {
                    pub(() => { const d = active(); host.db.update('knowledges', docId, { metadata: { ...object(d.metadata), [`${name}_status`]: 'skipped', [name]: { status: 'skipped' } }, updated_at: now() }); });
                    return { status: 'skipped' };
                }
                const hook = host.hooks?.[name];
                let result: WorkflowHookResult;
                if (!hook) {
                    warnings.push(warning(`${name}_integration_pending`, name));
                    result = { status: 'pending' };
                }
                else if (!allowModels) {
                    warnings.push(warning(`${name}_manual_dispatch_required`, name));
                    result = { status: 'pending' };
                }
                else
                    try {
                        active();
                        result = await hook({ db: host.db, auth: ctx, knowledgeId: docId, knowledgeBaseId: kbId, jobId: job.jobId, attempt: job.attempt, signal: job.signal, content: auxiliaryContent, chunks: host.db.all("SELECT id FROM chunks WHERE tenant_id=? AND knowledge_base_id=? AND knowledge_id=? AND deleted_at IS NULL AND is_enabled=1 AND chunk_type IN ('text','image_ocr','image_caption') ORDER BY chunk_index,id", ctx.tenantId, kbId, docId).map(row => host.db.read('chunks', String(row.id))!), processConfig: process, publish: pub });
                        active();
                        if (!result || !['completed', 'pending', 'needs_configuration', 'failed'].includes(result.status))
                            throw new Error('hook_result_invalid');
                        if (result.warnings)
                            warnings.push(...result.warnings);
                    }
                    catch (error) {
                        if (resultUnknown(error) || job.signal.aborted)
                            throw error;
                        result = { status: 'failed' };
                        warnings.push(warning(`${name}_failed`, name));
                    }
                pub(() => { const d = active(); host.db.update('knowledges', docId, { metadata: { ...object(d.metadata), [`${name}_status`]: result.status, [name]: result.output ?? { status: result.status } }, updated_at: now() }); });
                return { status: result.status, ...result.output };
            }, r => r);
        // Queue's final outcome publisher commits document/task/root/job together.
        return { knowledge_id: docId, warnings };
    }
    finally {
        removeTemporary(host.db.dataRoot, workspace.relative);
        const live = new Set(host.db.all('SELECT storage_path FROM knowledge_images WHERE deleted_at IS NULL').map(r => String(r.storage_path)));
        for (const file of publishedFiles)
            if (!published || !live.has(file.path))
                removeOwned(host.db.dataRoot, file.path, file.hash);
        if (published)
            for (const file of retiredFiles)
                if (!live.has(file.path))
                    removeOwned(host.db.dataRoot, file.path, file.hash);
    }
}
function relinkAndIndex(host: PipelineHost, ctx: AuthContext, docId: string, kbId: string, checkpoint?: () => void): void {
    const rows = host.db.all("SELECT id FROM chunks WHERE tenant_id=? AND knowledge_base_id=? AND knowledge_id=? AND deleted_at IS NULL AND is_enabled=1 AND chunk_type IN ('text','image_ocr','image_caption') ORDER BY chunk_index,id", ctx.tenantId, kbId, docId);
    const strategy = indexing(host.db.read('knowledge_bases', kbId)?.indexing_strategy);
    for (let i = 0; i < rows.length; i++) {
        if (i % 64 === 0) checkpoint?.();
        host.db.run('UPDATE chunks SET pre_chunk_id=?,next_chunk_id=?,updated_at=? WHERE id=? AND tenant_id=? AND knowledge_base_id=? AND knowledge_id=?',
            String(rows[i - 1]?.id ?? ''), String(rows[i + 1]?.id ?? ''), now(), String(rows[i]!.id), ctx.tenantId, kbId, docId);
    }
    if (strategy.keyword_enabled)
        host.index.indexKeywords({ tenantId: ctx.tenantId, knowledgeBaseIds: [kbId] }, rows.map(row => String(row.id)), undefined, checkpoint);
}
function persistMediaChunks(host: PipelineHost, ctx: AuthContext, docId: string, kbId: string, image: ImageDraft): void {
    if (!image.ocr && !image.caption)
        return;
    const b = image.block;
    const texts = host.db.all("SELECT id FROM chunks WHERE tenant_id=? AND knowledge_base_id=? AND knowledge_id=? AND chunk_type='text' AND deleted_at IS NULL ORDER BY end_at,chunk_index,id", ctx.tenantId, kbId, docId).map(r => host.db.read('chunks', String(r.id))!);
    const anchor = texts.filter(c => Array.isArray(object(c.metadata).block_indices) && (object(c.metadata).block_indices as Json[]).some(i => Number(i) <= b.block_index)).at(-1);
    const info: JsonObject = { image_id: image.id, source_type: b.provenance.source_type ?? 'embedded', source_ref: b.provenance.source_ref ?? '', mime_type: b.mime_type, width: b.width, height: b.height, page_index: b.provenance.page_index ?? null, block_index: b.block_index, preview_url: `/api/v1/knowledge/${docId}/images/${image.id}` };
    let index = Number(host.db.get('SELECT coalesce(max(chunk_index),-1)+1 AS n FROM chunks WHERE knowledge_id=?', docId)?.n);
    const common = { tenant_id: ctx.tenantId, knowledge_base_id: kbId, knowledge_id: docId, anchor_chunk_id: anchor?.id ?? null, image_info: info, metadata: { block_index: b.block_index, provenance: b.provenance, source_refs: [b.provenance], source_generation: object(host.db.read('knowledges', docId)?.metadata).source_generation ?? null }, relation_chunks: anchor ? [anchor.id] : [] };
    const container = host.db.insert('chunks', { ...common, content: `[图片：${String(b.provenance.source_ref ?? '')}]`, chunk_index: index++, chunk_type: 'image_container', is_enabled: false, content_hash: digest(`container:${image.id}`) });
    for (const [type, content] of [['image_ocr', image.ocr], ['image_caption', image.caption]])
        if (content)
            host.db.insert('chunks', { ...common, content, chunk_index: index++, chunk_type: type, media_parent_id: container.id, content_hash: digest(content!) });
}
