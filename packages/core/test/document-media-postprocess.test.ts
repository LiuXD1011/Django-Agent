import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import test from 'node:test';
import { AuthService } from '../src/auth/index.js';
import { DocumentParser } from '../src/documents/parser.js';
import { DocumentWorkflow } from '../src/documents/workflow.js';
import { JobQueue } from '../src/jobs/queue.js';
import { SearchIndex } from '../src/retrieval/search-index.js';
import { ModelConfigurationService } from '../src/settings/model-configuration.js';
import { CoreDatabase } from '../src/storage/database.js';
import { CredentialVault } from '../src/storage/credentials.js';

for (const visionConfigured of [true, false]) {
  test(`image-only auxiliary tasks use recognized source or skip unavailable source (vision=${visionConfigured})`, async () => {
    const root = mkdtempSync(join(tmpdir(), 'marlin-image-source-'));
    const db = new CoreDatabase(root), auth = new AuthService(db), jobs = new JobQueue(db), index = new SearchIndex(db);
    const ctx = auth.register({ username: 'media-owner', password: 'MediaFixturePassword✓' }).context;
    const models = new ModelConfigurationService(db, auth, new CredentialVault(root));
    const kb = db.insert('knowledge_bases', { tenant_id: ctx.tenantId, name: 'media', indexing_strategy: { vector_enabled: false, wiki_enabled: true, graph_enabled: false } });
    const requests: any[] = [], hookSources: string[] = [];
    const server = createServer(async (req, res) => {
      assert.equal(db.sqlite.inTransaction, false);
      let raw = ''; for await (const bytes of req) raw += bytes;
      const body = JSON.parse(raw); requests.push(body);
      const prompt = body.messages.at(-1).content;
      const content = Array.isArray(prompt)
        ? JSON.stringify(prompt).includes('OCR') ? '验证码 ORCA-QA-7421；设备数量32；交付2026-10-20。' : '白底黑字的设备交付验收卡。'
        : prompt.includes('5个用户问题') ? '["验证码是什么？"]'
        : prompt.includes('关键词') ? '{"keywords":["设备交付"]}'
        : prompt.includes('ORCA-QA-7421') ? '验证码ORCA-QA-7421，32台设备于2026-10-20交付。' : '没有知识正文，请提供内容。';
      res.setHeader('content-type', 'application/json');
      res.end(JSON.stringify({ choices: [{ message: { content }, finish_reason: 'stop' }], usage: { prompt_tokens: 8, completion_tokens: 9, total_tokens: 17 } }));
    });
    await new Promise<void>(r => server.listen(0, '127.0.0.1', r));
    const address = server.address(); assert.ok(address && typeof address !== 'string');
    models.create(ctx, { name: 'aux', type: 'chat', source: 'local', is_default: true, parameters: { base_url: `http://127.0.0.1:${address.port}/v1`, model: 'aux' } });
    if (visionConfigured) models.create(ctx, { name: 'vision', type: 'vision', source: 'local', is_default: true, parameters: { base_url: `http://127.0.0.1:${address.port}/v1`, model: 'vision' } });
    const workflow = new DocumentWorkflow(db, auth, jobs, models, undefined, {
      parser: new DocumentParser({ pythonExecutable: process.env.MARLIN_TEST_PYTHON ?? '/tmp/marlin-parser-isolation-20261010/bin/python', workerPath: resolve('../../workers/document/worker.py') }),
      index, scheduler: () => {}, hooks: { wiki: async context => { hookSources.push(context.content); return { status: 'completed' }; } },
    });
    try {
      const uploaded = await workflow.upload(ctx, String(kb.id), { name: 'source.png', bytes: readFileSync(resolve('../../workers/document/tests/fixtures/image.png')) }, randomUUID());
      assert.equal((await jobs.run(String(uploaded.task_id))).status, 'completed');
      const doc = db.read('knowledges', String(uploaded.knowledge.id))!;
      assert.equal((doc.metadata as any).content, '', 'canonical parser text and offsets must remain intact');
      if (visionConfigured) {
        assert.equal(doc.summary_status, 'completed');
        assert.match(String(doc.description), /ORCA-QA-7421.*32.*2026-10-20/);
        const auxiliary = requests.filter(body => typeof body.messages.at(-1).content === 'string');
        assert.equal(auxiliary.length, 3);
        for (const body of auxiliary) {
          assert.match(body.messages.at(-1).content, /ORCA-QA-7421/);
          assert.match(body.messages.at(-1).content, /白底黑字/);
        }
        assert.match(hookSources[0]!, /ORCA-QA-7421/);
        assert.equal(db.get('SELECT count(*) AS n FROM model_usage')!.n, 5);
        db.update('knowledges', String(doc.id), { description: '没有知识正文，请提供内容。', metadata: { ...(doc.metadata as any), summary: '没有知识正文，请提供内容。' } });
        const retry = await workflow.reparse(ctx, String(doc.id), {}, randomUUID());
        assert.equal((await jobs.run(String(retry.task_id))).status, 'completed');
        assert.match(String(db.read('knowledges', String(doc.id))!.description), /ORCA-QA-7421/, 'reparse refreshes a previous generated description');
        db.update('knowledges', String(doc.id), { description: '用户撰写说明' });
        const custom = await workflow.reparse(ctx, String(doc.id), {}, randomUUID());
        assert.equal((await jobs.run(String(custom.task_id))).status, 'completed');
        assert.equal(db.read('knowledges', String(doc.id))!.description, '用户撰写说明', 'preserve a manually supplied description');
      } else {
        assert.equal(requests.length, 0, 'do not pay for auxiliary tasks with no recognized source');
        assert.equal(doc.summary_status, 'needs_configuration');
        assert.equal(doc.description, '');
        assert.equal(db.get('SELECT count(*) AS n FROM model_usage')!.n, 0);
      }
    } finally {
      await Promise.all([workflow.close(), jobs.close()]);
      server.closeAllConnections(); await new Promise<void>(r => server.close(() => r()));
      db.close(); rmSync(root, { recursive: true, force: true });
    }
  });
}
