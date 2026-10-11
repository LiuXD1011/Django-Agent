import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import vm from 'node:vm'
import { transformSync } from 'esbuild'
import { parse, compileScript } from '@vue/compiler-sfc'

const require = createRequire(import.meta.url)
const vue = require('vue')
const { descriptor } = parse(readFileSync(new URL('./KnowledgeDetail.vue', import.meta.url), 'utf8'))
const script = transformSync(compileScript(descriptor, { id: 'knowledge-behavior' }).content, {
  loader: 'ts', format: 'cjs', target: 'es2022',
}).code

function mountDetail(overrides = {}) {
  const state = { count: 1, chunks: 2 }
  const api = {
    getKb: async () => ({ data: { id: 'kb', name: 'fixture', knowledge_count: state.count, chunk_count: state.chunks } }),
    listTags: async () => ({ data: { items: [] } }),
    listKnowledge: async () => ({ data: { items: state.count ? [{ id: 'doc', parse_status: 'completed' }] : [], processing_records: [{ id: 'doc', parse_status: 'completed' }], status_counts: {} } }),
    deleteKnowledge: async () => { state.count = 0; state.chunks = 0 },
    batchDeleteKnowledge: async () => { state.count = 0; state.chunks = 0 },
    moveKnowledge: async () => { state.count = 0; state.chunks = 0 },
    deleteChunk: async () => { state.chunks -= 1 },
    listChunks: async () => ({ data: { items: [], total: state.chunks } }),
    uploadFile: async () => { state.count += 1; state.chunks += 2; return { data: {} } },
  }
  Object.assign(api, overrides)
  const scope = vue.effectScope()
  const context = vm.createContext({
    module: { exports: {} }, console,
    setInterval, clearInterval, URL,
    require: (name) => {
      if (name === 'vue') return { ...vue, onMounted: () => {}, onUnmounted: () => {} }
      if (name === 'vue-router') return { useRoute: () => ({ params: { kbId: 'kb' }, query: {} }), useRouter: () => ({ replace: () => {} }) }
      if (name === 'tdesign-vue-next') return { MessagePlugin: { success: () => {}, warning: () => {}, error: () => {} } }
      if (name === '../api') return { api, normalizeChunkingConfig: () => ({}), chunkingConfigError: () => '' }
      if (name.endsWith('.vue')) return { default: {} }
      throw new Error(`Unexpected import: ${name}`)
    },
  })
  vm.runInContext(script, context)
  const b = scope.run(() => context.module.exports.default.setup({}, { expose: () => {} }))
  return { b, dispose: () => { b.stopPolling(); scope.stop() } }
}

for (const mutation of ['confirmRemoveDoc', 'confirmBatchDeleteDocs', 'confirmMove']) {
  test(`${mutation} updates document and chunk counts immediately`, async () => {
    const { b, dispose } = mountDetail()
    try {
      await b.load()
      b.deleteTarget.value = { id: 'doc' }
      b.selectedIds.value = ['doc']
      b.targetKbId.value = 'target'
      await b[mutation]()
      assert.equal(b.docs.value.length, 0)
      assert.equal(b.kb.value.knowledge_count, 0)
      assert.equal(b.kb.value.chunk_count, 0)
    } finally { dispose() }
  })
}

test('removing a chunk updates the knowledge base count without a page reload', async () => {
  const { b, dispose } = mountDetail()
  try {
    await b.load()
    b.activeDoc.value = { id: 'doc' }
    await b.removeChunk({ id: 'chunk' })
    assert.equal(b.kb.value.chunk_count, 1)
  } finally { dispose() }
})

test('an upload that finishes before polling starts still refreshes the counts', async () => {
  const { b, dispose } = mountDetail()
  try {
    await b.load()
    b.uploadFiles.value = [{ name: 'fixture.md', size: 12, lastModified: 1 }]
    await b.confirmUpload()
    assert.equal(b.kb.value.knowledge_count, 2)
    assert.equal(b.kb.value.chunk_count, 4)
  } finally { dispose() }
})

test('document refresh updates the open trace status so completed tasks stop polling', async () => {
  const { b, dispose } = mountDetail()
  try {
    b.activeDoc.value = { id: 'doc', title: 'fixture', parse_status: 'processing' }
    await b.loadDocs()
    assert.equal(b.activeDoc.value.parse_status, 'completed')
    assert.equal(b.activeDoc.value.title, 'fixture')
  } finally { dispose() }
})

test('a rejected upload keeps the file for retry and preserves the API rejection reason', async () => {
  const { b, dispose } = mountDetail({ uploadFile: async () => { throw { error: { message: 'unsupported file extension: exe' } } } })
  try {
    b.uploadFiles.value = [{ name: 'fixture.exe', size: 19, lastModified: 1 }]
    await b.confirmUpload()
    assert.equal(b.uploadFiles.value.length, 1)
    assert.equal(b.uploadVisible.value, true)
    assert.equal(b.uploadStates.value['fixture.exe:19:1'].error, 'unsupported file extension: exe')
  } finally { dispose() }
})

test('document summary text distinguishes failed, missing configuration and actual waiting states', () => {
  const { b, dispose } = mountDetail()
  try {
    assert.equal(b.summaryText({ summary_status: 'failed', parse_status: 'completed' }), '摘要生成失败，可重解析重试')
    assert.equal(b.summaryText({ summary_status: 'needs_configuration', parse_status: 'completed' }), '摘要模型未配置')
    assert.equal(b.summaryText({ summary_status: 'completed', description: '实际摘要' }), '实际摘要')
    assert.equal(b.summaryText({ summary_status: 'pending', parse_status: 'processing' }), '等待摘要/索引')
    assert.equal(b.summaryText({ summary_status: 'pending', parse_status: 'cancelled' }), '解析已取消，摘要未生成')
    assert.equal(b.summaryText({ summary_status: 'pending', parse_status: 'failed' }), '解析失败，摘要未生成')
  } finally { dispose() }
})
