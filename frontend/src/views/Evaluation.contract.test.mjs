import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const read = (path) => readFileSync(resolve(import.meta.dirname, path), 'utf8')
const evaluation = read('./Evaluation.vue')
const api = read('../api/index.ts')

for (const datasetId of ['open_rag_benchmark_180', 'open_rag_benchmark_full']) {
  assert.match(evaluation, new RegExp(datasetId), `workbench should expose ${datasetId}`)
}
assert.match(evaluation, /datasetId\s*=\s*ref\(['"]public:open_rag_benchmark_180@arxiv-v1['"]\)/, 'the fixed public subset should be selected by default')
assert.match(evaluation, /open_rag_benchmark_180[\s\S]*180/, 'the public subset should contain exactly 180 questions')
assert.match(evaluation, /open_rag_benchmark_full[\s\S]*3045/, 'the public full set should contain exactly 3045 questions')

assert.match(evaluation, /v-if="!isOpenDataset"[^>]*class="question-type-field"|class="question-type-field"[^>]*v-if="!isOpenDataset"/, 'question types should only render for tenant datasets')
assert.match(evaluation, /v-if="!isOpenDataset"[^>]*class="review-mode-row"|class="review-mode-row"[^>]*v-if="!isOpenDataset"/, 'review and generation controls should only render for tenant datasets')
assert.match(evaluation, /review_sampled/, 'sample review should use the server-selected fixed-seed sample')
assert.doesNotMatch(evaluation, /deterministicSample\(questions\.value,\s*5\)/, 'sample review must not silently hard-code five questions')
assert.match(evaluation, /const chunkingStrategies = ref<string\[\]>\(\['auto_parent_child'\]\)/, 'only auto parent-child should be enabled by default')
assert.match(evaluation, /v-model="chunkingStrategies"/, 'chunking strategies should be independently selectable')
assert.match(evaluation, /semantic_parent_child/, 'semantic chunking should remain an explicit option')
assert.match(evaluation, /const rerankEnabled = ref\(true\)/, 'reranking should have an explicit toggle')
assert.match(evaluation, /v-model="rerankEnabled"/, 'reranking toggle should be bound to run configuration')

assert.match(evaluation, /answerModelId/, 'answer model selection should be separate')
assert.match(evaluation, /judgeModelId/, 'judge model selection should be separate')
assert.match(evaluation, /isChatCapableModel/, 'model options should use a strict chat-capability predicate')
assert.doesNotMatch(evaluation, /\|\|\s*item\.is_default/, 'default non-chat models must not enter answer or judge options')
assert.match(evaluation, /answer_model_id/, 'run payload should include answer_model_id')
assert.match(evaluation, /judge_model_id/, 'run payload should include judge_model_id')

assert.match(evaluation, /api\.ragEvalRunCreate\(/, 'all evaluations should use the unified run creation endpoint')
assert.match(evaluation, /type:\s*['"]open_dataset['"]/, 'public runs should use an open_dataset source')
assert.match(evaluation, /type:\s*['"]tenant_dataset['"]/, 'tenant runs should use a tenant_dataset source')
assert.match(evaluation, /api\.ragEvalRunActive\(/, 'active run restoration should query the server')
assert.match(evaluation, /api\.ragEvalRunStatus\(/, 'run progress should use the unified status endpoint')
assert.match(evaluation, /api\.ragEvalRunCancel\(/, 'run cancellation should use the unified cancel endpoint')
assert.match(evaluation, /api\.ragEvalRunResume\(/, 'run continuation should resume the same run id')
assert.match(evaluation, /api\.ragEvalRunEstimate\(/, 'full runs should request a server estimate before confirmation')
assert.doesNotMatch(evaluation, /sessionStorage/, 'run restoration must not depend on tab-local storage')
assert.doesNotMatch(evaluation, /ragEvalOpenRun/, 'the workbench should not use the legacy open-run client')
assert.doesNotMatch(evaluation, /Promise\.allSettled\([\s\S]{0,300}ragEvalRetrievalRun/, 'tenant evaluation should not fan out legacy synchronous requests')

assert.match(evaluation, /payload\?\.metrics\s*\|\|\s*\{\}/, 'metrics should be read from the unified metrics object')
assert.match(evaluation, /chunkingMetrics/, 'selected chunking strategy metrics should be visible')
assert.match(evaluation, /分块策略指标/, 'the workbench should label the chunking comparison')
assert.doesNotMatch(evaluation, /payload\?\.results\s*\|\|\s*payload\?\.partial_metrics/, 'metrics should not accept ambiguous legacy result containers')
assert.doesNotMatch(evaluation, /mrr[^\n]*\?\?[^\n]*strategy/, 'retrieval MRR must not fall back to chunking metrics')
assert.doesNotMatch(evaluation, /context_precision[^\n]*\?\?[^\n]*strategy/, 'RAG context precision must not fall back to chunking metrics')
assert.match(evaluation, /value == null/, 'null and undefined metric values should remain empty')
for (const label of ['已完成题目', '失败题目', '有效覆盖率', '耗时', '预计剩余', '取消评测', '继续评测']) {
  assert.match(evaluation, new RegExp(label), `workbench should show ${label}`)
}

for (const method of ['ragEvalRunCreate', 'ragEvalRunActive', 'ragEvalRunStatus', 'ragEvalRunCancel', 'ragEvalRunResume', 'ragEvalRunEstimate']) {
  assert.match(api, new RegExp(`\\b${method}\\s*:`), `API client should expose ${method}`)
}
assert.match(api, /post\(['"]\/api\/v1\/rag-eval\/runs['"]/, 'run creation should POST to /rag-eval/runs')
assert.match(api, /get\(['"]\/api\/v1\/rag-eval\/runs['"]/, 'active-run restoration should GET /rag-eval/runs')
assert.match(api, /\/resume/, 'API client should expose the resume path')
assert.match(api, /\/estimate/, 'API client should expose the estimate path')

console.log('evaluation workbench contract assertions passed')
