<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import { api } from '../api'

const route = useRoute()
const router = useRouter()
const info = ref<any>({})
const models = ref<any[]>([])
const modelCounts = ref<Record<string, number>>({})
const usage = ref<any>({ total: {}, by_model: [], by_type: [], by_scenario: [], daily: [] })
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

// UI 偏好（localStorage）
const uiTheme = ref(localStorage.getItem('ui_theme') || 'light')
const uiFontSize = ref(localStorage.getItem('ui_font_size') || 'normal')

function saveUiPref(key: string, value: string) {
  localStorage.setItem(`ui_${key}`, value)
  if (key === 'theme') applyTheme(value)
  if (key === 'fontSize') applyFontSize(value)
}

function applyTheme(theme: string) {
  document.documentElement.setAttribute('data-theme', theme)
  if (theme === 'system') {
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
    document.documentElement.setAttribute('data-theme', prefersDark ? 'dark' : 'light')
  }
}

function applyFontSize(size: string) {
  const sizes: Record<string, string> = { small: '13px', normal: '14px', large: '16px' }
  document.documentElement.style.fontSize = sizes[size] || '14px'
}
const activeSection = ref(String(route.query.section || 'general'))
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
  { key: 'general', label: '常规设置', caption: '语言、主题、字体、记忆' },
  { key: 'user', label: '用户资料', caption: '账号与密码' },
  { key: 'models', label: '模型管理', caption: '对话 / Embedding / ReRank / 视觉' },
  { key: 'vector', label: '检索配置', caption: 'Top K / 阈值 / Rerank' },
  { key: 'websearch', label: '联网搜索', caption: 'WebSearch Provider' },
  { key: 'mcp', label: 'MCP', caption: '工具服务与凭证' },
  { key: 'parser', label: '解析引擎', caption: '文档解析与 DocReader' },
  { key: 'storage', label: '存储引擎', caption: 'FileSystemStorage 状态' },
  { key: 'tenant', label: '空间/API', caption: '租户与 API 信息' },
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
  asr: '语音转写',
  ASR: '语音转写',
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
const modelTypeOf = (model: any) => modelGroupKey(model.type || model.raw_type || model.legacy_type || model.role)
const visibleModels = computed(() => models.value.filter((model) => ['chat', 'embedding', 'rerank', 'vlm'].includes(modelTypeOf(model))))
const filteredModels = computed(() => activeModelType.value === 'all' ? visibleModels.value : visibleModels.value.filter((model) => modelTypeOf(model) === activeModelType.value))
const localModelTabCount = (key: string) => key === 'all' ? visibleModels.value.length : visibleModels.value.filter((model) => modelTypeOf(model) === key).length
const modelTabCount = (key: string) => {
  if (key === 'all') return Number(modelCounts.value.total ?? visibleModels.value.length)
  return Number(modelCounts.value[key] ?? localModelTabCount(key))
}
const usageTotal = computed(() => usage.value?.total || {})
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
    api.modelUsage({ range: 7 }),
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
  usage.value = usagePayload || { total: {}, by_model: [], by_type: [], by_scenario: [], daily: [] }
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

async function checkParser() {
  try {
    await api.checkParserEngine(kv.value.parser || {})
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
  router.replace({ path: '/platform/settings', query: { section } })
})

onMounted(() => {
  load()
  applyTheme(uiTheme.value)
  applyFontSize(uiFontSize.value)
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
          <div class="panel-head"><h3>常规设置</h3><p>界面语言、主题、字体与功能开关</p></div>
          <div class="settings-group">
            <!-- 主题 -->
            <div class="setting-row">
              <div class="setting-info">
                <label>主题</label>
                <p class="desc">选择浅色、深色或跟随系统</p>
              </div>
              <div class="setting-control">
                <select v-model="uiTheme" class="setting-select" @change="saveUiPref('theme', uiTheme)">
                  <option value="light">浅色</option>
                  <option value="dark">深色</option>
                  <option value="system">跟随系统</option>
                </select>
              </div>
            </div>

            <!-- 字体大小 -->
            <div class="setting-row">
              <div class="setting-info">
                <label>字体大小</label>
                <p class="desc">调整界面文字大小</p>
              </div>
              <div class="setting-control">
                <div class="radio-group">
                  <label :class="{ active: uiFontSize === 'small' }"><input v-model="uiFontSize" type="radio" value="small" @change="saveUiPref('fontSize', uiFontSize)" /> 小</label>
                  <label :class="{ active: uiFontSize === 'normal' }"><input v-model="uiFontSize" type="radio" value="normal" @change="saveUiPref('fontSize', uiFontSize)" /> 正常</label>
                  <label :class="{ active: uiFontSize === 'large' }"><input v-model="uiFontSize" type="radio" value="large" @change="saveUiPref('fontSize', uiFontSize)" /> 大</label>
                </div>
              </div>
            </div>

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
              <small>缓存 {{ formatNumber(usageTotal.cached_tokens) }}</small>
            </article>
            <article class="usage-stat">
              <span>输入 / 输出</span>
              <strong>{{ formatNumber(usageTotal.prompt_tokens) }} / {{ formatNumber(usageTotal.completion_tokens) }}</strong>
              <small>失败 {{ formatNumber(usageTotal.failed) }}</small>
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
              <t-tag :theme="engine.enabled ? 'success' : 'default'">{{ engine.enabled ? '可用' : '停用' }}</t-tag>
            </article>
            <article class="setting-tile wide-tile">
              <span>租户解析配置</span>
              <textarea v-model="kv.parser.notes" placeholder="解析偏好、OCR 或多模态说明"></textarea>
              <button @click="saveKv('parser-engine-config', kv.parser)">保存配置</button>
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

        <section v-if="activeSection === 'tenant'" class="settings-section">
          <div class="panel-head"><h3>空间与 API</h3></div>
          <div class="settings-grid">
            <article class="setting-tile">
              <span>当前空间</span>
              <strong>默认空间</strong>
              <p>组织功能已按你的要求移除，这里仅保留个人空间信息。</p>
            </article>
            <article class="setting-tile">
              <span>API</span>
              <strong>/api/v1</strong>
              <p>兼容 WeKnora 主要 API 路由，便于后续迁移组件。</p>
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
  </main>
</template>
