import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import test from 'node:test';
import type { CoreRequest, HttpMethod, JsonObject } from '../src/contracts.js';
import { CoreOwner } from '../src/runtime/owner-client.js';

const request = (method: HttpMethod, path: string, body?: JsonObject): CoreRequest => ({ protocol: 1, id: randomUUID(), method, path, ...(body ? { body } : {}) });
interface ProcessIds { supervisor: number; worker: number; descendant: number; }

async function running(pid: number): Promise<boolean> {
  try { process.kill(pid, 0); } catch { return false; }
  if (process.platform === 'linux') {
    const state = await readFile(`/proc/${pid}/stat`, 'utf8').catch(() => '');
    return Boolean(state) && state.slice(state.lastIndexOf(')') + 2).split(' ')[0] !== 'Z';
  }
  return true;
}
async function eventually(predicate: () => Promise<boolean>): Promise<void> {
  const deadline = Date.now() + 5000;
  while (!(await predicate())) {
    assert.ok(Date.now() < deadline, 'the owned process state must converge before the setup deadline');
    await delay(10);
  }
}

for (const operation of ['abort', 'close', 'timeout'] as const) {
  test(`complete owner ${operation} releases a running real Python worker and its descendant`, { timeout: 20000 }, async () => {
    const directory = await mkdtemp(join(tmpdir(), 'marlin-owner-lifecycle 中文 '));
    let owner: CoreOwner | undefined;
    const controller = new AbortController();
    const python = spawnSync('python', ['-c', 'import sys;print(sys.executable)'], { encoding: 'utf8' });
    assert.equal(python.status, 0);
    try {
      const marker = join(directory, 'owned-processes.json');
      const script = join(directory, 'owned-worker.py');
      // This fixture runs through the actual core parser supervisor. Its only
      // side effect is an atomic marker containing its own process IDs.
      await writeFile(script, `import sys,json,time,os,subprocess\nfrom pathlib import Path\nr=json.loads(sys.stdin.readline())\np=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])\nmarker=Path(${JSON.stringify(marker)})\ntemporary=marker.with_suffix('.tmp')\ntemporary.write_text(json.dumps({'supervisor':os.getppid(),'worker':os.getpid(),'descendant':p.pid}))\nos.replace(temporary,marker)\ntime.sleep(60)\n`);
      owner = await CoreOwner.start({ dataRoot: directory, allowAutoSetup: true,
        parser: { pythonExecutable: python.stdout.trim(), workerPath: script, timeoutMs: operation === 'timeout' ? 2000 : 10000 },
      });
      assert.equal((await owner.invoke(request('POST', '/api/v1/auth/auto-setup', { password: 'owner-lifecycle-test-password' }))).status, 200);
      const reason = new Error('isolated parser cancellation');
      const call = owner.invoke(request('GET', '/api/v1/system/parser-engines'), {}, controller.signal);
      // Attach rejection handlers before waiting for the real process handshake.
      const rejected = operation === 'timeout' ? undefined : assert.rejects(call, operation === 'abort' ? (error: unknown) => error === reason : { code: 'owner_closed' });
      void call.catch(() => {}); void rejected?.catch(() => {});
      await eventually(async () => readFile(marker, 'utf8').then(() => true, () => false));
      const ids = JSON.parse(await readFile(marker, 'utf8')) as ProcessIds;
      for (const pid of Object.values(ids)) { assert.ok(Number.isSafeInteger(pid) && pid > 0); assert.ok(await running(pid)); }
      if (operation === 'abort') {
        controller.abort(reason); await rejected;
      } else if (operation === 'close') {
        await owner.close(); await rejected;
        assert.equal(owner.worker.threadId, -1, 'close resolves only after the actual owner exits');
      } else {
        const response = await call; assert.equal(response.status, 200);
        const data = (response.body as { data: { items: { error_code: string }[] } }).data;
        assert.equal(data.items[0]?.error_code, 'parser_timeout');
      }
      await eventually(async () => (await Promise.all(Object.values(ids).map(running))).every(value => !value));
      // The supervised promise waits for child close, so the supervisor itself
      // must be reaped; orphan descendants may briefly remain as Linux zombies.
      assert.throws(() => process.kill(ids.supervisor, 0), { code: 'ESRCH' });
      if (operation !== 'close') assert.equal((await owner.invoke(request('GET', '/api/v1/auth/me'))).status, 200);
    } finally {
      controller.abort();
      try { await owner?.close(); } finally { await rm(directory, { recursive: true, force: true }); }
    }
  });
}
