import { createHash, randomUUID } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';
import type { AuthContext, ChatMessage, Json, JsonObject } from '../contracts.js';
import type { AuthService } from '../auth/index.js';
import type { CoreDatabase, Row } from '../storage/database.js';
import { CredentialVault, publicParameters } from '../storage/credentials.js';
import { ModelRuntimeError } from '../models/runtime.js';
import { ModelCaller } from '../chat/calls.js';
import type { ChatExecution, ChatForkHandle, ChatOutcome } from '../chat/types.js';
import { array, bounded, ChatError, fail, ids, memorySystemPrompt, now, object, text } from '../chat/internal.js';
import { BuiltinToolRunner, builtinTools } from './tools.js';
import { unavailable, validation, type AgentHooks, type ToolDefinition, type ToolResult } from './types.js';
export type { AgentHooks, ToolResult, ToolDefinition } from './types.js';
export class AgentError extends ChatError {}
const mainTools = ['actor', 'thinking', 'knowledge_search', 'list_knowledge_docs', 'get_document_info', 'grep_chunks', 'wiki_search', 'wiki_read_page'];
const presets: Record<string, { name: string; prompt: string; tools: string[]; rounds: number }> = {
  doc_retriever: { name: '文档检索子 Agent', prompt: '你是文档检索子 Agent，只基于原始文档查找证据。每条证据注明文档标题并引用原文；证据充足即停止，没有证据时明确说明。', tools: ['knowledge_search', 'grep_chunks', 'list_knowledge_docs', 'get_document_info'], rounds: 6 },
  wiki_researcher: { name: 'Wiki 研究子 Agent', prompt: '你是 Wiki 研究子 Agent，优先读取页面和来源。按主题总结并注明页面标题；冲突并列展示，证据充足即停止。', tools: ['wiki_search', 'wiki_read_page', 'wiki_list_pages', 'wiki_read_source_doc'], rounds: 6 },
  graph_reasoner: { name: '图谱推理子 Agent', prompt: '你是图谱推理子 Agent，用实际实体关系链支撑结论，图谱不存在的路径不要猜测。', tools: ['query_knowledge_graph', 'wiki_search', 'wiki_read_page', 'knowledge_search'], rounds: 6 },
  answer_writer: { name: '答案综合子 Agent', prompt: '你是答案综合子 Agent，只整理提供的证据，保留来源并明确冲突，不添加输入中不存在的事实。', tools: ['thinking'], rounds: 4 },
};
const defaultConfig = (input: JsonObject): JsonObject => ({ description: '自动调度文档、Wiki、图谱子 Agent。', avatar: '', system_prompt: '你是知识工作台主 Agent。简单问题直接回答；复杂问题用 actor 委派专业子任务。只能使用实际提供的工具，按证据回答并引用来源。', opening_statement: '你好，我可以帮你检索知识库并整理答案。', suggested_questions: ['请总结这个知识库', '有哪些关键风险点？', '给我列出引用来源'], kb_selection_mode: array(input.knowledge_base_ids).length ? 'selected' : 'all', knowledge_base_ids: [], model_id: '', rerank_model_id: '', allowed_tools: mainTools, mcp_selection_mode: array(input.mcp_services).length ? 'selected' : 'none', mcp_services: [], web_search_enabled: false, memory_enabled: true, rerank_enabled: true, temperature: 0.3, max_rounds: 8, ...input, name: input.name || input.title || '智能助手', type: 'multi-agent', agent_type: 'multi-agent', agent_mode: 'multi-agent' });
interface ActorWork { row: Row; controller: AbortController; work: Promise<ToolResult>; background: boolean; cancel?: () => Promise<void> }

export class AgentService {
  private readonly vault: CredentialVault; private readonly active = new Map<Promise<unknown>, AbortController>(); private closed = false;
  private readonly detached = new Map<Promise<Json>, ChatForkHandle>();
  constructor(readonly db: CoreDatabase, readonly auth: AuthService, readonly hooks: AgentHooks = {}) { this.vault = new CredentialVault(db.dataRoot); }
  private authorize(ctx: AuthContext, write = false) { if (this.closed) fail(503, 'agent_closed', 'Agent service is closed'); this.auth.assertCan(ctx, write ? 'agent.write' : 'read'); }
  private row(ctx: AuthContext, id: string, write = false): Row { this.authorize(ctx, write); const row = this.db.read('generic_resources', id); if (!row || row.deleted_at !== null || row.resource_type !== 'agents' || String(row.tenant_id) !== ctx.tenantId) fail(404, 'agent_not_found', 'Agent not found'); return row!; }
  private data(row: Row): JsonObject { return object(this.vault.decrypt(row.data!)); }
  private dto(row: Row): JsonObject { return { ...publicParameters(this.data(row)), id: String(row.id), tenant_id: row.tenant_id!, name: row.name!, status: row.status!, created_at: row.created_at!, updated_at: row.updated_at! }; }
  private validate(ctx: AuthContext, data: JsonObject): void {
    if (data.name !== undefined) text(data.name, 255); if (data.system_prompt !== undefined) text(data.system_prompt, 100000);
    for (const field of ['knowledge_base_ids', 'allowed_tools', 'mcp_services']) if (data[field] !== undefined) ids(data[field]);
    for (const id of ids(data.knowledge_base_ids ?? [])) { const kb = this.db.read('knowledge_bases', id); if (!kb || kb.deleted_at !== null || String(kb.tenant_id) !== ctx.tenantId) fail(404, 'knowledge_base_not_found', 'Knowledge base not found'); }
    for (const id of ids(data.mcp_services ?? [])) { const service = this.db.read('generic_resources', id); if (!service || service.deleted_at !== null || service.resource_type !== 'mcp_services' || String(service.tenant_id) !== ctx.tenantId) fail(404, 'mcp_not_found', 'MCP service not found'); }
    if (data.temperature !== undefined && (typeof data.temperature !== 'number' || !Number.isFinite(data.temperature) || data.temperature < 0 || data.temperature > 2)) fail(400, 'invalid_temperature', 'Temperature must be between zero and two');
    if (data.max_rounds !== undefined && (typeof data.max_rounds !== 'number' || !Number.isSafeInteger(data.max_rounds) || data.max_rounds < 1 || data.max_rounds > 20)) fail(400, 'invalid_rounds', 'Agent rounds must be between one and twenty');
  }
  create(ctx: AuthContext, input: JsonObject): JsonObject { this.authorize(ctx, true); const data = defaultConfig(input); this.validate(ctx, data); return this.dto(this.db.insert('generic_resources', { tenant_id: ctx.tenantId, resource_type: 'agents', name: String(data.name), status: String(data.status ?? 'active'), data: this.vault.encrypt(data) })); }
  get(ctx: AuthContext, id: string): JsonObject { return this.dto(this.row(ctx, id)); }
  update(ctx: AuthContext, id: string, input: JsonObject): JsonObject { return this.db.transaction(() => { const row = this.row(ctx, id, true), data = { ...this.data(row), ...input }; this.validate(ctx, data); return this.dto(this.db.update('generic_resources', id, { name: input.name ?? row.name, status: input.status ?? row.status, data: this.vault.encrypt(data), updated_at: now() })!); }); }
  delete(ctx: AuthContext, id: string): JsonObject { this.row(ctx, id, true); this.db.update('generic_resources', id, { deleted_at: now(), updated_at: now() }); return {}; }
  copy(ctx: AuthContext, id: string): JsonObject { const row = this.row(ctx, id, true); return this.create(ctx, { ...this.data(row), name: `${row.name} 副本`, copied_from: id }); }
  list(ctx: AuthContext, query: JsonObject = {}): JsonObject {
    this.authorize(ctx); const builtinId = `builtin-multi-agent-assistant-${ctx.tenantId}`;
    // Builtin creation is internal deterministic catalog initialization; reads never alter an existing resource.
    if (!this.db.read('generic_resources', builtinId)) this.db.insert('generic_resources', { id: builtinId, tenant_id: ctx.tenantId, resource_type: 'agents', name: '智能助手', data: defaultConfig({ name: '智能助手', builtin: true }) });
    const needle = String(query.keyword ?? query.query ?? query.q ?? '').toLocaleLowerCase();
    const rows = this.db.all("select id from generic_resources where resource_type='agents' and tenant_id=? and deleted_at is null order by updated_at desc,id", ctx.tenantId).map(r => this.db.read('generic_resources', String(r.id))!).filter(r => !needle || `${r.name} ${this.data(r).description}`.toLocaleLowerCase().includes(needle));
    const size = bounded(query.page_size ?? query.limit, 20), page = bounded(query.page, 1, 1000000), offset = query.offset !== undefined && query.page === undefined ? Math.max(0, Number(query.offset) || 0) : (page - 1) * size, items = rows.slice(offset, offset + size).map(r => this.dto(r));
    return { items, data: items, total: rows.length, page: Math.floor(offset / size) + 1, page_size: size };
  }
  suggestedQuestions(ctx: AuthContext, id = ''): JsonObject { this.authorize(ctx); if (id) { const config = this.data(this.row(ctx, id)); const questions = array(config.suggested_questions).map(v => ({ question: String(v), source: 'agent' })); if (questions.length) return { items: questions, questions }; } const questions = [{ question: '这个知识库里有哪些重要内容？', source: 'builtin' }, { question: '请总结最近上传的资料。', source: 'builtin' }, { question: '帮我查找和当前问题相关的引用。', source: 'builtin' }]; return { items: questions, questions }; }
  types(): JsonObject { return { items: [{ id: 'multi-agent', type: 'multi-agent', name: '智能助手', agent_mode: 'multi-agent', description: '调度文档、Wiki、图谱子任务' }] }; }
  placeholders(): JsonObject { return { items: ['query', 'context', 'history', 'current_date'].map(key => ({ key, fields: key === 'history' ? ['system_prompt'] : ['system_prompt', 'context_template'] })) }; }
  execute(e: ChatExecution): Promise<ChatOutcome> {
    this.authorize(e.context, true); const controller = new AbortController(), signal = AbortSignal.any([e.signal, controller.signal]);
    const assert = () => { signal.throwIfAborted(); this.authorize(e.context, true); e.assert(); };
    const execution: ChatExecution = { ...e, signal, assert, publish: work => e.publish(() => { assert(); return work(); }) };
    const promise = this.run(execution); this.active.set(promise, controller); void promise.finally(() => this.active.delete(promise)).catch(() => {}); return promise;
  }
  private async run(e: ChatExecution): Promise<ChatOutcome> {
    e.assert(); const resource = e.config.agent_id ? this.data(this.row(e.context, String(e.config.agent_id))) : {};
    const config = defaultConfig({ ...resource, ...e.config, model_id: e.config.model_id || resource.model_id || '', allowed_tools: resource.allowed_tools ?? e.input.allowed_tools ?? mainTools, max_rounds: e.input.max_rounds ?? resource.max_rounds ?? 8 });
    if (config.web_search_enabled !== true) config.allowed_tools = ids(config.allowed_tools).filter(name => !['web_search', 'web_fetch'].includes(name));
    else config.allowed_tools = [...new Set([...ids(config.allowed_tools), 'web_search', 'web_fetch'])];
    const runner = new BuiltinToolRunner(this.db, this.hooks), actors = new Map<string, ActorWork>(), tasks = new Set<Promise<ToolResult>>();
    const external = new Map<string, { service: string; name: string; schema: ToolDefinition }>();
    for (const service of ids(e.config.mcp_service_ids ?? resource.mcp_services ?? [])) {
      if (!this.hooks.integrations) { e.journal('maintenance/step', { step: 'mcp_discovery', success: false, error: 'MCP adapter is not configured' }); continue; }
      const result = await this.hooks.integrations.listMcpTools(e.context, service, { signal: e.signal }); e.assert();
      if (result.state !== 'connected') { e.journal('maintenance/step', { step: 'mcp_discovery', success: false, error: `MCP state: ${String(result.state)}` }); continue; }
      for (const value of array(result.tools)) { const tool = object(value), original = String(tool.name ?? ''); if (!original || original.length > 128) continue; const name = `mcp_${createHash('sha256').update(`${service}:${original}`).digest('hex').slice(0, 24)}`; external.set(name, { service, name: original, schema: { name, description: String(tool.description ?? '').slice(0, 2000), parameters: object(tool.inputSchema) } }); }
    }
    const actor = async (args: JsonObject, current: ChatExecution): Promise<ToolResult> => {
      const action = String(args.action ?? ''), actorId = String(args.actor_id ?? '');
      if (['run', 'spawn'].includes(action)) {
        const type = String(args.subagent_type ?? ''), preset = presets[type]; if (!preset) return validation('Unknown subagent type', ['subagent_type']); if (typeof args.prompt !== 'string' || !args.prompt.trim()) return validation('Prompt is required', ['prompt']); if (actors.size >= 8) return validation('Subagent limit reached');
        let index = 1; while (this.db.get('select id from agent_actors where session_id=? and actor_id=?', e.sessionId, `${type}-${index}`)) index++;
        if (action === 'spawn' && !current.fork) return unavailable('Independent actor scheduler is not configured');
        const id = `${type}-${index}`, controller = new AbortController();
        const row = current.publish(() => this.db.insert('agent_actors', { session_id: e.sessionId, actor_id: id, agent_type: type, parent_actor_id: 'main', parent_message_id: e.messageId, background: action === 'spawn', status: 'running', started_at: now(), input_prompt: args.prompt, tool_whitelist: preset.tools }));
        const lifecycle = (base: ChatExecution, event: string, data: JsonObject = {}) => { base.emit(event, { response_type: event, actor_id: id, agent_type: type, name: preset.name, parent_message_id: e.messageId, background: action === 'spawn', ...data }); if (['actor_started', 'actor_completed', 'actor_failed'].includes(event)) base.journal('agent/actor', { actor_id: id, agent_type: type, event: event === 'actor_started' ? 'spawned' : event === 'actor_completed' ? 'completed' : 'failed', status: event === 'actor_started' ? 'running' : 'idle', ...data }); };
        lifecycle(current, 'actor_started', { input_prompt: args.prompt });
        const execute = async (base: ChatExecution): Promise<ToolResult> => {
          const signal = AbortSignal.any([base.signal, controller.signal]);
          const check = () => { signal.throwIfAborted(); this.authorize(base.context, true); base.assert(); const fresh = this.db.read('agent_actors', String(row.id)); if (!fresh || fresh.deleted_at !== null || ['cancelled', 'interrupted'].includes(String(fresh.status))) fail(409, 'actor_cancelled', 'Actor cancelled'); };
          const child: ChatExecution = { ...base, signal, query: args.prompt as string, history: [], assert: check,
            publish: work => base.publish(() => { check(); return work(); }),
            journal: (type, data) => { check(); base.journal(type, { ...data, actor_id: id, agent_type: type }); },
            emit: (type, data) => { check(); lifecycle(base, type === 'thinking' ? 'actor_update' : `actor_${type}`, { ...data, ...(type.startsWith('tool_') ? { tool_name: data.name } : {}) }); },
            calls: new ModelCaller(this.db, base.calls.models, base.context, { ...base.calls.metadata, actor_id: id }, check, data => base.journal('llm/call', { ...data, actor_id: id, agent_type: type })) };
          const timeout = action === 'run' ? setTimeout(() => controller.abort(), bounded(args.timeout_ms, 120000, 600000)) : undefined; timeout?.unref();
          const monitor = action === 'run' ? setInterval(() => { try { check(); } catch { controller.abort(); } }, 100) : undefined; monitor?.unref();
          try {
            child.publish(() => this.db.insert('messages', { session_id: e.sessionId, request_id: `actor-${id}`, role: 'user', content: args.prompt, is_completed: true, agent_id: id, visible_to_user: false }));
            const result = await this.loop(child, { ...config, system_prompt: preset.prompt, allowed_tools: preset.tools, max_rounds: preset.rounds }, runner, new Map(), undefined); check();
            child.publish(() => { this.db.insert('messages', { session_id: e.sessionId, request_id: `actor-${id}`, role: 'assistant', content: result.content, rendered_content: result.content, agent_steps: result.steps, knowledge_references: result.refs, is_completed: true, agent_id: id, visible_to_user: false, agent_duration_ms: result.durationMs }); lifecycle(base, 'actor_completed', { output: result.content, output_excerpt: result.content.slice(0, 500), duration_ms: result.durationMs }); this.db.update('agent_actors', String(row.id), { status: 'idle', last_outcome: 'success', output: result.content, completed_at: now(), metadata: { ...object(this.db.read('agent_actors', String(row.id))!.metadata), duration_ms: result.durationMs, references: result.refs }, updated_at: now() }); });
            return { output: `[Actor ${id} success]\n${result.content}`, references: result.refs };
          } catch (error) {
            const cancelled = signal.aborted;
            // Detached terminal projection belongs to its queue claim; an uncertain paid result stays interrupted.
            if (action === 'spawn') throw error;
            try { base.publish(() => { lifecycle(base, 'actor_failed', { error: cancelled ? 'cancelled' : 'Subagent execution failed' }); this.db.update('agent_actors', String(row.id), { status: cancelled ? 'cancelled' : 'idle', last_outcome: cancelled ? 'cancelled' : 'failure', error: cancelled ? 'cancelled' : 'Subagent execution failed', completed_at: now(), updated_at: now() }); }); } catch {}
            if (error instanceof ModelRuntimeError && error.resultUnknown && !cancelled) throw error;
            return { output: '', error: cancelled ? 'Subagent cancelled' : 'Subagent failed', error_type: 'EXECUTION_ERROR', retryable: false };
          } finally { clearTimeout(timeout); clearInterval(monitor); }
        };
        let handle: ChatForkHandle | undefined;
        if (action === 'spawn') {
          handle = current.fork!({ actorRowId: String(row.id), actorId: id, query: args.prompt as string, config, timeoutMs: bounded(args.timeout_ms, 120000, 600000) }, async child => await execute(child) as unknown as Json);
          this.detached.set(handle.settled, handle); const pending = handle.settled; void pending.finally(() => this.detached.delete(pending)).catch(() => {});
        }
        const work = handle ? handle.settled.then(result => result as unknown as ToolResult) : execute(current);
        actors.set(id, { row, controller, work, background: action === 'spawn', ...(handle ? { cancel: handle.cancel } : {}) }); if (!handle) tasks.add(work); void work.catch(() => {});
        return action === 'run' ? work : { output: `[Actor ${id} spawned]`, data: { actor_id: id } };
      }
      if (!actorId) return validation('Actor ID is required', ['actor_id']); const existing = this.db.get('select id from agent_actors where session_id=? and actor_id=? and parent_message_id=? and deleted_at is null', e.sessionId, actorId, e.messageId); if (!existing) return { output: '', error: 'Owned actor not found', error_type: 'NOT_FOUND', retryable: false };
      if (action === 'cancel') { const target = actors.get(actorId); target?.controller.abort(); await target?.cancel?.(); current.publish(() => this.db.update('agent_actors', String(existing.id), { status: 'cancelled', last_outcome: 'cancelled', completed_at: now(), updated_at: now() })); return { output: `[Actor ${actorId} cancelled]` }; }
      if (action === 'wait') { const task = actors.get(actorId); if (!task) return { output: JSON.stringify(this.db.read('agent_actors', String(existing.id))) }; const deadline = Date.now() + bounded(args.timeout_ms, 120000, 600000); while (this.db.read('agent_actors', String(existing.id))?.status === 'running' && Date.now() < deadline) { current.assert(); await delay(30, undefined, { signal: current.signal }); } if (this.db.read('agent_actors', String(existing.id))?.status === 'running') return { output: '', error: 'Actor wait timed out', error_type: 'TIMEOUT', retryable: false }; return task.work; }
      if (action === 'status') return { output: JSON.stringify(publicParameters(this.db.read('agent_actors', String(existing.id))!)) }; return validation('Unknown actor action', ['action']);
    };
    try { const result = await this.loop(e, config, runner, external, actor); for (const task of tasks) { const child = await task; for (const ref of child.references ?? []) if (!result.refs.some(r => object(r).chunk_id === object(ref).chunk_id)) result.refs.push(ref); } return result; }
    finally { for (const value of actors.values()) if (!value.background) value.controller.abort(); await Promise.allSettled([...tasks]); }
  }
  private async loop(e: ChatExecution, config: JsonObject, runner: BuiltinToolRunner, external: Map<string, { service: string; name: string; schema: ToolDefinition }>, actor?: (args: JsonObject, e: ChatExecution) => Promise<ToolResult>): Promise<ChatOutcome> {
    const started = Date.now(), allowed = new Set(ids(config.allowed_tools)), definitions = [...builtinTools.filter(t => allowed.has(t.name) && (t.name !== 'actor' || actor)), ...[...external.values()].map(t => t.schema)].sort((a, b) => a.name.localeCompare(b.name));
    const tools = definitions.map(t => ({ type: 'function', function: { ...t } })); const messages: ChatMessage[] = [{ role: 'system', content: String(config.system_prompt) + '\n\n' + memorySystemPrompt(e.memoryEnabled === true) }, ...e.history, { role: 'user', content: [String(e.config.memory_context ?? ''), e.query].filter(Boolean).join('\n\n') }];
    const steps: Json[] = [], refs: Json[] = []; const rounds = bounded(config.max_rounds, 8, 20); const repeated = new Set<string>();
    e.journal('request/header', { model: config.model_id!, temperature: config.temperature!, allowed_tools: definitions.map(t => t.name), max_iterations: rounds, history_messages: e.history.length, agent_mode: config.agent_mode!, tool_schemas: definitions.map(t => ({ name: t.name, description: t.description.slice(0, 400), required: t.parameters.required ?? [], properties: Object.fromEntries(Object.entries(object(t.parameters.properties)).map(([k, v]) => [k, object(v).type ?? 'any'])) })) });
    for (let iteration = 1; iteration <= rounds; iteration++) {
      e.assert(); e.journal('agent/iteration', { iteration, model: config.model_id! });
      // Trim whole oldest turns; never leave tool messages without their assistant calls.
      const window = e.calls.models.configuration(e.context, String(config.model_id || 'KnowledgeQA')).context_window || 128000;
      const before = JSON.stringify(messages).length; while (messages.length > 3 && JSON.stringify(messages).length > Math.max(200, (window - Math.min(8000, window / 4)) * 3)) { let end = 2; while (end < messages.length - 1 && messages[end]!.role !== 'user') end++; messages.splice(1, end - 1); }
      if (JSON.stringify(messages).length < before) e.journal('context/compacted', { before_tokens: Math.ceil(before / 3), after_tokens: Math.ceil(JSON.stringify(messages).length / 3), iteration, trigger: 'context_window' });
      let content = '', reasoning = '', finish = ''; const merged = new Map<number, JsonObject>(); let usage: JsonObject = {};
      await e.calls.invoke(String(config.model_id || 'KnowledgeQA'), 'agent_chat', async (runtime, report) => {
        for await (const delta of runtime.chat(messages, { signal: e.signal, tools: tools as JsonObject[], temperature: Number(config.temperature) })) {
          e.assert(); if (delta.type === 'content' || delta.type === 'reasoning') { if (delta.type === 'content') content += delta.content; else reasoning += delta.content; e.emit('thinking', { iteration, content, reasoning_content: reasoning }); }
          else if (delta.type === 'usage') { report(delta.usage); usage = { ...delta.usage }; }
          else if (delta.type === 'done') finish = delta.finish_reason;
          else if (delta.type === 'tool_calls') for (const fragment of delta.tool_calls) { const index = Number(fragment.index ?? 0); if (!Number.isSafeInteger(index) || index < 0 || index > 63) throw new ModelRuntimeError('model_response_invalid', 'Model returned invalid tool call indices', undefined, true); const existing = merged.get(index) ?? { id: '', type: 'function', function: { name: '', arguments: '' } }; const fn = object(existing.function), patch = object(fragment.function); if (fragment.id) existing.id = String(existing.id) + String(fragment.id); fn.name = String(fn.name) + String(patch.name ?? ''); fn.arguments = String(fn.arguments) + String(patch.arguments ?? ''); if (String(fn.arguments).length > 256 * 1024) throw new ModelRuntimeError('model_response_invalid', 'Model tool arguments exceed the limit', undefined, true); existing.function = fn; merged.set(index, existing); }
        }
      }, { operation: 'chat', iteration });
      const calls = [...merged.entries()].sort(([a], [b]) => a - b).map(([, call]) => call);
      const step: JsonObject = { iteration, thought: content, reasoning, timestamp: Date.now() / 1000, tool_calls: [] }; steps.push(step);
      e.journal('agent/thinking', { iteration, content, reasoning_content: reasoning, usage, model: config.model_id!, finish_reason: finish });
      if (!calls.length) return { content, refs, steps, durationMs: Date.now() - started, stoppedReason: content.trim() ? 'completed' : 'empty_response' };
      messages.push({ role: 'assistant', content, tool_calls: calls });
      for (const call of calls) {
        const fn = object(call.function), name = String(fn.name), id = String(call.id); if (!id || !name) throw new ModelRuntimeError('model_response_invalid', 'Model returned incomplete tool calls', undefined, true);
        let args: JsonObject = {}, result: ToolResult; try { const parsed = JSON.parse(String(fn.arguments || '{}')); if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error(); args = parsed; } catch { result = validation('Tool arguments must be a JSON object'); }
        const fingerprint = JSON.stringify([name, args]); e.emit('tool_call', { iteration, name, tool_call_id: id, arguments: publicParameters(args) }); e.journal('tool/call', { iteration, name, tool_call_id: id, argument_keys: Object.keys(args).sort(), arguments: Object.fromEntries(Object.entries(args).filter(([key]) => ['query', 'keywords', 'knowledge_id', 'top_k', 'slug', 'action', 'subagent_type', 'actor_id'].includes(key))) });
        const toolStart = Date.now();
        if (repeated.has(fingerprint) && !['thinking', 'actor'].includes(name)) result = validation('The same tool request already ran; use its result or change the plan');
        else if (!definitions.some(d => d.name === name)) result = { output: '', error: 'Tool is outside the authorized selection', error_type: 'PERMISSION_DENIED', retryable: false };
        else if (!result!) {
          e.assert(); try {
            if (external.has(name)) { const remote = external.get(name)!; const response = await this.hooks.integrations!.callMcpTool(e.context, remote.service, remote.name, args, { signal: e.signal }); result = response.state === 'connected' ? { output: JSON.stringify(response.content), data: response, ...(response.isError ? { error: 'MCP tool reported an error', error_type: 'EXECUTION_ERROR', retryable: false } : {}) } : unavailable(`MCP state: ${String(response.state)}`); }
            else result = name === 'actor' && actor ? await actor(args, e) : await runner.execute(name, args, e);
          } catch (error) { e.assert(); if (error instanceof ModelRuntimeError && error.resultUnknown) throw error; result = { output: '', error: 'Tool execution failed', error_type: 'EXECUTION_ERROR', retryable: false }; }
        }
        e.assert(); result = { ...publicParameters(result! as unknown as JsonObject), duration_ms: Date.now() - toolStart } as unknown as ToolResult; repeated.add(fingerprint);
        (step.tool_calls as Json[]).push({ id, name, arguments: publicParameters(args), result: result as unknown as JsonObject });
        for (const ref of result.references ?? []) if (!refs.some(r => object(r).chunk_id === object(ref).chunk_id && object(r).knowledge_base_id === object(ref).knowledge_base_id)) refs.push(ref);
        const event = { iteration, name, tool_call_id: id, output: result.output, error: result.error ?? '', duration_ms: result.duration_ms!, meta: { count: result.references?.length ?? 0, error_type: result.error_type ?? '', retryable: result.retryable ?? false, failed_fields: result.failed_fields ?? [] } };
        e.emit('tool_result', event); e.journal('tool/result', event);
        messages.push({ role: 'tool', tool_call_id: id, content: result.error ? `${result.error}\n${JSON.stringify({ error_type: result.error_type, retryable: result.retryable, failed_fields: result.failed_fields })}` : result.output.slice(0, 16384) });
      }
    }
    return { content: '已达到最大推理轮数，请根据已返回的工具证据继续提问。', refs, steps, durationMs: Date.now() - started, stoppedReason: 'max_iterations' };
  }
  async close(): Promise<void> { this.closed = true; for (const controller of this.active.values()) controller.abort(); await Promise.allSettled([...this.detached.values()].map(handle => handle.cancel())); await Promise.allSettled([...this.active.keys(), ...this.detached.keys()]); }
}
