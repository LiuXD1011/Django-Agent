import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import vm from 'node:vm'
import { transformSync } from 'esbuild'
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'

const require = createRequire(import.meta.url)
const vue = require('vue')
const { descriptor } = parse(readFileSync(new URL('./KnowledgeDetail.vue', import.meta.url), 'utf8'))
const compiled = compileScript(descriptor, { id: 'kb-detail-load-state' })
const script = transformSync(compiled.content, { loader: 'ts', format: 'cjs' }).code
const template = compileTemplate({ source: descriptor.template.content, filename: 'KnowledgeDetail.vue', id: 'kb-detail-load-state', compilerOptions: { bindingMetadata: compiled.bindings } })
assert.deepEqual(template.errors, [])
const renderScript = transformSync(template.code, { loader: 'ts', format: 'cjs' }).code
const flush = async () => { await new Promise(resolve => setImmediate(resolve)); await vue.nextTick() }
const response = data => ({ data })

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

// KB-DETAIL-LOAD-002: actual Orca 125/126/127 showed GET 404 and mainText=null.
// Compile and mount the unmodified production SFC script AND template with the
// real Vue lifecycle/watch scheduler. Only IO and external widget hosts are
// controlled; no browser, real auth, service, QA data or model is accessed.
function fixture(overrides = {}, query = {}) {
  const requests = [], navigations = [], messages = [], warnings = [], timers = new Set()
  let nextTimer = 0
  const route = vue.reactive({ params: { kbId: 'a' }, query, fullPath: '/platform/knowledge-bases/a' })
  const api = {
    getKb: async id => response({ id, name: `知识库 ${id}`, indexing_strategy: { wiki_enabled: true, graph_enabled: true } }),
    listTags: async () => response({ items: [] }),
    listKnowledge: async id => response({ items: [{ id: `${id}-doc`, title: `文档 ${id}`, parse_status: 'completed' }], status_counts: {}, tag_counts: {}, processing_records: [] }),
    ...overrides,
  }
  for (const [name, method] of Object.entries(api)) api[name] = (...args) => { requests.push({ name, args }); return method(...args) }
  const router = { push: async target => { navigations.push(target) }, replace: async target => { navigations.push(target) } }
  const widget = { render: () => null }
  const context = vm.createContext({ module: { exports: {} }, URL,
    window: { matchMedia: () => ({ matches: false }), addEventListener() {}, removeEventListener() {} },
    setInterval: () => { const timer = ++nextTimer; timers.add(timer); return timer }, clearInterval: timer => timers.delete(timer),
    require: name => {
      if (name === 'vue') return vue
      if (name === 'vue-router') return { useRoute: () => route, useRouter: () => router }
      if (name === '../api') return { api, normalizeChunkingConfig: value => value || {}, chunkingConfigError: () => '' }
      if (name === 'tdesign-vue-next') return { MessagePlugin: Object.fromEntries(['success', 'warning', 'error'].map(level => [level, message => messages.push({ level, message })])) }
      if (name.endsWith('.vue')) return { default: widget }
      throw new Error(`Unexpected import ${name}`)
    },
  })
  vm.runInContext(script, context)
  const component = context.module.exports.default
  const renderContext = vm.createContext({ module: { exports: {} }, require: name => {
    assert.equal(name, 'vue'); return vue
  } })
  vm.runInContext(renderScript, renderContext)
  component.render = renderContext.module.exports.render
  let b
  const originalSetup = component.setup
  component.setup = (props, ctx) => { b = originalSetup(props, ctx); return b }
  const node = (type, text = '') => ({ type, text, children: [], parent: null, props: {}, addEventListener() {}, removeEventListener() {} })
  const renderer = vue.createRenderer({
    createElement: type => node(type), createText: text => node('#text', text), createComment: text => node('#comment', text),
    setText: (item, text) => { item.text = text }, setElementText: (item, text) => { item.text = text; item.children = [] },
    patchProp: (item, name, previous, next) => { item.props[name] = next },
    parentNode: item => item.parent,
    nextSibling: item => item.parent?.children[item.parent.children.indexOf(item) + 1] || null,
    insert: (item, parent, anchor = null) => {
      if (item.parent) item.parent.children.splice(item.parent.children.indexOf(item), 1)
      item.parent = parent
      const index = anchor ? parent.children.indexOf(anchor) : -1
      parent.children.splice(index < 0 ? parent.children.length : index, 0, item)
    },
    remove: item => { item.parent?.children.splice(item.parent.children.indexOf(item), 1); item.parent = null },
  })
  const root = node('root')
  const app = renderer.createApp(component)
  app.config.warnHandler = message => warnings.push(message)
  for (const name of ['t-input', 't-select', 't-option', 't-tag', 't-pagination', 't-textarea', 't-dialog', 't-drawer']) app.component(name, widget)
  app.component('t-button', { render() { return vue.h('button', this.$attrs, this.$slots.default?.()) } })
  app.mount(root)
  let disposed = false
  const nodes = (item = root) => [item, ...item.children.flatMap(child => nodes(child))]
  const text = item => item ? (item.type === '#comment' ? '' : item.text) + item.children.map(text).join('') : ''
  const find = predicate => nodes().find(predicate)
  return {
    b, api, route, requests, navigations, messages, warnings, timers, nodes, text,
    main: () => find(item => item.type === 'main'),
    role: role => find(item => item.props.role === role),
    button: label => find(item => item.type === 'button' && text(item) === label),
    async click(label) {
      const button = this.button(label)
      assert.ok(button, `Missing rendered button: ${label}`)
      await button.props.onClick(); await flush()
    },
    dispose: () => { if (!disposed) { disposed = true; app.unmount() } },
  }
}

test('pending first load renders a main loading status and a safe return action', async () => {
  const pending = deferred()
  const f = fixture({ getKb: () => pending.promise })
  try {
    assert.ok(f.main(), 'initial load must not leave the main region absent')
    assert.match(f.text(f.role('status')), /正在加载知识库/)
    assert.equal(f.button('重试'), undefined)
    await f.click('返回知识库')
    assert.deepEqual(f.navigations, ['/platform/knowledge-bases'])
    pending.resolve(response({ id: 'a', name: '加载完成' })); await flush()
    assert.match(f.text(f.main()), /加载完成/)
    assert.equal(f.role('status'), undefined)
    assert.deepEqual(f.warnings, [])
  } finally { f.dispose() }
})

for (const status of [401, 403, 404, 410]) {
  test(`HTTP ${status} renders a persistent generic unavailable state and return button`, async () => {
    const f = fixture({ getKb: async () => { throw { status, message: 'secret /private/user/db', error: { message: 'secret details' } } } })
    try {
      await flush()
      assert.ok(f.main(), 'failed detail must retain a main region')
      assert.match(f.text(f.role('alert')), /知识库不存在、已删除或无权访问/)
      assert.doesNotMatch(f.text(f.main()), /secret|private|文档工作台/)
      assert.equal(f.button('重试'), undefined)
      assert.equal(f.b.loading.value, false)
      await flush()
      assert.match(f.text(f.role('alert')), /知识库不存在、已删除或无权访问/)
      await f.click('返回知识库')
      assert.deepEqual(f.navigations, ['/platform/knowledge-bases'])
      assert.deepEqual(f.messages, [])
      assert.deepEqual(f.warnings, [])
    } finally { f.dispose() }
  })
}

for (const failure of [new Error('secret network failure'), { status: 500, message: 'secret service failure' }, { response: { status: 503 } }]) {
  test(`recoverable ${failure.status || failure.response?.status || 'network'} failure has a real pending retry and renders its result`, async () => {
    let attempts = 0
    const retry = deferred()
    const f = fixture({ getKb: async id => { if (++attempts === 1) throw failure; return retry.promise } })
    try {
      await flush()
      assert.match(f.text(f.role('alert')), /知识库加载失败，请检查网络或稍后重试/)
      assert.doesNotMatch(f.text(f.main()), /secret/)
      const button = f.button('重试')
      assert.ok(button)
      const retrying = button.props.onClick()
      await flush()
      assert.equal(attempts, 2)
      assert.equal(f.b.loading.value, true)
      assert.match(f.text(f.role('status')), /正在加载知识库/)
      assert.equal(f.role('alert'), undefined)
      assert.equal(f.button('重试'), undefined)
      retry.resolve(response({ id: 'a', name: '重试成功', indexing_strategy: { wiki_enabled: true, graph_enabled: true } }))
      await retrying; await flush()
      assert.match(f.text(f.main()), /重试成功.*文档工作台.*文档 a/s)
      assert.equal(f.role('alert'), undefined)
      assert.equal(f.b.loading.value, false)
      for (const label of ['Wiki', '图谱', '解析记录', '知识库设置', 'Chunk']) assert.ok(f.button(label), `normal feature preserved: ${label}`)
      assert.deepEqual(f.warnings, [])
    } finally { retry.resolve(response({ id: 'a' })); f.dispose() }
  })
}

test('tag and document read failures use the same durable recoverable page state', async () => {
  for (const method of ['listTags', 'listKnowledge']) {
    const f = fixture({ [method]: async () => { throw { status: 500 } } })
    try {
      await flush()
      assert.match(f.text(f.role('alert')), /知识库加载失败/)
      assert.ok(f.button('重试'))
      assert.doesNotMatch(f.text(f.main()), /还没有知识条目/)
    } finally { f.dispose() }
  }
})

test('an unavailable KB with a citation query still renders the KB error and safe return', async () => {
  const f = fixture({ getKb: async () => { throw { status: 404 } } }, { document: 'source', chunk: 'chunk' })
  try {
    await flush()
    assert.match(f.text(f.main()), /知识库不存在、已删除或无权访问/)
    assert.ok(f.button('返回知识库'))
  } finally { f.dispose() }
})

for (const late of ['success', 'failure']) test(`A→B route reuse ignores A late ${late} and preserves B loading then success`, async () => {
  const a = deferred(), b = deferred()
  const f = fixture({ getKb: id => (id === 'a' ? a : b).promise })
  try {
    f.route.params.kbId = 'b'; await flush()
    if (late === 'failure') a.reject({ status: 404 })
    else a.resolve(response({ id: 'a', name: '过时A' }))
    await flush()
    assert.equal(f.b.loading.value, true)
    assert.match(f.text(f.role('status')), /正在加载知识库/)
    assert.doesNotMatch(f.text(f.main()), /过时A|无权/)
    b.resolve(response({ id: 'b', name: '最新B' })); await flush()
    assert.match(f.text(f.main()), /最新B.*文档 b/s)
    assert.equal(f.role('alert'), undefined)
    assert.equal(f.b.loading.value, false)
  } finally { f.dispose() }
})

test('A document failure cannot overwrite B successful detail or its loading state', async () => {
  const oldDocs = deferred()
  const f = fixture({ listKnowledge: id => id === 'a' ? oldDocs.promise : Promise.resolve(response({ items: [{ id: 'b-doc', title: 'B保留文档', parse_status: 'completed' }] })) })
  try {
    await flush()
    f.route.params.kbId = 'b'; await flush()
    oldDocs.reject({ status: 403 }); await flush()
    assert.match(f.text(f.main()), /知识库 b.*B保留文档/s)
    assert.equal(f.role('alert'), undefined)
    assert.equal(f.b.loading.value, false)
  } finally { f.dispose() }
})

test('same-ID newer load ignores an older failed request', async () => {
  let attempts = 0
  const old = deferred()
  const f = fixture({ getKb: id => ++attempts === 1 ? old.promise : Promise.resolve(response({ id, name: '最新同ID' })) })
  try {
    await f.b.load(); await flush()
    old.reject({ status: 404 }); await flush()
    assert.match(f.text(f.main()), /最新同ID/)
    assert.equal(f.role('alert'), undefined)
    assert.equal(f.b.loading.value, false)
  } finally { f.dispose() }
})

test('same-ID newer load invalidates an older document result while its KB read is pending', async () => {
  const oldDocs = deferred(), latestKb = deferred()
  let kbReads = 0
  const f = fixture({
    getKb: id => ++kbReads === 1 ? Promise.resolve(response({ id, name: '先前信息' })) : latestKb.promise,
    listKnowledge: () => oldDocs.promise,
  })
  try {
    await flush()
    const loading = f.b.load()
    oldDocs.resolve(response({ items: [{ id: 'obsolete', title: '过时文档', parse_status: 'completed' }] })); await flush()
    assert.equal(f.b.docs.value.length, 0, 'superseded document results must not publish during the latest KB read')
    assert.equal(f.b.loading.value, true)
    latestKb.resolve(response({ id: 'a', name: '最新信息' })); await loading; await flush()
    assert.match(f.text(f.main()), /最新信息/)
  } finally { f.dispose() }
})

test('a successful retry restores processing polling after the earlier load error stopped it', async () => {
  let docsReads = 0
  const f = fixture({
    getKb: async id => response({ id, name: '处理中知识库', processing_count: 1 }),
    listKnowledge: async () => { if (++docsReads === 1) throw { status: 500 }; return response({ items: [], status_counts: { processing: 1 } }) },
  })
  try {
    await flush()
    assert.ok(f.role('alert'))
    assert.equal(f.timers.size, 0, 'failed page must stop polling')
    await f.click('重试')
    assert.equal(f.role('alert'), undefined)
    assert.equal(f.timers.size, 1, 'a recovered processing KB must resume its existing status polling')
  } finally { f.dispose() }
  assert.equal(f.timers.size, 0)
})

test('route reuse clears an earlier unavailable error before displaying the new result', async () => {
  const f = fixture({ getKb: async id => { if (id === 'a') throw { status: 404 }; return response({ id, name: '可访问B' }) } })
  try {
    await flush()
    assert.ok(f.role('alert'))
    f.route.params.kbId = 'b'; await flush()
    assert.match(f.text(f.main()), /可访问B/)
    assert.equal(f.role('alert'), undefined)
  } finally { f.dispose() }
})

for (const late of ['success', 'failure']) test(`unmount invalidates a late ${late} without changing the disposed refs`, async () => {
  const pending = deferred()
  const f = fixture({ getKb: () => pending.promise })
  f.dispose()
  const loading = f.b.loading.value, kb = f.b.kb.value, error = f.b.loadError?.value
  if (late === 'failure') pending.reject({ status: 404 })
  else pending.resolve(response({ id: 'a', name: '卸载后结果' }))
  await flush()
  assert.equal(f.b.loading.value, loading)
  assert.equal(f.b.kb.value, kb)
  assert.equal(f.b.loadError?.value, error)
  assert.deepEqual(f.messages, [])
})
