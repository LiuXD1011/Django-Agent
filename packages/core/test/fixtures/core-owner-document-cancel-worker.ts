import { parentPort, workerData } from 'node:worker_threads';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
if (!parentPort) throw new Error('Fixture requires private parent port');
if (import.meta.url.endsWith('.ts')) { const { register } = await import('tsx/esm/api'); register(); }
const { CoreApplication } = await import('../../src/application.js');
const { CoreIpcAdapter } = await import('../../src/adapters/ipc.js');
const { DocumentParser } = await import('../../src/documents/parser.js');
const { runCoreOwner } = await import('../../src/runtime/owner-host.js');
const { createOwnerAttemptBridge } = await import('../../src/runtime/owner-attempt-bridge.js');
const { config, authority, generation, barrier, barrierRoot } = workerData;
const state = new Int32Array(barrier), port = parentPort;
const bridge = createOwnerAttemptBridge(port, generation);
const app = new CoreApplication(config.dataRoot, { allowAutoSetup: true, parser: new DocumentParser(config.parser), attemptControl: {
  async register(identity, shared) {
    // The fixture observer exposes only to its trusted Node test parent, never
    // a renderer/fork transport or a configurable production worker URL.
    port.postMessage({ protocol: 1, type: 'fixture-attempt', identity, shared });
    await bridge.register(identity, shared);
  },
  unregister: bridge.unregister,
} });
app.database.sqlite.function('fixture_publication_barrier', () => {
  if (!Atomics.load(state, 2)) return 0;
  Atomics.store(state, 2, 0); Atomics.store(state, 0, 1); Atomics.notify(state, 0);
  if (barrierRoot) {
    mkdirSync(barrierRoot, { recursive: true });
    writeFileSync(join(barrierRoot, 'publication-paused'), '1');
    const deadline = Date.now() + 20000;
    while (!existsSync(join(barrierRoot, 'publication-release'))) {
      if (Date.now() >= deadline) throw new Error('Actual fork chunk INSERT barrier expired');
      Atomics.wait(state, 1, 0, 10);
    }
    return 0;
  }
  if (Atomics.wait(state, 1, 0, 20000) === 'timed-out') throw new Error('Actual chunk INSERT barrier expired');
  return 0;
});
app.database.sqlite.exec('CREATE TRIGGER fixture_chunk_publication AFTER INSERT ON chunks BEGIN SELECT fixture_publication_barrier(); END');
app.route('POST', '/api/v1/fixture/arm-document-publication', c => { app.auth.assertCan(c.auth, 'document.write'); Atomics.store(state, 0, 0); Atomics.store(state, 1, 0); Atomics.store(state, 2, 1); return {}; });
runCoreOwner(port, app, new CoreIpcAdapter(app), new BigUint64Array(authority), generation);
