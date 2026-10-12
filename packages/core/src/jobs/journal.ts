import type { Json, JsonObject } from '../contracts.js';
import type { CoreDatabase } from '../storage/database.js';
import { decoded, freezeJson, JobError, object, sessionFor, type JobScope } from './common.js';
export const SESSION_EVENT_TYPES = new Set([
  'session/started', 'turn/user-message', 'turn/assistant-created', 'turn/completed', 'turn/error',
  'retrieval/search', 'retrieval/result', 'agent/iteration', 'agent/thinking', 'agent/actor',
  'tool/call', 'tool/result', 'llm/call', 'llm/retry', 'context/compacted', 'request/header',
  'maintenance/step', 'observability/trace-linked',
]);
export interface SessionEvent { seq: number; request_id: string; type: string; data: JsonObject; created_at: string }
const array = (v: Json | undefined): Json[] => Array.isArray(v) ? v : [];
const text = (v: Json | undefined, size = 500): string => String(v ?? '').slice(0, size);
const usage = (): JsonObject => ({ prompt_tokens: 0, completion_tokens: 0, llm_calls: 0 });
function addUsage(target: JsonObject, value: JsonObject) {
  for (const key of ['prompt_tokens', 'completion_tokens', 'cached_tokens']) target[key] = Number(target[key] ?? 0) + Number(value[key] ?? 0);
  target.llm_calls = Number(target.llm_calls) + 1;
}
/** Pure fold, independent from live handlers and message projections. */
export function foldTrajectory(events: SessionEvent[]): { version: number; turns: JsonObject[] } {
  const turns = new Map<string, JsonObject>(), steps = new Map<string, Map<string, JsonObject>>(), actors = new Map<string, Map<string, JsonObject>>(), directUsage = new Set<string>(), thinkingUsage = new Map<string, JsonObject>();
  for (const event of [...events].sort((a, b) => a.seq - b.seq)) {
    if (event.type === 'session/started') continue;
    const d = object(event.data), key = event.request_id || `__seq_${event.seq}`;
    let turn = turns.get(key);
    if (!turn) {
      turn = { request_id: event.request_id, seq_range: [event.seq, event.seq], started_at: event.created_at, completed_at: null, mode: '', model_id: '', provider: '', stopped_reason: '', interrupted: true, duration_ms: null, error: '', langfuse_trace_id: '', observability: null, user: null, assistant: { content: '' }, retrievals: [], steps: [], actors: [], request: null, retries: [], compactions: [], maintenance: [], usage: usage() };
      turns.set(key, turn); steps.set(key, new Map()); actors.set(key, new Map()); thinkingUsage.set(key, usage());
    }
    (turn.seq_range as Json[])[1] = event.seq;
    const step = () => {
      const id = `${d.actor_id ?? ''}:${d.iteration ?? 0}`; let s = steps.get(key)!.get(id);
      if (!s) { s = { iteration: d.iteration ?? null, actor_id: d.actor_id ?? '', agent_type: d.agent_type ?? '', thought: '', tools: [], llm: {}, started_at: null, ended_at: null }; steps.get(key)!.set(id, s); }
      return s;
    };
    const actor = () => {
      const id = String(d.actor_id ?? ''); if (!id) return null;
      let a = actors.get(key)!.get(id);
      if (!a) { a = { actor_id: id, agent_type: d.agent_type ?? '', event: '', status: '', input_prompt: '', output_excerpt: '', duration_ms: null, error: '', tool_calls: 0, usage: usage() }; actors.get(key)!.set(id, a); }
      return a;
    };
    switch (event.type) {
      case 'turn/user-message': turn.user = { content: d.content ?? '', images: array(d.images).length, attachments: array(d.attachments), mentioned_items: array(d.mentioned_items).length, channel: d.channel ?? '' }; break;
      case 'turn/assistant-created': turn.mode = d.mode ?? ''; turn.model_id = d.model_id ?? ''; break;
      case 'turn/completed':
        if (turn.completed_at === null) { turn.stopped_reason = d.stopped_reason ?? 'completed'; turn.duration_ms = d.duration_ms ?? null; turn.completed_at = event.created_at; if (d.content) object(turn.assistant).content = d.content; if (d.langfuse_trace_id) turn.langfuse_trace_id = text(d.langfuse_trace_id, 64); }
        break;
      case 'turn/error': if (turn.completed_at === null) { turn.stopped_reason = 'error'; turn.error = text(d.message, 300); turn.completed_at = event.created_at; } break;
      case 'observability/trace-linked': turn.observability = { provider: text(d.provider, 32), trace_id: text(d.trace_id, 64), root_observation_id: text(d.root_observation_id, 64), link_state: 'recorded' }; if (!turn.langfuse_trace_id) turn.langfuse_trace_id = text(d.trace_id, 64); break;
      case 'retrieval/search': (turn.retrievals as Json[]).push({ query: text(d.query, 200), kb_count: array(d.kb_ids).length, top_k: d.top_k ?? null, count: null, intent: '', degradations: [], refs: [] }); break;
      case 'retrieval/result': { const r = array(turn.retrievals).at(-1); if (r) Object.assign(object(r), { count: d.count ?? null, intent: text(d.intent, 50), degradations: array(d.degradations), refs: array(d.refs).slice(0, 8).map(v => { const ref = object(v); return { chunk_id: text(ref.chunk_id ?? ref.id, 64), title: text(ref.knowledge_title ?? ref.title, 200) }; }) }); break; }
      case 'agent/iteration': if (step().started_at === null) step().started_at = event.created_at; break;
      case 'agent/thinking': {
        const s = step(), llm = object(s.llm); s.thought = d.content ?? ''; s.ended_at = event.created_at;
        if (d.reasoning_content) s.reasoning = d.reasoning_content;
        for (const field of ['duration_ms', 'model', 'finish_reason', 'degradation']) if (d[field] != null) llm[field] = d[field]!;
        if (!turn.model_id && d.model) turn.model_id = d.model; if (!turn.provider && d.provider) turn.provider = d.provider;
        const u = object(d.usage); if (u.total_tokens || u.prompt_tokens || u.completion_tokens) { llm.usage = u; addUsage(thinkingUsage.get(key)!, u); } break;
      }
      case 'tool/call': {
        const tool = { tool_call_id: d.tool_call_id ?? '', name: d.name ?? '', argument_keys: array(d.argument_keys).sort(), arguments: object(d.arguments), output_excerpt: '', error: '', duration_ms: null, started_at: event.created_at, ended_at: null, schema: object(object(turn.request).tool_schemas)[String(d.name)] ?? null };
        (step().tools as Json[]).push(tool); const a = actor(); if (a) a.tool_calls = Number(a.tool_calls) + 1; break;
      }
      case 'tool/result': {
        const tools = step().tools as JsonObject[]; let tool = [...tools].reverse().find(t => t.tool_call_id === d.tool_call_id);
        if (!tool) { tool = { tool_call_id: d.tool_call_id ?? '', name: d.name ?? '', argument_keys: [], arguments: {} }; tools.push(tool); }
        Object.assign(tool, { output_excerpt: text(d.output), error: text(d.error, 200), duration_ms: d.duration_ms ?? null, ended_at: event.created_at }); if (d.meta) tool.meta = d.meta; break;
      }
      case 'agent/actor': { const a = actor(); if (a) { a.event = d.event ?? ''; a.status = d.status ?? ''; for (const field of ['input_prompt', 'output_excerpt', 'error']) if (d[field]) a[field] = text(d[field], field === 'input_prompt' ? 300 : field === 'error' ? 200 : 500); if (d.duration_ms != null) a.duration_ms = d.duration_ms; } break; }
      case 'llm/call': if (d.success !== false) { directUsage.add(key); addUsage(object(turn.usage), d); const a = actor(); if (a) addUsage(object(a.usage), d); if (!turn.model_id && d.model) turn.model_id = d.model; if (!turn.provider && d.provider) turn.provider = d.provider; } break;
      case 'request/header': if (turn.request === null) turn.request = { model: d.model ?? '', temperature: d.temperature ?? null, tools: array(d.allowed_tools), tool_schemas: Object.fromEntries(array(d.tool_schemas).map(v => [String(object(v).name), v])), max_iterations: d.max_iterations ?? null, history_messages: d.history_messages ?? null, agent_mode: d.agent_mode ?? '' }; break;
      case 'llm/retry': (turn.retries as Json[]).push({ attempt: d.attempt ?? null, reason: text(d.reason, 200), wait_seconds: d.wait_seconds ?? null, model: text(d.model, 120), fallback_to: text(d.fallback_to, 120), stage: text(d.stage, 40) }); break;
      case 'context/compacted': (turn.compactions as Json[]).push({ before_tokens: d.before_tokens ?? null, after_tokens: d.after_tokens ?? null, iteration: d.iteration ?? null, trigger: text(d.trigger, 60), actor_id: d.actor_id ?? '' }); break;
      case 'maintenance/step': (turn.maintenance as Json[]).push({
        step: text(d.step, 40), stage: text(d.stage, 40), status: text(d.status, 40),
        state: text(d.state, 40), graph_state: text(d.graph_state, 40),
        success: typeof d.success === 'boolean' ? d.success : null,
        duration_ms: d.duration_ms ?? null, error: text(d.error, 200), warnings: array(d.warnings),
      }); break;
    }
  }
  for (const [key, turn] of turns) {
    turn.steps = [...steps.get(key)!.values()].filter(s => Boolean(s.thought) || array(s.tools).length > 0 || Object.keys(object(s.llm)).length > 0); turn.actors = [...actors.get(key)!.values()];
    if (!directUsage.has(key)) turn.usage = thinkingUsage.get(key)!;
    object(turn.usage).total_tokens = Number(object(turn.usage).prompt_tokens) + Number(object(turn.usage).completion_tokens); turn.interrupted = turn.completed_at === null;
  }
  return { version: 3, turns: [...turns.values()] };
}
export class SessionEventJournal {
  constructor(readonly database: CoreDatabase) {}
  append(sessionId: string, requestId: string, type: string, data: JsonObject, scope: JobScope): SessionEvent {
    if (!SESSION_EVENT_TYPES.has(type)) throw new JobError(400, 'unknown_event', 'Unknown session event type');
    const frozen = freezeJson(data);
    return this.database.transaction(() => {
      const session = sessionFor(this.database, sessionId, scope), seq = Number(session.event_seq) + 1;
      if (!Number.isSafeInteger(seq)) throw new JobError(409, 'sequence_overflow', 'Event sequence limit reached');
      this.database.run('update sessions set event_seq=? where id=? and event_seq=?', seq, sessionId, Number(session.event_seq));
      const event = this.database.insert('session_events', { tenant_id: session.tenant_id, session_id: sessionId, seq, request_id: requestId, type, data: frozen });
      return { seq, request_id: requestId, type, data: frozen, created_at: String(event.created_at) };
    });
  }
  read(sessionId: string, scope: JobScope, afterSeq = 0, limit = 500): SessionEvent[] {
    sessionFor(this.database, sessionId, scope);
    return this.database.all('select * from session_events where session_id=? and seq>? and deleted_at is null order by seq limit ?', sessionId, Math.max(0, afterSeq), Math.max(1, Math.min(2000, limit))).map(r => ({ seq: Number(r.seq), request_id: String(r.request_id), type: String(r.type), data: object(decoded(r).data), created_at: String(r.created_at) }));
  }
  fold(sessionId: string, scope: JobScope): { version: number; turns: JsonObject[] } {
    sessionFor(this.database, sessionId, scope);
    const events = this.database.all('select * from session_events where session_id=? and deleted_at is null order by seq', sessionId).map(r => ({ seq: Number(r.seq), request_id: String(r.request_id), type: String(r.type), data: object(decoded(r).data), created_at: String(r.created_at) }));
    return foldTrajectory(events);
  }
}
