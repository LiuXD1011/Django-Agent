import { parentPort, workerData } from 'node:worker_threads';
import type { MessagePort } from 'node:worker_threads';

if (!parentPort) throw new Error('Fixture requires private parent port');
if (import.meta.url.endsWith('.ts')) { const { register } = await import('tsx/esm/api'); register(); }
const { CoreApplication } = await import('../../src/application.js');
const { CoreIpcAdapter } = await import('../../src/adapters/ipc.js');
const { runCoreOwner } = await import('../../src/runtime/owner-host.js');
const { AppError } = await import('../../src/errors.js');
const { config, authority, generation, barrier, replyBarrier } = workerData;
const state = new Int32Array(barrier);
const app = new CoreApplication(config.dataRoot, { allowAutoSetup: true });
let armed = false;
let armedStream = false;
app.route('POST', '/api/v1/fixture/arm-auth-reply', c => { app.auth.assertCan(c.auth, 'read'); armed = true; return {}; });
app.route('POST', '/api/v1/fixture/arm-stream-reply', c => { app.auth.assertCan(c.auth, 'read'); armedStream = true; return {}; });
app.route('POST', '/api/v1/fixture/fail-auth-discard', c => {
  app.auth.assertCan(c.auth, 'read');
  app.database.sqlite.exec("CREATE TRIGGER fixture_discard_failure BEFORE UPDATE ON device_sessions WHEN NEW.revoke_reason='auth_superseded' BEGIN SELECT RAISE(ABORT,'controlled cleanup failure'); END");
  return {};
});
app.route('POST', '/api/v1/fixture/seed', c => {
  app.auth.assertCan(c.auth, 'document.write');
  const kb = app.knowledge.knowledgeBases.create(c.auth, { name: '事务一致性 真实资料' });
  const doc = app.database.insert('knowledges', { tenant_id: c.auth.tenantId, knowledge_base_id: kb.id, type: 'file', title: '旧完整版本', parse_status: 'completed', metadata: { content: '旧正文😀12345元' } });
  const chunk = app.database.insert('chunks', { tenant_id: c.auth.tenantId, knowledge_base_id: kb.id, knowledge_id: doc.id, content: '旧分块😀12345元', chunk_type: 'text', is_enabled: true });
  app.searchIndex.indexKeywords({ tenantId: c.auth.tenantId, knowledgeBaseIds: [String(kb.id)] }, [String(chunk.id)]);
  return { kbId: kb.id!, docId: doc.id!, chunkId: chunk.id! };
});
app.route('POST', '/api/v1/fixture/publication', c => {
  app.auth.assertCan(c.auth, 'document.write');
  const docId = String(c.body.docId), chunkId = String(c.body.chunkId);
  app.knowledge.get(c.auth, docId);
  return app.database.transaction(() => {
    app.database.update('knowledges', docId, { title: '新完整版本', metadata: { content: '新正文😀67890元' } });
    app.database.update('chunks', chunkId, { content: '新分块😀67890元' });
    app.searchIndex.indexKeywords({ tenantId: c.auth.tenantId }, [chunkId]);
    // Hold a real write transaction after DTO, chunk and FTS updates, before COMMIT.
    Atomics.store(state, 0, 1); Atomics.notify(state, 0);
    if (Atomics.wait(state, 1, 0, 10000) === 'timed-out') throw new AppError(408, 'fixture_deadline', 'Fixture barrier expired');
    if (Atomics.load(state, 2)) throw new AppError(409, 'fixture_rollback', 'Controlled publication rollback');
    return { committed: true };
  });
});
const port = new Proxy(parentPort, { get(target, key) {
  if (key === 'postMessage') return (message: any) => {
    if (replyBarrier && message.type === 'response' && (armed && (message.value?.authChange?.issue || message.value?.protocol === 1 && message.value?.body?.data?.auth_mode === 'ipc') || armedStream && message.streaming)) {
      armed = false; armedStream = false;
      const reply = new Int32Array(replyBarrier);
      Atomics.store(reply, 0, 1); Atomics.notify(reply, 0); Atomics.wait(reply, 1, 0, 10000);
    }
    target.postMessage(message);
  };
  const value = Reflect.get(target, key, target); return typeof value === 'function' ? value.bind(target) : value;
} }) as MessagePort;
runCoreOwner(port, app, new CoreIpcAdapter(app), new BigUint64Array(authority), generation);
