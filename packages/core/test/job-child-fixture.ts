import { CoreDatabase } from '../src/storage/database.js';
import { JobQueue, OwnedProcessRegistry, SessionEventJournal } from '../src/jobs/index.js';
import { spawn } from 'node:child_process';
import { writeFileSync } from 'node:fs';
const mode = process.argv[2];
if (mode === 'hang') {
  process.stdout.write('ready\n'); setInterval(() => {}, 1000);
} else if (mode === 'tree') {
  const descendant = spawn(process.execPath, ['--import', 'tsx', 'test/job-child-fixture.ts', 'descendant', process.argv[3]!], { stdio: ['ignore', 'inherit', 'inherit', 'ipc'] });
  descendant.once('message', () => {
    process.stdout.write('ready\n');
    if (process.argv[4] === 'exit') process.exit(0);
  });
  process.on('SIGTERM', () => {}); setInterval(() => {}, 1000);
} else if (mode === 'descendant') {
  process.on('SIGTERM', () => {});
  writeFileSync(process.argv[3]!, JSON.stringify({ pid: process.pid }));
  process.send?.('ready'); setInterval(() => {}, 1000);
} else if (mode === 'owned-core') {
  const registry = new OwnedProcessRegistry();
  const owned = registry.spawn(process.execPath, ['test/job-tree-fixture.cjs', 'tree', process.argv[3]!, 'hang'], new AbortController().signal);
  writeFileSync(process.argv[4]!, JSON.stringify({ pid: owned.child.pid }));
  owned.child.stdout.pipe(process.stdout);
} else if (mode === 'journal') {
  const db = new CoreDatabase(process.argv[3]!);
  const journal = new SessionEventJournal(db);
  const scope = { tenantId: process.argv[5]!, userId: process.argv[6]! };
  process.stdout.write('ready\n');
  for await (const _chunk of process.stdin) { /* Parent releases both writers together. */ }
  try { for (let i = 0; i < 20; i++) journal.append(process.argv[4]!, process.argv[7]!, 'maintenance/step', { step: 'synthetic' }, scope); }
  finally { db.close(); }
  process.stdout.write('done\n');
} else if (mode === 'crash') {
  const db = new CoreDatabase(process.argv[3]!);
  const queue = new JobQueue(db, { leaseMs: 5000, heartbeatMs: 1000 });
  let entered = 0;
  queue.register('fixture', async context => {
    context.emit('entered', {}); entered++;
    if (entered === 2) process.stdout.write('ready\n');
    await new Promise<void>(() => {}); return {};
  });
  for (const id of process.argv.slice(4)) void queue.run(id);
} else { throw new Error('unknown synthetic child fixture'); }
