import assert from 'node:assert/strict';
import test from 'node:test';
import { Worker } from 'node:worker_threads';
import { AttemptControl, AttemptState, createAttemptControl, readAttemptControl, requestCancel } from '../src/jobs/attempt-control.js';

test('shared cancellation differentiates rollback, local permission, final permission and durable terminals', () => {
  const early = new AttemptControl();
  assert.equal(requestCancel(early.shared).disposition, 'requested');
  assert.throws(() => early.beginCommit(false), (e: any) => e.code === 'job_cancelled');
  early.terminal('cancelled'); assert.equal(readAttemptControl(early.shared).state, AttemptState.CANCELLED_DURABLE);
  const local = new AttemptControl(); local.beginCommit(false);
  assert.equal(requestCancel(local.shared).disposition, 'after_local_commit');
  local.committed(false); assert.deepEqual(readAttemptControl(local.shared), { state: AttemptState.CANCEL_REQUESTED, ordinal: 1n });
  assert.throws(() => local.checkpoint(), (e: any) => e.code === 'job_cancelled');
  const final = new AttemptControl(); final.beginCommit(true);
  assert.equal(requestCancel(final.shared).disposition, 'finalizing');
  final.committed(true); assert.deepEqual(readAttemptControl(final.shared), { state: AttemptState.DONE, ordinal: 1n });
  assert.equal(requestCancel(final.shared).disposition, 'terminal');
});

test('actual Worker CAS observes the independent control word and cannot cancel final permission', async () => {
  const control = new AttemptControl(); control.beginCommit(true);
  const worker = new Worker("const {parentPort,workerData}=require('node:worker_threads'); const a=new BigUint64Array(workerData); const w=Atomics.load(a,0); parentPort.postMessage({state:Number(w&255n),won:Atomics.compareExchange(a,0,w&~255n,w&~255n|1n)===(w&~255n)});", { eval: true, workerData: control.shared });
  try {
    const observed = await new Promise<any>((resolve, reject) => { worker.once('message', resolve); worker.once('error', reject); });
    assert.deepEqual(observed, { state: AttemptState.COMMITTING_FINAL, won: false });
    control.committed(true); assert.equal(readAttemptControl(control.shared).state, AttemptState.DONE);
  } finally { await worker.terminate(); }
});

test('failed COMMIT returns to the same ordinal and remembers cancellation after local permission', () => {
  const control = new AttemptControl(); control.beginCommit(false); requestCancel(control.shared); control.rolledBack();
  assert.deepEqual(readAttemptControl(control.shared), { state: AttemptState.CANCEL_REQUESTED, ordinal: 0n });
  const final = new AttemptControl(); final.beginCommit(true); final.rolledBack();
  assert.deepEqual(readAttemptControl(final.shared), { state: AttemptState.ACTIVE, ordinal: 0n });
  final.terminal('failed'); assert.equal(requestCancel(final.shared).disposition, 'terminal');
});

test('invalid size, unknown state and ordinal exhaustion fail closed without aliasing another attempt', () => {
  assert.throws(() => requestCancel(new SharedArrayBuffer(16)), (e: any) => e.code === 'attempt_control_invalid');
  const shared = createAttemptControl(); Atomics.store(new BigUint64Array(shared), 0, 254n);
  assert.equal(requestCancel(shared).disposition, 'invalid');
  assert.throws(() => new AttemptControl(shared).checkpoint(), (e: any) => e.code === 'ownership_lost');
  Atomics.store(new BigUint64Array(shared), 0, ((1n << 56n) - 1n) << 8n);
  assert.throws(() => new AttemptControl(shared).beginCommit(false), (e: any) => e.code === 'attempt_control_exhausted');
  assert.equal(readAttemptControl(createAttemptControl()).state, AttemptState.ACTIVE);
});
