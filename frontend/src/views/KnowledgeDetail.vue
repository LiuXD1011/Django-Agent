<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import type { VNodeRef } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import { api, chunkingConfigError, normalizeChunkingConfig } from '../api'
import ChunkingSettings from '../components/ChunkingSettings.vue'
import Wiki from './Wiki.vue'
import KnowledgeTraceTimeline from './chat/components/KnowledgeTraceTimeline.vue'
import KnowledgeProcessingRecords from './knowledge/components/KnowledgeProcessingRecords.vue'

const route = useRoute()
const router = useRouter()
const kbId = ref(String(route.params.kbId || ''))

const kb = ref<any>(null)
const docs = ref<any[]>([])
const processingRecords = ref<any[]>([])
const statusCounts = ref<Record<string, number>>({})
const tagCounts = ref<Record<string, number>>({})
const tags = ref<any[]>([])
const chunks = ref<any[]>([])
const citationChunk = ref<any>(null)
const citationError = ref('')
const citationLoading = ref(false)
const displayedChunks = computed(() => citationChunk.value ? [citationChunk.value] : chunks.value)
const citationTarget = ref<HTMLElement | null>(null)
const setCitationTarget: VNodeRef = element => {
  citationTarget.value = element && 'focus' in element ? element as HTMLElement : null
}
let citationReadGeneration = 0
let kbLoadGeneration = 0
let docsLoadGeneration = 0
let refreshGeneration = 0
let detailClosed = false
let citationFocusObserver: MutationObserver | null = null
let citationFocusCleanup: (() => void) | null = null
const dirtyChunkIds = ref(new Set<string>())
const chunkImageUrls = ref<Record<string, string>>({})
const chunkPage = ref(1)
const chunkPageSize = 50
const chunkTotal = ref(0)
const chunkTypeFilter = ref('')
const chunkLoading = ref(false)
const selectedIds = ref<string[]>([])
const activeDoc = ref<any>(null)
const requestedTab = String(route.query.tab || 'documents')
const activeTab = ref(requestedTab === 'settings' ? 'documents' : requestedTab)
const loading = ref(true)
const loadError = ref<'unavailable' | 'retryable' | null>(null)
const uploading = ref(false)
const chunkVisible = ref(false)
const tagVisible = ref(false)
const uploadVisible = ref(false)
const collectVisible = ref(route.query.collect === '1')
const settingsVisible = ref(requestedTab === 'settings')
const moveVisible = ref(false)
const isMobileDocumentView = ref(false)
const deleteTarget = ref<any>(null)
const deleteLoading = ref(false)
const batchDeleteVisible = ref(false)
const filters = ref({ keyword: '', tag_id: '', parse_status: '', file_type: '' })
const tagForm = ref({ name: '', color: '#66713b' })
const uploadFiles = ref<File[]>([])
const uploadInput = ref<HTMLInputElement | null>(null)
const collectInput = ref<HTMLInputElement | null>(null)
const photoInput = ref<HTMLInputElement | null>(null)
const additionalUploadInput = ref<HTMLInputElement | null>(null)
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
const unsupportedPhotoExtensions = new Set(['heic', 'heif'])
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
  if (status === 'failed' || status === 'cancelled' || status === 'interrupted') return 'danger'
  return 'warning'
}

function statusTone(status: string) {
  if (status === 'completed') return 'done'
  if (status === 'failed' || status === 'cancelled' || status === 'interrupted') return 'bad'
  if (status === 'processing' || status === 'finalizing') return 'busy'
  return 'waiting'
}

function workflowStatus(doc: any) {
  return String(doc?.workflow_status ?? doc?.metadata?.workflow_status ?? '')
}

function documentStatus(doc: any) {
  const workflow = workflowStatus(doc)
  return ['pending', 'processing', 'failed', 'cancelled', 'interrupted'].includes(workflow)
    ? workflow : String(doc?.parse_status || '')
}

function documentStatusLabel(doc: any) {
  const status = documentStatus(doc)
  return status === 'interrupted' ? '已中断' : statusLabels[status] || status || '未知'
}

function isDocumentProcessing(doc: any) {
  return ['pending', 'processing', 'finalizing'].includes(documentStatus(doc))
}

function sourceGeneration(doc: any) {
  return String(doc?.source_generation ?? doc?.metadata?.source_generation ?? '')
}

function hasProcessingWarning(doc: any, code: string) {
  if (Array.isArray(doc.processing_warning_codes)) return doc.processing_warning_codes.includes(code)
  return Array.isArray(doc.metadata?.processing_warnings) && doc.metadata.processing_warnings.some((warning: any) => warning?.code === code)
}

function documentErrorMessage(doc: any) {
  const errors: Record<string, string> = { document_processing_failed: '文档处理失败', scheduling_failed: '任务启动失败', model_result_unknown: '模型请求结果未确认' }
  return errors[doc.error_message] || doc.error_message || ''
}

function summaryText(doc: any) {
  const workflow = workflowStatus(doc), status = documentStatus(doc)
  const retained = doc.description?.trim() ? `；保留已有摘要：${doc.description}` : ''
  if (status === 'cancelled') return `${workflow ? '处理' : '解析'}已取消${retained || '，摘要未生成'}`
  if (status === 'interrupted') return `处理已中断，请手动重解析${retained}`
  if (status === 'failed') {
    if (workflow === 'failed') {
      return `本次处理失败：${documentErrorMessage(doc) || '请查看解析记录'}${retained}`
    }
    return doc.error_message || '解析失败，摘要未生成'
  }
  if (workflow && isDocumentProcessing(doc)) return retained ? `处理中${retained}` : '等待摘要/索引'
  if (hasProcessingWarning(doc, 'postprocess_source_empty')) {
    if (hasProcessingWarning(doc, 'vlm_needs_configuration')) return `图片识别模型未配置，暂无法生成摘要${retained}`
    return retained ? `未提取到可用于摘要的内容，请检查原文件${retained}` : '未提取到可用于摘要的内容，请检查原文件'
  }
  if (doc.description?.trim()) return doc.description
  if (doc.summary_status === 'completed') return '摘要已生成'
  if (doc.summary_status === 'failed') return '摘要生成失败，可重解析重试'
  if (doc.summary_status === 'needs_configuration') return '摘要模型未配置'
  if (doc.error_message) return doc.error_message
  return '等待摘要/索引'
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
  if (detailClosed) return
  const requestedKb = kbId.value
  const generation = ++kbLoadGeneration
  ++docsLoadGeneration
  const current = () => !detailClosed && generation === kbLoadGeneration
    && kbId.value === requestedKb && String(route.params.kbId) === requestedKb
  loading.value = true
  loadError.value = null
  try {
    const [kbRes, tagRes]: any[] = await Promise.all([api.getKb(requestedKb), api.listTags(requestedKb)])
    if (!current()) return
    kb.value = kbRes.data
    hydrateSettingsForm()
    tags.value = tagRes.data?.items || []
    await loadDocs()
    if (!current()) return
    loading.value = false
    await openCitationFromRoute()
  } catch (error: any) {
    if (!current()) return
    const status = Number(error?.response?.status ?? error?.status)
    loadError.value = [401, 403, 404, 410].includes(status) ? 'unavailable' : 'retryable'
    stopPolling()
  } finally {
    if (current()) loading.value = false
  }
}

async function loadDocs() {
  const requestedKb = kbId.value
  const generation = ++docsLoadGeneration
  const params: any = { page: 1, page_size: 100 }
  Object.entries(filters.value).forEach(([key, value]) => {
    if (value) params[key] = value
  })
  const res: any = await api.listKnowledge(requestedKb, params)
  if (detailClosed || generation !== docsLoadGeneration || kbId.value !== requestedKb || String(route.params.kbId) !== requestedKb) return
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
  const unsupportedPhotos = rawFiles.filter((file) => unsupportedPhotoExtensions.has(file.name.split('.').pop()?.toLowerCase() || ''))
  if (unsupportedPhotos.length) MessagePlugin.warning('当前服务仅接收已支持的图片格式，请先将 HEIC/HEIF 转为 JPEG 或 PNG')
  const acceptedFiles = rawFiles.filter((file) => {
    const extension = file.name.split('.').pop()?.toLowerCase() || ''
    return !unsupportedMediaExtensions.has(extension) && !unsupportedPhotoExtensions.has(extension)
  })
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
  collectVisible.value = false
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
        const res: any = await api.uploadFile(kbId.value, file, { tag_id: uploadForm.value.tag_id, process_config })
        if (res.data?.deduplicated) { deduplicated += 1; uploadStates.value[key] = { status: 'deduplicated', deduplicated: true } }
        else { created += 1; uploadStates.value[key] = { status: 'success' } }
      } catch (error: any) {
        failed += 1
        uploadStates.value[key] = { status: 'failed', error: error?.error?.message || error?.message || '上传失败' }
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
  await refreshAll()

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
    await refreshAll()
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
  await api.batchDeleteKnowledge(selectedIds.value, kbId.value)
  selectedIds.value = []
  batchDeleteVisible.value = false
  await refreshAll()
}

async function reparse(doc: any) {
  await api.reparseKnowledge(doc.id, { process_config: defaultProcessConfig() })
  await refreshAll()
}

async function cancelParse(doc: any) {
  await api.cancelKnowledge(doc.id)
  await refreshAll()
}

async function loadChunksForDoc(doc: any, page = chunkPage.value, chunkType = chunkTypeFilter.value) {
  const requestedKb = kbId.value
  const generation = citationReadGeneration
  const current = () => !detailClosed && generation === citationReadGeneration
    && kbId.value === requestedKb && String(route.params.kbId) === requestedKb
    && activeDoc.value?.id === doc.id && !citationChunk.value
  chunkLoading.value = true
  try {
    const res: any = await api.listChunks(doc.id, {
      page,
      page_size: chunkPageSize,
      ...(chunkType ? { chunk_type: chunkType } : {}),
    })
    if (!current()) return
    if (dirtyChunkIds.value.size > 0) {
      citationError.value = '当前分块有未保存的修改，请先保存再刷新'
      return
    }
    chunks.value = res.data?.items || []
    chunkTotal.value = Number(res.data?.total || 0)
    chunkPage.value = Number(res.data?.page || page)
    chunkTypeFilter.value = chunkType
    dirtyChunkIds.value.clear()
    clearChunkImageUrls()
    const imageIds = [...new Set(chunks.value.map((chunk) => chunk.image_info?.image_id).filter(Boolean))]
    await Promise.all(imageIds.map(async (imageId) => {
      try {
        const imageRes: any = await api.knowledgeImage(doc.id, String(imageId))
        if (!current()) return
        const blob = imageRes instanceof Blob ? imageRes : imageRes?.data
        if (blob) chunkImageUrls.value[String(imageId)] = URL.createObjectURL(blob)
      } catch {
        // 图片预览失败不影响 Chunk 文本编辑。
      }
    }))
  } finally {
    if (generation === citationReadGeneration) chunkLoading.value = false
  }
}

async function openChunks(doc: any) {
  if (dirtyChunkIds.value.size > 0) {
    citationError.value = '当前分块有未保存的修改，请先保存再打开其他来源'
    return
  }
  ++citationReadGeneration
  stopCitationFocus()
  citationChunk.value = null
  citationError.value = ''
  citationLoading.value = false
  activeDoc.value = doc
  chunkPage.value = 1
  chunkTypeFilter.value = ''
  chunkTotal.value = 0
  const generation = citationReadGeneration
  await loadChunksForDoc(doc, 1, '')
  if (!detailClosed && generation === citationReadGeneration && activeDoc.value?.id === doc.id) chunkVisible.value = true
}

function stopCitationFocus() {
  citationFocusObserver?.disconnect()
  citationFocusObserver = null
  citationFocusCleanup?.()
  citationFocusCleanup = null
}

function setChunkVisible(visible: boolean) {
  if (!visible && dirtyChunkIds.value.size > 0) {
    MessagePlugin.warning('当前分块有未保存的修改，请先保存再关闭')
    return
  }
  chunkVisible.value = visible
  if (!visible) stopCitationFocus()
}

function focusCitationWhenVisible(current: () => boolean) {
  stopCitationFocus()
  const target = citationTarget.value
  if (!target) return
  const focus = () => {
    if (!current() || !chunkVisible.value || citationTarget.value !== target) { stopCitationFocus(); return }
    if (getComputedStyle(target).visibility !== 'visible') return
    target.scrollIntoView({ block: 'nearest' })
    target.focus({ preventScroll: true })
    stopCitationFocus()
  }
  // Drawer 的子组件异步更新 visibility；只观察影响目标可见性的祖先属性。
  citationFocusObserver = new MutationObserver(focus)
  const ancestors: HTMLElement[] = []
  for (let ancestor: HTMLElement | null = target; ancestor; ancestor = ancestor.parentElement) {
    ancestors.push(ancestor)
    citationFocusObserver.observe(ancestor, { attributes: true, attributeFilter: ['class', 'style'] })
    // CSS visibility 过渡完成时不会再修改 DOM 属性。
    ancestor.addEventListener('transitionend', focus)
    ancestor.addEventListener('transitioncancel', focus)
  }
  citationFocusCleanup = () => ancestors.forEach(ancestor => {
    ancestor.removeEventListener('transitionend', focus)
    ancestor.removeEventListener('transitioncancel', focus)
  })
  focus()
}

function sourceReadError(error: any) {
  const status = Number(error?.response?.status ?? error?.status)
  if (status === 401 || status === 403) return '无权查看此引用来源，请检查当前账号和空间'
  if (status === 404) return '引用来源不存在或已删除'
  return '引用来源加载失败，请稍后重试'
}

async function openCitationFromRoute() {
  const generation = ++citationReadGeneration
  stopCitationFocus()
  citationLoading.value = false
  const requestedKb = route.params.kbId
  const documentId = route.query.document
  const chunkId = route.query.chunk
  const current = () => !detailClosed && generation === citationReadGeneration
    && route.params.kbId === requestedKb && route.query.document === documentId && route.query.chunk === chunkId
    && kbId.value === requestedKb && kb.value?.id === requestedKb
  if (!documentId && !chunkId) {
    if (dirtyChunkIds.value.size > 0) return
    citationError.value = ''
    if (citationChunk.value) { citationChunk.value = null; chunkVisible.value = false }
    return
  }
  if (kb.value?.id !== requestedKb || kbId.value !== requestedKb) return
  if (dirtyChunkIds.value.size > 0) {
    citationError.value = '当前分块有未保存的修改，请先保存再打开其他来源'
    return
  }
  citationError.value = ''
  citationChunk.value = null
  chunkVisible.value = false
  chunkLoading.value = false
  const requestedIds = chunkId === undefined ? [requestedKb, documentId] : [requestedKb, documentId, chunkId]
  if (!requestedIds.every(id => typeof id === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(id))) {
    citationError.value = '引用缺少有效的知识库、文档或分块标识'
    return
  }
  citationLoading.value = true
  try {
    const docRes: any = await api.getKnowledge(documentId as string)
    if (!current()) return
    const doc = docRes.data
    if (doc?.id !== documentId || doc?.knowledge_base_id !== requestedKb) {
      citationError.value = '引用文档与知识库不匹配'
      return
    }
    if (chunkId === undefined) {
      if (dirtyChunkIds.value.size > 0) {
        citationError.value = '当前分块有未保存的修改，请先保存再打开其他来源'
        return
      }
      clearChunkImageUrls()
      activeDoc.value = doc
      chunks.value = []
      chunkPage.value = 1
      chunkTypeFilter.value = ''
      chunkTotal.value = 0
      await loadChunksForDoc(doc, 1, '')
      if (current()) chunkVisible.value = true
      return
    }
    const chunkRes: any = await api.getChunk(documentId as string, chunkId as string)
    if (!current()) return
    const chunk = chunkRes.data
    if (chunk?.id !== chunkId || chunk?.knowledge_id !== documentId || chunk?.knowledge_base_id !== requestedKb) {
      citationError.value = '引用分块与文档或知识库不匹配'
      return
    }
    if (dirtyChunkIds.value.size > 0) {
      citationError.value = '当前分块有未保存的修改，请先保存再打开其他来源'
      return
    }
    clearChunkImageUrls()
    activeDoc.value = doc
    citationChunk.value = chunk
    chunkVisible.value = true
    await nextTick()
    if (!current()) return
    focusCitationWhenVisible(current)
    const imageId = chunk.image_info?.image_id
    if (typeof imageId === 'string' && imageId) {
      try {
        const imageRes: any = await api.knowledgeImage(doc.id, imageId)
        if (!current()) return
        const blob = imageRes instanceof Blob ? imageRes : imageRes?.data
        if (blob instanceof Blob) chunkImageUrls.value[imageId] = URL.createObjectURL(blob)
      } catch { /* 图片预览失败不影响引用文本读取。 */ }
    }
  } catch (error: any) {
    if (current()) citationError.value = sourceReadError(error)
  } finally {
    if (generation === citationReadGeneration) citationLoading.value = false
  }
}

async function browseAllChunks() {
  if (!activeDoc.value || dirtyChunkIds.value.size > 0) {
    citationError.value = '当前分块有未保存的修改，请先保存再浏览完整文档'
    return
  }
  const requestedRoute = route.fullPath
  const opening = openChunks(activeDoc.value)
  const generation = citationReadGeneration
  try {
    await opening
  } catch (error: any) {
    if (generation === citationReadGeneration) citationError.value = sourceReadError(error)
    return
  }
  if (detailClosed || generation !== citationReadGeneration || route.fullPath !== requestedRoute) return
  const query = { ...route.query }
  delete query.document
  delete query.chunk
  await router.replace({ query })
}

async function handleChunkPageChange(pageInfo: any) {
  const page = Number(pageInfo?.current ?? pageInfo)
  if (!activeDoc.value || !Number.isFinite(page) || page === chunkPage.value) return
  if (dirtyChunkIds.value.size > 0) {
    MessagePlugin.warning('当前页有未保存的修改，请先保存再翻页')
    return
  }
  await loadChunksForDoc(activeDoc.value, page)
}

async function handleChunkTypeChange(value: any) {
  const chunkType = String(value || '')
  if (!activeDoc.value || chunkType === chunkTypeFilter.value) return
  if (dirtyChunkIds.value.size > 0) {
    MessagePlugin.warning('当前页有未保存的修改，请先保存再筛选')
    return
  }
  await loadChunksForDoc(activeDoc.value, 1, chunkType)
}

function clearChunkImageUrls() {
  Object.values(chunkImageUrls.value).forEach((url) => URL.revokeObjectURL(url))
  chunkImageUrls.value = {}
}

async function saveChunk(chunk: any) {
  const doc = activeDoc.value
  const requestedKb = kbId.value
  const generation = citationReadGeneration
  const submitted = { content: chunk.content, is_enabled: chunk.is_enabled }
  const current = () => !detailClosed && generation === citationReadGeneration
    && kbId.value === requestedKb && String(route.params.kbId) === requestedKb
    && activeDoc.value?.id === doc.id
  await api.updateChunk(doc.id, chunk.id, submitted)
  MessagePlugin.success('摘录已更新')
  if (!current()) return
  if (chunk.content === submitted.content && chunk.is_enabled === submitted.is_enabled) {
    dirtyChunkIds.value.delete(String(chunk.id))
  }
  if (chunkVisible.value && !citationChunk.value && dirtyChunkIds.value.size === 0) {
    await loadChunksForDoc(doc)
  }
  if (!current()) return
  await refreshAll()
}

async function removeChunk(chunk: any) {
  const doc = activeDoc.value
  const requestedKb = kbId.value
  await api.deleteChunk(doc.id, chunk.id)
  if (detailClosed || activeDoc.value?.id !== doc.id || kbId.value !== requestedKb) return
  dirtyChunkIds.value.delete(String(chunk.id))
  chunks.value = chunks.value.filter(item => item.id !== chunk.id)
  if (citationChunk.value?.id === chunk.id) {
    citationChunk.value = null
    chunks.value = []
    chunkPage.value = 1
    chunkTypeFilter.value = ''
    const query = { ...route.query }
    delete query.document
    delete query.chunk
    await router.replace({ query })
  }
  const remainingOnPage = chunks.value.length
  const page = remainingOnPage === 0 && chunkPage.value > 1 ? chunkPage.value - 1 : chunkPage.value
  await loadChunksForDoc(doc, page)
  await refreshAll()
}

async function chat() {
  const res: any = await api.createSession({ knowledge_base_id: kbId.value, title: `${kb.value?.name || '知识库'} 对话` })
  router.push(`/platform/chat/${res.data.id}`)
}

async function createTag() {
  if (!tagForm.value.name.trim()) return
  await api.createTag(kbId.value, tagForm.value)
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
  const res: any = await api.updateKb(kbId.value, payload)
  kb.value = res.data
  hydrateSettingsForm()
  MessagePlugin.success('知识库设置已保存')
}

async function openMoveDialog() {
  if (!selectedIds.value.length) return
  const res: any = await api.moveTargets(kbId.value)
  moveTargets.value = res.data?.items || []
  targetKbId.value = moveTargets.value[0]?.id || ''
  moveVisible.value = true
}

async function confirmMove() {
  if (!targetKbId.value || !selectedIds.value.length) return
  await api.moveKnowledge(selectedIds.value, targetKbId.value, kbId.value)
  selectedIds.value = []
  moveVisible.value = false
  await refreshAll()
  MessagePlugin.success('已移动所选文档')
}

watch(() => route.query.collect, (value) => {
  if (value === '1') collectVisible.value = true
})
watch(collectVisible, (visible) => {
  if (!visible && route.query.collect) {
    const query = { ...route.query }
    delete query.collect
    router.replace({ query })
  }
})

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
  const wasProcessing = isDocumentProcessing(activeDoc.value)
  const sourceChanged = sourceGeneration(updated) && sourceGeneration(updated) !== sourceGeneration(activeDoc.value)
  activeDoc.value = { ...activeDoc.value, ...updated }
  if ((wasProcessing && !isDocumentProcessing(updated) || sourceChanged) && chunkVisible.value && !citationChunk.value && dirtyChunkIds.value.size === 0) {
    await loadChunksForDoc(updated, chunkPage.value)
  }
})

watch(isWikiEnabled, (enabled) => {
  if (!enabled && activeTab.value === 'wiki') activeTab.value = 'documents'
})
watch(isGraphEnabled, (enabled) => {
  if (!enabled && activeTab.value === 'graph') activeTab.value = 'documents'
})

// 详情页之间直接跳转（最近访问/浏览器前进后退）时组件会被复用，
// 必须监听路由参数并按新知识库重置状态，否则页面与操作都停留在旧库上
watch(() => route.params.kbId, async (value) => {
  const nextKbId = String(value || '')
  if (!nextKbId || nextKbId === kbId.value) return
  if (dirtyChunkIds.value.size > 0) {
    citationError.value = '当前分块有未保存的修改，请先保存再切换知识库'
    const query = { ...route.query }
    if (citationChunk.value) { query.document = activeDoc.value.id; query.chunk = citationChunk.value.id }
    else { delete query.document; delete query.chunk }
    await router.replace({ path: `/platform/knowledge-bases/${encodeURIComponent(kbId.value)}`, query })
    return
  }
  ++citationReadGeneration
  stopCitationFocus()
  citationChunk.value = null
  citationError.value = ''
  citationLoading.value = false
  kbId.value = nextKbId
  kb.value = null
  loadError.value = null
  docs.value = []
  tags.value = []
  statusCounts.value = {}
  tagCounts.value = {}
  processingRecords.value = []
  stopPolling()
  clearChunkImageUrls()
  activeDoc.value = null
  chunkVisible.value = false
  selectedIds.value = []
  filters.value = { keyword: '', tag_id: '', parse_status: '', file_type: '' }
  await load()
})

watch([() => route.query.document, () => route.query.chunk], openCitationFromRoute)

// ── 状态自动轮询 ────────────────────────────────────────────────────
const pollTimer = ref<ReturnType<typeof setInterval> | null>(null)
const POLL_INTERVAL = 3000
let pollRefreshInFlight = false

// 处理中判定同时看 processing_count 与全库状态计数（status_counts 由后端
// 按整库统计、不受筛选影响）：上传/重解析只刷新文档列表，也能立即触发轮询
const isProcessing = computed(() =>
  !loadError.value && !loading.value && (
    (kb.value?.processing_count || 0) > 0
    || ['pending', 'processing', 'finalizing'].some((status) => (statusCounts.value[status] || 0) > 0)
    || docs.value.some(isDocumentProcessing) || processingRecords.value.some(isDocumentProcessing)
  ),
)

function startPolling() {
  stopPolling()
  pollTimer.value = setInterval(async () => {
    if (pollRefreshInFlight) return
    pollRefreshInFlight = true
    try { await refreshAll() }
    catch { /* 下一轮继续读取状态。 */ }
    finally { pollRefreshInFlight = false }
  }, POLL_INTERVAL)
}

async function refreshAll() {
  const requestedKb = kbId.value, generation = ++refreshGeneration, loadedGeneration = kbLoadGeneration
  const current = () => !detailClosed && generation === refreshGeneration && loadedGeneration === kbLoadGeneration
    && kbId.value === requestedKb && String(route.params.kbId) === requestedKb
  // 先刷新知识库信息以获取最新的 processing_count
  try {
    const res: any = await api.getKb(requestedKb)
    if (current() && res.data?.id === requestedKb) kb.value = res.data
  } catch { /* ignore */ }
  // 然后刷新文档列表
  if (current()) await loadDocs()
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
  detailClosed = true
  stopCitationFocus()
  ++citationReadGeneration
  ++kbLoadGeneration
  window.removeEventListener('resize', syncMobileDocumentView)
  stopPolling()
  clearChunkImageUrls()
})
</script>

<template>
  <main v-if="loadError || (loading && !kb)" class="content kb-load-page">
    <section class="workspace-panel kb-load-state" aria-label="知识库加载状态">
      <p v-if="loading" role="status">正在加载知识库…</p>
      <div v-else role="alert">
        <h2>无法打开知识库</h2>
        <p>{{ loadError === 'unavailable' ? '知识库不存在、已删除或无权访问' : '知识库加载失败，请检查网络或稍后重试' }}</p>
      </div>
      <div class="kb-load-actions">
        <t-button variant="outline" @click="router.push('/platform/knowledge-bases')">返回知识库</t-button>
        <t-button v-if="loadError === 'retryable' && !loading" @click="load">重试</t-button>
      </div>
    </section>
  </main>
  <p v-if="citationError" class="citation-source-error" role="alert">{{ citationError }}</p>
  <p v-if="citationLoading" role="status">正在读取引用来源…</p>
  <main class="content kb-detail-page" v-if="kb && !loadError">
    <p v-if="loading" role="status">正在加载知识库…</p>
    <section class="kb-workspace-header">
      <button class="kb-back-button" @click="router.push('/platform/knowledge-bases')">← 返回知识库</button>
      <div class="kb-workspace-title">
        <div class="paper-kicker">{{ typeName }}</div>
        <h2>{{ kb.name }}</h2>
      </div>
      <div class="kb-header-actions">
        <t-button variant="outline" @click="chat">发起对话</t-button>
        <t-button variant="outline" @click="hydrateSettingsForm(); settingsVisible = true">知识库设置</t-button>
        <button class="upload-button" type="button" @click="uploadInput?.click()">上传文件</button>
        <input ref="uploadInput" type="file" multiple hidden @change="queueUpload" />
        <button v-if="isMobileDocumentView" class="upload-button" type="button" @click="collectVisible = true">拍照 / 选图</button>
      </div>
      <div class="kb-workspace-stats">
        <span><strong>{{ kb.knowledge_count || kb.document_count || 0 }}</strong> 条目</span>
        <span><strong>{{ kb.chunk_count || 0 }}</strong> 摘录 · 共 {{ kb.total_chunk_count || kb.chunk_count || 0 }} 块</span>
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
              <strong>{{ tagCounts[tag.id] ?? 0 }}</strong>
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
                    <p>{{ summaryText(doc) }}</p>
                    <p v-if="doc.image_failed_count" class="doc-image-warning">⚠ 图片解析失败 {{ doc.image_failed_count }}/{{ doc.image_count }}，可重解析恢复</p>
                  </td>
                  <td class="doc-source" :title="doc.file_name || doc.source || doc.type">{{ doc.file_name || doc.source || doc.type || '-' }}</td>
                  <td>
                    <div class="status-stack">
                      <span :class="['parse-status-dot', statusTone(documentStatus(doc))]"></span>
                      <t-tag :theme="statusTheme(documentStatus(doc))">{{ documentStatusLabel(doc) }}</t-tag>
                    </div>
                  </td>
                  <td>{{ fileSize(doc.file_size || doc.storage_size) }}</td>
                  <td>{{ doc.updated_at ? new Date(doc.updated_at).toLocaleString() : '-' }}</td>
                  <td class="action-cell">
                    <div class="table-actions tiered">
                      <button class="primary-action" @click="openChunks(doc)">Chunk</button>
                      <button @click="reparse(doc)">重解析</button>
                      <button v-if="isDocumentProcessing(doc)" @click="cancelParse(doc)">取消</button>
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
                    <span :class="['parse-status-dot', statusTone(documentStatus(doc))]"></span>
                    <t-tag :theme="statusTheme(documentStatus(doc))">{{ documentStatusLabel(doc) }}</t-tag>
                  </div>
                </div>
                <p class="document-card-subtitle">{{ summaryText(doc) }}</p>
                <p v-if="doc.image_failed_count" class="doc-image-warning">⚠ 图片解析失败 {{ doc.image_failed_count }}/{{ doc.image_count }}，可重解析恢复</p>
                <div class="document-card-meta">
                  <span>{{ fileSize(doc.file_size || doc.storage_size) }}</span>
                  <span>{{ doc.updated_at ? new Date(doc.updated_at).toLocaleString() : '-' }}</span>
                  <span>{{ doc.file_name || doc.source || doc.type || '-' }}</span>
                </div>
                <div class="document-card-actions">
                  <button class="primary-action" @click="openChunks(doc)">Chunk</button>
                  <button @click="reparse(doc)">重解析</button>
                  <button v-if="isDocumentProcessing(doc)" @click="cancelParse(doc)">取消</button>
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
          <KnowledgeProcessingRecords :records="processingRecords" :loading="loading" :record-status="documentStatus" :record-status-label="documentStatusLabel" :record-error-label="documentErrorMessage" />
        </template>
      </section>

    </section>

    <t-drawer :visible="chunkVisible" @update:visible="setChunkVisible" size="620px" :footer="false" :close-btn="true" :header="activeDoc?.title || 'Chunk 管理'">
      <template #closeBtn>
        <button class="chunk-close-button" type="button" aria-label="关闭分块详情">×</button>
      </template>
      <div v-if="citationChunk" class="citation-source-range">
        <p>仅显示此引用片段；完整文档按每页 {{ chunkPageSize }} 条分块浏览。块序号不代表所在页。</p>
        <button type="button" @click="browseAllChunks">浏览文档全部分块</button>
      </div>
      <KnowledgeTraceTimeline v-if="activeDoc?.id" :knowledge-id="activeDoc.id" :active="chunkVisible && isDocumentProcessing(activeDoc)" />
      <div v-if="activeDoc?.image_failed_count" class="chunk-image-warning">
        ⚠️ {{ activeDoc.image_failed_count }}/{{ activeDoc.image_count }} 张图片解析失败，图片内容暂不可检索；可在文档列表“重解析”后恢复。
      </div>
      <div v-if="!citationChunk" class="chunk-toolbar">
        <t-select class="chunk-type-filter" :value="chunkTypeFilter" :disabled="chunkLoading" @change="handleChunkTypeChange">
          <t-option value="" label="全部类型" />
          <t-option value="text" label="正文" />
          <t-option value="image_ocr" label="图片 OCR" />
          <t-option value="image_caption" label="图片描述" />
        </t-select>
        <span class="chunk-total-label">{{ chunkTypeFilter ? `共 ${chunkTotal} 条` : `共 ${chunkTotal} 条（含父块/媒体容器）` }}</span>
      </div>
      <div class="chunk-list" :class="{ 'chunk-list-loading': chunkLoading }">
        <article v-for="chunk in displayedChunks" :key="chunk.id" class="chunk-editor" :class="{ 'is-citation-target': citationChunk?.id === chunk.id }" :tabindex="citationChunk?.id === chunk.id ? -1 : undefined" :ref="citationChunk?.id === chunk.id ? setCitationTarget : undefined">
          <div class="chunk-head">
            <span>#{{ chunk.chunk_index }} · {{ chunkTypeLabels[chunk.chunk_type] || chunk.chunk_type }}</span>
            <label v-if="!isReadOnlyChunk(chunk)"><input v-model="chunk.is_enabled" type="checkbox" @change="dirtyChunkIds.add(String(chunk.id))" /> 启用</label>
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
        <div v-if="!displayedChunks.length && !chunkLoading" class="empty-state">暂无摘录</div>
      </div>
      <t-pagination
        v-if="!citationChunk && chunkTotal > chunkPageSize"
        class="chunk-pagination"
        :current="chunkPage"
        :total="chunkTotal"
        :page-size="chunkPageSize"
        :show-page-size-selector="false"
        @change="handleChunkPageChange"
      />
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

    <t-dialog v-model:visible="collectVisible" header="采集文件" :footer="false" attach="body" dialog-class-name="mobile-collect-dialog">
      <p class="dialog-hint">目标知识库：{{ kb.name }}。文件与照片仅在你确认后上传。</p>
      <div class="mobile-collect-targets">
        <button class="upload-button" type="button" @click="collectInput?.click()">选择文件</button>
        <input ref="collectInput" type="file" multiple hidden @change="queueUpload" />
        <button class="upload-button" type="button" @click="photoInput?.click()">拍照 / 选图</button>
        <input ref="photoInput" type="file" accept="image/jpeg,image/png,image/webp" capture="environment" hidden @change="queueUpload" />
      </div>
      <p class="dialog-hint">上传期间请保持页面在前台。锁屏或关闭页面可能中断；未确认接收的文件需要重新选择。相机入口由当前浏览器提供，不访问相册或相机直到你点击。</p>
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
        <p class="dialog-hint">目标：{{ kb.name }}。确认后上传到服务器；上传期间请保持前台。服务器确认接收后，解析可继续进行。</p>
        <div class="upload-file-list-header">
          <strong>{{ uploadFiles.length }} 个文件</strong>
          <button class="upload-add-more" type="button" @click="additionalUploadInput?.click()">+ 添加更多</button>
          <input ref="additionalUploadInput" type="file" multiple hidden @change="queueUpload" />
        </div>
        <div class="upload-file-list">
          <div v-for="(file, idx) in uploadFiles" :key="`${file.name}-${file.size}-${idx}`" class="upload-file-item">
            <span class="upload-file-name">{{ file.name }}</span>
            <span class="upload-file-size">{{ fileSize(file.size) }}</span>
            <span class="upload-file-status">{{ uploadStates[`${file.name}:${file.size}:${file.lastModified}`]?.error || ({ uploading: '上传中', success: '成功', deduplicated: '已去重', failed: '失败' } as any)[uploadStates[`${file.name}:${file.size}:${file.lastModified}`]?.status] || '等待中' }}</span>
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

<style scoped>
.kb-load-page { display: block; height: 100%; max-width: none; padding: 10px 16px 14px; }
.kb-load-state { display: block; height: auto; overflow: visible; padding: 24px; }
.kb-load-actions { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 20px; }
.citation-source-error, .citation-source-range { padding: 12px 16px; }
.citation-source-error { color: var(--danger, #b42318); }
.citation-source-range { background: var(--surface-soft); border: 1px solid var(--border); border-radius: var(--radius); margin-bottom: 12px; }
.is-citation-target { outline: 2px solid var(--primary); outline-offset: 2px; }
.chunk-close-button { display: grid; place-items: center; width: 28px; height: 28px; padding: 0; border: 0; background: transparent; color: inherit; font-size: 24px; cursor: pointer; }
</style>
