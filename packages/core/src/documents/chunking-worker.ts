import { parentPort, workerData } from 'node:worker_threads';
import type { ChunkingWorkerMessage, ChunkingWorkerRequest } from './chunking-workers.js';

// This entry and its computational import chain perform no business file, DB or network I/O.
// Worker threads are not a system sandbox; only trusted core code constructs them.
const request = workerData as ChunkingWorkerRequest;
const port = parentPort;
if (!port) throw new Error('Chunking requires a private Worker port.');
const send = (message: ChunkingWorkerMessage) => port.postMessage(message);
try {
  if (request.protocol !== 1 || typeof request.id !== 'string' || request.config.strategy === 'semantic') throw new Error('Invalid pure chunking request.');
  // Node 22 loads this type-only TS bootstrap, then tsx must be registered in
  // this actual Worker before resolving source modules written with .js imports.
  // The compiled branch never resolves or imports the development loader.
  if (import.meta.url.endsWith('.ts')) {
    const { register } = await import('tsx/esm/api');
    register();
  }
  const { splitDocument } = await import('./chunker.js');
  send({ protocol: 1, id: request.id, type: 'started' });
  const result = await splitDocument(request.parsed, request.config, { title: request.title });
  send({ protocol: 1, id: request.id, type: 'result', result });
} catch (error) {
  send({ protocol: 1, id: request.id, type: 'error', message: error instanceof Error ? error.message : 'Chunking failed.' });
} finally { port.close(); }
