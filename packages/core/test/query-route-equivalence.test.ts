import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import test from 'node:test';
import { CoreApplication } from '../src/application.js';
import { DocumentParser } from '../src/documents/parser.js';
import { QueryClient } from '../src/runtime/query-client.js';

test('all sixteen real readonly routes match owner DTOs for HTTP and IPC without truncating bodies or high integer IDs', async () => {
  const root = await mkdtemp(join(tmpdir(), 'marlin-query-dto 真实 '));
  const app = new CoreApplication(root, { parser: new DocumentParser({ pythonExecutable: '/tmp/marlin-parser-isolation-20261010/bin/python', workerPath: resolve('../../workers/document/worker.py') }) });
  const issue = app.auth.register({ username: 'dto-owner', password: 'dto-owner-password' });
  const kb = app.knowledge.knowledgeBases.create(issue.context, { name: '完整资料' });
  app.knowledge.knowledgeBases.create(issue.context, { name: '移动目标' });
  const content = '完整正文😀中文：预算12345元。\n'.repeat(10000);
  const doc = app.database.insert('knowledges', { tenant_id: issue.context.tenantId, knowledge_base_id: kb.id, type: 'file', title: '正文 中文', parse_status: 'completed', metadata: { content } });
  const chunk = app.database.insert('chunks', { tenant_id: issue.context.tenantId, knowledge_base_id: kb.id, knowledge_id: doc.id, content: '父块😀', chunk_type: 'parent', seq_id: '9223372036854775806' });
  app.database.insert('chunks', { tenant_id: issue.context.tenantId, knowledge_base_id: kb.id, knowledge_id: doc.id, content: '子块😀12345元', chunk_type: 'text', context_parent_id: chunk.id, is_enabled: true });
  const tag = app.knowledge.createTag(issue.context, String(kb.id), { name: '中文标签' });
  app.database.update('knowledges', String(doc.id), { tag_id: tag.id });
  const paths = [
    '/api/v1/auth/me', '/api/v1/auth/devices', '/api/v1/knowledge-bases', `/api/v1/knowledge-bases/${kb.id}`,
    `/api/v1/knowledge-bases/${kb.id}/move-targets`, `/api/v1/knowledge-bases/${kb.id}/knowledge?file_type=&page_size=20`,
    `/api/v1/knowledge-bases/${kb.id}/knowledge/stats`, `/api/v1/knowledge/batch?ids=${doc.id}`, '/api/v1/knowledge/search?keyword=%E6%AD%A3%E6%96%87',
    `/api/v1/knowledge/${doc.id}`, `/api/v1/chunks/by-id/${chunk.id}`, `/api/v1/chunks/${doc.id}`, `/api/v1/chunks/${doc.id}/${chunk.id}`,
    `/api/v1/knowledge-bases/${kb.id}/tags`, `/api/v1/knowledge-bases/${kb.id}/tags/${tag.id}`, `/api/v1/knowledge/${doc.id}/stages`,
  ];
  let client: QueryClient | undefined;
  try {
    client = await QueryClient.start({ databasePath: app.database.path, dataRoot: root, generation: randomUUID(), parserEnabled: true }, new SharedArrayBuffer(8), () => true);
    for (const transport of ['http', 'ipc'] as const) for (const path of paths) {
      const request = { protocol: 1 as const, id: randomUUID(), method: 'GET' as const, path }, binding = { transport, access: issue.credentials.access };
      const expected = (await app.dispatch(request, binding)).response, actual = await client.dispatch(request, binding, '0');
      assert.equal(actual.status, 200, `${transport} ${path}`); assert.deepEqual(actual, expected, `${transport} ${path}`);
      if (path === `/api/v1/knowledge/${doc.id}`) assert.equal((actual.body as any).data.metadata.content, content);
      if (path === `/api/v1/chunks/by-id/${chunk.id}`) assert.equal((actual.body as any).data.seq_id, '9223372036854775806');
    }
  } finally { await client?.close(); await app.close(); await rm(root, { recursive: true, force: true }); }
});
