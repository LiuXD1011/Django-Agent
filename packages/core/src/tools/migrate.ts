import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { parseArgs } from 'node:util';
import { CoreDatabase } from '../storage/database.js';
import { createBackup, importLegacy, restoreBackup } from '../storage/legacy.js';

const usage = '用法：migrate.ts import|backup|restore --source 数据目录 --target 新空目录 [--summary 验收摘要.json]';

async function main(): Promise<void> {
  const { values, positionals } = parseArgs({ options: { source: { type: 'string' }, target: { type: 'string' }, summary: { type: 'string' } }, allowPositionals: true, strict: true });
  const operation = positionals[0];
  if (positionals.length !== 1 || !values.source || !values.target || !['import', 'backup', 'restore'].includes(operation ?? '')) throw new Error(usage);
  const started = performance.now();
  let summary: unknown;
  if (operation === 'import') {
    const result = await importLegacy({ sourceRoot: values.source, targetRoot: values.target });
    summary = { operation, protocol: 1, repeated: result.repeated, source_version: result.manifest.source_version, fingerprint: result.manifest.fingerprint, tables: result.manifest.tables, file_count: result.manifest.files.length, file_bytes: result.manifest.files.reduce((sum, file) => sum + file.size, 0), interrupted_tasks: result.manifest.interrupted_tasks, indexes: result.manifest.indexes, warnings: result.manifest.warnings, duration_ms: performance.now() - started };
  } else if (operation === 'backup') {
    const db = new CoreDatabase(values.source);
    try {
      const result = await createBackup(db, values.target);
      summary = { operation, protocol: 1, tables: result.tables, file_count: result.files.length, duration_ms: performance.now() - started };
    } finally { db.close(); }
  } else {
    const result = await restoreBackup(values.source, values.target);
    summary = { operation, protocol: 1, tables: result.tables, file_count: result.files.length, duration_ms: performance.now() - started };
  }
  const output = JSON.stringify(summary, null, 2);
  if (values.summary) {
    const path = resolve(values.summary);
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, output + '\n', { flag: 'wx' });
    process.stdout.write(`已完成 ${operation}，无秘密摘要保存至 ${path}\n`);
  } else process.stdout.write(output + '\n');
}

main().catch((error: unknown) => {
  process.stderr.write(`操作失败：${error instanceof Error ? error.message : '未知错误'}\n`);
  process.exitCode = 1;
});
