import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';
import { CoreApplication } from '../src/application.js';
import { createCoreHttpServer } from '../src/adapters/http.js';
import { CoreIpcAdapter } from '../src/adapters/ipc.js';
import type { HttpMethod, JsonObject } from '../src/contracts.js';
import { DocumentParser } from '../src/documents/parser.js';
import { SystemDiagnostics } from '../src/system/diagnostics.js';
import { embeddingBinding } from '../src/documents/pipeline.js';

const endpoints: Array<[HttpMethod, string]> = [
  ['GET', '/api/v1/system/parser-engines'],
  ['GET', '/api/v1/system/storage-engine-status'],
  ['POST', '/api/v1/system/parser-engines/check'],
  ['POST', '/api/v1/system/storage-engine-check'],
];

test('retained system diagnostics are reachable through actual HTTP without false missing-parser success', async () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-system-http-'));
  const app = new CoreApplication(root, { allowAutoSetup: true });
  const http = createCoreHttpServer(app, { port: 0 });
  try {
    const issue = app.auth.autoSetup({ password: 'system-diagnostics-http-fixture' });
    const { origin } = await http.listen();
    const statuses = [];
    const results: JsonObject[] = [];
    for (const [method, path] of endpoints) {
      const response = await fetch(origin + path, { method, headers: { authorization: `Bearer ${issue.credentials.access}`, ...(method === 'POST' ? { 'content-type': 'application/json' } : {}) }, ...(method === 'POST' ? { body: '{}' } : {}) });
      statuses.push(response.status);
      results.push((await response.json() as JsonObject).data as JsonObject);
    }
    assert.deepEqual(statuses, [200, 200, 200, 200]);
    assert.equal((results[0]!.items as JsonObject[])[0]!.status, 'not_configured');
    assert.equal((results[0]!.items as JsonObject[])[0]!.available, false);
    assert.equal(results[1]!.status, 'available');
    assert.equal((results[1]!.checks as JsonObject).integrity, true);
    assert.equal((results[1]!.checks as JsonObject).foreign_key_violations, 0);
    assert.equal((results[1]!.checks as JsonObject).fts5, true);
    assert.equal((results[1]!.checks as JsonObject).vector_extension, true);
    assert.match(String((results[1]!.database as JsonObject).version), /^\d+\.\d+/);
    assert.match(String((results[1]!.vector as JsonObject).version), /^v?\d+\.\d+/);
    assert.equal(JSON.stringify(results).includes(root), false);
    const refused = await fetch(origin + endpoints[2]![1], { method: 'POST', headers: { authorization: `Bearer ${issue.credentials.access}`, 'content-type': 'application/json' }, body: JSON.stringify({ path: '/arbitrary', url: 'http://127.0.0.1/' }) });
    assert.equal(refused.status, 400);
    for (const [path, selector] of [[endpoints[2]![1], { engine: 'builtin' }], [endpoints[3]![1], { provider: 'local' }], [endpoints[3]![1], { engine: 'sqlite' }]] as const) {
      const response = await fetch(origin + path, { method: 'POST', headers: { authorization: `Bearer ${issue.credentials.access}`, 'content-type': 'application/json' }, body: JSON.stringify(selector) });
      assert.equal(response.status, 200); await response.arrayBuffer();
    }
    assert.equal(app.database.get('SELECT count(*) AS n FROM model_usage')?.n, 0);
  } finally { await http.close(); await app.close(); rmSync(root, { recursive: true, force: true }); }
});

test('actual owned Python capability inspection preserves format, dependency, version and no local OCR claims', async () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-system-parser-'));
  const pythonExecutable = process.env.MARLIN_TEST_PYTHON ?? spawnSync('python', ['-c', 'import sys;print(sys.executable)'], { encoding: 'utf8' }).stdout.trim();
  const parser = new DocumentParser({ pythonExecutable, workerPath: resolve('../../workers/document/worker.py'), timeoutMs: 60000 });
  const app = new CoreApplication(root, { allowAutoSetup: true, parser });
  try {
    const issue = app.auth.autoSetup({ password: 'system-actual-parser-fixture' });
    const diagnostics = new SystemDiagnostics(app.database, app.auth, app.vault, app.models, { parser });
    const before = app.database.get('SELECT total_changes() AS n')?.n;
    const result = await diagnostics.parserEngines(issue.context);
    const engine = (result.items as JsonObject[])[0]!;
    assert.equal(engine.available, true); assert.equal(engine.parser_version, 'marlin-parser-v1');
    assert.equal((engine.format_status as JsonObject).txt, true);
    assert.equal((engine.dependency_status as JsonObject).Pillow, true);
    assert.equal(engine.ocr_available, false); assert.equal(engine.caption_available, false); assert.equal(engine.vlm_available, false);
    assert.equal((engine.format_status as JsonObject).doc, (engine.dependency_status as JsonObject).LibreOffice === true && (engine.dependency_status as JsonObject)['msoffcrypto-tool'] === true && (engine.format_status as JsonObject).docx === true);
    assert.equal(engine.dependency_versions_status, 'not_reported_by_worker');
    assert.equal(app.database.get('SELECT total_changes() AS n')?.n, before);
    assert.equal(JSON.stringify(result).includes(pythonExecutable), false);
    const controller = new AbortController(); controller.abort();
    await assert.rejects(diagnostics.parserEngines(issue.context, { signal: controller.signal }), { code: 'diagnostic_cancelled' });
    app.auth.logout(issue.context);
    await assert.rejects(diagnostics.parserEngines(issue.context), { code: 'unauthorized' });
  } finally { await app.close(); rmSync(root, { recursive: true, force: true }); }
});

test('SQLite probes expose real degraded state and system info exposes tenant dimensions without secrets', async () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-system-state-'));
  const app = new CoreApplication(root, { allowAutoSetup: true });
  try {
    const issue = app.auth.autoSetup({ password: 'system-state-fixture' });
    const diagnostics = new SystemDiagnostics(app.database, app.auth, app.vault, app.models);
    const initial = diagnostics.info(issue.context);
    assert.equal(initial.graph_database_engine, 'Not Enabled');
    assert.equal(initial.neo4j_configured, false); assert.equal(initial.graph_rag_enabled, false);
    assert.equal((initial.bailian as JsonObject).local_embedding_dimension, null);
    const secret = 'diagnostic-secret-do-not-project';
    const model = app.models.create(issue.context, { name: 'dimension-fixture', type: 'Embedding', source: 'openai', is_default: true, parameters: { base_url: 'http://127.0.0.1:12345/v1', api_key: secret, dimension: 1536 } });
    app.settings.updateIntegration(issue.context, 'neo4j', { enabled: true, uri: 'bolt://127.0.0.1:7687', username: 'fixture', password: secret });
    const info = diagnostics.info(issue.context);
    assert.equal((info.bailian as JsonObject).local_embedding_dimension, 1536);
    assert.equal((info.embedding as JsonObject).dimension_verified, false);
    assert.equal(info.graph_database_engine, 'neo4j'); assert.equal(info.graph_connection_verified, false);
    assert.equal(info.graph_adapter_status, 'configured_unverified');
    assert.equal(JSON.stringify(info).includes(secret), false); assert.equal(JSON.stringify(info).includes('7687'), false);
    const other = app.auth.register({ email: 'diagnostic-other@example.invalid', password: 'diagnostic-other-fixture' });
    assert.equal((diagnostics.info(other.context).bailian as JsonObject).local_embedding_dimension, null);
    const kb = app.knowledge.knowledgeBases.create(issue.context, { name: '真实向量维度' });
    const doc = app.database.insert('knowledges', { tenant_id: issue.context.tenantId, knowledge_base_id: kb.id, title: '本地SQLite诊断样本', parse_status: 'completed', metadata: { content: '真实维度检查' } });
    const chunk = app.database.insert('chunks', { tenant_id: issue.context.tenantId, knowledge_base_id: kb.id, knowledge_id: doc.id, content: '真实维度检查', start_at: 0, end_at: 6, seq_id: '17' });
    const binding = embeddingBinding(app.models.configuration(issue.context, String(model.id)));
    // Locally generated vector data verifies real sqlite-vec storage, not a model/provider claim.
    await app.searchIndex.indexChunk({ tenantId: issue.context.tenantId, knowledgeBaseIds: [String(kb.id)] }, String(chunk.id), { ...binding, runtime: { embed: async () => ({ vectors: [Array.from({ length: 1536 }, (_, index) => index === 0 ? 1 : 0)], usage: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, cached_tokens: 0, reasoning_tokens: 0 } }) } });
    const verified = diagnostics.info(issue.context).embedding as JsonObject;
    assert.equal(verified.indexed_dimension, 1536); assert.equal(verified.dimension_verified, true);
    app.models.update(issue.context, String(model.id), { parameters: { dimension: 1024 } });
    assert.equal((diagnostics.info(issue.context).embedding as JsonObject).dimension_verified, false);
    app.database.run('DROP TABLE chunks_fts');
    assert.equal(diagnostics.storageStatus(issue.context).status, 'degraded');
    assert.equal(app.database.get('SELECT count(*) AS n FROM model_usage')?.n, 0);
    app.auth.logout(issue.context);
    assert.throws(() => diagnostics.storageStatus(issue.context), { code: 'unauthorized' });
  } finally { await app.close(); rmSync(root, { recursive: true, force: true }); }
});

test('a broken actual helper reports unavailable rather than fabricated capabilities', async () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-system-unavailable-'));
  const parser = new DocumentParser({ pythonExecutable: '/missing-diagnostic-python', workerPath: resolve('../../workers/document/worker.py') });
  const app = new CoreApplication(root, { allowAutoSetup: true });
  try {
    const issue = app.auth.autoSetup({ password: 'system-unavailable-fixture' });
    const diagnostics = new SystemDiagnostics(app.database, app.auth, app.vault, app.models, { parser });
    const result = await diagnostics.parserEngines(issue.context), engine = (result.items as JsonObject[])[0]!;
    assert.equal(engine.status, 'unavailable'); assert.equal(engine.available, false); assert.equal(engine.error_code, 'parser_start_failed');
    assert.equal(JSON.stringify(result).includes('/missing'), false);
  } finally { await app.close(); rmSync(root, { recursive: true, force: true }); }
});

test('retained diagnostics are reachable through the real IPC adapter', async () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-system-ipc-'));
  const app = new CoreApplication(root, { allowAutoSetup: true });
  try {
    const ipc = new CoreIpcAdapter(app);
    assert.equal((await ipc.invoke({ protocol: 1, id: randomUUID(), method: 'POST', path: '/api/v1/auth/auto-setup', body: { password: 'system-diagnostics-ipc-fixture' } })).status, 200);
    const statuses = [];
    for (const [method, path] of endpoints) statuses.push((await ipc.invoke({ protocol: 1, id: randomUUID(), method, path, ...(method === 'POST' ? { body: {} } : {}) })).status);
    assert.deepEqual(statuses, [200, 200, 200, 200]);
  } finally { await app.close(); rmSync(root, { recursive: true, force: true }); }
});
