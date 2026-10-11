import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import vm from 'node:vm'
import { transformSync } from 'esbuild'
import { compileScript, parse } from '@vue/compiler-sfc'

const require = createRequire(import.meta.url)
const vue = require('vue')
const script = transformSync(compileScript(parse(readFileSync(new URL('./KnowledgeDetail.vue', import.meta.url), 'utf8')).descriptor, { id: 'server-job-polling' }).content, { loader: 'ts', format: 'cjs' }).code

function fixture(processingCount, pendingCount) {
  const server = { processingCount, pendingCount, summary: 'failed', workflow: '', generation: '', description: '' }
  const timers = new Map()
  let nextTimer = 1
  const api = {
    getKb: async () => ({ data: { id: 'kb', name: 'fixture', processing_count: server.processingCount } }),
    listTags: async () => ({ data: { items: [] } }),
    listKnowledge: async () => ({ data: { items: [{ id: 'doc', parse_status: 'completed', pending_subtasks_count: server.pendingCount, summary_status: server.summary, workflow_status: server.workflow, source_generation: server.generation, description: server.description }], status_counts: { completed: 1 } } }),
  }
  const context = vm.createContext({ module: { exports: {} }, console, URL,
    setInterval: (callback, delay) => { assert.equal(delay, 3000); const id = nextTimer++; timers.set(id, callback); return id },
    clearInterval: id => timers.delete(id),
    require: name => {
      if (name === 'vue') return { ...vue, onMounted() {}, onUnmounted() {} }
      if (name === 'vue-router') return { useRoute: () => ({ params: { kbId: 'kb' }, query: {} }), useRouter: () => ({ replace() {} }) }
      if (name === 'tdesign-vue-next') return { MessagePlugin: { success() {}, warning() {}, error() {} } }
      if (name === '../api') return { normalizeChunkingConfig: () => ({}), chunkingConfigError: () => '', api }
      if (name.endsWith('.vue')) return { default: {} }
      throw new Error(`Unexpected import ${name}`)
    },
  })
  vm.runInContext(script, context)
  const scope = vue.effectScope()
  const component = scope.run(() => context.module.exports.default.setup({}, { expose() {} }))
  return { component, server, api, timers, dispose: () => { component.stopPolling(); scope.stop() } }
}

test('server active-job count keeps polling completed parse until summary finishes and then stops', async () => {
  const { component: b, server, timers, dispose } = fixture(1, 1)
  try {
    await b.load(); await vue.nextTick()
    assert.equal(b.docs.value[0].parse_status, 'completed')
    assert.equal(b.isProcessing.value, true)
    assert.equal(timers.size, 1)
    assert.equal(b.summaryText(b.docs.value[0]), '摘要生成失败，可重解析重试')
    server.processingCount = 0; server.pendingCount = 0; server.summary = 'completed'
    await timers.get(b.pollTimer.value)(); await vue.nextTick()
    assert.equal(b.docs.value[0].summary_status, 'completed')
    assert.equal(b.summaryText(b.docs.value[0]), '摘要已生成')
    assert.equal(b.isProcessing.value, false)
    assert.equal(b.pollTimer.value, null)
    assert.equal(timers.size, 0)
  } finally { dispose() }
})

test('stale legacy pending count cannot restart polling when the server has no active job', async () => {
  const { component: b, timers, dispose } = fixture(0, 91)
  try {
    await b.load(); await vue.nextTick()
    assert.equal(b.docs.value[0].pending_subtasks_count, 91)
    assert.equal(b.isProcessing.value, false)
    assert.equal(timers.size, 0)
  } finally { dispose() }
})

test('starting polling does not duplicate the initial knowledge base request before a timer tick', async () => {
  const { component: b, api, timers, dispose } = fixture(1, 1)
  const read = api.getKb; let reads = 0
  try {
    api.getKb = async () => { reads++; return read() }
    await b.load(); await vue.nextTick()
    assert.equal(timers.size, 1)
    assert.equal(reads, 1)
  } finally { dispose() }
})

test('a projected current workflow polls an already-published parse and updates completion automatically', async () => {
  const { component: b, server, timers, dispose } = fixture(0, 1)
  try {
    server.workflow = 'processing'; server.description = '旧摘要'; server.summary = 'completed'
    await b.load(); await vue.nextTick()
    assert.equal(b.isProcessing.value, true)
    assert.equal(timers.size, 1)
    assert.match(b.summaryText(b.docs.value[0]), /^处理中.*旧摘要/)
    server.workflow = 'completed'; server.pendingCount = 0; server.description = '新摘要'
    await timers.get(b.pollTimer.value)(); await vue.nextTick()
    assert.equal(b.kb.value.processing_count, 0)
    assert.equal(b.docs.value[0].description, '新摘要')
    assert.equal(b.summaryText(b.docs.value[0]), '新摘要')
    assert.equal(b.isProcessing.value, false)
    assert.equal(timers.size, 0)
  } finally { dispose() }
})

test('overlapping timer ticks keep only one refresh in flight and still publish completion', async () => {
  const { component: b, server, api, timers, dispose } = fixture(1, 1)
  const replies = []; let first, second
  try {
    await b.load(); await vue.nextTick()
    api.getKb = () => new Promise(resolve => replies.push(resolve))
    const tick = timers.get(b.pollTimer.value)
    first = tick(); second = tick()
    assert.equal(replies.length, 1, 'a slow response must not start another poll request')
    server.processingCount = 0; server.pendingCount = 0; server.summary = 'completed'
    replies[0]({ data: { id: 'kb', name: 'fixture', processing_count: 0 } })
    await Promise.all([first, second]); await vue.nextTick()
    assert.equal(b.docs.value[0].summary_status, 'completed')
    assert.equal(b.isProcessing.value, false)
    assert.equal(timers.size, 0)
  } finally {
    for (const reply of replies) reply({ data: { id: 'kb', processing_count: 0 } })
    await Promise.allSettled([first, second].filter(Boolean)); dispose()
  }
})

test('an older refresh response cannot restore a stale processing count after a newer completion', async () => {
  const { component: b, server, api, timers, dispose } = fixture(0, 0)
  const replies = []; let older, newer
  try {
    await b.load()
    api.getKb = () => new Promise(resolve => replies.push(resolve))
    older = b.refreshAll(); newer = b.refreshAll()
    assert.equal(replies.length, 2)
    server.summary = 'completed'; server.description = '完成摘要'
    replies[1]({ data: { id: 'kb', name: 'fixture', processing_count: 0 } })
    await newer; await vue.nextTick()
    replies[0]({ data: { id: 'kb', name: '旧统计', processing_count: 1 } })
    await older; await vue.nextTick()
    assert.equal(b.kb.value.processing_count, 0)
    assert.equal(b.docs.value[0].description, '完成摘要')
    assert.equal(timers.size, 0)
  } finally {
    for (const reply of replies) reply({ data: { id: 'kb', processing_count: 0 } })
    await Promise.allSettled([older, newer].filter(Boolean)); dispose()
  }
})

test('a slower older list response cannot replace a newly published document summary', async () => {
  const { component: b, api, dispose } = fixture(0, 0)
  const replies = []; let older, newer
  try {
    api.listKnowledge = () => new Promise(resolve => replies.push(resolve))
    older = b.loadDocs(); newer = b.loadDocs()
    replies[1]({ data: { items: [{ id: 'doc', description: '新发布摘要', workflow_status: 'completed' }] } })
    await newer
    replies[0]({ data: { items: [{ id: 'doc', description: '旧摘要', workflow_status: 'processing' }] } })
    await older
    assert.equal(b.docs.value[0].description, '新发布摘要')
    assert.equal(b.docs.value[0].workflow_status, 'completed')
  } finally {
    for (const reply of replies) reply({ data: { items: [] } })
    await Promise.allSettled([older, newer].filter(Boolean)); dispose()
  }
})
