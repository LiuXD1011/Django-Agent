'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { finishDesktopQuit } = require('./owned-runtime.cjs');

test('desktop quit consumes shutdown rejection and still reports failure before actual application quit', async () => {
  const actions = [], error = new Error('owned tree unconfirmed');
  await finishDesktopQuit(() => { actions.push('windows'); }, async () => { actions.push('core'); throw error; },
    reported => { assert.equal(reported, error); actions.push('report'); }, () => { actions.push('quit'); });
  assert.deepEqual(actions, ['windows', 'core', 'report', 'quit']);
});

test('window cleanup failure cannot skip owned core shutdown or leave an unhandled quit Promise', async () => {
  const actions = [], error = new Error('window cleanup failed');
  await finishDesktopQuit(() => { actions.push('windows'); throw error; }, () => { actions.push('core'); },
    reported => { assert.equal(reported, error); actions.push('report'); }, () => { actions.push('quit'); });
  assert.deepEqual(actions, ['windows', 'core', 'report', 'quit']);
});

test('a diagnostic write failure cannot prevent exit and successful cleanup produces no failure report', async () => {
  let quit = 0;
  await finishDesktopQuit(() => {}, () => Promise.reject(new Error('core')), () => { throw new Error('diagnostic directory unavailable'); }, () => { quit++; });
  await finishDesktopQuit(() => {}, () => {}, () => assert.fail('No failed cleanup to report'), () => { quit++; });
  assert.equal(quit, 2);
});
