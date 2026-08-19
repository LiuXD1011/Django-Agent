import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const read = (path) => readFileSync(resolve(import.meta.dirname, path), 'utf8')
const evaluation = read('./Evaluation.vue')
const api = read('../api/index.ts')
const router = read('../router/index.ts')
const platform = read('./Platform.vue')

assert.match(router, /path:\s*'evaluation'/, 'evaluation workbench route should be registered')
assert.match(router, /Evaluation/, 'evaluation route should load the workbench view')
assert.match(platform, /评测工作台/, 'platform navigation should expose the evaluation workbench')
assert.match(platform, /Settings RAG/, 'platform navigation should retain the Settings RAG compatibility entry')

for (const mode of ['auto', 'manual', 'sample']) {
  assert.match(evaluation, new RegExp(`['\"]${mode}['\"]`), `workbench should support ${mode} review mode`)
}
assert.match(evaluation, /v-if="reviewMode !== 'auto'"/, 'manual and sample modes should render a review list')
assert.match(evaluation, /发布评估集/, 'auto mode should provide a publish action')

for (const label of ['数据集', '问题数量', '问题类型', '分块策略', '检索策略', 'Judge 模型', 'Hit@10', 'MRR@10', 'Recall@20', 'Context Precision', 'Faithfulness', 'Answer Relevancy']) {
  assert.match(evaluation, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')), `workbench should render ${label}`)
}
assert.match(evaluation, /verified|unverified|stale/, 'workbench should visibly distinguish result verification state')
assert.match(evaluation, /下载报告/, 'workbench should provide report download')
assert.match(evaluation, /responseData\(response/, 'workbench should normalize wrapped and unwrapped API responses')

for (const method of ['ragEvalGenerate', 'ragEvalQuestions', 'ragEvalRun', 'ragEvalRetrievalRun', 'ragEvalChunkingRun', 'ragEvalReportUrl']) {
  assert.match(api, new RegExp(`\\b${method}\\s*:`), `API client should expose ${method}`)
}

console.log('evaluation workbench contract assertions passed')
