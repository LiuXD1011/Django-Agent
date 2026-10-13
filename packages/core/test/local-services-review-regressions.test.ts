import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import { syncBuiltinESMExports } from 'node:module';
import { basename, delimiter, join } from 'node:path';
import { tmpdir } from 'node:os';
import { setTimeout as delay } from 'node:timers/promises';
import test from 'node:test';
import { LocalServicesStartupService, resolveLocalServicesConfiguration } from '../src/integrations/local-services.js';

// Independent review R2, verified against real Python float(), no runtime Python dependency.
test('finite Python float deployment values retain underscores and Unicode decimal digits', () => {
  for (const [value, expected] of [
    ['1_0', 10], ['1_2.5', 12.5], ['١.٢٥', 1.25], ['１.２５', 1.25], ['𝟙.𝟚𝟝', 1.25],
    ['١_٢.٥e١', 120], ['1e1_0', 120], ['1.2_5', 1.25],
    ['\u00851\u0085', 1], ['\u00a01\u00a0', 1], ['\ufeff1', 45], ['\u001c1', 45],
    ['1__0', 45], ['_10', 45], ['10_', 45], ['1_.0', 45], ['1._0', 45], ['1e_1', 45], ['0x10', 45],
  ] as const) assert.equal(resolveLocalServicesConfiguration({}, { LANGFUSE_STARTUP_TIMEOUT_SECONDS: value }).timeoutSeconds, expected, value);
});

async function resolverCase(kind: 'budget' | 'abort' | 'close', stage: 'stat' | 'access' = 'stat') {
  const root = await fs.mkdtemp(join(tmpdir(), 'marlin-local-review-regression '));
  await fs.writeFile(join(root, '.env.langfuse'), '# synthetic only');
  const service = new LocalServicesStartupService(join(root, 'data'), () => ({ autostart: true, timeoutSeconds: 1 }));
  const original = { stat: fs.stat, access: fs.access }; let attempts = 0;
  let ready!: () => void; const entered = new Promise<void>(done => { ready = done; });
  const target = (path: unknown) => ['docker', 'docker.exe'].includes(basename(String(path)));
  // Only the slow candidate filesystem boundary is injected. SQLite locks,
  // source config, diagnostic writes and lifecycle remain real; no mock success CLI.
  fs.stat = (async (...args: Parameters<typeof fs.stat>) => {
    if (target(args[0])) {
      if (stage === 'access') return { isFile: () => true } as any;
      attempts++; ready(); await delay(160); throw Object.assign(new Error('synthetic missing candidate'), { code: 'ENOENT' });
    }
    return original.stat(...args);
  }) as typeof fs.stat;
  fs.access = async (...args) => {
    if (target(args[0]) && stage === 'access') { attempts++; ready(); await delay(160); throw Object.assign(new Error('synthetic denied candidate'), { code: 'EACCES' }); }
    return original.access(...args);
  };
  syncBuiltinESMExports(); const controller = new AbortController();
  try {
    const before = performance.now();
    const pending = service.start({ sourceRoot: root, environ: { PATH: Array(10).fill(join(root, 'absent')).join(delimiter) }, signal: controller.signal });
    await entered;
    if (kind !== 'budget') { await delay(40); if (kind === 'close') await service.close(); else controller.abort(); }
    const result = await pending; const elapsed = performance.now() - before;
    console.log(JSON.stringify({ case: `resolver-${kind}-${stage}`, state: result.state, attempts, elapsed_ms: elapsed }));
    assert.equal(result.state, kind === 'budget' ? 'startup_timeout' : 'cancelled');
    if (kind === 'budget') assert.ok(attempts < 10, 'deadline must stop subsequent PATH candidates');
    else assert.equal(attempts, 1, 'cancel/close must stop subsequent PATH candidates');
    assert.ok(elapsed < (kind === 'budget' ? 1450 : 600), 'only the current unabortable filesystem request may delay cleanup');
  } finally {
    fs.stat = original.stat; fs.access = original.access; syncBuiltinESMExports();
    await service.close(); await fs.rm(root, { recursive: true, force: true });
  }
}
// Independent review R1: all use the existing single deadline and abort lifetime.
test('Docker candidate stat traversal consumes the original monotonic budget', () => resolverCase('budget'));
test('Docker candidate stat traversal stops after caller cancellation', () => resolverCase('abort'));
test('service close waits for current stat but stops all further candidate traversal', () => resolverCase('close'));
test('Docker candidate access traversal consumes the original monotonic budget', () => resolverCase('budget', 'access'));
test('Docker candidate access traversal stops after caller cancellation', () => resolverCase('abort', 'access'));
