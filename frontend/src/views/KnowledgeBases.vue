<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import { api } from '../api'

const router = useRouter()
const items = ref<any[]>([])
const loading = ref(false)
const visible = ref(false)
const keyword = ref('')
const typeFilter = ref('')
const form = ref({
  name: '',
  description: '',
  chunking_config: { chunk_size: 512, chunk_overlap: 50 },
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

const typeOptions = [
  { value: '', label: '全部知识库' },
  { value: 'document', label: '文档知识库' },
  { value: 'wiki', label: 'RAG + Wiki' },
]

const hybridEnabled = computed({
  get: () => !!(form.value.indexing_strategy.vector_enabled || form.value.indexing_strategy.keyword_enabled),
  set: (enabled: boolean) => {
    form.value.indexing_strategy.vector_enabled = enabled
    form.value.indexing_strategy.keyword_enabled = enabled
  },
})

const stats = computed(() => {
  const count = items.value.length
  const knowledge = items.value.reduce((sum, item) => sum + Number(item.knowledge_count || item.document_count || 0), 0)
  const chunks = items.value.reduce((sum, item) => sum + Number(item.chunk_count || 0), 0)
  const processing = items.value.reduce((sum, item) => sum + Number(item.processing_count || 0), 0)
  return { count, knowledge, chunks, processing }
})

function resetForm() {
  form.value = {
    name: '',
    description: '',
    chunking_config: { chunk_size: 512, chunk_overlap: 50 },
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
  }
}

function isWikiEnabled(kb: any) {
  return !!(kb.indexing_strategy?.wiki_enabled || kb.capabilities?.wiki)
}

function typeLabel(kb: any) {
  if (isWikiEnabled(kb)) return 'RAG + Wiki'
  return '文档知识库'
}

function capabilityLabels(kb: any) {
  const strategy = kb.indexing_strategy || {}
  const caps = kb.capabilities || {}
  const labels = []
  if (strategy.vector_enabled || strategy.keyword_enabled || caps.vector || caps.keyword) labels.push('混合检索')
  if (strategy.wiki_enabled || caps.wiki) labels.push('Wiki')
  if (strategy.graph_enabled || caps.graph) labels.push('图谱')
  return labels
}

async function load() {
  loading.value = true
  try {
    const params: any = { page: 1, page_size: 100 }
    if (keyword.value) params.keyword = keyword.value
    if (typeFilter.value) params.type = typeFilter.value
    const res: any = await api.searchKbs(params)
    items.value = res.data?.items || res.data?.knowledge_bases || []
  } finally {
    loading.value = false
  }
}

async function create() {
  if (!form.value.name.trim()) {
    MessagePlugin.warning('请输入知识库名称')
    return
  }
  const strategy = form.value.indexing_strategy
  if (!(strategy.vector_enabled || strategy.keyword_enabled || strategy.wiki_enabled || strategy.graph_enabled)) {
    MessagePlugin.warning('至少开启一种索引配置')
    return
  }
  const payload = {
    ...form.value,
    type: 'document',
    indexing_strategy: {
      vector_enabled: form.value.indexing_strategy.vector_enabled,
      keyword_enabled: form.value.indexing_strategy.keyword_enabled,
      wiki_enabled: form.value.indexing_strategy.wiki_enabled,
      graph_enabled: form.value.indexing_strategy.graph_enabled,
    },
    extract_config: {
      ...form.value.extract_config,
      enabled: form.value.indexing_strategy.graph_enabled,
    },
  }
  await api.createKb(payload)
  visible.value = false
  resetForm()
  await load()
  MessagePlugin.success('知识库已创建')
}

async function togglePin(kb: any) {
  await api.pinKb(kb.id, !kb.is_pinned)
  await load()
}

async function copyKb(kb: any) {
  await api.copyKb(kb.id)
  await load()
  MessagePlugin.success('已复制知识库')
}

async function removeKb(kb: any) {
  if (!confirm(`确定删除知识库“${kb.name}”？`)) return
  await api.deleteKb(kb.id)
  await load()
}

onMounted(load)
</script>

<template>
  <main class="content kb-page">
    <section class="archive-hero">
      <div>
        <div class="paper-kicker">Knowledge bases</div>
        <h2>知识库</h2>
        <p>统一管理文档与 Wiki 能力，创建后可立即上传、检索和对话。</p>
      </div>
      <div class="archive-stats">
        <span><strong>{{ stats.count }}</strong> 库</span>
        <span><strong>{{ stats.knowledge }}</strong> 条目</span>
        <span><strong>{{ stats.chunks }}</strong> 摘录</span>
        <span><strong>{{ stats.processing }}</strong> 处理中</span>
      </div>
    </section>

    <div class="workbench-bar">
      <t-input v-model="keyword" clearable placeholder="搜索知识库名称或描述" @enter="load" />
      <t-select v-model="typeFilter" class="filter-select" @change="load">
        <t-option v-for="item in typeOptions" :key="item.value" :value="item.value" :label="item.label" />
      </t-select>
      <t-button variant="outline" @click="load">刷新</t-button>
      <t-button theme="primary" @click="visible = true">新建知识库</t-button>
    </div>

    <div v-if="loading" class="kb-grid">
      <div v-for="n in 6" :key="n" class="kb-card skeleton-card"></div>
    </div>
    <div v-else class="kb-grid">
      <article v-for="kb in items" :key="kb.id" class="kb-card" @click="router.push(`/platform/knowledge-bases/${kb.id}`)">
        <div class="kb-card-top">
          <div class="kb-type">{{ typeLabel(kb) }}</div>
          <t-tag v-if="kb.is_pinned" size="small" theme="warning">置顶</t-tag>
        </div>
        <h3>{{ kb.name }}</h3>
        <p>{{ kb.description || '暂无描述' }}</p>
        <div class="kb-capabilities">
          <span v-for="cap in capabilityLabels(kb)" :key="cap">{{ cap }}</span>
        </div>
        <div class="kb-meter">
          <span :style="{ width: `${Math.min(100, (kb.chunk_count || 0) * 8)}%` }"></span>
        </div>
        <footer>
          <span>条目 {{ kb.knowledge_count || kb.document_count || 0 }}</span>
          <span>摘录 {{ kb.chunk_count || 0 }}</span>
          <span>{{ kb.updated_at ? new Date(kb.updated_at).toLocaleDateString() : '未归档' }}</span>
        </footer>
        <div class="card-actions" @click.stop>
          <button @click="togglePin(kb)">{{ kb.is_pinned ? '取消置顶' : '置顶' }}</button>
          <button @click="copyKb(kb)">复制</button>
          <button class="danger" @click="removeKb(kb)">删除</button>
        </div>
      </article>
      <div v-if="!items.length" class="empty-state">暂无知识库，创建一个工作空间后开始上传内容</div>
    </div>

    <t-dialog v-model:visible="visible" header="新建知识库" confirm-btn="创建" width="720px" @confirm="create">
      <div class="editor-grid">
        <t-input v-model="form.name" label="名称" placeholder="例如：合同资料库" />
        <div class="capability-panel">
          <span>索引配置</span>
          <label>
            <input v-model="hybridEnabled" type="checkbox" />
            <span>
              <strong>混合检索</strong>
              <small>同时启用向量检索和关键词检索</small>
            </span>
          </label>
          <label>
            <input v-model="form.indexing_strategy.wiki_enabled" type="checkbox" />
            <span>
              <strong>Wiki 知识库</strong>
              <small>用于组织结构化知识页面</small>
            </span>
          </label>
          <label>
            <input v-model="form.indexing_strategy.graph_enabled" type="checkbox" />
            <span>
              <strong>知识图谱</strong>
              <small>解析后抽取实体关系增强检索</small>
            </span>
          </label>
        </div>
        <t-textarea v-model="form.description" class="wide" label="描述" placeholder="记录用途、资料范围或维护人" />
        <div class="mini-config wide">
          <label><span>分块长度</span><input v-model.number="form.chunking_config.chunk_size" type="number" min="128" max="4096" /></label>
          <label><span>重叠字符</span><input v-model.number="form.chunking_config.chunk_overlap" type="number" min="0" max="1024" /></label>
        </div>
      </div>
    </t-dialog>
  </main>
</template>
