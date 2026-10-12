import { parentPort, workerData } from 'node:worker_threads';

if (!parentPort) throw new Error('Fixture requires parent port');
if (import.meta.url.endsWith('.ts')) { const { register } = await import('tsx/esm/api'); register(); }
const { ReadDatabase } = await import('../../src/storage/read-database.js');
const { QueryDispatcher } = await import('../../src/runtime/query-dispatcher.js');
const { bootstrap, authority, barrier } = workerData;
const db = new ReadDatabase(bootstrap.databasePath, bootstrap.dataRoot, { timeoutMs: 500 }), dispatcher = new QueryDispatcher(db, bootstrap.parserEnabled);
const state = new Int32Array(barrier);
parentPort.on('message', message => {
  if (message.type === 'close') { db.close(); parentPort!.close(); return; }
  if (message.type !== 'query') return;
  const result = message.operation === 'cancel-preflight' ? dispatcher.cancelPreflight(message.request, message.binding) : { response: dispatcher.dispatch(message.request, message.binding) };
  Atomics.store(state, 0, 1); Atomics.notify(state, 0);
  Atomics.wait(state, 1, 0, 30000);
  parentPort!.postMessage({ protocol: 1, type: 'result', id: message.id, generation: bootstrap.generation, epoch: message.epoch, ...result });
});
parentPort.postMessage({ protocol: 1, type: 'ready', generation: bootstrap.generation });
