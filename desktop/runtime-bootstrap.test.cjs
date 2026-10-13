'use strict';
// Real child process / JSON IPC. Only native currentIdentity is a labelled
// unit fixture, so these tests make no Windows identity or Job claim.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { fork } = require('node:child_process');
const { randomUUID } = require('node:crypto');
const { mkdtempSync, writeFileSync, readFileSync, existsSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const path = require('node:path');

async function fixture(mode, action) {
  const root = mkdtempSync(path.join(tmpdir(), 'marlin-bootstrap 真实 '));
  const entry = path.join(root, 'business.cjs'), native = path.join(root, 'unit-native.cjs'), marker = path.join(root, '业务导入.json');
  const generation = randomUUID();
  writeFileSync(native, "exports.currentIdentity=()=>({pid:process.pid,createdAt:'134363313315163659',executable:process.execPath});\n");
  writeFileSync(entry, `const fs=require('node:fs');
const [marker,mode,...args]=process.argv.slice(2);
fs.writeFileSync(marker,JSON.stringify(args));
if(mode==='delayed') {
  process.send({type:'business-imported'});
  setTimeout(()=>process.send({type:'ready',protocol:1}),10000);
} else {
  process.on('message',message=>{if(message.type==='shutdown')process.disconnect();else process.send({type:'business-response',value:message.value});});
  process.send({type:'ready',protocol:1,args});
}
`);
  const child = fork(path.join(__dirname, 'runtime-bootstrap.cjs'), [entry, generation, native, marker, mode, '中文路径 和空格', 'argument-2'], {
    execPath: process.execPath, execArgv: [], env: {}, serialization: 'json', stdio: ['ignore', 'ignore', 'pipe', 'ipc'], windowsHide: true
  });
  const messages = [], waiters = new Set();
  child.stderr.on('data', () => {});
  child.on('message', message => {
    messages.push(message);
    for (const waiter of [...waiters]) if (waiter.type === message.type) { waiters.delete(waiter); clearTimeout(waiter.timer); waiter.resolve(message); }
  });
  const exited = new Promise(resolve => child.once('exit', (code, signal) => resolve({ code, signal })));
  const message = type => {
    const present = messages.find(value => value.type === type); if (present) return Promise.resolve(present);
    return new Promise((resolve, reject) => {
      const waiter = { type, resolve, timer: setTimeout(() => { waiters.delete(waiter); reject(new Error(`Private bootstrap did not reach ${type}`)); }, 3000) };
      waiters.add(waiter);
    });
  };
  let deadline;
  try {
    await Promise.race([action({ child, generation, marker, messages, message, exited }),
      new Promise((_, reject) => { deadline = setTimeout(() => reject(new Error('Owned bootstrap fixture deadline exceeded')), 5000); })]);
  } finally {
    clearTimeout(deadline);
    for (const waiter of waiters) clearTimeout(waiter.timer);
    if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
    await exited;
    rmSync(root, { recursive: true, force: true });
  }
}

test('actual bootstrap waits for authorization and forwards business JSON with original argv', async () => {
  await fixture('ready', async f => {
    const identity = await f.message('owned-bootstrap');
    assert.equal(identity.pid, f.child.pid); assert.equal(identity.generation, f.generation);
    assert.equal(existsSync(f.marker), false);
    f.child.send({ type: 'owned-start', protocol: 1, generation: f.generation });
    const ready = await f.message('ready');
    assert.deepEqual(ready.args, ['中文路径 和空格', 'argument-2']);
    assert.deepEqual(JSON.parse(readFileSync(f.marker, 'utf8')), ready.args);
    f.child.send({ type: 'invoke-fixture', value: '普通JSON 不损失' });
    assert.equal((await f.message('business-response')).value, '普通JSON 不损失');
    f.child.send({ type: 'shutdown' });
    assert.deepEqual(await f.exited, { code: 0, signal: null });
  });
});

test('actual startup cancellation before authorization never imports business', async () => {
  await fixture('ready', async f => {
    await f.message('owned-bootstrap'); f.child.send({ type: 'shutdown' });
    assert.deepEqual(await f.exited, { code: 0, signal: null });
    assert.equal(existsSync(f.marker), false);
  });
});

test('actual stale startup generation is rejected before business import', async () => {
  await fixture('ready', async f => {
    await f.message('owned-bootstrap');
    f.child.send({ type: 'owned-start', protocol: 1, generation: randomUUID() });
    assert.deepEqual(await f.exited, { code: 1, signal: null });
    assert.equal(existsSync(f.marker), false);
  });
});

test('actual shutdown during async business initialization remains effective before Core ready', async () => {
  await fixture('delayed', async f => {
    await f.message('owned-bootstrap');
    f.child.send({ type: 'owned-start', protocol: 1, generation: f.generation });
    await f.message('business-imported'); f.child.send({ type: 'shutdown' });
    assert.deepEqual(await f.exited, { code: 0, signal: null });
    assert.equal(f.messages.some(message => message.type === 'ready'), false);
  });
});
