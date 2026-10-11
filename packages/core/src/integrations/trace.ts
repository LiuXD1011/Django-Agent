import type { Json, JsonObject, ModelUsage } from '../contracts.js';
import { type CallScope, endpoint, fail, responseJSON, restrictedFetch } from './network.js';
import { isSecretKey } from '../storage/credentials.js';
import { externalProjection } from './projection.js';

export interface TraceEvent {
  name: string; traceId: string; spanId: string; parentSpanId?: string;
  startedAt: number; endedAt: number; success: boolean;
  type?: 'span' | 'generation' | 'embedding' | 'agent' | 'tool' | 'chain' | 'retriever' | 'event';
  sessionId?: string; metadata?: JsonObject; usage?: ModelUsage; input?: Json; output?: Json;
}
function content(value: Json, depth = 0): Json {
  if (depth >= 6) return '[truncated]';
  if (typeof value === 'string') return value.slice(0, 2000).replace(/\b(Bearer|Basic)\s+[a-zA-Z0-9._~+\/-]+={0,2}/gi, '$1 [redacted]').replace(/(?:api_?key|secret|token|password|key)\s*[=:]\s*[^\s&"']+/gi, '[redacted]').replace(/:\/\/[^/@\s:]+:[^/@\s]+@/g, '://[redacted]@');
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (Array.isArray(value)) return value.slice(0, 50).map(item => content(item, depth + 1));
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).slice(0, 50).map(([key, item]) => [key, isSecretKey(key) ? '[redacted]' : content(item, depth + 1)]));
  return value;
}
function metadata(value: JsonObject = {}): JsonObject {
  const output: JsonObject = {};
  for (const [key, item] of Object.entries(value)) {
    if (['request_id', 'knowledge_id', 'knowledge_base_id', 'session_id', 'message_id', 'job_id', 'model_call_id'].includes(key) && typeof item === 'string' && /^[a-zA-Z0-9_.:-]{1,128}$/.test(item)) output[key] = item;
    if (['duration_ms', 'iteration', 'attempt', 'dimension'].includes(key) && typeof item === 'number' && Number.isSafeInteger(item) && item >= 0) output[key] = item;
    if (['scenario', 'operation'].includes(key) && typeof item === 'string' && /^[a-z][a-z0-9_.-]{0,63}$/.test(item)) output[key] = item;
  }
  return output;
}
export async function recordTrace(scope: CallScope, config: JsonObject, tenantId: string, userId: string, event: TraceEvent): Promise<JsonObject> {
  if (!event || !/^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,5}$/.test(event.name) || !/^[0-9a-f]{32}$/.test(event.traceId) || /^0+$/.test(event.traceId) || !/^[0-9a-f]{16}$/.test(event.spanId) || /^0+$/.test(event.spanId) || (event.parentSpanId !== undefined && (!/^[0-9a-f]{16}$/.test(event.parentSpanId) || /^0+$/.test(event.parentSpanId))) || ![event.startedAt, event.endedAt].every(value => Number.isSafeInteger(value) && value >= 0 && value <= 8640000000000000) || event.endedAt < event.startedAt || typeof event.success !== 'boolean') return fail(400, 'integration_invalid_trace', 'Invalid trace identity or timing');
  const kind = event.type || 'span';
  if (!['span', 'generation', 'embedding', 'agent', 'tool', 'chain', 'retriever', 'event'].includes(kind)) return fail(400, 'integration_invalid_trace', 'Invalid observation type');
  if (['generation', 'embedding', 'tool'].includes(kind) && !event.parentSpanId && config.orphan_mode !== 'standalone') return { state: 'orphan_skipped' };
  const rate = config.sample_rate ?? 1;
  if (typeof rate !== 'number' || !Number.isFinite(rate) || rate < 0 || rate > 1) return fail(400, 'integration_invalid_trace_configuration', 'Invalid trace sampling configuration');
  // The same trace ID makes one sampling decision for every child, without sampling twice.
  if (parseInt(event.traceId.slice(0, 8), 16) / 0x100000000 >= rate) return { state: 'sampled_out' };
  const attributes: Array<{ key: string; value: { stringValue: string } }> = [];
  const attribute = (key: string, value: string) => attributes.push({ key, value: { stringValue: value } });
  attribute('langfuse.observation.type', kind);
  attribute('langfuse.environment', String(config.tracing_environment || 'default').slice(0, 128));
  attribute('langfuse.trace.metadata.tenant_id', tenantId);
  attribute('langfuse.user.id', userId);
  if (event.sessionId) { if (!/^[a-zA-Z0-9_.:-]{1,128}$/.test(event.sessionId)) return fail(400, 'integration_invalid_trace', 'Invalid trace session'); attribute('langfuse.session.id', event.sessionId); }
  for (const [key, value] of Object.entries(metadata(event.metadata))) attribute(`langfuse.observation.metadata.${key}`, String(value));
  if (config.log_content === true) {
    const previews = externalProjection({ input: event.input ?? null, output: event.output ?? null }, config);
    for (const key of ['input', 'output'] as const) if (previews[key] !== null) {
      const text = JSON.stringify(content(previews[key]!));
      if (Buffer.byteLength(text) > 16384) return fail(400, 'integration_trace_content_too_large', 'Trace content exceeds the size limit');
      attribute(`langfuse.observation.${key}`, text);
    }
  }
  if (event.usage) {
    const counters = ['prompt_tokens', 'completion_tokens', 'total_tokens', 'cached_tokens', 'reasoning_tokens'] as const;
    for (const key of counters) if (event.usage[key] !== undefined && (!Number.isSafeInteger(event.usage[key]) || event.usage[key]! < 0)) return fail(400, 'integration_invalid_trace', 'Invalid observed token counts');
    const input = event.usage.prompt_tokens || 0, output = event.usage.completion_tokens || 0;
    const cached = Math.min(event.usage.cached_tokens || 0, input), reasoning = Math.min(event.usage.reasoning_tokens || 0, output);
    attribute('langfuse.observation.usage_details', JSON.stringify({ input: input - cached, output: output - reasoning, input_cached_tokens: cached, output_reasoning_tokens: reasoning, total: event.usage.total_tokens ?? input + output }));
  }
  const span = { traceId: event.traceId, spanId: event.spanId, ...(event.parentSpanId ? { parentSpanId: event.parentSpanId } : {}), name: event.name, kind: 1, startTimeUnixNano: (BigInt(event.startedAt) * 1000000n).toString(), endTimeUnixNano: (BigInt(event.endedAt) * 1000000n).toString(), attributes, status: { code: event.success ? 1 : 2 } };
  const base = endpoint(config.base_url), url = new URL(base.toString().replace(/\/$/, '') + '/api/public/otel/v1/traces');
  const response = await restrictedFetch(scope, base.origin)(url, { method: 'POST', headers: { authorization: `Basic ${Buffer.from(`${config.public_key}:${config.secret_key}`).toString('base64')}`, 'content-type': 'application/json', accept: 'application/json', 'x-langfuse-ingestion-version': '4' }, body: JSON.stringify({ resourceSpans: [{ resource: { attributes: [{ key: 'service.name', value: { stringValue: 'marlin-core' } }] }, scopeSpans: [{ scope: { name: 'marlin-core', version: '0.7.0' }, spans: [span] }] }] }) });
  const result = await responseJSON(response) as any;
  if (!result || typeof result !== 'object' || Array.isArray(result)) return fail(502, 'integration_invalid_response', 'Invalid trace ingestion response');
  if (result.partialSuccess && (Number(result.partialSuccess.rejectedSpans || 0) > 0 || result.partialSuccess.errorMessage)) return fail(502, 'integration_trace_rejected', 'External service rejected the trace');
  return { state: 'accepted', trace_id: event.traceId, span_id: event.spanId, transport: 'otlp_http_json' };
}
