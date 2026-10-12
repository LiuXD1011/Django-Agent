import { parentPort, workerData } from 'node:worker_threads';
import type { ReadDatabase as ReadConnection } from '../storage/read-database.js';
import type { QueryInput, QueryOutput, QueryWorkerData } from './query-contracts.js';

const port = parentPort;
if (!port) throw new Error('Query worker requires private parent port');
if (import.meta.url.endsWith('.ts')) { const { register } = await import('tsx/esm/api'); register(); }
const { ReadDatabase } = await import('../storage/read-database.js');
const { QueryDispatcher } = await import('./query-dispatcher.js');
const { errorResponse } = await import('../application.js');
const { AppError } = await import('../errors.js');
let database: ReadConnection | undefined;
const send = (message: QueryOutput) => port.postMessage(message);
try {
  const { bootstrap, authority } = workerData as QueryWorkerData;
  if (!(authority instanceof SharedArrayBuffer) || authority.byteLength !== 8 || !bootstrap?.generation) throw new Error('Invalid query bootstrap');
  const epoch = new BigUint64Array(authority);
  database = new ReadDatabase(bootstrap.databasePath, bootstrap.dataRoot, { timeoutMs: 500 });
  const dispatcher = new QueryDispatcher(database, bootstrap.parserEnabled);
  port.on('message', (message: QueryInput) => {
    if (!message || message.protocol !== 1) return;
    if (message.type === 'close') { database?.close(); send({ protocol: 1, type: 'closed' }); port.close(); return; }
    if (message.type !== 'query') return;
    let response, target;
    try {
      const check = () => {
        if (message.generation !== bootstrap.generation || message.epoch !== Atomics.load(epoch, 0).toString()) throw new AppError(409, 'auth_superseded', '登录状态已改变，请重新操作。');
        if (Date.now() >= message.deadline) throw new AppError(408, 'query_timeout', '页面读取超时，请重试。');
      };
      check();
      if (message.operation === 'cancel-preflight') ({ response, target } = dispatcher.cancelPreflight(message.request, message.binding));
      else response = dispatcher.dispatch(message.request, message.binding);
      check();
    } catch (error) { response = errorResponse(message.request?.id ?? '', error); }
    send({ protocol: 1, type: 'result', id: message.id, generation: bootstrap.generation, epoch: message.epoch, response, ...(target ? { target } : {}) });
  });
  port.once('close', () => database?.close());
  send({ protocol: 1, type: 'ready', generation: bootstrap.generation });
} catch (error) {
  database?.close();
  const response = errorResponse('', error), body = response.body as { error: { code: string; message: string } };
  send({ protocol: 1, type: 'startup-error', error: { status: response.status, ...body.error } }); port.close();
}
