import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdtempSync, rmSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { CoreApplication } from '../src/application.js';
import type { JsonObject } from '../src/contracts.js';

test('application chat reports actual missing Neo4j readiness and avoids graph work for an explicit empty scope', async () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-application-chat-graph-'));
  const app = new CoreApplication(root, { allowAutoSetup: true });
  let calls = 0;
  const server = createServer(async (request, response) => {
    let raw = ''; for await (const bytes of request) raw += bytes;
    const body = JSON.parse(raw);
    assert.equal(body.stream, true, 'missing Neo4j must not trigger extraction-model requests');
    assert.equal(app.database.sqlite.inTransaction, false);
    calls++;
    response.setHeader('content-type', 'text/event-stream');
    response.end(`data: ${JSON.stringify({ choices: [{ delta: { content: 'Controlled protocol answer' }, finish_reason: 'stop' }], usage: { prompt_tokens: 2, completion_tokens: 1, total_tokens: 3 } })}\n\ndata: [DONE]\n\n`);
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    const issue = app.auth.autoSetup({ password: 'application-graph-fixture-password' });
    app.auth.updatePreferences(issue.context, { enable_memory: false });
    const address = server.address(); assert.ok(address && typeof address !== 'string');
    app.models.create(issue.context, { name: 'Controlled graph protocol fixture', type: 'KnowledgeQA', source: 'openai', is_default: true, parameters: { model: 'controlled', base_url: `http://127.0.0.1:${address.port}/v1` } });
    const kb = app.knowledge.knowledgeBases.create(issue.context, { name: 'Graph readiness fixture', indexing_strategy: { graph_enabled: true } });
    const session = app.chat.create(issue.context, { title: 'Graph readiness', knowledge_base_ids: [kb.id!] });
    const ask = async (ids: string[]) => {
      const id = randomUUID();
      const result = await app.dispatch({ protocol: 1, id, method: 'POST', path: `/api/v1/knowledge-chat/${session.id}`, body: { query: 'Graph readiness fixture', knowledge_base_ids: ids } }, { transport: 'ipc', access: issue.credentials.access });
      assert.equal(result.response.status, 200);
      const answer = app.chat.response(issue.context, String(session.id), id);
      return ((answer.message as JsonObject).agent_steps as JsonObject[]).flatMap(step => (step.degradations as JsonObject[]) ?? []);
    };
    const warnings = await ask([String(kb.id)]);
    assert.ok(warnings.some(row => row.reason === 'graph_needs_configuration'));
    assert.equal(warnings.some(row => row.reason === 'graph_retrieval_not_configured'), false);
    assert.equal((await ask([])).some(row => row.stage === 'graph'), false);
    assert.equal(calls, 2);
  } finally {
    await app.close();
    server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve()));
    rmSync(root, { recursive: true, force: true });
  }
});
