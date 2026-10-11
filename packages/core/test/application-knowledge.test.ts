import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { test } from 'node:test';
import { CoreApplication, type PrivateBinding } from '../src/application.js';
import type { HttpMethod, JsonObject } from '../src/contracts.js';

async function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'marlin-business-routes-'));
  const app = new CoreApplication(root, { allowAutoSetup: true });
  const initial = await app.dispatch({ protocol: 1, id: randomUUID(), method: 'POST', path: '/api/v1/auth/auto-setup', body: { email: 'route-qa@example.invalid', password: 'route-qa-chosen-password' } }, { transport: 'ipc' });
  assert.equal(initial.response.status, 200);
  const issue = initial.authChange!.issue!;
  const binding: PrivateBinding = { transport: 'ipc', access: issue.credentials.access };
  const request = async (method: HttpMethod, path: string, body?: JsonObject, other = binding) => {
    const { response } = await app.dispatch({ protocol: 1, id: randomUUID(), method, path, ...(body ? { body } : {}) }, other);
    return { ...response, value: (response.body as JsonObject).data as JsonObject };
  };
  return { app, request, issue, async close() { await app.close(); rmSync(root, { recursive: true, force: true }); } };
}

test('registered knowledge routes preserve create, query, edit, pin, configuration-copy and deletion behavior', async () => {
  const f = await fixture();
  try {
    const created = await f.request('POST', '/api/v1/knowledge-bases', { name: '验收 海盐', description: '受控资料' });
    assert.equal(created.status, 200);
    const id = String(created.value.id), base = '/api/v1/knowledge-bases/' + id;
    assert.equal(created.value.document_count, 0);
    assert.equal((await f.request('GET', '/api/v1/knowledge-bases?keyword=' + encodeURIComponent('海盐'))).value.total, 1);
    assert.equal((await f.request('PUT', base, { name: '验收 海盐 修订' })).value.name, '验收 海盐 修订');
    assert.equal((await f.request('PUT', base + '/pin', { is_pinned: true })).value.is_pinned, true);
    const copied = await f.request('POST', '/api/v1/knowledge-bases/copy', { source_id: id });
    const copy = copied.value.knowledge_base as JsonObject;
    assert.equal(copy.name, '验收 海盐 修订 copy');
    assert.notEqual(copy.id, id);
    assert.equal(((await f.request('GET', base + '/move-targets')).value.items as JsonObject[]).length, 1);
    assert.equal((await f.request('GET', base + '/knowledge/stats')).value.total, 0);
    assert.equal((await f.request('DELETE', base)).status, 200);
    assert.equal((await f.request('GET', base)).status, 404);
    assert.equal((await f.request('GET', '/api/v1/knowledge-bases')).value.total, 1);
  } finally { await f.close(); }
});

test('document, tag and chunk routes use authoritative scope and remove edited or deleted text from real FTS', async () => {
  const f = await fixture();
  try {
    const id = String((await f.request('POST', '/api/v1/knowledge-bases', { name: '索引验收' })).value.id);
    const tag = await f.request('POST', `/api/v1/knowledge-bases/${id}/tags`, { name: '正式资料', color: '#00aa88' });
    assert.equal(tag.status, 200);
    const doc = f.app.database.insert('knowledges', { tenant_id: f.issue.context.tenantId, knowledge_base_id: id, title: '验收文件', file_name: '验收 文档.txt', parse_status: 'completed', tag_id: String(tag.value.id) });
    const chunk = f.app.database.insert('chunks', { tenant_id: f.issue.context.tenantId, knowledge_base_id: id, knowledge_id: doc.id, content: 'olduniqueitem', chunk_type: 'text' });
    f.app.searchIndex.indexKeyword({ tenantId: f.issue.context.tenantId, knowledgeBaseIds: [id] }, String(chunk.id));
    assert.equal((await f.request('GET', `/api/v1/knowledge-bases/${id}/knowledge?tag_id=${tag.value.id}`)).value.total, 1);
    assert.equal((await f.request('GET', `/api/v1/chunks/${doc.id}`)).value.total, 1);
    assert.equal((await f.request('GET', `/api/v1/chunks/by-id/${chunk.id}`)).value.id, chunk.id);
    const edited = await f.request('PUT', `/api/v1/chunks/${doc.id}/${chunk.id}`, { content: 'newuniqueitem' });
    assert.equal(edited.status, 200);
    assert.equal(f.app.database.get("SELECT count(*) AS n FROM chunks_fts WHERE chunks_fts MATCH 'olduniqueitem'")?.n, 0);
    assert.equal(f.app.database.get("SELECT count(*) AS n FROM chunks_fts WHERE chunks_fts MATCH 'newuniqueitem'")?.n, 1);
    const other = f.app.auth.register({ email: 'foreign-route@example.invalid', password: 'foreign-test-password' });
    const foreign: PrivateBinding = { transport: 'ipc', access: other.credentials.access };
    assert.equal((await f.request('GET', `/api/v1/knowledge/${doc.id}`, undefined, foreign)).status, 404);
    assert.equal((await f.request('GET', `/api/v1/chunks/by-id/${chunk.id}`, undefined, foreign)).status, 404);
    assert.equal((await f.request('DELETE', `/api/v1/knowledge/${doc.id}`, undefined, foreign)).status, 404);
    assert.equal((await f.request('POST', '/api/v1/knowledge/batch-delete', { ids: [String(doc.id)], kb_id: id })).status, 200);
    assert.equal(f.app.database.get("SELECT count(*) AS n FROM chunks_fts WHERE chunks_fts MATCH 'newuniqueitem'")?.n, 0);
    assert.equal((await f.request('GET', `/api/v1/knowledge/${doc.id}`)).status, 404);
  } finally { await f.close(); }
});
