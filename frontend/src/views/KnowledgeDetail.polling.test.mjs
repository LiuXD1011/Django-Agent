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
  const server = { processingCount, pendingCount, summary: 'failed' }
  const timers = new Map()
  let nextTimer = 1
  const context = vm.createContext({ module: { exports: {} }, console, URL,
    setInterval: (callback, delay) => { assert.equal(delay, 3000); const id = nextTimer++; timers.set(id, callback); return id },
    clearInterval: id => timers.delete(id),
    require: name => {
      if (name === 'vue') return { ...vue, onMounted() {}, onUnmounted() {} }
      if (name === 'vue-router') return { useRoute: () => ({ params: { kbId: 'kb' }, query: {} }), useRouter: () => ({ replace() {} }) }
      if (name === 'tdesign-vue-next') return { MessagePlugin: { success() {}, warning() {}, error() {} } }
      if (name === '../api') return { normalizeChunkingConfig: () => ({}), chunkingConfigError: () => '', api: {
        getKb: async () => ({ data: { id: 'kb', name: 'fixture', processing_count: server.processingCount } }),
        listTags: async () => ({ data: { items: [] } }),
        listKnowledge: async () => ({ data: { items: [{ id: 'doc', parse_status: 'completed', pending_subtasks_count: server.pendingCount, summary_status: server.summary }], status_counts: { completed: 1 } } }),
      } }
      if (name.endsWith('.vue')) return { default: {} }
      throw new Error(`Unexpected import ${name}`)
    },
  })
  vm.runInContext(script, context)
  const scope = vue.effectScope()
  const component = scope.run(() => context.module.exports.default.setup({}, { expose() {} }))
  return { component, server, timers, dispose: () => { component.stopPolling(); scope.stop() } }
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
