import { randomUUID } from 'node:crypto';
import { parentPort, workerData } from 'node:worker_threads';

if (!parentPort) throw new Error('Fixture requires private parent port');
if (import.meta.url.endsWith('.ts')) { const { register } = await import('tsx/esm/api'); register(); }
const { CoreApplication } = await import('../../src/application.js');
const { CoreIpcAdapter } = await import('../../src/adapters/ipc.js');
const { DocumentParser } = await import('../../src/documents/parser.js');
const { runCoreOwner } = await import('../../src/runtime/owner-host.js');
const { createOwnerAttemptBridge } = await import('../../src/runtime/owner-attempt-bridge.js');
const { digest, writeOwned } = await import('../../src/documents/workflow/files.js');
const { AppError } = await import('../../src/errors.js');
const { config, authority, generation, barrier } = workerData;
const state = new Int32Array(barrier), port = parentPort;
const bridge = createOwnerAttemptBridge(port, generation);
const app = new CoreApplication(config.dataRoot, { allowAutoSetup: true, parser: new DocumentParser(config.parser), attemptControl: {
  async register(identity, shared) {
    await bridge.register(identity, shared);
    // Pause only after the real claim is durable and registry ACK has arrived.
    // The owner message pump remains live; the future handler has not started.
    port.postMessage({ protocol: 1, type: 'fixture-attempt', identity, shared });
    Atomics.store(state, 2, 1); Atomics.notify(state, 2);
    if (await Atomics.waitAsync(state, 3, 0, 20000).value === 'timed-out') throw new Error('Future claim fixture barrier expired');
  },
  unregister: bridge.unregister,
} });
app.route('POST', '/api/v1/fixture/no-job-file', c => {
  app.auth.assertCan(c.auth, 'document.write');
  const baseId = c.body.knowledge_base_id;
  if (typeof baseId !== 'string') throw new AppError(400, 'invalid_fixture_base', 'Fixture requires a knowledge base');
  app.knowledge.knowledgeBases.get(c.auth, baseId);
  const id = randomUUID(), bytes = Buffer.from('futureonlysurvival\n新的完整中文资料😀。\n'.repeat(12));
  const reference = `media/documents/${id}/source/${randomUUID()}.txt`;
  writeOwned(app.database.dataRoot, reference, bytes);
  const doc = app.database.insert('knowledges', {
    id, tenant_id: c.auth.tenantId, knowledge_base_id: baseId, type: 'file', title: '无旧任务的历史文件',
    file_name: '无旧任务.txt', file_type: 'txt', file_path: reference, file_hash: digest(bytes),
    file_size: bytes.byteLength, storage_size: bytes.byteLength, parse_status: 'completed', processed_at: new Date().toISOString(),
    metadata: { storage_owned: true, content: '保留的历史正文', workflow_status: 'completed' },
  });
  return { id: doc.id!, status: doc.parse_status!, has_job: false };
});
runCoreOwner(port, app, new CoreIpcAdapter(app), new BigUint64Array(authority), generation);
// This trusted test observer runs after the real owner handler selected an
// attempt. It signals a turn boundary, without replacing dispatch or SQL.
port.on('message', message => {
  if (message?.type === 'call' && message.call?.operation === 'invoke' && message.call.input?.path?.endsWith('/cancel-parse')) {
    Atomics.store(state, 4, 1); Atomics.notify(state, 4);
  }
});
