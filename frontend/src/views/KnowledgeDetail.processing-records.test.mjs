import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { build } from 'esbuild'
import { compileScript, parse } from '@vue/compiler-sfc'
import { chromium } from '@playwright/test'

// R-PROCESSING-CURRENT-WORKFLOW: actual Orca row showed completed after failed reparse.
// Render the real parent, records child and timeline; only API/router/widgets are isolated.
const directory = fileURLToPath(new URL('.', import.meta.url))
const compile = (path, id) => compileScript(parse(readFileSync(new URL(path, import.meta.url), 'utf8')).descriptor,
  { id, inlineTemplate: true }).content
let bundled
async function bundle() {
  bundled ??= build({
    stdin: { contents: `import Detail from 'record:detail'; import {createApp,h} from 'vue'; import {createRouter,createMemoryHistory,RouterView} from 'vue-router';
      const router=createRouter({history:createMemoryHistory(),routes:[{path:'/platform/knowledge-bases/:kbId',component:Detail}]});window.fixtureRouter=router;
      const app=createApp({render:()=>h(RouterView)});app.use(router);
      const wrapper={props:['visible'],render(){return this.visible===false?null:h('section',this.$slots.default?.())}};
      app.component('t-drawer',wrapper);app.component('t-dialog',wrapper);
      app.component('t-button',{render(){return h('button',this.$slots.default?.())}});
      app.component('t-tag',{render(){return h('span',this.$slots.default?.())}});
      app.component('t-select',{props:['modelValue','placeholder'],emits:['update:modelValue','change'],render(){return h('select',{'aria-label':this.placeholder,value:this.modelValue,
        onChange:e=>{this.$emit('update:modelValue',e.target.value);this.$emit('change',e.target.value)}},[h('option',{value:''},this.placeholder),this.$slots.default?.()])}});
      app.component('t-option',{props:['value','label'],render(){return h('option',{value:this.value},this.label)}});
      for(const n of ['t-input','t-pagination','t-textarea'])app.component(n,{render(){return null}});
      router.push('/platform/knowledge-bases/kb-a?tab=processing').then(()=>router.isReady()).then(()=>app.mount('#app'));`,
      loader: 'ts', resolveDir: directory },
    bundle: true, write: false, format: 'iife',
    plugins: [{ name: 'record-boundaries', setup(builder) {
      builder.onResolve({ filter: /^record:/ }, args => ({ path: args.path, namespace: 'actual' }))
      builder.onResolve({ filter: /KnowledgeProcessingRecords\.vue$/ }, () => ({ path: 'record:list', namespace: 'actual' }))
      builder.onResolve({ filter: /KnowledgeTraceTimeline\.vue$/ }, () => ({ path: 'record:timeline', namespace: 'actual' }))
      builder.onLoad({ filter: /.*/, namespace: 'actual' }, args => ({ contents: compile(args.path === 'record:detail' ? './KnowledgeDetail.vue'
        : args.path === 'record:list' ? './knowledge/components/KnowledgeProcessingRecords.vue' : './chat/components/KnowledgeTraceTimeline.vue', args.path), loader: 'ts', resolveDir: directory }));
      builder.onResolve({ filter: /^(tdesign-vue-next|\.\.\/api|\.\.\/\.\.\/\.\.\/api)$|\.vue$/ }, args => ({ path: args.path, namespace: 'fixture' }))
      builder.onLoad({ filter: /.*/, namespace: 'fixture' }, args => ({ contents: args.path === 'tdesign-vue-next'
        ? `export const MessagePlugin={success(){},warning(){},error(){}}` : args.path.endsWith('/api')
        ? `export const normalizeChunkingConfig=v=>v||{};export const chunkingConfigError=()=>'';
          const get=async path=>{const response=await fetch(path);if(!response.ok)throw{status:response.status};return{data:await response.json()}};
          export const api={getKb:id=>get('/kb/'+id),listTags:id=>get('/tags/'+id),listKnowledge:id=>get('/records/'+id),getKnowledgeSpans:id=>get('/spans/'+id)};`
        : `export default{render(){return null}}`, loader: 'js' }));
    } }],
  }).then(result => result.outputFiles[0].text)
  return bundled
}
const record = (id, workflow, extra = {}) => ({ id, title: `title ${id}`, file_name: `${id}.png`, parse_status: 'completed',
  workflow_status: workflow, description: '旧摘要 retained', metadata: { content: '旧已发布正文', workflow_status: 'failed' }, ...extra })
const span = (id, status, kind = 'root', parent = '') => ({ id, parent_id: parent, kind, name: kind === 'root' ? 'process_knowledge' : 'docreader',
  status, started_at: '2026-10-11T10:00:00Z', finished_at: status === 'running' ? null : '2026-10-11T10:00:01Z', duration_ms: 1000,
  error_message: status === 'failed' ? 'current reader failure' : '', output: {}, input: {} })
async function fixture(initialRecords, options = {}) {
  const browser = await chromium.launch({ headless: true }); const page = await browser.newPage()
  const state = { records: initialRecords, spans: options.spans || {}, requests: [], errors: [], held: [] }
  page.on('pageerror', error => state.errors.push(error.message))
  await page.route('**/*', async route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/') return route.fulfill({ contentType: 'text/html', body: '<div id="app"></div>' })
    state.requests.push(path)
    const override = await options.respond?.(path, state, route)
    if (override) return route.fulfill({ contentType: 'application/json', body: JSON.stringify(override) })
    const id = path.split('/')[2]
    const body = path.startsWith('/kb/') ? { id, name: id, processing_count: 0 }
      : path.startsWith('/tags/') ? { items: [] }
      : path.startsWith('/records/') ? { items: state.records, processing_records: state.records, status_counts: {} }
      : path.startsWith('/spans/') ? { items: state.spans[id] || [span(`old-${id}`, 'done'), span(`old-stage-${id}`, 'done', 'stage')] } : {}
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('http://processing.fixture.test/')
  await page.addScriptTag({ content: await bundle() })
  await page.getByRole('heading', { name: '解析记录', exact: true }).waitFor()
  const rows = page.locator('.processing-record')
  if (initialRecords.length) await rows.first().waitFor()
  return { page, state, rows, close: () => browser.close() }
}

test('actual processing rows use effective failed/cancelled/interrupted/processing states and retain the original records', async () => {
  const inputs = [record('failed', 'failed'), record('cancelled', 'cancelled'), record('interrupted', 'interrupted'), record('active', 'processing'),
    record('legacy', undefined, { metadata: { content: '旧正文' } }), record('explicit-empty', '', { metadata: { workflow_status: 'failed', content: '旧正文' } })]
  const f = await fixture(inputs)
  try {
    assert.deepEqual(await f.rows.locator('.processing-state').allTextContents(), ['失败', '已取消', '已中断', '解析中', '已完成', '已完成'])
    const classes = await f.rows.locator('.processing-state').evaluateAll(nodes => nodes.map(node => node.className))
    assert.match(classes[0], /failed/); assert.match(classes[1], /cancelled/); assert.match(classes[2], /interrupted|failed/); assert.match(classes[3], /processing/)
    assert.equal(inputs.every(input => input.parse_status === 'completed'), true)
    assert.equal(inputs[0].description, '旧摘要 retained'); assert.equal(inputs[0].metadata.content, '旧已发布正文')
    assert.deepEqual(f.state.errors, [])
  } finally { await f.close() }
})

test('status filtering treats interrupted as failed and does not inherit the document filter or make new requests', async () => {
  const f = await fixture([record('failed', 'failed'), record('interrupted', 'interrupted'), record('cancelled', 'cancelled'), record('active', 'processing'), record('done', 'completed')])
  try {
    const selector = f.page.getByRole('combobox', { name: '全部状态', exact: true })
    const reads = f.state.requests.filter(path => path.startsWith('/records/')).length
    await selector.selectOption('failed'); await f.page.waitForFunction(() => document.querySelectorAll('.processing-record').length === 2)
    assert.deepEqual(await f.rows.locator('strong').allTextContents(), ['title failed', 'title interrupted'])
    assert.deepEqual(await f.rows.locator('.processing-state').allTextContents(), ['失败', '已中断'])
    await selector.selectOption('cancelled'); await f.page.waitForFunction(() => document.querySelectorAll('.processing-record').length === 1)
    assert.equal(await f.rows.locator('strong').innerText(), 'title cancelled')
    await selector.selectOption('completed'); await f.page.waitForFunction(() => document.querySelector('.processing-record strong')?.textContent === 'title done')
    await selector.selectOption(''); await f.page.waitForFunction(() => document.querySelectorAll('.processing-record').length === 5)
    assert.equal(f.state.requests.filter(path => path.startsWith('/records/')).length, reads)
    assert.deepEqual(f.state.errors, [])
  } finally { await f.close() }
})

test('record failures reuse the existing Chinese document errors and preserve unknown human messages', async () => {
  const f = await fixture([record('failed', 'failed', { error_message: 'document_processing_failed' }),
    record('scheduling', 'failed', { error_message: 'scheduling_failed' }), record('unknown-result', 'interrupted', { error_message: 'model_result_unknown' }),
    record('custom', 'failed', { error_message: '原文件内容已损坏，请重新选择文件' })])
  try {
    assert.deepEqual(await f.rows.locator('.processing-error').allTextContents(), ['文档处理失败', '任务启动失败', '模型请求结果未确认', '原文件内容已损坏，请重新选择文件'])
    assert.deepEqual(f.state.errors, [])
  } finally { await f.close() }
})

test('an expanded active workflow loads and polls current traces then stops with the final failed trace while retaining old history', async () => {
  const histories = [span('old-root', 'done'), span('old-stage', 'done', 'stage', 'old-root'), span('current-root', 'running'), span('current-stage', 'running', 'stage', 'current-root')]
  const f = await fixture([record('active', 'processing')], { spans: { active: histories } })
  try {
    await f.rows.getByRole('button').click()
    await f.page.locator('.trace-timeline').waitFor()
    assert.equal(await f.page.locator('.trace-live').count(), 1)
    const firstReads = f.state.requests.filter(path => path === '/spans/active').length
    await f.page.waitForFunction(() => document.querySelector('.trace-live')?.textContent === 'LIVE')
    await new Promise(resolve => setTimeout(resolve, 2100))
    assert.ok(f.state.requests.filter(path => path === '/spans/active').length > firstReads)
    f.state.records = [record('active', 'failed', { error_message: 'document_processing_failed' })]
    f.state.spans.active = [histories[0], histories[1], span('current-root', 'failed'), span('current-stage', 'failed', 'stage', 'current-root')]
    await f.page.waitForFunction(() => document.querySelector('.processing-state')?.textContent === '失败', null, { timeout: 6500 })
    await f.page.waitForFunction(() => !document.querySelector('.trace-live') && document.querySelector('.trace-error')?.textContent.includes('current reader failure'))
    const finalReads = f.state.requests.filter(path => path === '/spans/active').length
    await new Promise(resolve => setTimeout(resolve, 2300))
    assert.equal(f.state.requests.filter(path => path === '/spans/active').length, finalReads)
    assert.equal(f.state.spans.active.length, 4); assert.equal(f.state.spans.active[0].status, 'done')
    assert.equal(await f.rows.getByRole('button').getAttribute('aria-expanded'), 'true')
    assert.deepEqual(f.state.errors, [])
  } finally { await f.close() }
})

test('switching KB clears the old processing rows while new records load and rejects an older pending list response', async () => {
  let release, requested
  const pending = new Promise(resolve => { release = resolve }), started = new Promise(resolve => { requested = resolve })
  let readA = 0
  const f = await fixture([record('old-a', 'completed')], { respond: async path => {
    if (path === '/records/kb-a' && ++readA > 1) { requested(); await pending; return { items: [record('late-a', 'failed')], processing_records: [record('late-a', 'failed')] } }
    if (path === '/records/kb-b') { requested(); await pending; return { items: [], processing_records: [record('new-b', 'cancelled')] } }
  } })
  try {
    await f.page.getByRole('button', { name: '文档', exact: true }).click()
    const docFilter = f.page.getByRole('combobox', { name: '解析状态', exact: true })
    await docFilter.selectOption('failed'); await started
    await f.page.evaluate(() => window.fixtureRouter.push('/platform/knowledge-bases/kb-b?tab=processing'))
    await f.page.getByRole('heading', { name: 'kb-b', exact: true }).waitFor()
    assert.equal(await f.page.getByText('title old-a', { exact: true }).count(), 0, 'Previous KB records must not survive into the new KB loading state')
    release(); await f.page.waitForFunction(() => document.querySelector('.processing-record strong')?.textContent === 'title new-b')
    assert.equal(await f.page.getByText('title late-a', { exact: true }).count(), 0)
    assert.equal(await f.rows.locator('.processing-state').innerText(), '已取消')
    assert.deepEqual(f.state.errors, [])
  } finally { release(); await f.close() }
})
