'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');

test('Langfuse native navigation grants only the fixed saved origin/project and manual authentication pages', () => {
  let boundary; try { boundary = require('./langfuse.cjs'); } catch {}
  assert.ok(boundary, 'Langfuse needs its own isolated native browser boundary');
  const plan = { origin: 'http://127.0.0.1:3456', projectPath: '/project/one/', open_url: 'http://127.0.0.1:3456/project/one/traces', mode: 'automatic' };
  for (const value of [plan.open_url, `${plan.origin}/project/one/traces/trace?peek=one`, `${plan.origin}/project/one/settings`]) assert.equal(boundary.allowedNavigation(value, plan), true);
  for (const value of [`${plan.origin}/project/two/traces`, `${plan.origin}/project/one-other/traces`, `${plan.origin}/project/one/../../two`, `${plan.origin}/project/one/%2e%2e/other`, `${plan.origin}/project/one/%2f..%2fother`, `${plan.origin}/project/one/%255c..%255cother`, `${plan.origin}/auth/sign-in`, `${plan.origin}/`, `${plan.origin}/organizations`, 'https://example.invalid/project/one/traces', 'file:///private', 'javascript:x', 'http://user:pass@127.0.0.1:3456/project/one/traces']) assert.equal(boundary.allowedNavigation(value, plan), false, value);
  assert.equal(boundary.allowedNavigation(`${plan.origin}/auth/sign-in?callbackUrl=${encodeURIComponent(plan.open_url)}`, { ...plan, mode: 'manual' }), true);
  assert.equal(boundary.allowedNavigation(`${plan.origin}/auth/sign-in?callbackUrl=https://evil.invalid`, { ...plan, mode: 'manual' }), false);
  for (const input of [{ id: 'fixed', action: 'open', url: 'https://evil.invalid' }, { id: 'fixed', action: 'open', cookies: {} }, { id: 'fixed', action: 'session', traceUrl: plan.open_url }, { id: 'fixed', action: 'anything' }]) assert.throws(() => boundary.validatePublicRequest(input));
  assert.doesNotThrow(() => boundary.validatePublicRequest({ id: 'fixed', action: 'open', traceUrl: plan.open_url }));
});
