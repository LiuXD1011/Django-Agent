import type { JsonObject } from '../contracts.js';
import { type CallScope, endpoint, fail, responseJSON, restrictedFetch } from './network.js';

export interface SearchResult { title: string; url: string; snippet: string; provider: string }
const text = (value: unknown, limit: number): string => typeof value === 'string' ? value.slice(0, limit) : '';
function source(value: unknown): string { try { const url = new URL(String(value)); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.toString().slice(0, 4096) : ''; } catch { return ''; } }
function htmlText(value: string): string {
  return value.replace(/<[^>]*>/g, '').replace(/&(?:amp|lt|gt|quot|apos|#39|#x[0-9a-f]+|#\d+);/gi, entity => {
    const named: Record<string, string> = { '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&apos;': "'", '&#39;': "'" };
    if (named[entity]) return named[entity]!;
    const number = entity.startsWith('&#x') ? parseInt(entity.slice(3, -1), 16) : Number(entity.slice(2, -1));
    return Number.isInteger(number) && number >= 0 && number <= 0x10ffff ? String.fromCodePoint(number) : '';
  }).trim();
}
export async function search(scope: CallScope, config: JsonObject, query: string): Promise<{ state: string; provider: string; results: SearchResult[] }> {
  if (typeof query !== 'string' || !query.trim() || query.length > 2048) return fail(400, 'integration_invalid_query', 'Search query must contain between 1 and 2048 characters');
  const provider = String(config.provider || 'duckduckgo').toLowerCase();
  const defaults: Record<string, string> = { duckduckgo: 'https://html.duckduckgo.com/html/' };
  if (!['duckduckgo', 'searxng', 'google', 'bing'].includes(provider)) return fail(400, 'integration_unsupported_provider', 'Unsupported search provider');
  // Bing Search's former public endpoint was retired; retain explicitly configured compatible endpoints only.
  const configured = config.url || config.base_url || defaults[provider];
  if (!configured) return { state: 'not_configured', provider, results: [] };
  const url = endpoint(configured), headers: Record<string, string> = { accept: provider === 'duckduckgo' ? 'text/html' : 'application/json' };
  if (provider === 'duckduckgo') headers['user-agent'] = 'Mozilla/5.0';
  const key = config.api_key || config.apiKey || config.token;
  if (provider === 'google' && (!key || !config.cx)) return { state: 'not_configured', provider, results: [] };
  if (provider === 'bing' && !key) return { state: 'not_configured', provider, results: [] };
  url.searchParams.set('q', query);
  if (provider === 'searxng') { url.searchParams.set('format', 'json'); if (key) headers.authorization = `Bearer ${key}`; }
  if (provider === 'google') { url.searchParams.set('key', String(key)); url.searchParams.set('cx', String(config.cx)); url.searchParams.set('num', '5'); }
  if (provider === 'bing') { headers['Ocp-Apim-Subscription-Key'] = String(key); url.searchParams.set('count', '5'); }
  const response = await restrictedFetch(scope, url.origin)(url, { headers });
  let items: unknown[];
  if (provider === 'duckduckgo') {
    if (!response.ok) { await response.body?.cancel(); return fail(502, 'integration_connection_failed', 'Search provider request failed'); }
    const html = await response.text();
    const matches = [...html.matchAll(/<a\b([^>]*\bclass=["'][^"']*\bresult__a\b[^"']*["'][^>]*)>([\s\S]*?)<\/a>[\s\S]*?<[^>]+class=["'][^"']*\bresult__snippet\b[^"']*["'][^>]*>([\s\S]*?)<\/(?:a|span|div)>/gi)];
    if (!matches.length && !/class=["'][^"']*no-results|No results found/i.test(html)) return fail(502, 'integration_invalid_response', 'Search provider returned an unsupported or challenge page');
    items = matches.map(match => {
      const href = match[1]!.match(/\bhref=["']([^"']*)["']/i)?.[1] || '';
      let url: URL; try { url = new URL(htmlText(href), 'https://duckduckgo.com'); } catch { return {}; }
      return { title: htmlText(match[2]!), url: url.searchParams.get('uddg') || url.toString(), content: htmlText(match[3]!) };
    });
  } else {
    const raw = await responseJSON(response) as any;
    if (provider === 'searxng') items = raw?.results;
    else if (provider === 'google') { if (!raw || typeof raw !== 'object' || raw.error || (!Array.isArray(raw.items) && typeof raw.searchInformation?.totalResults !== 'string')) return fail(502, 'integration_invalid_response', 'Search provider returned an invalid response'); items = raw.items || []; }
    else items = raw?.webPages?.value;
    if (!Array.isArray(items)) return fail(502, 'integration_invalid_response', 'Search provider returned an invalid response');
  }
  const results: SearchResult[] = [];
  for (const item of items.slice(0, 100)) {
    if (!item || typeof item !== 'object') continue;
    const row = item as any, url = source(row.url || row.link);
    if (!url) continue;
    results.push({ title: text(row.title || row.name, 512), url, snippet: text(row.content || row.snippet, 2000), provider });
    if (results.length === 5) break;
  }
  return { state: 'connected', provider, results };
}
