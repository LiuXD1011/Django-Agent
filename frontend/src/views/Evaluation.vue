<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { api } from '../api'

type ReviewMode = 'auto' | 'manual' | 'sample'
type VerificationState = 'verified' | 'degraded' | 'unverified' | 'failed'
type FreshnessState = 'current' | 'stale' | 'unknown'
type EvaluationRunStatus = 'idle' | 'generating' | 'ready' | 'queued' | 'running' | 'completed' | 'partial' | 'failed' | 'cancelled'
type Metric = { label: string; value: number | null; state: VerificationState; source: string }
type OpenDataset = { id: string; version: string; label: string; count: number; documents: number; ready: boolean; status: string; progress: number; error?: string | null }
type EvaluationReport = { id?: string | null; report_id?: string | null; task_run_id?: string | null; url?: string | null; available?: boolean }
type EvaluationRun = {
  run_id: string
  status: EvaluationRunStatus
  source?: any
  stage?: string
  progress?: number
  stage_progress?: number
  completed_questions?: number
  total_questions?: number
  sample_size?: number
  failed_count?: number
  failed_questions?: number
  valid_coverage?: number | null
  elapsed_seconds?: number | null
  eta_seconds?: number | null
  estimated_remaining_seconds?: number | null
  metrics?: any
  requested_configuration?: any
  effective_pipeline?: any
  verification_status?: VerificationState
  freshness_status?: FreshnessState
  report?: EvaluationReport | null
  report_url?: string | null
  error?: string | null
  started_at?: string
  completed_at?: string
  verified?: boolean
}

const PUBLIC_DATASETS = [
  { id: 'open_rag_benchmark_180', version: 'arxiv-v1', label: 'Open RAG Benchmark', count: 180 },
  { id: 'open_rag_benchmark_full', version: 'arxiv-v1', label: 'Open RAG Benchmark', count: 3045 },
] as const

const reviewMode = ref<ReviewMode>('auto')
const datasetId = ref('public:open_rag_benchmark_180@arxiv-v1')
const questionCount = ref(180)
const questionTypes = ref<string[]>(['simple', 'reasoning'])
const chunkingStrategies = ref<string[]>(['auto_parent_child'])
const primaryChunkingStrategy = ref('auto_parent_child')
const comparisonChunkingStrategies = ref<string[]>([])
const retrievalStrategy = ref('hybrid')
const rerankEnabled = ref(true)
const answerModelId = ref('')
const judgeModelId = ref('')
const questions = ref<any[]>([])
const selectedQuestionIds = ref<string[]>([])
const knowledgeBases = ref<any[]>([])
const openDatasets = ref<OpenDataset[]>(PUBLIC_DATASETS.map((item) => ({ ...item, documents: 0, ready: false, status: 'not_ready', progress: 0 })))
const models = ref<any[]>([])
const history = ref<any[]>([])
const generating = ref(false)
const publishing = ref(false)
const preparingOpenDataset = ref(false)
const running = ref(false)
const cancelling = ref(false)
const stopRequested = ref(false)
const runStatus = ref<EvaluationRunStatus>('idle')
const publishedQuestions = ref<any[]>([])
const datasetResourceId = ref('')
const results = ref<{ primary?: any; comparisons?: any; rag?: any; retrieval?: any; chunking?: any; state: VerificationState; freshness: FreshnessState; requestedConfiguration?: any; effectivePipeline?: any; completedAt?: string }>({ state: 'unverified', freshness: 'unknown' })
const historyLoading = ref(false)
const historyError = ref('')
const deletingReportId = ref('')
const activeRun = ref<EvaluationRun | null>(null)
let runPollTimer: ReturnType<typeof window.setInterval> | null = null
let runPolling = false

const questionTypeOptions = [
  { value: 'simple', label: '事实问答' },
  { value: 'reasoning', label: '推理问答' },
  { value: 'multi-context', label: '多段落问答' },
]
const chunkingOptions = [
  { value: 'auto_parent_child', label: '自适应父子块（生产默认）' },
  { value: 'recursive', label: '递归分块（父子）' },
  { value: 'heading', label: '标题分块（父子）' },
  { value: 'layout', label: '版面分块（父子）' },
  { value: 'record', label: '记录分块（父子）' },
  { value: 'semantic_parent_child', label: '语义父子块' },
  { value: 'fixed_window', label: '固定窗口（基线·非生产策略）' },
]
const retrievalOptions = [
  { value: 'hybrid', label: '混合检索（生产形态）' },
  { value: 'vector', label: '向量检索（消融）' },
  { value: 'keyword', label: '关键词检索（消融）' },
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

const datasetOptions = computed(() => [
  ...openDatasets.value.map((item) => ({
    value: `public:${item.id}@${item.version}`,
    label: `${item.label}（${item.id.endsWith('_180') ? '固定子集' : '全集'}，${item.count} 题）`,
  })),
  ...knowledgeBases.value.map((item) => ({ value: `kb:${item.id}`, label: item.name || item.display_name || `知识库 ${item.id}` })),
])

const selectedOpenDataset = computed(() => {
  if (!datasetId.value.startsWith('public:')) return null
  const [id, version = 'arxiv-v1'] = datasetId.value.slice(7).split('@')
  return openDatasets.value.find((item) => item.id === id && item.version === version) || null
})
const isOpenDataset = computed(() => datasetId.value.startsWith('public:'))
const isFullOpenDataset = computed(() => selectedOpenDataset.value?.id === 'open_rag_benchmark_full')
const selectedDatasetCount = computed(() => selectedOpenDataset.value?.count || 0)
const selectedQuestions = computed(() => questions.value.filter((item) => selectedQuestionIds.value.includes(String(item.id))))
const activeQuestions = computed(() => publishedQuestions.value.length ? publishedQuestions.value : selectedQuestions.value)
const reviewRows = computed(() => {
  if (reviewMode.value !== 'sample') return questions.value
  const serverSample = questions.value.filter((item) => item.review_sampled === true)
  return serverSample.length
    ? serverSample
    : deterministicSample(questions.value, Math.max(1, Math.ceil(questions.value.length / 10)))
})
const datasetReady = computed(() => isOpenDataset.value ? selectedOpenDataset.value?.ready === true : Boolean(datasetResourceId.value && publishedQuestions.value.length))
const configLocked = computed(() => running.value)

watch([primaryChunkingStrategy, comparisonChunkingStrategies], () => {
  const comparisons = comparisonChunkingStrategies.value.filter((item) => item !== primaryChunkingStrategy.value)
  if (comparisons.length !== comparisonChunkingStrategies.value.length) {
    comparisonChunkingStrategies.value = comparisons
  }
  chunkingStrategies.value = [primaryChunkingStrategy.value, ...comparisons]
}, { deep: true })

function modelCapabilityValues(model: any): string[] {
  const values = [model?.model_type, model?.type, model?.raw_type, model?.role]
  if (Array.isArray(model?.roles)) values.push(...model.roles)
  return values.flatMap((value) => String(value || '').toLowerCase().split(/[\s,;|/]+/)).filter(Boolean)
}

function isChatCapableModel(model: any) {
  if (model?.status && String(model.status).toLowerCase() !== 'active') return false
  if (model?.deleted_at || model?.deletedAt) return false
  const chatCapabilities = new Set(['chat', 'knowledgeqa', 'llm', 'judge', 'answer', 'text-generation', 'text_generation'])
  return modelCapabilityValues(model).some((value) => chatCapabilities.has(value))
}

const chatModelOptions = computed(() => models.value
  .filter(isChatCapableModel)
  .map((item) => ({ value: String(item.id || item.name), label: item.display_name || item.name || item.id })))

function deterministicSample(items: any[], size: number) {
  return [...items]
    .map((item, index) => ({ item, score: seededScore(String(item?.id || index)) }))
    .sort((left, right) => left.score - right.score)
    .slice(0, Math.min(size, items.length))
    .map(({ item }) => item)
}

function seededScore(value: string) {
  let hash = 20260819
  for (const char of value) hash = Math.imul(hash ^ char.charCodeAt(0), 16777619)
  return hash >>> 0
}

function stateFor(payload: any): VerificationState {
  const status = String(payload?.verification_status || payload?.status || payload?.dataset_status || '').toLowerCase()
  if (status === 'verified') return 'verified'
  if (status === 'degraded' || status === 'partial') return 'degraded'
  if (status === 'failed') return 'failed'
  return payload?.verified === true ? 'verified' : 'unverified'
}

function metricValue(value: any): number | null {
  if (value == null || value === '') return null
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : null
}

const metrics = computed<Metric[]>(() => {
  const primary = results.value.primary || {}
  const rag = primary.rag || results.value.rag || {}
  const retrieval = primary.retrieval || results.value.retrieval || {}
  return [
    { label: 'Hit@10', value: metricValue(retrieval.hit_at_10 ?? retrieval.hit_at_10_new), state: stateFor(retrieval), source: '主分块策略 · Retrieval' },
    { label: 'MRR@10', value: metricValue(retrieval.mrr_at_10 ?? retrieval.mrr_new), state: stateFor(retrieval), source: '主分块策略 · Retrieval' },
    { label: 'Recall@20', value: metricValue(retrieval.recall_at_20 ?? retrieval.recall_new), state: stateFor(retrieval), source: '主分块策略 · Retrieval' },
    { label: 'Context Precision', value: metricValue(rag.context_precision), state: stateFor(rag), source: '主分块策略 · Ragas' },
    { label: 'Faithfulness', value: metricValue(rag.faithfulness), state: stateFor(rag), source: '主分块策略 · Ragas' },
    { label: 'Answer Relevancy', value: metricValue(rag.answer_relevancy), state: stateFor(rag), source: '主分块策略 · Ragas' },
  ]
})

const chunkingMetrics = computed(() => {
  const primaryName = results.value.requestedConfiguration?.primary_chunking_strategy || activeRun.value?.requested_configuration?.primary_chunking_strategy || primaryChunkingStrategy.value
  const primary = results.value.primary?.chunking || results.value.chunking?.primary || {}
  const comparisons = results.value.comparisons || results.value.chunking?.comparisons || results.value.chunking?.strategies || {}
  const all = primary && Object.keys(primary).length ? { [primaryName]: primary, ...comparisons } : comparisons
  return Object.entries(all).map(([strategy, raw]: [string, any]) => ({
    strategy,
    label: `${strategy === primaryName ? '主 · ' : '对比 · '}${chunkingOptions.find((item) => item.value === strategy)?.label || strategy}`,
    mrr: metricValue(raw?.mrr_at_10),
    recall: metricValue(raw?.recall_at_20),
    precision: metricValue(raw?.context_precision),
    coverage: metricValue(raw?.valid_coverage),
    state: stateFor(raw),
  }))
})

function formatMetric(value: number | null) {
  return value == null ? '--' : `${(value * 100).toFixed(1)}%`
}

function formatDate(value: any) {
  if (!value) return '--'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false })
}

function formatDuration(value: any) {
  if (value == null || !Number.isFinite(Number(value))) return '--'
  const seconds = Math.max(0, Math.round(Number(value)))
  if (seconds >= 3600) return `${Math.floor(seconds / 3600)} 小时 ${Math.floor((seconds % 3600) / 60)} 分`
  if (seconds >= 60) return `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`
  return `${seconds} 秒`
}

function historyState(item: any): VerificationState {
  return stateFor(item)
}

function statusLabel(state: VerificationState) {
  return state
}

function freshnessLabel(state?: string) {
  return state === 'current' ? 'current' : state === 'stale' ? 'stale' : 'unknown'
}

function runStatusLabel(status: EvaluationRunStatus) {
  return ({
    idle: '未开始', generating: '生成中', ready: '待运行', queued: '排队中', running: '运行中', completed: '已完成',
    partial: '部分完成', failed: '运行失败', cancelled: '已取消',
  } as Record<EvaluationRunStatus, string>)[status] || status
}

function selectedKnowledgeBaseId() {
  return datasetId.value.startsWith('kb:') ? datasetId.value.slice(3) : ''
}

watch(datasetId, (value) => {
  const source = activeRun.value?.requested_configuration?.source || {}
  const restoredValue = source.type === 'open_dataset'
    ? `public:${source.dataset_id}@${source.dataset_version || 'arxiv-v1'}`
    : source.type === 'tenant_dataset' ? `kb:${source.knowledge_base_id || ''}` : ''
  if (restoredValue && value === restoredValue) return
  datasetResourceId.value = ''
  publishedQuestions.value = []
  questions.value = []
  selectedQuestionIds.value = []
  results.value = { state: 'unverified', freshness: 'unknown' }
})

async function loadKnowledgeBases() {
  const payload = responseData(await api.searchKbs({ page: 1, page_size: 100 }))
  knowledgeBases.value = asArray(payload.items || payload.knowledge_bases)
}

async function loadModels() {
  const payload = responseData(await api.listModels())
  models.value = asArray(payload.items || payload.models || payload)
}

async function loadOpenDatasets() {
  const payload = responseData(await api.ragEvalOpenDatasets())
  const byId = new Map(asArray(payload.datasets).map((item) => [String(item.id), item]))
  openDatasets.value = PUBLIC_DATASETS.map((item) => ({
    ...item,
    documents: 0,
    ready: false,
    status: 'not_ready',
    progress: 0,
    ...(byId.get(item.id) || {}),
    count: item.count,
  }))
}

async function loadHistory() {
  historyLoading.value = true
  historyError.value = ''
  try {
    history.value = asArray(responseData(await api.ragEvalHistory()).history)
  } catch (error: any) {
    historyError.value = responseMessage(error, '报告历史加载失败')
  } finally {
    historyLoading.value = false
  }
}

async function refreshOpenDatasetStatus() {
  const dataset = selectedOpenDataset.value
  if (!dataset) return null
  const payload = responseData(await api.ragEvalOpenDatasetStatus(dataset.id))
  const index = openDatasets.value.findIndex((item) => item.id === dataset.id)
  if (index >= 0) openDatasets.value[index] = { ...openDatasets.value[index], ...payload, count: openDatasets.value[index].count }
  return payload
}

async function prepareOpenDataset() {
  const dataset = selectedOpenDataset.value
  if (!dataset || preparingOpenDataset.value) return
  preparingOpenDataset.value = true
  try {
    if (dataset.ready) {
      await refreshOpenDatasetStatus()
      return
    }
    await api.ragEvalOpenDatasetPrepare(dataset.id)
    for (let attempt = 0; attempt < 300; attempt += 1) {
      const payload = await refreshOpenDatasetStatus()
      if (payload?.ready === true && payload?.status === 'ready') {
        MessagePlugin.success('公开数据集已准备完成')
        return
      }
      if (payload?.status === 'failed') throw new Error(payload.error || '公开数据集准备失败')
      await new Promise((resolve) => window.setTimeout(resolve, 2000))
    }
    throw new Error('数据集仍在后台准备，请稍后刷新状态')
  } catch (error: any) {
    MessagePlugin.error(responseMessage(error, '准备公开数据集失败'))
  } finally {
    preparingOpenDataset.value = false
  }
}

async function generateDataset() {
  generating.value = true
  runStatus.value = 'generating'
  try {
    const payload = responseData(await api.ragEvalTestsetGenerate({
      testset_size: questionCount.value,
      review_mode: reviewMode.value,
      question_types: questionTypes.value,
      knowledge_base_id: selectedKnowledgeBaseId(),
      ...(judgeModelId.value ? { eval_llm_model: judgeModelId.value } : {}),
    }))
    datasetResourceId.value = String(payload.id || '')
    questions.value = asArray(payload.entries).map((item, index) => ({ ...item, id: questionId(item, index) }))
    selectedQuestionIds.value = questions.value.filter((item) => item.status !== 'rejected').map((item) => String(item.id))
    runStatus.value = 'ready'
    MessagePlugin.success(`已生成 ${Number(payload.generated ?? questions.value.length)} 个问题`)
  } catch (error: any) {
    runStatus.value = 'failed'
    MessagePlugin.error(responseMessage(error, '生成评估集失败'))
  } finally {
    generating.value = false
  }
}

async function publishDataset() {
  const candidates = reviewMode.value === 'auto'
    ? questions.value.filter((item) => item.status !== 'rejected')
    : selectedQuestions.value
  if (!datasetResourceId.value || !candidates.length) {
    MessagePlugin.warning('请先生成并选择至少一个评估问题')
    return
  }
  publishing.value = true
  try {
    if (reviewMode.value === 'sample') {
      const selected = new Set(selectedQuestionIds.value)
      const rejectedIds = reviewRows.value
        .filter((item) => !selected.has(String(item.id)))
        .map((item) => item.id)
      if (rejectedIds.length) {
        await api.ragEvalDatasetReview(datasetResourceId.value, {
          entry_ids: rejectedIds,
          status: 'rejected',
        })
      }
    }
    await api.ragEvalDatasetReview(datasetResourceId.value, {
      entry_ids: candidates.map((item) => item.id),
      status: 'approved',
      publish: true,
    })
    publishedQuestions.value = candidates.map((item) => ({ ...item }))
    runStatus.value = 'ready'
    MessagePlugin.success(`评估集已发布，本次运行包含 ${candidates.length} 题`)
  } catch (error: any) {
    MessagePlugin.error(responseMessage(error, '发布评估集失败'))
  } finally {
    publishing.value = false
  }
}

function isRunActive(status?: string) {
  return status === 'queued' || status === 'running'
}

function clearRunPolling() {
  if (runPollTimer !== null) window.clearInterval(runPollTimer)
  runPollTimer = null
}

function applyRunStatus(payload: any) {
  const runId = String(payload?.run_id || payload?.id || activeRun.value?.run_id || '')
  if (!runId) return
  const status = String(payload?.run_status || payload?.status || 'queued') as EvaluationRunStatus
  activeRun.value = { ...activeRun.value, ...payload, run_id: runId, status }
  if (payload?.requested_configuration) restoreConfiguration(payload.requested_configuration)
  runStatus.value = status
  running.value = isRunActive(status)
  const metricsPayload = payload?.metrics || {}
  const primary = metricsPayload.primary || {
    retrieval: metricsPayload.retrieval,
    rag: metricsPayload.rag,
  }
  results.value = {
    primary,
    comparisons: metricsPayload.comparisons || metricsPayload.chunking?.comparisons || metricsPayload.chunking?.strategies,
    rag: primary.rag,
    retrieval: primary.retrieval,
    chunking: metricsPayload.chunking,
    state: (payload?.verification_status || (payload?.verified === true ? 'verified' : 'unverified')) as VerificationState,
    freshness: (payload?.freshness_status || 'unknown') as FreshnessState,
    requestedConfiguration: payload?.requested_configuration,
    effectivePipeline: payload?.effective_pipeline,
    completedAt: payload?.completed_at,
  }
  if (!running.value) {
    clearRunPolling()
    if (status === 'completed' || status === 'partial') void loadHistory()
  }
}

async function refreshRunStatus(runId = activeRun.value?.run_id) {
  if (!runId || runPolling) return
  runPolling = true
  try {
    applyRunStatus(responseData(await api.ragEvalRunStatus(runId)))
  } catch (error: any) {
    if (isRunActive(activeRun.value?.status)) MessagePlugin.error(responseMessage(error, '获取评测进度失败'))
  } finally {
    runPolling = false
  }
}

function startRunPolling() {
  clearRunPolling()
  if (!activeRun.value?.run_id || !isRunActive(activeRun.value.status)) return
  void refreshRunStatus(activeRun.value.run_id)
  runPollTimer = window.setInterval(() => void refreshRunStatus(), 2000)
}

function runPayload() {
  const source = isOpenDataset.value
    ? { type: 'open_dataset', dataset_id: selectedOpenDataset.value?.id, dataset_version: selectedOpenDataset.value?.version }
    : { type: 'tenant_dataset', dataset_id: datasetResourceId.value, knowledge_base_id: selectedKnowledgeBaseId() }
  const canonical = {
    source,
    primary_chunking_strategy: primaryChunkingStrategy.value,
    comparison_chunking_strategies: [...comparisonChunkingStrategies.value],
    // One-release compatibility for older workers/API consumers.
    chunking_strategies: [...chunkingStrategies.value],
    retrieval_strategy: retrievalStrategy.value,
    rerank_enabled: rerankEnabled.value,
    ...(answerModelId.value ? { answer_model_id: answerModelId.value } : {}),
    ...(judgeModelId.value ? { judge_model_id: judgeModelId.value } : {}),
  }
  // Keep the exact legacy shape for the untouched default configuration for
  // one release; any non-default primary/comparison selection uses the new
  // explicit fields. The server normalizes both shapes identically.
  if (primaryChunkingStrategy.value === 'auto_parent_child' && !comparisonChunkingStrategies.value.length) {
    const { primary_chunking_strategy: _primary, comparison_chunking_strategies: _comparisons, ...legacy } = canonical
    return legacy
  }
  return canonical
}

function stableConfiguration(value: any) {
  const raw = value || {}
  const legacyStrategies = asArray(raw.chunking_strategies)
  const normalized = {
    source: raw.source || {},
    primary_chunking_strategy: raw.primary_chunking_strategy || legacyStrategies[0] || 'auto_parent_child',
    comparison_chunking_strategies: asArray(raw.comparison_chunking_strategies).length ? asArray(raw.comparison_chunking_strategies) : legacyStrategies.slice(1),
    retrieval_strategy: raw.retrieval_strategy,
    rerank_enabled: Boolean(raw.rerank_enabled),
    answer_model_id: raw.answer_model_id || '',
    judge_model_id: raw.judge_model_id || '',
  }
  return JSON.stringify(normalized)
}

function currentConfiguration() {
  return runPayload()
}

const configurationMismatch = computed(() => {
  const requested = activeRun.value?.requested_configuration
  if (!requested || isRunActive(activeRun.value?.status)) return false
  return stableConfiguration(requested) !== stableConfiguration(currentConfiguration())
})

function restoreConfiguration(configuration: any) {
  if (!configuration || typeof configuration !== 'object') return
  const source = configuration.source || {}
  if (source.type === 'open_dataset' && source.dataset_id) {
    datasetId.value = `public:${source.dataset_id}@${source.dataset_version || 'arxiv-v1'}`
  } else if (source.type === 'tenant_dataset') {
    datasetResourceId.value = String(source.dataset_id || '')
    if (source.knowledge_base_id) datasetId.value = `kb:${source.knowledge_base_id}`
  }
  if (configuration.primary_chunking_strategy) primaryChunkingStrategy.value = String(configuration.primary_chunking_strategy)
  comparisonChunkingStrategies.value = asArray(configuration.comparison_chunking_strategies).map(String).filter((item) => item !== primaryChunkingStrategy.value)
  chunkingStrategies.value = [primaryChunkingStrategy.value, ...comparisonChunkingStrategies.value]
  if (configuration.retrieval_strategy) retrievalStrategy.value = String(configuration.retrieval_strategy)
  if (typeof configuration.rerank_enabled === 'boolean') rerankEnabled.value = configuration.rerank_enabled
  answerModelId.value = String(configuration.answer_model_id || '')
  judgeModelId.value = String(configuration.judge_model_id || '')
}

function estimatedCallCount(estimate: any) {
  if (Number.isFinite(Number(estimate?.estimated_model_calls))) return Number(estimate.estimated_model_calls)
  const calls = estimate?.estimated_calls
  if (!calls || typeof calls !== 'object') return null
  return Object.values(calls).reduce((total: number, value) => total + (Number(value) || 0), 0)
}

async function confirmFullRun(payload: any) {
  const estimate = responseData(await api.ragEvalRunEstimate(payload))
  const duration = formatDuration(estimate.estimated_seconds)
  const calls = estimatedCallCount(estimate)
  const count = Number(estimate.sample_size ?? selectedDatasetCount.value)
  const strategyCount = Number(estimate.strategy_count ?? chunkingStrategies.value.length)
  return window.confirm(`将严格评测 ${count} 题、${strategyCount} 个分块策略。预计耗时：${duration}；预计模型调用：${calls ?? '--'} 次。确认继续吗？`)
}

async function runEvaluation() {
  stopRequested.value = false
  if (!datasetReady.value) {
    MessagePlugin.warning(isOpenDataset.value ? '请先准备公开数据集' : '请先发布评估集')
    return
  }
  if (!chunkingStrategies.value.length) {
    MessagePlugin.warning('请至少选择一种分块策略')
    return
  }
  const payload = runPayload()
  try {
    if (isFullOpenDataset.value && !(await confirmFullRun(payload))) return
    running.value = true
    runStatus.value = 'queued'
    results.value = { state: 'unverified', freshness: 'unknown' }
    const data = responseData(await api.ragEvalRunCreate(payload))
    if (!data?.run_id && !data?.id) throw new Error('评测任务未返回 run_id')
    applyRunStatus(data)
    if (stopRequested.value) {
      cancelling.value = false
      await cancelEvaluation()
      return
    }
    startRunPolling()
  } catch (error: any) {
    running.value = false
    cancelling.value = false
    stopRequested.value = false
    runStatus.value = 'failed'
    MessagePlugin.error(responseMessage(error, isFullOpenDataset.value ? '获取估算或创建评测任务失败' : '创建评测任务失败'))
  }
}

async function cancelEvaluation() {
  if (cancelling.value) return
  const runId = activeRun.value?.run_id
  if (!runId) {
    if (running.value) {
      stopRequested.value = true
      cancelling.value = true
    }
    return
  }
  if (!isRunActive(activeRun.value?.status)) return
  cancelling.value = true
  try {
    applyRunStatus(responseData(await api.ragEvalRunCancel(runId)))
    MessagePlugin.success('评测已停止')
  } catch (error: any) {
    MessagePlugin.error(responseMessage(error, '停止评测失败'))
    await refreshRunStatus(runId)
  } finally {
    cancelling.value = false
    stopRequested.value = false
  }
}

async function resumeEvaluation() {
  const runId = activeRun.value?.run_id
  if (!runId) return
  try {
    const payload = responseData(await api.ragEvalRunResume(runId))
    applyRunStatus({ ...payload, run_id: runId })
    startRunPolling()
  } catch (error: any) {
    MessagePlugin.error(responseMessage(error, '继续评测失败'))
  }
}

async function restoreActiveRun() {
  try {
    const payload = responseData(await api.ragEvalRunActive())
    const run = payload?.active_run || payload?.run || (payload?.run_id ? payload : null)
    if (!run?.run_id && !run?.id) return
    applyRunStatus(run)
    if (isRunActive(activeRun.value?.status)) startRunPolling()
  } catch {
    // No active run is a normal initial state.
  }
}

function reportIdFor(item: any) {
  const direct = item?.report_id || item?.report?.id || item?.id || item?.run_id
  if (direct) return String(direct)
  const url = String(item?.report_url || item?.report?.url || '')
  return url.split('/').filter(Boolean).pop() || ''
}

async function downloadReport(item: any) {
  const reportId = reportIdFor(item)
  if (!reportId || item?.available === false || item?.report?.available === false) {
    MessagePlugin.warning('该报告已不存在或不可下载')
    return
  }
  try {
    const response: any = await api.ragEvalReport(reportId)
    const blob = response instanceof Blob ? response : new Blob([JSON.stringify(responseData(response), null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `rag-eval-${reportId}.json`
    link.click()
    URL.revokeObjectURL(url)
  } catch (error: any) {
    const notFound = error?.response?.status === 404 || error?.status === 404 || error?.error?.code === 'report_not_found'
    if (notFound) {
      await loadHistory()
      MessagePlugin.warning('报告已不存在')
      return
    }
    MessagePlugin.error(responseMessage(error, '下载报告失败'))
  }
}

async function deleteReport(item: any) {
  const reportId = reportIdFor(item)
  if (!reportId || deletingReportId.value) return
  const dataset = item?.dataset || {}
  const requested = item?.requested_configuration || {}
  const confirmed = window.confirm(
    `确认删除报告？\n生成时间：${formatDate(item?.created_at || item?.provenance?.created_at)}\n数据集：${dataset.id || '--'}\n主分块：${requested.primary_chunking_strategy || '--'}\n检索：${requested.retrieval_strategy || '--'}\nRerank：${requested.rerank_enabled ? '开启' : '关闭'}`,
  )
  if (!confirmed) return
  deletingReportId.value = reportId
  try {
    await api.ragEvalDeleteReport(reportId)
    history.value = history.value.filter((entry) => reportIdFor(entry) !== reportId)
    if (activeRun.value && reportIdFor(activeRun.value) === reportId) {
      activeRun.value = { ...activeRun.value, report: { id: reportId, available: false, url: null } }
    }
    MessagePlugin.success('报告已删除')
  } catch (error: any) {
    const notFound = error?.response?.status === 404 || error?.status === 404 || error?.error?.code === 'report_not_found'
    if (notFound) {
      await loadHistory()
      if (activeRun.value && reportIdFor(activeRun.value) === reportId) activeRun.value = { ...activeRun.value, report: { id: reportId, available: false, url: null } }
      MessagePlugin.warning('报告已不存在')
    } else {
      MessagePlugin.error(responseMessage(error, '删除报告失败'))
    }
  } finally {
    deletingReportId.value = ''
  }
}

const completedQuestions = computed(() => Number(activeRun.value?.completed_questions ?? 0))
const totalQuestions = computed(() => Number(activeRun.value?.total_questions ?? activeRun.value?.sample_size ?? 0))
const failedCount = computed(() => Number(activeRun.value?.failed_count ?? activeRun.value?.failed_questions ?? 0))
const coverage = computed(() => metricValue(activeRun.value?.valid_coverage))
const elapsedSeconds = computed(() => {
  if (activeRun.value?.elapsed_seconds != null) return activeRun.value.elapsed_seconds
  if (!activeRun.value?.started_at) return null
  const start = new Date(activeRun.value.started_at).getTime()
  const end = activeRun.value.completed_at ? new Date(activeRun.value.completed_at).getTime() : Date.now()
  return Number.isFinite(start) && Number.isFinite(end) ? Math.max(0, (end - start) / 1000) : null
})
const etaSeconds = computed(() => activeRun.value?.eta_seconds ?? activeRun.value?.estimated_remaining_seconds ?? null)

onMounted(() => {
  void Promise.allSettled([loadKnowledgeBases(), loadModels(), loadHistory(), loadOpenDatasets(), restoreActiveRun()])
})

onBeforeUnmount(clearRunPolling)
</script>

<template>
  <main class="content evaluation-page">
    <header class="evaluation-header">
      <div><span class="evaluation-kicker">Evaluation</span><h2>评测工作台</h2><p>生成、审核和运行可追溯的 RAG 评测。</p></div>
      <div class="evaluation-run-state" :data-state="runStatus"><span class="state-dot"></span>{{ runStatusLabel(runStatus) }}</div>
    </header>

    <section class="evaluation-config" aria-label="评测配置">
      <div class="evaluation-section-head"><h3>评估集</h3><span>{{ isOpenDataset ? `${selectedDatasetCount} 个公开问题` : `${questions.length} 个可用问题` }}</span></div>
      <div class="evaluation-config-grid">
        <label class="config-control dataset-control">数据集<select v-model="datasetId" aria-label="数据集" :disabled="configLocked"><option v-for="option in datasetOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></label>
        <label v-if="!isOpenDataset" class="config-control question-count-control">问题数量<input v-model.number="questionCount" aria-label="问题数量" type="number" min="1" max="100" :disabled="configLocked" /></label>
        <fieldset v-if="!isOpenDataset" class="question-type-field"><legend>问题类型</legend><div class="compact-options"><label v-for="option in questionTypeOptions" :key="option.value" class="check-control"><input v-model="questionTypes" type="checkbox" :value="option.value" :disabled="configLocked" />{{ option.label }}</label></div></fieldset>
        <!-- Compatibility marker: legacy chunking_strategies is normalized by the server. v-model="chunkingStrategies" -->
        <fieldset class="question-type-field strategy-field primary-strategy-field"><legend>主分块策略</legend><div class="strategy-options"><label v-for="option in chunkingOptions" :key="option.value" class="check-control"><input v-model="primaryChunkingStrategy" type="radio" name="primary-chunking-strategy" :value="option.value" :aria-label="option.label" :disabled="configLocked" /><span>{{ option.label }}</span></label></div></fieldset>
        <fieldset class="question-type-field strategy-field comparison-strategy-field"><legend>对比分块策略</legend><div class="strategy-options"><template v-for="option in chunkingOptions" :key="`comparison-${option.value}`"><label v-if="option.value !== primaryChunkingStrategy" class="check-control"><input v-model="comparisonChunkingStrategies" type="checkbox" :value="option.value" :aria-label="`comparison-${option.value}`" :disabled="configLocked" /><span>{{ option.label }}</span></label></template></div><small>对比策略只生成 Retrieval 和资源指标；RAG 指标仅属于主分块策略。</small></fieldset>
        <label class="config-control pipeline-control">检索策略<select v-model="retrievalStrategy" aria-label="检索策略" :disabled="configLocked"><option v-for="option in retrievalOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></label>
        <label class="config-control pipeline-control toggle-control">检索重排<span><input v-model="rerankEnabled" type="checkbox" aria-label="启用 Rerank" :disabled="configLocked" />启用 Rerank</span></label>
        <label class="config-control pipeline-control">Answer 模型<select v-model="answerModelId" aria-label="Answer 模型" :disabled="configLocked"><option value="">服务端默认模型</option><option v-for="option in chatModelOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></label>
        <label class="config-control pipeline-control">Judge 模型<select v-model="judgeModelId" aria-label="Judge 模型" :disabled="configLocked"><option value="">服务端默认模型</option><option v-for="option in chatModelOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></label>
      </div>
      <div v-if="!isOpenDataset" class="review-mode-row" aria-label="审核模式">
        <span>审核模式</span>
        <label v-for="mode in [{ value: 'auto', label: '自动审核' }, { value: 'manual', label: '人工审核' }, { value: 'sample', label: '抽样审核' }]" :key="mode.value" :class="{ active: reviewMode === mode.value }"><input v-model="reviewMode" type="radio" name="review-mode" :value="mode.value" :disabled="configLocked" />{{ mode.label }}</label>
        <button class="evaluation-generate" type="button" :disabled="configLocked || generating || !questionTypes.length" @click="generateDataset">{{ generating ? '生成中...' : '生成评估集' }}</button>
        <button class="evaluation-publish" type="button" :disabled="configLocked || publishing || !questions.length" @click="publishDataset">{{ publishing ? '发布中...' : '发布评估集' }}</button>
      </div>
      <div v-else class="public-dataset-actions">
        <p class="evaluation-dataset-status" :data-status="selectedOpenDataset?.status">{{ selectedOpenDataset?.ready ? `已就绪：${selectedOpenDataset.documents} 篇文档，${selectedDatasetCount} 题` : `数据集状态：${selectedOpenDataset?.status || '未准备'}（${Math.round((selectedOpenDataset?.progress || 0) * 100)}%）` }}</p>
        <button class="evaluation-generate" type="button" :disabled="configLocked || preparingOpenDataset" @click="prepareOpenDataset">{{ preparingOpenDataset ? '准备中...' : selectedOpenDataset?.ready ? '刷新状态' : '准备数据集' }}</button>
      </div>
    </section>

    <section v-if="!isOpenDataset && reviewMode !== 'auto'" class="evaluation-review" aria-label="审核列表">
      <div class="evaluation-section-head"><div><h3>审核列表</h3><p>{{ reviewMode === 'sample' ? `按固定种子抽取 ${reviewRows.length} 题，可选择是否参与审核。` : '选择纳入本次评测的问答对。' }}</p></div><span>{{ reviewMode === 'sample' ? `${reviewRows.length} 题待抽样审核` : `${selectedQuestions.length} / ${questions.length} 已选` }}</span></div>
      <div v-if="reviewRows.length" class="review-list"><label v-for="(item, index) in reviewRows" :key="item.id" class="review-row"><input v-model="selectedQuestionIds" type="checkbox" :value="String(item.id)" :disabled="configLocked" /><span class="review-index">{{ index + 1 }}</span><span><strong>{{ item.question }}</strong><small>{{ item.ground_truth || '未提供标准答案' }}</small></span><span class="question-kind">{{ item.question_type || 'generated' }}</span></label></div>
      <div v-else class="evaluation-empty">生成评估集后在这里审核问题。</div>
    </section>

    <section class="evaluation-results" aria-label="评测结果">
      <div class="evaluation-section-head"><div><h3>评测指标</h3><p>主 Retrieval/RAG 指标来自主分块策略；对比策略仅展示检索和资源指标。</p></div><button class="evaluation-run" :class="{ 'stop-action': running }" type="button" :disabled="cancelling || (!running && (!datasetReady || !chunkingStrategies.length))" @click="running ? cancelEvaluation() : runEvaluation()">{{ cancelling ? '停止中...' : running ? '停止评测' : '运行评测' }}</button></div>
      <div v-if="activeRun?.requested_configuration" class="evaluation-provenance configuration-snapshot">
        <span>本结果配置：主 {{ activeRun.requested_configuration.primary_chunking_strategy || '--' }} · {{ activeRun.requested_configuration.retrieval_strategy || '--' }} · Rerank {{ activeRun.requested_configuration.rerank_enabled ? '开启' : '关闭' }}</span>
        <span v-if="configurationMismatch" class="configuration-warning">当前表单已改变，结果属于上一次配置</span>
        <span>验证：{{ statusLabel(results.state) }} · 新鲜度：{{ freshnessLabel(results.freshness) }}</span>
      </div>
      <div v-if="activeRun" class="evaluation-dataset-status run-progress" :data-status="activeRun.status" aria-label="评测任务状态">
        <span>任务：{{ runStatusLabel(activeRun.status) }}</span><span>阶段：{{ activeRun.stage || '--' }}</span>
        <span>已完成题目：{{ completedQuestions }} / {{ totalQuestions }}</span><span>失败题目：{{ failedCount }}</span>
        <span>有效覆盖率：{{ coverage == null ? '--' : `${(coverage * 100).toFixed(1)}%` }}</span>
        <span>耗时：{{ formatDuration(elapsedSeconds) }}</span><span>预计剩余：{{ formatDuration(etaSeconds) }}</span>
        <button v-if="isRunActive(activeRun.status)" type="button" class="report-download danger-action" :disabled="cancelling" @click="cancelEvaluation">{{ cancelling ? '停止中...' : '取消评测' }}</button>
        <button v-if="['partial', 'failed', 'cancelled'].includes(activeRun.status)" type="button" class="report-download" @click="resumeEvaluation">继续评测</button>
        <button v-if="activeRun.status === 'completed' && activeRun.report?.available !== false" type="button" class="report-download" @click="downloadReport(activeRun)">下载统一报告</button>
        <small v-if="activeRun.error" class="run-error">{{ activeRun.error }}</small>
      </div>
      <div class="metric-grid"><article v-for="metric in metrics" :key="metric.label" class="metric-card"><div><span>{{ metric.label }}</span><small>{{ metric.source }}</small></div><strong>{{ formatMetric(metric.value) }}</strong><span class="verification-tag" :class="metric.state">{{ statusLabel(metric.state) }}</span></article></div>
      <div v-if="chunkingMetrics.length" class="chunking-results">
        <div class="evaluation-section-head"><h3>分块策略指标</h3><span>{{ chunkingMetrics.length }} 个策略</span></div>
        <div class="history-table-wrap"><table><thead><tr><th>策略</th><th>MRR@10</th><th>Recall@20</th><th>Context Precision</th><th>覆盖率</th><th>状态</th></tr></thead><tbody><tr v-for="item in chunkingMetrics" :key="item.strategy"><td>{{ item.label }}</td><td>{{ formatMetric(item.mrr) }}</td><td>{{ formatMetric(item.recall) }}</td><td>{{ formatMetric(item.precision) }}</td><td>{{ formatMetric(item.coverage) }}</td><td><span class="verification-tag" :class="item.state">{{ statusLabel(item.state) }}</span></td></tr></tbody></table></div>
      </div>
      <div class="evaluation-provenance"><span class="verification-tag" :class="results.state">{{ statusLabel(results.state) }}</span><span>新鲜度：{{ freshnessLabel(results.freshness) }}</span><span>完成时间：{{ formatDate(results.completedAt) }}</span></div>
    </section>

    <section class="evaluation-history" aria-label="评测历史">
      <div class="evaluation-section-head"><div><h3>报告历史</h3><p>报告由服务端生成并按当前租户范围下载、删除；状态与新鲜度分开显示。</p></div><button type="button" class="history-refresh" :disabled="historyLoading" @click="loadHistory">{{ historyLoading ? '加载中...' : '刷新' }}</button></div>
      <div v-if="historyError" class="evaluation-empty history-error">{{ historyError }} <button type="button" class="history-refresh" @click="loadHistory">重试</button></div>
      <div v-else-if="historyLoading && !history.length" class="evaluation-empty">报告历史加载中...</div>
      <div v-else-if="history.length" class="history-table-wrap"><table><thead><tr><th>评测类型</th><th>数据集/配置</th><th>生成时间</th><th>验证状态</th><th>新鲜度</th><th></th></tr></thead><tbody><tr v-for="item in history" :key="item.report_id || item.run_id"><td>{{ item.evaluation_type || '--' }}</td><td>{{ item.dataset?.entries ?? '--' }} 题 · {{ item.requested_configuration?.primary_chunking_strategy || '旧版报告' }}</td><td>{{ formatDate(item.created_at || item.provenance?.created_at) }}</td><td><span class="verification-tag" :class="historyState(item)">{{ statusLabel(historyState(item)) }}</span></td><td><span class="verification-tag" :class="item.freshness_status || 'unknown'">{{ freshnessLabel(item.freshness_status) }}</span></td><td class="history-actions"><button type="button" class="report-download" :disabled="item.available === false || !reportIdFor(item)" @click="downloadReport(item)">下载</button><button type="button" class="report-download danger-action" :disabled="deletingReportId === reportIdFor(item) || !reportIdFor(item)" @click="deleteReport(item)">{{ deletingReportId === reportIdFor(item) ? '删除中...' : '删除' }}</button></td></tr></tbody></table></div>
      <div v-else class="evaluation-empty">暂无评测报告。</div>
    </section>
  </main>
</template>

<style scoped>
.evaluation-page { overflow-x: hidden; }
.evaluation-config-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
  align-items: start;
  gap: 18px 16px;
}
.config-control { align-content: start; }
.dataset-control { grid-column: 1 / span 2; grid-row: 1; }
.question-count-control { grid-column: 3; grid-row: 1; }
.evaluation-config-grid > .question-type-field:not(.strategy-field) { grid-column: 4; grid-row: 1; }
.primary-strategy-field { grid-column: 1 / span 2; grid-row: 2; }
.comparison-strategy-field { grid-column: 3 / span 2; grid-row: 2; }
.pipeline-control { grid-row: 3; }
.evaluation-config-grid select,
.evaluation-config-grid input[type="number"] {
  height: 40px;
  min-height: 40px;
  max-width: 100%;
}
.strategy-field {
  display: block;
  min-height: 178px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-soft);
}
.strategy-field legend {
  margin: 0;
  padding: 0 5px;
  color: var(--text-strong);
  font-size: 13px;
}
.strategy-options {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 9px 16px;
}
.compact-options { display: grid; gap: 7px; }
.strategy-field .check-control,
.compact-options .check-control {
  min-width: 0;
  margin: 0;
  white-space: normal;
  line-height: 1.35;
}
.strategy-field .check-control { align-items: flex-start; }
.strategy-field .check-control input { flex: 0 0 auto; margin-top: 2px; }
.strategy-field small {
  display: block;
  margin-top: 12px;
  color: var(--text-subtle);
  font-weight: 500;
  line-height: 1.5;
}
.public-dataset-actions { display: flex; align-items: center; gap: 12px; margin-top: 16px; }
.chunking-results { margin-top: 18px; }
.public-dataset-actions .evaluation-generate { margin-left: auto; }
.toggle-control > span {
  width: 100%;
  min-height: 40px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 0 10px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  color: var(--text);
  background: var(--surface);
  font-weight: 500;
}
.toggle-control input { accent-color: var(--primary); }
.run-progress { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 16px; margin-top: 15px; }
.run-error { flex-basis: 100%; color: var(--danger); overflow-wrap: anywhere; }
.configuration-snapshot { margin-top: 12px; gap: 10px; flex-wrap: wrap; }
.configuration-warning { color: var(--danger); font-weight: 700; }
.history-actions { display: flex; justify-content: flex-end; gap: 8px; }
.danger-action { color: var(--danger); }
.evaluation-run.stop-action { border-color: var(--danger); background: var(--danger); }
.history-error { color: var(--danger); }
.metric-grid {
  grid-template-columns: repeat(auto-fit, minmax(145px, 1fr));
  overflow: visible;
}
.metric-card { min-width: 0; }

@media (max-width: 1100px) {
  .evaluation-config-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .evaluation-config-grid > *,
  .evaluation-config-grid > .question-type-field:not(.strategy-field) { grid-column: auto; grid-row: auto; }
  .dataset-control { grid-column: 1 / -1; }
  .metric-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}

@media (max-width: 640px) {
  .evaluation-page { padding: 20px 16px 96px; }
  .evaluation-header { align-items: flex-start; margin-bottom: 20px; }
  .evaluation-header h2 { font-size: 25px; }
  .evaluation-config,
  .evaluation-results,
  .evaluation-history,
  .evaluation-review { padding: 16px; }
  .evaluation-section-head { align-items: flex-start; flex-wrap: wrap; gap: 10px; }
  .evaluation-section-head > div { min-width: 0; flex: 1 1 100%; }
  .evaluation-section-head .evaluation-run { width: 100%; }
  .evaluation-config-grid { grid-template-columns: minmax(0, 1fr); gap: 16px; }
  .evaluation-config-grid > *,
  .dataset-control { grid-column: 1; grid-row: auto; }
  .strategy-field { min-height: 0; }
  .strategy-options { grid-template-columns: minmax(0, 1fr); gap: 10px; }
  .public-dataset-actions { align-items: stretch; flex-direction: column; }
  .public-dataset-actions .evaluation-generate { width: 100%; margin-left: 0; }
  .run-progress > span { flex-basis: calc(50% - 8px); }
  .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
  .metric-card { min-height: 112px; padding: 11px; }
  .metric-card > div { align-items: flex-start; flex-direction: column; }
  .metric-card > div small { max-width: 100%; }
  .history-table-wrap { margin-right: -16px; padding-right: 16px; }
}
</style>
