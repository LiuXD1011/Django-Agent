import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import test from 'node:test';
import { OwnedProcessRegistry } from '../src/jobs/owned-process.js';
const fixture = resolve('test/fixtures/local-services-cli.cjs');
test('discard output drains actual large stdout and stderr without capture or output-limit failure', async () => {
  const root = await mkdtemp(join(tmpdir(), 'marlin-output-discard ')), registry = new OwnedProcessRegistry();
  try {
    const result = await registry.spawn(process.execPath, [fixture], new AbortController().signal, {
      cwd: root, env: { MARLIN_LOCAL_FIXTURE_RECORD: join(root, 'calls'), MARLIN_LOCAL_FIXTURE_MODE: 'noisy' },
      discardOutput: true, maxOutputBytes: 8, timeoutMs: 5000,
    }).completion;
    assert.equal(result.code, 0); assert.equal(result.stdout, ''); assert.equal(result.stderr, '');
  } finally { await registry.close(); await rm(root, { recursive: true, force: true }); }
});
test('default output mode still captures small output and rejects actual excess output', async () => {
  const root = await mkdtemp(join(tmpdir(), 'marlin-output-default ')), registry = new OwnedProcessRegistry();
  try {
    const env = { MARLIN_LOCAL_FIXTURE_RECORD: join(root, 'calls'), MARLIN_LOCAL_FIXTURE_MODE: 'echo' };
    const result = await registry.spawn(process.execPath, [fixture], new AbortController().signal, { cwd: root, env, timeoutMs: 5000 }).completion;
    assert.equal(result.stdout, 'fixture-output'); assert.equal(result.stderr, 'fixture-error');
    await assert.rejects(registry.spawn(process.execPath, [fixture], new AbortController().signal, { cwd: root, env: { ...env, MARLIN_LOCAL_FIXTURE_MODE: 'noisy' }, maxOutputBytes: 8, timeoutMs: 5000 }).completion, { code: 'child_output_limit' });
  } finally { await registry.close(); await rm(root, { recursive: true, force: true }); }
});
