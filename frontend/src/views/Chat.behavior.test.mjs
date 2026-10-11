import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import vm from 'node:vm'
import { transformSync } from 'esbuild'
import { parse, compileScript } from '@vue/compiler-sfc'

const require = createRequire(import.meta.url)
const vue = require('vue')
const { descriptor } = parse(readFileSync(new URL('./Chat.vue', import.meta.url), 'utf8'))
const script = transformSync(compileScript(descriptor, { id: 'chat-behavior' }).content, { loader: 'ts', format: 'cjs', target: 'es2022' }).code

function mountChat(kbId = '', overrides = {}) {
  const calls = []
  const api = new Proxy({ ...overrides, createSession: async (payload) => { calls.push(payload); return { data: { id: 'fixture-session' } } } }, {
    get: (target, key) => target[key] || (async () => ({ data: { items: [] } })),
  })
  const scope = vue.effectScope()
  const context = vm.createContext({ module: { exports: {} }, console, AbortController, window: { setTimeout: (callback) => callback() },
    require: (name) => {
      if (name === 'vue') return { ...vue, onMounted: () => {}, onUnmounted: () => {} }
      if (name === 'vue-router') return { useRoute: () => overrides.route || ({ params: { kbId }, path: '/platform/creatChat' }), useRouter: () => ({ replace: async () => {}, push: async () => {} }) }
      if (name === '../api') return { api, streamChat: overrides.streamChat, continueStream: overrides.continueStream }
      if (name === '../stores/chat') return { useChatStore: () => ({}) }
      if (name.endsWith('.vue') || name.endsWith('tool-call-state.mjs')) return {}
      throw new Error(`Unexpected import: ${name}`)
    },
  })
  vm.runInContext(script, context)
  const b = scope.run(() => context.module.exports.default.setup({}, { expose: () => {} }))
  return { b, calls, dispose: () => scope.stop() }
}

test('a knowledge-base entry point selects that base before the first message', async () => {
  const { b, calls, dispose } = mountChat('fixture-kb')
  const states = []
  try {
    b.inputRef.value = { applyState: (state) => states.push(state) }
    await b.bootstrap()
    assert.deepEqual(Array.from(states.at(-1)?.knowledge_base_ids || []), ['fixture-kb'])
    await b.createSession({ knowledge_base_ids: ['fixture-kb'] })
    assert.deepEqual(Array.from(calls[0].agent_config.knowledge_base_ids), ['fixture-kb'])
  } finally { dispose() }
})

test('an explicit empty selection and a multiple selection stay intact', async () => {
  const { b, calls, dispose } = mountChat('fixture-kb')
  try {
    await b.createSession({ knowledge_base_ids: [] })
    await b.createSession({ knowledge_base_ids: ['other-kb', 'fixture-kb'] })
    assert.deepEqual(Array.from(calls[0].agent_config.knowledge_base_ids), [])
    assert.deepEqual(Array.from(calls[1].agent_config.knowledge_base_ids), ['other-kb', 'fixture-kb'])
  } finally { dispose() }
})

test('reloading a session waits for its selection and available resources before accepting input', async () => {
  let finishModels
  const models = new Promise(resolve => { finishModels = resolve })
  const { b, dispose } = mountChat('', {
    route: { params: { chatId: 'fixture-session' }, path: '/platform/chat/fixture-session' },
    getSession: async () => ({ data: { last_request_state: { knowledge_base_ids: ['fixture-kb'] } } }),
    listModels: () => models,
    listKbs: async () => ({ data: { items: [{ id: 'fixture-kb' }] } }),
  })
  const states = []
  try {
    b.inputRef.value = { applyState: state => states.push(state) }
    assert.equal(b.initializing?.value, true)
    const pending = b.bootstrap()
    await new Promise(resolve => setImmediate(resolve))
    assert.equal(b.initializing.value, true)
    finishModels({ data: { items: [] } })
    await pending
    assert.equal(b.initializing.value, false)
    assert.deepEqual(Array.from(states.at(-1).knowledge_base_ids), ['fixture-kb'])
    assert.equal(b.knowledgeBases.value[0].id, 'fixture-kb')
  } finally { dispose() }
})

test('recovering an interrupted reply also restores the saved knowledge-base selection', async () => {
  const { b, dispose } = mountChat('', {
    route: { params: { chatId: 'fixture-session' }, path: '/platform/chat/fixture-session' },
    loadMessages: async () => ({ data: { items: [{ id: 'interrupted', role: 'assistant', is_completed: false }] } }),
    continueStream: async () => {},
    getSession: async () => ({ data: { last_request_state: { knowledge_base_ids: ['fixture-kb'] } } }),
    listKbs: async () => ({ data: { items: [{ id: 'fixture-kb' }] } }),
  })
  const states = []
  try {
    b.inputRef.value = { applyState: state => states.push(state) }
    await b.bootstrap()
    assert.deepEqual(Array.from(states.at(-1)?.knowledge_base_ids || []), ['fixture-kb'])
    assert.equal(b.knowledgeBases.value[0].id, 'fixture-kb')
    assert.equal(b.initializing.value, false)
  } finally { dispose() }
})


test('stopping before the response ID arrives waits for that request and stops its persisted reply', async () => {
  let loads = 0
  const stopped = []
  const { b, dispose } = mountChat('', {
    loadMessages: async () => ({ data: { items: ++loads === 1 ? [] : [{ id: 'future-assistant', request_id: 'pending-request', role: 'assistant' }] } }),
    stopSession: async (...args) => stopped.push(args),
    streamChat: (_id, _payload, _agent, _events, signal) => new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(Object.assign(new Error('stopped'), { name: 'AbortError' })))),
  })
  try {
    b.sessionId.value = 'fixture-session'
    const pending = b.doStream('fixture-session', { request_id: 'pending-request' })
    await b.stopReply()
    await pending
    assert.deepEqual(stopped, [['fixture-session', 'future-assistant']])
    assert.equal(b.stopping.value, false)
  } finally { dispose() }
})
