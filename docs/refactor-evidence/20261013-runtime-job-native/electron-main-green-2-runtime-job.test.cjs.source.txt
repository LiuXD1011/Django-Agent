'use strict';

// Real Windows fixtures, not a synthetic PID-reuse experiment. No app/Core is run.
const assert = require('node:assert/strict');
const { fork } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');
const [mode, addonPath, exchangeDirectory, resultPath] = process.argv.slice(2);
const fixturePath = path.join(__dirname, 'fixture.cjs');
const nodeExecutable = process.env.RUNTIME_JOB_TEST_NODE;
const observations = { mode, versions: process.versions, executable: process.execPath, cases: [] };
let sequence = 0;
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
function save() { fs.writeFileSync(resultPath, JSON.stringify(observations, null, 2)); }
save();

async function until(predicate, message, timeout = 5000) {
  const deadline = Date.now() + timeout;
  while (!predicate()) {
    assert.ok(Date.now() < deadline, message);
    await delay(10);
  }
}
async function exchange(operation, payload) {
  const id = String(++sequence).padStart(3, '0');
  const request = path.join(exchangeDirectory, `${id}.request.json`);
  const response = path.join(exchangeDirectory, `${id}.response.json`);
  fs.writeFileSync(`${request}.tmp`, JSON.stringify({ operation, ...payload }));
  fs.renameSync(`${request}.tmp`, request);
  await until(() => fs.existsSync(response), `Original-HANDLE observer did not acknowledge ${id}`);
  const receipt = JSON.parse(fs.readFileSync(response, 'utf8'));
  assert.equal(receipt.ok, true, receipt.error);
  return receipt;
}
function messageFrom(child, type) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { child.off('message', listener); reject(new Error(`Fixture ${type} timed out`)); }, 5000);
    function listener(message) {
      if (message.type === type || message.type === 'fixture-error') {
        clearTimeout(timer); child.off('message', listener);
        if (message.type === 'fixture-error') reject(new Error(message.message));
        else resolve(message);
      }
    }
    child.on('message', listener);
    child.once('error', reject);
  });
}
async function launch(t, missing = false, role = 'root') {
  const child = fork(fixturePath, [role, missing ? 'missing' : addonPath], {
    execPath: nodeExecutable, stdio: ['ignore', 'ignore', 'ignore', 'ipc'],
  });
  t.after(async () => {
    if (child.exitCode === null && child.signalCode === null) {
      if (child.connected) child.send({ type: 'shutdown' });
      await until(() => child.exitCode !== null || child.signalCode !== null, 'Own fixture graceful cleanup failed');
    }
  });
  const ready = await messageFrom(child, 'ready');
  return { child, identity: ready.identity };
}
async function ping(child) {
  const response = messageFrom(child, 'pong');
  child.send({ type: 'ping' });
  await response;
}
async function tree(root) {
  const response = messageFrom(root.child, 'tree');
  root.child.send({ type: 'start-tree' });
  return (await response).members;
}
async function observe(label, members) { return exchange('observe', { label, members }); }
async function check(label, exited, alive) { return exchange('check', { label, exited, alive }); }
async function scenario(t, name, callback) {
  const record = { name, passed: false };
  observations.cases.push(record);
  try { await callback(record); record.passed = true; }
  finally { save(); }
}

if (mode === 'red') {
  test('real Windows child requires the native Job adapter before authorization', { timeout: 15000 }, async (t) => {
    await scenario(t, 'missing-adapter-real-child', async (record) => {
      const root = await launch(t, true);
      record.before = await observe('red-root', [root.identity]);
      await ping(root.child);
      try { assert.ok(fs.existsSync(addonPath), 'Required runtime-job.node has not been implemented'); }
      finally {
        root.child.send({ type: 'shutdown' });
        await until(() => root.child.exitCode === 0, 'RED fixture did not exit normally');
        record.after = await check('red-root', [root.identity.pid], []);
      }
    });
  });
} else {
  assert.equal(process.platform, 'win32');
  const native = require(addonPath);
  test('identity and strict arguments use exact Windows FILETIME strings', async (t) => {
    await scenario(t, 'identity-and-arguments', async (record) => {
      const identity = native.currentIdentity();
      assert.equal(identity.pid, process.pid);
      assert.equal(identity.executable.toLowerCase(), process.execPath.toLowerCase());
      assert.match(identity.createdAt, /^[1-9][0-9]*$/);
      assert.ok(BigInt(identity.createdAt) > BigInt(Number.MAX_SAFE_INTEGER));
      record.originalHandle = await observe('driver', [identity]);
      for (const args of [[], [0, '1', nodeExecutable], [1.5, '1', nodeExecutable], ['1', '1', nodeExecutable],
        [1, 1, nodeExecutable], [1, '01', nodeExecutable], [1, '18446744073709551616', nodeExecutable],
        [1, '1', ''], [1, '1', `${nodeExecutable}\0`]]) {
        assert.throws(() => native.bindRoot(...args));
      }
    });
  });
  test('creation and image mismatches do not bind or stop the original child', async (t) => {
    await scenario(t, 'identity-mismatch', async (record) => {
      const root = await launch(t);
      record.before = await observe('mismatch-root', [root.identity]);
      assert.throws(() => native.bindRoot(root.identity.pid, String(BigInt(root.identity.createdAt) + 1n), nodeExecutable),
        { code: 'ERR_ROOT_IDENTITY' });
      assert.throws(() => native.bindRoot(root.identity.pid, root.identity.createdAt, `${nodeExecutable}.different`),
        { code: 'ERR_ROOT_IDENTITY' });
      await ping(root.child);
      record.after = await check('mismatch-root', [], [root.identity.pid]);
    });
  });
  for (const operation of ['terminate', 'close']) {
    test(`${operation} removes exactly its owned root, child and grandchild in an outer Job`, async (t) => {
      await scenario(t, `tree-${operation}`, async (record) => {
        const root = await launch(t);
        const bystander = await launch(t);
        const job = native.bindRoot(root.identity.pid, root.identity.createdAt, nodeExecutable);
        t.after(() => job.close());
        assert.deepEqual(job.status(), { rootExited: false, rootExitCode: null, activeProcesses: 1 });
        assert.throws(() => job.status.call({}), { code: 'ERR_JOB_RECEIVER' });
        assert.throws(() => job.terminate.call(Object.create(job)), { code: 'ERR_JOB_RECEIVER' });
        const members = await tree(root);
        await until(() => job.status().activeProcesses === 3, 'Nested Job never owned all three processes');
        record.before = await observe(`tree-${operation}`, [...members, bystander.identity]);
        job[operation]();
        if (operation === 'terminate') {
          await until(() => job.status().rootExited && job.status().activeProcesses === 0, 'Terminated Job not empty');
          record.nativeAfter = job.status();
          assert.equal(record.nativeAfter.rootExitCode, 1);
        }
        record.after = await check(`tree-${operation}`, members.map((item) => item.pid), [bystander.identity.pid]);
        await ping(bystander.child);
        job.close(); job.close();
        assert.throws(() => job.status(), { code: 'ERR_JOB_CLOSED' });
        assert.throws(() => job.terminate(), { code: 'ERR_JOB_CLOSED' });
      });
    });
  }
  test('same root HANDLE preserves actual exit0 while two descendants still live', async (t) => {
    await scenario(t, 'root-exits-first', async (record) => {
      const root = await launch(t);
      const bystander = await launch(t);
      const job = native.bindRoot(root.identity.pid, root.identity.createdAt, nodeExecutable);
      t.after(() => job.close());
      const members = await tree(root);
      await until(() => job.status().activeProcesses === 3, 'Root-first Job tree not complete');
      record.before = await observe('root-first', [...members, bystander.identity]);
      root.child.send({ type: 'exit-root' });
      await until(() => job.status().rootExited && job.status().activeProcesses === 2, 'Root exit was mistaken for tree exit');
      record.rootExit = job.status();
      assert.equal(record.rootExit.rootExitCode, 0);
      record.intermediate = await check('root-first', [root.identity.pid], [...members.slice(1).map((item) => item.pid), bystander.identity.pid]);
      job.terminate();
      await until(() => job.status().activeProcesses === 0, 'Root-first descendants not reaped');
      record.nativeAfter = job.status();
      assert.equal(record.nativeAfter.rootExitCode, 0);
      record.after = await check('root-first', members.map((item) => item.pid), [bystander.identity.pid]);
      await ping(bystander.child);
    });
  });
  test('abrupt death of the own Job owner closes its non-inherited handle and reaps its tree', async (t) => {
    await scenario(t, 'owner-abrupt-exit', async (record) => {
      const owner = await launch(t, false, 'owner');
      const bystander = await launch(t);
      const reply = messageFrom(owner.child, 'tree');
      owner.child.send({ type: 'owner-start-tree' });
      const members = (await reply).members;
      assert.equal(members.length, 4);
      record.before = await observe('owner-abrupt', [...members, bystander.identity]);
      // Public ChildProcess.kill uses its already-held original process object.
      // Never process.kill(pid), taskkill, or another PID lookup for termination.
      assert.equal(owner.child.kill('SIGKILL'), true);
      record.after = await check('owner-abrupt', members.map((item) => item.pid), [bystander.identity.pid]);
      await ping(bystander.child);
    });
  });
}
