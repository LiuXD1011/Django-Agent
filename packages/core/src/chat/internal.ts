import { AppError } from '../errors.js';
import type { Json, JsonObject, ChatMessage } from '../contracts.js';
import type { Row } from '../storage/database.js';
import { publicParameters } from '../storage/credentials.js';
export class ChatError extends AppError {}
export const fail = (status: number, code: string, message: string): never => { throw new ChatError(status, code, message); };
export const object = (v: Json | undefined): JsonObject => v && typeof v === 'object' && !Array.isArray(v) ? v : {};
export const array = (v: Json | undefined): Json[] => Array.isArray(v) ? v : [];
export const now = () => new Date().toISOString();
export function text(value: Json | undefined, limit = 1000000): string { if (typeof value !== 'string' || value.length > limit) fail(400, 'invalid_chat', 'Invalid chat text'); return value as string; }
export const bounded = (value: Json | undefined, fallback: number, max = 200): number => { const n = Number(value ?? fallback); return Number.isSafeInteger(n) && n > 0 ? Math.min(n, max) : fallback; };
export function ids(value: Json | undefined): string[] { if (!Array.isArray(value) || value.some(v => typeof v !== 'string' || !v || v.length > 128)) fail(400, 'invalid_selection', 'Selection must be an array of resource identifiers'); return [...new Set(value as string[])]; }
const booleans = ['agent_enabled', 'web_search_enabled', 'enable_memory'];
const selections = ['knowledge_base_ids', 'mcp_service_ids'];
const strings = ['agent_id', 'model_id', 'summary_model_id'];
export function state(input: JsonObject, previous: JsonObject = {}): JsonObject {
  const source = input.agent_config === undefined ? input : object(input.agent_config);
  const next: JsonObject = { agent_enabled: false, agent_id: '', model_id: '', summary_model_id: '', knowledge_base_ids: [], web_search_enabled: false, enable_memory: true, mcp_service_ids: [], ...previous };
  if (input.agent_config !== undefined && (input.agent_config === null || Array.isArray(input.agent_config) || typeof input.agent_config !== 'object')) fail(400, 'invalid_config', 'Agent configuration must be an object');
  if (input.agent_config !== undefined) Object.assign(next, publicParameters(source));
  for (const key of booleans) if (source[key] !== undefined) { if (typeof source[key] !== 'boolean') fail(400, 'invalid_config', 'Configuration flag must be boolean'); next[key] = source[key]!; }
  for (const key of strings) if (source[key] !== undefined) next[key] = text(source[key], 128);
  for (const key of selections) if (source[key] !== undefined) next[key] = ids(source[key]);
  if (Object.hasOwn(source, 'knowledge_base_ids')) next.knowledge_selection_explicit = true;
  return next;
}
export function sessionDto(row: Row): JsonObject { const config = publicParameters(object(row.agent_config)); return { id: String(row.id), tenant_id: row.tenant_id!, title: row.title!, description: row.description!, knowledge_base_id: row.knowledge_base_id!, agent_id: row.agent_id!, user_id: row.user_id!, is_pinned: row.is_pinned!, pinned_at: row.pinned_at!, last_request_state: config, agent_config: config, created_at: row.created_at!, updated_at: row.updated_at! }; }
export function userContent(row: Row): string {
  if (row.rendered_content) return String(row.rendered_content);
  let result = String(row.content ?? '');
  const images = array(row.images).map(v => String(object(v).caption ?? object(v).description ?? '')).filter(Boolean);
  if (images.length) result += '\n\n[用户上传图片内容]\n' + images.join('\n');
  const files = array(row.attachments).map(v => { const item = object(v); return `- ${item.file_name ?? item.name ?? v} (${item.file_size ?? item.size ?? 0} bytes)`; });
  if (files.length) result += '\n\n[用户上传附件]\n' + files.join('\n'); return result;
}
export function historyMessages(rows: Row[], rounds: number, agent: boolean): ChatMessage[] {
  const grouped = new Map<string, Row[]>();
  for (const row of rows) { const key = String(row.request_id); const turn = grouped.get(key) ?? []; turn.push(row); grouped.set(key, turn); }
  const complete = [...grouped.values()].filter(turn => turn.some(r => r.role === 'user') && turn.some(r => r.role === 'assistant' && r.content && r.is_completed && !r.is_fallback));
  const result: ChatMessage[] = [];
  for (const turn of complete.slice(-rounds)) for (const row of turn) {
    if (row.role === 'user') result.push({ role: 'user', content: userContent(row) });
    if (row.role !== 'assistant') continue;
    if (agent) for (const entry of array(row.agent_steps)) {
      const step = object(entry), calls = array(step.tool_calls).map(object); if (!calls.length) continue;
      result.push({ role: 'assistant', content: String(step.thought ?? ''), tool_calls: calls.map(call => ({ id: String(call.id ?? ''), type: 'function', function: { name: String(call.name ?? ''), arguments: typeof call.arguments === 'string' ? call.arguments : JSON.stringify(call.arguments ?? {}) } })) });
      for (const call of calls) { const value = object(call.result); result.push({ role: 'tool', tool_call_id: String(call.id ?? ''), content: String(value.error ? `Error: ${value.error}` : value.output ?? '').slice(0, 1000) }); }
    }
    result.push({ role: 'assistant', content: String(row.content).replace(/<think>[\s\S]*?<\/think>/g, '').trim() });
  }
  return result;
}
