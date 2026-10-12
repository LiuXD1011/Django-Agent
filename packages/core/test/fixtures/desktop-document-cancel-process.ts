import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { Worker } from 'node:worker_threads';
import { CoreOwner } from '../../src/runtime/owner-client.js';

// This isolated test child substitutes only the startup factory with a real
// Worker attachment. The actual desktop-process handler, CoreOwner, Query
// worker, authentication, SQLite, parser and cancellation all run unchanged.
CoreOwner.start = async config => {
  const parser = JSON.parse(readFileSync(join(config.dataRoot, 'fixture-parser.json'), 'utf8'));
  const authority = new SharedArrayBuffer(8), generation = randomUUID();
  const barrierRoot = join(config.dataRoot, 'fixture-cancel-barrier');
  mkdirSync(barrierRoot, { recursive: true });
  const worker = new Worker(new URL('./core-owner-document-cancel-worker.ts', import.meta.url), {
    workerData: { config: { ...config, parser }, authority, generation, barrier: new SharedArrayBuffer(12), barrierRoot },
    execArgv: [], stdout: true, stderr: true,
  });
  // Observe the actual private transport without changing its messages.
  const post = worker.postMessage.bind(worker);
  let controls = 0, aborts = 0;
  worker.postMessage = (...args) => {
    post(...args);
    if (args[0]?.type === 'cancel-attempt') writeFileSync(join(barrierRoot, 'controls-sent'), String(++controls));
  };
  process.on('message', message => {
    if (message && typeof message === 'object' && 'type' in message && message.type === 'cancel') {
      const count = ++aborts;
      setImmediate(() => writeFileSync(join(barrierRoot, 'aborts-consumed'), String(count)));
    }
  });
  return CoreOwner.connect(worker, { authority, generation });
};
await import('../../src/tools/desktop-process.js');
