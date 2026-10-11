import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { createServer } from 'node:http';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { AuthService } from '../src/auth/index.js';
import { ChatService } from '../src/chat/index.js';
import type { JsonObject } from '../src/contracts.js';
import { JobQueue } from '../src/jobs/queue.js';
import { SearchIndex } from '../src/retrieval/search-index.js';
import { ModelConfigurationService } from '../src/settings/model-configuration.js';
import { CredentialVault } from '../src/storage/credentials.js';
import { CoreDatabase } from '../src/storage/database.js';

async function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'marlin-chat-graph-')), db = new CoreDatabase(root), auth = new AuthService(db), jobs = new JobQueue(db), index = new SearchIndex(db);
  const ctx = auth.register({ username: 'alice', password: 'Graph✓Password' }).context, bob = auth.register({ username: 'bob', password: 'Graph✓Password' }).context, requests: JsonObject[] = [];
  const server = createServer(async (req, res) => { let body = ''; for await (const part of req) body += part; assert.equal(db.sqlite.inTransaction, false); requests.push(JSON.parse(body)); res.setHeader('content-type', 'text/event-stream'); res.end(`data: ${JSON.stringify({ choices: [{ delta: { content: 'Grounded fixture answer' }, finish_reason: 'stop' }], usage: { prompt_tokens: 2, completion_tokens: 1, total_tokens: 3 } })}\n\ndata: [DONE]\n\n`); });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve)); const address = server.address(); assert.ok(address && typeof address !== 'string');
  const models = new ModelConfigurationService(db, auth, new CredentialVault(root)); models.create(ctx, { name: 'local-fixture', source: 'openai', type: 'KnowledgeQA', is_default: true, parameters: { model: 'fixture', base_url: `http://127.0.0.1:${address.port}/v1` } });
  const chat = new ChatService(db, auth, { models, jobs, index }), session = chat.create(ctx), kb = String(db.insert('knowledge_bases', { tenant_id: ctx.tenantId, name: 'Allowed', indexing_strategy: { graph_enabled: true } }).id), doc = String(db.insert('knowledges', { tenant_id: ctx.tenantId, knowledge_base_id: kb, title: 'Source' }).id);
  let chunkIndex = 0;
  const add = (content: string, fields: JsonObject = {}) => String(db.insert('chunks', { seq_id: BigInt('0x' + createHash('sha256').update(randomUUID()).digest('hex').slice(0, 15)).toString(), chunk_index: chunkIndex++, tenant_id: ctx.tenantId, knowledge_base_id: kb, knowledge_id: doc, content, start_at: 0, end_at: Array.from(content).length, ...fields }).id);
  const ask = async (id: string, selected = [kb], agent = false) => { const start = chat.start(ctx, String(session.id), { query: 'Needle Alpha', knowledge_base_ids: selected }, id, agent); await chat.run(ctx, String(session.id), id); return chat.response(ctx, String(session.id), id); };
  const refs = (answer: JsonObject) => answer.references as JsonObject[];
  return { root, db, auth, ctx, bob, chat, jobs, index, models, session, kb, doc, requests, add, ask, refs, close: async () => { await chat.close(); await jobs.close(); server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); db.close(); rmSync(root, { recursive: true, force: true }); } };
}
const degradations = (answer: JsonObject) => ((answer.message as JsonObject).agent_steps as JsonObject[]).flatMap(step => (step.degradations as JsonObject[]) ?? []);

// Desktop migration regression: legacy hybrid_search merged an independent GraphRAG cohort.
test('chat graph retrieval invokes the fenced hook and interleaves real citations without forged remote text', async () => {
  const f = await fixture(); try {
    const first = f.add('Needle Alpha document first', { seq_id: '1152921504606846975' }), second = f.add('Needle Alpha document second'), graph = f.add('Graph-only current evidence', { knowledge_id: String(f.db.insert('knowledges', { tenant_id: f.ctx.tenantId, knowledge_base_id: f.kb, title: 'Source' }).id), metadata: { provenance: { source_ref: 'page:2' } } });
    for (const id of [first, second]) f.index.indexKeyword({ tenantId: f.ctx.tenantId }, id); let called = 0;
    f.chat.dependencies.hooks = { graphRetrieval: async (e, query, options) => { called++; e.assert(); assert.equal(query, 'Needle Alpha'); assert.deepEqual(e.scope.knowledgeBaseIds, [f.kb]); assert.equal(options.limit, 5); assert.ok(options.seenChunkIds.includes(first)); return { state: 'connected', items: [{ chunk_id: graph, content: 'FORGED_REMOTE_TEXT', knowledge_title: 'FORGED_TITLE', score: 1 }], warnings: [] }; } };
    const answer = await f.ask('graph-cohort'), refs = f.refs(answer); assert.equal(called, 1); assert.equal(refs[0]!.retrieval_path, 'document'); assert.equal(refs[1]!.chunk_id, graph); assert.equal(refs[1]!.retrieval_path, 'graph'); assert.equal(refs[1]!.match_type, 'graph'); assert.deepEqual(refs[1]!.match_sources, ['graph']); assert.equal(refs[1]!.content, 'Graph-only current evidence'); assert.equal(refs[1]!.knowledge_title, 'Source'); assert.equal(refs.find(r => r.chunk_id === first)!.seq_id, '1152921504606846975');
    assert.ok(JSON.stringify(f.requests[0]).includes('Graph-only current evidence')); assert.equal(JSON.stringify(refs).includes('FORGED'), false); await f.chat.run(f.ctx, String(f.session.id), 'graph-cohort'); assert.equal(called, 1);
  } finally { await f.close(); }
});

test('graph and direct/indirect relation candidates enforce scope enablement and deletion before relation limits', async () => {
  const f = await fixture(); try {
    const source = f.add('Needle Alpha owned seed'), direct = f.add('Direct evidence', { knowledge_id: String(f.db.insert('knowledges', { tenant_id: f.ctx.tenantId, knowledge_base_id: f.kb }).id) }), indirect = f.add('Indirect evidence', { knowledge_id: String(f.db.insert('knowledges', { tenant_id: f.ctx.tenantId, knowledge_base_id: f.kb }).id) }), disabled = f.add('Disabled', { is_enabled: false }), deleted = f.add('Deleted', { deleted_at: new Date().toISOString() });
    const otherKb = String(f.db.insert('knowledge_bases', { tenant_id: f.ctx.tenantId, name: 'Unselected' }).id), otherDoc = String(f.db.insert('knowledges', { tenant_id: f.ctx.tenantId, knowledge_base_id: otherKb }).id), unselected = f.add('Unselected', { knowledge_base_id: otherKb, knowledge_id: otherDoc }), mismatch = f.add('Wrong document', { knowledge_id: otherDoc });
    const foreignKb = String(f.db.insert('knowledge_bases', { tenant_id: f.bob.tenantId }).id), foreignDoc = String(f.db.insert('knowledges', { tenant_id: f.bob.tenantId, knowledge_base_id: foreignKb }).id), foreign = f.add('Foreign', { tenant_id: f.bob.tenantId, knowledge_base_id: foreignKb, knowledge_id: foreignDoc });
    f.db.update('chunks', source, { relation_chunks: [foreign, unselected, disabled, deleted, mismatch, direct], indirect_relation_chunks: [indirect] }); f.index.indexKeyword({ tenantId: f.ctx.tenantId }, source);
    f.chat.dependencies.hooks = { graphRetrieval: async () => ({ state: 'connected', items: [foreign, unselected, disabled, deleted, mismatch].map(chunk_id => ({ chunk_id, score: 1 })), warnings: [] }) };
    const refs = f.refs(await f.ask('graph-scope')); assert.deepEqual(refs.map(r => r.chunk_id), [source, direct, indirect]); assert.equal(refs[1]!.relation_type, 'direct'); assert.equal(refs[2]!.relation_type, 'indirect'); assert.equal((refs[1]!.graph_provenance as JsonObject[])[0]!.source_chunk_id, source);
    f.db.update('knowledges', f.doc, { enable_status: 'disabled' }); assert.deepEqual(f.refs(await f.ask('graph-disabled-doc')), []);
  } finally { await f.close(); }
});

test('graph parents preserve Unicode child ranges edits and image source and duplicate attribution', async () => {
  const f = await fixture(); try {
    const original = '开头😀原文结尾', parent = f.add(original, { chunk_type: 'parent_text', is_enabled: false }), child = f.add('编辑😀事实', { context_parent_id: parent, start_at: 3, end_at: 5 }), image = f.add('Image evidence', { chunk_type: 'image_ocr', image_info: { image_id: 'owned-image', source_ref: 'page:4', source_type: 'scanned_pdf' } });
    f.chat.dependencies.hooks = { graphRetrieval: async () => ({ state: 'connected', items: [{ chunk_id: child, score: 1 }, { chunk_id: image, score: 1 }], warnings: [] }) };
    let refs = f.refs(await f.ask('graph-parent')); assert.equal(refs[0]!.parent_chunk_id, parent); assert.deepEqual(refs[0]!.matched_child_ids, [child]); assert.equal(refs[0]!.content, '开头😀编辑😀事实结尾'); assert.equal((refs[0]!.matched_ranges as JsonObject[])[0]!.start_at, 3); assert.equal((refs[0]!.matched_child_provenance as JsonObject[])[0]!.chunk_id, child); assert.equal((refs[1]!.image_info as JsonObject).image_id, 'owned-image');
    f.db.update('chunks', child, { content: 'Needle Alpha edited child' }); f.index.indexKeyword({ tenantId: f.ctx.tenantId }, child); refs = f.refs(await f.ask('graph-parent-duplicate')); const merged = refs.find(r => r.chunk_id === child)!; assert.equal(refs.filter(r => r.chunk_id === child).length, 1); assert.equal(merged.retrieval_path, 'document'); assert.ok((merged.match_sources as string[]).includes('graph')); assert.equal((merged.graph_provenance as JsonObject[])[0]!.chunk_id, child);
  } finally { await f.close(); }
});

test('pending graph capability warns while empty selection and graph-disabled document chat issue no graph work', async () => {
  const f = await fixture(); try {
    const source = f.add('Needle Alpha document'); f.index.indexKeyword({ tenantId: f.ctx.tenantId }, source); let calls = 0;
    f.chat.dependencies.hooks = { graphRetrieval: async () => { calls++; return { state: 'model_not_configured', items: [], warnings: [{ code: 'graph_query_needs_configuration', stage: 'graph', message: 'Configure model' }] }; } };
    assert.ok(degradations(await f.ask('graph-pending')).some(w => w.reason === 'graph_query_needs_configuration')); assert.equal(calls, 1); assert.deepEqual(f.refs(await f.ask('graph-empty', [])), []); assert.equal(calls, 1);
    delete f.chat.dependencies.hooks.graphRetrieval; assert.ok(degradations(await f.ask('graph-unwired')).some(w => w.reason === 'graph_retrieval_not_configured'));
    f.db.update('knowledge_bases', f.kb, { indexing_strategy: { graph_enabled: false } }); assert.equal(degradations(await f.ask('graph-disabled')).some(w => w.stage === 'graph'), false);
  } finally { await f.close(); }
});

test('graph wait refreshes both cohorts after edits and deletion', async () => {
  const f = await fixture(); try {
    const old = f.add('Needle Alpha old text'), edited = f.add('Graph original text'); f.index.indexKeyword({ tenantId: f.ctx.tenantId }, old);
    f.chat.dependencies.hooks = { graphRetrieval: async () => { f.db.update('chunks', old, { deleted_at: new Date().toISOString() }); f.db.update('chunks', edited, { content: 'Graph newly edited text' }); return { state: 'connected', items: [{ chunk_id: old, score: 1 }, { chunk_id: edited, content: 'Graph original text', score: 1 }], warnings: [] }; } };
    const refs = f.refs(await f.ask('graph-fresh')); assert.deepEqual(refs.map(r => r.chunk_id), [edited]); assert.equal(refs[0]!.content, 'Graph newly edited text'); assert.equal(JSON.stringify(f.requests[0]).includes('Needle Alpha old text'), false);
  } finally { await f.close(); }
});

test('graph cancellation aborts hook lifetime and forbids late citations or downstream provider calls', async () => {
  const f = await fixture(); try {
    const source = f.add('Graph evidence'); let started!: () => void; const ready = new Promise<void>(resolve => { started = resolve; }); let cancelled = false;
    f.chat.dependencies.hooks = { graphRetrieval: async e => { started(); await new Promise<void>(resolve => e.signal.addEventListener('abort', () => { cancelled = true; resolve(); }, { once: true })); return { state: 'connected', items: [{ chunk_id: source, score: 1 }], warnings: [] }; } };
    const start = f.chat.start(f.ctx, String(f.session.id), { query: 'Needle Alpha', knowledge_base_ids: [f.kb] }, 'graph-cancel'), work = f.chat.run(f.ctx, String(f.session.id), start.request_id); await Promise.race([ready, work.then(() => assert.fail('Graph hook was not invoked'))]); f.chat.stop(f.ctx, String(f.session.id), start.request_id); await work; assert.equal(cancelled, true); assert.equal(f.requests.length, 0); assert.deepEqual(f.refs(f.chat.response(f.ctx, String(f.session.id), start.request_id)), []);
  } finally { await f.close(); }
});

test('agent knowledge search uses the same graph-capable citation contract', async () => {
  const f = await fixture(); try {
    const source = f.add('Agent graph evidence'); let calls = 0;
    f.chat.dependencies.hooks = { graphRetrieval: async () => { calls++; return { state: 'connected', items: [{ chunk_id: source, score: 1 }], warnings: [] }; }, agent: async e => { const result = await e.search('Needle Alpha', { topK: 2 }); return { content: 'Agent fixture', refs: result.results as unknown as JsonObject[], steps: [], durationMs: 0 }; } };
    const refs = f.refs(await f.ask('agent-graph', [f.kb], true)); assert.equal(calls, 1); assert.equal(refs[0]!.retrieval_path, 'graph'); assert.equal(f.requests.length, 0);
  } finally { await f.close(); }
});

test('graph waits cannot retain citations after the actual device or selected KB is revoked', async () => {
  for (const change of ['device', 'knowledge_base'] as const) {
    const f = await fixture(); try {
      const source = f.add('Graph scoped evidence');
      f.chat.dependencies.hooks = { graphRetrieval: async () => { if (change === 'device') f.auth.logout(f.ctx); else f.db.update('knowledge_bases', f.kb, { deleted_at: new Date().toISOString() }); return { state: 'connected', items: [{ chunk_id: source, score: 1 }], warnings: [] }; } };
      const start = f.chat.start(f.ctx, String(f.session.id), { query: 'Needle Alpha', knowledge_base_ids: [f.kb] }, `graph-revoked-${change}`);
      await f.chat.run(f.ctx, String(f.session.id), start.request_id).catch(() => {});
      assert.equal(f.requests.length, 0); assert.deepEqual(f.db.read('messages', start.assistant_message_id)!.knowledge_references, []); assert.notEqual(f.jobs.get(start.job_id, { tenantId: f.ctx.tenantId, userId: f.ctx.userId }).status, 'completed');
    } finally { await f.close(); }
  }
});
