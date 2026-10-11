import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import vm from 'node:vm'
import { transformSync } from 'esbuild'
import { parse, compileScript } from '@vue/compiler-sfc'

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
