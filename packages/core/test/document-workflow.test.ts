import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import test from 'node:test';
import { AuthService } from '../src/auth/index.js';
import type { ParsedDocument } from '../src/contracts.js';
import { DocumentParser } from '../src/documents/parser.js';
import { JobQueue } from '../src/jobs/queue.js';
import { SearchIndex } from '../src/retrieval/search-index.js';
import { ModelConfigurationService } from '../src/settings/model-configuration.js';
import { CoreDatabase } from '../src/storage/database.js';
import { CredentialVault } from '../src/storage/credentials.js';

test('real local publication does not rehydrate a migrated-size corpus for every new child chunk', async () => {
    const f = await fixture();
    try {
        const history = f.db.insert('knowledges', { tenant_id: f.ctx.tenantId, knowledge_base_id: f.kb.id, title: '历史来源', metadata: { content: '历史长正文😀'.repeat(20000) } });
        f.db.transaction(() => { for (let i = 0; i < 1400; i++) f.db.insert('chunks', { tenant_id: f.ctx.tenantId, knowledge_base_id: f.kb.id, knowledge_id: history.id, chunk_index: i, content: `历史预算${i}`, is_enabled: true }); });
        const created = await upload(f, 'large.md', '# 实际发布😀\n\n' + Array.from({ length: 80 }, (_, i) => `## 第${i}节\n\n${'正文预算😀与可信来源。'.repeat(45)}`).join('\n\n'));
        const read = f.db.all.bind(f.db); let hydratedRows = 0, scans = 0;
        f.db.all = ((sql: string, ...args: any[]) => { const rows = read(sql, ...args); if (sql.includes('d.metadata AS knowledge_metadata')) { scans++; hydratedRows += rows.length; } return rows; }) as typeof f.db.all;
        const completed = await f.run(created.task_id);
        assert.equal(completed.status, 'completed', completed.error);
        const children = Number(f.db.get("SELECT count(*) AS n FROM chunks WHERE knowledge_id=? AND chunk_type='text' AND is_enabled=1", created.knowledge.id)?.n);
        assert.ok(children > 50); assert.equal(scans, children); assert.equal(hydratedRows, children);
        const stage = (f.workflow.stages(f.ctx, created.knowledge.id).spans as any[]).find(s => s.name === 'publish_local');
        assert.equal(stage.status, 'done'); assert.ok(stage.finished_at);
        assert.equal(f.db.get('SELECT count(*) AS n FROM chunks WHERE knowledge_id=?', history.id)?.n, 1400);
    } finally { await f.close(); }
});
const repo = resolve('../..'), fixtures = join(repo, 'workers/document/tests/fixtures');
const python = process.env.MARLIN_TEST_PYTHON ?? '/tmp/marlin-parser-isolation-20261010/bin/python';
const sha = (data: string | Buffer) => createHash('sha256').update(data).digest('hex');
const parser = () => new DocumentParser({ pythonExecutable: python, workerPath: join(repo, 'workers/document/worker.py') });
const rejected = (p: Promise<unknown>, status: number) => assert.rejects(p, (e: any) => e.status === status);
async function eventually(work: () => boolean | Promise<boolean>) { for (let i = 0; i < 200; i++) {
    if (await work())
        return;
    await delay(10);
} assert.fail('Expected bounded workflow state transition'); }
async function fixture(options: any = {}) {
    const module = await import('../src/documents/workflow.js').catch(() => null);
    assert.ok(module, 'DocumentWorkflow must execute the authorized native document pipeline');
    const root = mkdtempSync(join(tmpdir(), 'marlin-workflow-'));
    const db = new CoreDatabase(root), auth = new AuthService(db), jobs = new JobQueue(db), index = new SearchIndex(db);
    const ctx = auth.register({ username: 'owner', password: 'DocumentFixture✓Password' }).context;
    const outsider = auth.register({ username: 'outside', password: 'DocumentFixture✓Password' }).context;
    const models = new ModelConfigurationService(db, auth, new CredentialVault(root));
    const kb = db.insert('knowledge_bases', { tenant_id: ctx.tenantId, name: '资料', indexing_strategy: { graph_enabled: false, wiki_enabled: false } });
    const scheduled: string[] = [];
    const workflow = new module.DocumentWorkflow(db, auth, jobs, models, undefined, { parser: parser(), index, scheduler: (id: string) => { scheduled.push(id); }, ...options });
    return { root, db, auth, jobs, index, ctx, outsider, models, kb, workflow, scheduled, scope: { tenantId: ctx.tenantId, knowledgeBaseIds: [String(kb.id)] }, run: (id: string) => jobs.run(id), close: async () => { await Promise.all([jobs.close(), workflow.close()]); db.close(); rmSync(root, { recursive: true, force: true }); } };
}
const upload = (f: any, name = 'test.txt', content = '真实解析预算😀内容。') => f.workflow.upload(f.ctx, String(f.kb.id), { name, bytes: Buffer.from(content) }, randomUUID());
function parsed(blocks: Array<{
    text?: string;
    type?: string;
    page?: number;
    image?: boolean;
}>): ParsedDocument {
    let offset = 0, texts = 0;
    const result = blocks.map((b, index) => {
        if (b.image)
            return { id: `b${index}`, kind: 'image' as const, block_index: index, artifact_path: 'images/a.png', sha256: sha('image'), original_mime_type: 'image/png', mime_type: 'image/png', width: 1, height: 1, provenance: { source_type: 'embedded', source_ref: 'image:1' }, metadata: {} };
        if (texts++)
            offset += 2;
        const start = offset;
        offset += Array.from(b.text!).length;
        return { id: `b${index}`, kind: 'text' as const, block_index: index, block_type: b.type ?? 'text', text: b.text!, canonical_range: { start, end: offset }, provenance: { page_index: b.page ?? null }, metadata: {} };
    });
    const content = blocks.filter(b => !b.image).map(b => b.text).join('\n\n');
    return { document: { name: 'fixture.md', input_sha256: sha(content), parser_version: 'fixture', canonicalization_version: 'blocks-double-newline-v1', offset_unit: 'unicode_code_point', canonical_text: content, canonical_sha256: sha(content) }, blocks: result, warnings: [], diagnostics: {} };
}
test('owned upload and queued task are atomic, scoped, idempotent and deduplicate same KB/name/hash', async () => {
    const f = await fixture();
    try {
        const request = randomUUID(), bytes = Buffer.from('原文😀');
        const first = await f.workflow.upload(f.ctx, String(f.kb.id), { name: '资料.txt', bytes }, request);
        const retry = await f.workflow.upload(f.ctx, String(f.kb.id), { name: '资料.txt', bytes }, request);
        const same = await f.workflow.upload(f.ctx, String(f.kb.id), { name: '资料.txt', bytes }, randomUUID());
        assert.equal(first.knowledge.id, retry.knowledge.id);
        assert.equal(first.task_id, retry.task_id);
        assert.equal(same.repeated, true);
        assert.equal(first.knowledge.id, same.knowledge.id);
        assert.equal(first.knowledge.parse_status, 'pending');
        assert.equal(f.db.get('select count(*) as n from knowledges')?.n, 1);
        assert.equal(f.db.get('select count(*) as n from desktop_jobs')?.n, 1);
        const row = f.db.read('knowledges', first.knowledge.id)!;
        assert.equal(row.file_hash, sha(bytes));
        assert.equal((row.metadata as any).storage_owned, true);
        assert.equal(readFileSync(join(f.root, String(row.file_path))).toString(), '原文😀');
        await rejected(f.workflow.upload(f.ctx, String(f.kb.id), { name: '资料.txt', bytes: Buffer.from('changed') }, request), 409);
        await rejected(f.workflow.upload(f.outsider, String(f.kb.id), { name: '资料.txt', bytes }, randomUUID()), 404);
        await rejected(f.workflow.upload(f.ctx, String(f.kb.id), { name: '../outside.txt', bytes }, randomUUID()), 400);
        await rejected(f.workflow.upload(f.ctx, String(f.kb.id), { name: 'x.txt', source: { path: '/etc/passwd' } }, randomUUID()), 400);
    }
    finally {
        await f.close();
    }
});
for (const name of ['unicode.md', 'unicode.txt', 'records.csv', 'text.pdf', 'image.png', 'scanned.pdf'])
    test(`real isolated Python parser publishes ${name}, exact sources, FTS and honest configuration warnings`, async () => {
        const worker = parser(), parse = worker.parse.bind(worker);
        let actual: ParsedDocument | undefined;
        worker.parse = async (...args) => { actual = await parse(...args); return actual; };
        const f = await fixture({ parser: worker });
        try {
            assert.equal(spawnSync(python, ['-c', 'import importlib.util; assert importlib.util.find_spec("django") is None']).status, 0);
            const created = await f.workflow.upload(f.ctx, String(f.kb.id), { name, bytes: readFileSync(join(fixtures, name)) }, randomUUID());
            const job = await f.run(created.task_id);
            assert.equal(job.status, 'completed', job.error);
            const row = f.db.read('knowledges', created.knowledge.id)!;
            const meta = row.metadata as any;
            assert.ok(actual);
            assert.deepEqual(meta.parser_blocks, actual.blocks.filter(b => b.kind === 'text'));
            assert.deepEqual(meta.parser_image_block_indices, actual.blocks.filter(b => b.kind === 'image').map(b => b.block_index));
            for (const block of meta.parser_blocks) {
                assert.equal(Array.from(meta.content).slice(block.canonical_range.start, block.canonical_range.end).join(''), block.text);
                assert.equal('artifact_path' in block, false);
            }
            assert.equal(JSON.stringify(meta.parser_blocks).includes(f.root), false);
            assert.equal(row.parse_status, 'completed');
            assert.equal(row.summary_status, 'needs_configuration');
            assert.equal(meta.vector_status, 'needs_configuration');
            assert.ok(meta.processing_warnings.some((w: any) => w.code === 'summary_needs_configuration'));
            const chunks = f.db.all('select id from chunks where knowledge_id=?', String(row.id)).map(r => f.db.read('chunks', String(r.id))!);
            for (const c of chunks.filter(c => c.chunk_type === 'text'))
                assert.equal(Array.from(meta.content).slice(Number(c.start_at), Number(c.end_at)).join(''), c.content);
            if (name.endsWith('.png') || name === 'scanned.pdf') {
                assert.ok(meta.image_count > 0);
                assert.ok(meta.processing_warnings.some((w: any) => w.code === 'vlm_needs_configuration'));
            }
            else {
                assert.ok(chunks.some(c => c.chunk_type === 'text'));
                const c = chunks.find(c => c.chunk_type === 'text')!;
                assert.ok(f.index.keyword(f.scope, Array.from(String(c.content)).slice(0, 2).join(''), 20).length);
            }
            for (const stage of f.workflow.stages(f.ctx, String(row.id)).spans)
                assert.ok(stage.finished_at, stage.name);
            assert.equal(f.jobs.events(job.id, job.scope).at(-1)?.type, 'completed');
            assert.equal(f.db.sqlite.pragma('foreign_key_check').length, 0);
        }
        finally {
            await f.close();
        }
    });
test('trusted source references and published images enforce ACL, content hashes and symlink boundaries', async () => {
    const f = await fixture();
    try {
        const first = await f.workflow.upload(f.ctx, String(f.kb.id), { name: 'image.png', bytes: readFileSync(join(fixtures, 'image.png')) }, randomUUID());
        await f.run(first.task_id);
        const source = await f.workflow.readOwnedSource(f.ctx, first.knowledge.id);
        assert.equal(sha(source.bytes), source.sha256);
        const copy = await f.workflow.upload(f.ctx, String(f.kb.id), { name: 'copy.png', source: source.source }, randomUUID());
        assert.notEqual(copy.knowledge.id, first.knowledge.id);
        await rejected(f.workflow.readOwnedSource(f.outsider, first.knowledge.id), 404);
        const image = f.db.all('select * from knowledge_images where knowledge_id=?', first.knowledge.id)[0]!;
        const media = await f.workflow.getMedia(f.ctx, first.knowledge.id, String(image.id));
        assert.equal(sha(media.bytes), image.content_hash);
        assert.equal(media.mimeType, 'image/png');
        await rejected(f.workflow.getMedia(f.outsider, first.knowledge.id, String(image.id)), 404);
        const target = join(f.root, String(image.storage_path));
        rmSync(target);
        writeFileSync(join(f.root, 'outside.png'), source.bytes);
        symlinkSync(join(f.root, 'outside.png'), target);
        await rejected(f.workflow.getMedia(f.ctx, first.knowledge.id, String(image.id)), 409);
    }
    finally {
        await f.close();
    }
});
test('six chunk strategies preserve Unicode hierarchy, protected content and media/page boundaries', async () => {
    const module = await import('../src/documents/chunker.js').catch(() => null);
    assert.ok(module, 'Native chunker must preserve existing strategies');
    for (const strategy of ['auto', 'recursive', 'heading', 'layout', 'record', 'semantic']) {
        const p = parsed([{ text: '# 标题😀\n' + '正文😀。'.repeat(90), type: 'heading', page: 0 }, { image: true }, { text: '表头\n' + '记录内容。'.repeat(90), type: 'record', page: 1 }]);
        const result = await module.splitDocument(p, { strategy, parent_chunk_size: 512, child_chunk_size: 128, child_chunk_overlap: 16 }, { title: '资料', semanticDimension: 2, semanticEmbed: async (texts: string[]) => texts.map((_: string, i: number) => [i + 1, 1]) });
        assert.equal(result.diagnostics.requested_strategy, strategy);
        assert.ok(result.parents.length >= 2);
        assert.ok(result.children.length >= 2);
        for (const c of result.children) {
            assert.equal(Array.from(p.document.canonical_text).slice(c.start_at, c.end_at).join(''), c.content);
            const parent = result.parents[c.context_parent_index!];
            assert.ok(parent && parent.start_at <= c.start_at && parent.end_at >= c.end_at);
            assert.ok(!c.metadata.block_indices.includes(0) || !c.metadata.block_indices.includes(2));
            assert.ok(c.metadata.source_refs.length);
        }
    }
    const code = '```python\n' + '😀print(1)\n'.repeat(30) + '```';
    const p = parsed([{ text: '开头\n' + code + '\n后文。'.repeat(50) }]);
    const result = await module.splitDocument(p, { strategy: 'recursive', enable_parent_child: false, chunk_size: 128, chunk_overlap: 16 }, { title: '代码' });
    assert.equal(result.children.filter((c: any) => c.content.includes('```')).length, 1);
});
test('semantic failure falls back explicitly, token budgets reject unsplittable protected blocks', async () => {
    const module = await import('../src/documents/chunker.js').catch(() => null);
    assert.ok(module);
    const p = parsed([{ text: '普通文本😀。'.repeat(100) }]);
    const result = await module.splitDocument(p, { strategy: 'semantic', enable_parent_child: false, chunk_size: 128, chunk_overlap: 16 }, { title: '资料' });
    assert.equal(result.diagnostics.selected_strategy, 'recursive');
    assert.match(result.diagnostics.fallback_chain[0].reason, /embedding/);
    await assert.rejects(module.splitDocument(parsed([{ text: '```\n' + 'x'.repeat(200) + '\n```', type: 'code' }]), { strategy: 'recursive', token_limit: 1 }, { title: '代码' }), /token_limit/);
});
test('configured real HTTP embedding, summary and VLM record each actual invocation once outside transactions', async () => {
    const f = await fixture();
    let calls = 0;
    const server = createServer(async (req, res) => { assert.equal(f.db.sqlite.inTransaction, false); let raw = ''; for await (const b of req)
        raw += b; const body = JSON.parse(raw); calls++; res.setHeader('content-type', 'application/json'); res.end(JSON.stringify(req.url?.endsWith('/embeddings') ? { data: body.input.map((_: string, index: number) => ({ index, embedding: [1, 0] })), usage: { prompt_tokens: 7, total_tokens: 7 } } : { choices: [{ message: { content: JSON.stringify(body.messages).includes('OCR') ? '识别😀预算文字' : '实际模型摘要' }, finish_reason: 'stop' }], usage: { prompt_tokens: 11, completion_tokens: 3, total_tokens: 14 } })); });
    await new Promise<void>(r => server.listen(0, '127.0.0.1', r));
    const address = server.address();
    assert.ok(address && typeof address !== 'string');
    try {
        for (const type of ['embedding', 'chat', 'vision'])
            f.models.create(f.ctx, { name: type, type, is_default: true, source: 'local', parameters: { base_url: `http://127.0.0.1:${address.port}/v1`, model: type, dimension: 2 } });
        const a = await upload(f, 'local.md', '# 标题\n真实预算😀内容。');
        assert.equal(f.jobs.get(a.task_id, { tenantId: f.ctx.tenantId, userId: f.ctx.userId }).recoveryPolicy, 'manual');
        assert.equal((await f.run(a.task_id)).status, 'completed');
        const b = await f.workflow.upload(f.ctx, String(f.kb.id), { name: 'image.png', bytes: readFileSync(join(fixtures, 'image.png')) }, randomUUID());
        assert.equal((await f.run(b.task_id)).status, 'completed');
        const rows = f.db.all('select * from model_usage');
        assert.equal(rows.length, calls);
        assert.equal(rows.reduce((n, r) => n + Number(r.request_count), 0), calls);
        assert.ok(rows.some(r => r.scenario === 'summary'));
        assert.ok(rows.some(r => r.scenario === 'image_ocr'));
        assert.ok(rows.some(r => r.scenario === 'embedding'));
        const image = f.db.all('select * from knowledge_images where knowledge_id=?', b.knowledge.id)[0]!;
        assert.equal(image.status, 'completed');
        const children = f.db.all("select * from chunks where knowledge_id=? and chunk_type in ('image_ocr','image_caption')", b.knowledge.id);
        assert.equal(children.length, 2);
        for (const c of children) {
            assert.ok(c.media_parent_id);
            assert.equal(JSON.parse(String(c.image_info)).source_ref, image.source_ref);
        }
        assert.equal(f.db.read('knowledges', a.knowledge.id)?.summary_status, 'completed');
        assert.equal(f.index.state(f.scope)[0]?.status, 'ready');
    }
    finally {
        server.closeAllConnections();
        await new Promise<void>(r => server.close(() => r()));
        await f.close();
    }
});
test('graph/wiki missing integration is pending, injected hooks publish through the job fence', async () => {
    const f = await fixture({ hooks: { graph: async (ctx: any) => { assert.ok(ctx.chunks.every((c: any) => c.is_enabled && ['text','image_ocr','image_caption'].includes(c.chunk_type))); ctx.publish(() => ctx.db.update('knowledges', ctx.knowledgeId, { description: 'hook实际执行' })); return { status: 'completed', output: { nodes: 1 } }; } } });
    try {
        f.db.update('knowledge_bases', f.kb.id, { indexing_strategy: { vector_enabled: false, graph_enabled: true, wiki_enabled: true } });
        const a = await upload(f);
        assert.equal((await f.run(a.task_id)).status, 'completed');
        const row = f.db.read('knowledges', a.knowledge.id)!;
        assert.equal(row.description, 'hook实际执行');
        assert.equal((row.metadata as any).graph_status, 'completed');
        assert.equal((row.metadata as any).wiki_status, 'pending');
        assert.ok((row.metadata as any).processing_warnings.some((w: any) => w.code === 'wiki_integration_pending'));
    }
    finally {
        await f.close();
    }
});
test('failed reparse preserves active content and original generation; cancelled queued uploads do not spawn', async () => {
    const f = await fixture();
    try {
        const a = await upload(f);
        await f.run(a.task_id);
        const before = f.db.all('select id from chunks where knowledge_id=?', a.knowledge.id);
        const row = f.db.read('knowledges', a.knowledge.id)!;
        writeFileSync(join(f.root, String(row.file_path)), 'tampered');
        const re = await f.workflow.reparse(f.ctx, a.knowledge.id, {}, randomUUID());
        assert.equal(f.db.read('knowledges', a.knowledge.id)?.parse_status, 'completed');
        assert.equal((await f.run(re.task_id)).status, 'failed');
        assert.deepEqual(f.db.all('select id from chunks where knowledge_id=?', a.knowledge.id), before);
        assert.ok(f.index.keyword(f.scope, '预算', 10).length);
        const b = await upload(f, 'queued.txt', '队列内容');
        await f.workflow.cancel(f.ctx, b.knowledge.id);
        assert.equal((await f.run(b.task_id)).status, 'cancelled');
        assert.equal(f.db.read('knowledges', b.knowledge.id)?.parse_status, 'cancelled');
    }
    finally {
        await f.close();
    }
});
test('cancellation and close stop the actual owned Python descendant before DB shutdown and reject late publication', async () => {
    const f = await fixture();
    try {
        const marker = join(f.root, 'pids.json'), worker = join(f.root, 'slow.py');
        writeFileSync(worker, `import json,os,subprocess,sys,time\np=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])\nopen(${JSON.stringify(marker)},'w').write(json.dumps({'worker':os.getpid(),'child':p.pid}))\nsys.stdin.readline()\ntime.sleep(60)\n`);
        await f.workflow.close();
        const module = await import('../src/documents/workflow.js');
        const flow = new module.DocumentWorkflow(f.db, f.auth, f.jobs, f.models, undefined, { parser: new DocumentParser({ pythonExecutable: python, workerPath: worker }), index: f.index, scheduler: () => undefined });
        const alive = (pid: number) => { try {
            process.kill(pid, 0);
            return true;
        }
        catch {
            return false;
        } };
        for (const op of ['cancel', 'close']) {
            rmSync(marker, { force: true });
            const a = await flow.upload(f.ctx, String(f.kb.id), { name: `${op}.txt`, bytes: Buffer.from('文档') }, randomUUID());
            const running = f.jobs.run(a.task_id);
            await eventually(() => existsSync(marker));
            const pids = JSON.parse(readFileSync(marker, 'utf8'));
            if (op === 'cancel')
                await flow.cancel(f.ctx, a.knowledge.id);
            else
                await flow.close();
            await running;
            await eventually(() => !alive(pids.worker) && !alive(pids.child));
            assert.equal(f.db.get('select count(*) as n from chunks where knowledge_id=?', a.knowledge.id)?.n, 0);
            assert.equal(f.jobs.get(a.task_id, { tenantId: f.ctx.tenantId, userId: f.ctx.userId }).status, 'cancelled');
        }
        await rejected(flow.upload(f.ctx, String(f.kb.id), { name: 'closed.txt', bytes: Buffer.from('a') }, randomUUID()), 503);
    }
    finally {
        await f.close();
    }
});
test('uncertain paid semantic calls preserve local parsed results and remain interrupted without automatic replay', async () => {
    const f = await fixture();
    let calls = 0;
    const server = createServer(async (req) => { for await (const _ of req) { } calls++; });
    await new Promise<void>(r => server.listen(0, '127.0.0.1', r));
    const address = server.address();
    assert.ok(address && typeof address !== 'string');
    try {
        f.models.create(f.ctx, { name: 'embedding', type: 'embedding', source: 'local', is_default: true, parameters: { base_url: `http://127.0.0.1:${address.port}/v1`, model: 'embedding', dimension: 2, timeoutMs: 60 } });
        const a = await f.workflow.upload(f.ctx, String(f.kb.id), { name: 'records.csv', bytes: readFileSync(join(fixtures, 'records.csv')), process_config: { chunking_config: { strategy: 'semantic' } } }, randomUUID());
        const job = await f.run(a.task_id);
        assert.equal(job.status, 'interrupted');
        assert.equal(calls, 1);
        const row = f.db.read('knowledges', a.knowledge.id)!;
        assert.equal(row.parse_status, 'completed');
        assert.ok((row.metadata as any).content);
        assert.ok(f.db.get('select count(*) as n from chunks where knowledge_id=?', a.knowledge.id)!.n > 0);
        assert.equal(f.db.get('select count(*) as n from model_usage')?.n, 1);
        f.workflow.recover();
        await delay(30);
        assert.equal(calls, 1);
        assert.equal(f.db.read('task_records', job.id)?.status, 'interrupted');
        for (const s of f.workflow.stages(f.ctx, a.knowledge.id).spans)
            assert.ok(s.finished_at);
    }
    finally {
        server.closeAllConnections();
        await new Promise<void>(r => server.close(() => r()));
        await f.close();
    }
});
test('revocation after dispatch retains actual vendor usage while rejecting late content and finishing source/stage records', async () => {
    const f = await fixture();
    let ready!: () => void, release!: () => void;
    const started = new Promise<void>(r => ready = r), blocked = new Promise<void>(r => release = r);
    const server = createServer(async (req, res) => { for await (const _ of req) { } ready(); await blocked; res.setHeader('content-type', 'application/json'); res.end(JSON.stringify({ choices: [{ message: { content: '不应保存的模型摘要' }, finish_reason: 'stop' }], usage: { prompt_tokens: 9, completion_tokens: 2, total_tokens: 11 } })); });
    await new Promise<void>(r => server.listen(0, '127.0.0.1', r));
    const address = server.address();
    assert.ok(address && typeof address !== 'string');
    try {
        f.models.create(f.ctx, { name: 'summary', type: 'chat', source: 'local', is_default: true, parameters: { base_url: `http://127.0.0.1:${address.port}/v1`, model: 'chat' } });
        const a = await upload(f);
        const running = f.run(a.task_id);
        await started;
        f.db.run("update tenant_members set status='revoked' where user_id=?", f.ctx.userId);
        release();
        const job = await running;
        assert.equal(job.status, 'failed');
        const row = f.db.read('knowledges', a.knowledge.id)!;
        assert.equal(row.description, '');
        assert.equal((row.metadata as any).summary, undefined);
        assert.equal(f.db.get('select count(*) as n from model_usage')?.n, 1);
        assert.equal(f.db.read('task_records', job.id)?.status, 'failed');
        assert.equal(f.db.get("select count(*) as n from knowledge_processing_spans where knowledge_id=? and finished_at is null", a.knowledge.id)?.n, 0);
    }
    finally {
        release();
        server.closeAllConnections();
        await new Promise<void>(r => server.close(() => r()));
        await f.close();
    }
});
test('recovery only dispatches safe local attempts and closes interrupted manual stage records', async () => {
    const f = await fixture();
    try {
        const a = await upload(f, 'safe.txt', '本地恢复😀'), b = await upload(f, 'manual.txt', '保留未知上游');
        for (const [value, policy] of [[a, 'safe'], [b, 'manual']] as const) {
            const row = f.db.get('select payload from desktop_jobs where id=?', value.task_id)!;
            const payload = JSON.parse(String(row.payload));
            payload.claim = { ownerToken: randomUUID(), leaseUntil: 0 };
            f.db.run("update desktop_jobs set status='running',attempt=1,recovery_policy=?,payload=? where id=?", policy, JSON.stringify(payload), value.task_id);
            f.db.update('task_records', value.task_id, { status: 'running' });
            f.db.insert('knowledge_processing_spans', { knowledge_id: value.knowledge.id, attempt: 1, span_id: randomUUID(), name: 'process_knowledge', kind: 'root', status: 'running', started_at: new Date().toISOString(), metadata: { job_id: value.task_id, queue_attempt: 1 } });
        }
        const result = f.workflow.recover();
        assert.deepEqual(result, { safe: 1, manual: 1 });
        assert.equal(f.jobs.get(b.task_id, { tenantId: f.ctx.tenantId, userId: f.ctx.userId }).status, 'interrupted');
        assert.equal(f.db.read('task_records', b.task_id)?.status, 'interrupted');
        assert.equal(f.db.get("select count(*) as n from knowledge_processing_spans where knowledge_id=? and status='running'", b.knowledge.id)?.n, 0);
        assert.equal((await f.run(a.task_id)).status, 'completed');
        assert.equal(f.db.read('task_records', a.task_id)?.status, 'completed');
        assert.equal(f.db.get('select count(*) as n from model_usage')?.n, 0);
    }
    finally {
        await f.close();
    }
});
test('upload rollback cleans exclusive source bytes and request conflicts preserve all previous data', async () => {
    const f = await fixture();
    try {
        const request = randomUUID();
        const unrelated = f.jobs.create({ scope: { tenantId: f.ctx.tenantId, userId: f.ctx.userId }, requestId: request, kind: 'other_domain', payload: { keep: true }, recoveryPolicy: 'safe' });
        await rejected(f.workflow.upload(f.ctx, String(f.kb.id), { name: 'conflict.txt', bytes: Buffer.from('private') }, request), 409);
        assert.equal(f.db.get('select count(*) as n from knowledges')?.n, 0);
        assert.equal(f.jobs.get(unrelated.id, unrelated.scope).payload.keep, true);
        const trigger = 'reject_document_job';
        f.db.sqlite.exec(`CREATE TRIGGER ${trigger} BEFORE INSERT ON desktop_jobs WHEN NEW.kind='process_knowledge' BEGIN SELECT RAISE(ABORT,'fixture_job_failure'); END`);
        await assert.rejects(upload(f), /fixture_job_failure/);
        assert.equal(f.db.get('select count(*) as n from knowledges')?.n, 0);
        const files = (path: string): string[] => existsSync(path) ? readdirSync(path, { withFileTypes: true }).flatMap(entry => entry.isDirectory() ? files(join(path, entry.name)) : [join(path, entry.name)]) : [];
        assert.deepEqual(files(join(f.root, 'media')), []);
    }
    finally {
        await f.close();
    }
});
test('deduplicated upload request IDs remain bound to their original source operation', async () => {
    const f = await fixture();
    try {
        const a = await upload(f, 'same.txt', '相同内容'), request = randomUUID();
        const repeated = await f.workflow.upload(f.ctx, String(f.kb.id), { name: 'same.txt', bytes: Buffer.from('相同内容') }, request);
        assert.equal(repeated.knowledge.id, a.knowledge.id);
        await rejected(f.workflow.upload(f.ctx, String(f.kb.id), { name: 'changed.txt', bytes: Buffer.from('别的内容') }, request), 409);
        assert.equal(f.db.get('select count(*) as n from knowledges')?.n, 1);
    }
    finally {
        await f.close();
    }
});
test('embedding model changes during a real pending response fence the old dimension generation', async () => {
    const f = await fixture();
    let ready!: () => void, release!: () => void;
    const started = new Promise<void>(r => ready = r), blocked = new Promise<void>(r => release = r);
    const server = createServer(async (req, res) => { let raw = ''; for await (const b of req)
        raw += b; const body = JSON.parse(raw); ready(); await blocked; res.setHeader('content-type', 'application/json'); res.end(JSON.stringify({ data: body.input.map((_: string, index: number) => ({ index, embedding: [1, 0] })), usage: { prompt_tokens: 5, total_tokens: 5 } })); });
    await new Promise<void>(r => server.listen(0, '127.0.0.1', r));
    const address = server.address();
    assert.ok(address && typeof address !== 'string');
    try {
        const model = f.models.create(f.ctx, { name: 'embedding', type: 'embedding', source: 'local', is_default: true, parameters: { base_url: `http://127.0.0.1:${address.port}/v1`, model: 'embedding', dimension: 2 } });
        const a = await upload(f);
        const running = f.run(a.task_id);
        await started;
        f.models.update(f.ctx, String(model.id), { parameters: { dimension: 3 } });
        release();
        const job = await running;
        assert.equal(job.status, 'completed');
        assert.ok(f.index.state(f.scope).every(s => s.status !== 'ready' || s.dimension === 3));
        assert.equal((f.db.read('knowledges', a.knowledge.id)?.metadata as any).vector_status, 'failed');
        assert.ok(f.index.keyword(f.scope, '预算', 10).length);
        assert.equal(f.db.get('select count(*) as n from model_usage')?.n, 1);
    }
    finally {
        release();
        server.closeAllConnections();
        await new Promise<void>(r => server.close(() => r()));
        await f.close();
    }
});
test('semantic cache is scoped by stable model identity and reparse reuses real validated embeddings', async () => {
    const f = await fixture();
    let calls = 0;
    const server = createServer(async (req, res) => { let raw = ''; for await (const b of req)
        raw += b; const body = JSON.parse(raw); calls++; res.setHeader('content-type', 'application/json'); res.end(JSON.stringify({ data: body.input.map((_: string, index: number) => ({ index, embedding: [1, index + 1] })), usage: { prompt_tokens: body.input.length, total_tokens: body.input.length } })); });
    await new Promise<void>(r => server.listen(0, '127.0.0.1', r));
    const address = server.address();
    assert.ok(address && typeof address !== 'string');
    try {
        f.models.create(f.ctx, { name: 'embedding', type: 'embedding', source: 'local', is_default: true, parameters: { base_url: `http://127.0.0.1:${address.port}/v1`, model: 'embedding', dimension: 2 } });
        const a = await f.workflow.upload(f.ctx, String(f.kb.id), { name: 'records.csv', bytes: readFileSync(join(fixtures, 'records.csv')), process_config: { chunking_config: { strategy: 'semantic' } } }, randomUUID());
        assert.equal((await f.run(a.task_id)).status, 'completed');
        const before = calls;
        assert.equal((f.db.read('knowledges', a.knowledge.id)?.metadata as any).chunking_diagnostics.selected_strategy, 'semantic');
        assert.equal(f.db.get('select count(*) as n from semantic_chunk_cache')?.n, 1);
        const re = await f.workflow.reparse(f.ctx, a.knowledge.id, undefined, randomUUID());
        assert.equal((await f.run(re.task_id)).status, 'completed');
        assert.equal(calls - before, 1);
        assert.equal(f.db.get('select count(*) as n from model_usage')?.n, calls);
        assert.equal(f.db.get('select count(*) as n from semantic_chunk_cache')?.n, 1);
    }
    finally {
        server.closeAllConnections();
        await new Promise<void>(r => server.close(() => r()));
        await f.close();
    }
});
test('safe queued local jobs cannot become paid after later model configuration changes', async () => {
    const f = await fixture();
    let calls = 0;
    const server = createServer(async (req, res) => { for await (const _ of req) { } calls++; res.setHeader('content-type', 'application/json'); res.end(JSON.stringify({ choices: [{ message: { content: 'later model' }, finish_reason: 'stop' }] })); });
    await new Promise<void>(r => server.listen(0, '127.0.0.1', r));
    const address = server.address();
    assert.ok(address && typeof address !== 'string');
    try {
        const a = await upload(f);
        assert.equal(f.jobs.get(a.task_id, { tenantId: f.ctx.tenantId, userId: f.ctx.userId }).recoveryPolicy, 'safe');
        f.models.create(f.ctx, { name: 'later', type: 'chat', source: 'local', is_default: true, parameters: { base_url: `http://127.0.0.1:${address.port}/v1`, model: 'later' } });
        assert.equal((await f.run(a.task_id)).status, 'completed');
        assert.equal(calls, 0);
        assert.equal(f.db.read('knowledges', a.knowledge.id)?.summary_status, 'needs_configuration');
        const re = await f.workflow.reparse(f.ctx, a.knowledge.id, {}, randomUUID());
        assert.equal(f.jobs.get(re.task_id, { tenantId: f.ctx.tenantId, userId: f.ctx.userId }).recoveryPolicy, 'manual');
        assert.equal((await f.run(re.task_id)).status, 'completed');
        assert.ok(calls > 0);
    }
    finally {
        server.closeAllConnections();
        await new Promise<void>(r => server.close(() => r()));
        await f.close();
    }
});

test('an injected graph hook with an uncertain real HTTP result remains manual and interrupted', async () => {
    let calls = 0;
    const server = createServer(async (req) => { for await (const _ of req) { } calls++; req.socket.destroy(); });
    await new Promise<void>(r => server.listen(0, '127.0.0.1', r));
    const address = server.address(); assert.ok(address && typeof address !== 'string');
    const f = await fixture({ hooks: { graph: async (ctx: any) => {
        assert.equal(ctx.db.sqlite.inTransaction, false);
        try { await fetch(`http://127.0.0.1:${address.port}/graph`, { method: 'POST', body: 'controlled-fixture', signal: ctx.signal }); }
        catch { throw Object.assign(new Error('Uncertain fixture result'), { resultUnknown: true }); }
        return { status: 'completed' };
    } } });
    try {
        f.db.update('knowledge_bases', f.kb.id, { indexing_strategy: { vector_enabled: false, graph_enabled: true, wiki_enabled: false } });
        const a = await upload(f); const job = await f.run(a.task_id);
        assert.equal(job.recoveryPolicy, 'manual'); assert.equal(job.status, 'interrupted'); assert.equal(calls, 1);
        assert.equal(f.db.read('task_records', job.id)?.status, 'interrupted');
        assert.equal((f.db.read('knowledges', a.knowledge.id)?.metadata as any).workflow_status, 'interrupted');
        f.workflow.recover(); await delay(20); assert.equal(calls, 1);
    } finally { server.closeAllConnections(); await new Promise<void>(r => server.close(() => r())); await f.close(); }
});

test('a real SQLite publication commit failure retains the previous owned image bytes and references', async () => {
    const f = await fixture();
    try {
        const a = await f.workflow.upload(f.ctx, String(f.kb.id), { name: 'image.png', bytes: readFileSync(join(fixtures, 'image.png')) }, randomUUID());
        assert.equal((await f.run(a.task_id)).status, 'completed');
        const image = f.db.all('select id from knowledge_images where knowledge_id=?', a.knowledge.id)[0]!;
        const before = await f.workflow.getMedia(f.ctx, a.knowledge.id, String(image.id));
        // Defer a real FK violation until COMMIT, after the publication callback
        // has completed its chunk/media changes and queued old artifact cleanup.
        f.db.sqlite.exec(`CREATE TRIGGER fixture_deferred_publication AFTER UPDATE ON knowledges
          WHEN json_extract(NEW.metadata,'$.source_generation') <> json_extract(OLD.metadata,'$.source_generation')
          BEGIN UPDATE knowledge_images SET knowledge_base_id='missing-fixture-base' WHERE knowledge_id=NEW.id; END`);
        const transaction = f.db.transaction.bind(f.db);
        f.db.transaction = work => transaction(() => { f.db.sqlite.pragma('defer_foreign_keys=ON'); return work(); });
        const re = await f.workflow.reparse(f.ctx, a.knowledge.id, {}, randomUUID());
        assert.equal((await f.run(re.task_id)).status, 'failed');
        const after = await f.workflow.getMedia(f.ctx, a.knowledge.id, String(image.id));
        assert.equal(after.sha256, before.sha256); assert.deepEqual(after.bytes, before.bytes);
        assert.equal(f.db.sqlite.pragma('foreign_key_check').length, 0);
    } finally { await f.close(); }
});
