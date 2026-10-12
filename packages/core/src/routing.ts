import type { CoreRequest, Json, JsonObject } from './contracts.js';
import { AppError } from './errors.js';

export function coreRequestUrl(path: string): URL {
  const url = new URL(path, 'http://core.invalid');
  if (url.origin !== 'http://core.invalid' || !url.pathname.startsWith('/api/v1/')) throw new AppError(400, 'invalid_path', '请求路径不正确。');
  return url;
}

export function routePattern(path: string): { matcher: RegExp; names: string[] } {
  const names: string[] = [];
  const matcher = path.split('/').map(part => {
    if (!part.startsWith(':')) return part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const wildcard = part.endsWith('*');
    const name = part.slice(1, wildcard ? -1 : undefined);
    if (!/^[a-zA-Z][a-zA-Z0-9_]*$/.test(name)) throw new Error('Invalid core route');
    names.push(name);
    return wildcard ? '(.+)' : '([^/]+)';
  }).join('/');
  return { matcher: new RegExp(`^${matcher}$`), names };
}

export function requestObject(value: Json | undefined): JsonObject {
  if (value === undefined) return {};
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new AppError(400, 'invalid_body', '请求正文必须是 JSON 对象。');
  return value;
}

/** Use the same normalized pathname as dispatch, including query-bearing auth requests. */
export function isSessionChange(request: CoreRequest): boolean {
  return request.method === 'POST' && /^\/api\/v1\/auth\/(?:login|register|auto-setup|refresh|logout|logout-all|change-password)$/.test(coreRequestUrl(request.path).pathname);
}

/** Conservative trusted reply fence; it does not grant or cache authorization. */
export function isAuthorityChange(request: CoreRequest): boolean {
  if (isSessionChange(request)) return true;
  const path = coreRequestUrl(request.path).pathname;
  if (request.method === 'DELETE' && /^\/api\/v1\/auth\/devices\/[^/]+$/.test(path)) return true;
  if (request.method === 'PUT' && path === '/api/v1/auth/me/preferences') return true;
  if (request.method === 'POST' && path === '/api/v1/auth/switch-tenant') return true;
  if (request.method === 'POST' && path === '/api/v1/tenants') return true;
  if (['PUT', 'PATCH', 'DELETE'].includes(request.method) && /^\/api\/v1\/tenants\/[^/]+(?:\/members\/[^/]+)?$/.test(path)) return true;
  return request.method === 'POST' && /^\/api\/v1\/tenants\/[^/]+\/(?:members|api-key)$/.test(path);
}
