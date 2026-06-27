<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import AssistantMessage from './AssistantMessage.vue'
import UserMessage from './UserMessage.vue'

const props = defineProps<{
  messages: any[]
  loading?: boolean
  historyLoading?: boolean
  hasMore?: boolean
}>()
const emit = defineEmits<{ loadMore: [] }>()

const scroller = ref<HTMLElement | null>(null)
const userScrolledUp = ref(false)

function nearBottom() {
  const el = scroller.value
  if (!el) return true
  return el.scrollHeight - el.scrollTop - el.clientHeight < 90
}

function scrollToBottom(force = false) {
  if (!force && userScrolledUp.value) return
  nextTick(() => {
    if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
  })
}

function onScroll() {
  const el = scroller.value
  if (!el) return
  userScrolledUp.value = !nearBottom()
  if (el.scrollTop <= 4 && props.hasMore && !props.historyLoading) emit('loadMore')
}

watch(
  () => props.messages.length,
  () => scrollToBottom(false),
)

defineExpose({ scrollToBottom })
</script>

<template>
  <section class="chat-timeline">
    <div ref="scroller" class="messages" @scroll="onScroll">
      <div v-if="historyLoading && !messages.length" class="msg-skeleton-list">
        <div class="msg-skeleton user"></div>
        <div class="msg-skeleton assistant"></div>
        <div class="msg-skeleton user short"></div>
      </div>
      <button v-if="hasMore && messages.length" class="load-history-btn" @click="$emit('loadMore')">加载更早消息</button>
      <template v-for="(message, index) in messages" :key="message.id || `${message.role}-${message.created_at}-${index}`">
        <UserMessage v-if="message.role === 'user'" :message="message" />
        <AssistantMessage v-else :message="message" :loading="loading && index === messages.length - 1" />
      </template>
      <!-- 流式等待提示：正在请求但还没有 assistant 消息 -->
      <AssistantMessage v-if="loading && (!messages.length || messages[messages.length - 1]?.role === 'user')" :message="{ content: '', is_completed: false, agent_steps: [{ type: 'search' }] }" loading />
      <div v-if="!messages.length && !loading && !historyLoading" class="suggested-questions-container empty-chat-state">
        <div class="suggested-questions-inner">
          <div class="paper-kicker">New chat</div>
          <h2>开始一次资料问答</h2>
          <p>选择知识库范围，输入问题，系统会检索引用并生成回答。</p>
        </div>
      </div>
    </div>
    <button v-show="userScrolledUp" class="scroll-to-bottom-btn" @click="scrollToBottom(true)">↓</button>
  </section>
</template>
