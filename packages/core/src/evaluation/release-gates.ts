import type { JsonObject } from '../contracts.js';
import { object } from './common.js';
const metric = (row: JsonObject, name: string): number | null => typeof row[name] === 'number' && Number.isFinite(row[name]) && Number(row[name]) >= 0 && (['processing_duration_ms', 'index_bytes'].includes(name) || Number(row[name]) <= 1) ? Number(row[name]) : null;
const delta = (candidate: number | null, baseline: number | null) => candidate !== null && baseline !== null && baseline > 0 ? (candidate - baseline) / baseline * 100 : null;
const ratio = (candidate: number | null, baseline: number | null) => candidate !== null && baseline !== null && baseline > 0 ? candidate / baseline : null;
/** Missing or zero denominators leave promotion unverified rather than inventing an improvement. */
export function releaseGates(rows: JsonObject): JsonObject {
  const baseline = object(rows.fixed_window), auto = object(rows.auto_parent_child), semantic = object(rows.semantic_parent_child);
  const autoDelta = delta(metric(auto, 'mrr_at_10'), metric(baseline, 'mrr_at_10')), semanticDelta = delta(metric(semantic, 'mrr_at_10'), metric(auto, 'mrr_at_10'));
  const durationRatio = ratio(metric(semantic, 'processing_duration_ms'), metric(auto, 'processing_duration_ms')), indexRatio = ratio(metric(semantic, 'index_bytes'), metric(auto, 'index_bytes'));
  const nonDecreasing = (candidate: JsonObject, source: JsonObject, name: string) => { const left = metric(candidate, name), right = metric(source, name); return left !== null && right !== null && left >= right; };
  return { auto_parent_child: { mrr_relative_improvement_pct: autoDelta, pass: autoDelta !== null && autoDelta >= 5 - 1e-9 && nonDecreasing(auto, baseline, 'recall_at_20') && nonDecreasing(auto, baseline, 'context_precision') }, semantic_parent_child: { mrr_relative_improvement_over_auto_pct: semanticDelta, processing_duration_ratio_over_auto: durationRatio, index_bytes_ratio_over_auto: indexRatio, promotion_eligible: semanticDelta !== null && semanticDelta >= 3 - 1e-9 && nonDecreasing(semantic, auto, 'recall_at_20') && metric(semantic, 'context_precision') !== null && metric(auto, 'context_precision') !== null && durationRatio !== null && durationRatio <= 2 && indexRatio !== null && indexRatio <= 2 } };
}
