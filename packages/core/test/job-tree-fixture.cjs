'use strict';
const { spawn } = require('node:child_process');
const { writeFileSync } = require('node:fs');

// OS lifetime tests need an actual descendant before the helper deadline.
// This fixture deliberately has no database or TypeScript-loader startup work.
if (process.argv[2] === 'tree') {
  const descendant = spawn(process.execPath, [__filename, 'descendant', process.argv[3]], {
    stdio: ['ignore', 'inherit', 'inherit', 'ipc'],
  });
  descendant.once('message', () => {
    process.stdout.write('ready\n');
    if (process.argv[4] === 'exit') process.exit(0);
  });
  process.on('SIGTERM', () => {});
  setInterval(() => {}, 1000);
} else if (process.argv[2] === 'descendant') {
  process.on('SIGTERM', () => {});
  writeFileSync(process.argv[3], JSON.stringify({ pid: process.pid }));
  process.send('ready');
  setInterval(() => {}, 1000);
} else {
  throw new Error('Unknown owned tree fixture mode');
}
