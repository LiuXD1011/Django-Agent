<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import { api } from '../api'

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
const activeTypes = ref(new Set(['summary', 'entity', 'concept', 'synthesis', 'comparison', 'page']))

const typeMeta: Record<string, { label: string; color: string }> = {
  summary: { label: '摘要', color: '#0052d9' },
  entity: { label: '实体', color: '#2ba471' },
  concept: { label: '概念', color: '#e37318' },
  synthesis: { label: '综合', color: '#0594fa' },
  comparison: { label: '对比', color: '#d54941' },
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
const legendItems = computed(() => Object.entries(typeMeta).map(([type, item]) => ({ type, ...item })))
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
  if (!kbId.value) return
  pages.value = ((await api.wikiPages(kbId.value) as any).data?.items || [])
}

async function loadGraph(mode: 'overview' | 'ego' = 'overview', center = '') {
  loading.value = true
  graphReady.value = false
  graphMode.value = mode
  graphCenter.value = center
  try {
    if (!kbId.value) return
    const params: any = { mode, limit: 500 }
    if (mode === 'ego') params.center = center
    if (graphTypesParam()) params.types = graphTypesParam()
    graph.value = (await api.wikiGraph(kbId.value, params) as any).data || { nodes: [], edges: [], meta: {} }
    await nextTick()
    renderGraph()
  } finally {
    loading.value = false
  }
}

async function create() {
  if (!form.value.title.trim()) {
    MessagePlugin.warning('请输入标题')
    return
  }
  await api.createWikiPage(kbId.value, form.value)
  visible.value = false
  form.value = { title: '', content: '' }
  await loadPages()
  await loadGraph()
}

async function searchWiki(keyword: string) {
  searchText.value = keyword
  const q = keyword.trim()
  if (!q) {
    searchOptions.value = graph.value.nodes.map((node) => ({ label: node.title || node.label || node.slug, value: node.slug }))
    return
  }
  searchLoading.value = true
  try {
    const res: any = await api.wikiSearch(kbId.value, { q, limit: 20 })
    const items = res.data?.pages || res.data?.items || []
    searchOptions.value = items.map((item: any) => ({ label: item.title, value: item.slug }))
  } finally {
    searchLoading.value = false
  }
}

async function selectSearch(value: string) {
  if (!value) return
  let node = graph.value.nodes.find((item) => item.slug === value)
  if (!node) {
    await loadGraph('ego', value)
    node = graph.value.nodes.find((item) => item.slug === value)
  }
  if (node) {
    selectedSlug.value = value
    focusNode(node)
    applyHighlight(value)
  }
  await openDrawer(value)
  setTimeout(() => { searchText.value = '' }, 200)
}

async function openDrawer(slug: string) {
  selectedSlug.value = slug
  drawerVisible.value = true
  const local = pages.value.find((page) => page.slug === slug)
  drawerPage.value = local || { title: slug, content: '' }
  try {
    const res: any = await api.getWikiPage(kbId.value, slug)
    drawerPage.value = res.data || drawerPage.value
  } catch {
    // Keep the local fallback visible.
  }
}

function toggleType(type: string) {
  const next = new Set(activeTypes.value)
  next.has(type) ? next.delete(type) : next.add(type)
  activeTypes.value = next
  if (!next.size) {
    graph.value = { nodes: [], edges: [], meta: { mode: graphMode.value, total: 0, returned: 0, truncated: false } }
    renderGraph()
    return
  }
  loadGraph(graphMode.value, graphCenter.value)
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
  window.addEventListener('mousemove', (event) => {
    if (!panning) return
    translateX = event.clientX - sx
    translateY = event.clientY - sy
    applyTransform()
  })
  window.addEventListener('mouseup', () => { panning = false })
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

watch(kbId, async (value, oldValue) => {
  if (!value || value === oldValue) return
  await loadPages()
  await loadGraph()
})

onMounted(async () => {
  await loadPages()
  await loadGraph()
})

onUnmounted(() => {
  if (animationId) cancelAnimationFrame(animationId)
})
</script>

<template>
  <main class="wiki-graph-page" :class="{ embedded }">
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
        <t-button size="small" theme="primary" @click="visible = true">新建页面</t-button>
      </div>
    </header>

    <section v-if="tab === 'graph'" class="wiki-graph-stage">
      <div class="wiki-graph-search-panel">
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
        <button class="wiki-help-dot" title="拖拽节点，滚轮缩放，双击展开邻域">?</button>
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

      <t-drawer v-model:visible="drawerVisible" :header="drawerPage?.title || 'Wiki 页面'" size="480px" :footer="false" placement="right" :show-overlay="false">
        <div v-if="drawerPage" class="wiki-drawer-body">
          <div class="wiki-drawer-meta">
            <t-tag size="small" variant="light-outline">{{ typeLabel(drawerPage.page_type) }}</t-tag>
            <span>{{ drawerPage.slug }}</span>
          </div>
          <p class="wiki-drawer-summary">{{ drawerPage.summary || '暂无摘要' }}</p>
          <article>{{ drawerPage.content || '暂无内容' }}</article>
          <div class="wiki-drawer-actions">
            <t-button size="small" variant="outline" @click="loadGraph('ego', drawerPage.slug)">展开邻域</t-button>
          </div>
        </div>
      </t-drawer>
    </section>

    <section v-else class="wiki-pages-panel">
      <article v-for="p in pages" :key="p.id" class="wiki-page">
        <div class="paper-kicker">{{ typeLabel(p.page_type) }}</div>
        <h3>{{ p.title }}</h3>
        <p>{{ p.summary || p.content }}</p>
      </article>
      <div v-if="!pages.length" class="empty-state">还没有 Wiki 页面</div>
    </section>

    <t-dialog v-model:visible="visible" header="新建 Wiki 页面" confirm-btn="保存" width="620px" @confirm="create">
      <t-space direction="vertical" class="form-stack">
        <t-input v-model="form.title" placeholder="标题" />
        <t-textarea v-model="form.content" :autosize="{ minRows: 8 }" placeholder="Markdown 内容" />
      </t-space>
    </t-dialog>
  </main>
</template>
