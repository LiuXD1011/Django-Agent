import { lookup } from 'node:dns/promises';
import { realpath, readdir, readFile, stat } from 'node:fs/promises';
import { request as httpRequest } from 'node:http';
import { request as httpsRequest } from 'node:https';
import { isIP } from 'node:net';
import { join, relative, isAbsolute } from 'node:path';
import type { AuthContext, Json, JsonObject } from '../contracts.js';
import type { AuthService } from '../auth/index.js';
import { AppError } from '../errors.js';
import type { GraphService } from '../graph/index.js';
import type { IntegrationService } from '../integrations/index.js';
import type { SearchIndex } from '../retrieval/search-index.js';
import type { SearchHit } from '../retrieval/types.js';
import type { CoreDatabase } from '../storage/database.js';
import type { AgentHooks, ToolResult } from './types.js';

export interface ApplicationAgentDependencies {
  db: CoreDatabase; auth: AuthService; graph: GraphService; index: SearchIndex; integrations: IntegrationService;
  /** Packaged business skills only. No fallback to user or Codex directories. */
  skillsRoot?: string;
  /** Trusted core fixture override; this object is never renderer input. */
  webFetch?: { allowedOrigins?: string[]; timeoutMs?: number };
}
const object = (v: unknown): JsonObject => v && typeof v === 'object' && !Array.isArray(v) ? v as JsonObject : {};
const fail = (code: string, message: string, status = 400): never => { throw new AppError(status, code, message); };
const inside = (root: string, file: string) => { const path = relative(root, file); return path !== '' && path !== '..' && !path.startsWith('../') && !path.startsWith('..\\') && !isAbsolute(path); };

/** Reject private, special-use and transition addresses before pinning the connection. */
function publicAddress(address: string): boolean {
  if (isIP(address) === 4) {
    const [a, b, c] = address.split('.').map(Number) as [number, number, number];
    return !(a === 0 || a === 10 || a === 127 || a >= 224 || a === 100 && b >= 64 && b <= 127 || a === 169 && b === 254 || a === 172 && b >= 16 && b <= 31 || a === 192 && (b === 168 || b === 0 && (c === 0 || c === 2)) || a === 198 && (b === 18 || b === 19 || b === 51 && c === 100) || a === 203 && b === 0 && c === 113);
  }
  if (isIP(address) !== 6) return false;
  // Only ordinary global unicast. Exclude documentation, Teredo and 6to4 transition ranges.
  const [first, second] = address.split(':').map(part => parseInt(part || '0', 16)), lower = address.toLowerCase();
  return first! >= 0x2000 && first! <= 0x3fff && !(first === 0x2001 && second! < 0x200) && !lower.startsWith('2001:db8:') && !lower.startsWith('2002:') && !lower.startsWith('3fff:');
}
function htmlText(text: string): string {
  const parts: string[] = [], lower = text.replace(/[A-Z]/g, char => char.toLowerCase()); let cursor = 0;
  // Consume each tag/body once. A missing raw-text closing tag excludes the rest of that body.
  while (cursor < text.length) {
    const open = text.indexOf('<', cursor);
    if (open < 0) { parts.push(text.slice(cursor)); break; }
    parts.push(text.slice(cursor, open)); const end = text.indexOf('>', open + 1); if (end < 0) break;
    const tag = /^\s*(script|style)\b/i.exec(text.slice(open + 1, Math.min(end, open + 64)));
    cursor = end + 1;
    if (tag) {
      const name = tag[1]!.toLowerCase(), prefix = `</${name}`; let close = lower.indexOf(prefix, cursor);
      while (close >= 0 && !/[\s/>]/.test(text[close + prefix.length] ?? '')) close = lower.indexOf(prefix, close + prefix.length);
      if (close < 0) break;
      const closeEnd = text.indexOf('>', close + prefix.length); if (closeEnd < 0) break; cursor = closeEnd + 1;
    }
    parts.push(' ');
  }
  return parts.join('')
    .replace(/&(#x[0-9a-f]+|#\d+|amp|lt|gt|quot|apos|nbsp);/gi, (whole, entity: string) => {
      const known: Record<string, string> = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ' };
      if (entity[0] !== '#') return known[entity.toLowerCase()] ?? whole;
      const value = parseInt(entity.slice(entity[1]?.toLowerCase() === 'x' ? 2 : 1), entity[1]?.toLowerCase() === 'x' ? 16 : 10);
      return value > 0 && value <= 0x10ffff && !(value >= 0xd800 && value <= 0xdfff) ? String.fromCodePoint(value) : whole;
    }).replace(/\s+/g, ' ').trim();
}

export function createApplicationAgentHooks(deps: ApplicationAgentDependencies): { hooks: AgentHooks; close(): Promise<void> } {
  let closed = false; const controllers = new Set<AbortController>(), active = new Set<Promise<unknown>>();
  const assert = (ctx: AuthContext) => { if (closed) fail('agent_hooks_closed', 'Agent services are closed', 503); deps.auth.assertCan(ctx, 'read'); };
  const operation = async <T>(ctx: AuthContext, outer: AbortSignal | undefined, work: (signal: AbortSignal) => Promise<T>): Promise<T> => {
    assert(ctx); const controller = new AbortController(), abort = () => controller.abort();
    if (outer?.aborted) controller.abort(); else outer?.addEventListener('abort', abort, { once: true });
    controllers.add(controller);
    const pending = Promise.resolve().then(() => { controller.signal.throwIfAborted(); return work(controller.signal); }).then(value => { controller.signal.throwIfAborted(); assert(ctx); return value; });
    active.add(pending); void pending.finally(() => { active.delete(pending); controllers.delete(controller); outer?.removeEventListener('abort', abort); }).catch(() => {});
    return pending;
  };
  const allowedOrigins = new Set((deps.webFetch?.allowedOrigins ?? []).map(value => new URL(value).origin));
  const timeout = deps.webFetch?.timeoutMs ?? 15000;
  if (!Number.isSafeInteger(timeout) || timeout < 1 || timeout > 60000) fail('web_fetch_invalid_timeout', 'Web timeout is outside the supported range');
  const hooks: AgentHooks = {
    integrations: deps.integrations,
    graph: (ctx, ids, query, options) => operation(ctx, options.signal, async signal => {
      const scope = { tenantId: ctx.tenantId, knowledgeBaseIds: ids };
      const response = await deps.graph.search(ctx, ids, query, { signal, limit: 10 }); signal.throwIfAborted(); assert(ctx);
      if (!Array.isArray(response.items) || !Array.isArray(response.warnings) || !['connected', 'pending', 'model_not_configured'].includes(String(response.state))) fail('graph_result_invalid', 'Graph result is invalid', 502);
      const items = response.items as Json[], warnings = response.warnings as Json[];
      const rows: SearchHit[] = [], provenance = new Map<string, JsonObject[]>(), seen = new Set<string>();
      const add = (id: string, relation: string, source?: string) => {
        const hit = deps.index.hydrate(scope, id); if (!hit || seen.has(id)) return false;
        seen.add(id); rows.push({ ...hit, score: 1, match_sources: ['graph'] });
        provenance.set(id, [{ chunk_id: id, knowledge_id: hit.knowledge_id, knowledge_base_id: hit.knowledge_base_id, relation_type: relation, ...(source ? { source_chunk_id: source } : {}), metadata: hit.metadata, image_info: hit.image_info }]); return true;
      };
      for (const value of items.slice(0, 1000)) { const item = object(value); if (typeof item.chunk_id === 'string' && item.chunk_id.length <= 128 && rows.length < 10) add(item.chunk_id, 'entity'); }
      let extras = 0;
      for (const seed of [...rows]) {
        const chunk = deps.db.read('chunks', seed.chunk_id); if (!chunk) continue;
        for (const [field, relation] of [['relation_chunks', 'direct'], ['indirect_relation_chunks', 'indirect']] as const) {
          const linked = chunk[field]; if (!Array.isArray(linked)) continue;
          for (const id of linked.slice(0, 128)) if (extras < 3 && typeof id === 'string' && add(id, relation, seed.chunk_id)) extras++;
        }
      }
      const resolved = deps.index.resolveParents(scope, rows, 300), references: Json[] = [], parts: string[] = []; let remaining = 8000;
      for (const row of resolved) {
        const heading = `${row.knowledge_base_name} / ${row.knowledge_title}\n`, characters = Array.from(heading + row.content);
        if (characters.length > remaining) break;
        // Rehydrate after graph I/O and parent resolution, keeping citations source-authoritative.
        if (!deps.index.hydrate(scope, row.chunk_id)) continue;
        const sources = (row.matched_child_ids ?? [row.chunk_id]).flatMap(id => provenance.get(id) ?? []);
        references.push({ ...row, retrieval_path: 'graph', match_type: 'graph', source_tool: 'graph_search', graph_provenance: sources } as unknown as Json);
        parts.push(characters.join('')); remaining -= characters.length + 2;
      }
      return { output: parts.join('\n\n') || (response.state === 'connected' ? '没有匹配的图谱来源。' : '图谱检索需要配置。'), references, data: { state: response.state!, warnings } };
    }),
    webFetch: (ctx, raw, options) => operation(ctx, options.signal, async signal => {
      if (typeof raw !== 'string' || raw.length > 4096 || /[\s\\]/.test(raw)) fail('web_fetch_invalid_url', 'Web URL is invalid');
      let url: URL; try { url = new URL(raw); } catch { return fail('web_fetch_invalid_url', 'Web URL is invalid'); }
      if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) fail('web_fetch_invalid_url', 'Only HTTP URLs without credentials are supported');
      if (!Number.isSafeInteger(options.maxChars) || options.maxChars < 1 || options.maxChars > 16000) fail('web_fetch_invalid_limit', 'Web text limit is outside the supported range');
      url.hash = ''; const hostname = url.hostname.replace(/^\[|\]$/g, ''), trusted = allowedOrigins.has(url.origin);
      const controller = new AbortController(), abort = () => controller.abort(signal.reason), timer = setTimeout(() => controller.abort(), timeout);
      signal.addEventListener('abort', abort, { once: true }); if (signal.aborted) abort();
      try {
        // DNS is completed once, then the checked address is pinned into the actual socket lookup.
        const addresses = await Promise.race([lookup(hostname, { all: true, verbatim: true }), new Promise<never>((_, reject) => {
          const rejectAbort = () => reject(new AppError(499, 'web_fetch_cancelled', 'Web request was cancelled')); controller.signal.addEventListener('abort', rejectAbort, { once: true });
          if (controller.signal.aborted) rejectAbort();
        })]);
        controller.signal.throwIfAborted(); if (!addresses.length || !trusted && addresses.some(item => !publicAddress(item.address))) fail('web_fetch_private_target', 'Web target is not a public address');
        const address = addresses[0]!;
        const result = await new Promise<{ body: string; mime: string }>((resolve, reject) => {
          const request = (url.protocol === 'https:' ? httpsRequest : httpRequest)(url, {
            method: 'GET', agent: false, signal: controller.signal, headers: { accept: 'text/html,text/plain,application/json,application/xml;q=0.9', 'user-agent': 'Marlin-WebFetch/1' },
            lookup: (_hostname, _options, callback) => { if (typeof _options === 'object' && _options.all) callback(null, [address]); else callback(null, address.address, address.family); },
          }, response => {
            const rejectResponse = (code: string, message: string) => { response.destroy(); request.destroy(); reject(new AppError(502, code, message)); };
            if ((response.statusCode ?? 0) >= 300 && (response.statusCode ?? 0) < 400) return rejectResponse('web_fetch_redirect_rejected', 'Web redirects are not followed');
            if ((response.statusCode ?? 0) < 200 || (response.statusCode ?? 0) >= 300) return rejectResponse('web_fetch_http_error', 'Web service returned an unsuccessful status');
            if (Number(response.headers['content-length'] ?? 0) > 1048576) return rejectResponse('web_fetch_response_too_large', 'Web response exceeds the size limit');
            const mime = String(response.headers['content-type'] ?? '').split(';')[0]!.trim().toLowerCase();
            if (response.headers['content-encoding'] && response.headers['content-encoding'] !== 'identity' || !['text/html', 'text/plain', 'application/json', 'application/xml', 'text/xml', 'application/xhtml+xml', ''].includes(mime)) return rejectResponse('web_fetch_unsupported_content', 'Web response is not supported text');
            const chunks: Buffer[] = []; let size = 0;
            response.on('data', (chunk: Buffer) => { size += chunk.length; if (size > 1048576) rejectResponse('web_fetch_response_too_large', 'Web response exceeds the size limit'); else chunks.push(chunk); });
            response.on('error', () => reject(new AppError(502, 'web_fetch_connection_failed', 'Web request failed')));
            response.on('end', () => resolve({ body: Buffer.concat(chunks).toString('utf8'), mime }));
          });
          request.on('error', () => reject(new AppError(controller.signal.aborted ? 499 : 502, controller.signal.aborted ? 'web_fetch_cancelled' : 'web_fetch_connection_failed', 'Web request failed'))); request.end();
        });
        return { output: Array.from(result.mime.includes('html') ? htmlText(result.body) : result.body).slice(0, options.maxChars).join('') };
      } finally { clearTimeout(timer); signal.removeEventListener('abort', abort); }
    }),
    readSkill: (ctx, name) => operation(ctx, undefined, async signal => {
      const absent = (): ToolResult => ({ output: '', error: '业务技能不存在。', error_type: 'NOT_FOUND', retryable: false });
      if (!deps.skillsRoot || typeof name !== 'string' || !/^[a-zA-Z0-9_-]{1,128}$/.test(name)) return absent();
      let root: string; try { root = await realpath(deps.skillsRoot); } catch { return absent(); }
      const entries = await readdir(root, { withFileTypes: true });
      for (const entry of entries.slice(0, 1000)) {
        signal.throwIfAborted(); if (!entry.isDirectory() || !/^[a-zA-Z0-9_-]{1,128}$/.test(entry.name)) continue;
        try {
          const file = await realpath(join(root, entry.name, 'SKILL.md')); if (!inside(root, file)) continue;
          const info = await stat(file); if (!info.isFile() || info.size > 65536) continue;
          const text = new TextDecoder('utf-8', { fatal: true }).decode(await readFile(file));
          const front = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/.exec(text);
          const declared = front?.[1]?.match(/^name:\s*['"]?([a-zA-Z0-9_-]+)['"]?\s*$/m)?.[1] ?? entry.name;
          if (name === declared) return { output: text.slice(front?.[0].length ?? 0).trim() };
        } catch { /* Missing, invalid or escaped catalog entries remain unavailable. */ }
      }
      return absent();
    }),
  };
  return { hooks, close: async () => { closed = true; for (const controller of controllers) controller.abort(); await Promise.allSettled([...active]); } };
}
