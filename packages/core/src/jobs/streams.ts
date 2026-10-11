import type { Json, JsonObject } from '../contracts.js';
import type { CoreDatabase, Row } from '../storage/database.js';
import { decoded, freezeJson, JobError, messageFor, notFound, object, sessionFor, type JobScope } from './common.js';
export interface StreamEvent { offset: number; event_type: string; data: JsonObject; created_at: string }
export interface StreamResult { content: string; refs?: Json[]; steps?: Json[]; durationMs?: number; error?: string }
export class StreamStore {
  constructor(readonly database: CoreDatabase) {}
  ensure(messageId: string, sessionId: string, scope: JobScope): Row {
    return this.database.transaction(() => {
      sessionFor(this.database, sessionId, scope); const m = messageFor(this.database, messageId, scope);
      if (String(m.session_id) !== sessionId) notFound(); const existing = this.database.read('stream_states', messageId);
      if (existing) { if (existing.session_id !== sessionId) notFound(); return existing; }
      const complete = m.is_completed === true;
      return this.database.insert('stream_states', { message_id: messageId, session_id: sessionId, is_complete: complete,
        final_content: complete ? m.content : '', final_refs: complete ? m.knowledge_references ?? [] : [],
        final_steps: complete ? m.agent_steps ?? [] : [], final_duration_ms: complete ? m.agent_duration_ms ?? 0 : 0 });
    });
  }
  read(messageId: string, scope: JobScope): Row | undefined { messageFor(this.database, messageId, scope); return this.database.read('stream_states', messageId); }
  events(messageId: string, scope: JobScope, fromOffset = 0): StreamEvent[] {
    messageFor(this.database, messageId, scope);
    return this.database.all('select * from stream_events where message_id=? and offset>=? order by offset limit 2000', messageId, Math.max(0, fromOffset)).map(r => ({ offset: Number(r.offset), event_type: String(r.event_type), data: object(decoded(r).data), created_at: String(r.created_at) }));
  }
  private event(messageId: string, sessionId: string, type: string, data: JsonObject): StreamEvent {
    const offset = Number(this.database.get('select coalesce(max(offset),-1)+1 as offset from stream_events where message_id=?', messageId)?.offset);
    const row = this.database.insert('stream_events', { message_id: messageId, session_id: sessionId, event_type: type, data: freezeJson(data), offset });
    return { offset, event_type: type, data: freezeJson(data), created_at: String(row.created_at) };
  }
  append(messageId: string, type: string, data: JsonObject, scope: JobScope): StreamEvent | null {
    if (type === 'complete' || type === 'error') {
      const content = data.content ?? '';
      if (typeof content !== 'string' || (data.refs !== undefined && !Array.isArray(data.refs)) || (data.steps !== undefined && !Array.isArray(data.steps))) throw new JobError(400, 'invalid_stream_result', 'Invalid stream result');
      const duration = data.duration_ms ?? data.durationMs ?? 0;
      if (typeof duration !== 'number') throw new JobError(400, 'invalid_stream_result', 'Invalid stream result');
      if (!this.finish(messageId, { content, refs: data.refs as Json[] | undefined, steps: data.steps as Json[] | undefined, durationMs: duration,
        ...(type === 'error' ? { error: content || 'Stream failed' } : {}) }, scope)) return null;
      const row = this.database.get('select * from stream_events where message_id=? order by offset desc limit 1', messageId);
      return row ? { offset: Number(row.offset), event_type: String(row.event_type), data: object(decoded(row).data), created_at: String(row.created_at) } : null;
    }
    const frozen = freezeJson(data);
    return this.database.transaction(() => {
      const message = messageFor(this.database, messageId, scope), state = this.ensure(messageId, String(message.session_id), scope);
      if (state.is_complete || state.is_error || message.is_completed) return null;
      const event = this.event(messageId, String(message.session_id), type, frozen);
      this.database.update('stream_states', messageId, { updated_at: new Date().toISOString() }); return event;
    });
  }
  finish(messageId: string, result: StreamResult, scope: JobScope): boolean {
    const frozen = freezeJson({ content: result.content, refs: result.refs ?? [], steps: result.steps ?? [], durationMs: result.durationMs ?? 0, error: result.error ?? '' });
    if (typeof result.content !== 'string' || !Number.isSafeInteger(result.durationMs ?? 0) || (result.durationMs ?? 0) < 0) throw new JobError(400, 'invalid_stream_result', 'Invalid stream result');
    return this.database.transaction(() => {
      const message = messageFor(this.database, messageId, scope), state = this.ensure(messageId, String(message.session_id), scope);
      if (state.is_complete || state.is_error || message.is_completed) return false;
      const error = String(frozen.error), content = String(frozen.content), now = new Date().toISOString();
      this.database.update('stream_states', messageId, { is_complete: true, is_error: Boolean(error), error_message: error, final_content: content, final_refs: frozen.refs, final_steps: frozen.steps, final_duration_ms: frozen.durationMs, updated_at: now });
      this.database.update('messages', messageId, { content, rendered_content: content, knowledge_references: frozen.refs, agent_steps: frozen.steps, agent_duration_ms: frozen.durationMs, is_completed: true, is_fallback: Boolean(error), updated_at: now });
      this.event(messageId, String(message.session_id), error ? 'error' : 'complete', { content, refs: frozen.refs!, steps: frozen.steps!, duration_ms: frozen.durationMs! }); return true;
    });
  }
  remove(messageId: string, scope: JobScope): void { this.database.transaction(() => { messageFor(this.database, messageId, scope); this.database.run('delete from stream_events where message_id=?', messageId); this.database.run('delete from stream_states where message_id=?', messageId); }); }
  deleteSession(sessionId: string, scope: JobScope): void {
    this.database.transaction(() => { sessionFor(this.database, sessionId, scope); this.database.run('delete from stream_events where session_id=?', sessionId); this.database.run('delete from stream_states where session_id=?', sessionId); this.database.run('delete from sessions where id=?', sessionId); });
  }
}
