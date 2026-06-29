<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  BrowseIcon,
  ChatIcon,
  CloseIcon,
  ImageIcon,
  InternetIcon,
  LinkIcon,
  SendIcon,
  StopCircleIcon,
} from 'tdesign-icons-vue-next'

const props = defineProps<{
  disabled?: boolean
  replying?: boolean
  models?: any[]
  knowledgeBases?: any[]
  agents?: any[]
  mcpServices?: any[]
}>()
const emit = defineEmits<{
  send: [payload: any]
  stop: []
}>()

const query = ref('')
const agentEnabled = ref(false)
const agentId = ref('')
const modelId = ref('')
const selectedKbIds = ref<string[]>([])
const webSearchEnabled = ref(false)
const selectedMcpIds = ref<string[]>([])
const images = ref<Array<{ file: File; url: string }>>([])
const attachments = ref<Array<{ file: File; name: string; size: number }>>([])
const imageInput = ref<HTMLInputElement | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const agentButtonRef = ref<HTMLElement | null>(null)
const modelButtonRef = ref<HTMLElement | null>(null)
const kbButtonRef = ref<HTMLElement | null>(null)
const mcpButtonRef = ref<HTMLElement | null>(null)
const activePopover = ref<'agent' | 'model' | 'kb' | 'mcp' | ''>('')
const popoverStyle = ref<Record<string, string>>({})

const modelOptions = computed(() => props.models?.filter((m) => ['chat', 'KnowledgeQA'].includes(m.type) || m.legacy_type === 'chat') || [])
const kbOptions = computed(() => props.knowledgeBases || [])
const agentOptions = computed(() => props.agents || [])
const mcpOptions = computed(() => props.mcpServices || [])
const selectedModel = computed(() => modelOptions.value.find((model: any) => model.id === modelId.value))
const selectedKbItems = computed(() => selectedKbIds.value.map((id) => kbOptions.value.find((item: any) => item.id === id)).filter(Boolean))
const selectedMcpItems = computed(() => selectedMcpIds.value.map((id) => mcpOptions.value.find((item: any) => item.id === id)).filter(Boolean))
const agentLabel = computed(() => selectedAgentObj.value?.name || '快速问答')
const modelLabel = computed(() => selectedModel.value?.display_name || selectedModel.value?.name || modelOptions.value[0]?.display_name || modelOptions.value[0]?.name || '默认模型')
const canSend = computed(() => !!query.value.trim() && !props.disabled && !props.replying)

// 从 API 加载所有 Agent（内置 + 自定义，与 Agents 页面对齐）
const allAgents = computed(() => agentOptions.value || [])

// 默认 Agent（快速问答）
const defaultAgent = computed(() => allAgents.value.find((a: any) => a.agent_mode === 'quick-answer') || allAgents.value[0])

// 当前选中的 Agent（无选择时默认为快速问答）
const selectedAgentObj = computed(() => {
  if (!agentId.value) return defaultAgent.value
  return allAgents.value.find((a: any) => a.id === agentId.value) || defaultAgent.value
})

// 初始化时自动选择默认 Agent
if (!agentId.value && defaultAgent.value) {
  agentId.value = defaultAgent.value.id
  agentEnabled.value = false
}

function applyState(state: any = {}) {
  agentEnabled.value = !!state.agent_enabled
  agentId.value = state.agent_id || ''
  modelId.value = state.model_id || ''
  selectedKbIds.value = Array.isArray(state.knowledge_base_ids) ? state.knowledge_base_ids : []
  webSearchEnabled.value = !!state.web_search_enabled
  selectedMcpIds.value = Array.isArray(state.mcp_service_ids) ? state.mcp_service_ids : []
}

function formatSize(size: number) {
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`
  if (size >= 1024) return `${Math.round(size / 1024)} KB`
  return `${size || 0} B`
}

function positionPopover(anchor: HTMLElement | null, width = 240) {
  if (!anchor) return
  const rect = anchor.getBoundingClientRect()
  const left = Math.min(Math.max(12, rect.left), window.innerWidth - width - 12)
  // 先尝试在按钮上方弹出，如果空间不够则弹到下方
  const spaceAbove = rect.top - 8
  const estimatedHeight = 200 // 预估弹出框高度
  if (spaceAbove >= estimatedHeight) {
    popoverStyle.value = {
      left: `${left}px`,
      top: `${spaceAbove}px`,
      width: `${width}px`,
      transform: 'translateY(-100%)',
    }
  } else {
    popoverStyle.value = {
      left: `${left}px`,
      top: `${rect.bottom + 8}px`,
      width: `${width}px`,
    }
  }
}

function togglePopover(name: 'agent' | 'model' | 'kb' | 'mcp', anchor: HTMLElement | null, width = 240) {
  if (activePopover.value === name) {
    activePopover.value = ''
    return
  }
  positionPopover(anchor, width)
  activePopover.value = name
}

function closePopover() {
  activePopover.value = ''
}

function selectAgent(agent: any) {
  agentId.value = agent?.id || ''
  // 判断是否启用 Agent 模式
  const mode = agent?.agent_mode || agent?.config?.agent_mode || 'quick-answer'
  agentEnabled.value = mode === 'smart-reasoning'
  // 应用 Agent 的模型配置
  if (agent?.model_id || agent?.config?.model_id) {
    modelId.value = agent.model_id || agent.config.model_id
  }
  // 应用 Agent 的知识库配置（切换到默认时清除）
  const configuredKbIds = agent?.knowledge_base_ids || agent?.knowledge_bases || agent?.config?.knowledge_bases || []
  if (configuredKbIds.length) {
    selectedKbIds.value = configuredKbIds
  } else if (!agent) {
    selectedKbIds.value = []
  }
  // 应用 Agent 的联网搜索配置
  webSearchEnabled.value = !!(agent?.web_search_enabled ?? agent?.config?.web_search_enabled ?? false)
  closePopover()
}

function selectModel(model: any) {
  modelId.value = model?.id || ''
  closePopover()
}

function toggleKb(id: string) {
  selectedKbIds.value = selectedKbIds.value.includes(id)
    ? selectedKbIds.value.filter((item) => item !== id)
    : [...selectedKbIds.value, id]
}

function toggleMcp(id: string) {
  selectedMcpIds.value = selectedMcpIds.value.includes(id)
    ? selectedMcpIds.value.filter((item) => item !== id)
    : [...selectedMcpIds.value, id]
}

function removeKb(id: string) {
  selectedKbIds.value = selectedKbIds.value.filter((item) => item !== id)
}

function removeAttachment(name: string) {
  attachments.value = attachments.value.filter((item) => item.name !== name)
}

function removeImage(url: string) {
  const target = images.value.find((item) => item.url === url)
  if (target) URL.revokeObjectURL(target.url)
  images.value = images.value.filter((item) => item.url !== url)
}

function addImages(event: Event) {
  const files = Array.from((event.target as HTMLInputElement).files || [])
  for (const file of files.slice(0, 5 - images.value.length)) {
    images.value.push({ file, url: URL.createObjectURL(file) })
  }
  ;(event.target as HTMLInputElement).value = ''
}

function addFiles(event: Event) {
  const files = Array.from((event.target as HTMLInputElement).files || [])
  for (const file of files.slice(0, 5 - attachments.value.length)) attachments.value.push({ file, name: file.name, size: file.size })
  ;(event.target as HTMLInputElement).value = ''
}

async function fileToData(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

async function submit() {
  if (!canSend.value) return
  const imagePayload = []
  for (const item of images.value) imagePayload.push({ data: await fileToData(item.file), url: item.url })
  const attachmentPayload = []
  for (const item of attachments.value) {
    const data = await fileToData(item.file)
    attachmentPayload.push({ data: data.split(',')[1] || data, file_name: item.name, file_size: item.size })
  }
  emit('send', {
    query: query.value.trim(),
    agent_enabled: agentEnabled.value,
    agent_id: agentId.value,
    model_id: modelId.value,
    knowledge_base_ids: selectedKbIds.value,
    web_search_enabled: webSearchEnabled.value,
    mcp_service_ids: selectedMcpIds.value,
    images: imagePayload,
    attachment_uploads: attachmentPayload,
    mentioned_items: selectedKbIds.value.map((id) => {
      const kb = kbOptions.value.find((item: any) => item.id === id)
      return { id, type: 'kb', name: kb?.name || id, kb_type: kb?.type || 'document' }
    }),
  })
  query.value = ''
  images.value.forEach((item) => URL.revokeObjectURL(item.url))
  images.value = []
  attachments.value = []
}

function onDocumentClick(event: MouseEvent) {
  const target = event.target as HTMLElement
  if (target.closest('.chat-popover') || target.closest('.control-btn')) return
  closePopover()
}

defineExpose({ applyState })

watch(modelOptions, (items) => {
  if (!modelId.value && items.length) modelId.value = items[0].id || ''
}, { immediate: true })

onMounted(() => document.addEventListener('click', onDocumentClick))
onUnmounted(() => {
  document.removeEventListener('click', onDocumentClick)
  images.value.forEach((item) => URL.revokeObjectURL(item.url))
})
</script>

<template>
  <section class="answers-input">
    <input ref="imageInput" type="file" accept="image/*" multiple hidden @change="addImages" />
    <input ref="fileInput" type="file" multiple hidden @change="addFiles" />

    <div class="rich-input-container">
      <div v-if="selectedKbItems.length || images.length || attachments.length || selectedMcpItems.length" class="selected-tags-inline">
        <span v-for="kb in selectedKbItems" :key="kb.id" class="mention-chip mention-chip--kb">
          <span class="mention-chip__icon">@</span>
          <span class="mention-chip__name">{{ kb.name }}</span>
          <button @click="removeKb(kb.id)"><CloseIcon /></button>
        </span>
        <span v-for="service in selectedMcpItems" :key="service.id" class="mention-chip">
          <span class="mention-chip__icon">M</span>
          <span class="mention-chip__name">{{ service.name }}</span>
        </span>
        <span v-for="img in images" :key="img.url" class="draft-preview-chip">
          <img :src="img.url" alt="draft image" />
          <button @click="removeImage(img.url)"><CloseIcon /></button>
        </span>
        <span v-for="file in attachments" :key="file.name" class="mention-chip">
          <span class="mention-chip__icon"><LinkIcon /></span>
          <span class="mention-chip__name">{{ file.name }}</span>
          <small>{{ formatSize(file.size) }}</small>
          <button @click="removeAttachment(file.name)"><CloseIcon /></button>
        </span>
      </div>

      <textarea
        v-model="query"
        :disabled="disabled"
        placeholder="直接问模型提问"
        @keydown.enter.exact.prevent="submit"
        @keydown.ctrl.enter.prevent="submit"
        @keydown.meta.enter.prevent="submit"
      />

      <div class="control-bar">
        <div class="control-left">
          <button ref="agentButtonRef" class="control-btn agent-mode-btn" :class="{ active: agentEnabled || agentId }" @click.stop="togglePopover('agent', agentButtonRef, 220)">
            <ChatIcon />
            <span>{{ agentLabel }}</span>
          </button>
          <button class="control-btn icon-only" :class="{ active: webSearchEnabled }" title="联网搜索" @click="webSearchEnabled = !webSearchEnabled"><InternetIcon /></button>
          <button class="control-btn icon-only" title="图片" @click="imageInput?.click()"><ImageIcon /></button>
          <button class="control-btn icon-only" title="附件" @click="fileInput?.click()"><LinkIcon /></button>
          <button ref="kbButtonRef" class="control-btn icon-only" :class="{ active: selectedKbIds.length }" title="知识库" @click.stop="togglePopover('kb', kbButtonRef, 280)">@</button>
          <button v-if="mcpOptions.length" ref="mcpButtonRef" class="control-btn icon-only" :class="{ active: selectedMcpIds.length }" title="MCP" @click.stop="togglePopover('mcp', mcpButtonRef, 260)"><BrowseIcon /></button>
        </div>

        <div class="control-right">
          <button ref="modelButtonRef" class="model-selector-trigger" @click.stop="togglePopover('model', modelButtonRef, 280)">
            <span>{{ modelLabel }}</span>
            <i class="model-arrow"></i>
          </button>
          <button v-if="replying" class="control-btn stop-btn" @click="$emit('stop')"><StopCircleIcon /></button>
          <button v-else class="control-btn send-btn" :class="{ disabled: !canSend }" :disabled="!canSend" @click="submit"><SendIcon /></button>
        </div>
      </div>
    </div>

    <Teleport to="body">
      <div v-if="activePopover" class="chat-popover" :style="popoverStyle" @click.stop>
        <template v-if="activePopover === 'agent'">
          <div class="chat-popover-head"><span>选择智能体</span></div>
          <!-- 所有 Agent（内置 + 自定义，与 Agents 页面一致） -->
          <button v-for="agent in allAgents" :key="agent.id" class="chat-option" :class="{ selected: agent.id === agentId }" @click="selectAgent(agent)">
            <ChatIcon />
            <span>{{ agent.name }}</span>
            <small>{{ agent.description || (agent.agent_mode === 'smart-reasoning' ? '智能推理' : '快速问答') }}</small>
            <strong v-if="agent.id === agentId">✓</strong>
          </button>
          <div v-if="!allAgents.length" class="chat-popover-empty">暂无可用智能体</div>
        </template>

        <template v-if="activePopover === 'model'">
          <div class="chat-popover-head"><span>对话模型</span></div>
          <button v-for="model in modelOptions" :key="model.id" class="chat-option" :class="{ selected: model.id === modelId }" @click="selectModel(model)">
            <span>{{ model.display_name || model.name }}</span>
            <small>{{ model.source || 'model' }}</small>
            <strong v-if="model.id === modelId">✓</strong>
          </button>
        </template>

        <template v-if="activePopover === 'kb'">
          <div class="chat-popover-head"><span>选择知识库</span><small>{{ selectedKbIds.length }} 已选</small></div>
          <button v-for="kb in kbOptions" :key="kb.id" class="chat-option" :class="{ selected: selectedKbIds.includes(kb.id) }" @click="toggleKb(kb.id)">
            <span>{{ kb.name }}</span>
            <small>{{ kb.document_count ?? kb.knowledge_count ?? 0 }} 文档</small>
            <strong v-if="selectedKbIds.includes(kb.id)">✓</strong>
          </button>
          <p v-if="!kbOptions.length" class="chat-popover-empty">暂无知识库</p>
        </template>

        <template v-if="activePopover === 'mcp'">
          <div class="chat-popover-head"><span>MCP 服务</span><small>{{ selectedMcpIds.length }} 已选</small></div>
          <button v-for="service in mcpOptions" :key="service.id" class="chat-option" :class="{ selected: selectedMcpIds.includes(service.id) }" @click="toggleMcp(service.id)">
            <span>{{ service.name }}</span>
            <small>{{ service.status || 'active' }}</small>
            <strong v-if="selectedMcpIds.includes(service.id)">✓</strong>
          </button>
        </template>
      </div>
    </Teleport>
  </section>
</template>
