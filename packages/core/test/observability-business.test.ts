import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import test from 'node:test';
import { AuthService } from '../src/auth/index.js';
import { AgentService } from '../src/agents/index.js';
import { ChatService } from '../src/chat/index.js';
import { IntegrationService } from '../src/integrations/index.js';
import { JobQueue } from '../src/jobs/queue.js';
import { ModelConfigurationService } from '../src/settings/model-configuration.js';
import { SettingsService } from '../src/settings/settings.js';
import { CredentialVault } from '../src/storage/credentials.js';
import { CoreDatabase } from '../src/storage/database.js';
import { ObservabilityService } from '../src/observability/index.js';
import { DocumentParser } from '../src/documents/parser.js';
import { DocumentWorkflow } from '../src/documents/workflow.js';
import { SearchIndex } from '../src/retrieval/search-index.js';

async function fixture(options = { timeoutMs: 300, maxQueue: 32 }) {
  const root = mkdtempSync(join(tmpdir(), 'marlin-observability-')), db = new CoreDatabase(root), auth = new AuthService(db), ctx = auth.register({ username: 'trace-owner', password: 'Trace fixture password 2026' }).context;
  db.update('users', ctx.userId, { is_system_admin: true });
  const vault = new CredentialVault(root), settings = new SettingsService(db, auth, vault), models = new ModelConfigurationService(db, auth, vault), integrations = new IntegrationService(db, auth, settings), jobs = new JobQueue(db);
  const spans: any[] = [], held: import('node:http').ServerResponse[] = []; let mode = 'accepted', modelStarted = 0, modelEnded = 0, modelRequests = 0;
  const server = createServer(async (req, res) => {
    assert.equal(db.sqlite.inTransaction, false); let raw = ''; for await (const part of req) raw += part;
    if (req.url === '/api/public/otel/v1/traces') {
      const payload = JSON.parse(raw); spans.push(...payload.resourceSpans[0].scopeSpans[0].spans);
      res.setHeader('content-type', 'application/json');
      if (mode === 'unavailable') { res.writeHead(503); res.end('fixture-public MUST_NOT_LOG_RAW_ERROR'); }
      else if (mode === 'wait' || mode === 'root_wait' && payload.resourceSpans[0].scopeSpans[0].spans[0].name === 'chat.turn') { res.write(' '); held.push(res); }
      else res.end('{}');
    } else {
      assert.equal(req.url, '/v1/chat/completions'); modelRequests++; modelStarted = Date.now(); res.setHeader('content-type', 'text/event-stream');
      await new Promise(resolve => setTimeout(resolve, 20)); modelEnded = Date.now();
      const body = JSON.parse(raw), child = String(body.messages[0].content).includes('文档检索子 Agent'), delegation = ['actor', 'spawn'].includes(mode), tool = (mode === 'agent' || delegation && !child) && !body.messages.some((message: any) => message.role === 'tool');
      const toolFunction = delegation ? { name: 'actor', arguments: JSON.stringify({ action: mode === 'actor' ? 'run' : 'spawn', subagent_type: 'doc_retriever', prompt: '实际子任务' }) } : { name: 'grep_chunks', arguments: '{"keywords":"实际来源"}' };
      const delta = tool ? { tool_calls: [{ index: 0, id: 'actual-source-call', type: 'function', function: toolFunction }] } : { content: child ? '实际子任务回答' : '实际回答😀 PRIVATE_ANSWER api_key=NEVER_SECRET', role: 'assistant' };
      res.end(`data: ${JSON.stringify({ choices: [{ delta, finish_reason: tool ? 'tool_calls' : 'stop' }], usage: { prompt_tokens: 2, completion_tokens: 1, total_tokens: 3 } })}\n\ndata: [DONE]\n\n`);
    }
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve)); const address = server.address(); assert.ok(address && typeof address !== 'string'); const origin = `http://127.0.0.1:${address.port}`;
  settings.updateIntegration(ctx, 'langfuse', { enabled: true, base_url: origin, ui_base_url: origin, ui_project_id: 'qa-project', trace_links_enabled: true, sample_rate: 1, public_key: 'fixture-public', secret_key: 'fixture-secret', log_content: false });
  models.create(ctx, { name: 'Actual local trace model', type: 'KnowledgeQA', source: 'openai', is_default: true, parameters: { model: 'fixture', base_url: origin + '/v1' } });
  const service = new ObservabilityService(db, auth, integrations, options);
  const chat = new ChatService(db, auth, { models, jobs, hooks: { observability: service.chatObserver } }); let request = 0;
  const run = async () => { const session = chat.create(ctx), start = chat.start(ctx, String(session.id), { query: 'PRIVATE_QUESTION api_key=NEVER_SECRET', knowledge_base_ids: [] }, `trace-${++request}`); const response = await chat.run(ctx, String(session.id), start.request_id); return { session, start, response }; };
  return { root, db, auth, ctx, settings, models, integrations, jobs, service, chat, spans, origin, run, release: () => { for (const res of held.splice(0)) res.end('{}'); }, mode: (value: string) => { mode = value; }, times: () => ({ modelStarted, modelEnded, modelRequests }), close: async () => { await chat.close(); await service.close(); await integrations.close(); await jobs.close(); await new Promise<void>(resolve => { server.closeAllConnections(); server.close(() => resolve()); }); db.close(); rmSync(root, { recursive: true, force: true }); } };
}
async function until(check: () => boolean): Promise<void> { const deadline = Date.now() + 1500; while (!check()) { assert.ok(Date.now() < deadline, 'actual HTTP handshake did not arrive'); await new Promise(resolve => setTimeout(resolve, 5)); } }
test('actual Chat/Model/Stream emits accepted bounded OTLP with real timing and usage; trace links require real owner and administrator', async () => {
  const f = await fixture(); try {
    const { session, response } = await f.run(); assert.ok(String(response.answer).includes('实际回答')); await f.service.flush();
    const root = f.spans.find(s => s.name === 'chat.turn'), model = f.spans.find(s => s.name === 'llm.chat'); assert.ok(root); assert.ok(model);
    assert.equal(model.traceId, root.traceId); assert.ok(model.parentSpanId); const times = f.times();
    assert.ok(Number(BigInt(model.startTimeUnixNano) / 1000000n) <= times.modelStarted); assert.ok(Number(BigInt(model.endTimeUnixNano) / 1000000n) >= times.modelEnded);
    const counters = JSON.parse(model.attributes.find((a: any) => a.key === 'langfuse.observation.usage_details').value.stringValue); assert.equal(counters.total, 3);
    assert.equal(JSON.stringify(f.spans).includes('PRIVATE_QUESTION') || JSON.stringify(f.spans).includes('PRIVATE_ANSWER') || JSON.stringify(f.spans).includes('NEVER_SECRET'), false);
    assert.equal(f.db.all('SELECT id FROM model_usage').length, 1);
    const turn = f.chat.trajectory(f.ctx, String(session.id)).turns[0]; assert.equal(turn.observability.trace_id, root.traceId); assert.equal(turn.observability.trace_url, `${f.origin}/project/qa-project/traces/${root.traceId}`);
    f.settings.updateIntegration(f.ctx, 'langfuse', { trace_links_enabled: false }); assert.equal(f.chat.trajectory(f.ctx, String(session.id)).turns[0].observability.trace_url, undefined);
    f.db.update('users', f.ctx.userId, { is_system_admin: false }); assert.equal(f.chat.trajectory(f.ctx, String(session.id)).turns[0].observability.trace_url, undefined);
    const other = f.auth.register({ username: 'foreign-trace-user', password: 'Trace fixture password 2026' }).context; assert.throws(() => f.chat.trajectory(other, String(session.id)), (e: any) => e.status === 404);
  } finally { await f.close(); }
});
test('sampling and safe content settings control actual business telemetry; failures never repeat a real model request', async () => {
  const f = await fixture(); try {
    f.settings.updateIntegration(f.ctx, 'langfuse', { sample_rate: 0 }); await f.run(); await f.service.flush(); assert.equal(f.spans.length, 0);
    f.settings.updateIntegration(f.ctx, 'langfuse', { sample_rate: 1, log_content: true }); await f.run(); await f.service.flush();
    assert.ok(JSON.stringify(f.spans).includes('PRIVATE_QUESTION') && JSON.stringify(f.spans).includes('PRIVATE_ANSWER')); assert.equal(JSON.stringify(f.spans).includes('NEVER_SECRET'), false);
    f.mode('unavailable'); const { session, response } = await f.run(); await f.service.flush(); assert.ok(String(response.answer).includes('实际回答'));
    assert.equal(f.db.all('SELECT id FROM model_usage').length, 3); assert.equal(f.chat.trajectory(f.ctx, String(session.id)).turns[0].observability, null);
    const diagnostics = f.db.all("SELECT value FROM desktop_meta WHERE key LIKE 'observability.%'"); assert.ok(diagnostics.some(r => String(r.value).includes('integration_connection_failed'))); assert.equal(JSON.stringify(diagnostics).includes('MUST_NOT_LOG_RAW_ERROR'), false);
  } finally { await f.close(); }
});
test('document telemetry derives only actual owned job and persisted processing span facts with no invented model generation', async () => {
  const f = await fixture(); try {
    const kb = f.db.insert('knowledge_bases', { tenant_id: f.ctx.tenantId, name: 'Trace documents' }), doc = f.db.insert('knowledges', { tenant_id: f.ctx.tenantId, knowledge_base_id: kb.id, title: 'Actual span' }); let started = 0, ended = 0;
    f.jobs.register('process_knowledge', async job => {
      started = Date.now(); const root = f.db.insert('knowledge_processing_spans', { knowledge_id: doc.id, attempt: job.attempt, span_id: 'root-fixture', name: 'process_knowledge', kind: 'root', status: 'running', started_at: new Date(started).toISOString(), metadata: { job_id: job.jobId, queue_attempt: job.attempt } });
      await job.step('docreader', async () => { await new Promise(resolve => setTimeout(resolve, 20)); return { content_length: 4 }; }); ended = Date.now();
      f.db.update('knowledge_processing_spans', String(root.id), { status: 'done', finished_at: new Date(ended).toISOString(), duration_ms: ended - started }); return { knowledge_id: doc.id };
    });
    const job = f.jobs.create({ scope: { tenantId: f.ctx.tenantId, userId: f.ctx.userId }, requestId: 'actual-document-trace', kind: 'process_knowledge', recoveryPolicy: 'safe', payload: { context: f.ctx as any, knowledge_id: doc.id, knowledge_base_id: kb.id } });
    await f.service.observeDocumentJob(job.id, () => f.jobs.run(job.id)); await f.service.flush(); const root = f.spans.find(s => s.name === 'knowledge.parse'); assert.ok(root);
    assert.equal(root.startTimeUnixNano, String(BigInt(started) * 1000000n)); assert.equal(root.endTimeUnixNano, String(BigInt(ended) * 1000000n)); assert.equal(f.spans.some(s => s.name.startsWith('llm.')), false); assert.equal(f.db.all('SELECT id FROM model_usage').length, 0);
    const count = f.spans.length; await f.service.observeDocumentJob(job.id, () => f.jobs.run(job.id)); await f.service.flush(); assert.equal(f.spans.length, count);
  } finally { await f.close(); }
});
test('accepted root telemetry cannot link after real owner revocation, source deletion, configuration change or replacement claim', async () => {
  for (const mutation of ['logout', 'delete', 'user-source-delete', 'configuration', 'replacement'] as const) {
    const f = await fixture({ timeoutMs: 1000, maxQueue: 32 }); try {
      f.mode('root_wait'); const { session, start } = await f.run(); await until(() => f.spans.some(span => span.name === 'chat.turn'));
      assert.equal(f.db.get("SELECT count(*) AS n FROM session_events WHERE session_id=? AND type='observability/trace-linked'", String(session.id))?.n, 0);
      if (mutation === 'logout') f.auth.logout(f.ctx);
      else if (mutation === 'delete') await f.chat.delete(f.ctx, String(session.id));
      else if (mutation === 'user-source-delete') { const user = f.db.get("SELECT id FROM messages WHERE session_id=? AND role='user'", String(session.id))!; await f.chat.deleteMessage(f.ctx, String(session.id), String(user.id)); }
      else if (mutation === 'configuration') f.settings.updateIntegration(f.ctx, 'langfuse', { log_content: true });
      else f.db.run("UPDATE desktop_jobs SET payload=json_set(payload,'$.claim.ownerToken','replacement-owner') WHERE id=?", start.job_id);
      f.release(); await f.service.flush();
      assert.equal(f.db.get("SELECT count(*) AS n FROM session_events WHERE session_id=? AND type='observability/trace-linked'", String(session.id))?.n, 0, mutation);
      assert.equal(f.db.all('SELECT id FROM model_usage').length, 1);
    } finally { await f.close(); }
  }
});
test('actual Agent SSE model and source tool lifecycles produce linked usage spans without losing scoped citations', async () => {
  const f = await fixture(), agent = new AgentService(f.db, f.auth); try {
    f.mode('agent'); const kb = f.db.insert('knowledge_bases', { tenant_id: f.ctx.tenantId, name: 'Observed actual sources' }), doc = f.db.insert('knowledges', { tenant_id: f.ctx.tenantId, knowledge_base_id: kb.id, title: '实际文档' }), chunk = f.db.insert('chunks', { tenant_id: f.ctx.tenantId, knowledge_base_id: kb.id, knowledge_id: doc.id, content: '实际来源😀' });
    f.chat.dependencies.hooks!.agent = execution => agent.execute(execution);
    const session = f.chat.create(f.ctx), started = f.chat.start(f.ctx, String(session.id), { query: '查找实际来源', knowledge_base_ids: [kb.id], allowed_tools: ['grep_chunks'], max_rounds: 3 }, 'observed-agent', true);
    await f.chat.run(f.ctx, String(session.id), started.request_id); await f.service.flush(); const response = f.chat.response(f.ctx, String(session.id), started.request_id);
    assert.equal(response.references.length, 1); assert.equal(response.references[0].chunk_id, chunk.id); assert.equal(response.references[0].content, '实际来源😀');
    const root = f.spans.find(span => span.name === 'chat.turn'), tool = f.spans.find(span => span.name === 'agent.tool'), calls = f.spans.filter(span => span.name === 'llm.chat'); assert.ok(root && tool); assert.equal(calls.length, 2);
    assert.ok(calls.every(span => span.traceId === root.traceId && span.parentSpanId === root.spanId)); assert.equal(tool.parentSpanId, root.spanId); assert.ok(BigInt(tool.endTimeUnixNano) >= BigInt(tool.startTimeUnixNano));
    assert.equal(f.db.all('SELECT id FROM model_usage').length, 2); assert.equal(f.times().modelRequests, 2); assert.equal(f.chat.trajectory(f.ctx, String(session.id)).turns[0].usage.total_tokens, 6);
  } finally { await agent.close(); await f.close(); }
});
test('telemetry queue and close remain bounded while actual HTTP hangs and business streams still complete exactly once', async () => {
  const f = await fixture({ timeoutMs: 1000, maxQueue: 2 }); try {
    f.mode('wait'); const { response } = await f.run(); assert.ok(String(response.answer).includes('实际回答')); await until(() => f.spans.length === 2);
    assert.ok(f.db.all("SELECT value FROM desktop_meta WHERE key LIKE 'observability.%'").some(row => String(row.value).includes('queue_full')));
    const start = Date.now(); await f.service.close(); assert.ok(Date.now() - start < 700, 'owned HTTP abort must bound close independently of the 1000 ms queue deadline');
    const count = f.spans.length; f.mode('accepted'); await f.run(); await f.service.flush(); assert.equal(f.spans.length, count); assert.equal(f.db.all('SELECT id FROM model_usage').length, 2);
  } finally { await f.close(); }
});
test('foreground and independent real actors retain distinct actual lifecycles, model parents and one accepted chat link', async () => {
  for (const mode of ['actor', 'spawn'] as const) {
    const f = await fixture(), agent = new AgentService(f.db, f.auth); try {
      f.mode(mode); f.chat.dependencies.hooks!.agent = execution => agent.execute(execution);
      const session = f.chat.create(f.ctx), started = f.chat.start(f.ctx, String(session.id), { query: '委派实际子任务', knowledge_base_ids: [], allowed_tools: ['actor'], max_rounds: 3 }, `observed-${mode}`, true);
      await f.chat.run(f.ctx, String(session.id), started.request_id);
      await until(() => f.chat.actors(f.ctx, String(session.id)).items[0]?.last_outcome === 'success');
      const actor = f.chat.actors(f.ctx, String(session.id)).items[0];
      if (mode === 'spawn') await until(() => f.jobs.get(actor.metadata.job_id, { tenantId: f.ctx.tenantId, userId: f.ctx.userId }).status === 'completed');
      await f.service.flush();
      const chatRoot = f.spans.find(span => span.name === 'chat.turn'), actorRoot = f.spans.find(span => span.name === 'agent.run'); assert.ok(chatRoot && actorRoot);
      if (mode === 'actor') { assert.equal(actorRoot.traceId, chatRoot.traceId); assert.equal(actorRoot.parentSpanId, chatRoot.spanId); }
      else { assert.notEqual(actorRoot.traceId, chatRoot.traceId); assert.equal(actorRoot.parentSpanId, undefined); }
      assert.ok(f.spans.some(span => span.name === 'llm.chat' && span.traceId === actorRoot.traceId && span.parentSpanId === actorRoot.spanId));
      assert.equal(f.times().modelRequests, 3); assert.equal(f.db.all('SELECT id FROM model_usage').length, 3);
      assert.equal(f.db.get("SELECT count(*) AS n FROM session_events WHERE session_id=? AND type='observability/trace-linked'", String(session.id))?.n, 1);
      assert.equal(f.chat.trajectory(f.ctx, String(session.id)).turns[0].observability.trace_id, chatRoot.traceId);
    } finally { await agent.close(); await f.close(); }
  }
});
test('real isolated Python upload/workflow reports exact persisted root and stage intervals and preserves local output', async () => {
  const f = await fixture(); let workflow: DocumentWorkflow | undefined; try {
    for (const row of f.db.all('SELECT id FROM models')) f.models.delete(f.ctx, String(row.id));
    const kb = f.db.insert('knowledge_bases', { tenant_id: f.ctx.tenantId, name: 'Observed local parser', indexing_strategy: { vector_enabled: false, wiki_enabled: false, graph_enabled: false } });
    const parser = new DocumentParser({ pythonExecutable: process.env.MARLIN_TEST_PYTHON ?? '/tmp/marlin-parser-isolation-20261010/bin/python', workerPath: resolve('../../workers/document/worker.py') });
    workflow = new DocumentWorkflow(f.db, f.auth, f.jobs, f.models, undefined, { parser, index: new SearchIndex(f.db), scheduler: () => {} });
    const uploaded = await workflow.upload(f.ctx, String(kb.id), { name: '实际观测 文档.md', bytes: Buffer.from('# 实际文档\n\n真实解析来源😀，保留原文。') }, 'observed-local-upload');
    const result = await f.service.observeDocumentJob(uploaded.task_id, () => f.jobs.run(uploaded.task_id)); assert.equal(result.status, 'completed'); await f.service.flush();
    const facts = workflow.stages(f.ctx, String(uploaded.knowledge.id)).spans as any[], root = facts.find(span => span.kind === 'root'), trace = f.spans.find(span => span.name === 'knowledge.parse'); assert.ok(root && trace);
    assert.equal(trace.startTimeUnixNano, String(BigInt(Date.parse(root.started_at)) * 1000000n)); assert.equal(trace.endTimeUnixNano, String(BigInt(Date.parse(root.finished_at)) * 1000000n));
    const stages = f.spans.filter(span => span.name === 'knowledge.stage'); assert.equal(stages.length, facts.filter(span => span.kind !== 'root' && span.finished_at).length);
    for (const stage of stages) { const operation = stage.attributes.find((attribute: any) => attribute.key === 'langfuse.observation.metadata.operation').value.stringValue, source = facts.find(span => span.name === operation); assert.ok(source); assert.equal(stage.startTimeUnixNano, String(BigInt(Date.parse(source.started_at)) * 1000000n)); assert.equal(stage.endTimeUnixNano, String(BigInt(Date.parse(source.finished_at)) * 1000000n)); }
    const doc = f.db.read('knowledges', String(uploaded.knowledge.id))!; assert.equal(doc.parse_status, 'completed'); assert.ok(String((doc.metadata as any).content).includes('真实解析来源😀')); assert.equal(doc.summary_status, 'needs_configuration');
    assert.equal(f.spans.some(span => span.name.startsWith('llm.')), false); assert.equal(f.db.all('SELECT id FROM model_usage').length, 0); assert.equal(f.times().modelRequests, 0);
  } finally { await workflow?.close(); await f.close(); }
});
