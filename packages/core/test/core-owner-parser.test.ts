import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import test from 'node:test';
import type { CoreRequest, HttpMethod, JsonObject } from '../src/contracts.js';
import { CoreOwner } from '../src/runtime/owner-client.js';
import { openNativeDatabase } from '../src/storage/database.js';

const request = (method: HttpMethod, path: string, body?: JsonObject): CoreRequest => ({ protocol: 1, id: randomUUID(), method, path, ...(body ? { body } : {}) });
const data = (response: { body: unknown }): any => (response.body as any).data;

test('complete owner supervises actual Python parsing and nested pure chunk Worker, publishing real FTS atomically', { timeout: 30000 }, async () => {
  const directory = await mkdtemp(join(tmpdir(), 'marlin-owner-parser 中文 ')); let owner: CoreOwner | undefined;
  const python = spawnSync('python', ['-c', 'import sys;print(sys.executable)'], { encoding: 'utf8' });
  assert.equal(python.status, 0);
  try {
    owner = await CoreOwner.start({ dataRoot: directory, allowAutoSetup: true,
      parser: { pythonExecutable: python.stdout.trim(), workerPath: resolve('../../workers/document/worker.py'), timeoutMs: 10000 },
      evaluation: { ragas: { pythonExecutable: python.stdout.trim(), workerPath: join(directory, 'evaluation-must-remain-lazy.py') } },
    });
    assert.equal((await owner.invoke(request('POST', '/api/v1/auth/auto-setup', { password: 'owner-parser-test-password' }))).status, 200);
    const kb = await owner.invoke(request('POST', '/api/v1/knowledge-bases', { name: '小隔离真实解析', indexing_strategy: { keyword_enabled: true, vector_enabled: false, graph_enabled: false, wiki_enabled: false } }));
    assert.equal(kb.status, 200); const kbId = String(data(kb).id);
    const content = 'owneruniqueword\n实际 Python 解析，unicode 😀\n';
    const uploaded = await owner.invoke(request('POST', `/api/v1/knowledge-bases/${kbId}/knowledge/file`), { upload: { name: '小文件 中文.txt', bytes: Buffer.from(content) } });
    assert.equal(uploaded.status, 200); const docId = String(data(uploaded).knowledge.id);
    let document: any;
    for (let i = 0; i < 200; i++) {
      document = data(await owner.invoke(request('GET', `/api/v1/knowledge/${docId}`)));
      if (['completed', 'failed', 'cancelled'].includes(document.workflow_status)) break;
      await new Promise<void>(resolveWait => setTimeout(resolveWait, 25));
    }
    assert.equal(document.parse_status, 'completed'); assert.equal(document.workflow_status, 'completed');
    const chunks = await owner.invoke(request('GET', `/api/v1/chunks/${docId}`));
    assert.equal(chunks.status, 200); assert.ok(data(chunks).items.some((chunk: any) => chunk.content.includes('owneruniqueword')));
    const download = await owner.invoke(request('GET', `/api/v1/knowledge/${docId}/download`));
    assert.equal(download.status, 200); assert.deepEqual(download.binary?.bytes, Uint8Array.from(Buffer.from(content)));
    assert.equal(download.binary?.sha256, createHash('sha256').update(content).digest('hex'));
    assert.equal(data(await owner.invoke(request('GET', '/api/v1/models/usage'))).total.calls, 0);
    await owner.close();
    const sqlite = openNativeDatabase(join(directory, 'marlin.sqlite3'), { readonly: true, fileMustExist: true });
    try {
      const result = sqlite.prepare("SELECT count(*) AS n FROM chunks_fts WHERE chunks_fts MATCH 'owneruniqueword'").get() as { n: number };
      assert.ok(result.n > 0);
      assert.equal((sqlite.prepare("SELECT count(*) AS n FROM desktop_jobs WHERE status IN ('running','queued')").get() as { n: number }).n, 0);
      assert.equal((sqlite.prepare('SELECT count(*) AS n FROM model_usage').get() as { n: number }).n, 0);
    } finally { sqlite.close(); }
  } finally { await owner?.close(); await rm(directory, { recursive: true, force: true }); }
});
