import type { Json, JsonObject } from '../contracts.js';
import type { CoreDatabase, Row } from '../storage/database.js';
import { publicParameters } from '../storage/credentials.js';
import type { ChatExecution } from '../chat/types.js';
import { array, bounded, object } from '../chat/internal.js';
import { unavailable, validation, type AgentHooks, type ToolDefinition, type ToolResult } from './types.js';
const def = (name: string, description: string, properties: JsonObject, required: string[] = []): ToolDefinition => ({ name, description, parameters: { type: 'object', properties, required } });
const str = (description: string) => ({ type: 'string', description });
const clip = (text: string, limit: number): string => Array.from(text).slice(0, Math.max(0, limit)).join('');
export const builtinTools: ToolDefinition[] = [
  def('knowledge_search', 'Search selected knowledge bases and return document chunks with citations.', { query: str('Search query'), top_k: { type: 'integer', default: 5 } }, ['query']),
  def('grep_chunks', 'Find keywords in selected document chunks.', { keywords: str('Keywords; use | for alternative patterns'), knowledge_id: str('Optional selected document ID') }, ['keywords']),
  def('get_document_info', 'Read a selected document title, description and chunk count.', { knowledge_id: str('Document identifier') }, ['knowledge_id']),
  def('list_knowledge_docs', 'List documents in selected knowledge bases.', { keyword: str('Optional title or description filter') }),
  def('thinking', 'Record a structured thought without any external operation.', { thought: str('Thought') }, ['thought']),
  def('todo_write', 'Record task plan and progress.', { todos: { type: 'array', items: { type: 'object', properties: { content: str('Task'), status: { type: 'string', enum: ['pending', 'in_progress', 'completed'] } }, required: ['content', 'status'] } } }, ['todos']),
  def('database_query', 'Read scoped knowledge, chunk or session statistics.', { query_type: { type: 'string', enum: ['knowledge_stats', 'chunk_stats', 'session_stats', 'knowledge_list'] } }, ['query_type']),
  def('wiki_search', 'Search selected Wiki page titles and text.', { query: str('Keywords'), limit: { type: 'integer', default: 5 } }, ['query']),
  def('wiki_read_page', 'Read full selected Wiki page with source references.', { slug: str('Page slug'), knowledge_base_id: str('Optional selected knowledge base') }, ['slug']),
  def('wiki_list_pages', 'List selected Wiki page categories and titles.', { category: str('Optional category filter') }),
  def('wiki_read_source_doc', 'Read original enabled source chunks from a selected document.', { knowledge_id: str('Document identifier'), limit: { type: 'integer', default: 10 } }, ['knowledge_id']),
  def('query_knowledge_graph', 'Query configured graph within selected knowledge bases.', { query: str('Entity or relation query') }, ['query']),
  def('web_search', 'Search configured web provider when explicitly enabled by the user.', { query: str('Search query') }, ['query']),
  def('web_fetch', 'Fetch a URL through the configured controlled web adapter.', { url: str('URL'), max_chars: { type: 'integer', default: 3000 } }, ['url']),
  def('read_skill', 'Load instructions from the configured skill adapter.', { skill_name: str('Skill name') }, ['skill_name']),
  def('actor', 'Run or spawn specialized subagents; status/wait/cancel manage owned actor lifecycle.', { action: { type: 'string', enum: ['run', 'spawn', 'status', 'wait', 'cancel'] }, subagent_type: { type: 'string', enum: ['doc_retriever', 'wiki_researcher', 'graph_reasoner', 'answer_writer'] }, prompt: str('Task prompt'), actor_id: str('Owned actor identifier'), timeout_ms: { type: 'integer', default: 120000 } }, ['action']),
];
export class BuiltinToolRunner {
  private readonly seen = new Set<string>();
  constructor(readonly db: CoreDatabase, readonly hooks: AgentHooks) {}
  private bases(e: ChatExecution): string[] { e.assert(); return e.scope.knowledgeBaseIds ?? this.db.all('select id from knowledge_bases where tenant_id=? and deleted_at is null and is_temporary=0', String(e.scope.tenantId)).map(r => String(r.id)); }
  private docs(e: ChatExecution, knowledgeId?: string): Row[] {
    const bases = [...new Set(this.bases(e))]; if (!bases.length) return [];
    return this.db.all(`SELECT d.id,d.tenant_id,d.knowledge_base_id,d.title,d.description,d.file_name,d.file_type,d.parse_status,b.name AS knowledge_base_name
      FROM knowledges d JOIN knowledge_bases b ON b.id=d.knowledge_base_id AND b.tenant_id=d.tenant_id
      WHERE d.tenant_id=? AND d.knowledge_base_id IN (${bases.map(() => '?').join(',')})
        AND d.deleted_at IS NULL AND d.enable_status='enabled' AND b.deleted_at IS NULL
        ${knowledgeId === undefined ? '' : 'AND d.id=?'} ORDER BY d.created_at DESC,d.rowid DESC`,
      e.context.tenantId, ...bases, ...(knowledgeId === undefined ? [] : [knowledgeId]));
  }
  private chunks(e: ChatExecution, knowledgeId?: string): Row[] {
    const bases = [...new Set(this.bases(e))]; if (!bases.length) return [];
    return this.db.all(`SELECT c.id,c.knowledge_id,c.knowledge_base_id,c.chunk_index,c.chunk_type,c.content
      FROM chunks c JOIN knowledges d ON d.id=c.knowledge_id AND d.tenant_id=c.tenant_id AND d.knowledge_base_id=c.knowledge_base_id
      JOIN knowledge_bases b ON b.id=d.knowledge_base_id AND b.tenant_id=d.tenant_id
      WHERE d.tenant_id=? AND d.knowledge_base_id IN (${bases.map(() => '?').join(',')})
        AND d.deleted_at IS NULL AND d.enable_status='enabled' AND b.deleted_at IS NULL
        AND c.deleted_at IS NULL AND c.is_enabled=1 AND c.chunk_type IN ('text','image_ocr','image_caption','parent_text')
        ${knowledgeId === undefined ? '' : 'AND d.id=?'} ORDER BY c.chunk_index,c.rowid`,
      e.context.tenantId, ...bases, ...(knowledgeId === undefined ? [] : [knowledgeId]));
  }
  private reference(e: ChatExecution, chunk: Row, doc: Row, visible: string, tool: string): JsonObject {
    e.assert();
    const source = this.db.read('chunks', String(chunk.id));
    if (!source || String(source.tenant_id) !== String(e.context.tenantId) || source.knowledge_id !== doc.id || source.knowledge_base_id !== doc.knowledge_base_id || source.deleted_at !== null || source.is_enabled !== true || source.content !== chunk.content) throw new Error('Selected source changed');
    const length = Array.from(String(source.content)).length, visibleLength = Array.from(visible).length;
    const start = Number(source.start_at), end = Number(source.end_at), exact = Number.isSafeInteger(start) && Number.isSafeInteger(end) && start >= 0 && end - start === length;
    return {
      id: String(source.id), chunk_id: String(source.id), seq_id: source.seq_id === null ? null : String(source.seq_id),
      knowledge_id: String(doc.id), knowledge_base_id: String(doc.knowledge_base_id), knowledge_title: String(doc.title), knowledge_base_name: String(doc.knowledge_base_name),
      content: visible, chunk_index: source.chunk_index!, chunk_type: source.chunk_type!, context_parent_id: source.context_parent_id ?? null, media_parent_id: source.media_parent_id ?? null, anchor_chunk_id: source.anchor_chunk_id ?? null,
      image_info: source.image_info ?? null, metadata: source.metadata ?? {}, source_tool: tool, match_type: 'tool_read',
      source_start_at: source.start_at!, source_end_at: source.end_at!, source_range_exact: exact, clipped: visibleLength < length,
      ...(exact ? { visible_source_start_at: start, visible_source_end_at: start + visibleLength } : {}),
    };
  }
  private pages(e: ChatExecution): Row[] {
    const bases = new Set(this.bases(e)); return this.db.all('select id from wiki_pages where tenant_id=? and deleted_at is null order by updated_at desc,id', e.context.tenantId).map(r => this.db.read('wiki_pages', String(r.id))!).filter(r => bases.has(String(r.knowledge_base_id)));
  }
  async execute(name: string, args: JsonObject, e: ChatExecution): Promise<ToolResult> {
    e.assert();
    if (name === 'knowledge_search') {
      if (typeof args.query !== 'string' || !args.query.trim()) return validation('Query is required', ['query']);
      const result = await e.search(args.query, { topK: bounded(args.top_k, 5) }); const refs = result.results as unknown as Json[];
      const lines = result.results.map((r, i) => { const seen = this.seen.has(r.chunk_id); this.seen.add(r.chunk_id); return `[${i + 1}] ${r.knowledge_title}\n${seen ? '[Content already returned this run]' : r.content.slice(0, 500)}`; });
      const degraded = result.meta.degradations.map(d => `${d.stage}: ${d.reason}`).join('; ');
      return { output: (lines.join('\n\n') || 'No relevant documents found.') + (degraded ? `\nRetrieval degraded: ${degraded}` : ''), data: refs, references: refs };
    }
    if (name === 'list_knowledge_docs') { const keyword = String(args.keyword ?? '').toLocaleLowerCase(); const docs = this.docs(e).filter(d => `${d.title} ${d.description}`.toLocaleLowerCase().includes(keyword)).slice(0, 20); return { output: docs.map(d => `- ${d.title} — ${String(d.description ?? '').slice(0, 100)}`).join('\n') || 'No documents found in selected knowledge bases.' }; }
    if (name === 'get_document_info' || name === 'wiki_read_source_doc') {
      if (typeof args.knowledge_id !== 'string') return validation('Document ID is required', ['knowledge_id']);
      const doc = this.docs(e, args.knowledge_id)[0]; if (!doc) return { output: '', error: 'Selected document not found', error_type: 'NOT_FOUND', retryable: false };
      const chunks = this.chunks(e, args.knowledge_id);
      const info = { id: doc.id!, title: doc.title!, description: doc.description!, file_name: doc.file_name!, file_type: doc.file_type!, chunk_count: chunks.length, parse_status: doc.parse_status! };
      if (name === 'get_document_info') return { output: JSON.stringify(info), data: info };
      let output = clip(`# ${doc.title}\n`, 8000); const references: Json[] = [];
      for (const [index, chunk] of chunks.slice(0, bounded(args.limit, 10)).entries()) {
        const header = `${index ? '\n\n' : ''}## Chunk ${chunk.chunk_index}\n`, remaining = 8000 - Array.from(output).length;
        if (remaining <= 0) break;
        output += clip(header, remaining);
        const visible = clip(String(chunk.content), 8000 - Array.from(output).length);
        output += visible;
        if (visible) references.push(this.reference(e, chunk, doc, visible, name));
        if (visible !== chunk.content) break;
      }
      return { output, references };
    }
    if (name === 'grep_chunks') {
      if (typeof args.keywords !== 'string' || !args.keywords.trim()) return validation('Keywords are required', ['keywords']);
      if (args.knowledge_id && typeof args.knowledge_id !== 'string') return validation('Document ID must be a string', ['knowledge_id']);
      const knowledgeId = typeof args.knowledge_id === 'string' && args.knowledge_id ? args.knowledge_id : undefined;
      const alternatives = args.keywords.toLocaleLowerCase().split('|').map(v => v.trim().split(/\s+/));
      const docs = new Map(this.docs(e, knowledgeId).map(d => [d.id, d])); const chunks = this.chunks(e, knowledgeId).filter(c => alternatives.some(terms => terms.every(t => String(c.content).toLocaleLowerCase().includes(t)))).slice(0, 10);
      const references: Json[] = [], lines: string[] = [];
      for (const chunk of chunks) {
        const doc = docs.get(chunk.knowledge_id); if (!doc) continue;
        const visible = clip(String(chunk.content), 300); lines.push(`[${doc.title}] ${visible}`);
        if (visible) references.push(this.reference(e, chunk, doc, visible, name));
      }
      return { output: lines.join('\n---\n') || 'No matching chunks found.', references };
    }
    if (name === 'thinking') { if (typeof args.thought !== 'string') return validation('Thought is required', ['thought']); return { output: `[Thinking logged: ${args.thought.length} chars]`, data: { thought: args.thought } }; }
    if (name === 'todo_write') { if (!Array.isArray(args.todos) || args.todos.some(v => typeof object(v).content !== 'string' || !['pending', 'in_progress', 'completed'].includes(String(object(v).status)))) return validation('Invalid todo list', ['todos']); return { output: args.todos.map(v => `[${object(v).status}] ${object(v).content}`).join('\n'), data: args.todos }; }
    if (name === 'database_query') {
      const docs = this.docs(e); if (args.query_type === 'knowledge_stats') return { output: JSON.stringify({ total: docs.length, completed: docs.filter(d => d.parse_status === 'completed').length, processing: docs.filter(d => ['pending', 'processing'].includes(String(d.parse_status))).length }) };
      if (args.query_type === 'chunk_stats') return { output: JSON.stringify({ total: this.chunks(e).length }) };
      if (args.query_type === 'session_stats') return { output: JSON.stringify({ total: Number(this.db.get('select count(*) as n from sessions where tenant_id=? and user_id=? and deleted_at is null', e.context.tenantId, e.context.userId)?.n ?? 0) }) };
      if (args.query_type === 'knowledge_list') return { output: docs.slice(0, 10).map(d => `${d.title} (${d.file_type}, ${d.parse_status})`).join('\n') || 'No documents found.' }; return validation('Unknown query type', ['query_type']);
    }
    if (name.startsWith('wiki_')) {
      const pages = this.pages(e);
      if (name === 'wiki_read_page') { if (typeof args.slug !== 'string' || !args.slug) return validation('Slug is required', ['slug']); const p = pages.find(p => (!args.knowledge_base_id || p.knowledge_base_id === args.knowledge_base_id) && (p.slug === args.slug || String(p.title).includes(String(args.slug)))); return p ? { output: `# ${p.title}\n\n${String(p.content).slice(0, 8000)}\n\nSources: ${JSON.stringify(p.source_refs)}`, data: publicParameters(p) } : { output: '', error: 'Selected Wiki page not found', error_type: 'NOT_FOUND', retryable: false }; }
      if (name === 'wiki_search') { if (typeof args.query !== 'string' || !args.query) return validation('Query is required', ['query']); const terms = args.query.toLocaleLowerCase().split(/\s+/); return { output: pages.filter(p => terms.some(t => `${p.title} ${p.content}`.toLocaleLowerCase().includes(t))).slice(0, bounded(args.limit, 5)).map(p => `[${p.slug}] ${p.title}\n${String(p.summary || p.content).slice(0, 300)}`).join('\n\n') || 'No selected Wiki pages found.' }; }
      if (name === 'wiki_list_pages') return { output: pages.filter(p => String(p.category_path).includes(String(args.category ?? ''))).slice(0, 50).map(p => `[${p.slug}] ${p.title}`).join('\n') || 'No selected Wiki pages found.' };
    }
    if (name === 'query_knowledge_graph') { if (typeof args.query !== 'string' || !args.query) return validation('Query is required', ['query']); const bases = this.bases(e); if (!bases.length) return { output: 'No knowledge bases selected.' }; if (!this.hooks.graph) return unavailable('Graph adapter is not configured'); return this.hooks.graph(e.context, bases, args.query, { signal: e.signal }); }
    if (name === 'web_search') {
      if (typeof args.query !== 'string' || !args.query) return validation('Query is required', ['query']); if (!this.hooks.integrations) return unavailable('Web search adapter is not configured');
      const providers = this.db.all("select id from generic_resources where tenant_id=? and resource_type='web_search_providers' and status='active' and deleted_at is null order by updated_at desc,id", e.context.tenantId);
      if (!providers.length) return unavailable('Web search provider is not configured'); const result = await this.hooks.integrations.search(e.context, String(providers[0]!.id), args.query, { signal: e.signal }); return result.state === 'connected' ? { output: JSON.stringify(result.results), data: result } : unavailable(`Web search state: ${String(result.state)}`);
    }
    if (name === 'web_fetch') { if (typeof args.url !== 'string' || !/^https?:\/\//.test(args.url)) return validation('HTTP URL is required', ['url']); return this.hooks.webFetch ? this.hooks.webFetch(e.context, args.url, { signal: e.signal, maxChars: bounded(args.max_chars, 3000, 16000) }) : unavailable('Web fetch adapter is not configured'); }
    if (name === 'read_skill') return typeof args.skill_name === 'string' && args.skill_name ? this.hooks.readSkill ? this.hooks.readSkill(e.context, args.skill_name) : unavailable('Skill adapter is not configured') : validation('Skill name is required', ['skill_name']);
    return { output: '', error: 'Unknown tool', error_type: 'UNKNOWN_TOOL', retryable: false };
  }
}
