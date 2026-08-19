<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { api } from '../api'

type ReviewMode = 'auto' | 'manual' | 'sample'
type VerificationState = 'verified' | 'unverified' | 'stale'
type Metric = { label: string; value: number | null; state: VerificationState; source: string }

const reviewMode = ref<ReviewMode>('manual')
const datasetId = ref('question-set')
const questionCount = ref(10)
const questionTypes = ref<string[]>(['simple', 'reasoning'])
const chunkingStrategy = ref('auto_parent_child')
const retrievalStrategy = ref('hybrid')
const judgeModel = ref('')
const questions = ref<any[]>([])
const selectedQuestionIds = ref<string[]>([])
const knowledgeBases = ref<any[]>([])
const models = ref<any[]>([])
const history = ref<any[]>([])
const generating = ref(false)
const running = ref(false)
const publishing = ref(false)
const runStatus = ref<'idle' | 'generating' | 'ready' | 'running' | 'completed' | 'partial' | 'failed'>('idle')
const publishedQuestions = ref<any[]>([])
const results = ref<{ rag?: any; retrieval?: any; chunking?: any; state: VerificationState; completedAt?: string }>({ state: 'unverified' })

const questionTypeOptions = [
  { value: 'simple', label: '事实问答' },
  { value: 'reasoning', label: '推理问答' },
  { value: 'multi-context', label: '多段落问答' },
]
const chunkingOptions = [
  { value: 'fixed_window', label: '固定窗口' },
  { value: 'recursive', label: '递归分块' },
  { value: 'auto_parent_child', label: '自适应父子块' },
  { value: 'semantic_parent_child', label: '语义父子块' },
]
const retrievalOptions = [
  { value: 'hybrid', label: '混合检索' },
  { value: 'vector', label: '向量检索' },
  { value: 'keyword', label: '关键词检索' },
]

function responseData(response: any) {
  return response?.data || response || {}
}

function asArray(value: any): any[] {
  return Array.isArray(value) ? value : []
}

function responseMessage(error: any, fallback: string) {
  return error?.error?.message || error?.message || error?.response?.data?.message || fallback
}

function questionId(question: any, index: number) {
  return String(question?.id || `question-${index}`)
}

function normalizeQuestions(raw: any) {
  const payload = responseData(raw)
  const entries = asArray(payload.questions || payload.items || payload)
  questions.value = entries.map((item, index) => ({ ...item, id: questionId(item, index) }))
  selectedQuestionIds.value = questions.value.map((item) => String(item.id))
}

const datasetOptions = computed(() => [
  { value: 'question-set', label: `当前评估集（${questions.value.length} 题）` },
  ...knowledgeBases.value.map((item) => ({ value: `kb:${item.id}`, label: item.name || item.display_name || `知识库 ${item.id}` })),
])

const judgeOptions = computed(() => models.value
  .filter((item) => ['chat', 'llm', 'KnowledgeQA'].includes(String(item.role || item.type || '').toLowerCase()) || item.is_default)
  .map((item) => ({ value: String(item.name || item.id), label: item.display_name || item.name || item.id })))

const selectedQuestions = computed(() => questions.value.filter((item) => selectedQuestionIds.value.includes(String(item.id))))
const activeQuestions = computed(() => publishedQuestions.value.length ? publishedQuestions.value : selectedQuestions.value)
const reviewRows = computed(() => reviewMode.value === 'sample' ? questions.value.slice(0, Math.min(5, questions.value.length)) : questions.value)
const datasetReady = computed(() => publishedQuestions.value.length > 0)

function stateFor(payload: any): VerificationState {
  const raw = String(payload?.dataset_status || payload?.status || '').toLowerCase()
  if (raw === 'stale') return 'stale'
  return payload?.verified === true ? 'verified' : 'unverified'
}

function metricValue(value: any): number | null {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : null
}

const metrics = computed<Metric[]>(() => {
  const rag = results.value.rag || {}
  const retrieval = results.value.retrieval || {}
  const chunking = results.value.chunking || {}
  const strategy = chunking?.strategies?.[chunkingStrategy.value] || {}
  const retrievalState = stateFor(retrieval)
  const ragState = stateFor(rag)
  const chunkingState = stateFor(chunking)
  return [
    { label: 'Hit@10', value: metricValue(retrieval.hit_at_10_new), state: retrievalState, source: '检索评测' },
    { label: 'MRR@10', value: metricValue(retrieval.mrr_new ?? strategy.mrr_at_10), state: retrieval.mrr_new !== undefined ? retrievalState : chunkingState, source: retrieval.mrr_new !== undefined ? '检索评测' : '分块对比' },
    { label: 'Recall@20', value: metricValue(retrieval.recall_new ?? strategy.recall_at_20), state: retrieval.recall_new !== undefined ? retrievalState : chunkingState, source: retrieval.recall_new !== undefined ? '检索评测' : '分块对比' },
    { label: 'Context Precision', value: metricValue(rag.context_precision ?? strategy.context_precision), state: rag.context_precision !== undefined ? ragState : chunkingState, source: rag.context_precision !== undefined ? 'RAGAs' : '分块对比' },
    { label: 'Faithfulness', value: metricValue(rag.faithfulness), state: ragState, source: 'RAGAs' },
    { label: 'Answer Relevancy', value: metricValue(rag.answer_relevancy), state: ragState, source: 'RAGAs' },
  ]
})

function statusLabel(state: VerificationState) {
  return state === 'verified' ? 'verified' : state === 'stale' ? 'stale' : 'unverified'
}

function formatMetric(value: number | null) {
  return value === null ? '--' : `${(value * 100).toFixed(1)}%`
}

function formatDate(value: any) {
  if (!value) return '--'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false })
}

function historyState(item: any): VerificationState {
  if (String(item?.status || '').toLowerCase() === 'stale') return 'stale'
  const createdAt = item?.provenance?.created_at
  if (createdAt && Date.now() - new Date(createdAt).getTime() > 7 * 24 * 60 * 60 * 1000) return 'stale'
  return item?.verified === true ? 'verified' : 'unverified'
}

function selectedKnowledgeBaseId() {
  return datasetId.value.startsWith('kb:') ? datasetId.value.slice(3) : ''
}

async function loadWorkbench() {
  const [questionsResult, kbResult, modelResult, historyResult] = await Promise.allSettled([
    api.ragEvalQuestions(), api.searchKbs({ page: 1, page_size: 100 }), api.listModels(), api.ragEvalHistory(),
  ])
  if (questionsResult.status === 'fulfilled') normalizeQuestions(questionsResult.value)
  if (kbResult.status === 'fulfilled') {
    const payload = responseData(kbResult.value)
    knowledgeBases.value = asArray(payload.items || payload.knowledge_bases)
  }
  if (modelResult.status === 'fulfilled') {
    const payload = responseData(modelResult.value)
    models.value = asArray(payload.items || payload.models || payload)
  }
  if (historyResult.status === 'fulfilled') history.value = asArray(responseData(historyResult.value).history)
}

async function generateDataset() {
  generating.value = true
  runStatus.value = 'generating'
  try {
    const response: any = await api.ragEvalGenerate({
      num_questions: questionCount.value,
      question_types: questionTypes.value,
      ...(selectedKnowledgeBaseId() ? { knowledge_base_id: selectedKnowledgeBaseId() } : {}),
    })
    const payload = responseData(response)
    await loadQuestions()
    if (!questions.value.length && asArray(payload.questions).length) normalizeQuestions(payload.questions)
    runStatus.value = 'ready'
    MessagePlugin.success(`已生成 ${Number(payload.generated || 0)} 个问题`)
  } catch (error: any) {
    runStatus.value = 'failed'
    MessagePlugin.error(responseMessage(error, '生成评估集失败'))
  } finally {
    generating.value = false
  }
}

async function loadQuestions() {
  const response: any = await api.ragEvalQuestions()
  normalizeQuestions(response)
}

async function publishDataset() {
  const candidates = reviewMode.value === 'auto' ? questions.value : selectedQuestions.value
  if (!candidates.length) {
    MessagePlugin.warning('请先生成或选择至少一个评估问题')
    return
  }
  publishing.value = true
  try {
    publishedQuestions.value = candidates.map((item) => ({ ...item }))
    runStatus.value = 'ready'
    MessagePlugin.success(`评估集已发布，本次运行包含 ${publishedQuestions.value.length} 题`)
  } finally {
    publishing.value = false
  }
}

function selectedStrategyMetrics(payload: any) {
  return payload?.strategies?.[chunkingStrategy.value] || {}
}

async function runEvaluation() {
  if (!datasetReady.value) {
    MessagePlugin.warning('请先发布评估集')
    return
  }
  running.value = true
  runStatus.value = 'running'
  results.value = { state: 'unverified' }
  const ragPayload = {
    questions: activeQuestions.value.map(({ question, ground_truth }) => ({ question, ground_truth })),
    ...(judgeModel.value ? { eval_llm_model: judgeModel.value } : {}),
    ...(selectedKnowledgeBaseId() ? { knowledge_base_id: selectedKnowledgeBaseId() } : {}),
  }
  const retrievalPayload = selectedKnowledgeBaseId() ? { knowledge_base_id: selectedKnowledgeBaseId(), strategy: retrievalStrategy.value } : { strategy: retrievalStrategy.value }
  try {
    const settled = await Promise.allSettled([
      api.ragEvalRun(ragPayload),
      api.ragEvalRetrievalRun(retrievalPayload),
      api.ragEvalChunkingRun(),
    ])
    const [ragResult, retrievalResult, chunkingResult] = settled
    const rag = ragResult.status === 'fulfilled' ? responseData(ragResult.value) : undefined
    const retrieval = retrievalResult.status === 'fulfilled' ? responseData(retrievalResult.value) : undefined
    const chunking = chunkingResult.status === 'fulfilled' ? responseData(chunkingResult.value) : undefined
    const everyVerified = [rag, retrieval, chunking].every((item) => item?.verified === true)
    const someCompleted = [rag, retrieval, chunking].some(Boolean)
    results.value = {
      rag,
      retrieval,
      chunking,
      state: everyVerified ? 'verified' : 'unverified',
      completedAt: new Date().toISOString(),
    }
    runStatus.value = everyVerified ? 'completed' : someCompleted ? 'partial' : 'failed'
    await loadHistory()
    if (everyVerified) MessagePlugin.success('评测完成')
    else MessagePlugin.warning('评测返回了未验证或不完整结果，请查看状态说明')
  } catch (error: any) {
    runStatus.value = 'failed'
    MessagePlugin.error(responseMessage(error, '运行评测失败'))
  } finally {
    running.value = false
  }
}

async function loadHistory() {
  const response: any = await api.ragEvalHistory()
  history.value = asArray(responseData(response).history)
}

async function downloadReport(item: any) {
  const runId = String(item?.run_id || '')
  if (!runId) {
    MessagePlugin.warning('该记录没有可下载的报告')
    return
  }
  try {
    const response: any = await api.ragEvalReport(runId)
    const blob = response instanceof Blob ? response : new Blob([JSON.stringify(responseData(response), null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `rag-eval-${runId}.json`
    link.click()
    URL.revokeObjectURL(url)
  } catch (error: any) {
    MessagePlugin.error(responseMessage(error, '下载报告失败'))
  }
}

onMounted(loadWorkbench)
</script>

<template>
  <main class="content evaluation-page">
    <header class="evaluation-header">
      <div>
        <span class="evaluation-kicker">Evaluation</span>
        <h2>评测工作台</h2>
        <p>生成、审核和运行可追溯的 RAG 评测。</p>
      </div>
      <div class="evaluation-run-state" :data-state="runStatus">
        <span class="state-dot"></span>{{ runStatus === 'running' ? '运行中' : runStatus === 'generating' ? '生成中' : runStatus === 'completed' ? '已完成' : runStatus === 'partial' ? '结果待确认' : runStatus === 'ready' ? '待运行' : '未开始' }}
      </div>
    </header>

    <section class="evaluation-config" aria-label="评测配置">
      <div class="evaluation-section-head"><h3>评估集</h3><span>{{ questions.length }} 个可用问题</span></div>
      <div class="evaluation-config-grid">
        <label>数据集
          <select v-model="datasetId" aria-label="数据集"><option v-for="option in datasetOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select>
        </label>
        <label>问题数量
          <input v-model.number="questionCount" aria-label="问题数量" type="number" min="1" max="50" />
        </label>
        <fieldset class="question-type-field"><legend>问题类型</legend>
          <label v-for="option in questionTypeOptions" :key="option.value" class="check-control"><input v-model="questionTypes" type="checkbox" :value="option.value" />{{ option.label }}</label>
        </fieldset>
        <label>分块策略
          <select v-model="chunkingStrategy" aria-label="分块策略"><option v-for="option in chunkingOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select>
        </label>
        <label>检索策略
          <select v-model="retrievalStrategy" aria-label="检索策略"><option v-for="option in retrievalOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select>
        </label>
        <label>Judge 模型
          <select v-model="judgeModel" aria-label="Judge 模型"><option value="">服务端默认模型</option><option v-for="option in judgeOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select>
        </label>
      </div>
      <div class="review-mode-row" aria-label="审核模式">
        <span>审核模式</span>
        <label v-for="mode in [{ value: 'auto', label: '自动审核' }, { value: 'manual', label: '人工审核' }, { value: 'sample', label: '抽样审核' }]" :key="mode.value" :class="{ active: reviewMode === mode.value }">
          <input v-model="reviewMode" type="radio" name="review-mode" :value="mode.value" />{{ mode.label }}
        </label>
        <button class="evaluation-generate" type="button" :disabled="generating || !questionTypes.length" @click="generateDataset">{{ generating ? '生成中...' : '生成评估集' }}</button>
        <button class="evaluation-publish" type="button" :disabled="publishing || !questions.length" @click="publishDataset">{{ publishing ? '发布中...' : '发布评估集' }}</button>
      </div>
    </section>

    <section v-if="reviewMode !== 'auto'" class="evaluation-review" aria-label="审核列表">
      <div class="evaluation-section-head"><div><h3>审核列表</h3><p>{{ reviewMode === 'sample' ? '从生成结果中抽取前 5 题进行确认。' : '选择纳入本次评测的问答对。' }}</p></div><span>{{ selectedQuestions.length }} / {{ questions.length }} 已选</span></div>
      <div v-if="reviewRows.length" class="review-list">
        <label v-for="(item, index) in reviewRows" :key="item.id" class="review-row">
          <input v-model="selectedQuestionIds" type="checkbox" :value="String(item.id)" />
          <span class="review-index">{{ index + 1 }}</span>
          <span><strong>{{ item.question }}</strong><small>{{ item.ground_truth || '未提供标准答案' }}</small></span>
          <span class="question-kind">{{ item.question_type || 'generated' }}</span>
        </label>
      </div>
      <div v-else class="evaluation-empty">生成评估集后在这里审核问题。</div>
    </section>

    <section class="evaluation-results" aria-label="评测结果">
      <div class="evaluation-section-head"><div><h3>评测指标</h3><p>仅显示接口返回的值；没有返回的指标保留为空。</p></div><button class="evaluation-run" type="button" :disabled="running || !datasetReady" @click="runEvaluation">{{ running ? '运行评测中...' : '运行评测' }}</button></div>
      <div class="metric-grid">
        <article v-for="metric in metrics" :key="metric.label" class="metric-card">
          <div><span>{{ metric.label }}</span><small>{{ metric.source }}</small></div>
          <strong>{{ formatMetric(metric.value) }}</strong>
          <span class="verification-tag" :class="metric.state">{{ statusLabel(metric.state) }}</span>
        </article>
      </div>
      <div class="evaluation-provenance"><span class="verification-tag" :class="results.state">{{ statusLabel(results.state) }}</span><span>完成时间：{{ formatDate(results.completedAt) }}</span><span v-if="results.chunking">分块结果：{{ selectedStrategyMetrics(results.chunking).questions ?? '--' }} 题</span></div>
    </section>

    <section class="evaluation-history" aria-label="评测历史">
      <div class="evaluation-section-head"><div><h3>报告历史</h3><p>报告由服务端生成并按当前租户范围下载。</p></div><button type="button" class="history-refresh" @click="loadHistory">刷新</button></div>
      <div v-if="history.length" class="history-table-wrap"><table><thead><tr><th>评测类型</th><th>评估器</th><th>数据集</th><th>生成时间</th><th>状态</th><th></th></tr></thead><tbody><tr v-for="item in history" :key="item.run_id"><td>{{ item.evaluation_type || '--' }}</td><td>{{ item.evaluator || '--' }}</td><td>{{ item.dataset?.entries ?? '--' }} 题</td><td>{{ formatDate(item.provenance?.created_at) }}</td><td><span class="verification-tag" :class="historyState(item)">{{ statusLabel(historyState(item)) }}</span></td><td><button type="button" class="report-download" :disabled="!item.run_id" @click="downloadReport(item)">下载报告</button></td></tr></tbody></table></div>
      <div v-else class="evaluation-empty">暂无评测报告。</div>
    </section>
  </main>
</template>
