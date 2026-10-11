import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import vm from 'node:vm'
import { build, transformSync } from 'esbuild'
import { parse, compileScript } from '@vue/compiler-sfc'
import { chromium } from '@playwright/test'

const require = createRequire(import.meta.url)
const vue = require('vue')
const { descriptor } = parse(readFileSync(new URL('./KnowledgeTraceTimeline.vue', import.meta.url), 'utf8'))
const script = transformSync(compileScript(descriptor, { id: 'timeline-behavior' }).content, {
  loader: 'ts', format: 'cjs', target: 'es2022',
}).code
const finished = (id) => ({ id, kind: 'root', name: 'processing', status: 'done', duration_ms: 100 })

function mountTimeline(fetch, active = false) {
  const mounted = []
  const unmounted = []
  const intervals = new Map()
  let nextInterval = 1
  const props = vue.reactive({ knowledgeId: 'first', active })
  const scope = vue.effectScope()
  const context = vm.createContext({
    module: { exports: {} }, console,
    setInterval: (callback) => { const id = nextInterval++; intervals.set(id, callback); return id },
    clearInterval: (id) => intervals.delete(id),
    require: (name) => {
      if (name === 'vue') return { ...vue, onMounted: (callback) => mounted.push(callback), onUnmounted: (callback) => unmounted.push(callback) }
      if (name === '../../../api') return { api: { getKnowledgeSpans: fetch } }
      throw new Error(`Unexpected import: ${name}`)
    },
  })
  vm.runInContext(script, context)
  const b = scope.run(() => context.module.exports.default.setup(props, { expose: () => {} }))
  return { b, props, mounted, intervals, dispose: () => { unmounted.forEach((callback) => callback()); scope.stop() } }
}

async function settle() { await vue.nextTick(); await Promise.resolve(); await vue.nextTick() }

test('completed document history loads its trace without polling', async () => {
  const calls = []
  const { b, mounted, dispose } = mountTimeline(async (id) => { calls.push(id); return { data: { items: [finished(id)] } } })
  try {
    mounted.forEach((callback) => callback())
    await settle()
    assert.deepEqual(calls, ['first'])
    assert.equal(b.rootSpan.value.id, 'first')
  } finally { dispose() }
})

test('switching completed documents fetches the new trace and ignores a late old response', async () => {
  let resolveFirst
  const first = new Promise((resolve) => { resolveFirst = resolve })
  const { b, props, mounted, dispose } = mountTimeline((id) => id === 'first' ? first : Promise.resolve({ data: { items: [finished(id)] } }))
  try {
    mounted.forEach((callback) => callback())
    props.knowledgeId = 'second'
    await settle()
    assert.equal(b.rootSpan.value?.id, 'second')
    resolveFirst({ data: { items: [finished('first')] } })
    await settle()
    assert.equal(b.rootSpan.value.id, 'second')
  } finally { dispose() }
})

test('switching active documents keeps polling while the new trace is loading', async () => {
  let resolveSecond
  const second = new Promise((resolve) => { resolveSecond = resolve })
  const running = (id) => ({ ...finished(id), status: 'running' })
  const { b, props, mounted, intervals, dispose } = mountTimeline((id) => id === 'first'
    ? Promise.resolve({ data: { items: [running(id)] } }) : second, true)
  try {
    mounted.forEach((callback) => callback())
    await settle()
    assert.equal(intervals.size, 1)
    props.knowledgeId = 'second'
    await settle()
    assert.equal(intervals.size, 1)
    resolveSecond({ data: { items: [running('second')] } })
    await settle()
    assert.equal(b.rootSpan.value.id, 'second')
    assert.equal(intervals.size, 1)
    props.active = false
    await settle()
    assert.equal(intervals.size, 0)
  } finally { dispose() }
})

let domBundle
async function bundleTimeline() {
  domBundle ??= build({
    stdin: { contents: `import Timeline from 'fixture:timeline'; import {createApp,h} from 'vue';
      createApp({render:()=>h(Timeline,{knowledgeId:'fixture-document',active:false})}).mount('#app');`,
      loader: 'ts', resolveDir: fileURLToPath(new URL('.', import.meta.url)) },
    bundle: true, write: false, format: 'iife',
    plugins: [{ name: 'timeline-dom', setup(builder) {
      builder.onResolve({ filter: /^fixture:timeline$/ }, () => ({ path: 'timeline', namespace: 'actual' }))
      builder.onLoad({ filter: /.*/, namespace: 'actual' }, () => ({
        contents: compileScript(descriptor, { id: 'timeline-errors-dom', inlineTemplate: true }).content,
        loader: 'ts', resolveDir: fileURLToPath(new URL('.', import.meta.url)),
      }))
      builder.onResolve({ filter: /^\.\.\/\.\.\/\.\.\/api$/ }, () => ({ path: 'api', namespace: 'fixture' }))
      builder.onLoad({ filter: /.*/, namespace: 'fixture' }, () => ({
        contents: `export const api={getKnowledgeSpans:async()=>({data:{items:window.fixtureSpans}})};`, loader: 'js',
      }))
    } }],
  }).then(result => result.outputFiles[0].text)
  return domBundle
}

const traceSpan = (id, name, errorMessage = '', kind = 'stage') => ({
  id, parent_id: kind === 'root' ? '' : 'current', name, kind, status: 'failed',
  error_message: errorMessage, started_at: '2026-10-11T10:00:00Z',
  finished_at: '2026-10-11T10:00:01Z', duration_ms: 1000, input: {}, output: {},
})
async function mountTimelineDOM(items) {
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage(), errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.setContent('<div id="app"></div>')
    await page.evaluate(spans => { window.fixtureSpans = spans }, items)
    await page.addScriptTag({ content: await bundleTimeline() })
    await page.locator('.trace-timeline').waitFor()
    return { page, errors, close: () => browser.close() }
  } catch (error) { await browser.close(); throw error }
}

// Real Orca 672: a failed reader stage rendered the literal code `stage_failed`.
test('actual trace DOM explains known stage and model errors in Chinese while retaining the latest attempt and raw data', async () => {
  const items = [traceSpan('old', 'processing', '', 'root'), { ...traceSpan('old-reader', 'docreader', '旧轨迹错误'), parent_id: 'old' },
    traceSpan('current', 'processing', '', 'root'), traceSpan('reader', 'docreader', 'stage_failed'),
    traceSpan('embedding', 'embedding', 'model_configuration_invalid'), traceSpan('graph', 'graph', 'model_network_error'),
    traceSpan('postprocess', 'postprocess', 'model_result_unknown'), traceSpan('wiki', 'wiki', 'model_output_invalid')]
  const f = await mountTimelineDOM(items)
  try {
    const errors = (await f.page.locator('.trace-error').allTextContents()).map(text => text.trim())
    assert.deepEqual(errors, ['文件读取: 阶段处理失败', '向量索引: 模型配置无效', '图谱提取: 模型网络连接失败，结果可能未确认',
      '后处理: 模型请求结果未确认', 'Wiki 生成: 模型输出无效'])
    assert.equal(await f.page.getByText('旧轨迹错误', { exact: false }).count(), 0)
    assert.equal(await f.page.locator('.trace-bar--failed').count(), 5)
    assert.equal(await f.page.locator('.trace-live').count(), 0)
    assert.deepEqual(await f.page.evaluate(() => window.fixtureSpans), items)
    assert.deepEqual(f.errors, [])
  } finally { await f.close() }
})

test('actual trace DOM retains unknown human text and codes verbatim without prototype matching or HTML execution', async () => {
  const items = [traceSpan('current', 'processing', '', 'root'),
    traceSpan('reader', 'docreader', '原文件损坏，请重新选择 <img src=x onerror=alert(1)>'),
    traceSpan('chunking', 'chunking', 'future_stage_error'), traceSpan('embedding', 'embedding', 'constructor'),
    traceSpan('graph', 'graph', '__proto__'), traceSpan('wiki', 'wiki')]
  const f = await mountTimelineDOM(items)
  try {
    assert.deepEqual((await f.page.locator('.trace-error').allTextContents()).map(text => text.trim()), [
      '文件读取: 原文件损坏，请重新选择 <img src=x onerror=alert(1)>', '文本分块: future_stage_error',
      '向量索引: constructor', '图谱提取: __proto__',
    ])
    assert.equal(await f.page.locator('.trace-errors img').count(), 0)
    assert.equal(await f.page.locator('.trace-bar--failed').count(), 5)
    assert.deepEqual(await f.page.evaluate(() => window.fixtureSpans), items)
    assert.deepEqual(f.errors, [])
  } finally { await f.close() }
})
