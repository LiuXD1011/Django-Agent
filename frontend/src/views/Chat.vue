<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, streamChat } from '../api'
import { useChatStore } from '../stores/chat'
import ChatInput from './chat/components/ChatInput.vue'
import ChatTimeline from './chat/components/ChatTimeline.vue'
import SessionSidebar from './chat/components/SessionSidebar.vue'

const route = useRoute()
const router = useRouter()
const chatStore = useChatStore()

const sessionId = ref(String(route.params.chatId || ''))
const sessions = ref<any[]>([])
const messages = ref<any[]>([])
const models = ref<any[]>([])
const knowledgeBases = ref<any[]>([])
const agents = ref<any[]>([])
const mcpServices = ref<any[]>([])
const historyLoading = ref(false)
const sessionLoading = ref(false)
const replying = ref(false)
const hasMoreHistory = ref(true)
const batchMode = ref(false)
const selectedSessionIds = ref<string[]>([])
const currentAssistantId = ref('')
const streamAbort = ref<AbortController | null>(null)
const timelineRef = ref<InstanceType<typeof ChatTimeline> | null>(null)
const inputRef = ref<InstanceType<typeof ChatInput> | null>(null)

const isCreateMode = computed(() => !sessionId.value || route.path.endsWith('/creatChat'))

// ── 资源加载 ──────────────────────────────────────────────────────
async function loadResources() {
  const [modelRes, kbRes, agentRes, mcpRes] = await Promise.all([api.listModels(), api.listKbs(), api.listAgents(), api.listMcpServices()])
  models.value = (modelRes as any).data?.items || []
  knowledgeBases.value = (kbRes as any).data?.items || []
  agents.value = ((agentRes as any).data?.items || []).map((item: any) => ({ ...item, ...(item.data || {}) }))
  mcpServices.value = (mcpRes as any).data?.items || []
}

async function loadSessions() {
  sessionLoading.value = true
  try {
    const res: any = await api.listSessions({ page: 1, page_size: 100 })
    sessions.value = res.data?.items || []
  } finally {
    sessionLoading.value = false
  }
}

async function loadMessages(reset = true) {
  if (!sessionId.value || isCreateMode.value) {
    messages.value = []
    return
  }
  historyLoading.value = true
  try {
    const before = reset ? '' : messages.value[0]?.created_at
    const res: any = await api.loadMessages(sessionId.value, { limit: 20, ...(before ? { before_time: before } : {}) })
    const items = res.data?.items || []
    hasMoreHistory.value = !!res.data?.has_more && items.length > 0
    if (reset) messages.value = items
    else {
      const height = document.querySelector('.messages')?.scrollHeight || 0
      messages.value = [...items, ...messages.value]
      nextTick(() => {
        const el = document.querySelector('.messages') as HTMLElement | null
        if (el) el.scrollTop = el.scrollHeight - height
      })
    }
  } finally {
    historyLoading.value = false
  }
}

// ── 会话操作 ──────────────────────────────────────────────────────
async function openSession(id: string) {
  if (!id || id === sessionId.value) return
  stopStream()
  sessionId.value = id
  await router.push(`/platform/chat/${id}`)
  await loadMessages(true)
  const res: any = await api.getSession(id)
  inputRef.value?.applyState(res.data?.last_request_state || {})
}

async function createSession(payload: any) {
  const kbId = route.params.kbId ? String(route.params.kbId) : ''
  const res: any = await api.createSession({
    title: '新的对话',
    knowledge_base_id: kbId || payload.knowledge_base_ids?.[0] || '',
    agent_config: {
      agent_enabled: payload.agent_enabled,
      agent_id: payload.agent_id || '',
      knowledge_base_ids: payload.knowledge_base_ids || [],
      model_id: payload.model_id || '',
      web_search_enabled: payload.web_search_enabled,
      mcp_service_ids: payload.mcp_service_ids || [],
    },
  })
  const id = res.data.id
  sessionId.value = id
  await loadSessions()
  return id
}

// ── 流控制 ────────────────────────────────────────────────────────
/** 中止当前正在进行的流式对话 */
function stopStream() {
  if (streamAbort.value) {
    streamAbort.value.abort()
    streamAbort.value = null
  }
  replying.value = false
  currentAssistantId.value = ''
}

/** 发送新消息前，将所有未完成的 assistant 消息标记为已完成 */
function prepareForNewOutgoingMessage() {
  for (const msg of messages.value) {
    if (msg.role === 'assistant' && !msg.is_completed) {
      msg.is_completed = true
    }
  }
}

// ── 消息发送 ──────────────────────────────────────────────────────
function upsertAssistant(payload: any, completed = false) {
  const id = payload.id || payload.message_id || currentAssistantId.value
  if (!id) return
  currentAssistantId.value = id
  let target = messages.value.find((m) => m.id === id || m.request_id === id)
  if (!target) {
    target = { id, request_id: payload.request_id || id, role: 'assistant', content: '', knowledge_references: [], agent_steps: [], is_completed: false }
    messages.value.push(target)
  }
  Object.assign(target, payload, { role: 'assistant', is_completed: completed || payload.is_completed })
}

function buildLocalUser(payload: any) {
  return {
    id: `local-${Date.now()}`,
    role: 'user',
    content: payload.query,
    mentioned_items: payload.mentioned_items,
    images: payload.images?.map((img: any) => ({ url: img.data || img.url })),
    attachments: payload.attachment_uploads,
    is_completed: true,
    created_at: new Date().toISOString(),
  }
}

/** 创建模式：创建会话 → 导航 → 在 onMounted 中发送 */
async function sendFromCreateMode(payload: any) {
  const id = await createSession(payload)
  if (!id) return
  // 存储首条消息到 store，导航到 chat 页面后由 onMounted 发送
  chatStore.setFirstQuery(payload.query, payload)
  await router.replace(`/platform/chat/${id}`)
}

/** 已有会话模式：直接发送 */
async function sendFromExistingSession(payload: any) {
  stopStream()
  prepareForNewOutgoingMessage()
  const localUser = buildLocalUser(payload)
  messages.value.push(localUser)
  const id = sessionId.value
  await doStream(id, payload)
}

/** 统一的发送入口 */
async function send(payload: any) {
  if (isCreateMode.value) {
    await sendFromCreateMode(payload)
  } else {
    await sendFromExistingSession(payload)
  }
}

/** 流式对话核心逻辑 */
async function doStream(id: string, payload: any) {
  replying.value = true
  currentAssistantId.value = ''
  streamAbort.value = new AbortController()
  try {
    await streamChat(
      id,
      payload,
      payload.agent_enabled,
      (event, data) => {
        const responseType = data?.response_type
        if (responseType === 'agent_query') {
          currentAssistantId.value = data.assistant_message_id || data.id
          upsertAssistant({ id: currentAssistantId.value, request_id: data.id, content: '', agent_steps: [], agent_tool_calls: [] }, false)
        } else if (responseType === 'answer') {
          upsertAssistant({ id: data.assistant_message_id || currentAssistantId.value, request_id: data.id, content: data.content || '', knowledge_references: data.knowledge_references || [] }, !!data.done)
        } else if (responseType === 'references') {
          upsertAssistant({ id: data.assistant_message_id || data.id || currentAssistantId.value, knowledge_references: data.knowledge_references || [] }, false)
        } else if (responseType === 'tool_call') {
          // Agent 工具调用事件
          const target = messages.value.find((m) => m.id === data.assistant_message_id || m.id === currentAssistantId.value)
          if (target) {
            if (!target.agent_tool_calls) target.agent_tool_calls = []
            target.agent_tool_calls.push({ name: data.name, arguments: data.arguments, iteration: data.iteration, status: 'running' })
          }
        } else if (responseType === 'tool_result') {
          // Agent 工具结果事件
          const target = messages.value.find((m) => m.id === data.assistant_message_id || m.id === currentAssistantId.value)
          if (target && target.agent_tool_calls) {
            const lastCall = target.agent_tool_calls.find((tc: any) => tc.name === data.name && tc.status === 'running')
            if (lastCall) {
              lastCall.status = 'done'
              lastCall.output = data.output
              lastCall.duration_ms = data.duration_ms
            }
          }
        } else if (responseType === 'complete') {
          const target = messages.value.find((m) => m.id === data.assistant_message_id || m.request_id === data.id)
          if (target) target.is_completed = true
        } else if (responseType === 'session_title') {
          // 更新侧边栏标题（不重载全部会话）
          if (data.session_id && data.title) {
            const target = sessions.value.find((s) => s.id === data.session_id)
            if (target) target.title = data.title
            else loadSessions()
          } else {
            loadSessions()
          }
        } else if (event === 'message_start') {
          currentAssistantId.value = data.id
          upsertAssistant({ ...data, content: '', agent_steps: [{ type: 'knowledge_search' }] }, false)
        } else if (event === 'message') {
          upsertAssistant(data, !!data.is_completed)
        } else if (event === 'references') {
          upsertAssistant({ id: data.id || currentAssistantId.value, knowledge_references: data.knowledge_references || [] }, false)
        } else if (event === 'done') {
          const target = messages.value.find((m) => m.id === data.message_id)
          if (target) target.is_completed = true
        }
        timelineRef.value?.scrollToBottom()
      },
      streamAbort.value.signal,
    )
  } catch (err: any) {
    // AbortError 是用户主动取消，不需要 fallback
    if (err?.name === 'AbortError') return
    try {
      const res: any = payload.agent_enabled ? await api.agentChat(id, payload) : await api.chat(id, payload)
      upsertAssistant(res.data.message, true)
    } catch {
      upsertAssistant({ content: '请求失败，请稍后重试。', is_completed: true, is_fallback: true }, true)
    }
  } finally {
    replying.value = false
    currentAssistantId.value = ''
    await loadSessions()
    if (id) {
      const res: any = await api.getSession(id)
      inputRef.value?.applyState(res.data?.last_request_state || {})
    }
  }
}

async function stopReply() {
  const abort = streamAbort.value
  const assistantId = currentAssistantId.value
  stopStream()
  if (sessionId.value && assistantId) {
    try { await api.stopSession(sessionId.value, assistantId) } catch { /* ignore */ }
  }
}

// ── 组件卸载时清理 ────────────────────────────────────────────────
onUnmounted(() => {
  stopStream()
})

async function removeSession(id: string) {
  await api.deleteSession(id)
  sessions.value = sessions.value.filter((s) => s.id !== id)
  selectedSessionIds.value = selectedSessionIds.value.filter((item) => item !== id)
  if (id === sessionId.value) {
    sessionId.value = ''
    messages.value = []
    await router.push('/platform/creatChat')
  }
}

async function clearMessages(id: string) {
  await api.clearSessionMessages(id)
  if (id === sessionId.value) messages.value = []
}

async function togglePin(session: any) {
  if (session.is_pinned) await api.unpinSession(session.id)
  else await api.pinSession(session.id)
  await loadSessions()
}

function toggleBatch() {
  batchMode.value = !batchMode.value
  selectedSessionIds.value = []
}

function toggleSelect(id: string) {
  selectedSessionIds.value = selectedSessionIds.value.includes(id)
    ? selectedSessionIds.value.filter((item) => item !== id)
    : [...selectedSessionIds.value, id]
}

async function deleteSelected() {
  if (!selectedSessionIds.value.length) return
  await api.deleteSessions(selectedSessionIds.value)
  if (sessionId.value && selectedSessionIds.value.includes(sessionId.value)) {
    sessionId.value = ''
    messages.value = []
    await router.push('/platform/creatChat')
  }
  selectedSessionIds.value = []
  batchMode.value = false
  await loadSessions()
}

async function deleteAll() {
  await api.deleteAllSessions()
  sessions.value = []
  selectedSessionIds.value = []
  batchMode.value = false
  sessionId.value = ''
  messages.value = []
  await router.push('/platform/creatChat')
}

// ── 初始化 ────────────────────────────────────────────────────────
async function bootstrap() {
  sessionId.value = String(route.params.chatId || '')
  await Promise.all([loadResources(), loadSessions()])
  if (sessionId.value && !isCreateMode.value) {
    await loadMessages(true)
    const res: any = await api.getSession(sessionId.value)
    inputRef.value?.applyState(res.data?.last_request_state || {})
  }
}

onMounted(bootstrap)
watch(
  () => route.params.chatId,
  async (value) => {
    sessionId.value = String(value || '')
    await loadMessages(true)
    if (value) {
      const res: any = await api.getSession(String(value))
      inputRef.value?.applyState(res.data?.last_request_state || {})
    }
    // 从创建模式跳转过来时，发送首条消息
    if (value && chatStore.firstQuery) {
      const payload = chatStore.firstPayload
      chatStore.clearFirstQuery()
      if (payload) {
        await sendFromExistingSession(payload)
      }
    }
  },
)
</script>

<template>
  <main class="wk-chat-layout" :class="{ 'create-mode': isCreateMode }">
    <SessionSidebar
      :sessions="sessions"
      :active-id="sessionId"
      :loading="sessionLoading"
      :batch-mode="batchMode"
      :selected-ids="selectedSessionIds"
      @new-chat="router.push('/platform/creatChat')"
      @open="openSession"
      @delete="removeSession"
      @clear="clearMessages"
      @pin="togglePin"
      @batch="toggleBatch"
      @toggle-select="toggleSelect"
      @delete-selected="deleteSelected"
      @delete-all="deleteAll"
    />

    <section v-if="isCreateMode" class="create-chat-page">
      <div class="create-chat-scroll">
        <div class="dialogue-title">
          <div class="paper-kicker">New chat</div>
          <h2>今天想查阅什么资料？</h2>
          <p>先选择知识范围，再发送问题；系统会创建会话并进入连续问答。</p>
        </div>
      </div>
      <ChatInput ref="inputRef" :models="models" :knowledge-bases="knowledgeBases" :agents="agents" :mcp-services="mcpServices" :replying="replying" @send="send" @stop="stopReply" />
    </section>

    <section v-else class="wk-chat-main">
      <ChatTimeline ref="timelineRef" :messages="messages" :loading="replying" :history-loading="historyLoading" :has-more="hasMoreHistory" @load-more="loadMessages(false)" />
      <ChatInput ref="inputRef" :models="models" :knowledge-bases="knowledgeBases" :agents="agents" :mcp-services="mcpServices" :replying="replying" @send="send" @stop="stopReply" />
    </section>
  </main>
</template>
