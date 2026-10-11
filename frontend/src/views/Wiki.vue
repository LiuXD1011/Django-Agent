<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import { api } from '../api'
import { renderMarkdownLite } from '../utils/markdown-lite.mjs'

type GraphNode = { id?: string; slug: string; title: string; label?: string; page_type: string; link_count: number; x?: number; y?: number; vx?: number; vy?: number; pinned?: boolean }
type GraphEdge = { source: string; target: string }
type GraphData = { nodes: GraphNode[]; edges: GraphEdge[]; meta?: any }

const route = useRoute()
const router = useRouter()
const props = withDefaults(defineProps<{ kbId?: string; view?: 'graph' | 'pages'; embedded?: boolean; kbName?: string }>(), {
  kbId: '',
  view: undefined,
  embedded: false,
  kbName: '',
})
const kbId = computed(() => props.kbId || String(route.params.kbId || ''))
const tab = ref(props.view || String(route.query.tab || 'graph'))
const pages = ref<any[]>([])
const graph = ref<GraphData>({ nodes: [], edges: [], meta: {} })
const visible = ref(false)
const form = ref({ title: '', content: '' })
const editingPage = ref<{ kbId: string; slug: string; version: number } | null>(null)
const formKbId = ref('')
const saving = ref(false)
const formError = ref('')
const deleteTarget = ref<{ kbId: string; slug: string; title: string } | null>(null)
const deleting = ref(false)
const deleteError = ref('')
const wikiError = ref('')
const sourceError = ref('')
const sourceLoading = ref('')
const loading = ref(false)
const graphReady = ref(false)
const graphCanvas = ref<HTMLElement | null>(null)
const selectedSlug = ref('')
const drawerVisible = ref(false)
const drawerPage = ref<any>(null)
const showArrows = ref(true)
const graphMode = ref<'overview' | 'ego'>('overview')
const graphCenter = ref('')
const searchText = ref('')
const searchOptions = ref<any[]>([])
const searchLoading = ref(false)
const pageSearch = ref('')
const activeTypes = ref(new Set(['summary', 'entity', 'concept', 'page']))
const readerContent = ref<HTMLElement | null>(null)
const readerOutline = ref<Array<{ id: string; level: number; label: string }>>([])
const headingPrefix = `wiki-heading-${Math.random().toString(36).slice(2)}`
let closed = false
let scopeGeneration = 0
let pagesRequest = 0
let graphRequest = 0
let drawerRequest = 0
let searchRequest = 0
let mutationRequest = 0
let sourceRequest = 0

type WikiSource = { documentId: string; title: string; chunkId?: string }
const validIdentifier = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(value)
const record = (value: unknown): Record<string, any> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, any> : {}
const scopeCurrent = (requestedKb: string, generation: number) => !closed && kbId.value === requestedKb && generation === scopeGeneration

function requestError(error: any, action: string) {
  const status = Number(error?.response?.status ?? error?.status)
  if (status === 401 || status === 403) return `无权${action}，请检查当前账号和空间`
  if (status === 404) return '页面或来源不存在或已删除'
  if (status === 409) return '页面已变化，请刷新后再编辑；当前草稿已保留'
  return `${action}失败，请稍后重试`
}

const typeMeta: Record<string, { label: string; color: string }> = {
  summary: { label: '摘要', color: '#0052d9' },
  entity: { label: '实体', color: '#2ba471' },
  concept: { label: '概念', color: '#e37318' },
  page: { label: '页面', color: '#8c8c8c' },
}

let svgEl: SVGSVGElement | null = null
let rootEl: SVGGElement | null = null
let animationId = 0
let nodeEls: { g: SVGGElement; circle: SVGCircleElement; ring: SVGCircleElement; text: SVGTextElement; node: GraphNode }[] = []
let edgeEls: { line: SVGLineElement; source: string; target: string; bidir: boolean }[] = []
let adjacency = new Map<string, Set<string>>()
let scale = 1
let translateX = 0
let translateY = 0

const visibleTypes = computed(() => Array.from(activeTypes.value).filter(Boolean))
const legendItems = computed(() => Object.entries(typeMeta).filter(([type]) => type !== 'page').map(([type, item]) => ({ type, ...item })))
const renderedDrawerContent = computed(() => renderMarkdownLite(drawerPage.value?.content || '暂无内容', { wikiLinks: true }))
const selectedPage = computed(() => pages.value.find((page) => page.slug === selectedSlug.value) || pages.value[0] || null)
const filteredPages = computed(() => {
  const keyword = pageSearch.value.trim().toLowerCase()
  if (!keyword) return pages.value
  return pages.value.filter((page) => [page.title, page.summary, page.content, page.slug].some((value) => String(value || '').toLowerCase().includes(keyword)))
})
const renderedSelectedPageContent = computed(() => renderMarkdownLite(selectedPage.value?.content || selectedPage.value?.summary || '暂无内容', { wikiLinks: true }))
const graphStatus = computed(() => {
  const meta = graph.value.meta || {}
  if (!graph.value.nodes.length) return '暂无可展示节点'
  if (meta.mode === 'ego') return `${meta.returned || graph.value.nodes.length} / ${meta.total || graph.value.nodes.length} 个节点`
  return `${meta.returned || graph.value.nodes.length} / ${meta.total || graph.value.nodes.length} 个节点`
})

function colorFor(type: string) {
  return typeMeta[type]?.color || '#8c8c8c'
}

function typeLabel(type: string) {
  return typeMeta[type]?.label || type || '页面'
}

function nodeRadius(node: GraphNode) {
  return Math.max(9, Math.min(26, 9 + Math.log((node.link_count || 0) + 1) * 4.2))
}

function graphTypesParam() {
  const all = Object.keys(typeMeta)
  if (all.every((item) => activeTypes.value.has(item))) return undefined
  return visibleTypes.value.join(',')
}

async function loadPages() {
  const requestedKb = kbId.value, generation = scopeGeneration, request = ++pagesRequest
  if (!requestedKb) return false
  try {
    const res: any = await api.wikiPages(requestedKb)
    if (!scopeCurrent(requestedKb, generation) || request !== pagesRequest) return false
    pages.value = (Array.isArray(res.data?.items) ? res.data.items : []).filter((page: any) => page.knowledge_base_id === requestedKb)
    if (!pages.value.some(page => page.slug === selectedSlug.value)) selectedSlug.value = pages.value[0]?.slug || ''
    return true
  } catch (error: any) {
    if (scopeCurrent(requestedKb, generation) && request === pagesRequest) wikiError.value = requestError(error, '读取 Wiki')
    return false
  }
}

async function refreshWiki() {
  wikiError.value = ''
  if (!await loadPages()) return
  if (tab.value === 'graph' && !await loadGraph(graphMode.value, graphCenter.value)) return
  MessagePlugin.success('Wiki 已刷新')
}

async function navigateWikiLink(event: MouseEvent) {
  const link = (event.target as HTMLElement).closest<HTMLAnchorElement>('a[data-wiki-slug]')
  if (!link) return
  event.preventDefault()
  const slug = link.dataset.wikiSlug || ''
  if (!pages.value.some((page) => page.slug === slug)) {
    MessagePlugin.warning('Wiki 页面不存在')
    return
  }
  if (tab.value === 'graph') await openDrawer(slug)
  else selectedSlug.value = slug
}

async function loadGraph(mode: 'overview' | 'ego' = 'overview', center = '') {
  const requestedKb = kbId.value, generation = scopeGeneration, request = ++graphRequest
  loading.value = true
  graphReady.value = false
  graphMode.value = mode
  graphCenter.value = center
  try {
    if (!requestedKb) return false
    const params: any = { mode, limit: 500 }
    if (mode === 'ego') params.center = center
    if (graphTypesParam()) params.types = graphTypesParam()
    const res: any = await api.wikiGraph(requestedKb, params)
    if (!scopeCurrent(requestedKb, generation) || request !== graphRequest) return false
    graph.value = res.data || { nodes: [], edges: [], meta: {} }
    await nextTick()
    if (!scopeCurrent(requestedKb, generation) || request !== graphRequest) return false
    renderGraph()
    return true
  } catch (error: any) {
    if (scopeCurrent(requestedKb, generation) && request === graphRequest) wikiError.value = requestError(error, '读取 Wiki 图谱')
    return false
  } finally {
    if (scopeCurrent(requestedKb, generation) && request === graphRequest) loading.value = false
  }
}

function openCreatePage() {
  if (props.embedded || closed || !kbId.value) return
  editingPage.value = null
  formKbId.value = kbId.value
  form.value = { title: '', content: '' }
  formError.value = ''
  visible.value = true
}

function editPage(page: any) {
  if (props.embedded || closed || !page || page.knowledge_base_id !== kbId.value || !Number.isSafeInteger(page.version)) return
  editingPage.value = { kbId: kbId.value, slug: page.slug, version: page.version }
  formKbId.value = kbId.value
  form.value = { title: page.title || '', content: page.content || '' }
  formError.value = ''
  visible.value = true
}

function closeEditor() {
  if (saving.value) return
  visible.value = false
}

async function create() {
  if (props.embedded || saving.value || closed || formKbId.value !== kbId.value) return
  if (!form.value.title.trim()) {
    MessagePlugin.warning('请输入标题')
    return
  }
  const requestedKb = kbId.value, generation = scopeGeneration, request = ++mutationRequest, editing = editingPage.value
  const current = () => scopeCurrent(requestedKb, generation) && request === mutationRequest
  saving.value = true
  formError.value = ''
  wikiError.value = ''
  try {
    const res: any = editing
      ? await api.updateWikiPage(requestedKb, editing.slug, { ...form.value, version: editing.version })
      : await api.createWikiPage(requestedKb, { ...form.value })
    if (!current()) return
    visible.value = false
    editingPage.value = null
    form.value = { title: '', content: '' }
    selectedSlug.value = String(res.data?.slug || editing?.slug || '')
    MessagePlugin.success('Wiki 页面已保存')
    if (!await loadPages()) {
      if (current()) wikiError.value = '页面已保存，刷新失败，请重新刷新 Wiki'
      return
    }
    if (!current()) return
    if (drawerVisible.value && drawerPage.value?.slug === selectedSlug.value) await openDrawer(selectedSlug.value)
    if (current()) await loadGraph(graphMode.value, graphCenter.value)
  } catch (error: any) {
    if (current()) formError.value = requestError(error, '保存 Wiki 页面')
  } finally {
    if (current()) saving.value = false
  }
}

function requestDelete(page: any) {
  if (props.embedded || closed || !page || page.knowledge_base_id !== kbId.value) return
  deleteTarget.value = { kbId: kbId.value, slug: page.slug, title: page.title }
  deleteError.value = ''
}

function cancelDelete() {
  if (!deleting.value) deleteTarget.value = null
}

async function confirmDeletePage() {
  const target = deleteTarget.value
  if (props.embedded || deleting.value || closed || !target || target.kbId !== kbId.value) return
  const generation = scopeGeneration, request = ++mutationRequest
  const current = () => scopeCurrent(target.kbId, generation) && request === mutationRequest
  deleting.value = true
  deleteError.value = ''
  wikiError.value = ''
  try {
    await api.deleteWikiPage(target.kbId, target.slug)
    if (!current()) return
    deleteTarget.value = null
    pages.value = pages.value.filter(page => page.slug !== target.slug)
    if (selectedSlug.value === target.slug) selectedSlug.value = pages.value[0]?.slug || ''
    if (drawerPage.value?.slug === target.slug) { drawerVisible.value = false; drawerPage.value = null }
    graph.value = { ...graph.value, nodes: graph.value.nodes.filter(node => node.slug !== target.slug), edges: graph.value.edges.filter(edge => edge.source !== target.slug && edge.target !== target.slug) }
    MessagePlugin.success('Wiki 页面已删除')
    if (!await loadPages()) {
      if (current()) wikiError.value = '页面已删除，刷新失败，请重新刷新 Wiki'
      return
    }
    if (current()) await loadGraph(graphCenter.value === target.slug ? 'overview' : graphMode.value, graphCenter.value === target.slug ? '' : graphCenter.value)
  } catch (error: any) {
    if (current()) deleteError.value = requestError(error, '删除 Wiki 页面')
  } finally {
    if (current()) deleting.value = false
  }
}

async function searchWiki(keyword: string) {
  const requestedKb = kbId.value, generation = scopeGeneration, request = ++searchRequest
  searchText.value = keyword
  const q = keyword.trim()
  if (!q) {
    searchLoading.value = false
    searchOptions.value = graph.value.nodes.map((node) => ({ label: node.title || node.label || node.slug, value: node.slug }))
    return
  }
  searchLoading.value = true
  try {
    const res: any = await api.wikiSearch(requestedKb, { q, limit: 20 })
    if (!scopeCurrent(requestedKb, generation) || request !== searchRequest) return
    const items = res.data?.pages || res.data?.items || []
    searchOptions.value = items.map((item: any) => ({ label: item.title, value: item.slug }))
  } catch (error: any) {
    if (scopeCurrent(requestedKb, generation) && request === searchRequest) wikiError.value = requestError(error, '搜索 Wiki')
  } finally {
    if (scopeCurrent(requestedKb, generation) && request === searchRequest) searchLoading.value = false
  }
}

async function selectSearch(value: string) {
  if (!value) return
  const requestedKb = kbId.value, generation = scopeGeneration
  let node = graph.value.nodes.find((item) => item.slug === value)
  if (!node) {
    await loadGraph('ego', value)
    if (!scopeCurrent(requestedKb, generation)) return
    node = graph.value.nodes.find((item) => item.slug === value)
  }
  if (node) {
    selectedSlug.value = value
    focusNode(node)
    applyHighlight(value)
  }
  await openDrawer(value)
  setTimeout(() => { if (scopeCurrent(requestedKb, generation)) searchText.value = '' }, 200)
}

async function openDrawer(slug: string) {
  const requestedKb = kbId.value, generation = scopeGeneration, request = ++drawerRequest
  selectedSlug.value = slug
  drawerVisible.value = true
  const local = pages.value.find((page) => page.slug === slug)
  drawerPage.value = local || { title: slug, content: '' }
  try {
    const res: any = await api.getWikiPage(requestedKb, slug)
    if (!scopeCurrent(requestedKb, generation) || request !== drawerRequest) return
    if (res.data?.knowledge_base_id === requestedKb && res.data?.slug === slug) drawerPage.value = res.data
  } catch (error: any) {
    if (!scopeCurrent(requestedKb, generation) || request !== drawerRequest) return
    if ([401, 403, 404].includes(Number(error?.response?.status ?? error?.status))) drawerPage.value = null
    wikiError.value = requestError(error, '读取 Wiki 页面')
  }
}

function sourcesFor(page: any): WikiSource[] {
  if (!page || page.knowledge_base_id !== kbId.value || !Array.isArray(page.source_refs)) return []
  const contributions = record(record(page.metadata ?? page.page_metadata).contributions), seen = new Set<string>()
  const sources: WikiSource[] = []
  for (const value of page.source_refs) {
    const ref = record(value), documentId = typeof value === 'string' ? value : ref.knowledge_id ?? ref.id
    if (!validIdentifier(documentId) || seen.has(documentId)) continue
    seen.add(documentId)
    const candidate = ref.chunk_id ?? (Array.isArray(contributions[documentId]?.chunks) ? contributions[documentId].chunks[0] : undefined)
    sources.push({ documentId, title: String(ref.title ?? ref.knowledge_title ?? '来源文档'), ...(validIdentifier(candidate) ? { chunkId: candidate } : {}) })
  }
  return sources
}

async function openSource(page: any, source: WikiSource) {
  const requestedKb = kbId.value, generation = scopeGeneration, request = ++sourceRequest, view = tab.value
  if (!validIdentifier(requestedKb) || !sourcesFor(page).some(item => item.documentId === source.documentId && item.chunkId === source.chunkId)) return
  const current = () => scopeCurrent(requestedKb, generation) && request === sourceRequest && view === tab.value
    && (view === 'graph' ? drawerVisible.value && drawerPage.value?.slug === page.slug : selectedPage.value?.slug === page.slug)
  sourceLoading.value = source.documentId
  sourceError.value = ''
  try {
    const res: any = await api.getKnowledge(source.documentId)
    if (!current()) return
    if (res.data?.id !== source.documentId || res.data?.knowledge_base_id !== requestedKb) {
      sourceError.value = '来源文档与当前知识库不匹配'
      return
    }
    if (source.chunkId) {
      const chunkRes: any = await api.getChunk(source.documentId, source.chunkId)
      if (!current()) return
      if (chunkRes.data?.id !== source.chunkId || chunkRes.data?.knowledge_id !== source.documentId || chunkRes.data?.knowledge_base_id !== requestedKb) {
        sourceError.value = '来源分块与文档或当前知识库不匹配'
        return
      }
    }
    await router.push({ path: `/platform/knowledge-bases/${encodeURIComponent(requestedKb)}`, query: { document: source.documentId, ...(source.chunkId ? { chunk: source.chunkId } : {}) } })
  } catch (error: any) {
    if (current()) sourceError.value = requestError(error, '查看来源')
  } finally {
    if (request === sourceRequest) sourceLoading.value = ''
  }
}

function updateReaderOutline() {
  const headings = Array.from(readerContent.value?.querySelectorAll<HTMLElement>('h2,h3,h4') || []).slice(0, 12)
  readerOutline.value = headings.map((heading, index) => {
    heading.id = `${headingPrefix}-${index}`
    heading.tabIndex = -1
    return { id: heading.id, level: Number(heading.tagName.slice(1)) - 1, label: heading.textContent?.trim() || '' }
  })
}

function focusHeading(id: string) {
  const heading = Array.from(readerContent.value?.querySelectorAll<HTMLElement>('h2,h3,h4') || []).find(node => node.id === id)
  heading?.scrollIntoView({ block: 'start' })
  heading?.focus({ preventScroll: true })
}

function toggleType(type: string) {
  const next = new Set(activeTypes.value)
  next.has(type) ? next.delete(type) : next.add(type)
  activeTypes.value = next
  if (!next.size) {
    ++graphRequest
    loading.value = false
    graph.value = { nodes: [], edges: [], meta: { mode: graphMode.value, total: 0, returned: 0, truncated: false } }
    renderGraph()
    return
  }
  loadGraph(graphMode.value, graphCenter.value)
}

async function selectType(value: string | number) {
  activeTypes.value = new Set(value ? [String(value)] : Object.keys(typeMeta))
  await loadGraph(graphMode.value, graphCenter.value)
}

function toggleArrows() {
  showArrows.value = !showArrows.value
  for (const edge of edgeEls) {
    if (showArrows.value) {
      edge.line.setAttribute('marker-end', 'url(#arrow-end)')
      if (edge.bidir) edge.line.setAttribute('marker-start', 'url(#arrow-start)')
    } else {
      edge.line.removeAttribute('marker-end')
      edge.line.removeAttribute('marker-start')
    }
  }
}

function fitGraphToView() {
  if (!rootEl || !graphCanvas.value || !graph.value.nodes.length) return
  const width = graphCanvas.value.clientWidth || 900
  const height = graphCanvas.value.clientHeight || 600
  const xs = graph.value.nodes.map((node) => node.x || 0)
  const ys = graph.value.nodes.map((node) => node.y || 0)
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys)
  const graphW = Math.max(maxX - minX, 1)
  const graphH = Math.max(maxY - minY, 1)
  scale = Math.max(0.25, Math.min(2.2, Math.min((width - 120) / graphW, (height - 120) / graphH)))
  translateX = width / 2 - ((minX + maxX) / 2) * scale
  translateY = height / 2 - ((minY + maxY) / 2) * scale
  applyTransform()
}

function focusNode(node: GraphNode) {
  if (!graphCanvas.value) return
  const width = graphCanvas.value.clientWidth || 900
  const height = graphCanvas.value.clientHeight || 600
  translateX = width / 2 - (node.x || 0) * scale - (drawerVisible.value ? 180 : 0)
  translateY = height / 2 - (node.y || 0) * scale
  applyTransform()
}

function applyTransform() {
  rootEl?.setAttribute('transform', `translate(${translateX},${translateY}) scale(${scale})`)
}

function applyHighlight(slug: string) {
  const neighbors = adjacency.get(slug) || new Set()
  for (const item of nodeEls) {
    const active = item.node.slug === slug
    const near = neighbors.has(item.node.slug)
    item.g.style.opacity = active || near ? '1' : '0.22'
    item.ring.style.opacity = active ? '1' : '0'
    item.circle.setAttribute('stroke-width', active ? '3' : '2')
  }
  for (const edge of edgeEls) {
    const hit = edge.source === slug || edge.target === slug
    edge.line.setAttribute('stroke-opacity', hit ? '0.88' : '0.1')
    edge.line.setAttribute('stroke-width', hit ? '2' : '1.1')
    edge.line.setAttribute('stroke', hit ? colorFor(graph.value.nodes.find((node) => node.slug === slug)?.page_type || '') : '#c9ced8')
  }
}

function clearHighlight() {
  if (selectedSlug.value) {
    applyHighlight(selectedSlug.value)
    return
  }
  for (const item of nodeEls) {
    item.g.style.opacity = '1'
    item.ring.style.opacity = '0'
    item.circle.setAttribute('stroke-width', '2')
  }
  for (const edge of edgeEls) {
    edge.line.setAttribute('stroke', '#c9ced8')
    edge.line.setAttribute('stroke-opacity', '0.38')
    edge.line.setAttribute('stroke-width', '1.2')
  }
}

function renderGraph() {
  if (animationId) cancelAnimationFrame(animationId)
  const container = graphCanvas.value
  if (!container) return
  container.innerHTML = ''
  graphReady.value = false
  if (!graph.value.nodes.length) return
  const width = container.clientWidth || 1000
  const height = container.clientHeight || 680
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`)
  svg.style.width = '100%'
  svg.style.height = '100%'
  container.appendChild(svg)
  svgEl = svg
  rootEl = document.createElementNS('http://www.w3.org/2000/svg', 'g')
  rootEl.setAttribute('class', 'wiki-svg-root')
  svg.appendChild(rootEl)

  const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs')
  defs.innerHTML = `
    <marker id="arrow-end" viewBox="0 0 10 6" refX="10" refY="3" markerWidth="8" markerHeight="6" orient="auto"><path d="M0,0 L10,3 L0,6 L2,3 Z" fill="#c9ced8"/></marker>
    <marker id="arrow-start" viewBox="0 0 10 6" refX="0" refY="3" markerWidth="8" markerHeight="6" orient="auto"><path d="M10,0 L0,3 L10,6 L8,3 Z" fill="#c9ced8"/></marker>
  `
  svg.appendChild(defs)

  const edgeLayer = document.createElementNS('http://www.w3.org/2000/svg', 'g')
  const nodeLayer = document.createElementNS('http://www.w3.org/2000/svg', 'g')
  rootEl.appendChild(edgeLayer)
  rootEl.appendChild(nodeLayer)

  adjacency = new Map()
  for (const edge of graph.value.edges) {
    adjacency.set(edge.source, adjacency.get(edge.source) || new Set())
    adjacency.set(edge.target, adjacency.get(edge.target) || new Set())
    adjacency.get(edge.source)!.add(edge.target)
    adjacency.get(edge.target)!.add(edge.source)
  }

  const previous = new Map(graph.value.nodes.filter((node) => typeof node.x === 'number').map((node) => [node.slug, node]))
  graph.value.nodes = graph.value.nodes.map((node, index) => {
    const old = previous.get(node.slug)
    if (old) return { ...node, x: old.x, y: old.y, vx: old.vx || 0, vy: old.vy || 0, pinned: old.pinned || false }
    const angle = (Math.PI * 2 * index) / graph.value.nodes.length
    const radius = Math.min(width, height) * 0.34
    return { ...node, x: width / 2 + Math.cos(angle) * radius + (Math.random() - 0.5) * 70, y: height / 2 + Math.sin(angle) * radius + (Math.random() - 0.5) * 70, vx: 0, vy: 0, pinned: false }
  })

  const nodeMap = new Map(graph.value.nodes.map((node) => [node.slug, node]))
  const edgePairs = new Set(graph.value.edges.map((edge) => `${edge.source}->${edge.target}`))
  const processed = new Set<string>()
  edgeEls = []
  for (const edge of graph.value.edges) {
    const key = [edge.source, edge.target].sort().join('<>')
    if (processed.has(key)) continue
    processed.add(key)
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line')
    const bidir = edgePairs.has(`${edge.target}->${edge.source}`)
    line.setAttribute('stroke', '#c9ced8')
    line.setAttribute('stroke-width', '1.2')
    line.setAttribute('stroke-opacity', '0.38')
    if (showArrows.value) line.setAttribute('marker-end', 'url(#arrow-end)')
    if (showArrows.value && bidir) line.setAttribute('marker-start', 'url(#arrow-start)')
    edgeLayer.appendChild(line)
    edgeEls.push({ line, source: edge.source, target: edge.target, bidir })
  }

  nodeEls = []
  for (const node of graph.value.nodes) {
    const g = document.createElementNS('http://www.w3.org/2000/svg', 'g')
    g.style.cursor = 'pointer'
    const r = nodeRadius(node)
    const hidden = Math.max(0, (node.link_count || 0) - (adjacency.get(node.slug)?.size || 0))
    const expansion = document.createElementNS('http://www.w3.org/2000/svg', 'circle')
    expansion.setAttribute('r', String(r + 4))
    expansion.setAttribute('fill', 'none')
    expansion.setAttribute('stroke', colorFor(node.page_type))
    expansion.setAttribute('stroke-width', '1.5')
    expansion.setAttribute('stroke-dasharray', '3 3')
    expansion.style.opacity = hidden > 0 ? '0.55' : '0'
    g.appendChild(expansion)

    const ring = document.createElementNS('http://www.w3.org/2000/svg', 'circle')
    ring.setAttribute('r', String(r + 7))
    ring.setAttribute('fill', 'none')
    ring.setAttribute('stroke', colorFor(node.page_type))
    ring.setAttribute('stroke-width', '2')
    ring.style.opacity = '0'
    g.appendChild(ring)

    const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle')
    circle.setAttribute('r', String(r))
    circle.setAttribute('fill', colorFor(node.page_type))
    circle.setAttribute('stroke', '#fff')
    circle.setAttribute('stroke-width', '2')
    g.appendChild(circle)

    const text = document.createElementNS('http://www.w3.org/2000/svg', 'text')
    text.setAttribute('text-anchor', 'middle')
    text.setAttribute('dy', String(r + 15))
    text.setAttribute('font-size', '11')
    text.setAttribute('fill', '#4b5565')
    text.setAttribute('pointer-events', 'none')
    text.textContent = (node.title || node.label || node.slug).length > 14 ? `${(node.title || node.label || node.slug).slice(0, 14)}…` : (node.title || node.label || node.slug)
    g.appendChild(text)

    g.addEventListener('mouseenter', () => { if (!selectedSlug.value) applyHighlight(node.slug) })
    g.addEventListener('mouseleave', () => { if (!selectedSlug.value) clearHighlight() })
    g.addEventListener('click', (event) => {
      event.stopPropagation()
      selectedSlug.value = node.slug
      applyHighlight(node.slug)
      focusNode(node)
      openDrawer(node.slug)
    })
    g.addEventListener('dblclick', (event) => {
      event.stopPropagation()
      loadGraph('ego', node.slug)
    })
    setupNodeDrag(g, node, nodeMap)
    nodeLayer.appendChild(g)
    nodeEls.push({ g, circle, ring, text, node })
  }

  setupPanZoom(svg)
  runSimulation(nodeMap)
  graphReady.value = true
  setTimeout(fitGraphToView, 260)
}

function updatePositions(nodeMap: Map<string, GraphNode>) {
  for (const item of nodeEls) item.g.setAttribute('transform', `translate(${item.node.x},${item.node.y})`)
  for (const edge of edgeEls) {
    const source = nodeMap.get(edge.source)
    const target = nodeMap.get(edge.target)
    if (!source || !target) continue
    const dx = (target.x || 0) - (source.x || 0)
    const dy = (target.y || 0) - (source.y || 0)
    const dist = Math.sqrt(dx * dx + dy * dy) || 1
    const ux = dx / dist
    const uy = dy / dist
    const rs = nodeRadius(source) + 4
    const rt = nodeRadius(target) + 4
    edge.line.setAttribute('x1', String((source.x || 0) + ux * rs))
    edge.line.setAttribute('y1', String((source.y || 0) + uy * rs))
    edge.line.setAttribute('x2', String((target.x || 0) - ux * rt))
    edge.line.setAttribute('y2', String((target.y || 0) - uy * rt))
  }
}

function runSimulation(nodeMap: Map<string, GraphNode>) {
  let alpha = 1
  const tick = () => {
    alpha *= 0.985
    if (alpha < 0.025) {
      animationId = 0
      return
    }
    const nodes = graph.value.nodes
    for (let i = 0; i < nodes.length; i += 1) {
      const a = nodes[i]
      for (let j = i + 1; j < nodes.length; j += 1) {
        const b = nodes[j]
        const dx = (b.x || 0) - (a.x || 0)
        const dy = (b.y || 0) - (a.y || 0)
        const d2 = Math.max(dx * dx + dy * dy, 120)
        if (d2 > 90000) continue
        const d = Math.sqrt(d2)
        const force = (190 * alpha) / d2 * 70
        if (!a.pinned) { a.vx = (a.vx || 0) - (dx / d) * force; a.vy = (a.vy || 0) - (dy / d) * force }
        if (!b.pinned) { b.vx = (b.vx || 0) + (dx / d) * force; b.vy = (b.vy || 0) + (dy / d) * force }
      }
    }
    for (const edge of graph.value.edges) {
      const source = nodeMap.get(edge.source)
      const target = nodeMap.get(edge.target)
      if (!source || !target) continue
      const dx = (target.x || 0) - (source.x || 0)
      const dy = (target.y || 0) - (source.y || 0)
      const d = Math.sqrt(dx * dx + dy * dy) || 1
      const force = (d - 116) * 0.005 * alpha
      if (!source.pinned) { source.vx = (source.vx || 0) + (dx / d) * force; source.vy = (source.vy || 0) + (dy / d) * force }
      if (!target.pinned) { target.vx = (target.vx || 0) - (dx / d) * force; target.vy = (target.vy || 0) - (dy / d) * force }
    }
    const width = graphCanvas.value?.clientWidth || 1000
    const height = graphCanvas.value?.clientHeight || 680
    for (const node of nodes) {
      if (node.pinned) continue
      node.vx = ((node.vx || 0) + (width / 2 - (node.x || 0)) * 0.002 * alpha) * 0.62
      node.vy = ((node.vy || 0) + (height / 2 - (node.y || 0)) * 0.002 * alpha) * 0.62
      node.x = (node.x || 0) + node.vx
      node.y = (node.y || 0) + node.vy
    }
    updatePositions(nodeMap)
    animationId = requestAnimationFrame(tick)
  }
  updatePositions(nodeMap)
  animationId = requestAnimationFrame(tick)
}

function setupNodeDrag(g: SVGGElement, node: GraphNode, nodeMap: Map<string, GraphNode>) {
  let dragging = false
  let startX = 0
  let startY = 0
  const point = (event: MouseEvent) => {
    if (!svgEl || !rootEl) return { x: event.clientX, y: event.clientY }
    const pt = svgEl.createSVGPoint()
    pt.x = event.clientX
    pt.y = event.clientY
    const ctm = rootEl.getCTM()?.inverse()
    return ctm ? pt.matrixTransform(ctm) : { x: event.clientX, y: event.clientY }
  }
  const move = (event: MouseEvent) => {
    if (!dragging) return
    const p = point(event)
    node.x = p.x - startX
    node.y = p.y - startY
    node.vx = 0
    node.vy = 0
    updatePositions(nodeMap)
  }
  const up = () => {
    dragging = false
    window.removeEventListener('mousemove', move)
    window.removeEventListener('mouseup', up)
  }
  g.addEventListener('mousedown', (event) => {
    if (event.button !== 0) return
    event.stopPropagation()
    dragging = true
    node.pinned = true
    const p = point(event)
    startX = p.x - (node.x || 0)
    startY = p.y - (node.y || 0)
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
  })
}

// 每次重渲染都会重建 SVG 并重挂监听，必须持有引用统一拆除，否则向 window 无限累积
let panWindowHandlers: { move: (event: MouseEvent) => void; up: () => void } | null = null

function teardownPanZoom() {
  if (!panWindowHandlers) return
  window.removeEventListener('mousemove', panWindowHandlers.move)
  window.removeEventListener('mouseup', panWindowHandlers.up)
  panWindowHandlers = null
}

function setupPanZoom(svg: SVGSVGElement) {
  let panning = false
  let sx = 0
  let sy = 0
  svg.addEventListener('wheel', (event) => {
    event.preventDefault()
    const next = Math.max(0.22, Math.min(5, scale * (event.deltaY > 0 ? 0.92 : 1.08)))
    const rect = svg.getBoundingClientRect()
    const cx = event.clientX - rect.left
    const cy = event.clientY - rect.top
    translateX = cx - (cx - translateX) * (next / scale)
    translateY = cy - (cy - translateY) * (next / scale)
    scale = next
    applyTransform()
  }, { passive: false })
  svg.addEventListener('mousedown', (event) => {
    if (event.button !== 0 || event.target !== svg) return
    panning = true
    sx = event.clientX - translateX
    sy = event.clientY - translateY
    selectedSlug.value = ''
    drawerVisible.value = false
    clearHighlight()
  })
  const move = (event: MouseEvent) => {
    if (!panning) return
    translateX = event.clientX - sx
    translateY = event.clientY - sy
    applyTransform()
  }
  const up = () => { panning = false }
  teardownPanZoom()
  panWindowHandlers = { move, up }
  window.addEventListener('mousemove', move)
  window.addEventListener('mouseup', up)
}

watch(() => props.view, (value) => {
  if (value && value !== tab.value) tab.value = value
})

watch(() => route.query.tab, (value) => {
  if (props.embedded) return
  tab.value = String(value || 'graph')
})

watch(tab, (value) => {
  if (!props.embedded) router.replace({ query: { ...route.query, tab: value } })
  if (value === 'graph') nextTick(() => loadGraph())
})

watch([tab, renderedSelectedPageContent], async () => {
  await nextTick()
  if (!closed) updateReaderOutline()
}, { flush: 'post' })

watch(kbId, async (value, oldValue) => {
  if (!value || value === oldValue) return
  ++scopeGeneration
  ++mutationRequest
  ++sourceRequest
  pages.value = []
  graph.value = { nodes: [], edges: [], meta: {} }
  selectedSlug.value = ''
  drawerVisible.value = false
  drawerPage.value = null
  visible.value = false
  editingPage.value = null
  formKbId.value = ''
  form.value = { title: '', content: '' }
  deleteTarget.value = null
  saving.value = false
  deleting.value = false
  sourceLoading.value = ''
  formError.value = ''
  deleteError.value = ''
  wikiError.value = ''
  sourceError.value = ''
  pageSearch.value = ''
  searchText.value = ''
  searchOptions.value = []
  searchLoading.value = false
  activeTypes.value = new Set(['summary', 'entity', 'concept', 'page'])
  graphMode.value = 'overview'
  graphCenter.value = ''
  loading.value = false
  teardownPanZoom()
  renderGraph()
  if (await loadPages()) await loadGraph()
})

onMounted(async () => {
  if (await loadPages()) await loadGraph()
})

onUnmounted(() => {
  closed = true
  ++scopeGeneration
  ++mutationRequest
  ++sourceRequest
  if (animationId) cancelAnimationFrame(animationId)
  teardownPanZoom()
})
</script>

<template>
  <main class="wiki-graph-page" :class="[{ embedded }, `view-${tab}`]">
    <p v-if="wikiError" role="alert" class="wiki-error">{{ wikiError }}</p>
    <p v-if="sourceError" role="alert" class="wiki-error">{{ sourceError }}</p>
    <header v-if="!embedded" class="wiki-graph-header">
      <div>
        <div class="wiki-breadcrumb">知识库 / {{ kbName || '文档' }} / Wiki / <strong>图谱</strong></div>
        <p>支持拖拽、缩放、搜索和邻域展开，快速浏览结构化 Wiki 关系。</p>
      </div>
      <div class="wiki-header-actions">
        <t-radio-group v-model="tab" variant="default-filled" size="small">
          <t-radio-button value="graph">图谱</t-radio-button>
          <t-radio-button value="pages">页面</t-radio-button>
        </t-radio-group>
        <t-button size="small" theme="primary" :disabled="saving || deleting" @click="openCreatePage">新建页面</t-button>
      </div>
    </header>

    <section v-if="tab === 'graph'" class="wiki-graph-stage">
      <div class="wiki-graph-search-panel wiki-graph-toolbar">
        <t-select
          v-model="searchText"
          filterable
          clearable
          :options="searchOptions"
          :loading="searchLoading"
          placeholder="搜索 Wiki 页面..."
          @search="searchWiki"
          @change="selectSearch"
        />
        <t-select class="wiki-type-select" :value="activeTypes.size === 1 ? visibleTypes[0] : undefined" placeholder="节点类型" clearable @change="selectType">
          <t-option v-for="item in legendItems" :key="item.type" :value="item.type" :label="item.label" />
        </t-select>
        <button type="button" @click="toggleArrows">{{ showArrows ? '隐藏箭头' : '显示箭头' }}</button>
        <button type="button" @click="fitGraphToView">适应屏幕</button>
      </div>

      <div ref="graphCanvas" class="wiki-graph-canvas"></div>

      <div v-if="loading" class="wiki-graph-empty"><t-loading /> <span>加载图谱中...</span></div>
      <div v-else-if="!graph.nodes.length" class="wiki-graph-empty">
        <strong>暂无图谱关系</strong>
        <span>创建 Wiki 页面并建立链接后会显示关系图。</span>
      </div>

      <aside class="wiki-graph-legend" :class="{ shifted: drawerVisible }">
        <div class="legend-items">
          <button v-for="item in legendItems" :key="item.type" :class="{ disabled: !activeTypes.has(item.type) }" @click="toggleType(item.type)">
            <i :style="{ background: item.color }"></i>
            <span>{{ item.label }}</span>
          </button>
        </div>
        <div class="legend-divider"></div>
        <button @click="fitGraphToView">适应屏幕</button>
        <button @click="toggleArrows">{{ showArrows ? '隐藏箭头' : '显示箭头' }}</button>
        <button v-if="graphMode === 'ego'" @click="loadGraph()">全库概览</button>
        <div class="legend-divider"></div>
        <div class="graph-status">
          <span>{{ graphStatus }}</span>
          <small v-if="graph.meta?.truncated">已展示知识库全部节点中的一部分</small>
        </div>
      </aside>

      <t-drawer v-model:visible="drawerVisible" :header="drawerPage?.title || 'Wiki 页面'" size="480px" :footer="false" placement="right" :show-overlay="false" :close-btn="true">
        <template #closeBtn><button type="button" class="wiki-close-button" aria-label="关闭 Wiki 页面详情">×</button></template>
        <div v-if="drawerPage" class="wiki-drawer-body">
          <div class="wiki-drawer-meta">
            <t-tag size="small" variant="light-outline">{{ typeLabel(drawerPage.page_type) }}</t-tag>
            <span>{{ drawerPage.slug }}</span>
          </div>
          <p class="wiki-drawer-summary">{{ drawerPage.summary || '暂无摘要' }}</p>
          <article class="wiki-drawer-content markdown-lite" @click="navigateWikiLink" v-html="renderedDrawerContent"></article>
          <div class="wiki-drawer-actions">
            <t-button size="small" variant="outline" @click="loadGraph('ego', drawerPage.slug)">展开邻域</t-button>
            <button v-if="!embedded" type="button" :disabled="saving || deleting" @click="editPage(drawerPage)">编辑页面</button>
            <button v-if="!embedded" type="button" :disabled="saving || deleting" @click="requestDelete(drawerPage)">删除页面</button>
          </div>
          <div v-if="sourcesFor(drawerPage).length" class="wiki-source-links" aria-label="来源文档">
            <button v-for="source in sourcesFor(drawerPage)" :key="source.documentId" type="button" :disabled="!!sourceLoading" @click="openSource(drawerPage, source)">查看来源：{{ source.title }}</button>
          </div>
        </div>
      </t-drawer>
    </section>

    <section v-else class="wiki-pages-panel">
      <aside v-if="pages.length" class="wiki-pages-list" aria-label="Wiki 页面索引">
        <div class="wiki-index-tools">
          <t-input v-model="pageSearch" class="wiki-index-search" clearable placeholder="搜索 Wiki 页面" />
          <div><span>页面目录</span><button type="button" @click="refreshWiki">刷新 Wiki</button></div>
        </div>
        <button
          v-for="p in filteredPages"
          :key="p.id"
          type="button"
          class="wiki-page-list-item"
          :class="{ active: selectedPage?.slug === p.slug }"
          @click="selectedSlug = p.slug"
        >
          <span class="paper-kicker">{{ typeLabel(p.page_type) }}</span>
          <strong>{{ p.title }}</strong>
          <small>{{ p.summary || p.content || '暂无摘要' }}</small>
        </button>
      </aside>
      <article v-if="selectedPage" class="wiki-page-reader">
        <div class="wiki-reader-meta">
          <t-tag size="small" variant="light-outline">{{ typeLabel(selectedPage.page_type) }}</t-tag>
          <span>{{ selectedPage.slug }}</span>
        </div>
        <h2>{{ selectedPage.title }}</h2>
        <div v-if="!embedded" class="wiki-reader-actions">
          <button type="button" :disabled="saving || deleting" @click="editPage(selectedPage)">编辑页面</button>
          <button type="button" :disabled="saving || deleting" @click="requestDelete(selectedPage)">删除页面</button>
        </div>
        <p class="wiki-reader-summary">{{ selectedPage.summary || '暂无摘要' }}</p>
        <div ref="readerContent" class="wiki-reader-content markdown-lite" @click="navigateWikiLink" v-html="renderedSelectedPageContent"></div>
        <div v-if="sourcesFor(selectedPage).length" class="wiki-source-links" aria-label="来源文档">
          <button v-for="source in sourcesFor(selectedPage)" :key="source.documentId" type="button" :disabled="!!sourceLoading" @click="openSource(selectedPage, source)">查看来源：{{ source.title }}</button>
        </div>
      </article>
      <aside v-if="selectedPage" class="wiki-reader-outline" aria-label="本页目录">
        <strong>本页目录</strong>
        <button v-for="heading in readerOutline" :key="heading.id" type="button" :style="{ paddingLeft: `${(heading.level - 1) * 10}px` }" @click="focusHeading(heading.id)">{{ heading.label }}</button>
        <span v-if="!readerOutline.length">正文概览</span>
      </aside>
      <div v-else class="empty-state">还没有 Wiki 页面</div>
    </section>

    <t-dialog :visible="visible && !embedded" :header="editingPage ? '编辑 Wiki 页面' : '新建 Wiki 页面'" confirm-btn="保存" :confirm-loading="saving" :close-btn="!saving" :close-on-esc-keydown="!saving" :close-on-overlay-click="!saving" width="620px" @close="closeEditor" @confirm="create">
      <t-space direction="vertical" class="form-stack">
        <t-input v-model="form.title" placeholder="标题" />
        <t-textarea v-model="form.content" :autosize="{ minRows: 8, maxRows: 12 }" placeholder="Markdown 内容" />
        <p v-if="formError" role="alert" class="wiki-error">{{ formError }}</p>
      </t-space>
    </t-dialog>
    <t-dialog :visible="!!deleteTarget && !embedded" header="删除 Wiki 页面" confirm-btn="确认删除" :cancel-btn="{ content: '取消', disabled: deleting }" :confirm-loading="deleting" :close-btn="!deleting" :close-on-esc-keydown="!deleting" :close-on-overlay-click="!deleting" theme="danger" @close="cancelDelete" @confirm="confirmDeletePage">
      <p>确定删除“{{ deleteTarget?.title }}”？页面链接和关系图会同步更新。</p>
      <p v-if="deleteError" role="alert" class="wiki-error">{{ deleteError }}</p>
    </t-dialog>
  </main>
</template>

<style scoped>
.wiki-reader-actions, .wiki-source-links { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }
.wiki-error { color: var(--danger, #b42318); }
.wiki-reader-outline button { border: 0; background: none; color: inherit; text-align: left; cursor: pointer; }
.wiki-close-button { width: 28px; height: 28px; display: grid; place-items: center; border: 0; background: transparent; color: inherit; font-size: 24px; cursor: pointer; }
</style>
