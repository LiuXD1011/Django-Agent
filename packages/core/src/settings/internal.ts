import type { Json, JsonObject } from '../contracts.js';
import { AppError } from '../errors.js';
import { isSecretKey, publicParameters } from '../storage/credentials.js';

export function fail(status: number, code: string, message: string): never { throw new AppError(status, code, message); }
export function object(value: unknown): JsonObject {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.getPrototypeOf(value) !== Object.prototype) fail(400, 'invalid_configuration', 'Configuration must be an object');
  return value as JsonObject;
}
export function canonical(value: unknown = 'KnowledgeQA'): string {
  const text = String(value || 'KnowledgeQA').trim().toLowerCase();
  if (['knowledgeqa', 'knowledge_qa', 'chat', 'summary', 'title', 'question', 'extract'].includes(text)) return 'KnowledgeQA';
  if (text === 'embedding') return 'Embedding';
  if (text === 'rerank') return 'Rerank';
  if (['vision', 'vlm', 'vllm'].includes(text)) return 'VLLM';
  return fail(400, 'unsupported_model_type', 'Unsupported model type');
}
export const groups: Record<string, string> = { KnowledgeQA: 'chat', Embedding: 'embedding', Rerank: 'rerank', VLLM: 'vlm' };
/** Preserve unsupported imported rows for public inspection without making them callable. */
export function storedType(value: unknown): string { try { return canonical(value); } catch { return String(value || ''); } }
export function secretFields(value: JsonObject): Record<string, { configured: boolean }> {
  const result: Record<string, { configured: boolean }> = {};
  function visit(item: Json, path = ''): void {
    if (!item || typeof item !== 'object') return;
    for (const [key, val] of Object.entries(item)) {
      const name = path ? `${path}.${key}` : key;
      if (isSecretKey(key)) result[name] = { configured: Boolean(val) }; else visit(val, name);
    }
  }
  visit(value); return result;
}
export function publicValue(value: JsonObject): JsonObject { return publicParameters(value); }
export function clearSecret(value: JsonObject, path: string): JsonObject {
  const names = path.split('.'), leaf = names.pop()!;
  if (!isSecretKey(leaf) || names.some(name => ['__proto__', 'constructor', 'prototype'].includes(name))) fail(400, 'invalid_credential', 'Unknown credential field');
  const result = structuredClone(value); let cursor = result;
  for (const name of names) {
    if (!Object.hasOwn(cursor, name) || !cursor[name] || typeof cursor[name] !== 'object' || Array.isArray(cursor[name])) fail(400, 'invalid_credential', 'Unknown credential field');
    cursor = cursor[name] as JsonObject;
  }
  cursor[leaf] = '';
  if (leaf === 'api_key') { delete cursor.apiKey; delete cursor.apikey; }
  return result;
}
export function merge(existing: JsonObject, incoming: JsonObject): JsonObject {
  const result = structuredClone(existing);
  for (let [key, value] of Object.entries(incoming)) {
    if (['apiKey', 'apikey'].includes(key)) key = 'api_key';
    if (isSecretKey(key)) {
      if (value === null || value === '' || value === '******') continue;
      if (typeof value !== 'string' || value.startsWith('enc:v1:') || value.length > 16384) fail(400, 'invalid_credential', 'Invalid credential value');
    }
    if (value && typeof value === 'object' && !Array.isArray(value)) result[key] = merge(result[key] && typeof result[key] === 'object' && !Array.isArray(result[key]) ? result[key] as JsonObject : {}, value);
    else if (Array.isArray(value)) result[key] = value.map(item => item && typeof item === 'object' && !Array.isArray(item) ? merge({}, item) : item);
    else result[key] = value;
  }
  // Validate the complete JSON tree before any database mutation.
  function validate(value: Json): void {
    if (typeof value === 'number' && !Number.isFinite(value)) fail(400, 'invalid_configuration', 'Configuration contains an invalid number');
    if (value === undefined || typeof value === 'function' || typeof value === 'bigint') fail(400, 'invalid_configuration', 'Configuration contains an invalid value');
    if (value && typeof value === 'object') for (const item of Object.values(value)) validate(item);
  }
  validate(result); return result;
}
export function endpoint(value: unknown, neo4j = false): string {
  if (typeof value !== 'string' || !value || value.includes('\\') || /\s/.test(value)) fail(400, 'invalid_endpoint', 'Invalid service endpoint');
  let url: URL;
  try { url = new URL(value); } catch { return fail(400, 'invalid_endpoint', 'Invalid service endpoint'); }
  if (!(neo4j ? ['bolt:', 'bolt+s:', 'bolt+ssc:', 'neo4j:', 'neo4j+s:', 'neo4j+ssc:'] : ['http:', 'https:']).includes(url.protocol) || !url.hostname || url.username || url.password || url.search || url.hash) fail(400, 'invalid_endpoint', 'Service endpoint cannot contain credentials, query or fragment');
  return url.origin === 'null' ? `${url.protocol}//${url.host}` : url.origin;
}
export function protectEndpoint(previous: JsonObject, incoming: JsonObject, next: JsonObject, urlKey = 'base_url', secretNames?: string[], neo4j = false): void {
  const oldUrl = previous[urlKey] ?? (urlKey === 'base_url' ? previous.baseURL : undefined);
  const newUrl = next[urlKey] ?? (urlKey === 'base_url' ? next.baseURL : undefined);
  if (!newUrl) return;
  const origin = endpoint(newUrl, neo4j);
  if (!oldUrl || endpoint(oldUrl, neo4j) === origin) return;
  const names = secretNames ?? Object.keys(secretFields(previous));
  function at(value: JsonObject, path: string): Json | undefined {
    let cursor: Json | undefined = value;
    for (const key of path.split('.')) cursor = cursor && typeof cursor === 'object' ? (cursor as JsonObject)[key] : undefined;
    return cursor;
  }
  for (const name of names) {
    if (!at(previous, name)) continue;
    const replacement = at(incoming, name) ?? (name === 'api_key' ? incoming.apiKey ?? incoming.apikey : undefined);
    if (typeof replacement !== 'string' || !replacement || replacement === '******' || replacement.startsWith('enc:v1:')) fail(400, 'credential_endpoint_changed', 'Changing the service host requires new credentials; clear the saved credentials first for an anonymous service');
  }
}
