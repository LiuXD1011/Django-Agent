import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { build } from 'esbuild'
import { compileScript, parse } from '@vue/compiler-sfc'
import { chromium } from '@playwright/test'

const directory = fileURLToPath(new URL('.', import.meta.url))
const bundles = new Map()

function bundle(name) {
  if (!bundles.has(name)) bundles.set(name, build({
    stdin: { contents: `import Component from 'fixture:component'; import {createApp,h,ref} from 'vue';
      const component=ref(); window.fixtureSent=[]; window.fixtureApiCalls=[];
      createApp({render:()=>h(Component,{...window.fixtureProps,ref:component,onSend:payload=>window.fixtureSent.push(payload)})}).mount('#app');`,
      loader: 'ts', resolveDir: directory },
    bundle: true, write: false, format: 'iife', outdir: 'fixture-bundle',
    plugins: [{ name: 'actual-chat-display', setup(builder) {
      builder.onResolve({ filter: /^fixture:component$/ }, () => ({ path: name, namespace: 'actual' }))
      builder.onLoad({ filter: /.*/, namespace: 'actual' }, () => {
        const { descriptor } = parse(readFileSync(new URL(name, import.meta.url), 'utf8'))
        return { contents: compileScript(descriptor, { id: 'chat-display-regression', inlineTemplate: true }).content, loader: 'ts', resolveDir: directory }
      })
      builder.onResolve({ filter: /^\.\.\/\.\.\/\.\.\/api$/ }, () => ({ path: 'api', namespace: 'fixture' }))
      builder.onResolve({ filter: /^\.\.\/\.\.\/\.\.\/services\/langfuse$/ }, () => ({ path: 'langfuse', namespace: 'fixture' }))
      builder.onLoad({ filter: /.*/, namespace: 'fixture' }, ({ path }) => ({ loader: 'js', contents: path === 'api'
        ? `export const api={sessionTrajectory:async id=>{window.fixtureApiCalls.push(id);return structuredClone(window.fixtureResponse)}};`
        : `export async function openLangfuse(){throw new Error('External trace opening is outside this display fixture')}` }))
    } }],
  }).then(result => result.outputFiles.find(file => file.path.endsWith('.js')).text))
  return bundles.get(name)
}

async function fixture(name, props, response) {
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage(), errors = []
    page.setDefaultTimeout(3000)
    page.on('pageerror', error => errors.push(error.message))
    await page.setContent('<div id="app"></div>')
    await page.evaluate(({ props, response }) => { window.fixtureProps = props; window.fixtureResponse = response }, { props, response })
    await page.addScriptTag({ content: await bundle(name) })
    await page.locator(name === 'ChatInput.vue' ? '.answers-input' : '.trajectory-turn').waitFor({ timeout: 3000 })
    return { page, errors, close: () => browser.close() }
  } catch (error) { await browser.close(); throw error }
}

const turn = (fields = {}) => ({
  request_id: 'real-shape-request', seq_range: [1, 8], started_at: '2026-10-12T00:00:00Z', completed_at: '2026-10-12T00:00:01Z',
  mode: 'agent', model_id: '', stopped_reason: 'completed', duration_ms: 1000, error: '',
  user: null, assistant: { content: '' }, retrievals: [], steps: [], actors: [], request: null,
  provider: '', retries: [], compactions: [], maintenance: [], usage: { prompt_tokens: 0, completion_tokens: 0, llm_calls: 0, total_tokens: 0 },
  ...fields,
})
const response = (fields) => ({ success: true, data: { version: 3, session_id: 'scope-trace-session', turns: [turn(fields)] } })

// Orca 1121 + persisted scope proof: zero chosen KBs send an explicit [], never all KBs.
test('actual input cancels the last KB and explains the exact emitted empty scope', async () => {
  const f = await fixture('ChatInput.vue', { knowledgeBases: [{ id: 'kb-current', name: '当前知识库' }] })
  try {
    await f.page.getByTitle('知识库', { exact: true }).click()
    await f.page.locator('.chat-option').click()
    assert.equal(await f.page.locator('.mention-chip--kb').count(), 1)
    await f.page.locator('.chat-option').click()
    assert.equal(await f.page.locator('.chat-popover-head small').textContent(), '0 已选')
    assert.equal(await f.page.getByTestId('kb-empty-hint').textContent(), '未选择知识库：本轮不检索知识库资料')
    await f.page.locator('textarea').click()
    assert.equal(await f.page.locator('.chat-popover').count(), 0)
    await f.page.locator('textarea').fill('无需资料的计算')
    await f.page.getByRole('button', { name: '发送消息', exact: true }).click()
    assert.deepEqual(await f.page.evaluate(() => window.fixtureSent[0].knowledge_base_ids), [])
    await f.page.getByTitle('知识库', { exact: true }).click()
    await f.page.locator('.chat-option').click()
    assert.equal(await f.page.getByTestId('kb-empty-hint').count(), 0)
    await f.page.locator('textarea').fill('检索当前知识库')
    await f.page.getByRole('button', { name: '发送消息', exact: true }).click()
    assert.deepEqual(await f.page.evaluate(() => window.fixtureSent[1].knowledge_base_ids), ['kb-current'])
    assert.deepEqual(f.errors, [])
  } finally { await f.close() }
})

// Orca 1155: actual retrieval/result contains objects; joining them hid vector_reindex_required.
test('actual trajectory preserves structured retrieval degradations and unfamiliar text safely', async () => {
  const payload = response({ retrievals: [{ query: '预算', kb_count: 2, top_k: 5, count: 2, intent: 'kb_search', refs: [], degradations: [
    { stage: 'vector', reason: 'vector_reindex_required' }, { stage: 'rerank', reason: 'future_rank_code' },
    'legacy warning', { detail: '<img src=x onerror=alert(1)>' },
  ] }] })
  const f = await fixture('TrajectoryPanel.vue', { sessionId: 'scope-trace-session' }, payload)
  try {
    const text = await f.page.getByTestId('retrieval-0-0').innerText()
    assert.ok(text.includes('向量检索：需要重建向量索引（vector_reindex_required）'), text)
    assert.ok(text.includes('重排：future_rank_code'), text)
    assert.ok(text.includes('legacy warning'), text)
    assert.ok(text.includes('"detail":"<img src=x onerror=alert(1)>"'), text)
    assert.equal(text.includes('[object Object]'), false)
    assert.equal(await f.page.locator('.turn-retrieval img').count(), 0)
    assert.deepEqual(await f.page.evaluate(() => window.fixtureApiCalls), ['scope-trace-session'])
    assert.deepEqual(await f.page.evaluate(() => window.fixtureResponse), payload)
    assert.deepEqual(f.errors, [])
  } finally { await f.close() }
})

// Real producers: chat/index emits stage/status; memory emits stage/state/graph_state/warnings.
test('actual maintenance DOM shows source states, graph state and warnings without inventing completion', async () => {
  const payload = response({ maintenance: [
    { step: '', stage: 'memory_retrieval', success: null, warnings: [{ code: 'memory_response_invalid', message: 'Optional memory was skipped' }] },
    { step: '', stage: 'memory_extraction', state: 'stored', graph_state: 'not_configured', success: null, warnings: [{ code: 'memory_graph_unavailable', message: 'Local memory remains available' }] },
    { step: '', stage: 'memory_extraction', state: 'disabled', graph_state: 'disabled', success: null, warnings: [] },
    { step: '', stage: 'post_turn', status: 'completed', success: null, warnings: [] },
  ] })
  const f = await fixture('TrajectoryPanel.vue', { sessionId: 'scope-trace-session' }, payload)
  try {
    const rows = await f.page.locator('.turn-maintenance').allTextContents()
    assert.ok(rows[0].includes('维护 · 记忆检索：未明确结果'), rows[0])
    assert.ok(rows[0].includes('Optional memory was skipped（memory_response_invalid）'), rows[0])
    assert.equal(rows[0].includes('完成'), false)
    assert.ok(rows[1].includes('维护 · 记忆提取：已保存'), rows[1])
    assert.ok(rows[1].includes('图谱状态：未配置'), rows[1])
    assert.ok(rows[1].includes('Local memory remains available（memory_graph_unavailable）'), rows[1])
    assert.ok(rows[2].includes('维护 · 记忆提取：已关闭'), rows[2])
    assert.ok(rows[3].includes('维护 · 回合后处理：完成'), rows[3])
    assert.deepEqual(await f.page.evaluate(() => window.fixtureResponse), payload)
    assert.deepEqual(f.errors, [])
  } finally { await f.close() }
})

test('actual maintenance DOM prioritizes explicit status and retains legacy results and unknown errors', async () => {
  const payload = response({ maintenance: [
    { stage: 'attachment_preparation', status: 'failed', success: true, error: '文件损坏 <img src=x onerror=alert(1)>', warnings: [] },
    { step: 'legacy-step', success: true, error: '' },
    { step: 'legacy-failed', success: false, error: 'legacy_error' },
    { stage: 'future_stage', state: 'future_state', graph_state: '__proto__', success: null, warnings: [{ code: 'constructor', message: 'unknown warning' }] },
    { step: '', success: null, warnings: [] },
  ] })
  const f = await fixture('TrajectoryPanel.vue', { sessionId: 'scope-trace-session' }, payload)
  try {
    const rows = await f.page.locator('.turn-maintenance').allTextContents()
    assert.ok(rows[0].includes('维护 · 附件准备：失败'), rows[0])
    assert.ok(rows[0].includes('文件损坏 <img src=x onerror=alert(1)>'), rows[0])
    assert.equal(rows[0].includes('完成'), false)
    assert.ok(rows[1].includes('维护 · legacy-step：完成'), rows[1])
    assert.ok(rows[2].includes('维护 · legacy-failed：失败（legacy_error）'), rows[2])
    assert.ok(rows[3].includes('维护 · future_stage：future_state'), rows[3])
    assert.ok(rows[3].includes('图谱状态：__proto__'), rows[3])
    assert.ok(rows[3].includes('unknown warning（constructor）'), rows[3])
    assert.ok(rows[4].includes('维护 · 阶段未记录：未明确结果'), rows[4])
    assert.equal(await f.page.locator('.turn-maintenance img').count(), 0)
    assert.deepEqual(f.errors, [])
  } finally { await f.close() }
})
