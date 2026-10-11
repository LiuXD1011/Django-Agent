import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { CoreApplication } from '../src/application.js';

test('application Agent routes use graph and skill services and deny private web fetch before opening a socket', async () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-app-agent-hooks-'));
  const app = new CoreApplication(root, { allowAutoSetup: true });
  let calls = 0, privateRequests = 0;
  const server = createServer(async (req, res) => {
    if (req.url === '/private') { privateRequests++; res.end('Must not be read'); return; }
    let raw = ''; for await (const part of req) raw += part;
    const body = JSON.parse(raw); calls++;
    const finished = body.messages.some((message: any) => message.role === 'tool');
    const tools = [
      ['query_knowledge_graph', { query: 'Graph fixture' }],
      ['read_skill', { skill_name: 'missing-business-skill' }],
      ['web_fetch', { url: origin + '/private', max_chars: 100 }],
    ].map(([name, args], index) => ({ index, id: `hook-${index}`, type: 'function', function: { name, arguments: JSON.stringify(args) } }));
    res.setHeader('content-type', 'text/event-stream');
    res.end(`data: ${JSON.stringify({ choices: [{ delta: finished ? { content: 'Verified application adapters' } : { tool_calls: tools }, finish_reason: finished ? 'stop' : 'tool_calls' }], usage: { prompt_tokens: 2, completion_tokens: 1, total_tokens: 3 } })}\n\ndata: [DONE]\n\n`);
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = server.address(); assert.ok(address && typeof address !== 'string');
  const origin = `http://127.0.0.1:${address.port}`;
  try {
    const issue = app.auth.autoSetup({ password: 'Ephemeral application fixture 2026' });
    app.auth.updatePreferences(issue.context, { enable_memory: false });
    app.models.create(issue.context, { name: 'Local hook protocol', type: 'KnowledgeQA', source: 'openai', is_default: true, parameters: { model: 'fixture', base_url: origin + '/v1' } });
    const kb = app.knowledge.knowledgeBases.create(issue.context, { name: 'Graph fixture', indexing_strategy: { graph_enabled: true } });
    const session = app.chat.create(issue.context, { agent_config: { web_search_enabled: true } });
    const result = await app.dispatch({ protocol: 1, id: 'actual-app-agent-hooks', method: 'POST', path: `/api/v1/agent-chat/${session.id}`, body: { query: 'Verify services', knowledge_base_ids: [kb.id!], allowed_tools: ['query_knowledge_graph', 'read_skill', 'web_fetch'], web_search_enabled: true, max_rounds: 3 } }, { transport: 'ipc', access: issue.credentials.access });
    assert.equal(result.response.status, 200);
    const response = app.chat.response(issue.context, String(session.id), 'actual-app-agent-hooks');
    assert.equal(response.answer, 'Verified application adapters');
    const results = response.message.agent_steps[0].tool_calls.map((tool: any) => tool.result);
    assert.equal(results.length, 3);
    assert.equal(results[0].data.state, 'pending', 'the actual GraphService reports missing Neo4j configuration');
    assert.ok(results[0].data.warnings.some((warning: any) => warning.code === 'graph_needs_configuration'));
    assert.equal(results[1].error_type, 'NOT_FOUND', 'the business catalog is connected, but this skill is absent');
    assert.equal(results[2].error_type, 'EXECUTION_ERROR', 'the controlled web adapter denies a private address');
    assert.equal(results.some((result: any) => result.error_type === 'NOT_CONFIGURED'), false);
    assert.equal(privateRequests, 0); assert.equal(calls, 2);
    assert.equal(app.database.all('SELECT id FROM model_usage').length, 2);
  } finally {
    await app.close(); server.closeAllConnections();
    await new Promise<void>(resolve => server.close(() => resolve()));
    rmSync(root, { recursive: true, force: true });
  }
});

test('application chat dispatch emits real optional OTLP and exposes only an authorized accepted trace link', async () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-app-trace-'));
  const app = new CoreApplication(root, { allowAutoSetup: true });
  const spans: any[] = []; let modelCalls = 0;
  const server = createServer(async (req, res) => {
    let raw = ''; for await (const part of req) raw += part;
    assert.equal(app.database.sqlite.inTransaction, false);
    if (req.url === '/api/public/otel/v1/traces') {
      spans.push(...JSON.parse(raw).resourceSpans[0].scopeSpans[0].spans);
      res.setHeader('content-type', 'application/json'); res.end('{}');
    } else {
      assert.equal(req.url, '/v1/chat/completions'); modelCalls++;
      res.setHeader('content-type', 'text/event-stream');
      res.end(`data: ${JSON.stringify({ choices: [{ delta: { content: 'Actual application trace', role: 'assistant' }, finish_reason: 'stop' }], usage: { prompt_tokens: 2, completion_tokens: 1, total_tokens: 3 } })}\n\ndata: [DONE]\n\n`);
    }
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = server.address(); assert.ok(address && typeof address !== 'string');
  const origin = `http://127.0.0.1:${address.port}`;
  try {
    const issue = app.auth.autoSetup({ password: 'Ephemeral application trace fixture 2026' });
    app.auth.updatePreferences(issue.context, { enable_memory: false });
    app.settings.updateIntegration(issue.context, 'langfuse', { enabled: true, base_url: origin, ui_base_url: origin, ui_project_id: 'qa-project', trace_links_enabled: true, sample_rate: 1, public_key: 'fixture-public', secret_key: 'fixture-secret', log_content: false });
    app.models.create(issue.context, { name: 'Local trace protocol', type: 'KnowledgeQA', source: 'openai', is_default: true, parameters: { model: 'fixture', base_url: origin + '/v1' } });
    const session = app.chat.create(issue.context);
    const result = await app.dispatch({ protocol: 1, id: 'actual-application-trace', method: 'POST', path: `/api/v1/knowledge-chat/${session.id}`, body: { query: 'Private application trace input', knowledge_base_ids: [] } }, { transport: 'ipc', access: issue.credentials.access });
    assert.equal(result.response.status, 200);
    const deadline = Date.now() + 2000;
    let trajectory: any;
    do {
      trajectory = app.chat.trajectory(issue.context, String(session.id));
      if (trajectory.turns[0]?.observability?.trace_url) break;
      await new Promise(resolve => setTimeout(resolve, 10));
    } while (Date.now() < deadline);
    const rootSpan = spans.find(span => span.name === 'chat.turn');
    assert.ok(rootSpan, 'the application route must connect the business observer');
    assert.ok(spans.some(span => span.name === 'llm.chat'));
    assert.equal(trajectory.turns[0].observability.trace_url, `${origin}/project/qa-project/traces/${rootSpan.traceId}`);
    assert.equal(JSON.stringify(spans).includes('Private application trace input'), false);
    assert.equal(modelCalls, 1);
  } finally {
    await app.close(); server.closeAllConnections();
    await new Promise<void>(resolve => server.close(() => resolve()));
    rmSync(root, { recursive: true, force: true });
  }
});
