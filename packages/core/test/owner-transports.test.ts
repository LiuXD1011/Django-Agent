import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { request as httpRequest } from 'node:http';
import { setTimeout as delay } from 'node:timers/promises';
import { test } from 'node:test';
import { CoreOwner } from '../src/runtime/owner-client.js';
import { createCoreHttpServer } from '../src/adapters/http.js';

async function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'marlin-owner-transport-'));
  let owner = await CoreOwner.start({ dataRoot: root, allowAutoSetup: true, parser: {
    pythonExecutable: process.env.MARLIN_PARSER_PYTHON ?? '/tmp/marlin-parser-isolation-20261010/bin/python',
    workerPath: resolve('../../workers/document/worker.py'),
  } });
  let adapter: ReturnType<typeof createCoreHttpServer> | undefined;
  const jar = new Map<string, string>();
  let origin = '';
  const openHttp = async () => {
    const transport = await owner.httpTransport();
    assert.doesNotThrow(() => { adapter = createCoreHttpServer(transport, { port: 0, maxUploadBytes: 4096 }); }, 'HTTP must accept the trusted owner facade without opening a coordinator database');
    origin = (await adapter!.listen()).origin;
  };
  try { await openHttp(); }
  catch (error) { await owner.close(); rmSync(root, { recursive: true, force: true }); throw error; }
  const request = async (path: string, method = 'GET', body?: unknown, headers: Record<string, string> = {}, authenticated = true) => {
    const response = await fetch(origin + path, { method, headers: {
      Origin: origin,
      ...(authenticated ? { Cookie: [...jar].map(([key, value]) => `${key}=${value}`).join('; ') } : {}),
      ...(method !== 'GET' && jar.has('csrftoken') ? { 'X-CSRFToken': jar.get('csrftoken')! } : {}),
      ...(body !== undefined && !(body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}), ...headers,
    }, body: body instanceof FormData ? body : body === undefined ? undefined : JSON.stringify(body) });
    for (const cookie of response.headers.getSetCookie()) {
      const pair = cookie.split(';')[0]!, index = pair.indexOf('=');
      if (pair.slice(index + 1)) jar.set(pair.slice(0, index), pair.slice(index + 1));
      else jar.delete(pair.slice(0, index));
    }
    return response;
  };
  const setup = async () => {
    assert.equal((await request('/api/v1/auth/csrf')).status, 200);
    const response = await request('/api/v1/auth/auto-setup', 'POST', { email: 'owner-http@example.invalid', password: 'owner-isolated-http-password' });
    assert.equal(response.status, 200);
    return response;
  };
  return { jar, request, setup, origin: () => origin, serviceId: () => owner.serviceId,
    async reopen() { await adapter!.close(); await owner.close(); owner = await CoreOwner.start({ dataRoot: root, allowAutoSetup: true }); await openHttp(); },
    async close() { try { await adapter!.close(); } finally { await owner.close(); rmSync(root, { recursive: true, force: true }); } },
  };
}

test('owner HTTP transport preserves signed CSRF, private cookies, identity and authoritative logout across restart', async () => {
  const f = await fixture();
  try {
    const response = await f.setup(), body = await response.json() as any;
    assert.ok(response.headers.getSetCookie().some(value => value.startsWith('marlin_access=') && value.includes('HttpOnly')));
    for (const forbidden of ['credentials', 'password', 'token', 'refresh_token', 'api_key']) assert.equal(Object.hasOwn(body.data, forbidden), false);
    const userId = body.data.user.id, identity = f.serviceId(), csrf = f.jar.get('csrftoken');
    assert.equal((await f.request('/api/v1/auth/me')).status, 200);
    const hostile = await new Promise<number>(resolveStatus => {
      const req = httpRequest(f.origin() + '/health', { headers: { Host: 'attacker.invalid' } }, result => { result.resume(); resolveStatus(result.statusCode!); }); req.end();
    });
    assert.equal(hostile, 403);
    assert.equal((await f.request('/api/v1/knowledge-bases', 'POST', { name: 'denied' }, { 'X-CSRFToken': 'forged' })).status, 403);
    assert.equal((await f.request('/api/v1/knowledge-bases', 'POST', { name: 'denied' }, { Origin: 'https://attacker.invalid' })).status, 403);
    await f.reopen();
    assert.equal(f.serviceId(), identity);
    assert.equal((await (await f.request('/api/v1/auth/me')).json() as any).data.user.id, userId);
    assert.equal((await (await f.request('/api/v1/auth/csrf')).json() as any).data.csrf_token, csrf);
    assert.equal((await f.request('/api/v1/knowledge-bases', 'POST', { name: '重启后真实写入' })).status, 200);
    assert.equal((await f.request('/api/v1/auth/logout', 'POST', {})).status, 200);
    assert.equal((await f.request('/api/v1/auth/me')).status, 401);
  } finally { await f.close(); }
});

test('owner HTTP multipart authenticates scope before decoding and round-trips real Python parsed source bytes', async () => {
  const f = await fixture();
  try {
    await f.setup();
    const kb = await (await f.request('/api/v1/knowledge-bases', 'POST', { name: 'owner 上传隔离' })).json() as any;
    const route = `/api/v1/knowledge-bases/${kb.data.id}/knowledge/file`;
    const original = '# owner 资料\n\n预算为456780元。\n';
    const form = () => { const value = new FormData(); value.append('file', new Blob([original]), 'owner 中文 空格.md'); value.append('process_config', JSON.stringify({ chunk_size: 256, enable_parent_child: false, enable_graph_extract: false })); return value; };
    const uploaded = await f.request(route, 'POST', form()); assert.equal(uploaded.status, 200);
    const documentId = (await uploaded.json() as any).data.knowledge.id;
    let chunks: any;
    const deadline = Date.now() + 15000;
    do { chunks = await (await f.request(`/api/v1/chunks/${documentId}`)).json() as any; if (chunks.data.items.length) break; await delay(20); } while (Date.now() < deadline);
    assert.ok(chunks.data.items.some((item: any) => item.content.includes('456780')), 'owned Python and nested chunk worker must publish actual text');
    const download = await f.request(`/api/v1/knowledge/${documentId}/download`);
    assert.equal(download.status, 200); assert.equal(await download.text(), original);
    assert.match(download.headers.get('content-disposition')!, /filename\*=UTF-8/);
    assert.equal((await (await f.request(route, 'POST', form())).json() as any).data.deduplicated, true);
    assert.equal((await f.request(route, 'POST', form(), { 'X-CSRFToken': 'forged' })).status, 403);
    assert.equal((await f.request('/api/v1/auth/register', 'POST', { email: 'other-owner-http@example.invalid', password: 'other-owner-isolated-password' })).status, 200);
    assert.equal((await f.request(route, 'POST', {}, { 'Content-Type': 'multipart/form-data; boundary=broken' })).status, 404, 'foreign scope must fail before malformed multipart is read');
    assert.equal((await f.request(`/api/v1/knowledge/${documentId}/download`)).status, 404);
  } finally { await f.close(); }
});
