'use strict';
const { readFile, realpath } = require('node:fs/promises');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { isLocal } = require('./runtime.cjs');
const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.json': 'application/json', '.webmanifest': 'application/manifest+json', '.svg': 'image/svg+xml', '.png': 'image/png',
  '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.ico': 'image/x-icon', '.woff': 'font/woff', '.woff2': 'font/woff2', '.ttf': 'font/ttf' };
const policy = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https: http:; font-src 'self' data:; connect-src 'self'; worker-src 'self'; object-src 'none'; frame-src 'none'; base-uri 'none'";
function createProtocolHandler(root, runtime, origin, fetchRemote) {
  const rootPath = path.resolve(root);
  const error = status => new Response('资源不可用', { status, headers: { 'Content-Type': 'text/plain; charset=utf-8', 'X-Content-Type-Options': 'nosniff' } });
  return async request => {
    if (!isLocal(request.url, origin)) {
      if (fetchRemote && /^https:\/\//.test(request.url)) return fetchRemote(request);
      return error(403);
    }
    if (request.initiatorOrigin !== undefined && request.initiatorOrigin !== origin) return error(403);
    if (!['GET', 'HEAD'].includes(request.method)) return error(405);
    const url = new URL(request.url);
    if (url.pathname.startsWith('/api/v1/')) {
      if (!runtime) return error(503);
      try {
        const tenant = request.headers?.get('X-Tenant-ID'), result = await runtime.invoke({ protocol: 1, id: randomUUID(), method: 'GET', path: url.pathname + url.search }, tenant ? { tenantId: tenant } : {});
        const binary = result.binary;
        return new Response(request.method === 'HEAD' ? null : binary ? binary.bytes : JSON.stringify(result.body), { status: result.status, headers: {
          'Content-Type': binary ? binary.mimeType : 'application/json; charset=utf-8', 'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store',
          ...(binary ? { 'Content-Disposition': `inline; filename*=UTF-8''${encodeURIComponent(binary.name)}`, 'X-Content-SHA256': binary.sha256 } : {}),
        } });
      } catch { return error(503); }
    }
    let pathname;
    try { pathname = decodeURIComponent(url.pathname); } catch { return error(400); }
    if (/[\x00-\x1f\x7f\\]/.test(pathname) || pathname.split('/').some(part => part === '..' || part === '.')) return error(400);
    const spa = pathname === '/' || pathname === '/login' || pathname.startsWith('/platform/') && !path.extname(pathname);
    const target = path.resolve(rootPath, spa ? 'index.html' : '.' + pathname);
    const relative = path.relative(rootPath, target);
    if (!relative || relative.startsWith('..' + path.sep) || relative === '..' || path.isAbsolute(relative)) return error(400);
    try {
      const actualRoot = await realpath(rootPath), actualFile = await realpath(target), actualRelative = path.relative(actualRoot, actualFile);
      if (actualRelative === '..' || actualRelative.startsWith('..' + path.sep) || path.isAbsolute(actualRelative)) return error(403);
      return new Response(request.method === 'HEAD' ? null : await readFile(actualFile), { headers: {
        'Content-Type': types[path.extname(actualFile)] || 'application/octet-stream', 'Content-Security-Policy': policy,
        'X-Content-Type-Options': 'nosniff', 'Cache-Control': spa || pathname === '/sw.js' ? 'no-store' : 'public, max-age=3600',
      } });
    } catch { return error(404); }
  };
}
module.exports = { createProtocolHandler };
