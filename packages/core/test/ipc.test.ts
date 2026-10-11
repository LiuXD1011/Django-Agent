import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { CoreApplication } from '../src/application.js';
import type { CoreRequest, HttpMethod } from '../src/contracts.js';

async function implementation() {
  const module = await import('../src/adapters/ipc.js').catch(() => null);
  assert.ok(module,'The installed renderer must use a controlled IPC adapter for the same core');
  return module;
}
const request=(method:HttpMethod,path:string,body?:any):CoreRequest=>({protocol:1,id:randomUUID(),method,path,...(body===undefined?{}:{body})});

test('IPC persists an encrypted private device session, never exposes tokens, and resumes through the same authoritative core',async()=>{
  const {CoreIpcAdapter}=await implementation();
  const root=mkdtempSync(join(tmpdir(),'marlin-ipc-'));
  let app=new CoreApplication(root,{allowAutoSetup:true});
  try{
    let ipc=new CoreIpcAdapter(app);
    const before=await ipc.invoke(request('GET','/api/v1/auth/me'));
    assert.equal(before.status,401);
    const initial=await ipc.invoke(request('POST','/api/v1/auth/auto-setup',{email:'ipc-qa@example.invalid',password:'ipc-qa-chosen-password'}));
    assert.equal(initial.status,200);
    const data=(initial.body as any).data;
    assert.equal(data.device.client_type,'desktop');
    assert.equal(data.auth_mode,'ipc');
    for(const forbidden of ['credentials','token','refresh_token','temp_password','password'])assert.equal(JSON.stringify(initial).includes(`"${forbidden}":`),false);
    const stored=app.database.get("SELECT value FROM desktop_meta WHERE key='ipc.session'")!.value;
    assert.match(String(stored),/enc:v1:/);
    const privateValue=app.vault.decrypt(JSON.parse(String(stored))) as any;
    const credentials=JSON.parse(privateValue.token);
    assert.ok(credentials.access&&credentials.refresh);
    assert.equal(String(stored).includes(credentials.access),false);
    const kb=await ipc.invoke(request('POST','/api/v1/knowledge-bases',{name:'正式IPC 实库'}));
    assert.equal(kb.status,200);
    await app.close();
    app=new CoreApplication(root,{allowAutoSetup:true});ipc=new CoreIpcAdapter(app);
    assert.equal((await ipc.invoke(request('GET','/api/v1/auth/me'))).status,200);
    assert.equal((await ipc.invoke(request('GET','/api/v1/knowledge-bases'))).body.data.total,1);
    assert.equal((await ipc.invoke(request('POST','/api/v1/auth/logout'))).status,200);
    assert.equal((await ipc.invoke(request('GET','/api/v1/auth/me'))).status,401);
    assert.equal(app.database.get("SELECT value FROM desktop_meta WHERE key='ipc.session'"),undefined);
  }finally{await app.close();rmSync(root,{recursive:true,force:true});}
});

test('IPC validates request and upload boundaries; renderer cannot provide private access or auth context',async()=>{
  const {CoreIpcAdapter}=await implementation();
  const root=mkdtempSync(join(tmpdir(),'marlin-ipc-boundaries-')),app=new CoreApplication(root,{allowAutoSetup:true});
  try{
    const ipc=new CoreIpcAdapter(app);
    const issue=app.auth.autoSetup({email:'ipc-other@example.invalid',password:'private-token-test'});
    const forged={...request('GET','/api/v1/auth/me'),access:issue.credentials.access,auth:issue.context,binding:{transport:'ipc',access:issue.credentials.access}};
    assert.equal((await ipc.invoke(forged)).status,401);
    assert.equal((await ipc.invoke({...request('GET','/api/v1/auth/me'),path:'https://example.invalid/api/v1/auth/me'})).status,400);
    assert.equal((await ipc.invoke(request('POST','/api/v1/auth/login',{email:'ipc-other@example.invalid',password:'private-token-test'}))).status,200);
    assert.equal((await ipc.invoke(request('GET','/api/v1/auth/me'),{tenantId:'foreign-tenant'})).status,401);
    assert.equal((await ipc.invoke(request('POST','/api/v1/knowledge-bases',{name:'big',padding:'x'.repeat(2*1024*1024)}))).status,413);
    assert.equal((await ipc.invoke(request('POST','/api/v1/knowledge-bases'),{upload:{name:'escape.md',path:'/etc/passwd'}})).status,400);
  }finally{await app.close();rmSync(root,{recursive:true,force:true});}
});

test('IPC refresh uses its protected refresh family and logout fence defeats an in-flight login',async()=>{
  const {CoreIpcAdapter}=await implementation();
  const root=mkdtempSync(join(tmpdir(),'marlin-ipc-refresh-'));let now=Date.now();
  const app=new CoreApplication(root,{allowAutoSetup:true,now:()=>now});
  try{
    const ipc=new CoreIpcAdapter(app);
    await ipc.invoke(request('POST','/api/v1/auth/auto-setup',{email:'ipc-refresh@example.invalid',password:'private-refresh-password'}));
    now+=11*60000;
    assert.equal((await ipc.invoke(request('GET','/api/v1/auth/me'))).status,401);
    assert.equal((await ipc.invoke(request('POST','/api/v1/auth/refresh'))).status,200);
    assert.equal((await ipc.invoke(request('GET','/api/v1/auth/me'))).status,200);
    const login=ipc.invoke(request('POST','/api/v1/auth/login',{email:'ipc-refresh@example.invalid',password:'private-refresh-password'}));
    const logout=ipc.invoke(request('POST','/api/v1/auth/logout'));
    await Promise.all([login,logout]);
    assert.equal((await ipc.invoke(request('GET','/api/v1/auth/me'))).status,401);
  }finally{await app.close();rmSync(root,{recursive:true,force:true});}
});
