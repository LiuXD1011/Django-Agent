import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import vm from 'node:vm'
import { transformSync } from 'esbuild'
import { parse, compileScript, compileTemplate } from '@vue/compiler-sfc'

const require = createRequire(import.meta.url)
const vue = require('vue')
const { renderToString } = require('@vue/server-renderer')
const { descriptor } = parse(readFileSync(new URL('./Evaluation.vue', import.meta.url), 'utf8'))
const compiled = compileScript(descriptor, { id: 'evaluation-behavior' })
const script = transformSync(compiled.content, { loader: 'ts', format: 'cjs', target: 'es2022' }).code
const template = transformSync(compileTemplate({ source: descriptor.template.content, filename: 'Evaluation.vue', id: 'evaluation-behavior' }).code, { format: 'cjs', target: 'es2022' }).code
function mountEvaluation({ api = {}, confirm = () => true } = {}) {
  const notices = []; const confirmations = [];
  const scope = vue.effectScope()
  const context = vm.createContext({ module: { exports: {} }, console, Date, window: { setInterval: () => 1, clearInterval: () => {}, confirm: (text) => { confirmations.push(text); return confirm(text) } },
    require: (name) => {
      if (name === 'vue') return { ...vue, onMounted: () => {}, onBeforeUnmount: () => {} }
      if (name === '../api') return { api }
      if (name === 'tdesign-vue-next') return { MessagePlugin: Object.fromEntries(['error', 'warning', 'success'].map(kind => [kind, text => notices.push({ kind, text })])) }
      throw new Error(`Unexpected import: ${name}`)
    },
  })
  vm.runInContext(script, context)
  const component = context.module.exports.default
  const b = scope.run(() => component.setup({}, { expose: () => {} }))
  context.module = { exports: {} };vm.runInContext(template, context)
  return { b, notices, confirmations, render: () => renderToString(vue.createSSRApp({ setup: () => ({ ...b }), render: context.module.exports.render })), dispose: () => scope.stop() }
}

test('dataset provenance version does not mark an unchanged tenant form as changed', () => {
  const { b, dispose } = mountEvaluation()
  try {
    const source = { type: 'tenant_dataset', dataset_id: 'fixture-set', knowledge_base_id: 'fixture-kb' }
    const base = { source, chunking_strategies: ['auto_parent_child'], retrieval_strategy: 'hybrid', rerank_enabled: true }
    assert.equal(b.stableConfiguration(base), b.stableConfiguration({ ...base, source: { ...source, dataset_version: '2' } }))
    assert.notEqual(b.stableConfiguration(base), b.stableConfiguration({ ...base, rerank_enabled: false }))
  } finally { dispose() }
})

test('the available question count follows the approved published subset', async () => {
  const { b, render, dispose } = mountEvaluation()
  try {
    b.datasetId.value = 'kb:fixture-kb'
    await vue.nextTick()
    b.questions.value = [{ id: 'approved', status: 'approved' }, { id: 'rejected-1', status: 'rejected' }, { id: 'rejected-2', status: 'rejected' }]
    b.selectedQuestionIds.value = ['approved']
    b.publishedQuestions.value = [b.questions.value[0]]
    const html = await render()
    assert.match(html, /1 个可用问题/)
    assert.doesNotMatch(html, /3 个可用问题/)
  } finally { dispose() }
})


test('full-run confirmation shows real bounded request estimates and unestimated indexing work', async () => {
  const { b, confirmations, dispose } = mountEvaluation({ api: { ragEvalRunEstimate: async () => ({ sample_size: 3045, effective_pipeline: { comparison_chunking_strategies: ['fixed_window'] }, estimated_model_requests: { lower_bound: 27405, upper_bound: 39585, excludes_corpus_index_and_semantic_embedding: true } }) } });
  try { await b.confirmFullRun({}); assert.match(confirmations[0], /27405[–-]39585/); assert.match(confirmations[0], /2 个分块策略/); assert.match(confirmations[0], /索引.*未估算|未估算.*索引/); assert.equal(b.estimatedCallCount({ estimated_model_calls: null }), null); } finally { dispose(); }
});

test('active run restoration accepts the core runs array and follows the real run identifier', async () => {
  const reads = []; const run = { run_id: 'actual-active', status: 'running', sample_size: 5 };
  const { b, dispose } = mountEvaluation({ api: { ragEvalRunActive: async () => ({ runs: [run] }), ragEvalRunStatus: async id => { reads.push(id); return run; } } });
  try { await b.restoreActiveRun(); await vue.nextTick(); assert.equal(b.activeRun.value?.run_id, 'actual-active'); assert.equal(b.running.value, true); assert.deepEqual(reads, ['actual-active']); } finally { dispose(); }
});

test('cancelled resume uses the new run id and does not retain the old report or scored metrics', async () => {
  const reads = []; const next = { run_id: 'new-run', status: 'queued', sample_size: 5, metrics: null, report: null };
  const { b, dispose } = mountEvaluation({ api: { ragEvalRunResume: async () => next, ragEvalRunStatus: async id => { reads.push(id); return next; } } });
  try { b.activeRun.value = { run_id: 'old-run', status: 'cancelled', report: { id: 'old-report' }, metrics: { rag: { faithfulness: 1 } } }; await b.resumeEvaluation(); await vue.nextTick(); assert.equal(b.activeRun.value.run_id, 'new-run'); assert.deepEqual(reads, ['new-run']); assert.equal(b.activeRun.value.report, null); assert.equal(b.metrics.value.find(item => item.label === 'Faithfulness').value, null); } finally { dispose(); }
});

for (const accepted of [false, true]) test(`unknown paid result requires explicit acknowledgement; accepted=${accepted}`, async () => {
  const calls = []; const { b, confirmations, dispose } = mountEvaluation({ confirm: () => accepted, api: { ragEvalRunResume: async (id, input = {}) => { calls.push({ id, input }); if (!input.acknowledge_unknown_paid_request) throw { status: 409, error: { code: 'paid_result_unknown', message: 'Outcome unknown' } }; return { run_id: 'resumed', status: 'queued' }; }, ragEvalRunStatus: async () => ({ run_id: 'resumed', status: 'queued' }) } });
  try { b.activeRun.value = { run_id: 'stopped', status: 'interrupted' }; await b.resumeEvaluation(); assert.equal(confirmations.length, 1); assert.match(confirmations[0], /重复.*费用|重复.*计费/); assert.equal(calls.length, accepted ? 2 : 1); if (accepted) assert.equal(calls[1].input.acknowledge_unknown_paid_request, true); else assert.equal(b.activeRun.value.run_id, 'stopped'); } finally { dispose(); }
});

test('real Ragas report metrics render measured values and sample count without filling unsupported metrics', async () => {
  const { b, render, dispose } = mountEvaluation({ api: { ragEvalHistory: async () => ({ history: [] }) } });
  try { b.applyRunStatus({ run_id: 'scored', status: 'completed', sample_size: 5, completed_questions: 5, verification_status: 'verified', metrics: { samples: 5, ragas: { faithfulness: 0.8, answer_relevancy: 0.6, context_precision: 0.9, verified: true }, retrieval: { hit_at_10: 0.4, mrr_at_10: 0.3, recall_at_20: 0.5, verified: true }, chunking_comparison: { strategies: { recursive: { mrr_at_10: 0.3, recall_at_20: 0.5, valid_coverage: 1, verified: true } } } } }); const html = await render(); assert.match(html, /80.0%/); assert.match(html, /已完成题目：5 \/ 5/); assert.match(html, /Ragas.*5.*题|5.*题.*Ragas/); assert.equal(b.metrics.value.find(item => item.label === 'Faithfulness').state, 'verified'); } finally { dispose(); }
});

test('server-derived public provenance and default model roles do not imply an edited form', () => {
  const { b, dispose } = mountEvaluation();
  try { const raw = b.runPayload(); assert.equal(b.stableConfiguration(raw), b.stableConfiguration({ ...raw, source: { ...raw.source, knowledge_base_id: 'public-derived', sample_size: 180, seed: 20260819 }, primary_chunking_strategy: 'auto_parent_child', comparison_chunking_strategies: [], answer_model_id: 'KnowledgeQA', judge_model_id: 'KnowledgeQA' })); } finally { dispose(); }
});

test('interrupted runs expose manual resume in the rendered task controls', async () => {
  const { b, render, dispose } = mountEvaluation(); try { b.applyRunStatus({ run_id: 'interrupted', status: 'interrupted', result_unknown: true }); assert.match(await render(), /继续评测/); } finally { dispose(); }
});

test('a delayed poll for the old run cannot replace a newly resumed run', async () => {
  let release
  const waiting = new Promise(resolve => { release = resolve })
  const { b, dispose } = mountEvaluation({ api: { ragEvalRunStatus: async () => waiting, ragEvalRunResume: async () => ({ run_id: 'new-after-cancel', status: 'queued', sample_size: 5 }) } })
  try {
    b.activeRun.value = { run_id: 'old-polled', status: 'cancelled' }
    const poll = b.refreshRunStatus('old-polled')
    await b.resumeEvaluation()
    release({ run_id: 'old-polled', status: 'cancelled' })
    await poll
    assert.equal(b.activeRun.value.run_id, 'new-after-cancel')
    assert.equal(b.activeRun.value.status, 'queued')
  } finally { dispose() }
})

test('missing per-question failure counts stay unknown and pending candidates are not usable questions', async () => {
  const { b, render, dispose } = mountEvaluation()
  try {
    b.datasetId.value = 'kb:fixture'; await vue.nextTick()
    b.questions.value = [{ id: 'candidate', status: 'pending_review' }]; b.selectedQuestionIds.value = ['candidate']
    b.applyRunStatus({ run_id: 'failed-run', status: 'failed', sample_size: 5, completed_questions: 0 })
    const html = await render(); assert.match(html, /失败题目：--/); assert.match(html, /0 个可用问题/)
  } finally { dispose() }
})

test('publication uses the actual approved server entries instead of pending local candidates', async () => {
  const entry = { id: 'approved-after-review', question: 'Actual question', status: 'approved' }
  const { b, render, dispose } = mountEvaluation({ api: { ragEvalDatasetReview: async () => ({ id: 'published-dataset', status: 'published', entries: [entry], version: 1 }) } })
  try {
    b.datasetId.value = 'kb:fixture'; await vue.nextTick(); b.datasetResourceId.value = 'published-dataset'; b.reviewMode.value = 'manual'
    b.questions.value = [{ ...entry, status: 'pending_review' }]; b.selectedQuestionIds.value = [entry.id]
    await b.publishDataset(); assert.equal(b.publishedQuestions.value[0].status, 'approved'); assert.equal(b.activeQuestions.value.length, 1); assert.match(await render(), /1 个可用问题/)
  } finally { dispose() }
})

test('restoring a tenant run reloads its actual published dataset so it remains usable after restart', async () => {
  const entries = Array.from({ length: 5 }, (_, index) => ({ id: String(index), status: 'approved' }))
  const run = { run_id: 'restored-tenant', status: 'running', requested_configuration: { source: { type: 'tenant_dataset', dataset_id: 'published-snapshot', knowledge_base_id: 'fixture-kb' }, primary_chunking_strategy: 'recursive', comparison_chunking_strategies: [], retrieval_strategy: 'keyword', rerank_enabled: false }, sample_size: 5 }
  const { b, dispose } = mountEvaluation({ api: { ragEvalRunActive: async () => ({ active_run: run }), ragEvalRunStatus: async () => run, ragEvalDataset: async id => { assert.equal(id, 'published-snapshot'); return { id, status: 'published', entries }; } } })
  try { await b.restoreActiveRun(); await vue.nextTick(); assert.equal(b.activeQuestions.value.length, 5); assert.equal(b.datasetReady.value, true); assert.equal(b.datasetResourceId.value, 'published-snapshot') } finally { dispose() }
})

test('saved published and draft datasets can be refreshed and explicitly reused without an active run', async () => {
  const saved = { id: 'saved-set', knowledge_base_id: 'fixture-kb', name: 'Reusable sea salt', status: 'published', version: 2, entries: [{ id: 'q', question: 'Salt?', reference_answer: 'Sea', status: 'approved', evidence: [{ source_quote: 'Sea salt' }] }] }
  const { b, render, dispose } = mountEvaluation({ api: { ragEvalDatasets: async () => ({ datasets: [saved] }), ragEvalTestsets: async () => ({ testsets: [] }), ragEvalDataset: async () => saved } })
  try { await b.loadSavedDatasets(); b.savedDatasetSelection.value = saved.id; await b.loadSelectedDataset(); assert.equal(b.datasetReady.value, true); assert.equal(b.datasetResourceId.value, saved.id); assert.equal(b.runPayload().source.knowledge_base_id, 'fixture-kb'); assert.match(await render(), /Reusable sea salt/); assert.match(await render(), /版本 2.*已发布/); } finally { dispose() }
})

test('candidate editing preserves source evidence, updates all answer aliases, and resets approval using server DTO', async () => {
  const calls = [], evidence = [{ knowledge_id: 'doc', source_start: 0, source_end: 8, source_quote: 'Sea salt' }]
  const entry = { id: 'q', question: 'Salt?', answer: 'Old', reference_answer: 'Old', ground_truth: 'Old', status: 'approved', evidence }
  const { b, render, dispose } = mountEvaluation({ api: { ragEvalDatasetEditEntry: async (id, entryId, patch) => { calls.push({ id, entryId, patch }); return { id, knowledge_base_id: 'fixture-kb', status: 'draft', version: 1, entries: [{ ...entry, ...patch, status: 'pending_review' }] } } } })
  try { await b.applyDataset({ id: 'draft', knowledge_base_id: 'fixture-kb', status: 'draft', entries: [entry] }); b.beginCandidateEdit(entry); b.candidateEditAnswer.value = 'Sea'; await b.saveCandidateEdit(); assert.equal(calls[0].patch.reference_answer, 'Sea'); assert.equal(calls[0].patch.ground_truth, 'Sea'); assert.equal(b.questions.value[0].status, 'pending_review'); assert.equal(b.questions.value[0].evidence[0].source_quote, 'Sea salt'); assert.equal(b.publishedQuestions.value.length, 0); assert.match(await render(), /Sea salt/); } finally { dispose() }
})

test('published datasets stay immutable while a new version is editable and individual candidates can be deleted', async () => {
  const calls = [], old = { id: 'v1', knowledge_base_id: 'fixture-kb', status: 'published', version: 1, entries: [{ id: 'q', status: 'approved', question: 'Salt?', reference_answer: 'Sea', evidence: [] }] }
  const { b, dispose } = mountEvaluation({ api: { ragEvalDatasetVersion: async id => { calls.push(['version', id]); return { ...old, id: 'v2', status: 'draft', version: 2, entries: [{ ...old.entries[0], status: 'pending_review' }] } }, ragEvalDatasetDeleteEntry: async (id, q) => { calls.push(['delete', id, q]); return { ...old, id, status: 'draft', version: 2, entries: [] } } } })
  try { await b.applyDataset(old); b.beginCandidateEdit(old.entries[0]); assert.equal(b.candidateEditId.value, ''); await b.createDatasetVersion(); assert.equal(b.datasetResourceId.value, 'v2'); assert.equal(b.datasetStatus.value, 'draft'); assert.equal(b.datasetReady.value, false); await b.deleteCandidate(b.questions.value[0]); assert.equal(b.questions.value.length, 0); assert.deepEqual(calls, [['version', 'v1'], ['delete', 'v2', 'q']]); } finally { dispose() }
})

test('standalone chunking metrics cannot be labelled as Ragas scores', async () => {
  const { b, render, dispose } = mountEvaluation({ api: { ragEvalChunkingRun: async () => ({ run_id: 'chunking-result', evaluation_type: 'chunking', status: 'completed', verification_status: 'verified', sample_size: 5, completed_questions: 5, metrics: { samples: 5, primary_strategy: 'recursive', primary: { mrr_at_10: 1, recall_at_20: 1, context_precision: 1, verified: true }, strategies: { recursive: { mrr_at_10: 1, verified: true } } } }), ragEvalHistory: async () => ({ history: [] }) } })
  try { await b.applyDataset({ id: 'ready', status: 'published', knowledge_base_id: 'fixture-kb', entries: [{ id: 'q', status: 'approved' }] }); await b.runDeterministicEvaluation('chunking'); assert.equal(b.metrics.value.find(item => item.label === 'Faithfulness').value, null); assert.doesNotMatch(await render(), /Ragas 实际评分：5/); assert.match(await render(), /仅检索评测/); assert.match(await render(), /仅分块评测/); } finally { dispose() }
})

test('partial generated drafts clearly show retained candidates and safe failure state', async () => {
  const { b, render, dispose } = mountEvaluation()
  try { await b.applyDataset({ id: 'partial', knowledge_base_id: 'fixture-kb', status: 'draft', version: 1, generation: { status: 'failed', completed_count: 1, requested_count: 3, error_code: 'evaluation_generation_invalid', result_unknown: false }, entries: [{ id: 'q', question: 'Salt?', reference_answer: 'Sea', status: 'pending_review' }] }); const html = await render(); assert.match(html, /生成未完成.*1.*3/); assert.match(html, /evaluation_generation_invalid/); assert.match(html, /保留的候选题仍可编辑审核/); assert.equal(b.datasetReady.value, false); } finally { dispose() }
})

test('a running generation checkpoint blocks edits and publication instead of advertising editable candidates', async () => {
  const entry = { id: 'q', question: 'Salt?', reference_answer: 'Sea', status: 'pending_review' }
  const calls = []; const { b, render, dispose } = mountEvaluation({ api: { ragEvalDatasetReview: async () => { calls.push('publish'); return {} } } })
  try { await b.applyDataset({ id: 'running-draft', knowledge_base_id: 'fixture-kb', status: 'draft', generation: { status: 'running', completed_count: 1, requested_count: 3 }, entries: [entry] }); b.beginCandidateEdit(entry); assert.equal(b.candidateEditId.value, ''); await b.publishDataset(); assert.equal(calls.length, 0); const html = await render(); assert.match(html, /生成进行中/); assert.doesNotMatch(html, /保留的候选题仍可编辑审核/); } finally { dispose() }
})
