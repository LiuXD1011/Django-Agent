'use strict';

// Only the bounded, isolated native-addon test harness starts this fixture.
const { fork } = require('node:child_process');
const [role, addonPath] = process.argv.slice(2);
const identity = addonPath === 'missing'
  ? { pid: process.pid, createdAt: null, executable: process.execPath }
  : require(addonPath).currentIdentity();
const children = [];
let ownedJob;
const keepAlive = setInterval(() => {}, 1000);

function child(nextRole) {
  return new Promise((resolve, reject) => {
    const member = fork(__filename, [nextRole, addonPath], {
      // libuv detached avoids its per-parent kill Job; it does NOT request
      // CREATE_BREAKAWAY_FROM_JOB. Native and outer Jobs must still own us.
      execPath: process.execPath, detached: true, windowsHide: true,
      stdio: ['ignore', 'ignore', 'ignore', 'ipc'],
    });
    children.push(member);
    const timer = setTimeout(() => reject(new Error('Fixture child readiness timed out')), 5000);
    member.once('error', reject);
    member.on('message', (message) => {
      if (message.type === 'ready') { clearTimeout(timer); resolve({ member, identity: message.identity }); }
    });
  });
}

process.on('message', async (message) => {
  if (message.type === 'ping') process.send({ type: 'pong', identity });
  if (message.type === 'owner-start-tree' && role === 'owner') {
    try {
      const root = await child('root');
      ownedJob = require(addonPath).bindRoot(root.identity.pid, root.identity.createdAt, process.execPath);
      root.member.once('message', (reply) => {
        if (reply.type === 'tree') process.send({ type: 'tree', members: [identity, ...reply.members] });
      });
      root.member.send({ type: 'start-tree' });
    } catch (error) { process.send({ type: 'fixture-error', message: error.message }); }
  }
  if (message.type === 'start-tree' && role === 'root') {
    try {
      const direct = await child('child');
      direct.member.once('message', (reply) => {
        if (reply.type === 'tree') process.send({ type: 'tree', members: [identity, ...reply.members] });
      });
      direct.member.send({ type: 'start-grandchild' });
    } catch (error) { process.send({ type: 'fixture-error', message: error.message }); }
  }
  if (message.type === 'start-grandchild' && role === 'child') {
    try {
      const grandchild = await child('grandchild');
      process.send({ type: 'tree', members: [identity, grandchild.identity] });
    } catch (error) { process.send({ type: 'fixture-error', message: error.message }); }
  }
  if (message.type === 'shutdown' || message.type === 'exit-root') {
    clearInterval(keepAlive);
    process.exit(0);
  }
});
// Descendants deliberately remain alive after their parent exits; the Job owns them.
process.on('disconnect', () => {});
process.send({ type: 'ready', identity });
