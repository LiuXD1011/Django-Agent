import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import test from 'node:test';

// Run explicitly after a fresh build with plain Node (no --import tsx).
test('compiled JS owner starts actual native application and bounded streams without a development loader', {
  skip: process.env.MARLIN_CORE_OWNER_COMPILED_TEST !== '1', timeout: 30000,
}, async () => {
  assert.deepEqual(process.execArgv, []);
  const { CoreOwner } = await import("file:///C:/Users/lxd/AppData/Local/Temp/Marlin%20TS%20Cancel%20Worker%20Build%2020261012/app/payload/core/dist/runtime/owner-client.js");
  const directory = await mkdtemp(join(tmpdir(), 'marlin-owner-compiled 中文 ')); let owner: any;
  const request = (method: string, path: string, body?: object) => ({ protocol: 1, id: randomUUID(), method, path, ...(body ? { body } : {}) });
  const data = (response: any) => response.body.data;
  try {
    owner = await CoreOwner.start({ dataRoot: directory, allowAutoSetup: true });
    const setup = await owner.invoke(request('POST', '/api/v1/auth/auto-setup', { password: 'compiled-owner-test-password' }));
    assert.equal(setup.status, 200); assert.equal(data(setup).auth_mode, 'ipc');
    const storage = await owner.invoke(request('GET', '/api/v1/system/storage-engine-status'));
    assert.equal(storage.status, 200); assert.equal(data(storage).checks.fts5, true); assert.equal(data(storage).checks.vector_extension, true);
    await owner.invoke(request('PUT', '/api/v1/auth/me/preferences', { enable_memory: false }));
    const session = await owner.invoke(request('POST', '/api/v1/sessions', { title: '编译实际核心', knowledge_base_ids: [] })), sessionId = String(data(session).id);
    const bytes = Uint8Array.from([0, 1, 127, 128, 255]);
    const upload = await owner.invoke(request('POST', `/api/v1/sessions/${sessionId}/uploads`), { upload: { name: 'compiled.bin', bytes } });
    const binary = await owner.invoke(request('GET', `/api/v1/sessions/${sessionId}/uploads/${data(upload).upload_id}`));
    assert.deepEqual(binary.binary.bytes, bytes);
    const opened = await owner.openStream(request('POST', `/api/v1/knowledge-chat/${sessionId}`, { query: '未配置模型的明确失败', stream: true, knowledge_base_ids: [] }));
    assert.equal(opened.response.status, 200);
    const frames = []; for await (const frame of opened.frames) frames.push(frame);
    assert.equal(frames[0]?.event, 'message_start'); assert.equal(frames.at(-1)?.event, 'done'); assert.ok(frames.some(frame => frame.data.error));
    const http = await owner.httpTransport(); assert.equal(http.serviceId, owner.serviceId); assert.match(http.csrfKey, /^[A-Za-z0-9_-]{43}$/);
    const id = owner.serviceId; await owner.close();
    owner = await CoreOwner.start({ dataRoot: directory, allowAutoSetup: true });
    assert.equal(owner.serviceId, id); assert.equal((await owner.invoke(request('GET', '/api/v1/auth/me'))).status, 200);
  } finally { await owner?.close(); await rm(directory, { recursive: true, force: true }); }
});

test('compiled owner uses actual Python and compiled nested chunk Worker to publish a small document', {
  skip: process.env.MARLIN_CORE_OWNER_COMPILED_TEST !== '1', timeout: 30000,
}, async () => {
  assert.deepEqual(process.execArgv, []);
  const { CoreOwner } = await import("file:///C:/Users/lxd/AppData/Local/Temp/Marlin%20TS%20Cancel%20Worker%20Build%2020261012/app/payload/core/dist/runtime/owner-client.js");
  const directory = await mkdtemp(join(tmpdir(), 'marlin-owner-compiled-parser 中文 ')); let owner: any;
  const python = spawnSync('python', ['-c', 'import sys;print(sys.executable)'], { encoding: 'utf8' }); assert.equal(python.status, 0);
  const request = (method: string, path: string, body?: object) => ({ protocol: 1, id: randomUUID(), method, path, ...(body ? { body } : {}) });
  const data = (response: any) => response.body.data;
  try {
    owner = await CoreOwner.start({ dataRoot: directory, allowAutoSetup: true,
      parser: { pythonExecutable: python.stdout.trim(), workerPath: "C:\\Users\\lxd\\AppData\\Local\\Temp\\Marlin TS Cancel Worker Build 20261012\\app\\payload\\workers\\document\\worker.py", timeoutMs: 10000 },
    });
    assert.equal((await owner.invoke(request('POST', '/api/v1/auth/auto-setup', { password: 'compiled-parser-test-password' }))).status, 200);
    const kb = await owner.invoke(request('POST', '/api/v1/knowledge-bases', { name: '编译实际解析', indexing_strategy: { keyword_enabled: true, vector_enabled: false, wiki_enabled: false, graph_enabled: false } }));
    assert.equal(kb.status, 200);
    const content = 'compileduniqueterm\n编译 Worker Unicode 😀';
    const upload = await owner.invoke(request('POST', `/api/v1/knowledge-bases/${data(kb).id}/knowledge/file`), { upload: { name: '编译 中文.txt', bytes: Buffer.from(content) } });
    assert.equal(upload.status, 200); const documentId = String(data(upload).knowledge.id);
    let document: any;
    for (let i = 0; i < 200; i++) {
      document = data(await owner.invoke(request('GET', `/api/v1/knowledge/${documentId}`)));
      if (['completed', 'failed', 'cancelled'].includes(document.workflow_status)) break;
      await new Promise<void>(resolveWait => setTimeout(resolveWait, 25));
    }
    assert.equal(document.workflow_status, 'completed');
    const chunks = data(await owner.invoke(request('GET', `/api/v1/chunks/${documentId}`))).items;
    assert.ok(chunks.some((chunk: any) => chunk.content.includes('compileduniqueterm')));
    assert.equal(data(await owner.invoke(request('GET', '/api/v1/models/usage'))).total.calls, 0);
  } finally { await owner?.close(); await rm(directory, { recursive: true, force: true }); }
});
