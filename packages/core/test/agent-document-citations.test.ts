import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { AuthService } from '../src/auth/index.js';
import { AgentService } from '../src/agents/index.js';
import { BuiltinToolRunner } from '../src/agents/tools.js';
import { ChatService } from '../src/chat/index.js';
import type { ChatExecution } from '../src/chat/types.js';
import { ModelConfigurationService } from '../src/settings/model-configuration.js';
import { CredentialVault } from '../src/storage/credentials.js';
import { CoreDatabase } from '../src/storage/database.js';

function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'marlin-tool-citations-')), db = new CoreDatabase(root), auth = new AuthService(db);
  const ctx = auth.register({ username: 'citation-fixture', password: 'Ephemeral source fixture✓' }).context;
  const kb = db.insert('knowledge_bases', { tenant_id: ctx.tenantId, name: '引用知识库' });
  const doc = db.insert('knowledges', { tenant_id: ctx.tenantId, knowledge_base_id: kb.id, title: '真实图片😀', description: '仅元数据描述', parse_status: 'completed' });
  const parent = db.insert('chunks', { tenant_id: ctx.tenantId, knowledge_base_id: kb.id, knowledge_id: doc.id, chunk_type: 'parent_text', content: '上下文父块', chunk_index: 99 });
  const media = db.insert('chunks', { tenant_id: ctx.tenantId, knowledge_base_id: kb.id, knowledge_id: doc.id, chunk_type: 'image_container', content: 'raw container', chunk_index: 98 });
  const source = '验证码😀 ORCA-DEMO-123，数量32';
  const chunk = db.insert('chunks', { tenant_id: ctx.tenantId, knowledge_base_id: kb.id, knowledge_id: doc.id, content: source, chunk_type: 'image_ocr', chunk_index: 0, seq_id: '1152921504606846975', start_at: 10, end_at: 10 + Array.from(source).length, context_parent_id: parent.id, media_parent_id: media.id, image_info: { image_id: 'image-fixture', source_ref: '第2页图片' }, metadata: { source_ref: '真实OCR来源', canonical_range: [10, 10 + Array.from(source).length] } });
  const models = new ModelConfigurationService(db, auth, new CredentialVault(root)), runner = new BuiltinToolRunner(db, {}), chat = new ChatService(db, auth, { models });
  let count = 0;
  const ask = async (work: (e: ChatExecution) => Promise<void>, selected = [String(kb.id)]) => {
    let failure: unknown;
    chat.dependencies.hooks = { agent: async e => { try { await work(e); } catch (error) { failure = error; throw error; } return { content: 'Local source verification', refs: [], steps: [], durationMs: 0 }; } };
    const session = chat.create(ctx), start = chat.start(ctx, String(session.id), { query: 'Actual source tool', knowledge_base_ids: selected }, `sources-${++count}`, true);
    await chat.run(ctx, String(session.id), start.request_id); if (failure) throw failure;
    assert.equal(chat.jobs.get(start.job_id, { tenantId: ctx.tenantId, userId: ctx.userId }).status, 'completed');
  };
  return { root, db, auth, ctx, kb, doc, chunk, parent, media, source, models, runner, chat, ask, close: async () => { await chat.close(); await chat.jobs.close(); db.close(); rmSync(root, { recursive: true, force: true }); } };
}

test('actual scoped grep sources carry exact string identifiers, Unicode and media provenance while metadata tools do not invent citations', async () => {
  const f = fixture(); try {
    f.db.insert('chunks', { tenant_id: f.ctx.tenantId, knowledge_base_id: f.kb.id, knowledge_id: f.doc.id, content: 'ORCA-DEMO-123 disabled', is_enabled: false });
    f.db.insert('chunks', { tenant_id: f.ctx.tenantId, knowledge_base_id: f.kb.id, knowledge_id: f.doc.id, content: 'ORCA-DEMO-123 deleted', deleted_at: '2026-01-01' });
    const other = f.db.insert('knowledge_bases', { tenant_id: f.ctx.tenantId, name: 'Unselected' });
    f.db.insert('chunks', { tenant_id: f.ctx.tenantId, knowledge_base_id: other.id, knowledge_id: f.doc.id, content: 'ORCA-DEMO-123 mismatched KB' });
    await f.ask(async e => {
      const result = await f.runner.execute('grep_chunks', { keywords: 'ORCA-DEMO-123' }, e), refs = result.references as any[];
      assert.equal(refs?.length, 1); const ref = refs[0];
      assert.equal(ref.chunk_id, f.chunk.id); assert.equal(ref.knowledge_id, f.doc.id); assert.equal(ref.knowledge_base_id, f.kb.id);
      assert.equal(ref.seq_id, '1152921504606846975'); assert.equal(ref.knowledge_title, '真实图片😀'); assert.equal(ref.content, f.source);
      assert.equal(ref.source_range_exact, true); assert.equal(ref.visible_source_start_at, 10); assert.equal(ref.visible_source_end_at, 10 + Array.from(f.source).length);
      assert.equal(ref.context_parent_id, f.parent.id); assert.equal(ref.media_parent_id, f.media.id); assert.equal(ref.image_info.source_ref, '第2页图片'); assert.equal(ref.metadata.source_ref, '真实OCR来源');
      assert.equal(ref.source_tool, 'grep_chunks'); assert.equal(ref.rerank_score, undefined);
      for (const tool of ['get_document_info', 'list_knowledge_docs', 'database_query']) assert.equal((await f.runner.execute(tool, { knowledge_id: f.doc.id, query_type: 'knowledge_list' }, e)).references, undefined);
      assert.deepEqual((await f.runner.execute('grep_chunks', { keywords: 'not-present' }, e)).references, []);
      const controller = new AbortController(); controller.abort();
      await assert.rejects(f.runner.execute('grep_chunks', { keywords: 'ORCA-DEMO-123' }, { ...e, signal: controller.signal, assert() { controller.signal.throwIfAborted(); e.assert(); } }));
    });
    await f.ask(async e => assert.deepEqual((await f.runner.execute('grep_chunks', { keywords: 'ORCA-DEMO-123' }, e)).references, []), []);
    assert.equal(f.db.all('SELECT id FROM model_usage').length, 0);
  } finally { await f.close(); }
});

test('source document clipping cites only text actually visible within the Unicode 8000-character tool budget', async () => {
  const f = fixture(); try {
    f.db.update('chunks', String(f.chunk.id), { content: '文😀'.repeat(3900), start_at: 0, end_at: 7800 });
    const next = f.db.insert('chunks', { tenant_id: f.ctx.tenantId, knowledge_base_id: f.kb.id, knowledge_id: f.doc.id, content: '尾😀'.repeat(200), chunk_index: 1, start_at: 10000, end_at: 10400 });
    const unseen = f.db.insert('chunks', { tenant_id: f.ctx.tenantId, knowledge_base_id: f.kb.id, knowledge_id: f.doc.id, content: 'NEVER_UNSEEN_AFTER_LIMIT', chunk_index: 2 });
    await f.ask(async e => {
      const result = await f.runner.execute('wiki_read_source_doc', { knowledge_id: f.doc.id }, e), refs = result.references as any[];
      assert.equal(Array.from(result.output).length, 8000); assert.equal(refs?.length, 2);
      assert.deepEqual(refs.map(ref => ref.chunk_id), [f.chunk.id, next.id]); assert.equal(refs.some(ref => ref.chunk_id === unseen.id), false);
      assert.equal(refs[0].content, '文😀'.repeat(3900)); assert.ok(Array.from(refs[1].content).length > 0 && Array.from(refs[1].content).length < 400);
      assert.ok(result.output.endsWith(refs[1].content)); assert.equal(refs[1].visible_source_end_at, 10000 + Array.from(refs[1].content).length); assert.equal(refs[1].clipped, true);
      assert.equal(/[\uD800-\uDBFF]$/.test(refs[1].content), false, 'never cut an astral codepoint in half');
      f.db.update('chunks', String(f.chunk.id), { end_at: 3 });
      const edited = (await f.runner.execute('wiki_read_source_doc', { knowledge_id: f.doc.id, limit: 1 }, e)).references?.[0] as any;
      assert.equal(edited.source_range_exact, false); assert.equal(edited.visible_source_end_at, undefined);
    });
  } finally { await f.close(); }
});

test('actual Agent SSE grep and source reads persist deduplicated citations and provider usage without a knowledge_search call', async () => {
  const f = fixture(), agent = new AgentService(f.db, f.auth), bodies: any[] = [];
  const server = createServer(async (req, res) => {
    let raw = ''; for await (const part of req) raw += part; const body = JSON.parse(raw); bodies.push(body);
    assert.equal(f.db.sqlite.inTransaction, false);
    const complete = body.messages.some((message: any) => message.role === 'tool');
    const toolCalls = [['grep_chunks', { keywords: 'ORCA-DEMO-123' }], ['wiki_read_source_doc', { knowledge_id: f.doc.id, limit: 1 }], ['get_document_info', { knowledge_id: f.doc.id }]].map(([name, args], index) => ({ index, id: `source-${index}`, type: 'function', function: { name, arguments: JSON.stringify(args) } }));
    res.setHeader('content-type', 'text/event-stream');
    res.write(`data: ${JSON.stringify({ choices: [{ delta: complete ? { content: 'Actual image source: ORCA-DEMO-123 and 32' } : { tool_calls: toolCalls } }] })}\n\n`);
    res.end(`data: ${JSON.stringify({ choices: [{ delta: {}, finish_reason: complete ? 'stop' : 'tool_calls' }], usage: { prompt_tokens: 7, completion_tokens: 2, total_tokens: 9 } })}\n\ndata: [DONE]\n\n`);
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    const address = server.address(); assert.ok(address && typeof address !== 'string');
    f.models.create(f.ctx, { name: 'local-source-model', type: 'KnowledgeQA', source: 'openai', is_default: true, parameters: { model: 'fixture', base_url: `http://127.0.0.1:${address.port}/v1` } });
    f.chat.dependencies.hooks = { agent: e => agent.execute(e) };
    const session = f.chat.create(f.ctx), start = f.chat.start(f.ctx, String(session.id), { query: 'Read image source', knowledge_base_ids: [f.kb.id], allowed_tools: ['grep_chunks', 'wiki_read_source_doc', 'get_document_info'], max_rounds: 3 }, 'source-sse', true);
    await f.chat.run(f.ctx, String(session.id), start.request_id); const response = f.chat.response(f.ctx, String(session.id), start.request_id);
    assert.equal(response.answer, 'Actual image source: ORCA-DEMO-123 and 32'); assert.equal(bodies.length, 2);
    assert.equal(response.references.length, 1); assert.equal(response.references[0].chunk_id, f.chunk.id); assert.equal(response.references[0].image_info.source_ref, '第2页图片');
    assert.deepEqual(response.message.agent_steps[0].tool_calls.map((call: any) => call.name), ['grep_chunks', 'wiki_read_source_doc', 'get_document_info']);
    assert.equal(response.message.agent_steps[0].tool_calls[0].result.references.length, 1); assert.equal(response.message.agent_steps[0].tool_calls[1].result.references.length, 1);
    assert.ok(bodies[1].messages.filter((message: any) => message.role === 'tool').slice(0, 2).every((message: any) => message.content.includes('ORCA-DEMO-123')));
    assert.equal(f.chat.trajectory(f.ctx, String(session.id)).turns[0].usage.total_tokens, 18); assert.equal(f.db.all('SELECT id FROM model_usage').length, 2);
  } finally { await agent.close(); await f.close(); await new Promise<void>(resolve => { server.closeAllConnections(); server.close(() => resolve()); }); }
});
