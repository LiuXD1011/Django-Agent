import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { CoreBinary, type PrivateBinding } from '../src/application.js';
import type { CoreRequest, HttpMethod, JsonObject } from '../src/contracts.js';
import { CoreOwner } from '../src/runtime/owner-client.js';
import { openNativeDatabase } from '../src/storage/database.js';

const request = (method: HttpMethod, path: string, body?: JsonObject): CoreRequest => ({ protocol: 1, id: randomUUID(), method, path, ...(body ? { body } : {}) });
const data = (response: { body: unknown }): any => (response.body as any).data;

test('HTTP private facade owns encrypted persistent CSRF and reauthorizes scoped uploads after revocation', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'marlin-owner-http ')); let owner: CoreOwner | undefined;
  try {
    owner = await CoreOwner.start({ dataRoot: directory, allowAutoSetup: true });
    const http = await owner.httpTransport(); assert.equal(await owner.httpTransport(), http);
    assert.equal(http.serviceId, owner.serviceId); assert.match(http.csrfKey, /^[A-Za-z0-9_-]{43}$/);
    const setup = await http.dispatch(request('POST', '/api/v1/auth/auto-setup', { password: 'owner-http-test-password' }), { transport: 'http' });
    assert.equal(setup.response.status, 200); assert.ok(setup.authChange?.issue);
    assert.equal(Object.hasOwn(data(setup.response), 'credentials'), false);
    const credentials = setup.authChange.issue.credentials;
    const binding: PrivateBinding = { transport: 'http', access: credentials.access, refresh: credentials.refresh };
    const kb = await http.dispatch(request('POST', '/api/v1/knowledge-bases', { name: 'HTTP upload scope' }), binding);
    assert.equal(kb.response.status, 200); const kbId = String(data(kb.response).id);
    const session = await http.dispatch(request('POST', '/api/v1/sessions', { title: '私有上传', knowledge_base_ids: [] }), binding);
    const sessionId = String(data(session.response).id);
    await assert.rejects(http.preflightUpload({ transport: 'http' }, 'document', kbId), { status: 401 });
    await assert.rejects(http.preflightUpload(binding, 'document', 'missing'), { status: 404 });
    await assert.rejects(http.preflightUpload({ ...binding, selectedTenant: 'outside-tenant' }, 'chat', sessionId), { status: 401 });
    await http.preflightUpload(binding, 'document', kbId); await http.preflightUpload(binding, 'chat', sessionId);
    const other = await http.dispatch(request('POST', '/api/v1/auth/register', { email: 'owner-outside@example.invalid', password: 'owner-outside-test-password' }), { transport: 'http' });
    const outsider: PrivateBinding = { transport: 'http', access: other.authChange!.issue!.credentials.access };
    await assert.rejects(http.preflightUpload(outsider, 'document', kbId), { status: 404 });
    await assert.rejects(http.preflightUpload(outsider, 'chat', sessionId), { status: 404 });
    assert.equal((await http.dispatch(request('POST', '/api/v1/auth/logout'), binding)).response.status, 200);
    assert.equal((await http.dispatch(request('POST', `/api/v1/sessions/${sessionId}/uploads`), { ...binding, upload: { name: 'rejected.txt', bytes: new Uint8Array([65]) } })).response.status, 401);
    await owner.close();
    // The only additional connection opens read-only after the owner exits; no second writer.
    const sqlite = openNativeDatabase(join(directory, 'marlin.sqlite3'), { readonly: true, fileMustExist: true });
    try {
      const stored = (sqlite.prepare("SELECT value FROM desktop_meta WHERE key='http.csrf-secret'").get() as { value: string }).value;
      assert.match(stored, /enc:v1:/); assert.equal(stored.includes(http.csrfKey), false);
    } finally { sqlite.close(); }
    owner = await CoreOwner.start({ dataRoot: directory, allowAutoSetup: true });
    assert.equal((await owner.httpTransport()).csrfKey, http.csrfKey);
  } finally { await owner?.close(); await rm(directory, { recursive: true, force: true }); }
});

test('actual managed binary upload preserves exact Uint8Array views and download hashes across owner transport', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'marlin-owner-bytes ')); let owner: CoreOwner | undefined;
  try {
    owner = await CoreOwner.start({ dataRoot: directory, allowAutoSetup: true });
    assert.equal((await owner.invoke(request('POST', '/api/v1/auth/auto-setup', { password: 'owner-binary-test-password' }))).status, 200);
    const session = await owner.invoke(request('POST', '/api/v1/sessions', { title: '二进制精确字节', knowledge_base_ids: [] }));
    const sessionId = String(data(session).id);
    const backing = Buffer.concat([Buffer.from([17]), Buffer.from('中文\0\r\n😀'), Buffer.from(Array.from({ length: 256 }, (_, i) => i)), Buffer.from([19])]);
    const view = backing.subarray(1, backing.length - 1), expected = Uint8Array.from(view);
    const upload = await owner.invoke(request('POST', `/api/v1/sessions/${sessionId}/uploads`), { upload: { name: '中文 bytes.dat', bytes: view } });
    assert.equal(upload.status, 200); assert.deepEqual(view, Buffer.from(expected));
    const filePath = `/api/v1/sessions/${sessionId}/uploads/${data(upload).upload_id}`;
    const result = await owner.invoke(request('GET', filePath)); assert.equal(result.status, 200); assert.ok(result.binary);
    assert.deepEqual(result.binary.bytes, expected); assert.equal(result.binary.name, '中文 bytes.dat');
    assert.equal(result.binary.sha256, createHash('sha256').update(expected).digest('hex'));
    const http = await owner.httpTransport();
    const login = await http.dispatch(request('POST', '/api/v1/auth/login', { login: 'admin', password: 'owner-binary-test-password' }), { transport: 'http' });
    const download = await http.dispatch(request('GET', filePath), { transport: 'http', access: login.authChange!.issue!.credentials.access });
    assert.ok(download.binary instanceof CoreBinary); assert.deepEqual(download.binary.bytes, expected);
    assert.equal((await owner.invoke(request('GET', filePath), { tenantId: 'outside' })).status, 401);
  } finally { await owner?.close(); await rm(directory, { recursive: true, force: true }); }
});

test('private integration plans and cookies stay outside ordinary renderer invoke responses', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'marlin-owner-langfuse ')); let owner: CoreOwner | undefined;
  try {
    owner = await CoreOwner.start({ dataRoot: directory, allowAutoSetup: true });
    assert.equal((await owner.invoke(request('POST', '/api/v1/auth/auto-setup', { password: 'owner-langfuse-test-password' }))).status, 200);
    assert.equal((await owner.invoke(request('PUT', '/api/v1/system/config/langfuse', { base_url: 'http://127.0.0.1:3000', ui_base_url: 'http://127.0.0.1:3000', ui_project_id: 'isolated-project', enabled: false }))).status, 200);
    const prepared = await owner.nativeLangfuse({ id: randomUUID(), action: 'prepare' });
    assert.equal(prepared.response.status, 200); assert.equal(prepared.plan?.mode, 'manual');
    assert.equal(Object.hasOwn(data(prepared.response), 'ticket'), false);
    const forged = await owner.nativeLangfuse({ id: randomUUID(), action: 'validate', ticket: randomUUID() }); assert.equal(forged.response.status, 409);
    const session = await owner.nativeLangfuse({ id: randomUUID(), action: 'session', ticket: prepared.plan!.ticket });
    assert.equal(session.response.status, 200); assert.deepEqual(session.cookies, []);
    const ordinary = await owner.invoke(request('POST', '/api/v1/observability/langfuse/session/clear'));
    assert.equal(ordinary.status, 501); assert.equal(Object.hasOwn(ordinary, 'cookies'), false);
    const http = await owner.httpTransport();
    const login = await http.dispatch(request('POST', '/api/v1/auth/login', { login: 'admin', password: 'owner-langfuse-test-password' }), { transport: 'http' });
    const cleared = await http.dispatch(request('POST', '/api/v1/observability/langfuse/session/clear'), {
      transport: 'http', access: login.authChange!.issue!.credentials.access,
      localSession: { requestOrigin: 'http://127.0.0.1:8000', remoteAddress: '127.0.0.1', existingCookies: { 'next-auth.session-token': 'synthetic-private-cookie' } },
    });
    assert.equal(cleared.response.status, 200); assert.deepEqual(cleared.cookies, [{ name: 'next-auth.session-token', value: '', maxAge: 0, secure: false }]);
    assert.equal(JSON.stringify(cleared.response).includes('next-auth.session-token'), false);
    await owner.startupLog('INFO', 'owner.private_test');
    const log = await readFile(join(directory, '.logs/core.jsonl'), 'utf8');
    assert.ok(log.includes('owner.private_test')); assert.equal(log.includes('synthetic-private-cookie'), false);
    await assert.rejects(owner.startupLog('INFO', 'synthetic-private-cookie'), { code: 'invalid_log_event' });
  } finally { await owner?.close(); await rm(directory, { recursive: true, force: true }); }
});

test('owner rejects uncloneable configuration and exposes safe failures without starting a second application', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'marlin-owner-invalid '));
  try {
    for (const config of [
      { dataRoot: directory, evaluation: { answer: () => ({}) } },
      { dataRoot: directory, evaluation: { answer: undefined } },
      { dataRoot: directory, parser: { callback: () => {} } },
      { dataRoot: directory, unknown: 'synthetic-private-detail' },
      { dataRoot: directory, evaluation: { publicDatasetSpecs: new Map() } },
    ]) await assert.rejects(CoreOwner.start(config as any), { code: 'invalid_owner_config' });
    const notDirectory = join(directory, 'synthetic-private-path.txt'); await writeFile(notDirectory, 'private-not-directory');
    await assert.rejects(CoreOwner.start({ dataRoot: notDirectory }), error => {
      assert.equal((error as any).code, 'internal_error'); assert.equal((error as Error).message.includes(notDirectory), false); return true;
    });
    const owner = await CoreOwner.start({ dataRoot: directory });
    try {
      await assert.rejects(owner.invoke({ ...request('GET', '/api/v1/capabilities'), callable: () => {} }), { code: 'owner_input_uncloneable' });
      assert.equal((await owner.invoke({ ...request('GET', '/api/v1/capabilities'), path: 'https://outside.invalid' })).status, 400);
      const cancelled = new AbortController(), reason = new Error('pre-cancelled private request'); cancelled.abort(reason);
      await assert.rejects(owner.invoke(request('GET', '/api/v1/capabilities'), {}, cancelled.signal), error => error === reason);
      assert.equal((await owner.invoke(request('GET', '/api/v1/capabilities'))).status, 200);
    } finally { await owner.close(); }
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test('actual owner environment preserves existing startup overrides without exposing inherited values in logs', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'marlin-owner-startup ')); let owner: CoreOwner | undefined;
  const previous = process.env.MARLIN_LOG_LEVEL; process.env.MARLIN_LOG_LEVEL = 'ERROR';
  try {
    owner = await CoreOwner.start({ dataRoot: directory, allowAutoSetup: true });
    if (previous === undefined) delete process.env.MARLIN_LOG_LEVEL; else process.env.MARLIN_LOG_LEVEL = previous;
    await owner.startupLog('INFO', 'owner.suppressed_test'); await owner.startupLog('ERROR', 'owner.visible_test');
    const log = await readFile(join(directory, '.logs/core.jsonl'), 'utf8');
    assert.equal(log.includes('owner.suppressed_test'), false); assert.equal(log.includes('owner.visible_test'), true);
  } finally {
    if (previous === undefined) delete process.env.MARLIN_LOG_LEVEL; else process.env.MARLIN_LOG_LEVEL = previous;
    await owner?.close(); await rm(directory, { recursive: true, force: true });
  }
});
