import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { AuthService } from '../src/auth/index.js';
import { BuiltinToolRunner } from '../src/agents/tools.js';
import type { ToolResult } from '../src/agents/types.js';
import { ChatService } from '../src/chat/index.js';
import { IntegrationService } from '../src/integrations/index.js';
import { ModelConfigurationService, SettingsService } from '../src/settings/index.js';
import { CredentialVault } from '../src/storage/credentials.js';
import { CoreDatabase } from '../src/storage/database.js';

// Integration fixtures use actual SQLite/Auth/ChatExecution and localhost HTTP.
// No renderer, user data, configured vendor model or fabricated usage is used.
async function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'marlin-web-search-settings-'));
  const db = new CoreDatabase(root), auth = new AuthService(db), vault = new CredentialVault(root);
  const owner = auth.register({ username: 'owner', password: 'Search fixture password' }).context;
  const foreign = auth.register({ username: 'foreign', password: 'Search fixture password' }).context;
  const settings = new SettingsService(db, auth, vault);
  const integrations = new IntegrationService(db, auth, settings);
  const chat = new ChatService(db, auth, { models: new ModelConfigurationService(db, auth, vault) });
  const runner = new BuiltinToolRunner(db, { integrations });
  const received: { path: string; query: string | null; authenticated: boolean }[] = [];
  const server = createServer((request, response) => {
    assert.equal(db.sqlite.inTransaction, false, 'External search must not run inside a database transaction');
    const url = new URL(request.url!, 'http://localhost');
    received.push({ path: url.pathname, query: url.searchParams.get('q'), authenticated: request.headers.authorization === 'Bearer fixture-search-key' });
    response.setHeader('content-type', 'application/json');
    response.end(JSON.stringify({ results: [{ title: url.pathname, url: `https://example.org${url.pathname}`, content: 'Controlled HTTP search citation' }] }));
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = server.address(); assert.ok(address && typeof address !== 'string');
  const create = (name: string, context = owner) => settings.createProvider(context, 'web_search_providers', {
    name, provider: 'searxng', url: `http://127.0.0.1:${address.port}/${name}`, enabled: true, api_key: 'fixture-search-key',
  });
  const first = create('first'), second = create('second');
  db.update('generic_resources', String(first.id), { updated_at: '2026-01-01T00:00:00.000Z' });
  db.update('generic_resources', String(second.id), { updated_at: '2026-02-01T00:00:00.000Z' });
  let request = 0;
  const ask = async () => {
    let entered = false, failure: unknown, result: ToolResult | undefined;
    chat.dependencies.hooks = { agent: async execution => {
      entered = true;
      try { result = await runner.execute('web_search', { query: '检索配置验收' }, execution); }
      catch (error) { failure = error; throw error; }
      return { content: 'Controlled search integration', refs: [], steps: [], durationMs: 0 };
    } };
    const session = chat.create(owner);
    const start = chat.start(owner, String(session.id), { query: 'Verify configured web search', knowledge_base_ids: [] }, `search-fixture-${++request}`, true);
    await chat.run(owner, String(session.id), start.request_id);
    assert.ok(entered, 'Exercise the tool through a real authenticated, fenced execution');
    if (failure) throw failure;
    assert.equal(chat.jobs.get(start.job_id, { tenantId: owner.tenantId, userId: owner.userId }).status, 'completed');
    assert.equal(db.all('select id from model_usage').length, 0);
    assert.ok(result);
    return result;
  };
  return { db, auth, vault, settings, integrations, owner, foreign, create, first, second, received, ask,
    close: async () => {
      await chat.close(); await chat.jobs.close(); await integrations.close();
      await new Promise<void>(resolve => { server.closeAllConnections(); server.close(() => resolve()); });
      db.close(); rmSync(root, { recursive: true, force: true });
    },
  };
}

test('explicit web provider selection remains stable when a different provider is edited', async () => {
  const f = await fixture();
  try {
    f.settings.setKV(f.owner, 'web-search-config', { enabled: true, provider_id: f.first.id! });
    f.settings.updateProvider(f.owner, 'web_search_providers', String(f.second.id), { name: 'second edited' });
    const result = await f.ask();
    assert.equal(result.error, undefined);
    assert.deepEqual(f.received, [{ path: '/first', query: '检索配置验收', authenticated: true }]);
    assert.equal(JSON.parse(result.output)[0].url, 'https://example.org/first');
  } finally { await f.close(); }
});

test('tenant web search disabled setting prevents every external search request', async () => {
  const f = await fixture();
  try {
    f.settings.setKV(f.owner, 'web-search-config', { enabled: false, provider_id: f.first.id! });
    const result = await f.ask();
    assert.equal(result.error_type, 'NOT_CONFIGURED');
    assert.match(result.error!, /disabled/i);
    assert.deepEqual(f.received, []);
  } finally { await f.close(); }
});

test('web search without an explicit provider retains the existing latest active provider rule', async () => {
  const f = await fixture();
  try {
    assert.equal((await f.ask()).error, undefined);
    assert.equal(f.received[0]?.path, '/second');
    f.settings.setKV(f.owner, 'web-search-config', { enabled: true, provider_id: '' });
    assert.equal((await f.ask()).error, undefined);
    assert.equal(f.received[1]?.path, '/second');
  } finally { await f.close(); }
});

test('a selected inactive or deleted web provider never falls back to another active service', async () => {
  const f = await fixture();
  try {
    f.settings.setKV(f.owner, 'web-search-config', { enabled: true, provider_id: f.first.id! });
    f.settings.updateProvider(f.owner, 'web_search_providers', String(f.first.id), { status: 'inactive' });
    assert.equal((await f.ask()).error_type, 'NOT_CONFIGURED');
    f.settings.updateProvider(f.owner, 'web_search_providers', String(f.first.id), { status: 'active' });
    f.settings.deleteProvider(f.owner, 'web_search_providers', String(f.first.id));
    assert.equal((await f.ask()).error_type, 'NOT_CONFIGURED');
    assert.deepEqual(f.received, []);
  } finally { await f.close(); }
});

test('historical foreign or malformed provider selections fail closed without sending a search', async () => {
  const f = await fixture();
  try {
    const foreign = f.create('foreign', f.foreign);
    for (const provider_id of [foreign.id!, 123]) {
      f.db.update('tenants', f.owner.tenantId, { web_search_config: { enabled: true, provider_id } });
      assert.equal((await f.ask()).error_type, 'NOT_CONFIGURED');
    }
    assert.deepEqual(f.received, []);
  } finally { await f.close(); }
});

test('web search configuration validates types and scopes selection before persisting changes', async () => {
  const f = await fixture();
  try {
    const foreign = f.create('foreign', f.foreign);
    const mcp = f.settings.createProvider(f.owner, 'mcp_services', { name: 'unrelated MCP', url: 'http://localhost:8080/mcp' });
    const inactive = f.create('inactive');
    f.settings.updateProvider(f.owner, 'web_search_providers', String(inactive.id), { status: 'inactive' });
    const deleted = f.create('deleted'); f.settings.deleteProvider(f.owner, 'web_search_providers', String(deleted.id));
    f.settings.setKV(f.owner, 'web-search-config', { enabled: true, provider_id: f.first.id!, notes: 'preserved setting' });
    const before = f.settings.getKV(f.owner, 'web-search-config');
    for (const changes of [{ enabled: 'true' }, { enabled: 1 }, { provider_id: 123 }, { provider_id: foreign.id! }, { provider_id: mcp.id! }, { provider_id: inactive.id! }, { provider_id: deleted.id! }, { provider_id: 'missing' }]) {
      assert.throws(() => f.settings.setKV(f.owner, 'web-search-config', changes), (error: any) => error.status === 400 && error.code === 'invalid_web_search_config');
      assert.deepEqual(f.settings.getKV(f.owner, 'web-search-config'), before);
    }
    const saved = f.settings.setKV(f.owner, 'web-search-config', { enabled: false });
    assert.equal(saved.value.notes, 'preserved setting');
  } finally { await f.close(); }
});

test('web provider credentials remain encrypted on blank edits and explicit clearing changes actual HTTP authentication', async () => {
  const f = await fixture();
  try {
    const id = String(f.first.id);
    f.settings.setKV(f.owner, 'web-search-config', { enabled: true, provider_id: id });
    f.settings.updateProvider(f.owner, 'web_search_providers', id, { name: 'first edited', api_key: '' });
    assert.equal(f.settings.providerCredentials(f.owner, 'web_search_providers', id).fields.api_key.configured, true);
    assert.match(String(f.db.read('generic_resources', id)!.data.api_key), /^enc:v1:/);
    assert.equal(JSON.stringify(f.settings.getProvider(f.owner, 'web_search_providers', id)).includes('fixture-search-key'), false);
    assert.equal((await f.ask()).error, undefined); assert.equal(f.received[0]?.authenticated, true);
    f.settings.clearProviderCredential(f.owner, 'web_search_providers', id, 'api_key');
    assert.equal(f.settings.providerCredentials(f.owner, 'web_search_providers', id).fields.api_key.configured, false);
    assert.equal((await f.ask()).error, undefined); assert.equal(f.received[1]?.authenticated, false);
  } finally { await f.close(); }
});

test('a base_url search provider cannot retain old credentials when a new url changes the effective host', async () => {
  const f = await fixture();
  try {
    const provider = f.settings.createProvider(f.owner, 'web_search_providers', {
      name: 'legacy endpoint', provider: 'searxng', base_url: 'http://localhost:18080/search', api_key: 'fixture-search-key',
    });
    const id = String(provider.id), before = f.db.read('generic_resources', id);
    for (const changes of [{ url: 'http://localhost:18081/search' }, { url: 'http://localhost:18081/search', api_key: '' }]) {
      assert.throws(() => f.settings.updateProvider(f.owner, 'web_search_providers', id, changes),
        (error: any) => error.status === 400 && error.code === 'credential_endpoint_changed');
      assert.deepEqual(f.db.read('generic_resources', id), before);
    }
    assert.deepEqual(f.received, []);
  } finally { await f.close(); }
});

test('clearing the active url cannot silently send retained search credentials to a different base_url host', async () => {
  const f = await fixture();
  try {
    const provider = f.settings.createProvider(f.owner, 'web_search_providers', {
      name: 'dual endpoints', provider: 'searxng', url: 'http://localhost:18080/search',
      base_url: 'http://localhost:18081/search', api_key: 'fixture-search-key',
    });
    const id = String(provider.id), before = f.db.read('generic_resources', id);
    assert.throws(() => f.settings.updateProvider(f.owner, 'web_search_providers', id, { url: '' }),
      (error: any) => error.status === 400 && error.code === 'credential_endpoint_changed');
    assert.deepEqual(f.db.read('generic_resources', id), before);
    assert.deepEqual(f.received, []);
  } finally { await f.close(); }
});

test('search endpoint aliases permit the same host, explicit new credentials and an explicitly cleared anonymous service', async () => {
  const f = await fixture();
  try {
    const provider = f.settings.createProvider(f.owner, 'web_search_providers', {
      name: 'legacy positive', provider: 'searxng', base_url: 'http://localhost:18080/search',
      api_key: 'fixture-search-key', description: 'retained', opaque: { retained: true },
    });
    const id = String(provider.id);
    f.settings.updateProvider(f.owner, 'web_search_providers', id, { url: 'http://localhost:18080/another', api_key: '' });
    assert.equal(f.settings.providerCredentials(f.owner, 'web_search_providers', id).fields.api_key.configured, true);
    f.settings.updateProvider(f.owner, 'web_search_providers', id, { url: 'http://localhost:18081/search', api_key: 'fixture-replacement-key' });
    assert.equal(f.vault.decrypt(f.db.read('generic_resources', id)!.data).api_key, 'fixture-replacement-key');
    assert.equal(JSON.stringify(f.settings.getProvider(f.owner, 'web_search_providers', id)).includes('fixture-replacement-key'), false);
    f.settings.clearProviderCredential(f.owner, 'web_search_providers', id, 'api_key');
    f.settings.updateProvider(f.owner, 'web_search_providers', id, { url: '', base_url: 'http://localhost:18082/search' });
    const saved = f.settings.getProvider(f.owner, 'web_search_providers', id);
    assert.equal(saved.base_url, 'http://localhost:18082/search');
    assert.deepEqual(saved.opaque, { retained: true }); assert.equal(saved.description, 'retained');
    assert.equal(f.settings.providerCredentials(f.owner, 'web_search_providers', id).fields.api_key.configured, false);
    assert.deepEqual(f.received, []);
  } finally { await f.close(); }
});
