import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { ModelConfiguration } from '../src/contracts.js';
import type { RagasRow } from '../src/evaluation/ragas.js';

const configuration = (parameters: ModelConfiguration['parameters'] = {}): ModelConfiguration => ({ id: 'fixture', name: 'fixture', type: 'KnowledgeQA', source: 'openai', parameters: { base_url: 'http://127.0.0.1:9/v1', ...parameters } });
const rows = (count: number, contexts = 1): RagasRow[] => Array.from({ length: count }, (_, index) => ({ example_id: String(index), question: 'question', answer: 'answer', reference: 'reference', contexts: Array.from({ length: contexts }, () => 'evidence') }));
const planner = async () => {
  const module = await import('../src/evaluation/budget.js').catch(() => null);
  assert.ok(module, 'Scoring needs a bounded budget based on the actual Ragas RPC count and effective model timeouts');
  return module.planRagasBatches;
};

test('default five-row scoring has enough serial RPC budget for one and five contexts', async () => {
  const plan = await planner();
  assert.deepEqual(plan(rows(5), configuration(), configuration()).map(batch => [batch.offset, batch.rows.length, batch.timeoutMs]), [[0, 5, 2500000]]);
  assert.deepEqual(plan(rows(5, 5), configuration(), configuration()).map(batch => [batch.offset, batch.rows.length, batch.timeoutMs]), [[0, 4, 2988000], [4, 1, 792000]]);
});

test('effective provider timeout precedence and independently configured embedding timeout are respected', async () => {
  const plan = await planner();
  assert.equal(plan(rows(1), configuration({ timeout: 120 }), configuration({ timeoutMs: 60000 }))[0]!.timeoutMs, 908000);
  assert.equal(plan(rows(1), configuration({ timeout: 120, timeoutMs: 20000 }), configuration({ timeout: 120, timeoutMs: 30000 }))[0]!.timeoutMs, 300000);
  assert.deepEqual(plan(rows(5, 5), configuration({ timeout: 120 }), configuration()).map(batch => [batch.rows.length, batch.timeoutMs]), [[2, 2724000], [2, 2724000], [1, 1392000]]);
});

test('plans retain row order, offset, original fifty-row cap and five-minute floor', async () => {
  const plan = await planner(), input = rows(100), result = plan(input, configuration({ timeoutMs: 1 }), configuration({ timeoutMs: 1 }));
  assert.deepEqual(result.map(batch => [batch.offset, batch.rows.length, batch.timeoutMs]), [[0, 50, 460400], [50, 50, 460400]]);
  assert.deepEqual(result.flatMap(batch => batch.rows), input);
  assert.deepEqual(plan([], configuration(), configuration()), []);
  assert.equal(plan(rows(1), configuration({ timeoutMs: 1 }), configuration({ timeoutMs: 1 }))[0]!.timeoutMs, 300000);
});

test('all rows are preflighted and oversized single rows fail instead of silently shortening their deadline', async () => {
  const plan = await planner();
  for (const count of [0, 6]) assert.throws(() => plan(rows(1, count), configuration(), configuration()), (error: any) => error.code === 'invalid_evaluation_input');
  assert.throws(() => plan(rows(1), configuration({ timeoutMs: 600000 }), configuration()), (error: any) => error.code === 'evaluation_budget_exceeded');
  assert.throws(() => plan([...rows(1), ...rows(1, 6)], configuration(), configuration()), (error: any) => error.code === 'invalid_evaluation_input');
});
