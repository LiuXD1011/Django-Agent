import { parentPort, workerData } from 'node:worker_threads';
if (!parentPort) throw new Error('Private fixture worker required');
if (import.meta.url.endsWith('.ts')) { const { register } = await import('tsx/esm/api'); register(); }
const { AuthService } = await import('../../src/auth/index.js');
const { DocumentWorkflow } = await import('../../src/documents/workflow.js');
const { DocumentParser } = await import('../../src/documents/parser.js');
const { JobQueue } = await import('../../src/jobs/queue.js');
const { SearchIndex } = await import('../../src/retrieval/search-index.js');
const { CoreDatabase } = await import('../../src/storage/database.js');
const { CredentialVault } = await import('../../src/storage/credentials.js');
const { ModelConfigurationService } = await import('../../src/settings/model-configuration.js');
const { observeAttemptCommits, observeAttemptCheckpoints, readAttemptControl } = await import('../../src/jobs/attempt-control.js');
const { randomUUID } = await import('node:crypto');
const db = new CoreDatabase(workerData.root), auth = new AuthService(db), index = new SearchIndex(db);
const ctx = auth.register({ username: 'native-barrier', password: 'NativeBarrierFixture✓Password' }).context;
const kb = db.insert('knowledge_bases', { tenant_id: ctx.tenantId, name: '精确取消😀', indexing_strategy: { keyword_enabled: true, vector_enabled: false, graph_enabled: false, wiki_enabled: false } });
let armed = false, hit = false, identity: any, shared: SharedArrayBuffer | undefined, disposers: Array<() => void> = [];
const barrier = new Int32Array(workerData.barrier), acknowledgements = new Map<string, () => void>();
const block = (phase: string, insertedChunkId?: string) => {
  if (hit) return; hit = true;
  const evidence = { phase, inTransaction: db.sqlite.inTransaction, insertedChunkId: insertedChunkId ?? null, newChunks: phase === 'chunks' ? null : db.get('SELECT count(*) AS n FROM chunks WHERE knowledge_id=?', identity.knowledgeId)?.n, ftsRows: phase === 'chunks' ? null : db.get('SELECT count(*) AS n FROM chunks_fts')?.n, control: readAttemptControl(shared!) };
  parentPort!.postMessage({ type: 'barrier', evidence });
  Atomics.store(barrier, 0, 1); Atomics.notify(barrier, 0);
  if (Atomics.wait(barrier, 1, 0, 15000) === 'timed-out') throw new Error('Controlled native publication barrier expired');
};
const jobs = new JobQueue(db, { attemptControl: {
  register: async (claim, control) => {
    if (!armed) return;
    identity = claim; shared = control;
    if (workerData.phase === 'final' || workerData.phase === 'local') disposers.push(observeAttemptCommits(control, event => {
      if (workerData.phase === 'final' && event.final || workerData.phase === 'local' && !event.final && String((db.read('knowledges', claim.knowledgeId)?.metadata as any)?.source_generation) !== generation) block(workerData.phase);
    }));
    if (workerData.phase === 'fts') disposers.push(observeAttemptCheckpoints(control, () => {
      const row = db.read('knowledges', claim.knowledgeId);
      if (String((row?.metadata as any)?.source_generation) !== generation && Number(db.get('SELECT count(*) AS n FROM chunks_fts')?.n) > 0) block('fts');
    }));
    parentPort!.postMessage({ type: 'registered', identity: claim, shared: control });
    await new Promise<void>(resolve => acknowledgements.set(claim.ownerToken, resolve));
  },
  unregister: (claim, control) => { disposers.splice(0).forEach(dispose => dispose()); if (armed) parentPort!.postMessage({ type: 'unregistered', identity: claim, control: readAttemptControl(control) }); },
} });
const workflow = new DocumentWorkflow(db, auth, jobs, new ModelConfigurationService(db, auth, new CredentialVault(workerData.root)), undefined, { parser: new DocumentParser({ pythonExecutable: workerData.python, workerPath: workerData.parserPath }), index, scheduler: () => undefined });
const uploaded = await workflow.upload(ctx, String(kb.id), { name: 'small-native-😀.txt', bytes: Buffer.from(Array.from({ length: 96 }, (_, i) => `Section ${i}: actual-source-fact-${i}😀 has documented transaction context.\n`).join('')), process_config: { chunking_config: { strategy: 'recursive', chunk_size: 128, chunk_overlap: 8, parent_chunk_size: 512, child_chunk_size: 128, child_chunk_overlap: 8 } } }, randomUUID());
const initial = await jobs.run(uploaded.task_id); if (initial.status !== 'completed') throw new Error(`Initial real parser publication failed: ${initial.status}`);
const docId = String(uploaded.knowledge.id), generation = String((db.read('knowledges', docId)?.metadata as any)?.source_generation);
function snapshot() {
  return { doc: db.read('knowledges', docId), chunks: db.all('SELECT * FROM chunks WHERE knowledge_id=? ORDER BY id', docId), fts: db.all('SELECT rowid,content FROM chunks_fts ORDER BY rowid'), registry: db.all('SELECT * FROM retrieval_chunk_ids ORDER BY rowid'), tasks: db.all('SELECT id,status,progress FROM task_records ORDER BY id'), runningSpans: db.get("SELECT count(*) AS n FROM knowledge_processing_spans WHERE knowledge_id=? AND status='running'", docId)?.n, runningSteps: db.get("SELECT count(*) AS n FROM desktop_job_steps WHERE status='running'")?.n, foreignKeys: db.sqlite.pragma('foreign_key_check'), modelCalls: db.get('SELECT count(*) AS n FROM model_usage')?.n };
}
const before = snapshot();
if (workerData.phase === 'chunks') {
  db.sqlite.function('fixture_publication_barrier', (insertedId: string) => { if (armed) { try { block('chunks', insertedId); } catch (error) { parentPort!.postMessage({ type: 'error', error: String(error) }); throw error; } } return 0; });
  db.sqlite.exec(`CREATE TRIGGER fixture_chunk_barrier AFTER INSERT ON chunks WHEN NEW.knowledge_id='${docId}' BEGIN SELECT fixture_publication_barrier(NEW.id); END`);
}
if (workerData.commitFault) {
  db.sqlite.exec(`CREATE TABLE fixture_deferred_completion(value TEXT REFERENCES knowledge_bases(id) DEFERRABLE INITIALLY DEFERRED);
    CREATE TRIGGER fixture_completion_fk AFTER UPDATE OF status ON desktop_jobs WHEN NEW.status='completed' BEGIN INSERT INTO fixture_deferred_completion VALUES('missing-fixture-kb'); END`);
}
const reparsed = await workflow.reparse(ctx, docId, undefined, randomUUID()); armed = true;
parentPort.postMessage({ type: 'ready', before, docId, taskId: reparsed.task_id });
let running: Promise<any> | undefined;
parentPort.on('message', async message => {
  try {
    if (message.type === 'ack') { acknowledgements.get(message.ownerToken)?.(); acknowledgements.delete(message.ownerToken); }
    if (message.type === 'run') { running = jobs.run(reparsed.task_id); const result = await running; parentPort!.postMessage({ type: 'result', result, after: snapshot() }); }
    if (message.type === 'cancel') { const result = await workflow.cancelAttempt(message.identity); parentPort!.postMessage({ type: 'cancel-result', result }); }
    if (message.type === 'close') { Atomics.store(barrier, 1, 1); Atomics.notify(barrier, 1); acknowledgements.forEach(resolve => resolve()); await workflow.close(); await jobs.close(); await running?.catch(() => undefined); disposers.splice(0).forEach(dispose => dispose()); db.close(); parentPort!.close(); }
  } catch (error) { parentPort!.postMessage({ type: 'error', error: String(error) }); }
});
