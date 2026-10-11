import type { JsonObject } from '../contracts.js';
import type { CoreDatabase, Row } from '../storage/database.js';
import { canonical, groups } from './internal.js';

const counters = ['prompt_tokens', 'completion_tokens', 'total_tokens', 'cached_tokens', 'reasoning_tokens', 'duration_ms'] as const;
const rate = (n: number, d: number) => d ? Math.round(n / d * 10000) / 10000 : 0;
function sum(rows: Row[]): JsonObject {
  const result: JsonObject = { calls: 0, records: rows.length, success: 0, failed: 0 };
  for (const key of counters) result[key] = 0;
  for (const row of rows) {
    const calls = Number(row.request_count || 0); result.calls = Number(result.calls) + calls;
    const key = row.success === true || row.success === 1 ? 'success' : 'failed'; result[key] = Number(result[key]) + calls;
    for (const key of counters) result[key] = Number(result[key]) + Number(row[key] || 0);
  }
  result.success_rate = rate(Number(result.success), Number(result.calls));
  result.cache_hit_rate = rate(Number(result.cached_tokens), Number(result.prompt_tokens));
  result.cache_total_rate = rate(Number(result.cached_tokens), Number(result.total_tokens));
  return result;
}
function group(rows: Row[], key: string, extra: string[] = []): JsonObject[] {
  const grouped = new Map<string, Row[]>();
  for (const row of rows) { const id = JSON.stringify([row[key], ...extra.map(k => row[k])]); const list = grouped.get(id) ?? []; list.push(row); grouped.set(id, list); }
  return [...grouped.values()].map(list => ({ ...Object.fromEntries([key, ...extra].map(k => [k, list[0]![k] ?? ''])), ...sum(list) }))
    .sort((a, b) => Number(b.total_tokens) - Number(a.total_tokens) || Number(b.calls) - Number(a.calls)).slice(0, 20);
}
function cacheGroup(row: Row): string {
  if (['summary', 'title', 'question', 'extract'].includes(String(row.model_type).toLowerCase())) return '';
  try { return groups[canonical(row.model_type)] ?? ''; } catch { return ''; }
}
/** Dates and cache buckets are explicit UTC ISO timestamps; token counters come only from stored calls. */
export function usageSummary(db: CoreDatabase, tenantId: string, query: JsonObject): JsonObject {
  const value = Number(String(query.range ?? query.days ?? '7').replace(/d$/i, ''));
  const days = Number.isFinite(value) ? Math.min(Math.max(Math.trunc(value), 1), 90) : 7;
  const now = Date.now(), since = new Date(now - days * 86400000).toISOString();
  let rows = db.all('select * from model_usage where tenant_id=? and deleted_at is null and created_at>=? order by created_at,id', tenantId, since);
  if (query.model_id) rows = rows.filter(r => r.model_id === query.model_id);
  if (query.model_type || query.type) rows = rows.filter(r => { try { return canonical(r.model_type) === canonical(query.model_type ?? query.type); } catch { return false; } });
  const cached = rows.filter(r => cacheGroup(r)), cache = sum(cached);
  const granularity = ['hour', '15m'].includes(String(query.granularity)) ? String(query.granularity) : 'day';
  const step = granularity === 'hour' ? 3600000 : granularity === '15m' ? 900000 : 86400000;
  const end = Math.floor(now / step) * step;
  const start = granularity === 'day' ? end - (days - 1) * step : Math.floor((now - days * 86400000) / step) * step;
  const buckets: JsonObject[] = [];
  for (let cursor = start; cursor <= end; cursor += step) { const iso = new Date(cursor).toISOString(); buckets.push({ bucket: iso, label: granularity === 'day' ? iso.slice(5, 10) : iso.slice(5, 16).replace('T', ' ') }); }
  const models: JsonObject[] = [];
  const names: Record<string, string> = { chat: '对话', embedding: 'Embedding', rerank: 'ReRank', vlm: '视觉' };
  for (const type of ['chat', 'embedding', 'rerank', 'vlm']) {
    const list = cached.filter(r => cacheGroup(r) === type), totals = sum(list);
    if (!totals.prompt_tokens) continue;
    const byBucket = new Map<string, Row[]>();
    for (const row of list) {
      const key = new Date(Math.floor(Date.parse(String(row.created_at)) / step) * step).toISOString();
      const bucketRows = byBucket.get(key) ?? []; bucketRows.push(row); byBucket.set(key, bucketRows);
    }
    const points = buckets.map(b => {
      const counts = sum(byBucket.get(String(b.bucket)) ?? []);
      return { ...b, prompt_tokens: counts.prompt_tokens!, cached_tokens: counts.cached_tokens!, total_tokens: counts.total_tokens!, cache_hit_rate: counts.cache_hit_rate!, cache_total_rate: counts.cache_total_rate! };
    });
    models.push({ model_key: `group:${type}`, model_id: `group:${type}`, model_name: names[type]!, provider: '', model_type: type, model_group: type, ...totals, points });
  }
  const daily: JsonObject[] = [];
  const today = Math.floor(now / 86400000) * 86400000;
  for (let offset = days - 1; offset >= 0; offset--) { const date = new Date(today - offset * 86400000).toISOString().slice(0, 10); daily.push({ date, ...sum(rows.filter(r => String(r.created_at).slice(0, 10) === date)) }); }
  return { range_days: days, since, total: sum(rows), cache: { prompt_rate: cache.cache_hit_rate!, total_rate: cache.cache_total_rate!, prompt_tokens: cache.prompt_tokens!, total_tokens: cache.total_tokens!, cached_tokens: cache.cached_tokens! },
    by_type: group(rows, 'model_type'), by_model: group(rows, 'model_id', ['model_name', 'provider', 'model_type']), by_scenario: group(rows, 'scenario'), daily,
    cache_series: { granularity, buckets, models } };
}
