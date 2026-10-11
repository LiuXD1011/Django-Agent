import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { readFile, writeFile, symlink } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { DocumentParser } from '../src/documents/parser.js';
import { test } from 'node:test';
import { AuthService } from '../src/auth/index.js';
import { CoreDatabase } from '../src/storage/database.js';
import { CredentialVault } from '../src/storage/credentials.js';
import { ModelConfigurationService } from '../src/settings/model-configuration.js';
import { SearchIndex } from '../src/retrieval/search-index.js';
import { JobQueue } from '../src/jobs/queue.js';

async function fixture() {
  const module = await import('../src/chat/index.js').catch(() => null);
  assert.ok(module, 'ChatService must implement the approved real chat business');
  const root = mkdtempSync(join(tmpdir(), 'marlin-chat-'));
  const db = new CoreDatabase(root), auth = new AuthService(db), jobs = new JobQueue(db), index = new SearchIndex(db);
  const ctx = auth.register({ username: 'alice', password: 'Chat✓Password' }).context;
  const bob = auth.register({ username: 'bob', password: 'Chat✓Password' }).context;
  let calls = 0, visionText = '图片识别✓'; const bodies: any[] = []; let release: (() => void) | undefined;
  const server = createServer(async (req, res) => {
    assert.equal(db.sqlite.inTransaction, false);
    let raw = ''; for await (const part of req) raw += part;
    const body = JSON.parse(raw); bodies.push(body); calls++;
    const query = JSON.stringify(body.messages);
    if (query.includes('PAUSE')) await new Promise<void>(resolve => { release = resolve; req.on('close', resolve); });
    if (!body.stream) { res.setHeader('content-type', 'application/json'); res.end(JSON.stringify({ choices: [{ message: { content: visionText }, finish_reason: 'stop' }], usage: { prompt_tokens: 9, completion_tokens: 3, total_tokens: 12 } })); return; }
    res.setHeader('content-type', 'text/event-stream');
    res.write(`data: ${JSON.stringify({ choices: [{ delta: { reasoning_content: '逐步推理' } }] })}\n\n`);
    res.write(`data: ${JSON.stringify({ choices: [{ delta: { content: '真实回答✓' } }] })}\n\n`);
    if (query.includes('CUT')) { res.end(); return; }
    res.end(`data: ${JSON.stringify({ choices: [{ delta: {}, finish_reason: 'stop' }], usage: { prompt_tokens: 17, completion_tokens: 5, total_tokens: 22, prompt_tokens_details: { cached_tokens: 3 }, completion_tokens_details: { reasoning_tokens: 2 } } })}\n\ndata: [DONE]\n\n`);
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = server.address(); assert.ok(address && typeof address !== 'string');
  const models = new ModelConfigurationService(db, auth, new CredentialVault(root));
  const model = models.create(ctx, { name: 'fixture', source: 'openai', type: 'KnowledgeQA', is_default: true, parameters: { model: 'fixture', base_url: `http://127.0.0.1:${address.port}/v1`, api_key: 'test-only-secret' } });
  const chat = new module.ChatService(db, auth, { models, index, jobs });
  const session = chat.create(ctx, { title: '新的对话' });
  return { ...module, root, db, auth, jobs, index, models, model, ctx, bob, chat, session, calls: () => calls, bodies, visionText: (value: string) => { visionText = value; }, release: () => release?.(), close: async () => { release?.(); await chat.close(); await jobs.close(); await new Promise<void>(resolve => { server.closeAllConnections(); server.close(() => resolve()); }); db.close(); rmSync(root, { recursive: true, force: true }); } };
}
const rejected = (work: () => unknown, status: number) => assert.throws(work, (error: any) => error.status === status);
const waitFor = async (work: () => boolean) => { for (let n = 0; n < 100 && !work(); n++) await new Promise(resolve => setTimeout(resolve, 10)); assert.ok(work()); };

test('session state, query pagination, pin, metadata and tenant/user privacy retain original DTOs', async () => {
  const f = await fixture(); try {
    const s = f.chat.create(f.ctx, { title: '研发', agent_config: { knowledge_base_ids: [], opaque: { retained: true } } });
    assert.deepEqual(s.last_request_state.knowledge_base_ids, []);
    assert.equal(f.chat.pin(f.ctx, s.id, true).is_pinned, true);
    assert.equal(f.chat.list(f.ctx, { page_size: 1 }).items[0].id, s.id);
    assert.equal(f.chat.list(f.ctx, { query: '研发' }).total, 1);
    f.chat.update(f.ctx, s.id, { description: '说明', agent_config: { web_search_enabled: true } });
    assert.deepEqual((f.db.read('sessions', s.id)?.agent_config as any).opaque, { retained: true });
    rejected(() => f.chat.get(f.bob, s.id), 404);
    f.db.update('users', f.ctx.userId, { is_system_admin: true, can_access_all_tenants: true });
    rejected(() => f.chat.get(f.bob, s.id), 404);
    const unowned = f.db.insert('sessions', { tenant_id: f.ctx.tenantId, user_id: '', title: 'legacy' });
    rejected(() => f.chat.get(f.ctx, unowned.id), 404); assert.ok(f.db.read('sessions', unowned.id));
  } finally { await f.close(); }
});

test('real runtime stream persists reasoning, original SSE DTO, usage, history and request idempotency', async () => {
  const f = await fixture(); try {
    const start = f.chat.start(f.ctx, f.session.id, { query: '第一次', knowledge_base_ids: [] }, 'request-one');
    const run = f.chat.run(f.ctx, f.session.id, start.request_id);
    const events: any[] = []; for await (const event of f.chat.stream(f.ctx, f.session.id, start.request_id)) events.push(event);
    await run;
    assert.equal(events[0].event, 'message_start');
    assert.ok(events.some(e => e.data.reasoning_content === '逐步推理'));
    assert.equal(events.at(-1).event, 'done');
    const response = f.chat.response(f.ctx, f.session.id, start.request_id);
    assert.equal(response.answer, '真实回答✓'); assert.equal(response.message.is_completed, true);
    assert.equal(response.message.agent_steps[0].reasoning, '逐步推理');
    assert.equal(f.chat.start(f.ctx, f.session.id, { query: '第一次', knowledge_base_ids: [] }, 'request-one').idempotent, true);
    await f.chat.run(f.ctx, f.session.id, start.request_id); assert.equal(f.calls(), 1);
    const usage = f.db.all('select * from model_usage'); assert.equal(usage.length, 1); assert.equal(usage[0]?.total_tokens, 22); assert.equal(usage[0]?.reasoning_tokens, 2);
    const trajectory = f.chat.trajectory(f.ctx, f.session.id); assert.equal(trajectory.turns[0].usage.total_tokens, 22);
    const next = f.chat.start(f.ctx, f.session.id, { query: '第二次', knowledge_base_ids: [] }, 'request-two');
    await f.chat.run(f.ctx, f.session.id, next.request_id);
    assert.ok(f.bodies[1].messages.some((m: any) => m.role === 'assistant' && m.content === '真实回答✓'));
    assert.equal(JSON.stringify(response).includes('test-only-secret'), false);
    const history = f.chat.loadMessages(f.ctx, f.session.id, { limit: 2 }); assert.equal(history.items.length, 2); assert.equal(history.messages.length, 2);
  } finally { await f.close(); }
});

test('explicit empty knowledge selection never expands scope, missing selection searches real scoped FTS', async () => {
  const f = await fixture(); try {
    const kb = f.db.insert('knowledge_bases', { tenant_id: f.ctx.tenantId, name: '预算资料' });
    const d = f.db.insert('knowledges', { tenant_id: f.ctx.tenantId, knowledge_base_id: kb.id, title: '预算', type: 'file', source: '预算' });
    const c = f.db.insert('chunks', { tenant_id: f.ctx.tenantId, knowledge_base_id: kb.id, knowledge_id: d.id, content: '预算证据原文', seq_id: '1152921504606846975' });
    f.index.indexKeyword({ tenantId: f.ctx.tenantId }, c.id);
    const all = f.chat.start(f.ctx, f.session.id, { query: '预算' }, 'scope-all'); await f.chat.run(f.ctx, f.session.id, all.request_id);
    assert.equal(f.chat.response(f.ctx, f.session.id, all.request_id).references[0].seq_id, '1152921504606846975');
    const none = f.chat.start(f.ctx, f.session.id, { query: '预算', knowledge_base_ids: [] }, 'scope-none'); await f.chat.run(f.ctx, f.session.id, none.request_id);
    assert.deepEqual(f.chat.response(f.ctx, f.session.id, none.request_id).references, []);
    const saved = f.chat.start(f.ctx, f.session.id, { query: '预算' }, 'scope-saved'); await f.chat.run(f.ctx, f.session.id, saved.request_id);
    assert.deepEqual(f.chat.response(f.ctx, f.session.id, saved.request_id).references, []);
    rejected(() => f.chat.start(f.bob, f.session.id, { query: '预算' }, 'private'), 404);
  } finally { await f.close(); }
});

test('request-ID stop before assistant creation persists cancellation without issuing a model request', async () => {
  const f = await fixture(); try {
    assert.equal(f.chat.stop(f.ctx, f.session.id, 'early-request').stopped, true);
    const start = f.chat.start(f.ctx, f.session.id, { query: '不应付费', knowledge_base_ids: [] }, 'early-request');
    await f.chat.run(f.ctx, f.session.id, start.request_id);
    assert.equal(f.calls(), 0); assert.equal(f.chat.response(f.ctx, f.session.id, start.request_id).message.is_completed, true);
    rejected(() => f.chat.stop(f.bob, f.session.id, 'foreign-request'), 404);
  } finally { await f.close(); }
});

test('truncated paid stream becomes interrupted, partial result survives and reconnect never replays payment', async () => {
  const f = await fixture(); try {
    const start = f.chat.start(f.ctx, f.session.id, { query: 'CUT', knowledge_base_ids: [] }, 'cut-request');
    await f.chat.run(f.ctx, f.session.id, start.request_id);
    assert.equal(f.jobs.get(start.job_id, { tenantId: f.ctx.tenantId, userId: f.ctx.userId }).status, 'interrupted');
    const message = f.chat.response(f.ctx, f.session.id, start.request_id).message;
    assert.equal(message.content, '真实回答✓'); assert.equal(message.is_fallback, true);
    const replay: any[] = []; for await (const event of f.chat.stream(f.ctx, f.session.id, start.request_id)) replay.push(event);
    await f.chat.run(f.ctx, f.session.id, start.request_id); assert.equal(f.calls(), 1); assert.equal(replay.at(-1).event, 'done');
    assert.equal(f.db.all('select * from model_usage')[0]?.success, 0);
  } finally { await f.close(); }
});

test('cancel and shutdown await real HTTP workers, preserve terminal content and prevent late writes', async () => {
  const f = await fixture(); try {
    const start = f.chat.start(f.ctx, f.session.id, { query: 'PAUSE', knowledge_base_ids: [] }, 'pause-request');
    const work = f.chat.run(f.ctx, f.session.id, start.request_id); await waitFor(() => f.calls() === 1);
    f.chat.stop(f.ctx, f.session.id, start.request_id); await work;
    assert.equal(f.chat.response(f.ctx, f.session.id, start.request_id).message.is_completed, true);
    f.release(); await f.chat.close();
    rejected(() => f.chat.start(f.ctx, f.session.id, { query: 'closed' }, 'closed-request'), 503);
    const count = f.db.all('select * from model_usage').length; await new Promise(resolve => setTimeout(resolve, 30)); assert.equal(f.db.all('select * from model_usage').length, count);
  } finally { await f.close(); }
});

test('branch copies legacy facts, deleting a branch or clearing messages never affects another owner/source', async () => {
  const f = await fixture(); try {
    const user = f.db.insert('messages', { session_id: f.session.id, request_id: 'legacy', role: 'user', content: '历史', is_completed: true, images: [{ url: 'data:image/png;base64,AA==', caption: '旧图片' }], attachments: [{ file_name: 'x.txt', file_size: 2 }], mentioned_items: [{ id: 'old', type: 'kb' }] });
    const answer = f.db.insert('messages', { session_id: f.session.id, request_id: 'legacy', role: 'assistant', content: '历史答案', is_completed: true, knowledge_references: [{ seq_id: '1152921504606846975' }], agent_steps: [{ reasoning: '旧推理' }], agent_duration_ms: 456 });
    const branch = f.chat.branch(f.ctx, f.session.id, { message_id: answer.id });
    const history = f.chat.loadMessages(f.ctx, branch.id); assert.equal(history.items.length, 2); assert.notEqual(history.items[0].id, user.id); assert.equal(history.items[1].agent_duration_ms, 456);
    await f.chat.clearMessages(f.ctx, branch.id); assert.equal(f.chat.loadMessages(f.ctx, branch.id).items.length, 0); assert.equal(f.chat.loadMessages(f.ctx, f.session.id).items.length, 2);
    await f.chat.delete(f.ctx, branch.id); assert.equal(f.chat.list(f.ctx).total, 1); assert.ok(f.db.read('messages', answer.id));
  } finally { await f.close(); }
});

test('automatic maintenance has an independent manual job, real provider audit and shutdown lifetime', async () => {
  const f = await fixture(); try {
    f.chat.dependencies.hooks = { maintenance: async execution => { execution.assert(); const answer = await execution.calls.complete('KnowledgeQA', [{ role: 'user', content: '维护调用' }], { signal: execution.signal }, 'chat_maintenance'); execution.publish(() => f.db.run('insert into desktop_meta(key,value) values(?,?)', 'fixture.maintenance', JSON.stringify(answer.content))); } };
    const start = f.chat.start(f.ctx, f.session.id, { query: '主回答', knowledge_base_ids: [] }, 'with-maintenance'); await f.chat.run(f.ctx, f.session.id, start.request_id);
    await waitFor(() => !!f.db.get('select key from desktop_meta where key=?', 'fixture.maintenance'));
    assert.equal(f.calls(), 2); assert.equal(f.db.all('select * from model_usage').length, 2);
    assert.equal(f.chat.response(f.ctx, f.session.id, start.request_id).message.is_completed, true);
  } finally { await f.close(); }
});

test('image caption and inline attachments use real runtime and survive historical context', async () => {
  const f = await fixture(); try {
    f.models.create(f.ctx, { name: 'vision-fixture', type: 'VLLM', source: 'openai', is_default: true, parameters: { model: 'vision-fixture', base_url: (f.models.configuration(f.ctx, 'KnowledgeQA').parameters.base_url) } });
    const start = f.chat.start(f.ctx, f.session.id, { query: '分析图片和附件', knowledge_base_ids: [], images: [{ data: 'data:image/png;base64,AA==' }], attachment_uploads: [{ data: Buffer.from('文本附件事实').toString('base64'), file_name: 'facts.txt', file_size: 18 }] }, 'image-request');
    await f.chat.run(f.ctx, f.session.id, start.request_id); assert.equal(f.calls(), 2);
    assert.ok(JSON.stringify(f.bodies[1].messages).includes('图片识别✓')); assert.ok(JSON.stringify(f.bodies[1].messages).includes('文本附件事实'));
    const user = f.chat.loadMessages(f.ctx, f.session.id).items[0]; assert.equal(user.images[0].caption, '图片识别✓'); assert.equal(user.attachments[0].file_name, 'facts.txt'); assert.equal('data' in user.attachments[0], false);
  } finally { await f.close(); }
});

test('delete_all handles more than a page of history and preserves another owner', async () => {
  const f = await fixture(); try {
    for (let n = 0; n < 205; n++) f.db.insert('sessions', { tenant_id: f.ctx.tenantId, user_id: f.ctx.userId, title: `history-${n}` });
    const other = f.chat.create(f.bob, { title: 'private' });
    await f.chat.batchDelete(f.ctx, { delete_all: true }); assert.equal(f.chat.list(f.ctx).total, 0); assert.equal(f.chat.get(f.bob, other.id).title, 'private');
  } finally { await f.close(); }
});

test('slow automatic maintenance returns the answer first, closes its real HTTP request and cannot publish late', async () => {
  const f = await fixture(); try {
    f.chat.dependencies.hooks = { maintenance: async execution => { await execution.calls.complete('KnowledgeQA', [{ role: 'user', content: 'PAUSE maintenance' }], { signal: execution.signal }, 'chat_maintenance'); execution.publish(() => f.db.run('insert into desktop_meta(key,value) values(?,?)', 'late.maintenance', '{}')); } };
    const start = f.chat.start(f.ctx, f.session.id, { query: '先返回主回答', knowledge_base_ids: [] }, 'slow-maintenance'); await f.chat.run(f.ctx, f.session.id, start.request_id);
    await waitFor(() => f.calls() === 2); assert.equal(f.chat.response(f.ctx, f.session.id, start.request_id).answer, '真实回答✓');
    await f.chat.close(); assert.equal(f.db.get('select key from desktop_meta where key=?', 'late.maintenance'), undefined);
    assert.equal(f.db.all("select status from desktop_jobs where kind='chat.maintenance'")[0]?.status, 'cancelled');
    const audits = f.db.all('select * from model_usage'); assert.equal(audits.length, 2); assert.equal(audits.filter(row => !row.success).length, 1);
    f.release(); await new Promise(resolve => setTimeout(resolve, 30)); assert.equal(f.db.all('select * from model_usage').length, 2);
  } finally { await f.close(); }
});

test('managed chat uploads scope bytes to the exact owner and session and reject tampering and renderer paths', async () => {
  const f = await fixture(); try {
    assert.ok(f.ManagedChatUploads, 'owned upload service must exist'); const uploads = new f.ManagedChatUploads(f.db, f.auth), other = f.chat.create(f.ctx, {});
    const upload = await uploads.store(f.ctx, f.session.id, { name: 'notes.txt', bytes: Buffer.from('私有事实😀') });
    assert.equal(upload.file_size, Buffer.byteLength('私有事实😀')); assert.equal('path' in upload, false); assert.equal((await uploads.read(f.ctx, f.session.id, upload.upload_id)).bytes.toString(), '私有事实😀');
    await assert.rejects(() => uploads.read(f.ctx, other.id, upload.upload_id), (e: any) => e.status === 404); await assert.rejects(() => uploads.read(f.bob, f.session.id, upload.upload_id), (e: any) => e.status === 404);
    await assert.rejects(() => uploads.store(f.ctx, f.session.id, { name: '../arbitrary.txt', bytes: Buffer.from('bad') }), (e: any) => e.status === 400);
    const metadata = JSON.parse(String(f.db.get('select value from desktop_meta where key=?', `chat.upload:${upload.upload_id}`)!.value)); await writeFile(join(f.root, metadata.asset_path), '被替换的字节');
    await assert.rejects(() => uploads.read(f.ctx, f.session.id, upload.upload_id), (e: any) => e.code === 'upload_source_changed');
    f.chat.dependencies.hooks = f.createChatAttachmentHooks(f.db, f.auth, { uploads });
    const start = f.chat.start(f.ctx, f.session.id, { query: '不得读取任意路径', knowledge_base_ids: [], attachment_uploads: [{ file_name: 'secret.txt', path: '/etc/passwd' }] }, 'invalid-local-file');
    await f.chat.run(f.ctx, f.session.id, start.request_id); assert.equal(f.calls(), 0);
  } finally { await f.close(); }
});

test('real chat attachment parser reads managed DOCX/PDF/text and indexed image captions survive history without exposing paths', async () => {
  const f = await fixture(); try {
    assert.ok(f.createChatAttachmentHooks, 'trusted parser adapter must exist');
    const pythonExecutable = spawnSync('python', ['-c', 'import sys; print(sys.executable)'], { encoding: 'utf8' }).stdout.trim();
    const parser = new DocumentParser({ pythonExecutable, workerPath: resolve('../../workers/document/worker.py') });
    f.chat.dependencies.hooks = f.createChatAttachmentHooks(f.db, f.auth, { parser });
    f.models.create(f.ctx, { name: 'vision-fixture', type: 'VLLM', source: 'openai', is_default: true, parameters: { model: 'vision-fixture', base_url: f.models.configuration(f.ctx, 'KnowledgeQA').parameters.base_url } });
    const png = await readFile(resolve('../../workers/document/tests/fixtures/small.png'));
    const attachments = await Promise.all(['unicode.txt', 'table.docx', 'text.pdf'].map(async name => { const bytes = await readFile(resolve('../../workers/document/tests/fixtures', name)); return { file_name: name, data: bytes.toString('base64'), file_size: bytes.length }; }));
    const start = f.chat.start(f.ctx, f.session.id, { query: '实际附件', knowledge_base_ids: [], images: [{ data: `data:image/png;base64,${png.toString('base64')}` }], attachment_uploads: attachments }, 'actual-managed-files');
    await f.chat.run(f.ctx, f.session.id, start.request_id); const user = f.chat.loadMessages(f.ctx, f.session.id).items[0];
    assert.equal(user.images[0].caption, '图片识别✓'); assert.ok(user.images[0].upload_id); assert.match(user.images[0].url, /^\/api\/v1\/sessions\//); assert.ok(user.attachments.every((v: any) => v.upload_id && v.preparation_state === 'ready'));
    const rendered = f.db.read('messages', user.id)!.rendered_content; assert.ok(String(rendered).includes('季度收入😀')); assert.ok(String(rendered).includes('unicode.txt')); assert.ok(String(rendered).includes('table.docx')); assert.ok(String(rendered).includes('text.pdf')); assert.equal(JSON.stringify(user).includes(f.root), false);
    const beforeFollowup = f.calls(); assert.equal(f.bodies.filter((v: any) => !v.stream).length, 3, 'one direct image and two actual parser image blocks');
    const next = f.chat.start(f.ctx, f.session.id, { query: '沿用附件事实', knowledge_base_ids: [] }, 'managed-followup'); await f.chat.run(f.ctx, f.session.id, next.request_id); assert.ok(JSON.stringify(f.bodies.at(-1).messages).includes('季度收入😀')); assert.equal(f.calls(), beforeFollowup + 1);
    const branch = f.chat.branch(f.ctx, f.session.id), imageId = user.images[0].upload_id; assert.ok(f.chat.loadMessages(f.ctx, branch.id).items[0].images[0].url.includes(branch.id));
    await f.chat.clearMessages(f.ctx, f.session.id); assert.equal((await f.chat.dependencies.hooks.uploads.read(f.ctx, branch.id, imageId)).bytes.length, png.length);
    await f.chat.delete(f.ctx, branch.id); await assert.rejects(() => f.chat.dependencies.hooks.uploads.read(f.ctx, branch.id, imageId), (e: any) => e.status === 404);
    assert.equal(f.db.all("select * from desktop_meta where key like 'chat.upload:%'").length, 0);
  } finally { await f.close(); }
});

test('blank vision response terminates without a fabricated main answer or paid replay', async () => {
  const f = await fixture(); try {
    f.visionText('   '); f.models.create(f.ctx, { name: 'vision-fixture', type: 'VLLM', source: 'openai', is_default: true, parameters: { model: 'vision-fixture', base_url: f.models.configuration(f.ctx, 'KnowledgeQA').parameters.base_url } });
    const input = { query: '图片必须可辨认', knowledge_base_ids: [], images: [{ data: 'data:image/png;base64,AA==' }] }, start = f.chat.start(f.ctx, f.session.id, input, 'empty-vision');
    await f.chat.run(f.ctx, f.session.id, start.request_id); assert.equal(f.calls(), 1); assert.equal(f.chat.response(f.ctx, f.session.id, start.request_id).message.is_fallback, true);
    assert.equal(f.chat.start(f.ctx, f.session.id, input, start.request_id).idempotent, true); await f.chat.run(f.ctx, f.session.id, start.request_id); assert.equal(f.calls(), 1); assert.equal(f.db.all('select * from model_usage').length, 1);
  } finally { await f.close(); }
});

test('managed image stop and source mutation fence real provider lifetime and publication while keeping audit facts', async () => {
  for (const action of ['close', 'source']) {
    const f = await fixture(); try {
      f.models.create(f.ctx, { name: 'vision-fixture', type: 'VLLM', source: 'openai', is_default: true, parameters: { model: 'vision-fixture', base_url: f.models.configuration(f.ctx, 'KnowledgeQA').parameters.base_url } });
      const hooks = f.createChatAttachmentHooks(f.db, f.auth); f.chat.dependencies.hooks = hooks; const png = await readFile(resolve('../../workers/document/tests/fixtures/small.png')); const image = await hooks.uploads.store(f.ctx, f.session.id, { name: 'picture.png', bytes: png, kind: 'image' });
      const start = f.chat.start(f.ctx, f.session.id, { query: 'PAUSE 实际识别', knowledge_base_ids: [], images: [{ upload_id: image.upload_id }] }, `managed-${action}`);
      const work = f.chat.run(f.ctx, f.session.id, start.request_id); await waitFor(() => f.calls() === 1);
      if (action === 'close') await f.chat.close(); else { const user = f.db.get("select id from messages where session_id=? and role='user'", f.session.id)!.id; f.db.update('messages', String(user), { content: '源已修改' }); f.release(); }
      await work; f.release(); assert.equal(f.calls(), 1); assert.equal(f.db.all('select * from model_usage').length, 1); const user = f.db.read('messages', String(f.db.get("select id from messages where session_id=? and role='user'", f.session.id)!.id))!; assert.equal(user.images[0].caption, undefined);
      const usage = f.db.all('select * from model_usage').length; await new Promise(resolve => setTimeout(resolve, 80)); assert.equal(f.db.all('select * from model_usage').length, usage);
    } finally { await f.close(); }
  }
});

test('managed SVG image is normalized by the actual parser before vision and retains its original owned source across branches', async () => {
  const f = await fixture(); try {
    const pythonExecutable = spawnSync('python', ['-c', 'import sys; print(sys.executable)'], { encoding: 'utf8' }).stdout.trim(), parser = new DocumentParser({ pythonExecutable, workerPath: resolve('../../workers/document/worker.py') });
    const hooks = f.createChatAttachmentHooks(f.db, f.auth, { parser }); f.chat.dependencies.hooks = hooks;
    f.models.create(f.ctx, { name: 'vision-fixture', type: 'VLLM', source: 'openai', is_default: true, parameters: { model: 'vision-fixture', base_url: f.models.configuration(f.ctx, 'KnowledgeQA').parameters.base_url } });
    const bytes = await readFile(resolve('../../workers/document/tests/fixtures/image.svg')), start = f.chat.start(f.ctx, f.session.id, { query: '识别矢量图', knowledge_base_ids: [], images: [{ data: `data:image/svg+xml;base64,${bytes.toString('base64')}` }] }, 'managed-svg');
    await f.chat.run(f.ctx, f.session.id, start.request_id); const user = f.chat.loadMessages(f.ctx, f.session.id).items[0]; assert.equal(user.images[0].caption, '图片识别✓'); assert.ok(user.images[0].original_upload_id);
    const request = f.bodies.find((v: any) => !v.stream); assert.match(request.messages[0].content[1].image_url.url, /^data:image\/png;base64,/);
    const branch = f.chat.branch(f.ctx, f.session.id); await f.chat.clearMessages(f.ctx, f.session.id); assert.equal((await hooks.uploads.read(f.ctx, branch.id, user.images[0].original_upload_id)).bytes.toString(), bytes.toString()); await f.chat.delete(f.ctx, branch.id); assert.equal(f.db.all("select * from desktop_meta where key like 'chat.upload:%'").length, 0);
  } finally { await f.close(); }
});

test('attachment byte and context bounds are explicit and legacy metadata remains available without a parser', async () => {
  const f = await fixture(); try {
    assert.ok(f.createChatAttachmentHooks); const hooks = f.createChatAttachmentHooks(f.db, f.auth, { maxFileBytes: 32, maxTextChars: 4 }); f.chat.dependencies.hooks = hooks;
    const start = f.chat.start(f.ctx, f.session.id, { query: '有边界的附件', knowledge_base_ids: [], attachment_uploads: [{ file_name: 'short.txt', data: Buffer.from('甲乙😀丁戊').toString('base64') }, { file_name: 'legacy.pdf', file_size: 123 }] }, 'bounded-files');
    await f.chat.run(f.ctx, f.session.id, start.request_id); const user = f.chat.loadMessages(f.ctx, f.session.id).items[0];
    assert.ok(String(f.db.read('messages', user.id)!.rendered_content).includes('甲乙😀丁')); assert.equal(user.attachments[0].truncated, true); assert.equal(user.attachments[1].preparation_state, 'metadata_only'); assert.ok(String(f.db.read('messages', user.id)!.rendered_content).includes('legacy.pdf (123 bytes)'));
    await assert.rejects(() => hooks.uploads.store(f.ctx, f.session.id, { name: 'large.txt', bytes: Buffer.alloc(33) }), (e: any) => e.status === 413);
    await assert.rejects(() => hooks.uploads.store(f.ctx, f.session.id, { name: 'bad.txt', bytes: Buffer.from('x'), fileSize: 2 }), (e: any) => e.code === 'upload_size_mismatch');
    const reference = await hooks.uploads.store(f.ctx, f.session.id, { name: 'link.txt', bytes: Buffer.from('private') });
    const metadata = JSON.parse(String(f.db.get('select value from desktop_meta where key=?', `chat.upload:${reference.upload_id}`)!.value)); rmSync(join(f.root, metadata.asset_path)); await symlink('/etc/passwd', join(f.root, metadata.asset_path));
    await assert.rejects(() => hooks.uploads.read(f.ctx, f.session.id, reference.upload_id), (e: any) => e.code === 'upload_source_changed');
  } finally { await f.close(); }
});
