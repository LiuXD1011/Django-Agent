import { parentPort, workerData } from 'node:worker_threads';

if (!parentPort) throw new Error('Fixture requires private parent port');
if (import.meta.url.endsWith('.ts')) { const { register } = await import('tsx/esm/api'); register(); }
const { ReadDatabase } = await import('../../src/storage/read-database.js');
const { QueryDispatcher } = await import('../../src/runtime/query-dispatcher.js');
const { errorResponse } = await import('../../src/application.js');
const { AppError } = await import('../../src/errors.js');
const { bootstrap, authority, barrier } = workerData;
const database = new ReadDatabase(bootstrap.databasePath, bootstrap.dataRoot, { timeoutMs: 500 });
const dispatcher = new QueryDispatcher(database, bootstrap.parserEnabled);
const state = new Int32Array(barrier), epoch = new BigUint64Array(authority), port = parentPort;
port.on('message', message => {
  if (message.type === 'close') { database.close(); port.close(); return; }
  if (message.type !== 'query') return;
  let result;
  try {
    const check = () => {
      if (message.generation !== bootstrap.generation || message.epoch !== Atomics.load(epoch, 0).toString()) throw new AppError(409, 'auth_superseded', 'Fixture authority changed');
      if (Date.now() >= message.deadline) throw new AppError(408, 'query_timeout', 'Fixture query expired');
    };
    check();
    result = message.operation === 'cancel-preflight'
      ? dispatcher.cancelPreflight(message.request, message.binding)
      : { response: dispatcher.dispatch(message.request, message.binding) };
    if (message.operation === 'cancel-preflight' && Atomics.compareExchange(state, 0, 0, 1) === 0) {
      // The actual native readonly auth/document snapshot has ended. Keep its
      // exact result private until the owner has claimed a newer document job.
      Atomics.store(state, 5, result.response.status === 200 && !('target' in result && result.target) ? 0 : 1);
      Atomics.notify(state, 0);
      if (Atomics.wait(state, 1, 0, 20000) === 'timed-out') throw new Error('Old no-job snapshot fixture barrier expired');
    }
    check();
  } catch (error) { result = { response: errorResponse(message.request.id, error) }; }
  port.postMessage({ protocol: 1, type: 'result', id: message.id, generation: bootstrap.generation, epoch: message.epoch, ...result });
});
port.once('close', () => database.close());
port.postMessage({ protocol: 1, type: 'ready', generation: bootstrap.generation });
