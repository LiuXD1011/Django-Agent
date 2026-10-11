import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { build } from 'esbuild'
import { compileScript, parse } from '@vue/compiler-sfc'
import { chromium } from '@playwright/test'

const directory = fileURLToPath(new URL('.', import.meta.url))
const compile = (path, id) => compileScript(parse(readFileSync(new URL(path, import.meta.url), 'utf8')).descriptor, { id, inlineTemplate: true }).content
let bundled
async function bundle() {
  bundled ??= build({
    stdin: { contents: `import Detail from 'citation:detail'; import Citations from 'citation:list';
      import {createApp,h} from 'vue'; import {createRouter,createMemoryHistory,RouterView} from 'vue-router'; import ActualDrawer from 'tdesign-vue-next/es/drawer/drawer.mjs';
      const router=createRouter({history:createMemoryHistory(),routes:[{path:'/chat',component:{render:()=>h(Citations,{references:window.fixtureReferences})}},{path:'/platform/knowledge-bases/:kbId',component:Detail}]});
      window.fixtureRouter=router;
      const app=createApp({render:()=>h(RouterView)});app.use(router);
      const wrapper={props:['visible','header'],render(){return this.visible===false?null:h('section',{'data-widget':'drawer'},[h('h3',this.header),this.$slots.default?.()])}};
      app.component('t-drawer',window.fixtureRealDrawer?ActualDrawer:wrapper);app.component('t-dialog',wrapper);
      app.component('t-button',{render(){return h('button',this.$slots.default?.())}});
      for(const n of ['t-input','t-select','t-option','t-tag','t-pagination','t-textarea'])app.component(n,{render(){return null}});
      router.push(window.fixtureRoute).then(()=>router.isReady()).then(()=>app.mount('#app'));`, loader: 'ts', resolveDir: directory },
    bundle: true, write: false, format: 'iife', outdir: '/virtual/citation-test',
    plugins: [{ name: 'citation-boundaries', setup(builder) {
      builder.onResolve({ filter: /^citation:/ }, args => ({ path: args.path, namespace: 'component' }))
      builder.onLoad({ filter: /.*/, namespace: 'component' }, args => ({ contents: compile(args.path === 'citation:detail' ? './KnowledgeDetail.vue' : './chat/components/CitationList.vue', args.path), loader: 'ts', resolveDir: directory }))
      builder.onResolve({ filter: /^(tdesign-vue-next|\.\.\/api)$|\.vue$/ }, args => ({ path: args.path, namespace: 'fixture' }))
      builder.onLoad({ filter: /.*/, namespace: 'fixture' }, args => ({ contents:
        args.path === 'tdesign-vue-next' ? `export const MessagePlugin={success(){},warning(v){window.fixtureWarnings.push(v)},error(v){window.fixtureWarnings.push(v)}};` :
        args.path === '../api' ? `async function get(path,options){const res=await fetch(path,options);if(!res.ok)throw{status:res.status};return{data:await res.json()}};export const normalizeChunkingConfig=v=>v||{strategy:'heading',chunk_size:512};export const chunkingConfigError=()=>'';export const api={getKb:id=>get('/api/v1/knowledge-bases/'+id),listTags:id=>get('/api/v1/knowledge-bases/'+id+'/tags'),listKnowledge:id=>get('/api/v1/knowledge-bases/'+id+'/knowledge'),getKnowledge:id=>get('/api/v1/knowledge/'+encodeURIComponent(id)),getChunk:(doc,id)=>get('/api/v1/chunks/'+encodeURIComponent(doc)+'/'+encodeURIComponent(id)),listChunks:doc=>get('/api/v1/chunks/'+doc),deleteChunk:(doc,id)=>get('/api/v1/chunks/'+doc+'/'+id,{method:'DELETE'}),knowledgeImage:async(doc,id)=>{const res=await fetch('/api/v1/knowledge/'+doc+'/images/'+id);if(!res.ok)throw{status:res.status};return{data:await res.blob()}}};` :
        `export default{render(){return null}}`, loader: 'js' }))
    } }],
  }).then(result => ({ script: result.outputFiles.find(file => file.path.endsWith('.js')).text, style: result.outputFiles.find(file => file.path.endsWith('.css'))?.text || '' }))
  return bundled
}

const reference = { knowledge_base_id: 'kb-a', knowledge_id: 'doc-a', chunk_id: 'chunk-a', knowledge_title: '引用文档', content: '回答中的引用', score: 0.8 }
const sourceRoute = '/platform/knowledge-bases/kb-a?document=doc-a&chunk=chunk-a'

async function fixture(options = {}) {
  const { script, style } = await bundle()
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage()
  const requests = [], errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/*', async route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/') return route.fulfill({ contentType: 'text/html', body: '<div id="app"></div>' })
    requests.push(path)
    const override = await options.respond?.(path, route.request().method())
    if (override) return route.fulfill({ status: override.status || 200, contentType: 'application/json', body: JSON.stringify(override.data || {}) })
    const kbId = path.split('/')[4]
    const docId = path.split('/')[4], chunkId = path.split('/')[5]
    let data
    if (/\/knowledge-bases\/[^/]+$/.test(path)) data = { id: kbId, name: `知识库 ${kbId}`, chunking_config: { strategy: 'heading', chunk_size: 512 } }
    else if (path.endsWith('/tags') || path.endsWith('/knowledge')) data = { items: [] }
    else if (/\/knowledge\/[^/]+$/.test(path)) data = { id: docId, knowledge_base_id: docId === 'doc-b' ? 'kb-b' : 'kb-a', title: `原始文档 ${docId}`, parse_status: 'completed' }
    else if (/\/chunks\/[^/]+\/[^/]+$/.test(path)) data = { id: chunkId, knowledge_id: docId, knowledge_base_id: docId === 'doc-b' ? 'kb-b' : 'kb-a', chunk_index: 9876, chunk_type: 'text', content: `真实来源 ${chunkId}`, is_enabled: true }
    else if (/\/chunks\/[^/]+$/.test(path)) data = { items: [{ id: 'page-one', knowledge_id: docId, knowledge_base_id: 'kb-a', chunk_index: 0, chunk_type: 'text', content: '普通分页第一块', is_enabled: true }], total: 120, page: 1 }
    else if (/\/images\//.test(path)) return route.fulfill({ contentType: 'image/png', body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aSxkAAAAASUVORK5CYII=', 'base64') })
    else return route.fulfill({ status: 404, body: '{}' })
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify(data) })
  })
  await page.goto('http://citation.fixture.test/')
  await page.evaluate(() => { window.fixtureFocusEvents = []; document.addEventListener('focusin', event => window.fixtureFocusEvents.push({ className: event.target.className, time: performance.now() })) })
  await page.evaluate(({ references, route, realDrawer }) => { window.fixtureReferences = references; window.fixtureRoute = route; window.fixtureWarnings = []; window.fixtureRealDrawer = realDrawer }, { references: options.references || [reference], route: options.route || '/chat', realDrawer: !!options.realDrawer })
  if (style && options.realDrawer) await page.addStyleTag({ content: style })
  if (options.noTransitions) await page.addStyleTag({ content: '* { transition: none !important; animation: none !important }' })
  await page.addScriptTag({ content: script })
  return { page, requests, errors, close: () => browser.close() }
}

test('keyboard citation disclosure navigates the real router and focuses the exact source outside pagination', async () => {
  const f = await fixture()
  try {
    const disclosure = f.page.getByRole('button', { name: '展开 1 条引用', exact: true })
    await disclosure.waitFor({ timeout: 2000 })
    assert.equal(await disclosure.getAttribute('aria-expanded'), 'false')
    await disclosure.focus(); await disclosure.press('Enter')
    assert.equal(await f.page.getByRole('button', { name: '收起 1 条引用', exact: true }).getAttribute('aria-expanded'), 'true')
    const source = f.page.getByRole('button', { name: '查看来源', exact: true })
    await source.focus(); await source.press('Space')
    const target = f.page.locator('.chunk-editor.is-citation-target')
    await target.waitFor({ timeout: 2000 })
    assert.equal(await target.locator('textarea').inputValue(), '真实来源 chunk-a')
    assert.equal(await target.evaluate(node => document.activeElement === node), true)
    assert.equal(await f.page.getByRole('heading', { name: '原始文档 doc-a' }).count(), 1)
    assert.match(await f.page.locator('.citation-source-range').innerText(), /仅显示此引用片段/)
    assert.deepEqual(await f.page.evaluate(() => window.fixtureRouter.currentRoute.value.query), { document: 'doc-a', chunk: 'chunk-a' })
    assert.deepEqual(f.requests.filter(path => path.includes('/chunks/')), ['/api/v1/chunks/doc-a/chunk-a'], 'never guess a page from index 9876 or scan chunks')
    await f.page.getByRole('button', { name: '浏览文档全部分块', exact: true }).click()
    await f.page.waitForFunction(() => document.querySelector('.chunk-editor textarea')?.value === '普通分页第一块')
    assert.equal(await f.page.locator('.is-citation-target').count(), 0)
    assert.deepEqual(f.errors, [])
  } finally { await f.close() }
})

test('incomplete or URL-like citation identifiers stay disabled and never navigate externally', async () => {
  const f = await fixture({ references: [{ content: '无定位标识', url: 'https://foreign.invalid/source' }, { ...reference, knowledge_base_id: 'https://foreign.invalid' }] })
  try {
    await f.page.getByRole('button', { name: '展开 2 条引用' }).click({ timeout: 2000 })
    const actions = f.page.getByRole('button', { name: '查看来源', exact: true })
    assert.equal(await actions.count(), 2)
    for (const button of await actions.all()) assert.equal(await button.isDisabled(), true)
    assert.equal(await f.page.getByText('缺少有效的来源标识', { exact: true }).count(), 2)
    assert.equal(await f.page.evaluate(() => window.fixtureRouter.currentRoute.value.path), '/chat')
    assert.deepEqual(f.requests, [])
  } finally { await f.close() }
})

for (const problem of ['wrong-kb', 'wrong-document', 'wrong-chunk-kb', 'forbidden', 'removed']) {
  test(`citation source rejects ${problem} without displaying unrelated content`, async () => {
    const f = await fixture({ route: sourceRoute, respond: path => {
      if (problem === 'wrong-kb' && path === '/api/v1/knowledge/doc-a') return { data: { id: 'doc-a', knowledge_base_id: 'kb-b', title: '不相关文档' } }
      if (path === '/api/v1/chunks/doc-a/chunk-a') {
        if (problem === 'forbidden' || problem === 'removed') return { status: problem === 'forbidden' ? 403 : 404 }
        if (problem.startsWith('wrong-')) return { data: { id: 'chunk-a', knowledge_id: problem === 'wrong-document' ? 'doc-b' : 'doc-a', knowledge_base_id: 'kb-b', content: '不相关内容' } }
      }
    } })
    try {
      await f.page.getByRole('alert').waitFor({ timeout: 2000 })
      assert.match(await f.page.getByRole('alert').innerText(), problem === 'forbidden' ? /无权/ : problem === 'removed' ? /不存在|已删除/ : /不匹配/)
      assert.equal(await f.page.locator('.chunk-editor').count(), 0)
      assert.equal(await f.page.getByText('不相关内容', { exact: true }).count(), 0)
      assert.deepEqual(f.errors, [])
    } finally { await f.close() }
  })
}

test('same-component citation navigation preserves unsaved edits including navigation to another knowledge base', async () => {
  const f = await fixture({ route: sourceRoute })
  try {
    const editor = f.page.locator('.chunk-editor textarea')
    await editor.waitFor({ timeout: 2000 }); await editor.fill('尚未保存的编辑')
    await f.page.evaluate(() => window.fixtureRouter.push('/platform/knowledge-bases/kb-a?document=doc-a&chunk=chunk-new'))
    await f.page.getByRole('alert').waitFor({ timeout: 2000 })
    assert.equal(await editor.inputValue(), '尚未保存的编辑')
    assert.match(await f.page.getByRole('alert').innerText(), /未保存/)
    await f.page.evaluate(() => window.fixtureRouter.push('/platform/knowledge-bases/kb-b?document=doc-b&chunk=chunk-b'))
    await f.page.waitForFunction(() => window.fixtureRouter.currentRoute.value.params.kbId === 'kb-a')
    assert.equal(await editor.inputValue(), '尚未保存的编辑')
    assert.equal(f.requests.includes('/api/v1/chunks/doc-b/chunk-b'), false)
    assert.deepEqual(f.errors, [])
  } finally { await f.close() }
})

test('late source reads cannot overwrite a more recent citation route', async () => {
  let release, started
  const startedPromise = new Promise(resolve => { started = resolve })
  const gate = new Promise(resolve => { release = resolve })
  const f = await fixture({ route: sourceRoute, respond: async path => {
    if (path === '/api/v1/chunks/doc-a/chunk-a') { started(); await gate }
  } })
  try {
    await Promise.race([startedPromise, new Promise((_, reject) => setTimeout(() => reject(new Error('Citation must issue the direct source read')), 2000))])
    await f.page.evaluate(() => window.fixtureRouter.push('/platform/knowledge-bases/kb-a?document=doc-a&chunk=chunk-new'))
    await f.page.waitForFunction(() => document.querySelector('.chunk-editor textarea')?.value === '真实来源 chunk-new')
    const response = f.page.waitForResponse('**/chunks/doc-a/chunk-a')
    release()
    await (await response).finished()
    await f.page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    await f.page.waitForFunction(() => document.querySelector('.chunk-editor textarea')?.value === '真实来源 chunk-new')
    assert.equal(await f.page.locator('.chunk-editor').count(), 1)
    assert.deepEqual(f.errors, [])
  } finally { release(); await f.close() }
})

for (const noTransitions of [false, true]) test(`the installed drawer opens visibly before citation keyboard focus (transitions ${noTransitions ? 'disabled' : 'enabled'})`, async () => {
  const f = await fixture({ route: sourceRoute, realDrawer: true, noTransitions })
  try {
    const target = f.page.locator('.t-drawer--open .is-citation-target')
    await target.waitFor({ timeout: 2000 })
    await f.page.waitForFunction(() => document.activeElement === document.querySelector('.t-drawer--open .is-citation-target'), null, { timeout: 2000 })
    assert.equal(await target.evaluate(node => document.activeElement === node), true, JSON.stringify(await target.evaluate(node => ({ active: document.activeElement?.className, visibility: getComputedStyle(node).visibility, events: window.fixtureFocusEvents }))))
    assert.equal(await target.locator('textarea').inputValue(), '真实来源 chunk-a')
    assert.deepEqual(f.errors, [])
  } finally { await f.close() }
})

test('image citations preserve source preview and parent/media provenance through the owned image endpoint', async () => {
  const f = await fixture({ route: sourceRoute, respond: path => path === '/api/v1/chunks/doc-a/chunk-a' ? { data: { id: 'chunk-a', knowledge_id: 'doc-a', knowledge_base_id: 'kb-a', chunk_type: 'image_ocr', chunk_index: 3, content: '图片中的真实文字', image_info: { image_id: 'image-a', source_ref: '第 2 页图片' }, context_parent_id: 'parent-a', media_parent_id: 'media-a', anchor_chunk_id: 'anchor-a' } } : undefined })
  try {
    const image = f.page.getByRole('img', { name: '第 2 页图片', exact: true })
    await image.waitFor({ timeout: 2000 })
    assert.match(await image.getAttribute('src'), /^blob:/)
    assert.equal(await f.page.getByText('媒体容器：media-a', { exact: true }).count(), 1)
    assert.equal(await f.page.getByText('上下文父块：parent-a', { exact: true }).count(), 1)
    assert.equal(await f.page.getByText('锚定正文：anchor-a', { exact: true }).count(), 1)
    assert.equal(f.requests.includes('/api/v1/knowledge/doc-a/images/image-a'), true)
    assert.deepEqual(f.errors, [])
  } finally { await f.close() }
})

test('deleting the opened citation removes it and restores ordinary document pagination', async () => {
  const f = await fixture({ route: sourceRoute })
  try {
    await f.page.locator('.is-citation-target textarea').fill('已决定删除的未保存修改', { timeout: 2000 })
    await f.page.getByRole('button', { name: '删除', exact: true }).click({ timeout: 2000 })
    await f.page.waitForFunction(() => document.querySelector('.chunk-editor textarea')?.value === '普通分页第一块', null, { timeout: 2000 })
    assert.equal(await f.page.locator('.is-citation-target').count(), 0)
    assert.deepEqual(await f.page.evaluate(() => window.fixtureRouter.currentRoute.value.query), {})
    assert.deepEqual(f.errors, [])
  } finally { await f.close() }
})

test('an older paginated read cannot clear edits made to a newly opened citation', async () => {
  let release, started
  const startedPromise = new Promise(resolve => { started = resolve })
  const gate = new Promise(resolve => { release = resolve })
  const f = await fixture({ route: sourceRoute, respond: async path => {
    if (path === '/api/v1/chunks/doc-a') { started(); await gate }
  } })
  try {
    await f.page.getByRole('button', { name: '浏览文档全部分块', exact: true }).click({ timeout: 2000 })
    await startedPromise
    await f.page.evaluate(() => window.fixtureRouter.push('/platform/knowledge-bases/kb-a?document=doc-a&chunk=chunk-new'))
    const editor = f.page.locator('.is-citation-target textarea')
    await editor.waitFor({ timeout: 2000 }); await editor.fill('分页期间未保存的修改')
    const response = f.page.waitForResponse('**/chunks/doc-a')
    release(); await (await response).finished()
    await f.page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    await f.page.evaluate(() => window.fixtureRouter.push('/platform/knowledge-bases/kb-a?document=doc-a&chunk=chunk-third'))
    await f.page.getByRole('alert').waitFor({ timeout: 2000 })
    assert.match(await f.page.getByRole('alert').innerText(), /未保存/)
    assert.equal(await editor.inputValue(), '分页期间未保存的修改')
    assert.deepEqual(f.errors, [])
  } finally { release(); await f.close() }
})

test('a document-only Wiki source opens the authorized document with ordinary pagination and no guessed citation', async () => {
  const f = await fixture({ route: '/platform/knowledge-bases/kb-a?document=doc-a' })
  try {
    const editor = f.page.locator('.chunk-editor textarea')
    await editor.waitFor({ timeout: 2000 })
    assert.equal(await editor.inputValue(), '普通分页第一块')
    assert.equal(await f.page.getByRole('heading', { name: '原始文档 doc-a' }).count(), 1)
    assert.equal(await f.page.locator('.is-citation-target,.citation-source-range').count(), 0)
    assert.deepEqual(f.requests.filter(path => path.includes('/chunks/')), ['/api/v1/chunks/doc-a'])
    await editor.fill('Wiki 来源未保存修改')
    await f.page.evaluate(() => window.fixtureRouter.push('/platform/knowledge-bases/kb-a?document=doc-other'))
    await f.page.getByRole('alert').waitFor({ timeout: 2000 })
    assert.match(await f.page.getByRole('alert').innerText(), /未保存/)
    assert.equal(await editor.inputValue(), 'Wiki 来源未保存修改')
    assert.equal(f.requests.includes('/api/v1/knowledge/doc-other'), false)
    assert.deepEqual(f.errors, [])
  } finally { await f.close() }
})

for (const problem of ['foreign', 'forbidden', 'removed']) test(`a document-only Wiki source rejects ${problem} before loading any chunks`, async () => {
  const f = await fixture({ route: '/platform/knowledge-bases/kb-a?document=doc-a', respond: path => {
    if (path !== '/api/v1/knowledge/doc-a') return
    return problem === 'foreign' ? { data: { id: 'doc-a', knowledge_base_id: 'kb-b', title: '外空间文档' } } : { status: problem === 'forbidden' ? 403 : 404 }
  } })
  try {
    await f.page.getByRole('alert').waitFor({ timeout: 2000 })
    assert.match(await f.page.getByRole('alert').innerText(), problem === 'foreign' ? /不匹配/ : problem === 'forbidden' ? /无权/ : /不存在|已删除/)
    assert.equal(f.requests.some(path => path.includes('/chunks/')), false)
    assert.equal(await f.page.locator('.chunk-editor').count(), 0)
    assert.deepEqual(f.errors, [])
  } finally { await f.close() }
})

for (const destination of [
  '/platform/knowledge-bases/kb-a',
  '/platform/knowledge-bases/kb-b',
  '/platform/knowledge-bases/kb-a?document=bad%2Fid',
]) test(`leaving a pending document source clears its loading state at ${destination}`, async () => {
  let release, started
  const startedPromise = new Promise(resolve => { started = resolve })
  const gate = new Promise(resolve => { release = resolve })
  const f = await fixture({ route: '/platform/knowledge-bases/kb-a?document=doc-a', respond: async path => {
    if (path === '/api/v1/knowledge/doc-a') { started(); await gate }
  } })
  try {
    await startedPromise
    assert.equal(await f.page.getByRole('status').innerText(), '正在读取引用来源…')
    await f.page.evaluate(route => window.fixtureRouter.push(route), destination)
    await f.page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    assert.equal(await f.page.getByRole('status').count(), 0, 'the superseded source must stop showing as loading before its reply arrives')
    const response = f.page.waitForResponse('**/knowledge/doc-a')
    release(); await (await response).finished()
    await f.page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    assert.equal(await f.page.getByRole('status').count(), 0)
    assert.equal(await f.page.locator('.chunk-editor').count(), 0)
    assert.equal(f.requests.some(path => path.includes('/chunks/')), false, 'the superseded source must not load or expose its chunks')
    assert.deepEqual(f.errors, [])
  } finally { release(); await f.close() }
})

test('opening ordinary chunks replaces a pending source without leaving its loading status or accepting its late reply', async () => {
  let release, started
  const startedPromise = new Promise(resolve => { started = resolve })
  const gate = new Promise(resolve => { release = resolve })
  const f = await fixture({ route: '/platform/knowledge-bases/kb-a?document=doc-a', respond: async path => {
    if (path === '/api/v1/knowledge-bases/kb-a/knowledge') return { data: { items: [{ id: 'doc-manual', title: '手动打开文档', parse_status: 'completed' }] } }
    if (path === '/api/v1/knowledge/doc-a') { started(); await gate }
  } })
  try {
    await startedPromise
    assert.equal(await f.page.getByRole('status').count(), 1)
    await f.page.getByRole('button', { name: 'Chunk', exact: true }).click()
    const editor = f.page.locator('.chunk-editor textarea')
    await editor.waitFor({ timeout: 2000 })
    assert.equal(await editor.inputValue(), '普通分页第一块')
    assert.equal(await f.page.getByRole('status').count(), 0)
    const response = f.page.waitForResponse('**/knowledge/doc-a')
    release(); await (await response).finished()
    await f.page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    assert.equal(await f.page.getByRole('status').count(), 0)
    assert.equal(await editor.inputValue(), '普通分页第一块')
    assert.equal(f.requests.includes('/api/v1/chunks/doc-a'), false)
    assert.deepEqual(f.errors, [])
  } finally { release(); await f.close() }
})
