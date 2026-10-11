import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createServer } from 'node:http'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { build } from 'esbuild'
import { parse, compileScript } from '@vue/compiler-sfc'
import { chromium } from '@playwright/test'

const directory = fileURLToPath(new URL('.', import.meta.url))
const compile = (file, id) => compileScript(parse(readFileSync(new URL(file, import.meta.url), 'utf8')).descriptor, { id, inlineTemplate: true }).content
let bundlePromise
function bundle() {
  bundlePromise ??= build({ stdin: { contents: [
    "import Wiki from 'wiki:page';import Detail from 'wiki:detail';import {createApp,h,provide,inject} from 'vue';import {createRouter,createMemoryHistory,RouterView} from 'vue-router';import Dialog from 'tdesign-vue-next/es/dialog/dialog.mjs';import Select from 'tdesign-vue-next/es/select/select.mjs';import Option from 'tdesign-vue-next/es/select/option.mjs';",
    "const router=createRouter({history:createMemoryHistory(),routes:[{path:'/platform/knowledge-bases/:kbId/wiki',component:Wiki,props:()=>({embedded:window.fixtureEmbedded,view:window.fixtureEmbedded?'pages':undefined})},{path:'/platform/knowledge-bases/:kbId',component:Detail}]});window.fixtureRouter=router;const app=createApp({render:()=>h(RouterView)});app.use(router);app.component('t-dialog',Dialog);",
    "app.component('t-drawer',{props:['visible','header'],render(){return this.visible?h('section',{'data-widget':'drawer'},[h('h3',this.header),this.$slots.default?.()]):null}});app.component('t-button',{props:['disabled','loading'],render(){return h('button',{disabled:this.disabled||this.loading},this.$slots.default?.())}});",
    "for(const [name,tag] of [['t-input','input'],['t-textarea','textarea']])app.component(name,{props:['modelValue','placeholder'],emits:['update:modelValue'],render(){return h(tag,{value:this.modelValue,placeholder:this.placeholder,onInput:e=>this.$emit('update:modelValue',e.target.value)})}});",
    "app.component('t-radio-group',{props:['modelValue'],emits:['update:modelValue'],setup(_,ctx){provide('radioChange',value=>ctx.emit('update:modelValue',value))},render(){return h('div',this.$slots.default?.())}});app.component('t-radio-button',{props:['value'],setup(){return{change:inject('radioChange')}},render(){return h('button',{onClick:()=>this.change(this.value)},this.$slots.default?.())}});",
    "for(const name of ['t-space','t-tag','t-loading','t-pagination'])app.component(name,{render(){return h('div',this.$slots.default?.())}});for(const [name,component] of [['t-select',Select],['t-option',Option]])app.component(name,window.fixtureRealSelect?component:{render(){return h('div',this.$slots.default?.())}});router.push(window.fixtureRoute).then(()=>router.isReady()).then(()=>app.mount('#app'));",
  ].join('\n'), resolveDir: directory, loader: 'ts' }, bundle: true, write: false, format: 'iife', outdir: '/virtual/wiki-actions',
    plugins: [{ name: 'wiki-test-boundaries', setup(builder) {
      builder.onResolve({ filter: /^wiki:/ }, args => ({ path: args.path, namespace: 'component' }))
      builder.onLoad({ filter: /.*/, namespace: 'component' }, args => ({ contents: compile(args.path === 'wiki:page' ? './Wiki.vue' : './KnowledgeDetail.vue', args.path), loader: 'ts', resolveDir: directory }))
      builder.onResolve({ filter: /^(tdesign-vue-next|\.\.\/api)$|\.vue$/ }, args => ({ path: args.path, namespace: 'boundary' }))
      builder.onLoad({ filter: /.*/, namespace: 'boundary' }, args => ({ contents: args.path === 'tdesign-vue-next' ? "export const MessagePlugin={success:v=>window.fixtureMessages.push(v),warning:v=>window.fixtureMessages.push(v),error:v=>window.fixtureMessages.push(v)};" : args.path === '../api' ? [
        "async function request(path,method='GET',body){const r=await fetch(path,{method,headers:{'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)})});if(!r.ok)throw{status:r.status};return{data:await r.json()}};const pagePath=(kb,slug)=>'/api/v1/knowledge-bases/'+kb+'/wiki/pages/'+slug.split('/').map(encodeURIComponent).join('/');export const normalizeChunkingConfig=v=>v||{};export const chunkingConfigError=()=>'';",
        "export const api={wikiPages:kb=>request('/api/v1/knowledge-bases/'+kb+'/wiki/pages'),getWikiPage:(kb,s)=>request(pagePath(kb,s)),createWikiPage:(kb,b)=>request('/api/v1/knowledge-bases/'+kb+'/wiki/pages','POST',b),updateWikiPage:(kb,s,b)=>request(pagePath(kb,s),'PUT',b),deleteWikiPage:(kb,s)=>request(pagePath(kb,s),'DELETE'),wikiGraph:(kb,q)=>request('/api/v1/knowledge-bases/'+kb+'/wiki/graph?'+new URLSearchParams(q)),wikiSearch:(kb,q)=>request('/api/v1/knowledge-bases/'+kb+'/wiki/search?'+new URLSearchParams(q)),getKnowledge:id=>request('/api/v1/knowledge/'+id),getChunk:(d,c)=>request('/api/v1/chunks/'+d+'/'+c),getKb:id=>request('/api/v1/knowledge-bases/'+id),listTags:id=>request('/api/v1/knowledge-bases/'+id+'/tags'),listKnowledge:id=>request('/api/v1/knowledge-bases/'+id+'/knowledge'),listChunks:(id,q)=>request('/api/v1/chunks/'+id+'?'+new URLSearchParams(q))};",
      ].join('\n') : 'export default{render(){return null}}', loader: 'js' }))
    } }],
  }).then(result => ({ script: result.outputFiles.find(f => f.path.endsWith('.js')).text, css: result.outputFiles.find(f => f.path.endsWith('.css'))?.text || '' }))
  return bundlePromise
}

const ticks = String.fromCharCode(96).repeat(3)
const alpha = { id: 'page-alpha', knowledge_base_id: 'kb-a', slug: 'concept/alpha', title: 'Wiki Alpha', content: '# 真实目录\n\n[[concept/beta|前往 Beta]]\n\n| 名称 | 数量 |\n| --- | --- |\n| QA | 32 |\n\n$x^2=4$\n\n' + ticks + 'js\nconst marker = "CODE"\n' + ticks + '\n\n<script>window.fixtureAttack=1</script>\n[危险链接](javascript:alert(1))', page_type: 'concept', version: 4, source_refs: [{ knowledge_id: 'doc-alpha', title: '来源 Alpha' }], chunk_refs: ['chunk-alpha'], metadata: { contributions: { 'doc-alpha': { chunks: ['chunk-alpha'] } } } }
const beta = { id: 'page-beta', knowledge_base_id: 'kb-a', slug: 'concept/beta', title: 'Wiki Beta', content: '# Beta 正文\n\n[[concept/alpha|返回 Alpha]]', page_type: 'concept', version: 2, source_refs: [{ knowledge_id: 'doc-beta', title: '来源 Beta' }], chunk_refs: [], metadata: {} }

async function fixture(options = {}) {
  const compiled = await bundle()
  const state = new Map([alpha, beta].map(p => [p.slug, structuredClone(p)]))
  const requests = [], errors = []
  const server = createServer(async (req, res) => {
    const url = new URL(req.url, 'http://127.0.0.1'), path = decodeURIComponent(url.pathname), method = req.method
    if (path === '/') { res.setHeader('Content-Type', 'text/html'); return res.end('<div id="app"></div>') }
    let input = ''; for await (const chunk of req) input += chunk
    const body = input ? JSON.parse(input) : undefined
    requests.push({ path, method, body, query: Object.fromEntries(url.searchParams) })
    try {
      let result = await options.respond?.({ path, method, body, state })
      if (!result) {
        const kb = path.split('/')[4], pageMatch = path.match(/^\/api\/v1\/knowledge-bases\/([^/]+)\/wiki\/pages\/(.+)$/)
        if (path.endsWith('/wiki/pages') && method === 'GET') result = { data: { items: kb === 'kb-a' ? [...state.values()] : [] } }
        else if (path.endsWith('/wiki/pages') && method === 'POST') { const p = { ...structuredClone(beta), ...body, id: 'new-page', slug: body.title.toLowerCase().replaceAll(' ', '-'), knowledge_base_id: kb, source_refs: [], chunk_refs: [] }; state.set(p.slug, p); result = { data: p } }
        else if (pageMatch) {
          const p = state.get(pageMatch[2]); result = { status: p ? 200 : 404, data: p || {} }
          if (p && method === 'PUT') { if (body.version !== p.version) result = { status: 409 }; else { Object.assign(p, body, { version: p.version + 1 }); result = { data: p } } }
          if (p && method === 'DELETE') { state.delete(p.slug); result = { data: {} } }
        } else if (path.endsWith('/wiki/graph')) result = { data: { nodes: kb === 'kb-a' ? [...state.values()].map(p => ({ slug: p.slug, title: p.title, page_type: p.page_type, link_count: 1 })) : [], edges: state.has(alpha.slug) && state.has(beta.slug) ? [{ source: alpha.slug, target: beta.slug }] : [], meta: { mode: url.searchParams.get('mode'), total: state.size } } }
        else if (/\/knowledge-bases\/[^/]+$/.test(path)) result = { data: { id: kb, name: '来源知识库', chunking_config: {}, indexing_strategy: { wiki_enabled: true } } }
        else if (path.endsWith('/knowledge') || path.endsWith('/tags')) result = { data: { items: [] } }
        else if (/\/knowledge\/[^/]+$/.test(path)) result = { data: { id: path.split('/')[4], knowledge_base_id: 'kb-a', title: '真实来源文档', parse_status: 'completed' } }
        else if (/\/chunks\/[^/]+\/[^/]+$/.test(path)) result = { data: { id: path.split('/')[5], knowledge_id: path.split('/')[4], knowledge_base_id: 'kb-a', chunk_type: 'text', content: '准确来源片段' } }
        else if (/\/chunks\/[^/]+$/.test(path)) result = { data: { items: [{ id: 'source-first', knowledge_id: path.split('/')[4], knowledge_base_id: 'kb-a', chunk_type: 'text', content: '来源普通分页正文' }], page: 1, total: 120 } }
        else result = { status: 404 }
      }
      res.statusCode = result.status || 200; res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(result.data || {}))
    } catch { if (!res.writableEnded) { res.statusCode = 500; res.end('{}') } }
  })
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  const browser = await chromium.launch({ headless: true }), page = await browser.newPage()
  page.on('pageerror', e => errors.push(e.message))
  await page.goto('http://127.0.0.1:' + server.address().port)
  await page.evaluate(({ embedded, route, realSelect }) => { window.fixtureEmbedded = embedded; window.fixtureRoute = route; window.fixtureRealSelect = realSelect; window.fixtureMessages = [] }, { embedded: !!options.embedded, route: options.route || '/platform/knowledge-bases/kb-a/wiki?tab=pages', realSelect: !!options.realSelect })
  if (compiled.css) await page.addStyleTag({ content: compiled.css })
  await page.addStyleTag({ content: '.wiki-graph-canvas{width:900px;height:600px}.wiki-page-reader{max-width:600px}*{transition:none!important;animation:none!important}' })
  await page.addScriptTag({ content: compiled.script })
  await page.getByRole('heading', { name: 'Wiki Alpha', exact: true }).waitFor({ timeout: 3000 })
  return { page, requests, state, errors, close: async () => { await browser.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)) } }
}

async function edit(f) {
  await f.page.getByRole('button', { name: '编辑页面', exact: true }).click({ timeout: 1500 })
  await f.page.getByPlaceholder('标题', { exact: true }).waitFor({ timeout: 1500 })
}

test('independent Wiki editing uses immutable slug/version and refreshes the rendered reader', async () => {
  const f = await fixture()
  try {
    await edit(f)
    await f.page.getByPlaceholder('标题', { exact: true }).fill('编辑后 Alpha')
    await f.page.getByPlaceholder('Markdown 内容', { exact: true }).fill('# 编辑正文\n\n[[concept/beta|保留双链]]')
    await f.page.getByRole('button', { name: '保存', exact: true }).click()
    await f.page.getByRole('heading', { name: '编辑后 Alpha', exact: true }).waitFor({ timeout: 2000 })
    const write = f.requests.find(r => r.method === 'PUT')
    assert.deepEqual(write, { path: '/api/v1/knowledge-bases/kb-a/wiki/pages/concept/alpha', method: 'PUT', body: { title: '编辑后 Alpha', content: '# 编辑正文\n\n[[concept/beta|保留双链]]', version: 4 }, query: {} })
    assert.equal(f.requests.some(r => r.path.endsWith('/wiki/graph') && r.method === 'GET'), true)
    assert.deepEqual(f.errors, [])
  } finally { await f.close() }
})

for (const status of [403, 409]) test('Wiki edit HTTP ' + status + ' preserves the unsaved Markdown instead of closing the installed dialog', async () => {
  const f = await fixture({ respond: ({ method }) => method === 'PUT' ? { status } : undefined })
  try {
    await edit(f)
    await f.page.getByPlaceholder('Markdown 内容', { exact: true }).fill('尚未保存的 Markdown')
    await f.page.getByRole('button', { name: '保存', exact: true }).click()
    await f.page.getByRole('alert').waitFor({ timeout: 2000 })
    assert.equal(await f.page.getByPlaceholder('Markdown 内容', { exact: true }).inputValue(), '尚未保存的 Markdown')
    assert.equal(f.state.get(alpha.slug).content, alpha.content)
    assert.deepEqual(f.errors, [])
  } finally { await f.close() }
})

test('Wiki deletion cancellation writes nothing and confirmation refreshes reader selection and graph', async () => {
  const f = await fixture()
  try {
    await f.page.getByRole('button', { name: '删除页面', exact: true }).click({ timeout: 1500 })
    await f.page.getByRole('button', { name: '取消', exact: true }).click()
    assert.equal(f.requests.some(r => r.method === 'DELETE'), false)
    await f.page.getByRole('button', { name: '删除页面', exact: true }).click()
    await f.page.getByRole('button', { name: '确认删除', exact: true }).click()
    await f.page.getByRole('heading', { name: 'Wiki Beta', exact: true }).waitFor({ timeout: 2000 })
    assert.equal(f.requests.filter(r => r.method === 'DELETE').length, 1)
    assert.equal(f.state.has(alpha.slug), false)
    assert.equal(await f.page.locator('.wiki-page-list-item').count(), 1)
    assert.deepEqual(f.errors, [])
  } finally { await f.close() }
})

test('embedded Wiki keeps write controls absent and still renders safe Markdown and real internal links', async () => {
  const f = await fixture({ embedded: true })
  try {
    assert.equal(await f.page.getByRole('button', { name: /新建页面|编辑页面|删除页面/ }).count(), 0)
    assert.equal(await f.page.locator('.wiki-reader-content table').count(), 1)
    assert.equal(await f.page.locator('.wiki-reader-content .katex').count(), 1)
    assert.match(await f.page.locator('.wiki-reader-content pre code').innerText(), /CODE/)
    assert.equal(await f.page.locator('.wiki-reader-content script').count(), 0)
    assert.equal(await f.page.evaluate(() => window.fixtureAttack), undefined)
    assert.equal(await f.page.getByRole('link', { name: '危险链接', exact: true }).getAttribute('href'), '#')
    await f.page.getByRole('link', { name: '前往 Beta', exact: true }).click()
    await f.page.getByRole('heading', { name: 'Wiki Beta', exact: true }).waitFor({ timeout: 2000 })
    assert.deepEqual(f.errors, [])
  } finally { await f.close() }
})

test('Wiki directory buttons focus the actual rendered heading inside this reader', async () => {
  const f = await fixture()
  try {
    await f.page.getByRole('button', { name: '真实目录', exact: true }).click({ timeout: 1500 })
    const heading = f.page.locator('.wiki-reader-content h2', { hasText: '真实目录' })
    assert.equal(await heading.evaluate(node => document.activeElement === node), true)
    assert.match(await heading.getAttribute('id'), /^wiki-heading-/)
    assert.deepEqual(f.errors, [])
  } finally { await f.close() }
})

test('Wiki provenance opens the authenticated same-KB exact chunk through the real router', async () => {
  const f = await fixture()
  try {
    await f.page.getByRole('button', { name: '查看来源：来源 Alpha', exact: true }).click({ timeout: 1500 })
    await f.page.locator('.is-citation-target textarea').waitFor({ timeout: 2000 })
    assert.deepEqual(await f.page.evaluate(() => window.fixtureRouter.currentRoute.value.query), { document: 'doc-alpha', chunk: 'chunk-alpha' })
    assert.equal(await f.page.locator('.is-citation-target textarea').inputValue(), '准确来源片段')
    assert.equal(f.requests.some(r => r.path === '/api/v1/knowledge/doc-alpha'), true)
    assert.deepEqual(f.errors, [])
  } finally { await f.close() }
})

test('Wiki source without reliable chunk evidence opens only ordinary document pagination', async () => {
  const f = await fixture()
  try {
    await f.page.getByRole('button', { name: /Wiki Beta/ }).click()
    await f.page.getByRole('button', { name: '查看来源：来源 Beta', exact: true }).click({ timeout: 1500 })
    await f.page.locator('.chunk-editor textarea').waitFor({ timeout: 2000 })
    assert.deepEqual(await f.page.evaluate(() => window.fixtureRouter.currentRoute.value.query), { document: 'doc-beta' })
    assert.equal(await f.page.locator('.is-citation-target').count(), 0)
    const paginated = f.requests.find(r => r.path === '/api/v1/chunks/doc-beta')
    assert.deepEqual(paginated.query, { page: '1', page_size: '50' })
    assert.deepEqual(f.errors, [])
  } finally { await f.close() }
})

for (const problem of ['foreign', 'forbidden', 'removed']) test('Wiki source ' + problem + ' is rejected before any router navigation', async () => {
  const f = await fixture({ respond: ({ path }) => path === '/api/v1/knowledge/doc-alpha' ? problem === 'foreign' ? { data: { id: 'doc-alpha', knowledge_base_id: 'kb-b', title: '不相关文档' } } : { status: problem === 'forbidden' ? 403 : 404 } : undefined })
  try {
    await f.page.getByRole('button', { name: '查看来源：来源 Alpha', exact: true }).click({ timeout: 1500 })
    await f.page.getByRole('alert').waitFor({ timeout: 2000 })
    assert.equal(await f.page.evaluate(() => window.fixtureRouter.currentRoute.value.path), '/platform/knowledge-bases/kb-a/wiki')
    assert.equal(f.requests.some(r => r.path.includes('/chunks/')), false)
    assert.deepEqual(f.errors, [])
  } finally { await f.close() }
})

test('Wiki page creation selects the saved page and never fabricates a source for a manual page', async () => {
  const f = await fixture()
  try {
    await f.page.getByRole('button', { name: '新建页面', exact: true }).click()
    await f.page.getByRole('button', { name: '保存', exact: true }).click()
    assert.equal(f.requests.some(r => r.method === 'POST'), false)
    await f.page.getByPlaceholder('标题', { exact: true }).fill('Manual QA')
    await f.page.getByPlaceholder('Markdown 内容', { exact: true }).fill('# 手写正文')
    await f.page.getByRole('button', { name: '保存', exact: true }).click()
    await f.page.getByRole('heading', { name: 'Manual QA', exact: true }).waitFor({ timeout: 2000 })
    assert.equal(await f.page.getByRole('button', { name: /^查看来源：/ }).count(), 0)
    assert.equal(f.requests.filter(r => r.method === 'POST').length, 1)
    assert.deepEqual(f.errors, [])
  } finally { await f.close() }
})

test('a rejected Wiki deletion retains the confirm target and does not change reader or graph', async () => {
  const f = await fixture({ respond: ({ method }) => method === 'DELETE' ? { status: 403 } : undefined })
  try {
    await f.page.getByRole('button', { name: '删除页面', exact: true }).click({ timeout: 1500 })
    await f.page.getByRole('button', { name: '确认删除', exact: true }).click()
    await f.page.getByRole('alert').waitFor({ timeout: 2000 })
    assert.equal(await f.page.getByRole('button', { name: '确认删除', exact: true }).isVisible(), true)
    assert.equal(f.state.size, 2)
    assert.equal(await f.page.getByRole('heading', { name: 'Wiki Alpha', exact: true }).count(), 1)
    assert.deepEqual(f.errors, [])
  } finally { await f.close() }
})

function gate() {
  let started, release
  return { started: new Promise(r => { started = r }), wait: new Promise(r => { release = r }), begin: () => started(), release: () => release() }
}

test('a source authorization response arriving after KB navigation cannot navigate back to the old source', async () => {
  const hold = gate()
  const f = await fixture({ respond: async ({ path }) => { if (path === '/api/v1/knowledge/doc-alpha') { hold.begin(); await hold.wait } } })
  try {
    await f.page.getByRole('button', { name: '查看来源：来源 Alpha', exact: true }).click({ timeout: 1500 })
    await hold.started
    await f.page.evaluate(() => window.fixtureRouter.push('/platform/knowledge-bases/kb-b/wiki?tab=pages'))
    await f.page.getByText('还没有 Wiki 页面', { exact: true }).waitFor({ timeout: 2000 })
    const response = f.page.waitForResponse('**/knowledge/doc-alpha')
    hold.release(); await (await response).finished()
    await f.page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))))
    assert.equal(await f.page.evaluate(() => window.fixtureRouter.currentRoute.value.params.kbId), 'kb-b')
    assert.equal(f.requests.some(r => r.path.includes('/chunks/')), false)
    assert.equal(await f.page.getByText('还没有 Wiki 页面', { exact: true }).isVisible(), true)
    assert.deepEqual(f.errors, [])
  } finally { hold.release(); await f.close() }
})

test('a completed Wiki mutation cannot publish its old scope into a newly selected KB', async () => {
  const hold = gate()
  const f = await fixture({ respond: async ({ method }) => { if (method === 'PUT') { hold.begin(); await hold.wait } } })
  try {
    await edit(f)
    await f.page.getByPlaceholder('标题', { exact: true }).fill('Old KB late update')
    await f.page.getByRole('button', { name: '保存', exact: true }).click()
    await hold.started
    await f.page.evaluate(() => window.fixtureRouter.push('/platform/knowledge-bases/kb-b/wiki?tab=pages'))
    await f.page.getByText('还没有 Wiki 页面', { exact: true }).waitFor({ timeout: 2000 })
    const response = f.page.waitForResponse('**/wiki/pages/concept/alpha')
    hold.release(); await (await response).finished()
    await f.page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))))
    await f.page.getByPlaceholder('Markdown 内容', { exact: true }).waitFor({ state: 'hidden', timeout: 2000 })
    assert.equal(await f.page.getByPlaceholder('Markdown 内容', { exact: true }).isVisible(), false)
    assert.equal(await f.page.getByRole('heading', { name: 'Old KB late update', exact: true }).count(), 0)
    assert.equal(await f.page.evaluate(() => window.fixtureRouter.currentRoute.value.params.kbId), 'kb-b')
    assert.deepEqual(f.errors, [])
  } finally { hold.release(); await f.close() }
})

test('a successful Wiki save followed by a refresh failure remains a confirmed write and is not offered as an unsaved retry', async () => {
  let changed = false
  const f = await fixture({ respond: ({ method, path }) => {
    if (method === 'PUT') changed = true
    if (changed && method === 'GET' && path.endsWith('/wiki/pages')) return { status: 503 }
  } })
  try {
    await edit(f)
    await f.page.getByPlaceholder('Markdown 内容', { exact: true }).fill('已经持久化的正文')
    await f.page.getByRole('button', { name: '保存', exact: true }).click()
    await f.page.getByRole('alert').waitFor({ timeout: 2000 })
    assert.match(await f.page.getByRole('alert').innerText(), /已保存|刷新/)
    assert.equal(f.state.get(alpha.slug).content, '已经持久化的正文')
    await f.page.getByPlaceholder('Markdown 内容', { exact: true }).waitFor({ state: 'hidden', timeout: 2000 })
    assert.equal(await f.page.getByPlaceholder('Markdown 内容', { exact: true }).isVisible(), false)
    assert.equal(f.requests.filter(r => r.method === 'PUT').length, 1)
    assert.deepEqual(f.errors, [])
  } finally { await f.close() }
})

test('the independent Wiki graph drawer edits and deletes the authenticated selected page and refreshes graph nodes', async () => {
  const f = await fixture()
  try {
    await f.page.getByRole('button', { name: '图谱', exact: true }).click()
    const node = f.page.locator('.wiki-graph-canvas svg text').filter({ hasText: /^Wiki Alpha$/ }).locator('..')
    await node.waitFor({ timeout: 2000 })
    // The SVG force simulation moves nodes; a real mouse click does not need to wait for layout stability.
    await node.click({ force: true })
    const drawer = f.page.locator('[data-widget="drawer"]')
    await drawer.getByRole('button', { name: '编辑页面', exact: true }).waitFor({ timeout: 2000 })
    await drawer.getByRole('button', { name: '编辑页面', exact: true }).click()
    await f.page.getByPlaceholder('标题', { exact: true }).fill('Drawer edited Alpha')
    await f.page.getByPlaceholder('Markdown 内容', { exact: true }).fill('# 抽屉更新正文')
    await f.page.getByRole('button', { name: '保存', exact: true }).click()
    await drawer.getByRole('heading', { name: 'Drawer edited Alpha', exact: true }).waitFor({ timeout: 2000 })
    assert.equal(await drawer.locator('.wiki-drawer-content').innerText(), '抽屉更新正文')
    assert.equal(f.requests.find(r => r.method === 'PUT').body.version, 4)
    await drawer.getByRole('button', { name: '删除页面', exact: true }).click()
    await f.page.getByRole('button', { name: '确认删除', exact: true }).click()
    await drawer.waitFor({ state: 'hidden', timeout: 2000 })
    await f.page.locator('.wiki-graph-canvas svg text').filter({ hasText: /^Wiki Beta$/ }).waitFor({ timeout: 2000 })
    assert.equal(await f.page.locator('.wiki-graph-canvas svg text').filter({ hasText: /Alpha/ }).count(), 0)
    assert.equal(f.state.has(alpha.slug), false)
    assert.equal(f.requests.filter(r => r.method === 'DELETE').length, 1)
    assert.deepEqual(f.errors, [])
  } finally { await f.close() }
})

for (const mismatch of ['document', 'knowledge-base']) test('a Wiki source chunk with mismatched ' + mismatch + ' cannot navigate to source content', async () => {
  const f = await fixture({ respond: ({ path }) => path === '/api/v1/chunks/doc-alpha/chunk-alpha' ? { data: { id: 'chunk-alpha', knowledge_id: mismatch === 'document' ? 'doc-foreign' : 'doc-alpha', knowledge_base_id: mismatch === 'knowledge-base' ? 'kb-b' : 'kb-a', content: '禁止显示的分块' } } : undefined })
  try {
    await f.page.getByRole('button', { name: '查看来源：来源 Alpha', exact: true }).click()
    await f.page.getByRole('alert').waitFor({ timeout: 2000 })
    assert.match(await f.page.getByRole('alert').innerText(), /不匹配/)
    assert.equal(await f.page.evaluate(() => window.fixtureRouter.currentRoute.value.path), '/platform/knowledge-bases/kb-a/wiki')
    assert.equal(await f.page.locator('.chunk-editor').count(), 0)
    assert.equal(await f.page.getByText('禁止显示的分块', { exact: true }).count(), 0)
    assert.deepEqual(f.errors, [])
  } finally { await f.close() }
})

test('clearing an in-flight Wiki search stops the installed Select loading state and rejects the late results', async () => {
  const hold = gate()
  const f = await fixture({ realSelect: true, respond: async ({ path }) => {
    if (path.endsWith('/wiki/search')) { hold.begin(); await hold.wait; return { data: { pages: [{ title: '迟到搜索结果', slug: alpha.slug }] } } }
  } })
  try {
    await f.page.getByRole('button', { name: '图谱', exact: true }).click()
    const input = f.page.locator('.wiki-graph-search-panel input').first()
    await input.fill('Alpha')
    await hold.started
    await f.page.locator('.wiki-graph-search-panel .t-loading').waitFor({ timeout: 2000 })
    await input.fill('')
    // Wait for the installed Select's debounced search event to restore all graph options.
    await input.evaluate(node => new Promise((resolve, reject) => {
      const started = performance.now()
      const check = () => {
        for (let component = node.__vueParentComponent; component; component = component.parent) {
          if (component.type.name === 'TSelect' && component.props.options?.length === 2) { resolve(); return }
        }
        if (performance.now() - started > 2000) { reject(new Error('Clearing search must restore the two graph options')); return }
        requestAnimationFrame(check)
      }
      check()
    }))
    assert.equal(await f.page.locator('.wiki-graph-search-panel .t-loading').count(), 0, 'the empty search must finish even while its superseded response is pending')
    const response = f.page.waitForResponse('**/wiki/search?*')
    hold.release(); await (await response).finished()
    await f.page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    assert.equal(await input.inputValue(), '')
    assert.equal(await f.page.locator('.wiki-graph-search-panel .t-loading').count(), 0)
    assert.equal(await f.page.getByText('迟到搜索结果', { exact: true }).count(), 0)
    assert.equal(f.requests.filter(request => request.path.endsWith('/wiki/search')).length, 1)
    assert.deepEqual(f.errors, [])
  } finally { hold.release(); await f.close() }
})

test('deselecting the only graph type cancels its pending view and keeps late graph results hidden', async () => {
  const hold = gate()
  let armed = false
  const f = await fixture({ realSelect: true, respond: async ({ path }) => {
    if (armed && path.endsWith('/wiki/graph')) { hold.begin(); await hold.wait; return { data: { nodes: [{ slug: alpha.slug, title: '迟到图谱节点', page_type: 'concept', link_count: 0 }], edges: [], meta: {} } } }
  } })
  try {
    await f.page.getByRole('button', { name: '图谱', exact: true }).click()
    await f.page.locator('.wiki-graph-canvas svg text').first().waitFor({ timeout: 2000 })
    armed = true
    await f.page.locator('.wiki-type-select').click()
    await f.page.locator('.t-select-option').filter({ hasText: '概念' }).click({ timeout: 2000 })
    await hold.started
    await f.page.getByText('加载图谱中...', { exact: true }).waitFor({ timeout: 2000 })
    await f.page.getByRole('button', { name: '概念', exact: true }).click()
    assert.equal(await f.page.getByText('加载图谱中...', { exact: true }).count(), 0)
    assert.equal(await f.page.getByText('暂无图谱关系', { exact: true }).count(), 1)
    const response = f.page.waitForResponse('**/wiki/graph?*')
    hold.release(); await (await response).finished()
    await f.page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    assert.equal(await f.page.getByText('加载图谱中...', { exact: true }).count(), 0)
    assert.equal(await f.page.locator('.wiki-graph-canvas svg text').count(), 0)
    assert.equal(await f.page.getByText('迟到图谱节点', { exact: true }).count(), 0)
    assert.deepEqual(f.errors, [])
  } finally { hold.release(); await f.close() }
})
