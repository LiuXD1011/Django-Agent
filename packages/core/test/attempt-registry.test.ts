import assert from 'node:assert/strict';
import test from 'node:test';
import { AttemptRegistry } from '../src/runtime/attempt-registry.js';
import { AttemptState, createAttemptControl, readAttemptControl, type DocumentAttemptIdentity } from '../src/jobs/attempt-control.js';
import type { CancelTarget } from '../src/runtime/document-cancel-preflight.js';

const identity = (jobId = 'job', attempt = 1): DocumentAttemptIdentity => ({ jobId, attempt, previousAttempt: attempt - 1, ownerToken: `owner-${attempt}`, tenantId: 'tenant', jobUserId: 'job-user', knowledgeId: 'document', knowledgeBaseId: 'base' });
test('an authorized queued intent affects exactly its following claim and stale cleanup cannot remove a retry', () => {
  const registry = new AttemptRegistry(), first = identity(), shared = createAttemptControl();
  const { attempt: _attempt, ownerToken: _owner, ...queued } = first;
  const release = registry.request({ state: 'queued', identity: queued });
  registry.register(first, shared); assert.equal(readAttemptControl(shared).state, AttemptState.CANCEL_REQUESTED);
  release(); registry.unregister(first);
  const retry = identity('job', 2), next = createAttemptControl(); registry.register(retry, next);
  registry.unregister(first);
  assert.throws(() => registry.request({ state: 'running', identity: first }), { status: 409 });
  assert.throws(() => registry.request({ state: 'queued', identity: queued }), { status: 409 });
  assert.equal(readAttemptControl(next).state, AttemptState.ACTIVE);
  const done = registry.request({ state: 'running', identity: retry }); assert.equal(readAttemptControl(next).state, AttemptState.CANCEL_REQUESTED); done(); registry.close(false);
});
test('cancellation registry bounds distinct targets and repeated waiters without changing other namespace attempts', () => {
  const registry = new AttemptRegistry(), shared = createAttemptControl(), original = identity(); registry.register(original, shared);
  assert.throws(() => registry.request({ state: 'running', identity: { ...original, tenantId: 'other-tenant' } }), { status: 409 });
  assert.equal(readAttemptControl(shared).state, AttemptState.ACTIVE);
  const target: CancelTarget = { state: 'running', identity: original }, releases = Array.from({ length: 8 }, () => registry.request(target));
  assert.throws(() => registry.request(target), { status: 429 });
  const others = Array.from({ length: 7 }, (_, i) => { const { attempt: _a, ownerToken: _b, ...queued } = identity(`other-${i}`); return registry.request({ state: 'queued', identity: queued }); });
  const { attempt: _a, ownerToken: _b, ...overflow } = identity('overflow');
  assert.throws(() => registry.request({ state: 'queued', identity: overflow }), { status: 429 });
  for (const release of [...releases, ...others]) { release(); release(); }
  const released = registry.request({ state: 'queued', identity: overflow }); released(); registry.close();
});
test('graceful close preserves the owner commit decision while fault close invalidates volatile attempts', () => {
  for (const invalidate of [false, true]) {
    const registry = new AttemptRegistry(), shared = createAttemptControl(), target = identity(); registry.register(target, shared);
    registry.close(invalidate);
    assert.equal(readAttemptControl(shared).state, invalidate ? AttemptState.INVALID : AttemptState.ACTIVE);
    assert.throws(() => registry.request({ state: 'running', identity: target }), { status: 503 });
  }
});
