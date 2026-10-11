import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { test } from 'node:test';
import { CoreApplication } from '../src/application.js';
import { createCoreHttpServer } from '../src/adapters/http.js';
import { DocumentParser } from '../src/documents/parser.js';

async function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'marlin-http-documents-'));
  const parser = new DocumentParser({ pythonExecutable: process.env.MARLIN_PARSER_PYTHON ?? '/tmp/marlin-parser-isolation-20261010/bin/python', workerPath: resolve('../../workers/document/worker.py') });
  const app = new CoreApplication(root, { allowAutoSetup: true, parser });
  const adapter = createCoreHttpServer(app, { port: 0, maxUploadBytes: 4096 });
  const { origin } = await adapter.listen();
  const jar = new Map<string, string>();
  const request = async (path: string, method = 'GET', body?: unknown, authenticated = true) => {
    const response = await fetch(origin + path, { method,
      headers: { Origin: origin, ...(authenticated ? { Cookie: [...jar].map(([k,v])=>`${k}=${v}`).join('; ') } : {}), ...(method !== 'GET' && jar.has('csrftoken') ? { 'X-CSRFToken': jar.get('csrftoken')! } : {}), ...(body !== undefined && !(body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}) },
      body: body instanceof FormData ? body : body === undefined ? undefined : JSON.stringify(body) });
    for (const cookie of response.headers.getSetCookie()) { const pair = cookie.split(';')[0]!; const i = pair.indexOf('='); if(pair.slice(i+1)) jar.set(pair.slice(0,i),pair.slice(i+1)); else jar.delete(pair.slice(0,i)); }
    return response;
  };
  await request('/api/v1/auth/csrf');
  const initial = await request('/api/v1/auth/auto-setup','POST',{email:'documents-qa@example.invalid',password:'isolated-document-test-password'});
  assert.equal(initial.status,200);
  const kb = await (await request('/api/v1/knowledge-bases','POST',{name:'文档 闭环'})).json() as any;
  const path = `/api/v1/knowledge-bases/${kb.data.id}/knowledge/file`;
  const form = (text = '# 海盐计划\n\n2026年生效预算468000元。\n',name='中文 空格.md') => { const data=new FormData(); data.append('file',new Blob([text]),name); return data; };
  return { app, request, path, form, kbId: kb.data.id as string, async close() { await adapter.close(); await app.close(); rmSync(root,{recursive:true,force:true}); } };
}

test('actual multipart upload drives Python parsing and FTS; stage DTO, original bytes and duplicate response preserve browser contracts',async()=>{
  const f=await fixture();
  try {
    const response=await f.request(f.path,'POST',f.form());
    assert.equal(response.status,200);
    const body=await response.json() as any;
    assert.equal(body.data.deduplicated,false);
    const id=body.data.knowledge.id;
    const limit=Date.now()+5000;
    while(Date.now()<limit&&f.app.database.read('knowledges',id)?.processed_at===null) await delay(15);
    assert.notEqual(f.app.database.read('knowledges',id)?.processed_at,null,'actual owned parser must finish');
    const chunks=await (await f.request(`/api/v1/chunks/${id}`)).json() as any;
    assert.ok(chunks.data.items.some((c:any)=>c.content.includes('468000')));
    assert.equal(f.app.database.get("SELECT count(*) AS n FROM chunks_fts WHERE chunks_fts MATCH '468000'")!.n,1);
    const stages=await (await f.request(`/api/v1/knowledge/${id}/stages`)).json() as any;
    assert.ok(Array.isArray(stages.data.items));
    assert.ok(stages.data.items.length>1);
    assert.ok(stages.data.items.every((s:any)=>s.status!=='running'));
    const download=await f.request(`/api/v1/knowledge/${id}/download`);
    assert.equal(download.status,200);
    assert.equal(download.headers.get('x-content-type-options'),'nosniff');
    assert.match(download.headers.get('content-disposition')! ,/filename\*=UTF-8/);
    assert.equal(await download.text(),'# 海盐计划\n\n2026年生效预算468000元。\n');
    const repeat=await (await f.request(f.path,'POST',f.form())).json() as any;
    assert.equal(repeat.data.deduplicated,true);
    assert.equal(repeat.data.knowledge.id,id);
    assert.equal(f.app.database.get('SELECT count(*) AS n FROM knowledges')!.n,1);
    assert.equal((await f.request(`/api/v1/knowledge/${id}/download`,'GET',undefined,false)).status,401);
    const reparsed=await f.request(`/api/v1/knowledge/${id}/reparse`,'POST',{});
    assert.equal(reparsed.status,200);
    assert.equal((await f.request(`/api/v1/knowledge/${id}/cancel-parse`,'POST')).status,200);
    assert.equal(f.app.database.read('knowledges',id)?.pending_subtasks_count,0);
  } finally { await f.close(); }
});

test('unauthorized, duplicate fields, foreign uploads and byte limits cannot publish documents or owned files',async()=>{
  const f=await fixture();
  try {
    assert.equal((await f.request(f.path,'POST',f.form(),false)).status,403);
    const duplicate=f.form();duplicate.append('file',new Blob(['other']),'other.md');
    assert.equal((await f.request(f.path,'POST',duplicate)).status,400);
    const config=f.form();config.append('process_config','{"parser_engine":"shell","path":"/etc/passwd"}');
    assert.equal((await f.request(f.path,'POST',config)).status,400);
    assert.equal((await f.request(f.path,'POST',f.form('x'.repeat(4097)))).status,413);
    const other=await f.request('/api/v1/auth/register','POST',{email:'other-documents-qa@example.invalid',password:'other-isolated-password'});
    assert.equal(other.status,200);
    assert.equal((await f.request(f.path,'POST',f.form())).status,404);
    assert.equal(f.app.database.get('SELECT count(*) AS n FROM knowledges')!.n,0);
  } finally { await f.close(); }
});

test('clear library content preserves tags and library while removing active FTS entries',async()=>{
  const f=await fixture();
  try {
    await f.request(`/api/v1/knowledge-bases/${f.kbId}/tags`,'POST',{name:'保留标签'});
    assert.equal((await f.request(`/api/v1/knowledge-bases/${f.kbId}/knowledge`,'DELETE')).status,200);
    assert.equal((await f.request(`/api/v1/knowledge-bases/${f.kbId}`)).status,200);
    const tags=await (await f.request(`/api/v1/knowledge-bases/${f.kbId}/tags`)).json() as any;
    assert.equal(tags.data.items.length,1);
  } finally { await f.close(); }
});
