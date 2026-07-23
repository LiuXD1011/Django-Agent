<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import { api, chunkingConfigError, normalizeChunkingConfig } from '../api'
import ChunkingSettings from '../components/ChunkingSettings.vue'
import Wiki from './Wiki.vue'
import KnowledgeTraceTimeline from './chat/components/KnowledgeTraceTimeline.vue'
import KnowledgeProcessingRecords from './knowledge/components/KnowledgeProcessingRecords.vue'

const route = useRoute()
const router = useRouter()
const kbId = String(route.params.kbId)

const kb = ref<any>(null)
const docs = ref<any[]>([])
const processingRecords = ref<any[]>([])
const statusCounts = ref<Record<string, number>>({})
const tagCounts = ref<Record<string, number>>({})
const tags = ref<any[]>([])
const chunks = ref<any[]>([])
const dirtyChunkIds = ref(new Set<string>())
const chunkImageUrls = ref<Record<string, string>>({})
const selectedIds = ref<string[]>([])
const activeDoc = ref<any>(null)
const requestedTab = String(route.query.tab || 'documents')
const activeTab = ref(requestedTab === 'settings' ? 'documents' : requestedTab)
const loading = ref(false)
const uploading = ref(false)
const chunkVisible = ref(false)
const tagVisible = ref(false)
const uploadVisible = ref(false)
const settingsVisible = ref(requestedTab === 'settings')
const moveVisible = ref(false)
const isMobileDocumentView = ref(false)
const deleteTarget = ref<any>(null)
const deleteLoading = ref(false)
const batchDeleteVisible = ref(false)
const filters = ref({ keyword: '', tag_id: '', parse_status: '', file_type: '' })
const tagForm = ref({ name: '', color: '#66713b' })
const uploadFiles = ref<File[]>([])
const uploadStates = ref<Record<string, { status: string; error?: string; deduplicated?: boolean }>>({})
const moveTargets = ref<any[]>([])
const targetKbId = ref('')
const uploadForm = ref({
  tag_id: '',
  chunking_config: normalizeChunkingConfig(),
  graph_enabled: false,
})
const settingsForm = ref({
  name: '',
  description: '',
  chunking_config: normalizeChunkingConfig(),
  indexing_strategy: { vector_enabled: true, keyword_enabled: true, wiki_enabled: false, graph_enabled: false },
  extract_config: {
    enabled: false,
    text: '从知识片段中抽取核心实体和实体关系，用于 GraphRAG 检索增强。',
    tags: ['related_to', 'part_of', 'depends_on', 'uses', 'describes'],
    nodes: [{ name: 'Entity' }, { name: 'Concept' }],
    relations: [
      { node1: 'Entity', node2: 'Entity', type: 'related_to' },
      { node1: 'Entity', node2: 'Concept', type: 'describes' },
    ],
  },
  wiki_config: { auto_generate_outline: true },
})

function syncMobileDocumentView() {
  isMobileDocumentView.value = window.matchMedia('(max-width: 760px)').matches
}

const statusLabels: Record<string, string> = {
  pending: '等待解析',
  processing: '解析中',
  finalizing: '索引中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

const visibleDocs = computed(() => docs.value)
const isWikiEnabled = computed(() => !!(kb.value?.indexing_strategy?.wiki_enabled || kb.value?.capabilities?.wiki))
const isGraphEnabled = computed(() => !!(kb.value?.indexing_strategy?.graph_enabled || kb.value?.capabilities?.graph))
const typeName = computed(() => (isWikiEnabled.value ? 'RAG + Wiki 知识库' : '文档知识库'))
const totalItems = computed(() => visibleDocs.value.length)
const selectedDocSet = computed(() => new Set(selectedIds.value))
const allDocsSelected = computed(() => !!visibleDocs.value.length && visibleDocs.value.every((doc) => selectedDocSet.value.has(doc.id)))
const fileTypeOptions = [
  'pdf', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx', 'md', 'markdown', 'html', 'htm',
  'csv', 'json', 'txt', 'log', 'py', 'jpg', 'jpeg', 'png', 'gif', 'bmp', 'tif', 'tiff',
  'webp', 'svg',
]
const unsupportedMediaExtensions = new Set(['mp3', 'wav', 'm4a', 'aac', 'ogg', 'flac', 'mp4', 'mov', 'avi', 'mkv', 'webm'])
const chunkTypeLabels: Record<string, string> = {
  text: '正文',
  image_ocr: '图片 OCR',
  image_caption: '图片描述',
  image_container: '图片容器',
  parent_text: '上下文父块',
}
const readOnlyChunkTypes = new Set(['parent_text', 'image_container'])

function isReadOnlyChunk(chunk: any) {
  return readOnlyChunkTypes.has(chunk.chunk_type)
}
const settingsHybridEnabled = computed({
  get: () => !!(settingsForm.value.indexing_strategy.vector_enabled || settingsForm.value.indexing_strategy.keyword_enabled),
  set: (enabled: boolean) => {
    settingsForm.value.indexing_strategy.vector_enabled = enabled
    settingsForm.value.indexing_strategy.keyword_enabled = enabled
  },
})
const activeTagName = computed(() => {
  if (!filters.value.tag_id) return '全部标签'
  return tags.value.find((tag) => tag.id === filters.value.tag_id)?.name || '已选标签'
})
function statusTheme(status: string) {
  if (status === 'completed') return 'success'
  if (status === 'failed' || status === 'cancelled') return 'danger'
  return 'warning'
}

function statusTone(status: string) {
  if (status === 'completed') return 'done'
  if (status === 'failed' || status === 'cancelled') return 'bad'
  if (status === 'processing' || status === 'finalizing') return 'busy'
  return 'waiting'
}

function loadCurrent() {
  return loadDocs()
}

async function clearFilters() {
  filters.value = { keyword: '', tag_id: '', parse_status: '', file_type: '' }
  await loadCurrent()
}

async function selectTag(tagId: string) {
  filters.value.tag_id = tagId
  await loadCurrent()
}

async function selectStatus(status: string) {
  filters.value.parse_status = filters.value.parse_status === status ? '' : status
  await loadDocs()
}

function toggleAllDocs() {
  selectedIds.value = allDocsSelected.value ? [] : visibleDocs.value.map((doc) => doc.id)
}

function fileSize(bytes: number) {
  if (!bytes) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

async function load() {
  loading.value = true
  try {
  const [kbRes, tagRes]: any[] = await Promise.all([api.getKb(kbId), api.listTags(kbId)])
    kb.value = kbRes.data
    hydrateSettingsForm()
    tags.value = tagRes.data?.items || []
    await loadDocs()
  } finally {
    loading.value = false
  }
}

async function loadDocs() {
  const params: any = { page: 1, page_size: 100 }
  Object.entries(filters.value).forEach(([key, value]) => {
    if (value) params[key] = value
  })
  const res: any = await api.listKnowledge(kbId, params)
  docs.value = res.data?.items || []
  statusCounts.value = res.data?.status_counts || {}
  tagCounts.value = res.data?.tag_counts || {}
  processingRecords.value = res.data?.processing_records || []
  const visibleIds = new Set(docs.value.map((doc) => doc.id))
  selectedIds.value = selectedIds.value.filter((id) => visibleIds.has(id))
}

function queueUpload(ev: Event) {
  const rawFiles = Array.from((ev.target as HTMLInputElement).files || [])
  ;(ev.target as HTMLInputElement).value = ''
  if (!rawFiles.length) return

  const rejectedFiles = rawFiles.filter((file) => unsupportedMediaExtensions.has(file.name.split('.').pop()?.toLowerCase() || ''))
  if (rejectedFiles.length) {
    MessagePlugin.warning(`不支持音频或视频文件：${rejectedFiles.map((file) => file.name).join('、')}`)
  }
  const acceptedFiles = rawFiles.filter((file) => !unsupportedMediaExtensions.has(file.name.split('.').pop()?.toLowerCase() || ''))
  if (!acceptedFiles.length) return

  // 去重：基于文件名+大小+最后修改时间
  const seen = new Set(uploadFiles.value.map(f => `${f.name}:${f.size}:${f.lastModified}`))
  const newFiles = acceptedFiles.filter((file) => {
    const key = `${file.name}:${file.size}:${file.lastModified}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })

  // 追加到现有列表（不覆盖）
  uploadFiles.value = [...uploadFiles.value, ...newFiles]

  // 首次选择时初始化表单
  if (!uploadVisible.value) {
    uploadForm.value = {
      tag_id: filters.value.tag_id || '',
      chunking_config: normalizeChunkingConfig(kb.value?.chunking_config),
      graph_enabled: isGraphEnabled.value,
    }
  }
  uploadVisible.value = true
}

function removeUploadFile(index: number) {
  uploadFiles.value = uploadFiles.value.filter((_, i) => i !== index)
  if (!uploadFiles.value.length) uploadVisible.value = false
}

function uploadProcessConfig() {
  const graphEnabled = !!uploadForm.value.graph_enabled
  return {
    chunking_config: normalizeChunkingConfig(uploadForm.value.chunking_config),
    graph_enabled: graphEnabled,
    extract_config: graphEnabled ? { ...(kb.value?.extract_config || settingsForm.value.extract_config), enabled: true } : { enabled: false },
  }
}

function defaultProcessConfig() {
  const graphEnabled = isGraphEnabled.value
  return {
    chunking_config: normalizeChunkingConfig(settingsForm.value.chunking_config),
    graph_enabled: graphEnabled,
    extract_config: graphEnabled ? { ...(kb.value?.extract_config || settingsForm.value.extract_config), enabled: true } : { enabled: false },
  }
}

function updateExtractTags(value: string | number) {
  settingsForm.value.extract_config.tags = String(value || '').split(',').map((item) => item.trim()).filter(Boolean)
}

async function confirmUpload() {
  if (!uploadFiles.value.length || uploading.value) return
  const configError = chunkingConfigError(uploadForm.value.chunking_config)
  if (configError) {
    MessagePlugin.warning(configError)
    return
  }
  uploading.value = true
  const process_config = uploadProcessConfig()
  let created = 0
  let deduplicated = 0
  let failed = 0

  const queue = [...uploadFiles.value]
  const worker = async () => {
    while (queue.length) {
      const file = queue.shift()
      if (!file) return
      const key = `${file.name}:${file.size}:${file.lastModified}`
      uploadStates.value[key] = { status: 'uploading' }
      try {
        const res: any = await api.uploadFile(kbId, file, { tag_id: uploadForm.value.tag_id, process_config })
        if (res.data?.deduplicated) { deduplicated += 1; uploadStates.value[key] = { status: 'deduplicated', deduplicated: true } }
        else { created += 1; uploadStates.value[key] = { status: 'success' } }
      } catch (error: any) {
        failed += 1
        uploadStates.value[key] = { status: 'failed', error: error?.message || '上传失败' }
      }
    }
  }
  await Promise.all([worker(), worker(), worker()])

  // 成功项离开队列，失败项保留以便单独重试。
  uploading.value = false
  if (failed) {
    uploadFiles.value = uploadFiles.value.filter((file) => uploadStates.value[`${file.name}:${file.size}:${file.lastModified}`]?.status === 'failed')
    uploadVisible.value = true
  } else {
    uploadFiles.value = []
    uploadStates.value = {}
    uploadVisible.value = false
  }
  await loadDocs()

  // 显示准确的结果消息
  const successCount = created + deduplicated
  if (failed === 0) {
    MessagePlugin.success(deduplicated ? `已提交 ${created} 个文件，跳过 ${deduplicated} 个重复文件` : `已提交 ${successCount} 个文件解析`)
  } else if (successCount > 0) {
    MessagePlugin.warning(`成功 ${successCount} 个，失败 ${failed} 个`)
  } else {
    MessagePlugin.error(`${failed} 个文件上传失败，请重试`)
  }
}

async function removeDoc(doc: any) {
  deleteTarget.value = doc
}

async function confirmRemoveDoc() {
  if (!deleteTarget.value || deleteLoading.value) return
  deleteLoading.value = true
  try {
    await api.deleteKnowledge(deleteTarget.value.id)
    await loadDocs()
    deleteTarget.value = null
    MessagePlugin.success('文档已删除')
  } finally {
    deleteLoading.value = false
  }
}

async function batchDeleteDocs() {
  if (!selectedIds.value.length) return
  batchDeleteVisible.value = true
}

async function confirmBatchDeleteDocs() {
  await api.batchDeleteKnowledge(selectedIds.value, kbId)
  selectedIds.value = []
  batchDeleteVisible.value = false
  await loadDocs()
}

async function reparse(doc: any) {
  await api.reparseKnowledge(doc.id, { process_config: defaultProcessConfig() })
  await loadDocs()
}

async function cancelParse(doc: any) {
  await api.cancelKnowledge(doc.id)
  await loadDocs()
}

async function loadChunksForDoc(doc: any) {
  const res: any = await api.listChunks(doc.id, { page: 1, page_size: 200 })
  chunks.value = res.data?.items || res.data?.chunks || []
  dirtyChunkIds.value.clear()
  clearChunkImageUrls()
  const imageIds = [...new Set(chunks.value.map((chunk) => chunk.image_info?.image_id).filter(Boolean))]
  await Promise.all(imageIds.map(async (imageId) => {
    try {
      const imageRes: any = await api.knowledgeImage(doc.id, String(imageId))
      const blob = imageRes instanceof Blob ? imageRes : imageRes?.data
      if (blob) chunkImageUrls.value[String(imageId)] = URL.createObjectURL(blob)
    } catch {
      // 图片预览失败不影响 Chunk 文本编辑。
    }
  }))
}

async function openChunks(doc: any) {
  activeDoc.value = doc
  await loadChunksForDoc(doc)
  chunkVisible.value = true
}

function clearChunkImageUrls() {
  Object.values(chunkImageUrls.value).forEach((url) => URL.revokeObjectURL(url))
  chunkImageUrls.value = {}
}

async function saveChunk(chunk: any) {
  await api.updateChunk(activeDoc.value.id, chunk.id, { content: chunk.content, is_enabled: chunk.is_enabled })
  MessagePlugin.success('摘录已更新')
  dirtyChunkIds.value.delete(String(chunk.id))
}

async function removeChunk(chunk: any) {
  await api.deleteChunk(activeDoc.value.id, chunk.id)
  chunks.value = chunks.value.filter((item) => item.id !== chunk.id)
}

async function chat() {
  const res: any = await api.createSession({ knowledge_base_id: kbId, title: `${kb.value?.name || '知识库'} 对话` })
  router.push(`/platform/chat/${res.data.id}`)
}

async function createTag() {
  if (!tagForm.value.name.trim()) return
  await api.createTag(kbId, tagForm.value)
  tagVisible.value = false
  tagForm.value = { name: '', color: '#66713b' }
  await load()
}

function hydrateSettingsForm() {
  if (!kb.value) return
  const strategy = kb.value.indexing_strategy || {}
  settingsForm.value = {
    name: kb.value.name || '',
    description: kb.value.description || '',
    chunking_config: normalizeChunkingConfig(kb.value.chunking_config),
    indexing_strategy: {
      vector_enabled: strategy.vector_enabled !== false,
      keyword_enabled: strategy.keyword_enabled !== false,
      wiki_enabled: !!strategy.wiki_enabled,
      graph_enabled: !!strategy.graph_enabled,
    },
    extract_config: {
      ...settingsForm.value.extract_config,
      ...(kb.value.extract_config || {}),
      enabled: !!strategy.graph_enabled,
    },
    wiki_config: {
      auto_generate_outline: true,
      ...(kb.value.wiki_config || {}),
    },
  }
}

async function saveSettings() {
  if (!settingsForm.value.name.trim()) {
    MessagePlugin.warning('请输入知识库名称')
    return
  }
  const strategy = settingsForm.value.indexing_strategy
  if (!(strategy.vector_enabled || strategy.keyword_enabled || strategy.wiki_enabled || strategy.graph_enabled)) {
    MessagePlugin.warning('至少开启一种索引配置')
    return
  }
  const configError = chunkingConfigError(settingsForm.value.chunking_config)
  if (configError) {
    MessagePlugin.warning(configError)
    return
  }
  const payload = {
    name: settingsForm.value.name,
    description: settingsForm.value.description,
    type: 'document',
    chunking_config: normalizeChunkingConfig(settingsForm.value.chunking_config),
    indexing_strategy: strategy,
    extract_config: {
      ...settingsForm.value.extract_config,
      enabled: !!strategy.graph_enabled,
    },
    wiki_config: settingsForm.value.wiki_config,
  }
  const res: any = await api.updateKb(kbId, payload)
  kb.value = res.data
  hydrateSettingsForm()
  MessagePlugin.success('知识库设置已保存')
}

async function openMoveDialog() {
  if (!selectedIds.value.length) return
  const res: any = await api.moveTargets(kbId)
  moveTargets.value = res.data?.items || []
  targetKbId.value = moveTargets.value[0]?.id || ''
  moveVisible.value = true
}

async function confirmMove() {
  if (!targetKbId.value || !selectedIds.value.length) return
  await api.moveKnowledge(selectedIds.value, targetKbId.value, kbId)
  selectedIds.value = []
  moveVisible.value = false
  await loadDocs()
  MessagePlugin.success('已移动所选文档')
}

watch(activeTab, (tab) => {
  const query = { ...route.query }
  if (tab === 'documents') delete query.tab
  else query.tab = tab
  router.replace({ query })
})

watch(() => route.query.tab, (value) => {
  const next = String(value || 'documents')
  if (next === 'settings') {
    activeTab.value = 'documents'
    hydrateSettingsForm()
    settingsVisible.value = true
    return
  }
  if (next !== activeTab.value) activeTab.value = next
})

watch(docs, async (items) => {
  if (!activeDoc.value?.id) return
  const updated = items.find((item) => item.id === activeDoc.value.id)
  if (!updated) return
  const wasProcessing = activeDoc.value.parse_status === 'processing'
  activeDoc.value = { ...activeDoc.value, ...updated }
  if (wasProcessing && updated.parse_status !== 'processing' && chunkVisible.value && dirtyChunkIds.value.size === 0) {
    await loadChunksForDoc(updated)
  }
})

watch(isWikiEnabled, (enabled) => {
  if (!enabled && activeTab.value === 'wiki') activeTab.value = 'documents'
})
watch(isGraphEnabled, (enabled) => {
  if (!enabled && activeTab.value === 'graph') activeTab.value = 'documents'
})

// ── 状态自动轮询 ────────────────────────────────────────────────────
const pollTimer = ref<ReturnType<typeof setInterval> | null>(null)
const POLL_INTERVAL = 3000

// 基于 API 返回的 processing_count 判断是否有正在处理的文档
const isProcessing = computed(() => (kb.value?.processing_count || 0) > 0)

function startPolling() {
  stopPolling()
  pollTimer.value = setInterval(refreshAll, POLL_INTERVAL)
}

async function refreshAll() {
  // 先刷新知识库信息以获取最新的 processing_count
  try {
    const res: any = await api.getKb(kbId)
    kb.value = res.data
  } catch { /* ignore */ }
  // 然后刷新文档列表
  await loadDocs()
}

function stopPolling() {
  if (pollTimer.value) {
    clearInterval(pollTimer.value)
    pollTimer.value = null
  }
}

watch(isProcessing, (processing) => {
  if (processing) startPolling()
  else stopPolling()
}, { immediate: true })

onMounted(load)
onMounted(() => {
  syncMobileDocumentView()
  window.addEventListener('resize', syncMobileDocumentView)
})
onUnmounted(() => {
  window.removeEventListener('resize', syncMobileDocumentView)
  stopPolling()
  clearChunkImageUrls()
})
</script>

<template>
  <main class="content kb-detail-page" v-if="kb">
    <section class="kb-workspace-header">
      <button class="kb-back-button" @click="router.push('/platform/knowledge-bases')">← 返回知识库</button>
      <div class="kb-workspace-title">
        <div class="paper-kicker">{{ typeName }}</div>
        <h2>{{ kb.name }}</h2>
      </div>
      <div class="kb-header-actions">
        <t-button variant="outline" @click="chat">发起对话</t-button>
        <t-button variant="outline" @click="hydrateSettingsForm(); settingsVisible = true">知识库设置</t-button>
        <label class="upload-button">上传文件<input type="file" multiple hidden @change="queueUpload" /></label>
      </div>
      <div class="kb-workspace-stats">
        <span><strong>{{ kb.knowledge_count || kb.document_count || 0 }}</strong> 条目</span>
        <span><strong>{{ kb.chunk_count || 0 }}</strong> 摘录</span>
        <span><strong>{{ kb.processing_count || 0 }}</strong> 处理中</span>
        <span><strong>{{ totalItems }}</strong> 当前</span>
      </div>
      <nav class="kb-tab-strip" aria-label="知识库工作台">
        <button :class="{ active: activeTab === 'documents' }" @click="activeTab = 'documents'">文档</button>
        <button :class="{ active: activeTab === 'wiki' }" :disabled="!isWikiEnabled" @click="activeTab = 'wiki'">Wiki</button>
        <button :class="{ active: activeTab === 'graph' }" :disabled="!isGraphEnabled" @click="activeTab = 'graph'">图谱</button>
        <button :class="{ active: activeTab === 'processing' }" @click="activeTab = 'processing'">解析记录</button>
      </nav>
    </section>

    <section class="kb-detail-shell" :class="{ 'no-side': activeTab !== 'documents' }">
      <aside v-if="activeTab === 'documents'" class="kb-side-panel" aria-label="知识库侧栏">
        <div class="side-card kb-side-summary">
          <div class="paper-kicker">Overview</div>
          <h3>{{ activeTagName }}</h3>
          <dl>
            <div><dt>类型</dt><dd>{{ typeName }}</dd></div>
            <div><dt>当前列表</dt><dd>{{ totalItems }}</dd></div>
          </dl>
        </div>

        <div class="side-card">
          <div class="side-card-head">
            <h3>标签</h3>
            <button class="text-link compact" @click="tagVisible = true">管理</button>
          </div>
          <div class="side-filter-list">
            <button class="side-filter" :class="{ active: !filters.tag_id }" @click="selectTag('')">
              <span>全部标签</span>
              <strong>{{ kb.knowledge_count || kb.document_count || totalItems }}</strong>
            </button>
            <button
              v-for="tag in tags"
              :key="tag.id"
              class="side-filter tag-filter"
              :class="{ active: filters.tag_id === tag.id }"
              :style="{ borderLeftColor: tag.color || '#66713b' }"
              @click="selectTag(tag.id)"
            >
              <span>{{ tag.name }}</span>
              <strong>{{ tag.knowledge_count || tag.document_count || tag.chunk_count || tagCounts[tag.id] || 0 }}</strong>
            </button>
            <div v-if="!tags.length" class="side-empty">暂无标签</div>
          </div>
        </div>

        <div class="side-card">
          <div class="side-card-head">
            <h3>解析状态</h3>
            <button class="text-link compact" @click="selectStatus('')">全部</button>
          </div>
          <div class="side-filter-list">
            <button
              v-for="(_, status) in statusLabels"
              :key="status"
              class="side-filter status-filter"
              :class="[statusTone(status), { active: filters.parse_status === status }]"
              @click="selectStatus(status)"
            >
              <span><i></i>{{ statusLabels[status] }}</span>
              <strong>{{ statusCounts[status] || 0 }}</strong>
            </button>
          </div>
        </div>
      </aside>

      <section class="kb-main-workbench">
        <template v-if="activeTab === 'documents'">
        <div class="workbench-bar detail-toolbar">
          <t-input v-model="filters.keyword" clearable placeholder="搜索标题、文件名或问题" @enter="loadCurrent" />
          <t-select v-model="filters.parse_status" class="filter-select" clearable placeholder="解析状态" @change="loadDocs">
            <t-option value="pending" label="等待解析" />
            <t-option value="processing" label="解析中" />
            <t-option value="finalizing" label="索引中" />
            <t-option value="completed" label="已完成" />
            <t-option value="failed" label="失败" />
            <t-option value="cancelled" label="已取消" />
          </t-select>
          <t-select v-model="filters.file_type" class="filter-select" clearable placeholder="文件类型" @change="loadDocs">
            <t-option v-for="type in fileTypeOptions" :key="type" :value="type" :label="type.toUpperCase()" />
          </t-select>
          <t-button variant="outline" @click="clearFilters">清空筛选</t-button>
        </div>

        <div class="workspace-panel document-panel">
          <div class="panel-head detail-panel-head">
            <div>
              <h3>文档工作台</h3>
              <span>{{ visibleDocs.length }} 条目，已选 {{ selectedIds.length }} 条</span>
            </div>
          </div>
          <div class="batch-bar">
            <label><input :checked="allDocsSelected" :disabled="!visibleDocs.length" type="checkbox" @change="toggleAllDocs" /> 全选当前列表</label>
            <div class="batch-actions">
              <t-button size="small" variant="outline" :disabled="!selectedIds.length" @click="batchDeleteDocs">批量删除</t-button>
              <t-button size="small" variant="outline" :disabled="!selectedIds.length" @click="openMoveDialog">移动到</t-button>
            </div>
          </div>
          <div class="document-table-wrap workbench-scroll">
            <table v-if="visibleDocs.length" class="data-table document-table">
              <thead>
                <tr>
                  <th></th>
                  <th>标题</th>
                  <th>来源</th>
                  <th>状态</th>
                  <th>大小</th>
                  <th>更新时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="doc in visibleDocs" :key="doc.id">
                  <td><input v-model="selectedIds" :value="doc.id" type="checkbox" /></td>
                  <td class="doc-title-cell">
                    <strong>{{ doc.title }}</strong>
                    <p>{{ doc.summary_status === 'completed' ? '摘要已生成' : (doc.error_message || '等待摘要/索引') }}</p>
                  </td>
                  <td class="doc-source" :title="doc.file_name || doc.source || doc.type">{{ doc.file_name || doc.source || doc.type || '-' }}</td>
                  <td>
                    <div class="status-stack">
                      <span :class="['parse-status-dot', statusTone(doc.parse_status)]"></span>
                      <t-tag :theme="statusTheme(doc.parse_status)">{{ statusLabels[doc.parse_status] || doc.parse_status || '未知' }}</t-tag>
                    </div>
                  </td>
                  <td>{{ fileSize(doc.file_size || doc.storage_size) }}</td>
                  <td>{{ doc.updated_at ? new Date(doc.updated_at).toLocaleString() : '-' }}</td>
                  <td class="action-cell">
                    <div class="table-actions tiered">
                      <button class="primary-action" @click="openChunks(doc)">Chunk</button>
                      <button @click="reparse(doc)">重解析</button>
                      <button v-if="doc.parse_status !== 'completed'" @click="cancelParse(doc)">取消</button>
                      <button class="danger" @click="removeDoc(doc)">删除</button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
            <div v-if="isMobileDocumentView" class="document-card-list">
              <article v-for="doc in visibleDocs" :key="`card-${doc.id}`" class="document-card">
                <div class="document-card-head">
                  <div class="document-card-title">
                    <input v-model="selectedIds" :value="doc.id" type="checkbox" :aria-label="`选择 ${doc.title}`" />
                    <strong>{{ doc.title }}</strong>
                  </div>
                  <div class="status-stack">
                    <span :class="['parse-status-dot', statusTone(doc.parse_status)]"></span>
                    <t-tag :theme="statusTheme(doc.parse_status)">{{ statusLabels[doc.parse_status] || doc.parse_status || '未知' }}</t-tag>
                  </div>
                </div>
                <p class="document-card-subtitle">{{ doc.summary_status === 'completed' ? '摘要已生成' : (doc.error_message || '等待摘要/索引') }}</p>
                <div class="document-card-meta">
                  <span>{{ fileSize(doc.file_size || doc.storage_size) }}</span>
                  <span>{{ doc.updated_at ? new Date(doc.updated_at).toLocaleString() : '-' }}</span>
                  <span>{{ doc.file_name || doc.source || doc.type || '-' }}</span>
                </div>
                <div class="document-card-actions">
                  <button class="primary-action" @click="openChunks(doc)">Chunk</button>
                  <button @click="reparse(doc)">重解析</button>
                  <button v-if="doc.parse_status !== 'completed'" @click="cancelParse(doc)">取消</button>
                  <button class="danger" @click="removeDoc(doc)">删除</button>
                </div>
              </article>
            </div>
            <div v-if="!visibleDocs.length && !loading" class="empty-state detail-empty">还没有知识条目，上传文件开始建库</div>
          </div>
        </div>
        </template>

        <template v-else-if="activeTab === 'wiki'">
          <Wiki :kb-id="kbId" :kb-name="kb.name" view="pages" embedded />
        </template>

        <template v-else-if="activeTab === 'graph'">
          <Wiki :kb-id="kbId" :kb-name="kb.name" view="graph" embedded />
        </template>

        <template v-else-if="activeTab === 'processing'">
          <KnowledgeProcessingRecords :records="processingRecords" :loading="loading" />
        </template>
      </section>

    </section>

    <t-drawer v-model:visible="chunkVisible" size="620px" :header="activeDoc?.title || 'Chunk 管理'">
      <KnowledgeTraceTimeline v-if="activeDoc?.id" :knowledge-id="activeDoc.id" :active="chunkVisible && activeDoc?.parse_status === 'processing'" />
      <div class="chunk-list">
        <article v-for="chunk in chunks" :key="chunk.id" class="chunk-editor">
          <div class="chunk-head">
            <span>#{{ chunk.chunk_index }} · {{ chunkTypeLabels[chunk.chunk_type] || chunk.chunk_type }}</span>
            <label v-if="!isReadOnlyChunk(chunk)"><input v-model="chunk.is_enabled" type="checkbox" /> 启用</label>
            <span v-else class="chunk-readonly-badge">只读</span>
          </div>
          <img v-if="chunkImageUrls[chunk.image_info?.image_id]" class="chunk-image-preview" :src="chunkImageUrls[chunk.image_info?.image_id]" :alt="chunk.image_info.source_ref || '知识图片'" />
          <div class="chunk-relationships">
            <p v-if="chunk.context_parent_id" class="chunk-parent"><strong>上下文父块：</strong>{{ chunk.context_parent_id }}</p>
            <p v-if="chunk.media_parent_id" class="chunk-parent"><strong>媒体容器：</strong>{{ chunk.media_parent_id }}</p>
            <p v-if="chunk.anchor_chunk_id" class="chunk-parent"><strong>锚定正文：</strong>{{ chunk.anchor_chunk_id }}</p>
          </div>
          <p v-if="isReadOnlyChunk(chunk)" class="chunk-readonly-content">{{ chunk.content }}</p>
          <template v-else>
            <textarea v-model="chunk.content" @input="dirtyChunkIds.add(String(chunk.id))"></textarea>
            <div class="card-actions inline">
              <button @click="saveChunk(chunk)">保存</button>
              <button class="danger" @click="removeChunk(chunk)">删除</button>
            </div>
          </template>
        </article>
        <div v-if="!chunks.length" class="empty-state">暂无摘录</div>
      </div>
    </t-drawer>
    <t-dialog
      :visible="!!deleteTarget"
      header="删除文档"
      confirm-btn="删除"
      cancel-btn="取消"
      theme="danger"
      :confirm-loading="deleteLoading"
      @close="deleteTarget = null"
      @confirm="confirmRemoveDoc"
    >
      <p>确定删除“{{ deleteTarget?.title }}”？文档、Chunk 和索引将一并删除。</p>
    </t-dialog>
    <t-dialog v-model:visible="batchDeleteVisible" header="批量删除文档" confirm-btn="删除" cancel-btn="取消" theme="danger" @confirm="confirmBatchDeleteDocs">
      <p>确定删除选中的 {{ selectedIds.length }} 个文档？相关 Chunk 和索引将一并删除。</p>
    </t-dialog>

    <t-dialog v-model:visible="tagVisible" header="标签管理" confirm-btn="新建标签" width="520px" @confirm="createTag">
      <div class="tag-manager">
        <div class="tag-row">
          <span v-for="tag in tags" :key="tag.id" class="meta-pill">{{ tag.name }}</span>
        </div>
        <t-input v-model="tagForm.name" label="标签名" />
      </div>
    </t-dialog>

    <t-dialog
      v-model:visible="uploadVisible"
      header="上传解析设置"
      width="680px"
      placement="center"
      attach="body"
      dialog-class-name="chunking-dialog"
      :confirm-btn="{ content: uploading ? '提交中...' : '开始解析', loading: uploading, disabled: uploading || !uploadFiles.length }"
      @confirm="confirmUpload"
    >
      <div class="upload-confirm-lite">
        <div class="upload-file-list-header">
          <strong>{{ uploadFiles.length }} 个文件</strong>
          <label class="upload-add-more">
            + 添加更多
            <input type="file" multiple hidden @change="queueUpload" />
          </label>
        </div>
        <div class="upload-file-list">
          <div v-for="(file, idx) in uploadFiles" :key="`${file.name}-${file.size}-${idx}`" class="upload-file-item">
            <span class="upload-file-name">{{ file.name }}</span>
            <span class="upload-file-size">{{ fileSize(file.size) }}</span>
            <span class="upload-file-status">{{ ({ uploading: '上传中', success: '成功', deduplicated: '已去重', failed: '失败' } as any)[uploadStates[`${file.name}:${file.size}:${file.lastModified}`]?.status] || '等待中' }}</span>
            <button class="upload-file-remove" @click="removeUploadFile(idx)">×</button>
          </div>
          <div v-if="!uploadFiles.length" class="upload-file-empty">请选择文件</div>
        </div>
        <t-select v-model="uploadForm.tag_id" clearable label="标签" placeholder="不设置标签">
          <t-option v-for="tag in tags" :key="tag.id" :value="tag.id" :label="tag.name" />
        </t-select>
        <ChunkingSettings v-model="uploadForm.chunking_config" />
        <label class="index-setting-row">
          <input v-model="uploadForm.graph_enabled" type="checkbox" />
          <span><strong>本次解析生成知识图谱</strong><small>使用当前知识库图谱抽取模板；Neo4j 未启用时会自动跳过</small></span>
        </label>
      </div>
    </t-dialog>

    <t-dialog v-model:visible="moveVisible" header="移动文档" confirm-btn="移动" width="520px" @confirm="confirmMove">
      <t-select v-model="targetKbId" placeholder="选择目标知识库">
        <t-option v-for="target in moveTargets" :key="target.id" :value="target.id" :label="target.name" />
      </t-select>
      <p class="dialog-hint">移动会同步迁移 chunk 与索引，并按目标知识库配置尝试重建图谱。</p>
    </t-dialog>

    <t-dialog v-model:visible="settingsVisible" header="快速设置" confirm-btn="保存" width="720px" placement="center" attach="body" dialog-class-name="chunking-dialog" @confirm="saveSettings">
      <div class="editor-grid">
        <t-input v-model="settingsForm.name" label="名称" />
        <t-textarea v-model="settingsForm.description" class="wide" label="描述" />
        <div class="capability-panel wide">
          <span>索引配置</span>
          <label><input v-model="settingsHybridEnabled" type="checkbox" /><span><strong>混合检索</strong><small>向量 + 关键词</small></span></label>
          <label><input v-model="settingsForm.indexing_strategy.wiki_enabled" type="checkbox" /><span><strong>Wiki 知识库</strong><small>结构化页面和链接图谱</small></span></label>
          <label><input v-model="settingsForm.indexing_strategy.graph_enabled" type="checkbox" /><span><strong>知识图谱</strong><small>实体关系增强检索</small></span></label>
        </div>
        <ChunkingSettings
          v-model="settingsForm.chunking_config"
          class="wide"
          :needs-reindex="kb.needs_reindex"
          :last-effective-strategy="kb.last_effective_strategy"
        />
      </div>
    </t-dialog>
  </main>
</template>
