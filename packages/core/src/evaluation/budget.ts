import type { ModelConfiguration } from '../contracts.js';
import { resolveProvider } from '../models/providers.js';
import { fail } from './common.js';
import type { RagasRow } from './ragas.js';

export interface RagasBatch { rows: RagasRow[]; offset: number; timeoutMs: number }
const maximumTimeoutMs = 3600000, minimumTimeoutMs = 300000, startupAllowanceMs = 60000;

/** Ragas 0.4.3 runs serially: faithfulness 2 chats, relevance 3 chats + 2
 * embeddings, and precision 1 chat per context. Budget the full normal path,
 * including a bounded startup allowance and 1s protocol overhead per RPC. */
export function planRagasBatches(rows: RagasRow[], judge: ModelConfiguration, embedding: ModelConfiguration): RagasBatch[] {
  const judgeTimeoutMs = resolveProvider(judge).timeoutMs, embeddingTimeoutMs = resolveProvider(embedding).timeoutMs;
  const result: RagasBatch[] = [];
  let current: RagasRow[] = [], offset = 0, cost = 0;
  const flush = () => {
    if (!current.length) return;
    result.push({ rows: current, offset, timeoutMs: Math.max(minimumTimeoutMs, startupAllowanceMs + cost) });
    offset += current.length; current = []; cost = 0;
  };
  for (const row of rows) {
    const contexts = row.contexts.length;
    if (!Number.isSafeInteger(contexts) || contexts < 1 || contexts > 5) return fail(400, 'invalid_evaluation_input', 'Scoring contexts must follow the evaluation context policy');
    const judgeCalls = 5 + contexts;
    const rowCost = judgeCalls * judgeTimeoutMs + 2 * embeddingTimeoutMs + (judgeCalls + 2) * 1000;
    if (!Number.isSafeInteger(rowCost) || startupAllowanceMs + rowCost > maximumTimeoutMs) return fail(422, 'evaluation_budget_exceeded', 'One scoring row exceeds the supported worker budget');
    if (current.length === 50 || startupAllowanceMs + cost + rowCost > maximumTimeoutMs) flush();
    current.push(row); cost += rowCost;
  }
  flush(); return result;
}
