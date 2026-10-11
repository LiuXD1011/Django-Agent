import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { CoreApplication } from '../src/application.js';
import { createCoreHttpServer } from '../src/adapters/http.js';

test('actual browser multipart chat attachment roundtrips bytes through authenticated opaque references and cleans only its own source', async () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-http-chat-upload-'));
  const app = new CoreApplication(root, { allowAutoSetup: true }), adapter = createCoreHttpServer(app, { port: 0 });
  const { origin } = await adapter.listen(), jar = new Map<string, string>();
  const request = async (path: string, method = 'GET', body?: BodyInit) => {
    const response = await fetch(origin + path, { method, body, headers: { Origin: origin, Cookie: [...jar].map(([k, v]) => `${k}=${v}`).join('; '), ...(method === 'GET' ? {} : { 'X-CSRFToken': jar.get('csrftoken')! }) } });
    for (const value of response.headers.getSetCookie()) { const [name, ...parts] = value.split(';')[0]!.split('='); jar.set(name!, parts.join('=')); }
    return response;
  };
  try {
    await request('/api/v1/auth/csrf');
    const init = await fetch(origin + '/api/v1/auth/auto-setup', { method: 'POST', headers: { Origin: origin, Cookie: `csrftoken=${jar.get('csrftoken')}`, 'X-CSRFToken': jar.get('csrftoken')!, 'Content-Type': 'application/json' }, body: JSON.stringify({ email: 'opaque-upload@example.invalid', password: 'opaque-upload-only-password' }) });
    assert.equal(init.status, 200);
    for (const value of init.headers.getSetCookie()) { const [name, ...parts] = value.split(';')[0]!.split('='); jar.set(name!, parts.join('=')); }
    const ctx = app.auth.authenticateAccess(jar.get('marlin_access')!);
    const session = app.chat.create(ctx, { title: '附件源文件', knowledge_base_ids: [] }), other = app.chat.create(ctx, { title: '其他会话', knowledge_base_ids: [] });
    const bytes = Uint8Array.from([0, 255, 192, 64, 13, 10]), form = new FormData(); form.set('file', new File([bytes], '中文 空格附件.bin', { type: 'application/octet-stream' }));
    const upload = await request(`/api/v1/sessions/${session.id}/uploads`, 'POST', form);
    assert.equal(upload.status, 200); const data = (await upload.json() as any).data;
    assert.equal(data.file_name, '中文 空格附件.bin'); assert.equal(data.file_size, bytes.length);
    assert.equal(JSON.stringify(data).includes(root), false);
    const path = `/api/v1/sessions/${session.id}/uploads/${data.upload_id}`;
    const downloaded = await request(path); assert.equal(downloaded.status, 200);
    assert.equal(downloaded.headers.get('content-type'), 'application/octet-stream');
    assert.deepEqual(new Uint8Array(await downloaded.arrayBuffer()), bytes);
    assert.equal(data.sha256, createHash('sha256').update(bytes).digest('hex'));
    assert.equal((await request(`/api/v1/sessions/${other.id}/uploads/${data.upload_id}`)).status, 404);
    const outsider = app.auth.register({ email: 'outsider-upload@example.invalid', password: 'outsider-upload-password' });
    const denied = await fetch(origin + path, { headers: { Authorization: `Bearer ${outsider.credentials.access}` } }); assert.equal(denied.status, 404);
    assert.equal((await request(`/api/v1/sessions/${session.id}`, 'DELETE')).status, 200);
    assert.equal((await request(path)).status, 404);
    assert.equal(app.database.get('select value from desktop_meta where key=?', `chat.upload:${data.upload_id}`), undefined);
    assert.equal((await request(`/api/v1/sessions/${other.id}`)).status, 200);
  } finally { await adapter.close(); await app.close(); rmSync(root, { recursive: true, force: true }); }
});
