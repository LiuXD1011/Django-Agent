import { mkdir, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { LocalServicesStartupService } from '../../src/integrations/local-services.js';
import { openNativeDatabase } from '../../src/storage/database.js';
const [data, source, record, mode, timeout, baseUrl] = process.argv.slice(2);
if (mode!.includes('lock')) {
  await mkdir(join(data!, '.cache/langfuse'), { recursive: true });
  const lock = openNativeDatabase(join(data!, '.cache/langfuse/startup-lock.sqlite3'), { timeout: 0 });
  lock.exec('BEGIN IMMEDIATE'); await writeFile(record + '.locked', String(process.pid));
  if (mode === 'release-lock') { await new Promise(done => setTimeout(done, 1500)); lock.exec('ROLLBACK'); lock.close(); } else setInterval(() => {}, 1000);
} else {
  const service = new LocalServicesStartupService(data!, () => ({ autostart: true, timeoutSeconds: Number(timeout), baseUrl }), { executable: { file: process.execPath, args: [resolve('test/fixtures/local-services-cli.cjs')] } });
  try { console.log(JSON.stringify(await service.start({ sourceRoot: source!, environ: { PATH: '', MARLIN_LOCAL_FIXTURE_RECORD: record } }))); } finally { await service.close(); }
}
