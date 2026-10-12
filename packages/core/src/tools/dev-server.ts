import { parseArgs } from 'node:util';
import { resolve } from 'node:path';
import { createCoreHttpServer } from '../adapters/http.js';
import { CoreOwner } from '../runtime/owner-client.js';

async function main(): Promise<void> {
  const { values } = parseArgs({ options: { 'data-root': { type: 'string' }, port: { type: 'string', default: '8000' }, 'ui-origin': { type: 'string', multiple: true }, python: { type: 'string' }, 'parser-worker': { type: 'string' }, 'ragas-python': { type: 'string' }, 'ragas-worker': { type: 'string' } }, strict: true });
  if (!values['data-root']) throw new Error('Specify an isolated --data-root for browser testing');
  if (Boolean(values.python) !== Boolean(values['parser-worker'])) throw new Error('Specify both --python and --parser-worker for document operations');
  if (Boolean(values['ragas-python']) !== Boolean(values['ragas-worker'])) throw new Error('Specify both --ragas-python and --ragas-worker for evaluation operations');
  const parser = values.python ? { pythonExecutable: resolve(values.python), workerPath: resolve(values['parser-worker']!) } : undefined;
  const evaluation = values['ragas-python'] ? { ragas: { pythonExecutable: resolve(values['ragas-python']), workerPath: resolve(values['ragas-worker']!) } } : undefined;
  const app = await CoreOwner.start({ dataRoot: resolve(values['data-root']), allowAutoSetup: true, parser, evaluation });
  let http: ReturnType<typeof createCoreHttpServer> | undefined;
  let shutdown: Promise<void> | undefined;
  const close = () => shutdown ??= (async () => {
    try { await app.startupLog('INFO', 'application.stopping'); }
    finally { try { await http?.close(); } finally { await app.close(); } }
  })();
  try {
    http = createCoreHttpServer(await app.httpTransport(), { port: Number(values.port), browserOrigins: values['ui-origin'] ?? ['http://localhost:5173', 'http://127.0.0.1:5173'] });
    const { origin } = await http.listen();
    await app.startupLog('INFO', 'application.started');
    process.stdout.write(`TypeScript core listening at ${origin}; use the Vue browser entry on port 5173.\n`);
    process.once('SIGINT', () => { void close().catch(() => { process.exitCode = 1; }); });
    process.once('SIGTERM', () => { void close().catch(() => { process.exitCode = 1; }); });
  } catch (error) { await close(); throw error; }
}
main().catch(() => { process.stderr.write('TypeScript core startup failed; check the selected data directory and available port.\n'); process.exitCode = 1; });
