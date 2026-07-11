<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import { api } from '../api'

const route = useRoute()
const router = useRouter()
function emptyUsage() {
  return { total: {}, by_model: [], by_type: [], by_scenario: [], daily: [], cache: {}, cache_series: { buckets: [], models: [] } }
}
const info = ref<any>({})
const models = ref<any[]>([])
const modelCounts = ref<Record<string, number>>({})
const usage = ref<any>(emptyUsage())
const usageGranularity = ref('day')
const parserEngines = ref<any[]>([])
const storage = ref<any>({})
const vectorStores = ref<any[]>([])
const webSearchTypes = ref<any[]>([])
const mcpServices = ref<any[]>([])
const kv = ref<Record<string, any>>({
  parser: {},
  storage: {},
  retrieval: {},
  chatHistory: {},
  webSearch: {},
})
const enableMemory = ref(true)
const neo4jAvailable = ref(false)
const memorySaving = ref(false)
const visible = ref(false)
const currentUser = ref<any>(null)
const passwordForm = ref({ old_password: '', new_password: '', confirm_password: '' })
const mcpDialogVisible = ref(false)
const mcpForm = ref({ id: '', name: '', description: '', url: '', api_key: '', enabled: true })

const requestedSection = String(route.query.section || 'general')
const activeSection = ref(requestedSection === 'tenant' ? 'general' : requestedSection)
const form = ref({
  id: '',
  name: '',
  display_name: '',
  type: 'KnowledgeQA',
  source: 'openai',
  description: '',
  parameters: { base_url: '', api_key: '', model: '' },
  is_default: true,
})

const sections = [
  { key: 'general', label: '常规设置', caption: '记忆与 RAG 评估' },
  { key: 'user', label: '用户资料', caption: '账号与密码' },
  { key: 'models', label: '模型管理', caption: '对话 / Embedding / ReRank / 视觉' },
  { key: 'vector', label: '检索配置', caption: 'Top K / 阈值 / Rerank' },
  { key: 'websearch', label: '联网搜索', caption: 'WebSearch Provider' },
  { key: 'mcp', label: 'MCP', caption: '工具服务与凭证' },
  { key: 'parser', label: '解析引擎', caption: '文档解析与 DocReader' },
  { key: 'storage', label: '存储引擎', caption: 'FileSystemStorage 状态' },
  { key: 'system', label: '系统信息', caption: '版本、缓存、向量索引' },
]
const roleLabels: Record<string, string> = {
  chat: '对话',
  KnowledgeQA: '对话',
  summary: '摘要',
  title: '标题',
  question: '问题生成',
  extract: '信息抽取',
  embedding: '向量',
  Embedding: 'Embedding',
  rerank: '重排序',
  Rerank: 'ReRank',
  vlm: '视觉理解',
  VLLM: '视觉',
}
const providerLabels: Record<string, string> = {
  'aliyun-bailian': '阿里云 DashScope',
  aliyun: '阿里云 DashScope',
  openai: 'OpenAI Compatible',
  local: 'Ollama / 本地',
}
const modelTypeOptions = [
  { type: 'KnowledgeQA', label: '对话' },
  { type: 'Embedding', label: 'Embedding' },
  { type: 'Rerank', label: 'ReRank' },
  { type: 'VLLM', label: '视觉' },
]
const modelTabs = [
  { key: 'all', label: '全部' },
  { key: 'chat', label: '对话' },
  { key: 'embedding', label: 'Embedding' },
  { key: 'rerank', label: 'ReRank' },
  { key: 'vlm', label: '视觉' },
]
const cacheGranularityOptions = [
  { value: 'day', label: '天' },
  { value: 'hour', label: '小时' },
  { value: '15m', label: '15分钟' },
]
const cacheChartColors = ['#136f83', '#8f5fe8', '#d88914', '#16845b']
const cacheChartWidth = 760
const cacheChartHeight = 250
const cacheChartPadding = { top: 18, right: 22, bottom: 36, left: 46 }
const activeModelType = ref('all')
const modelGroupKey = (type: string) => {
  const value = String(type || '')
  if (['KnowledgeQA', 'chat', 'summary', 'title', 'question', 'extract'].includes(value)) return 'chat'
  if (['Embedding', 'embedding'].includes(value)) return 'embedding'
  if (['Rerank', 'rerank'].includes(value)) return 'rerank'
  if (['VLLM', 'vlm', 'vllm', 'vision'].includes(value)) return 'vlm'
  return ''
}
const modelGroupLabel = (key: string) => modelTabs.find((item) => item.key === key)?.label || roleLabels[key] || key
const modelTypeOf = (model: any) => modelGroupKey(model.type || model.raw_type || model.role)
const visibleModels = computed(() => models.value.filter((model) => ['chat', 'embedding', 'rerank', 'vlm'].includes(modelTypeOf(model))))
const filteredModels = computed(() => activeModelType.value === 'all' ? visibleModels.value : visibleModels.value.filter((model) => modelTypeOf(model) === activeModelType.value))
const localModelTabCount = (key: string) => key === 'all' ? visibleModels.value.length : visibleModels.value.filter((model) => modelTypeOf(model) === key).length
const modelTabCount = (key: string) => {
  if (key === 'all') return Number(modelCounts.value.total ?? visibleModels.value.length)
  return Number(modelCounts.value[key] ?? localModelTabCount(key))
}
const usageTotal = computed(() => usage.value?.total || {})
const cacheSummary = computed(() => usage.value?.cache || {})
const cacheSeries = computed(() => usage.value?.cache_series || { buckets: [], models: [] })
const topUsageModels = computed(() => (usage.value?.by_model || []).slice(0, 5))
const usageByType = computed(() => {
  const grouped: Record<string, number> = {}
  for (const item of usage.value?.by_type || []) {
    const key = modelGroupKey(item.model_type)
    if (!['chat', 'embedding', 'rerank', 'vlm'].includes(key)) continue
    grouped[key] = (grouped[key] || 0) + Number(item.total_tokens || 0)
  }
  return Object.entries(grouped).map(([model_type, total_tokens]) => ({ model_type, total_tokens }))
})
const configuredModelCount = computed(() => visibleModels.value.filter((model) => model.status === 'active' || model.credentials_configured || model.parameters?.api_key_configured).length)
const currentSection = computed(() => sections.find((item) => item.key === activeSection.value) || sections[0])
const cacheChart = computed(() => {
  const buckets = cacheSeries.value?.buckets || []
  const plotWidth = cacheChartWidth - cacheChartPadding.left - cacheChartPadding.right
  const plotHeight = cacheChartHeight - cacheChartPadding.top - cacheChartPadding.bottom
  const xFor = (index: number) => cacheChartPadding.left + (buckets.length <= 1 ? plotWidth / 2 : (index / (buckets.length - 1)) * plotWidth)
  const yFor = (rate: any) => {
    const value = Math.max(0, Math.min(1, Number(rate || 0)))
    return cacheChartPadding.top + (1 - value) * plotHeight
  }
  const yTicks = [1, 0.75, 0.5, 0.25, 0].map((value) => ({
    value,
    y: yFor(value),
    label: cacheRate(value),
  }))
  const xStep = Math.max(1, Math.ceil(Math.max(buckets.length, 1) / 6))
  const xLabels = buckets
    .map((bucket: any, index: number) => ({ ...bucket, x: xFor(index), index }))
    .filter((bucket: any) => bucket.index === 0 || bucket.index === buckets.length - 1 || bucket.index % xStep === 0)
  const lines = (cacheSeries.value?.models || [])
    .filter((model: any) => Number(model.prompt_tokens || 0) > 0)
    .map((model: any, modelIndex: number) => {
      const points = buckets.map((bucket: any, index: number) => {
        const point = model.points?.[index] || { ...bucket, cache_hit_rate: 0, prompt_tokens: 0, cached_tokens: 0 }
        return { ...point, x: xFor(index), y: yFor(point.cache_hit_rate) }
      })
      return {
        ...model,
        name: model.model_name || model.model_id || '未知模型',
        color: cacheChartColors[modelIndex % cacheChartColors.length],
        path: points.map((point: any, index: number) => `${index ? 'L' : 'M'} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(' '),
        points,
      }
    })
  return {
    width: cacheChartWidth,
    height: cacheChartHeight,
    padding: cacheChartPadding,
    plotRight: cacheChartWidth - cacheChartPadding.right,
    plotBottom: cacheChartHeight - cacheChartPadding.bottom,
    yTicks,
    xLabels,
    lines,
  }
})
const hasCacheTrend = computed(() => cacheChart.value.lines.length > 0)
const roleSummary = (model: any) => {
  const roles = Array.isArray(model.roles) ? model.roles : []
  if (!roles.length && model.role) return roleLabels[model.role] || model.role
  if (!roles.length) return model.description || ''
  return roles.map((role: any) => roleLabels[role.key] || role.key).join('、')
}
const modelProviderLabel = (model: any) => providerLabels[model.source] || model.source || '自定义'

function formatNumber(value: any) {
  const num = Number(value || 0)
  if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`
  if (num >= 10000) return `${(num / 10000).toFixed(1)}万`
  return num.toLocaleString('zh-CN')
}

function successRate(value: any) {
  return `${Math.round(Number(value || 0) * 100)}%`
}

function cacheRate(value: any) {
  const num = Number(value || 0) * 100
  if (!Number.isFinite(num)) return '0%'
  return `${num.toFixed(1)}%`
}

function responseData(response: any) {
  return response?.data || response || {}
}

function resetForm() {
  form.value = {
    id: '',
    name: '',
    display_name: '',
    type: 'KnowledgeQA',
    source: 'openai',
    description: '',
    parameters: { base_url: '', api_key: '', model: '' },
    is_default: true,
  }
}

function openModel(model?: any) {
  if (model) {
    form.value = {
      id: model.id,
      name: model.name,
      display_name: model.display_name,
      type: model.type,
      source: model.source,
      description: model.description,
      parameters: {
        base_url: model.parameters?.base_url || '',
        api_key: '',
        model: model.parameters?.model || model.name || '',
      },
      is_default: !!model.is_default,
    }
  } else {
    resetForm()
  }
  visible.value = true
}

async function load() {
  const [infoRes, modelRes, usageRes, parserRes, storageRes, vectorRes, webTypeRes, mcpRes]: any[] = await Promise.all([
    api.systemInfo(),
    api.listModels(),
    api.modelUsage({ range: 7, granularity: usageGranularity.value }),
    api.parserEngines(),
    api.storageStatus(),
    api.vectorStoreTypes(),
    api.webSearchProviderTypes(),
    api.listMcpServices(),
  ])
  const infoPayload = responseData(infoRes)
  const modelPayload = responseData(modelRes)
  const usagePayload = responseData(usageRes)
  info.value = infoPayload
  neo4jAvailable.value = !!infoPayload.graph_database_engine && infoPayload.graph_database_engine !== 'Not Enabled'
  try {
    const meRes: any = await api.me()
    currentUser.value = meRes.data?.user || meRes.data
    enableMemory.value = (meRes.data?.user?.preferences ?? meRes.data?.preferences ?? {}).enable_memory !== false
  } catch {
    enableMemory.value = true
  }
  models.value = modelPayload.items || modelPayload.models || []
  modelCounts.value = { ...(modelPayload.counts_by_type || {}), total: Number(modelPayload.total ?? (modelPayload.items || modelPayload.models || []).length) }
  usage.value = usagePayload || emptyUsage()
  parserEngines.value = responseData(parserRes).items || []
  storage.value = responseData(storageRes)
  vectorStores.value = responseData(vectorRes).items || []
  webSearchTypes.value = responseData(webTypeRes).items || []
  mcpServices.value = responseData(mcpRes).items || []
  const [parserKv, storageKv, retrievalKv, chatKv, webKv]: any[] = await Promise.all([
    api.getTenantKv('parser-engine-config'),
    api.getTenantKv('storage-engine-config'),
    api.getTenantKv('retrieval-config'),
    api.getTenantKv('chat-history-config'),
    api.getTenantKv('web-search-config'),
  ])
  kv.value = {
    parser: responseData(parserKv).value || {},
    storage: responseData(storageKv).value || {},
    retrieval: responseData(retrievalKv).value || {},
    chatHistory: responseData(chatKv).value || {},
    webSearch: responseData(webKv).value || {},
  }
}

async function loadUsage() {
  const usageRes: any = await api.modelUsage({ range: 7, granularity: usageGranularity.value })
  usage.value = responseData(usageRes) || emptyUsage()
}

async function saveModel() {
  try {
    const payload = { ...form.value, parameters: { ...form.value.parameters } }
    const secret = payload.parameters.api_key
    if (!secret) payload.parameters.api_key = undefined as any
    if (payload.id) await api.updateModel(payload.id, payload)
    else {
      const res: any = await api.createModel(payload)
      payload.id = res.data?.id
    }
    if (secret && payload.id) await api.updateModelCredentials(payload.id, { api_key: secret })
    visible.value = false
    resetForm()
    await load()
    MessagePlugin.success('模型配置已保存')
  } catch (e: any) {
    MessagePlugin.error(e?.response?.data?.message || '保存模型失败')
  }
}

async function removeModel(model: any) {
  if (model.is_builtin || model.managed_by === 'env') {
    MessagePlugin.warning('内置或 .env 模型不可删除')
    return
  }
  if (!confirm(`删除模型“${model.display_name || model.name}”？`)) return
  await api.deleteModel(model.id)
  await load()
}

async function clearSecret(model: any) {
  await api.deleteModelCredential(model.id, 'api_key')
  await load()
}

async function saveKv(key: string, value: any) {
  await api.updateTenantKv(key, value)
  await load()
  MessagePlugin.success('配置已保存')
}

async function changePassword() {
  if (!passwordForm.value.old_password || !passwordForm.value.new_password) {
    MessagePlugin.warning('请填写完整密码信息')
    return
  }
  if (passwordForm.value.new_password !== passwordForm.value.confirm_password) {
    MessagePlugin.warning('两次输入的新密码不一致')
    return
  }
  try {
    await api.changePassword(passwordForm.value)
    passwordForm.value = { old_password: '', new_password: '', confirm_password: '' }
    MessagePlugin.success('密码修改成功')
  } catch (e: any) {
    MessagePlugin.error(e?.response?.data?.message || '密码修改失败')
  }
}

function openMcpDialog() {
  mcpForm.value = { id: '', name: '', description: '', url: '', api_key: '', enabled: true }
  mcpDialogVisible.value = true
}

function editMcpService(service: any) {
  mcpForm.value = { ...service, api_key: '' }
  mcpDialogVisible.value = true
}

async function saveMcpService() {
  if (!mcpForm.value.name || !mcpForm.value.url) {
    MessagePlugin.warning('请填写服务名称和 URL')
    return
  }
  try {
    if (mcpForm.value.id) {
      await api.updateMcpService(mcpForm.value.id, mcpForm.value)
    } else {
      await api.createMcpService(mcpForm.value)
    }
    mcpDialogVisible.value = false
    await load()
    MessagePlugin.success('MCP 服务已保存')
  } catch (e: any) {
    MessagePlugin.error(e?.response?.data?.message || '保存失败')
  }
}

async function deleteMcpService(service: any) {
  if (!confirm(`删除 MCP 服务"${service.name}"？`)) return
  await api.deleteMcpService(service.id)
  await load()
  MessagePlugin.success('已删除')
}

async function toggleMemory(enabled: boolean) {
  if (enabled && !neo4jAvailable.value) {
    MessagePlugin.warning('Neo4j 未启用，无法开启记忆功能')
    return
  }
  memorySaving.value = true
  try {
    enableMemory.value = enabled
    await api.updatePreferences({ enable_memory: enabled })
    MessagePlugin.success(enabled ? '记忆功能已开启' : '记忆功能已关闭')
  } catch {
    enableMemory.value = !enabled
    MessagePlugin.error('保存失败')
  } finally {
    memorySaving.value = false
  }
}

// ── RAG 评估 ─────────────────────────────────────────────────────
const ragEvalLoading = ref(false)
const ragEvalResult = ref<any>(null)
const ragEvalHistory = ref<any[]>([])

async function runRagEval() {
  ragEvalLoading.value = true
  ragEvalResult.value = null
  try {
    const res: any = await api.ragEvalRun()
    ragEvalResult.value = res.data
    MessagePlugin.success('评估完成')
    await loadRagEvalHistory()
  } catch (e: any) {
    MessagePlugin.error(e?.response?.data?.message || '评估失败')
  } finally {
    ragEvalLoading.value = false
  }
}

async function loadRagEvalHistory() {
  try {
    const res: any = await api.ragEvalHistory()
    ragEvalHistory.value = res.data?.history || []
  } catch {}
}

function getScoreColor(score: number) {
  if (score >= 0.8) return 'success'
  if (score >= 0.6) return 'warning'
  return 'danger'
}

// ── 评估问题管理 ─────────────────────────────────────────────
const showEvalQuestionDialog = ref(false)
const evalQuestions = ref<any[]>([])
const evalQuestionForm = ref({ question: '', ground_truth: '' })

async function loadEvalQuestions() {
  try {
    const res: any = await api.ragEvalQuestions()
    evalQuestions.value = res.data?.questions || []
  } catch {}
}

async function addEvalQuestion() {
  if (!evalQuestionForm.value.question) {
    MessagePlugin.warning('请填写问题')
    return
  }
  try {
    await api.ragEvalAddQuestion(evalQuestionForm.value)
    evalQuestionForm.value = { question: '', ground_truth: '' }
    await loadEvalQuestions()
    MessagePlugin.success('问题已添加')
  } catch (e: any) {
    MessagePlugin.error(e?.response?.data?.message || '添加失败')
  }
}

function removeEvalQuestion(index: number) {
  evalQuestions.value.splice(index, 1)
}

const generateLoading = ref(false)
const generateNum = ref(10)

async function generateEvalQuestions() {
  generateLoading.value = true
  try {
    const res: any = await api.ragEvalGenerate({
      num_questions: generateNum.value,
      question_types: ['simple', 'reasoning'],
    })
    MessagePlugin.success(`已生成 ${res.data?.generated || 0} 个评估问题`)
    await loadEvalQuestions()
  } catch (e: any) {
    MessagePlugin.error(e?.response?.data?.message || '生成失败')
  } finally {
    generateLoading.value = false
  }
}

// 打开对话框时加载问题
watch(showEvalQuestionDialog, (val) => {
  if (val) loadEvalQuestions()
})

async function checkParser() {
  try {
    const res: any = await api.checkParserEngine()
    if (res.data?.available === false) throw new Error('parser unavailable')
    MessagePlugin.success('解析引擎可用')
  } catch {
    MessagePlugin.error('解析引擎检测失败')
  }
}

async function checkStorage() {
  try {
    await api.checkStorageEngine(kv.value.storage || {})
    MessagePlugin.success('存储引擎可用')
  } catch {
    MessagePlugin.error('存储引擎检测失败')
  }
}

watch(activeSection, (section) => {
  const nextSection = sections.some((item) => item.key === section) ? section : 'general'
  if (nextSection !== section) {
    activeSection.value = nextSection
    return
  }
  router.replace({ path: '/platform/settings', query: { section: nextSection } })
})

onMounted(() => {
  if (!sections.some((item) => item.key === activeSection.value)) activeSection.value = 'general'
  load()
})
</script>

<template>
  <main class="content settings-page">
    <section class="settings-titlebar">
      <div>
        <div class="settings-eyebrow">Settings</div>
        <h2>设置</h2>
        <p>{{ currentSection.label }} · {{ currentSection.caption }}</p>
      </div>
      <div class="settings-title-actions">
        <span>{{ info.name || '个人轻量知识库' }}</span>
      </div>
    </section>

    <section class="settings-shell">
      <aside class="settings-nav">
        <button v-for="section in sections" :key="section.key" :class="{ active: activeSection === section.key }" @click="activeSection = section.key">
          <strong>{{ section.label }}</strong>
          <span>{{ section.caption }}</span>
        </button>
      </aside>

      <div class="settings-content">
        <section v-if="activeSection === 'general'" class="settings-section">
          <div class="panel-head"><h3>常规设置</h3><p>记忆开关、RAG 评估与项目信息</p></div>
          <div class="settings-group">
            <!-- 记忆功能 -->
            <div class="setting-row">
              <div class="setting-info">
                <label>跨会话记忆</label>
                <p class="desc">对话完成后自动提取实体关系存入知识图谱，新对话时检索相关记忆注入上下文。依赖 Neo4j。</p>
              </div>
              <div class="setting-control">
                <label class="toggle-switch">
                  <input type="checkbox" :checked="enableMemory" :disabled="!neo4jAvailable || memorySaving" @change="toggleMemory(($event.target as HTMLInputElement).checked)" />
                  <span class="toggle-slider"></span>
                </label>
              </div>
            </div>
            <div v-if="!neo4jAvailable" class="setting-alert">
              <strong>Neo4j 未启用</strong>
              <span>请在 <code>.env</code> 中设置 <code>NEO4J_ENABLE=true</code> 并配置连接信息，然后重启服务。</span>
            </div>

            <!-- RAG 评估 -->
            <div class="eval-section">
              <div class="eval-header">
                <h3>RAG 评估</h3>
                <p>评估 RAG 管道质量，使用 RAGAs 框架测量检索和生成的准确性。</p>
              </div>

              <!-- 步骤 1：评估问题 -->
              <div class="eval-step">
                <div class="step-header">
                  <span class="step-number">1</span>
                  <span class="step-title">评估问题</span>
                  <button class="btn btn-sm btn-outline" @click="showEvalQuestionDialog = true">编辑</button>
                </div>
                <div class="step-content">
                  <div v-if="evalQuestions.length" class="question-preview">
                    <div v-for="(q, i) in evalQuestions.slice(0, 3)" :key="i" class="question-item-small">
                      <span class="q-num">{{ i + 1 }}.</span>
                      <span class="q-text">{{ q.question }}</span>
                      <span v-if="q.ground_truth" class="q-has-gt">✓ GT</span>
                    </div>
                    <div v-if="evalQuestions.length > 3" class="more-questions">
                      还有 {{ evalQuestions.length - 3 }} 个问题...
                    </div>
                  </div>
                  <div v-else class="no-questions-hint">
                    使用默认问题（3 个示例问题）
                  </div>
                </div>
              </div>

              <!-- 步骤 2：运行评估 -->
              <div class="eval-step">
                <div class="step-header">
                  <span class="step-number">2</span>
                  <span class="step-title">运行评估</span>
                </div>
                <div class="step-content">
                  <button class="btn btn-primary" :disabled="ragEvalLoading" @click="runRagEval">
                    {{ ragEvalLoading ? '评估中...' : '开始评估' }}
                  </button>
                  <span class="eval-hint">将对每个问题运行 RAG 管道并评估结果</span>
                </div>
              </div>

              <!-- 步骤 3：评估结果 -->
              <div v-if="ragEvalResult" class="eval-step">
                <div class="step-header">
                  <span class="step-number">3</span>
                  <span class="step-title">评估结果</span>
                  <span class="step-info">{{ ragEvalResult.total_questions }} 个问题 · {{ ragEvalResult.eval_time_ms }}ms</span>
                </div>
                <div class="step-content">
                  <!-- 指标卡片 -->
                  <div class="eval-metrics">
                    <div class="eval-metric">
                      <span class="metric-value" :class="getScoreColor(ragEvalResult.faithfulness)">
                        {{ (ragEvalResult.faithfulness * 100).toFixed(0) }}%
                      </span>
                      <span class="metric-label">Faithfulness</span>
                      <span class="metric-desc">忠实度</span>
                    </div>
                    <div class="eval-metric">
                      <span class="metric-value" :class="getScoreColor(ragEvalResult.answer_relevancy)">
                        {{ (ragEvalResult.answer_relevancy * 100).toFixed(0) }}%
                      </span>
                      <span class="metric-label">Relevancy</span>
                      <span class="metric-desc">相关性</span>
                    </div>
                    <div class="eval-metric">
                      <span class="metric-value" :class="getScoreColor(ragEvalResult.context_precision)">
                        {{ (ragEvalResult.context_precision * 100).toFixed(0) }}%
                      </span>
                      <span class="metric-label">Precision</span>
                      <span class="metric-desc">精确度</span>
                    </div>
                    <div v-if="ragEvalResult.context_recall > 0" class="eval-metric">
                      <span class="metric-value" :class="getScoreColor(ragEvalResult.context_recall)">
                        {{ (ragEvalResult.context_recall * 100).toFixed(0) }}%
                      </span>
                      <span class="metric-label">Recall</span>
                      <span class="metric-desc">召回率</span>
                    </div>
                    <div v-if="ragEvalResult.answer_correctness > 0" class="eval-metric">
                      <span class="metric-value" :class="getScoreColor(ragEvalResult.answer_correctness)">
                        {{ (ragEvalResult.answer_correctness * 100).toFixed(0) }}%
                      </span>
                      <span class="metric-label">Correctness</span>
                      <span class="metric-desc">正确性</span>
                    </div>
                  </div>

                  <!-- 详情表格 -->
                  <div v-if="ragEvalResult.details?.length" class="eval-details-table">
                    <table>
                      <thead>
                        <tr>
                          <th>问题</th>
                          <th>答案</th>
                          <th>F</th>
                          <th>AR</th>
                          <th>CP</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr v-for="(detail, i) in ragEvalResult.details" :key="i">
                          <td>{{ detail.question }}</td>
                          <td>{{ detail.answer?.substring(0, 100) }}...</td>
                          <td :class="getScoreColor(detail.faithfulness)">{{ (detail.faithfulness * 100).toFixed(0) }}%</td>
                          <td :class="getScoreColor(detail.answer_relevancy)">{{ (detail.answer_relevancy * 100).toFixed(0) }}%</td>
                          <td :class="getScoreColor(detail.context_precision)">{{ (detail.context_precision * 100).toFixed(0) }}%</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            </div>

            <!-- 项目信息（只读） -->
            <div class="setting-row">
              <div class="setting-info">
                <label>项目名称</label>
                <p class="desc">来自 <code>.env</code> 的 <code>APP_NAME</code></p>
              </div>
              <div class="setting-control">
                <span class="setting-value">{{ info.name || '个人轻量知识库' }}</span>
              </div>
            </div>

            <div class="setting-row">
              <div class="setting-info">
                <label>百炼 API</label>
                <p class="desc">阿里云百炼 OpenAI 兼容接口</p>
              </div>
              <div class="setting-control">
                <span class="setting-value">{{ info.bailian?.base_url || '-' }}</span>
                <span class="setting-tag" :class="info.bailian?.configured ? 'tag-success' : 'tag-warning'">{{ info.bailian?.configured ? '已配置' : '未配置' }}</span>
              </div>
            </div>
          </div>
        </section>

        <section v-if="activeSection === 'models'" class="settings-section">
          <div class="settings-section-head">
            <div>
              <h3>模型配置</h3>
              <p>管理不同类型的 AI 模型，支持 Ollama 本地模型和远程 API</p>
            </div>
            <t-button theme="primary" variant="outline" @click="openModel()">+ 添加模型</t-button>
          </div>
          <div class="builtin-models-note">
            <strong>内置模型</strong>
            <p>内置模型对所有用户可见，敏感信息会被隐藏，且不可编辑或删除。</p>
            <span>查看内置模型管理指南 ↗</span>
          </div>
          <div class="model-usage-panel">
            <article class="usage-stat">
              <span>7 日调用</span>
              <strong>{{ formatNumber(usageTotal.calls) }}</strong>
              <small>成功率 {{ successRate(usageTotal.success_rate) }}</small>
            </article>
            <article class="usage-stat">
              <span>Token 合计</span>
              <strong>{{ formatNumber(usageTotal.total_tokens) }}</strong>
              <small>四类缓存 {{ formatNumber(cacheSummary.cached_tokens) }} · 输入命中 {{ cacheRate(cacheSummary.prompt_rate) }}</small>
            </article>
            <article class="usage-stat">
              <span>输入 / 输出</span>
              <strong>{{ formatNumber(usageTotal.prompt_tokens) }} / {{ formatNumber(usageTotal.completion_tokens) }}</strong>
              <small>总量命中 {{ cacheRate(cacheSummary.total_rate) }} · 失败 {{ formatNumber(usageTotal.failed) }}</small>
            </article>
            <article class="usage-rank">
              <div class="usage-rank-head">
                <span>模型用量排行</span>
                <small>最近 7 天</small>
              </div>
              <div v-if="topUsageModels.length" class="usage-list">
                <div v-for="item in topUsageModels" :key="item.model_id || item.model_name" class="usage-row">
                  <span>{{ item.model_name || item.model_id || '未知模型' }}</span>
                  <strong>{{ formatNumber(item.total_tokens) }}</strong>
                </div>
              </div>
              <p v-else class="muted-line">暂无模型调用记录</p>
            </article>
          </div>
          <section class="cache-trend-panel">
            <div class="cache-trend-head">
              <div>
                <h4>缓存命中率趋势</h4>
                <p>仅统计对话 / Embedding / ReRank / 视觉四类模型的 cached_tokens / prompt_tokens</p>
              </div>
              <t-radio-group v-model="usageGranularity" variant="default-filled" size="small" @change="loadUsage">
                <t-radio-button v-for="item in cacheGranularityOptions" :key="item.value" :value="item.value">{{ item.label }}</t-radio-button>
              </t-radio-group>
            </div>
            <div v-if="hasCacheTrend" class="cache-trend-chart">
              <svg :viewBox="`0 0 ${cacheChart.width} ${cacheChart.height}`" role="img" aria-label="模型缓存命中率趋势">
                <g class="cache-grid">
                  <line
                    v-for="tick in cacheChart.yTicks"
                    :key="tick.label"
                    :x1="cacheChart.padding.left"
                    :x2="cacheChart.plotRight"
                    :y1="tick.y"
                    :y2="tick.y"
                  />
                </g>
                <g class="cache-axis-labels">
                  <text v-for="tick in cacheChart.yTicks" :key="`y-${tick.label}`" :x="cacheChart.padding.left - 10" :y="tick.y + 4" text-anchor="end">{{ tick.label }}</text>
                  <text v-for="label in cacheChart.xLabels" :key="`x-${label.bucket}`" :x="label.x" :y="cacheChart.height - 10" text-anchor="middle">{{ label.label }}</text>
                </g>
                <g v-for="line in cacheChart.lines" :key="line.model_key">
                  <path class="cache-line" :d="line.path" :stroke="line.color" />
                  <circle
                    v-for="point in line.points"
                    :key="`${line.model_key}-${point.bucket}`"
                    class="cache-point"
                    :cx="point.x"
                    :cy="point.y"
                    :r="point.prompt_tokens ? 3 : 0"
                    :fill="line.color"
                  >
                    <title>{{ line.name }} · {{ point.label }} · {{ cacheRate(point.cache_hit_rate) }} · 缓存 {{ formatNumber(point.cached_tokens) }}/输入 {{ formatNumber(point.prompt_tokens) }}</title>
                  </circle>
                </g>
              </svg>
            </div>
            <div v-else class="cache-trend-empty">暂无缓存命中数据</div>
            <div v-if="hasCacheTrend" class="cache-trend-legend">
              <span v-for="line in cacheChart.lines" :key="line.model_key">
                <i :style="{ background: line.color }"></i>
                {{ line.name }}
                <em v-if="line.provider">{{ line.provider }}</em>
                <strong>{{ cacheRate(line.cache_hit_rate) }}</strong>
              </span>
            </div>
          </section>
          <div v-if="usageByType.length" class="usage-type-strip">
            <span v-for="item in usageByType" :key="item.model_type">
              {{ modelGroupLabel(item.model_type) }} · {{ formatNumber(item.total_tokens) }}
            </span>
          </div>
          <div class="model-config-status">
            <div>
              <span>当前可见模型</span>
              <strong>{{ visibleModels.length }}</strong>
            </div>
            <div>
              <span>已配置</span>
              <strong>{{ configuredModelCount }}</strong>
            </div>
            <div>
              <span>DashScope</span>
              <strong>{{ info.bailian?.configured ? '已连接' : '待配置' }}</strong>
            </div>
          </div>
          <t-tabs v-model="activeModelType" class="model-type-tabs">
            <t-tab-panel v-for="tab in modelTabs" :key="tab.key" :value="tab.key" :label="`${tab.label}(${modelTabCount(tab.key)})`" />
          </t-tabs>
          <div class="model-card-grid">
            <article v-for="m in filteredModels" :key="m.id" class="settings-model-card" :class="`model-type-${modelTypeOf(m)}`">
              <div class="model-type-icon">{{ modelGroupLabel(modelTypeOf(m)).slice(0, 1) }}</div>
              <div class="settings-model-main">
                <div class="settings-model-title">
                  <strong>{{ m.display_name || m.name }}</strong>
                  <span v-if="m.is_builtin || m.managed_by === 'env'">锁定</span>
                </div>
                <p>{{ modelProviderLabel(m) }}</p>
                <div class="settings-model-meta">
                  <span>{{ modelGroupLabel(modelTypeOf(m)) }}</span>
                  <span v-if="roleSummary(m)">{{ roleSummary(m) }}</span>
                  <span v-if="m.parameters?.dimension">维度 {{ m.parameters.dimension }}</span>
                </div>
                <div class="settings-model-tags">
                  <t-tag v-if="m.is_default" size="small" theme="primary">默认</t-tag>
                  <t-tag v-if="m.managed_by === 'env'" size="small" theme="success">ENV</t-tag>
                  <t-tag v-if="m.status === 'missing_api_key'" size="small" theme="warning">待配置</t-tag>
                  <t-tag v-if="m.credentials_configured || m.parameters?.api_key_configured" size="small" theme="success">密钥已配置</t-tag>
                  <t-tag size="small" variant="outline">{{ m.type }}</t-tag>
                </div>
              </div>
              <div v-if="m.managed_by !== 'env'" class="settings-model-actions">
                <button @click="openModel(m)">编辑</button>
                <button :disabled="!m.credentials_configured" @click="clearSecret(m)">清密钥</button>
                <button class="danger" :disabled="m.is_builtin" @click="removeModel(m)">删除</button>
              </div>
            </article>
            <p v-if="!filteredModels.length" class="model-empty-state">暂无 {{ modelGroupLabel(activeModelType) }} 模型</p>
          </div>
        </section>

        <section v-if="activeSection === 'parser'" class="settings-section">
          <div class="panel-head"><h3>解析引擎</h3><t-button variant="outline" @click="checkParser">检测</t-button></div>
          <div class="settings-grid">
            <article v-for="engine in parserEngines" :key="engine.name" class="setting-tile">
              <span>{{ engine.name }}</span>
              <strong>{{ engine.display_name || engine.name }}</strong>
              <t-tag :theme="engine.available ? 'success' : 'danger'">{{ engine.available ? '可用' : '依赖缺失' }}</t-tag>
              <p>格式：{{ (engine.formats || []).join('、') }}</p>
              <p>能力：{{ (engine.capabilities || []).join('、') }}</p>
              <p>依赖：{{ Object.entries(engine.dependency_status || {}).map(([name, ready]) => `${name} ${ready ? '✓' : '✗'}`).join('、') }}</p>
              <p>VLM：{{ engine.vlm_available ? '已配置' : '未配置；纯文本仍可解析' }}</p>
            </article>
          </div>
        </section>

        <section v-if="activeSection === 'websearch'" class="settings-section">
          <div class="panel-head"><h3>联网搜索</h3></div>
          <div class="settings-grid">
            <article v-for="provider in webSearchTypes" :key="provider.provider || provider.name" class="setting-tile">
              <span>Provider</span>
              <strong>{{ provider.provider || provider.name }}</strong>
              <p>可作为 Agent 输入框的联网搜索能力来源。</p>
            </article>
            <article class="setting-tile wide-tile">
              <span>租户搜索配置</span>
              <label class="switch-line"><input v-model="kv.webSearch.enabled" type="checkbox" /> 允许联网搜索</label>
              <textarea v-model="kv.webSearch.notes" placeholder="当前轻量版默认保留入口；真实 provider 可通过后续凭证配置启用"></textarea>
              <button @click="saveKv('web-search-config', kv.webSearch)">保存配置</button>
            </article>
          </div>
        </section>

        <section v-if="activeSection === 'vector'" class="settings-section">
          <div class="panel-head"><h3>检索配置</h3></div>
          <div class="settings-grid">
            <article class="setting-tile">
              <span>向量引擎</span>
              <strong>SQLite sqlite-vec</strong>
              <t-tag theme="success">本地可用</t-tag>
              <p>FTS5 全文检索 + sqlite-vec 向量检索混合排序。</p>
            </article>
            <article class="setting-tile">
              <span>Rerank 模型</span>
              <label class="switch-line"><input v-model="kv.retrieval.rerank_enabled" type="checkbox" /> 启用 Rerank</label>
              <p>对检索结果进行语义重排序，提高相关性。</p>
              <button @click="saveKv('retrieval-config', kv.retrieval)">保存</button>
            </article>
            <article class="setting-tile wide-tile">
              <span>检索参数</span>
              <div class="retrieval-params">
                <label>
                  <span>Embedding Top K</span>
                  <input v-model.number="kv.retrieval.embedding_top_k" type="range" min="1" max="50" step="1" />
                  <strong>{{ kv.retrieval.embedding_top_k || 10 }}</strong>
                </label>
                <label>
                  <span>向量阈值</span>
                  <input v-model.number="kv.retrieval.vector_threshold" type="range" min="0" max="1" step="0.05" />
                  <strong>{{ (kv.retrieval.vector_threshold || 0.15).toFixed(2) }}</strong>
                </label>
                <label>
                  <span>关键词阈值</span>
                  <input v-model.number="kv.retrieval.keyword_threshold" type="range" min="0" max="1" step="0.05" />
                  <strong>{{ (kv.retrieval.keyword_threshold || 0.3).toFixed(2) }}</strong>
                </label>
                <label>
                  <span>Rerank Top K</span>
                  <input v-model.number="kv.retrieval.rerank_top_k" type="range" min="1" max="50" step="1" />
                  <strong>{{ kv.retrieval.rerank_top_k || 5 }}</strong>
                </label>
                <label>
                  <span>Rerank 阈值</span>
                  <input v-model.number="kv.retrieval.rerank_threshold" type="range" min="0" max="1" step="0.05" />
                  <strong>{{ (kv.retrieval.rerank_threshold || 0.3).toFixed(2) }}</strong>
                </label>
              </div>
              <button @click="saveKv('retrieval-config', kv.retrieval)">保存检索配置</button>
            </article>
          </div>
        </section>

        <section v-if="activeSection === 'mcp'" class="settings-section">
          <div class="settings-section-head">
            <div>
              <h3>MCP 服务</h3>
              <p>管理 Agent 可用的外部工具服务（Model Context Protocol）</p>
            </div>
            <t-button theme="primary" variant="outline" @click="openMcpDialog()">+ 添加服务</t-button>
          </div>
          <div class="settings-grid">
            <article v-for="service in mcpServices" :key="service.id" class="setting-tile">
              <div class="tile-header">
                <span>{{ service.status || 'active' }}</span>
                <div class="tile-actions">
                  <button @click="editMcpService(service)">编辑</button>
                  <button class="danger" @click="deleteMcpService(service)">删除</button>
                </div>
              </div>
              <strong>{{ service.name }}</strong>
              <p>{{ service.description || 'Agent 可选工具服务' }}</p>
              <t-tag :theme="service.enabled !== false ? 'success' : 'default'">{{ service.enabled !== false ? '已启用' : '已禁用' }}</t-tag>
            </article>
            <article v-if="!mcpServices.length" class="setting-tile wide-tile empty-tile">
              <strong>尚未配置 MCP 服务</strong>
              <p>点击上方"+ 添加服务"按钮配置 MCP 工具服务。</p>
            </article>
          </div>
        </section>

        <section v-if="activeSection === 'user'" class="settings-section">
          <div class="panel-head"><h3>用户资料</h3></div>
          <div class="settings-grid">
            <article class="setting-tile">
              <span>邮箱</span>
              <strong>{{ currentUser?.email || '-' }}</strong>
            </article>
            <article class="setting-tile">
              <span>用户名</span>
              <strong>{{ currentUser?.name || currentUser?.email || '-' }}</strong>
            </article>
            <article class="setting-tile">
              <span>聊天历史</span>
              <strong>{{ kv.chatHistory?.enabled === false ? '关闭' : '开启' }}</strong>
              <label class="switch-line"><input v-model="kv.chatHistory.enabled" type="checkbox" /> 保存历史会话</label>
              <button @click="saveKv('chat-history-config', kv.chatHistory)">保存</button>
            </article>
            <article class="setting-tile wide-tile">
              <span>修改密码</span>
              <div class="password-form">
                <input v-model="passwordForm.old_password" type="password" placeholder="当前密码" />
                <input v-model="passwordForm.new_password" type="password" placeholder="新密码" />
                <input v-model="passwordForm.confirm_password" type="password" placeholder="确认新密码" />
                <button @click="changePassword">修改密码</button>
              </div>
            </article>
          </div>
        </section>

        <section v-if="activeSection === 'storage'" class="settings-section">
          <div class="panel-head"><h3>存储引擎</h3><t-button variant="outline" @click="checkStorage">检测</t-button></div>
          <div class="settings-grid">
            <article class="setting-tile">
              <span>当前存储</span>
              <strong>{{ storage.provider || info.storage }}</strong>
              <t-tag theme="success">{{ storage.status || 'available' }}</t-tag>
            </article>
            <article class="setting-tile">
              <span>缓存</span>
              <strong>{{ info.cache || 'LocMemCache' }}</strong>
              <p>限流、流状态与任务进度使用本地内存缓存。</p>
            </article>
            <article class="setting-tile wide-tile">
              <span>租户存储配置</span>
              <textarea v-model="kv.storage.notes" placeholder="本地存储无需额外配置"></textarea>
              <button @click="saveKv('storage-engine-config', kv.storage)">保存配置</button>
            </article>
          </div>
        </section>

        <section v-if="activeSection === 'system'" class="settings-section">
          <div class="panel-head"><h3>系统信息</h3></div>
          <dl class="info-list settings-info">
            <dt>名称</dt><dd>{{ info.name }}</dd>
            <dt>版本</dt><dd>{{ info.version }}</dd>
            <dt>版本类型</dt><dd>{{ info.edition }}</dd>
            <dt>存储</dt><dd>{{ info.storage }}</dd>
            <dt>缓存</dt><dd>{{ info.cache }}</dd>
            <dt>向量</dt><dd>{{ info.vector }}</dd>
            <dt>Embedding 维度</dt><dd>{{ info.bailian?.local_embedding_dimension || 384 }}</dd>
          </dl>
        </section>
      </div>
    </section>

    <t-dialog v-model:visible="visible" header="模型配置" confirm-btn="保存" width="720px" @confirm="saveModel">
      <div class="editor-grid">
        <t-input v-model="form.name" label="模型名称" />
        <t-input v-model="form.display_name" label="显示名称" />
        <t-select v-model="form.type" label="模型类型">
          <t-option v-for="item in modelTypeOptions" :key="item.type" :value="item.type" :label="item.label" />
        </t-select>
        <t-select v-model="form.source" label="来源">
          <t-option value="openai" label="OpenAI Compatible" />
          <t-option value="aliyun-bailian" label="阿里云百炼" />
          <t-option value="local" label="本地" />
        </t-select>
        <t-input v-model="form.parameters.base_url" class="wide" label="Base URL" />
        <t-input v-model="form.parameters.model" label="Provider Model" />
        <t-input v-model="form.parameters.api_key" type="password" label="API Key" placeholder="留空则不更新密钥" />
        <t-textarea v-model="form.description" class="wide" label="描述" />
        <label class="switch-line"><input v-model="form.is_default" type="checkbox" /> 设为默认模型</label>
      </div>
    </t-dialog>

    <t-dialog v-model:visible="mcpDialogVisible" :header="mcpForm.id ? '编辑 MCP 服务' : '添加 MCP 服务'" confirm-btn="保存" width="600px" @confirm="saveMcpService">
      <div class="editor-grid">
        <t-input v-model="mcpForm.name" label="服务名称" placeholder="my-mcp-service" />
        <t-input v-model="mcpForm.url" class="wide" label="服务 URL" placeholder="http://localhost:3000" />
        <t-input v-model="mcpForm.api_key" type="password" label="API Key" placeholder="留空则不使用认证" />
        <t-textarea v-model="mcpForm.description" class="wide" label="描述" placeholder="服务用途说明" />
        <label class="switch-line"><input v-model="mcpForm.enabled" type="checkbox" /> 启用服务</label>
      </div>
    </t-dialog>

    <!-- 评估问题管理对话框 -->
    <t-dialog v-model:visible="showEvalQuestionDialog" header="管理评估问题" width="700px" :footer="false">
      <div class="eval-question-manager">
        <!-- 从知识库自动生成 -->
        <div class="generate-section">
          <h4>从知识库自动生成</h4>
          <p class="desc">使用 LLM 从知识库文档中自动生成评估问题和标准答案</p>
          <div class="generate-form">
            <div class="generate-input">
              <label>生成数量</label>
              <input v-model.number="generateNum" type="number" min="1" max="50" />
            </div>
            <button class="btn btn-primary" :disabled="generateLoading" @click="generateEvalQuestions">
              {{ generateLoading ? '生成中...' : '自动生成' }}
            </button>
          </div>
        </div>

        <div class="divider">或</div>

        <!-- 手动添加问题表单 -->
        <div class="add-question-form">
          <h4>手动添加</h4>
          <t-textarea v-model="evalQuestionForm.question" label="评估问题" placeholder="例如：什么是 RAG?" />
          <t-textarea v-model="evalQuestionForm.ground_truth" label="标准答案（Ground Truth）" placeholder="RAG 是检索增强生成的缩写..." />
          <button class="btn btn-outline" @click="addEvalQuestion">添加问题</button>
        </div>

        <!-- 问题列表 -->
        <div class="question-list">
          <h4>评估问题列表（{{ evalQuestions.length }}）</h4>
          <div v-for="(q, i) in evalQuestions" :key="i" class="question-item">
            <div class="question-text">{{ i + 1 }}. {{ q.question }}</div>
            <div v-if="q.ground_truth" class="question-ground-truth">
              <strong>GT:</strong> {{ q.ground_truth.substring(0, 100) }}{{ q.ground_truth.length > 100 ? '...' : '' }}
            </div>
            <div v-if="q.question_type" class="question-type">{{ q.question_type }}</div>
            <button class="btn btn-sm btn-danger" @click="removeEvalQuestion(i)">删除</button>
          </div>
          <div v-if="!evalQuestions.length" class="no-questions">
            暂无评估问题，请从知识库生成或手动添加
          </div>
        </div>
      </div>
    </t-dialog>
  </main>
</template>

<style scoped>
.eval-section {
  background: var(--surface, #fff);
  border: 1px solid var(--border, #dbe3ee);
  border-radius: 8px;
  padding: 20px;
  margin-top: 16px;
}

.eval-header {
  margin-bottom: 20px;
}

.eval-header h3 {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 4px;
}

.eval-header p {
  font-size: 13px;
  color: var(--text-muted, #637083);
}

.eval-step {
  border-top: 1px solid var(--border, #dbe3ee);
  padding-top: 16px;
  margin-top: 16px;
}

.step-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.step-number {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: var(--primary, #136f83);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
}

.step-title {
  font-weight: 500;
  flex: 1;
}

.step-info {
  font-size: 12px;
  color: var(--text-muted, #637083);
}

.step-content {
  padding-left: 34px;
}

.question-preview {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.question-item-small {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.q-num {
  color: var(--text-muted, #637083);
  min-width: 20px;
}

.q-text {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.q-has-gt {
  font-size: 11px;
  color: var(--success, #16845b);
  background: var(--success-soft, #e8f7f0);
  padding: 1px 6px;
  border-radius: 4px;
}

.more-questions {
  font-size: 12px;
  color: var(--text-muted, #637083);
}

.no-questions-hint {
  font-size: 13px;
  color: var(--text-muted, #637083);
}

.eval-hint {
  font-size: 12px;
  color: var(--text-muted, #637083);
  margin-left: 12px;
}

.eval-metrics {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.eval-metric {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 12px 16px;
  background: var(--bg, #f6f8fb);
  border-radius: 8px;
  min-width: 80px;
}

.metric-value {
  font-size: 28px;
  font-weight: 700;
  line-height: 1;
}

.metric-value.success {
  color: #52c41a;
}

.metric-value.warning {
  color: #faad14;
}

.metric-value.danger {
  color: #ff4d4f;
}

.metric-label {
  font-size: 11px;
  font-weight: 500;
  color: var(--text, #18212f);
  margin-top: 4px;
}

.metric-desc {
  font-size: 10px;
  color: var(--text-muted, #637083);
}

.eval-details-table {
  overflow-x: auto;
}

.eval-details-table table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.eval-details-table th,
.eval-details-table td {
  padding: 8px 12px;
  text-align: left;
  border-bottom: 1px solid var(--border, #dbe3ee);
}

.eval-details-table th {
  font-weight: 500;
  color: var(--text-muted, #637083);
  font-size: 12px;
}

.eval-details-table td.success {
  color: #52c41a;
  font-weight: 500;
}

.eval-details-table td.warning {
  color: #faad14;
  font-weight: 500;
}

.eval-details-table td.danger {
  color: #ff4d4f;
  font-weight: 500;
}

.eval-details {
  margin-top: 16px;
  border-top: 1px solid var(--border, #dbe3ee);
  padding-top: 12px;
}

.eval-details h4 {
  font-size: 14px;
  margin-bottom: 8px;
}

.eval-detail-item {
  padding: 8px;
  background: var(--bg, #f6f8fb);
  border-radius: 6px;
  margin-bottom: 8px;
}

.detail-question {
  font-weight: 500;
  margin-bottom: 4px;
}

.detail-answer {
  font-size: 12px;
  color: var(--text-muted, #637083);
  margin-bottom: 4px;
}

.detail-scores {
  display: flex;
  gap: 12px;
  font-size: 12px;
  color: var(--text-subtle, #8793a5);
}

.eval-question-manager {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.generate-section {
  background: var(--bg, #f6f8fb);
  border-radius: 8px;
  padding: 16px;
}

.generate-section h4 {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 4px;
}

.generate-section .desc {
  font-size: 12px;
  color: var(--text-muted, #637083);
  margin-bottom: 12px;
}

.generate-form {
  display: flex;
  align-items: center;
  gap: 12px;
}

.generate-input {
  display: flex;
  align-items: center;
  gap: 8px;
}

.generate-input label {
  font-size: 13px;
  color: var(--text-muted, #637083);
}

.generate-input input {
  width: 60px;
  padding: 6px 8px;
  border: 1px solid var(--border, #dbe3ee);
  border-radius: 4px;
  text-align: center;
}

.divider {
  text-align: center;
  color: var(--text-muted, #637083);
  font-size: 13px;
  position: relative;
}

.divider::before,
.divider::after {
  content: '';
  position: absolute;
  top: 50%;
  width: 40%;
  height: 1px;
  background: var(--border, #dbe3ee);
}

.divider::before {
  left: 0;
}

.divider::after {
  right: 0;
}

.add-question-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.add-question-form h4 {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 4px;
}

.question-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.question-list h4 {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 8px;
}

.question-item {
  padding: 12px;
  background: var(--bg, #f6f8fb);
  border-radius: 6px;
  position: relative;
}

.question-text {
  font-weight: 500;
  margin-bottom: 4px;
  padding-right: 60px;
}

.question-ground-truth {
  font-size: 12px;
  color: var(--text-muted, #637083);
  margin-bottom: 4px;
}

.question-type {
  display: inline-block;
  font-size: 11px;
  color: var(--primary, #136f83);
  background: var(--primary-soft, #e6f4f7);
  padding: 2px 8px;
  border-radius: 4px;
}

.question-item .btn-danger {
  position: absolute;
  top: 8px;
  right: 8px;
}

.no-questions {
  text-align: center;
  color: var(--text-muted, #637083);
  padding: 16px;
}

.cache-trend-panel {
  margin-top: 12px;
  padding: 14px;
  border: 1px solid var(--border, #dbe3ee);
  border-radius: var(--radius-sm, 8px);
  background: var(--surface-soft, #f6f8fb);
}

.cache-trend-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 10px;
}

.cache-trend-head h4 {
  margin: 0 0 4px;
  color: var(--text-strong, #18212f);
  font-size: 15px;
  line-height: 1.25;
}

.cache-trend-head p {
  margin: 0;
  color: var(--text-muted, #637083);
  font-size: 12px;
}

.cache-trend-chart {
  width: 100%;
  overflow-x: auto;
}

.cache-trend-chart svg {
  display: block;
  width: 100%;
  min-width: 640px;
  height: 250px;
}

.cache-grid line {
  stroke: var(--border, #dbe3ee);
  stroke-width: 1;
}

.cache-axis-labels text {
  fill: var(--text-muted, #637083);
  font-size: 11px;
}

.cache-line {
  fill: none;
  stroke-width: 2.4;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.cache-point {
  stroke: var(--surface, #fff);
  stroke-width: 1.5;
}

.cache-trend-empty {
  display: grid;
  place-items: center;
  min-height: 180px;
  color: var(--text-muted, #637083);
  font-size: 13px;
  border: 1px dashed var(--border, #dbe3ee);
  border-radius: var(--radius-sm, 8px);
  background: var(--surface, #fff);
}

.cache-trend-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.cache-trend-legend span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 260px;
  padding: 5px 8px;
  border: 1px solid var(--border, #dbe3ee);
  border-radius: var(--radius-sm, 8px);
  background: var(--surface, #fff);
  color: var(--text-muted, #637083);
  font-size: 12px;
}

.cache-trend-legend i {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: 0 0 auto;
}

.cache-trend-legend em {
  color: var(--text-subtle, #8793a5);
  font-style: normal;
}

.cache-trend-legend strong {
  color: var(--text-strong, #18212f);
  font-weight: 600;
}

@media (max-width: 760px) {
  .cache-trend-head {
    align-items: stretch;
    flex-direction: column;
  }

  .cache-trend-chart svg {
    min-width: 560px;
  }
}
</style>
