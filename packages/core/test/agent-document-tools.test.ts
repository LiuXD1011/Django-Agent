import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { AuthService } from '../src/auth/index.js';
import { BuiltinToolRunner } from '../src/agents/tools.js';
import { AgentService } from '../src/agents/index.js';
import { ChatService } from '../src/chat/index.js';
import type { ChatExecution } from '../src/chat/types.js';
import { ModelConfigurationService } from '../src/settings/model-configuration.js';
import { CredentialVault } from '../src/storage/credentials.js';
import { CoreDatabase } from '../src/storage/database.js';

function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'marlin-agent-document-tools-'));
  const db = new CoreDatabase(root), auth = new AuthService(db);
  const ctx = auth.register({ username: 'alice', password: 'Document tool fixture✓' }).context;
  const foreign = auth.register({ username: 'foreign', password: 'Document tool fixture✓' }).context;
  const kb = db.insert('knowledge_bases', { tenant_id: ctx.tenantId, name: 'Selected' });
  const other = db.insert('knowledge_bases', { tenant_id: ctx.tenantId, name: 'Unselected' });
  const removed = db.insert('knowledge_bases', { tenant_id: ctx.tenantId, name: 'Deleted', deleted_at: '2026-01-01' });
  const foreignKb = db.insert('knowledge_bases', { tenant_id: foreign.tenantId, name: 'Foreign' });
  const doc = (title: string, values = {}) => db.insert('knowledges', { tenant_id: ctx.tenantId, knowledge_base_id: kb.id, title, description: `Description ${title}`, type: 'file', source: 'fixture', file_name: `${title}.txt`, file_type: 'txt', parse_status: 'completed', ...values });
  const enabled = doc('Selected budget🪸', { metadata: { content: 'Large local parser body'.repeat(10000) } });
  const pending = doc('Selected pending', { parse_status: 'pending' });
  const disabled = doc('NEVER_DISABLED_DOC', { enable_status: 'disabled' });
  const deleted = doc('NEVER_DELETED_DOC', { deleted_at: '2026-01-01' });
  const unselected = doc('NEVER_UNSELECTED_DOC', { knowledge_base_id: other.id, metadata: { content: 'Unselected parser body'.repeat(10000) } });
  const foreignDoc = doc('NEVER_FOREIGN_DOC', { tenant_id: foreign.tenantId, knowledge_base_id: foreignKb.id });
  const deletedKbDoc = doc('NEVER_DELETED_KB_DOC', { knowledge_base_id: removed.id });
  const mismatchedDoc = doc('NEVER_MISMATCHED_DOC', { tenant_id: foreign.tenantId });
  const foreignKbDoc = doc('NEVER_FOREIGN_KB_DOC', { knowledge_base_id: foreignKb.id });
  const chunk = (knowledge = enabled, content = 'Needle valid', values = {}) => db.insert('chunks', { tenant_id: knowledge.tenant_id, knowledge_base_id: knowledge.knowledge_base_id, knowledge_id: knowledge.id, content, chunk_index: 0, ...values });
  for (const [at, type] of ['text', 'image_ocr', 'image_caption', 'parent_text'].entries()) chunk(enabled, `Needle permitted ${type}`, { chunk_type: type, chunk_index: at });
  chunk(enabled, 'Needle NEVER_DISABLED_CHUNK', { is_enabled: false });
  chunk(enabled, 'Needle NEVER_DELETED_CHUNK', { deleted_at: '2026-01-01' });
  chunk(enabled, 'Needle NEVER_FOREIGN_CHUNK', { tenant_id: foreign.tenantId });
  chunk(enabled, 'Needle NEVER_MISMATCHED_KB_CHUNK', { knowledge_base_id: other.id });
  chunk(enabled, 'Needle NEVER_RAW_IMAGE', { chunk_type: 'image' });
  for (const knowledge of [disabled, deleted, unselected, foreignDoc, deletedKbDoc, mismatchedDoc, foreignKbDoc]) chunk(knowledge, `Needle ${knowledge.title}`);
  const models = new ModelConfigurationService(db, auth, new CredentialVault(root));
  const chat = new ChatService(db, auth, { models }), runner = new BuiltinToolRunner(db, {});
  let request = 0;
  const ask = async (work: (e: ChatExecution) => Promise<void>, selected = [String(kb.id)]) => {
    let failure: unknown, entered = false;
    chat.dependencies.hooks = { agent: async e => {
      entered = true;
      try { await work(e); } catch (error) { failure = error; throw error; }
      return { content: 'Controlled local tool verification', refs: [], steps: [], durationMs: 0 };
    } };
    const session = chat.create(ctx), start = chat.start(ctx, String(session.id), { query: 'Exercise read-only document tools', knowledge_base_ids: selected }, `tool-fixture-${++request}`, true);
    await chat.run(ctx, String(session.id), start.request_id);
    assert.ok(entered, 'Run tools through a real authenticated, source-fenced ChatExecution');
    if (failure) throw failure;
    assert.equal(chat.jobs.get(start.job_id, { tenantId: ctx.tenantId, userId: ctx.userId }).status, 'completed');
    assert.equal(db.all('SELECT id FROM model_usage').length, 0, 'Local tools must not require a paid provider');
  };
  return { root, db, auth, chat, models, ctx, kb, other, removed, foreignKb, enabled, pending, disabled, deleted, unselected, foreignDoc, foreignKbDoc, runner, ask, close: async () => { await chat.close(); await chat.jobs.close(); db.close(); rmSync(root, { recursive: true, force: true }); } };
}

test('real SQLite document tools use the actual enable_status field and preserve selected document/source reads', async () => {
  const f = fixture(); try {
    assert.equal(f.db.all('PRAGMA table_info(knowledges)').some(c => c.name === 'is_enabled'), false);
    await f.ask(async e => {
      const list = await f.runner.execute('list_knowledge_docs', {}, e);
      assert.ok(list.output.includes('Selected budget🪸')); assert.ok(list.output.includes('Selected pending')); assert.equal(list.output.includes('NEVER_'), false);
      assert.equal((await f.runner.execute('list_knowledge_docs', { keyword: 'budget' }, e)).output.includes('Selected pending'), false);
      const info = await f.runner.execute('get_document_info', { knowledge_id: f.enabled.id }, e);
      assert.equal(info.error, undefined); assert.equal((info.data as any).chunk_count, 4); assert.equal((info.data as any).id, f.enabled.id);
      const grep = await f.runner.execute('grep_chunks', { keywords: 'Needle', knowledge_id: f.enabled.id }, e);
      for (const type of ['text', 'image_ocr', 'image_caption', 'parent_text']) assert.ok(grep.output.includes(`permitted ${type}`));
      assert.equal(grep.output.includes('NEVER_'), false);
      assert.deepEqual(JSON.parse((await f.runner.execute('database_query', { query_type: 'knowledge_stats' }, e)).output), { total: 2, completed: 1, processing: 1 });
      assert.equal((await f.runner.execute('database_query', { query_type: 'knowledge_list' }, e)).output.includes('NEVER_'), false);
      assert.deepEqual(JSON.parse((await f.runner.execute('database_query', { query_type: 'chunk_stats' }, e)).output), { total: 4 });
      assert.deepEqual(JSON.parse((await f.runner.execute('database_query', { query_type: 'session_stats' }, e)).output), { total: 1 });
      const wiki = await f.runner.execute('wiki_read_source_doc', { knowledge_id: f.enabled.id, limit: 10 }, e);
      assert.equal(wiki.error, undefined); assert.ok(wiki.output.includes('Needle permitted image_ocr')); assert.ok(wiki.output.includes('Needle permitted parent_text')); assert.equal(wiki.output.includes('NEVER_'), false);
      for (const doc of [f.disabled, f.deleted, f.unselected, f.foreignDoc, f.foreignKbDoc]) for (const tool of ['get_document_info', 'wiki_read_source_doc']) {
        assert.equal((await f.runner.execute(tool, { knowledge_id: doc.id }, e)).error_type, 'NOT_FOUND');
      }
    });
  } finally { await f.close(); }
});

test('document tools preserve empty scopes and reject forged foreign/deleted/mismatched libraries before returning text', async () => {
  const f = fixture(); try {
    await f.ask(async e => {
      assert.match((await f.runner.execute('list_knowledge_docs', {}, e)).output, /No documents/);
      assert.deepEqual(JSON.parse((await f.runner.execute('database_query', { query_type: 'knowledge_stats' }, e)).output), { total: 0, completed: 0, processing: 0 });
      assert.deepEqual(JSON.parse((await f.runner.execute('database_query', { query_type: 'chunk_stats' }, e)).output), { total: 0 });
      assert.equal((await f.runner.execute('get_document_info', { knowledge_id: f.enabled.id }, e)).error_type, 'NOT_FOUND');
      assert.equal((await f.runner.execute('wiki_read_source_doc', { knowledge_id: f.enabled.id }, e)).error_type, 'NOT_FOUND');
      assert.match((await f.runner.execute('grep_chunks', { keywords: 'Needle' }, e)).output, /No matching/);
    }, []);
    await f.ask(async e => {
      // Trusted-core execution still carries real auth and source fences. Library IDs cannot authorize a mismatched row.
      for (const selected of [[String(f.foreignKb.id)], [String(f.removed.id)], []]) {
        const restricted: ChatExecution = { ...e, scope: { ...e.scope, knowledgeBaseIds: selected } };
        assert.equal((await f.runner.execute('list_knowledge_docs', {}, restricted)).output.includes('NEVER_'), false);
        assert.equal((await f.runner.execute('grep_chunks', { keywords: 'Needle' }, restricted)).output.includes('NEVER_'), false);
      }
      const implicit: ChatExecution = { ...e, scope: { tenantId: e.scope.tenantId } };
      const all = await f.runner.execute('list_knowledge_docs', {}, implicit);
      assert.ok(all.output.includes('NEVER_UNSELECTED_DOC'), 'Implicit selection retains all active libraries in the current tenant');
      for (const hidden of ['NEVER_DISABLED_DOC', 'NEVER_DELETED_DOC', 'NEVER_FOREIGN_DOC', 'NEVER_DELETED_KB_DOC', 'NEVER_MISMATCHED_DOC', 'NEVER_FOREIGN_KB_DOC']) assert.equal(all.output.includes(hidden), false);
    });
  } finally { await f.close(); }
});

test('actual Agent streamed document-list call persists success and resumes the local model with real scoped tool output', async () => {
  const f = fixture(), agents = new AgentService(f.db, f.auth), bodies: any[] = [];
  const server = createServer(async (req, res) => {
    assert.equal(f.db.sqlite.inTransaction, false);
    let raw = ''; for await (const part of req) raw += part;
    const body = JSON.parse(raw); bodies.push(body);
    const complete = body.messages.some((message: any) => message.role === 'tool');
    res.setHeader('content-type', 'text/event-stream');
    const delta = complete ? { content: 'Document listing verified' } : { tool_calls: [{ index: 0, id: 'list-actual', type: 'function', function: { name: 'list_knowledge_docs', arguments: JSON.stringify({ keyword: 'budget' }) } }] };
    res.write(`data: ${JSON.stringify({ choices: [{ delta }] })}\n\n`);
    res.end(`data: ${JSON.stringify({ choices: [{ delta: {}, finish_reason: complete ? 'stop' : 'tool_calls' }], usage: { prompt_tokens: 7, completion_tokens: 2, total_tokens: 9 } })}\n\ndata: [DONE]\n\n`);
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    const address = server.address(); assert.ok(address && typeof address !== 'string');
    f.models.create(f.ctx, { name: 'local-document-tool-fixture', type: 'KnowledgeQA', source: 'openai', is_default: true, parameters: { model: 'fixture', base_url: `http://127.0.0.1:${address.port}/v1` } });
    f.chat.dependencies.hooks = { agent: execution => agents.execute(execution) };
    const session = f.chat.create(f.ctx), start = f.chat.start(f.ctx, String(session.id), { query: 'List selected budget documents', knowledge_base_ids: [f.kb.id], max_rounds: 3 }, 'actual-doc-list', true);
    await f.chat.run(f.ctx, String(session.id), start.request_id);
    const response = f.chat.response(f.ctx, String(session.id), start.request_id);
    assert.equal(response.answer, 'Document listing verified'); assert.equal(bodies.length, 2);
    const result = response.message.agent_steps[0].tool_calls[0].result;
    assert.equal(result.error, undefined); assert.ok(result.output.includes('Selected budget🪸')); assert.equal(result.output.includes('NEVER_'), false);
    const delivered = bodies[1].messages.find((message: any) => message.role === 'tool');
    assert.equal(delivered.tool_call_id, 'list-actual'); assert.ok(delivered.content.includes('Selected budget🪸')); assert.equal(delivered.content.includes('Tool execution failed'), false);
    assert.equal(f.chat.trajectory(f.ctx, String(session.id)).turns[0].usage.total_tokens, 18);
    assert.equal(f.db.all('SELECT id FROM model_usage').length, 2, 'Both actual localhost invocations keep their provider-reported usage');
  } finally {
    await agents.close(); await f.close();
    await new Promise<void>(resolve => { server.closeAllConnections(); server.close(() => resolve()); });
  }
});

test('selected document tools never hydrate whole-tenant document metadata or read unselected candidate rows', async () => {
  const f = fixture(); try {
    await f.ask(async e => {
      const read = f.db.read.bind(f.db), all = f.db.all.bind(f.db); let hydrated = 0;
      const candidates: string[] = [];
      f.db.read = (...args) => { if (args[0] === 'knowledges') hydrated++; return read(...args); };
      f.db.all = (...args) => {
        const rows = all(...args);
        if (/FROM knowledges/i.test(args[0])) for (const row of rows) { candidates.push(String(row.id)); assert.equal(Object.hasOwn(row, 'metadata'), false); }
        return rows;
      };
      try {
        await f.runner.execute('list_knowledge_docs', {}, e);
        await f.runner.execute('get_document_info', { knowledge_id: f.enabled.id }, e);
        await f.runner.execute('wiki_read_source_doc', { knowledge_id: f.enabled.id }, e);
        assert.equal(hydrated, 0, 'Tool DTOs need only explicit columns, not large parser metadata');
        assert.ok(candidates.length > 0);
        assert.equal(candidates.includes(String(f.unselected.id)), false, 'Selected-KB filtering must occur in SQLite');
        assert.ok(candidates.every(id => id === f.enabled.id || id === f.pending.id));
      } finally { f.db.read = read; f.db.all = all; }
    });
  } finally { await f.close(); }
});
