import { randomUUID } from 'node:crypto';
import type { AuthContext, JsonObject, ModelConfiguration, ModelUsage } from '../contracts.js';
import type { CoreDatabase } from '../storage/database.js';
import { canonical, fail, object } from './internal.js';

export interface UsageOutcome {
  scenario: string;
  success: boolean;
  durationMs: number;
  errorCode?: string;
  metadata?: JsonObject;
  invocationId?: string;
}
const identifier = /^[a-z][a-z0-9_.-]{0,63}$/;
const ids = new Set(['request_id', 'knowledge_id', 'knowledge_base_id', 'session_id', 'message_id', 'job_id', 'model_call_id']);
const enums: Record<string, string[]> = {
  operation: ['chat', 'embedding', 'rerank', 'vision', 'complete', 'ocr', 'caption'],
  finish_reason: ['stop', 'length', 'tool_calls', 'content_filter', 'other'],
  think_profile: ['unknown', 'deepseek-v4-chat', 'glm-5.3-required-thinking'],
  think_policy_source: ['default', 'stale', 'model', 'tenant_env', 'internal'],
  think_level_requested: ['default', 'on', 'off', 'low', 'high', 'max'],
  think_level_applied: ['default', 'on', 'off', 'low', 'high', 'max', 'unconfirmed'],
};
function metadataProjection(metadata: JsonObject = {}): JsonObject {
  object(metadata); const result: JsonObject = {};
  for (const [key, value] of Object.entries(metadata)) {
    if (ids.has(key) && typeof value === 'string' && /^[a-zA-Z0-9_.:-]{1,128}$/.test(value)) result[key] = value;
    else if (key === 'result_unknown' && typeof value === 'boolean') result[key] = value;
    else if (['attempt', 'dimension', 'think_policy_revision'].includes(key) && typeof value === 'number' && Number.isSafeInteger(value) && value >= 0) result[key] = value;
    else if (enums[key] && typeof value === 'string' && enums[key]!.includes(value)) result[key] = value;
  }
  return Object.fromEntries(Object.entries(result).sort(([a], [b]) => a.localeCompare(b)));
}

/** Caller authenticates before dispatch; revocation must not erase an already-issued request's audit. */
export function auditUsage(db: CoreDatabase, ctx: AuthContext, configuration: ModelConfiguration, usage: ModelUsage, outcome: UsageOutcome): JsonObject {
  const model = db.read('models', configuration.id);
  if (!model || String(model.tenant_id) !== ctx.tenantId) fail(404, 'model_not_found', 'Usage model not found in the requested workspace');
  if (typeof configuration.name !== 'string' || configuration.name.length > 255 || typeof configuration.source !== 'string' || configuration.source.length > 64) fail(400, 'invalid_usage', 'Invalid audit model identity');
  const counts: JsonObject = {};
  for (const key of ['prompt_tokens', 'completion_tokens', 'total_tokens', 'cached_tokens', 'reasoning_tokens'] as const) {
    const value = usage[key];
    if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) fail(400, 'invalid_usage', 'Usage counters must be finite nonnegative safe integers');
    counts[key] = value;
  }
  if (!Number.isSafeInteger(outcome.durationMs) || outcome.durationMs < 0 || typeof outcome.success !== 'boolean' || typeof outcome.scenario !== 'string' || !identifier.test(outcome.scenario) ||
    (outcome.errorCode !== undefined && (typeof outcome.errorCode !== 'string' || !identifier.test(outcome.errorCode)))) fail(400, 'invalid_usage', 'Invalid usage outcome; use fixed scenario and error identifiers');
  const id = outcome.invocationId ?? randomUUID();
  if (typeof id !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(id)) fail(400, 'invalid_usage', 'Invocation ID must be a UUID');
  const metadata = metadataProjection(outcome.metadata);
  const record: JsonObject = { id: id.toLowerCase(), tenant_id: ctx.tenantId, model_id: configuration.id, model_name: configuration.name,
    model_type: canonical(configuration.type), provider: configuration.source, scenario: outcome.scenario, success: outcome.success, request_count: 1,
    ...counts, duration_ms: outcome.durationMs, error_message: outcome.errorCode ?? '', request_id: metadata.request_id ?? '', metadata };
  return db.transaction(() => {
    const existing = db.read('model_usage', String(record.id));
    if (existing) {
      const equal = Object.entries(record).every(([key, value]) => key === 'tenant_id' ? String(existing[key]) === String(value)
        : key === 'metadata' ? JSON.stringify(metadataProjection(object(existing[key]))) === JSON.stringify(value) : existing[key] === value);
      if (!equal) fail(409, 'usage_conflict', 'Invocation ID already has different recorded usage');
      return { ...record, created_at: existing.created_at! };
    }
    const stored = db.insert('model_usage', record); return { ...record, created_at: stored.created_at! };
  });
}
