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

test('current cancelled or failed processing takes priority while preserving an earlier summary', () => {
  const { b, dispose } = mountDetail()
  try {
    assert.equal(b.summaryText({ parse_status: 'completed', summary_status: 'needs_configuration', workflow_status: 'cancelled' }), '处理已取消，摘要未生成')
    assert.match(b.summaryText({ parse_status: 'completed', summary_status: 'completed', workflow_status: 'cancelled', description: '旧摘要' }), /^处理已取消.*旧摘要/)
    const failed = { parse_status: 'completed', summary_status: 'completed', workflow_status: 'failed', error_message: 'document_processing_failed', description: '旧摘要' }
    assert.match(b.summaryText(failed), /^本次处理失败.*文档处理失败.*旧摘要/)
    assert.equal(b.documentStatus(failed), 'failed')
    assert.equal(b.documentStatus({ parse_status: 'completed', metadata: { workflow_status: 'interrupted' } }), 'interrupted')
  } finally { dispose() }
})

test('empty source asks the user to inspect the original file instead of promising a successful retry', () => {
  const { b, dispose } = mountDetail()
  try {
    const empty = { parse_status: 'completed', workflow_status: 'completed', summary_status: 'failed', processing_warning_codes: ['postprocess_source_empty'] }
    assert.equal(b.summaryText(empty), '未提取到可用于摘要的内容，请检查原文件')
    assert.equal(b.summaryText({ ...empty, processing_warning_codes: undefined, metadata: { processing_warnings: [{ code: 'postprocess_source_empty' }] } }), '未提取到可用于摘要的内容，请检查原文件')
    assert.doesNotMatch(b.summaryText(empty), /重解析|重试/)
  } finally { dispose() }
})

test('reprocessing preserves the earlier summary but identifies the current active workflow', () => {
  const { b, dispose } = mountDetail()
  try {
    const doc = { parse_status: 'completed', workflow_status: 'processing', description: '旧摘要', summary_status: 'completed' }
    assert.match(b.summaryText(doc), /^处理中.*旧摘要/)
    assert.equal(b.documentStatus(doc), 'processing')
    assert.equal(b.isDocumentProcessing(doc), true)
    assert.equal(b.isDocumentProcessing({ ...doc, workflow_status: 'cancelled', pending_subtasks_count: 999 }), false)
  } finally { dispose() }
})

test('explicit empty list projections clear older detail workflow and warnings', () => {
  const { b, dispose } = mountDetail()
  try {
    const doc = { parse_status: 'completed', summary_status: 'completed', workflow_status: '', source_generation: '', processing_warning_codes: [], metadata: { workflow_status: 'failed', source_generation: 'older-source', processing_warnings: [{ code: 'postprocess_source_empty' }] } }
    assert.equal(b.documentStatus(doc), 'completed')
    assert.equal(b.sourceGeneration(doc), '')
    assert.equal(b.summaryText(doc), '摘要已生成')
  } finally { dispose() }
})

for (const change of ['workflow-finished', 'source-generation']) {
  test(`an already-published open document refreshes its chunks after ${change}`, async () => {
    let reads = 0
    const updated = { id: 'doc', parse_status: 'completed', workflow_status: 'completed', source_generation: 'new-source', description: '新摘要' }
    const { b, dispose } = mountDetail({
      listKnowledge: async () => ({ data: { items: [updated] } }),
      listChunks: async () => { reads++; return { data: { items: [{ id: 'new-chunk', content: '新发布内容' }], total: 1 } } },
    })
    try {
      b.activeDoc.value = { ...updated, workflow_status: change === 'workflow-finished' ? 'processing' : 'completed', source_generation: change === 'source-generation' ? 'old-source' : 'new-source' }
      b.chunkVisible.value = true
      b.chunks.value = [{ id: 'old-chunk', content: '旧发布内容' }]
      await b.loadDocs(); await vue.nextTick(); await vue.nextTick()
      assert.equal(b.activeDoc.value.description, '新摘要')
      assert.equal(reads, 1)
      assert.equal(b.chunks.value[0].content, '新发布内容')
    } finally { dispose() }
  })
}

for (const protectedView of ['dirty-edit', 'citation']) {
  test(`a new published source keeps the current ${protectedView} intact`, async () => {
    let reads = 0
    const { b, dispose } = mountDetail({
      listKnowledge: async () => ({ data: { items: [{ id: 'doc', parse_status: 'completed', workflow_status: 'completed', source_generation: 'new-source' }] } }),
      listChunks: async () => { reads++; return { data: { items: [], total: 0 } } },
    })
    try {
      b.activeDoc.value = { id: 'doc', parse_status: 'completed', workflow_status: 'processing', source_generation: 'old-source' }
      b.chunkVisible.value = true
      b.chunks.value = [{ id: 'editing', content: '保留编辑内容' }]
      if (protectedView === 'dirty-edit') b.dirtyChunkIds.value.add('editing')
      else b.citationChunk.value = { id: 'exact-source', content: '精确引用内容' }
      await b.loadDocs(); await vue.nextTick()
      assert.equal(reads, 0)
      assert.equal(b.chunks.value[0].content, '保留编辑内容')
      if (protectedView === 'citation') assert.equal(b.citationChunk.value.content, '精确引用内容')
    } finally { dispose() }
  })
}

test('saving the last disabled child refreshes the open total and parent relationships', async () => {
  let saved = false
  const child = { id: 'child', chunk_type: 'text', content: '当前额度', is_enabled: true, context_parent_id: 'parent' }
  const { b, dispose } = mountDetail({
    updateChunk: async () => { saved = true; return { data: { ...child, is_enabled: false, context_parent_id: null } } },
    listChunks: async () => ({ data: { items: saved
      ? [{ ...child, is_enabled: false, context_parent_id: null }]
      : [{ id: 'parent', chunk_type: 'parent_text', content: '上下文', is_enabled: false }, { ...child }], total: saved ? 1 : 2, page: 1 } }),
  })
  try {
    await b.load()
    await b.openChunks({ id: 'doc' })
    const editing = b.chunks.value.find(c => c.id === 'child')
    editing.is_enabled = false
    b.dirtyChunkIds.value.add('child')
    await b.saveChunk(editing)
    assert.equal(b.chunkVisible.value, true)
    assert.equal(b.chunkTotal.value, 1)
    assert.equal(b.chunks.value.length, 1)
    assert.equal(b.chunks.value[0].context_parent_id, null)
    assert.equal(b.chunks.value[0].is_enabled, false)
  } finally { dispose() }
})

test('a successful save preserves changes typed while its request is pending', async () => {
  let finish
  const pending = new Promise(resolve => { finish = resolve })
  let reads = 0
  const { b, dispose } = mountDetail({
    updateChunk: async () => pending,
    listChunks: async () => { reads++; return { data: { items: [], total: 0 } } },
  })
  try {
    await b.load()
    b.activeDoc.value = { id: 'doc' }
    b.chunkVisible.value = true
    b.chunks.value = [{ id: 'child', content: '已提交版本', is_enabled: true }]
    b.dirtyChunkIds.value.add('child')
    const saving = b.saveChunk(b.chunks.value[0])
    b.chunks.value[0].content = '请求期间新输入，尚未保存'
    finish({ data: { id: 'child', content: '已提交版本', is_enabled: true } })
    await saving
    assert.equal(b.dirtyChunkIds.value.has('child'), true)
    assert.equal(b.chunks.value[0].content, '请求期间新输入，尚未保存')
    assert.equal(reads, 0)
  } finally { dispose() }
})

test('saving one chunk preserves the other unsaved chunk on the same page', async () => {
  let reads = 0
  const { b, dispose } = mountDetail({
    updateChunk: async () => ({ data: {} }),
    listChunks: async () => { reads++; return { data: { items: [], total: 0 } } },
  })
  try {
    await b.load()
    b.activeDoc.value = { id: 'doc' }
    b.chunkVisible.value = true
    b.chunks.value = [{ id: 'first', content: '本次保存', is_enabled: true }, { id: 'other', content: '其它未保存内容', is_enabled: true }]
    b.dirtyChunkIds.value = new Set(['first', 'other'])
    await b.saveChunk(b.chunks.value[0])
    assert.equal(b.dirtyChunkIds.value.has('first'), false)
    assert.equal(b.dirtyChunkIds.value.has('other'), true)
    assert.equal(b.chunks.value[1].content, '其它未保存内容')
    assert.equal(reads, 0)
  } finally { dispose() }
})

test('saving a clean filtered chunk page retains its page and type', async () => {
  const requested = []
  const { b, dispose } = mountDetail({
    updateChunk: async () => ({ data: {} }),
    listChunks: async (id, query) => {
      requested.push({ id, ...query })
      return { data: { items: [{ id: 'child', content: '保存后的正文', is_enabled: true }], page: 2, total: 60 } }
    },
  })
  try {
    await b.load()
    b.activeDoc.value = { id: 'doc' }
    b.chunkVisible.value = true
    b.chunkPage.value = 2
    b.chunkTypeFilter.value = 'text'
    b.chunks.value = [{ id: 'child', content: '保存后的正文', is_enabled: true }]
    b.dirtyChunkIds.value.add('child')
    await b.saveChunk(b.chunks.value[0])
    assert.equal(requested.length, 1)
    assert.deepEqual(requested[0], { id: 'doc', page: 2, page_size: 50, chunk_type: 'text' })
    assert.equal(b.chunkPage.value, 2)
    assert.equal(b.chunkTypeFilter.value, 'text')
    assert.equal(b.chunkTotal.value, 60)
  } finally { dispose() }
})

test('a rejected chunk save leaves its draft and dirty marker intact', async () => {
  const rejected = new Error('保存被拒绝')
  const { b, dispose } = mountDetail({ updateChunk: async () => { throw rejected } })
  try {
    await b.load()
    b.activeDoc.value = { id: 'doc' }
    b.chunks.value = [{ id: 'child', content: '保留草稿', is_enabled: false }]
    b.dirtyChunkIds.value.add('child')
    await assert.rejects(b.saveChunk(b.chunks.value[0]), rejected)
    assert.equal(b.dirtyChunkIds.value.has('child'), true)
    assert.equal(b.chunks.value[0].content, '保留草稿')
  } finally { dispose() }
})
