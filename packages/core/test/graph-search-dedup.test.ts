import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { AuthService } from '../src/auth/index.js';
import { GraphService } from '../src/graph/index.js';
import { ModelConfigurationService } from '../src/settings/model-configuration.js';
import { CredentialVault } from '../src/storage/credentials.js';
import { CoreDatabase } from '../src/storage/database.js';
import type { JsonObject } from '../src/contracts.js';

test('graph search excludes already retrieved chunks before taking its independent top K', async () => {
  const root = mkdtempSync(join(tmpdir(), 'graph-independent-')), db = new CoreDatabase(root), auth = new AuthService(db);
  const ctx = auth.register({ username: 'graph-independent', password: 'IndependentGraphFixture2026' }).context;
  const models = new ModelConfigurationService(db, auth, new CredentialVault(root));
  const server = createServer(async (request, response) => {
    assert.equal(db.sqlite.inTransaction, false);
    let raw = ''; for await (const part of request) raw += part;
    const body = JSON.parse(raw), prompt = body.messages.at(-1).content;
    const result = prompt.includes('GRAPH_ENTITIES') ? [{ chunk_key: 'c001', entities: [{ name: 'Orca' }] }] : { node: [{ name: 'Orca' }], relation: [] };
    response.setHeader('content-type', 'application/json');
    response.end(JSON.stringify({ choices: [{ message: { content: JSON.stringify(result) }, finish_reason: 'stop' }], usage: { prompt_tokens: 3, completion_tokens: 2, total_tokens: 5 } }));
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = server.address(); assert.ok(address && typeof address !== 'string');
  const model = models.create(ctx, { name: 'local protocol fixture', type: 'KnowledgeQA', source: 'openai', parameters: { model: 'controlled', base_url: `http://127.0.0.1:${address.port}/v1`, api_key: 'fixture-key' } });
  const kb = db.insert('knowledge_bases', { tenant_id: ctx.tenantId, name: 'independent graph evidence', indexing_strategy: { graph_enabled: true }, summary_model_id: model.id });
  const nodes: JsonObject[] = [];
  const graph = new GraphService(db, auth, models, undefined, { transport: async (context, id, statement, parameters) => {
    auth.assertCan(context, 'read'); assert.equal(id, kb.id); assert.equal(parameters.tenant_id, ctx.tenantId);
    if (statement.includes('MARLIN_WRITE_GENERATION')) {
      nodes.push(...parameters.nodes as JsonObject[]);
      return { state: 'connected', records: [{ nodes: (parameters.nodes as JsonObject[]).length, relations: 0 }] };
    }
    assert.ok(statement.includes('MARLIN_READ_GENERATIONS'));
    const active = parameters.active as JsonObject[];
    return { state: 'connected', records: nodes.filter(node => active.some(item => item.knowledge_id === node.knowledge_id && item.generation === node.generation)).slice(Number(parameters.offset), Number(parameters.offset) + Number(parameters.limit)).map(node => ({ node })) };
  } });
  try {
    for (let i = 0; i < 2; i++) {
      const document = db.insert('knowledges', { tenant_id: ctx.tenantId, knowledge_base_id: kb.id, title: `evidence ${i}`, enable_status: 'enabled' });
      db.insert('chunks', { tenant_id: ctx.tenantId, knowledge_base_id: kb.id, knowledge_id: document.id, content: `Orca independent source ${i}`, metadata: { source_refs: [{ source_ref: `text:${i}`, block_index: 0 }] } });
      assert.equal((await graph.build(ctx, String(kb.id), String(document.id))).status, 'completed');
    }
    const all = await graph.search(ctx, String(kb.id), 'Orca', { limit: 10 });
    const items = all.items as JsonObject[]; assert.equal(items.length, 2);
    const next = await graph.search(ctx, String(kb.id), 'Orca', { limit: 1, seenChunkIds: [String(items[0]!.chunk_id)] });
    assert.deepEqual((next.items as JsonObject[]).map(item => item.chunk_id), [items[1]!.chunk_id]);
    assert.equal(db.get('SELECT count(*) AS n FROM model_usage')?.n, 4);
  } finally {
    await graph.close(); await new Promise<void>(resolve => { server.closeAllConnections(); server.close(() => resolve()); });
    db.close(); rmSync(root, { recursive: true, force: true });
  }
});
