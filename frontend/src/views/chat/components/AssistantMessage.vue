<script setup lang="ts">
import { computed } from 'vue'
import CitationList from './CitationList.vue'
import ActorTrace from './ActorTrace.vue'
import RagProgress from './RagProgress.vue'
import ToolResultRenderer from './ToolResultRenderer.vue'
import { renderMarkdownLite } from '../../../utils/markdown-lite.mjs'
import { CheckCircleIcon, ErrorCircleIcon, LoadingIcon } from 'tdesign-icons-vue-next'

const props = defineProps<{ message: any; loading?: boolean }>()

const isThinking = computed(() => props.loading && !props.message?.content?.trim())
const isStreaming = computed(() => props.loading && props.message?.content?.trim() && !props.message?.is_completed)
const toolCalls = computed(() => props.message?.agent_tool_calls || [])
const actorTraces = computed(() => props.message?.actor_traces || [])

const renderedContent = computed(() => renderMarkdownLite(props.message?.content || ''))

function copyAnswer() {
  navigator.clipboard?.writeText(props.message?.content || '')
}
</script>

<template>
  <article class="chat-message assistant-message" :class="{ 'is-thinking': isThinking, 'is-streaming': isStreaming }">
    <div class="paper-kicker">{{ message?.is_fallback ? '本地兜底' : '答复' }}</div>

    <!-- RAG 进度条 -->
    <RagProgress :message="message" :loading="loading" />

    <!-- Agent 工具调用展示 -->
    <div v-if="toolCalls.length" class="agent-tool-trace">
      <component
        :is="tc.status === 'running' ? 'div' : 'details'"
        v-for="(tc, idx) in toolCalls"
        :key="tc.tool_call_id || `${tc.name}-${idx}`"
        class="tool-call-item"
        :class="tc.status"
        :open="tc.status === 'failed'"
      >
        <component :is="tc.status === 'running' ? 'div' : 'summary'" class="tool-call-header">
          <LoadingIcon v-if="tc.status === 'running'" class="tool-call-icon tool-call-loading" />
          <CheckCircleIcon v-else-if="tc.status === 'done'" class="tool-call-icon" />
          <ErrorCircleIcon v-else class="tool-call-icon" />
          <span class="tool-call-name">{{ tc.name }}</span>
          <span v-if="tc.duration_ms" class="tool-call-time">{{ tc.duration_ms }}ms</span>
        </component>
        <div v-if="tc.status !== 'running'" class="tool-call-output">
          <ToolResultRenderer :name="tc.name" :output="tc.output || ''" :error="tc.error" :duration-ms="tc.duration_ms" />
        </div>
      </component>
    </div>

    <!-- 子 Actor 执行轨迹 -->
    <ActorTrace :actors="actorTraces" />

    <!-- 思考中状态 -->
    <div v-if="isThinking" class="thinking-indicator">
      <div class="thinking-dots">
        <span></span><span></span><span></span>
      </div>
      <span class="thinking-text">正在思考...</span>
    </div>

    <!-- 正文内容 -->
    <div v-if="message.content" class="message-body markdown-lite" v-html="renderedContent"></div>
    <span v-if="isStreaming" class="streaming-cursor">▋</span>

    <!-- 引用列表 -->
    <CitationList :references="message.knowledge_references" />

    <!-- 完成后的工具栏 -->
    <div v-if="message?.is_completed && message?.content" class="answer-tools">
      <button @click="copyAnswer">复制</button>
      <button disabled>加入知识库</button>
      <span v-if="message.request_id">RID {{ String(message.request_id).slice(0, 8) }}</span>
    </div>
  </article>
</template>

<style scoped>
/* ── Agent 工具调用追踪 ─────────────────────────────────────────── */
.agent-tool-trace {
  padding: 8px 0;
  margin-bottom: 4px;
}

.tool-call-item {
  margin-bottom: 4px;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid #e8e8e8;
  background: #fafbfc;
  transition: all 0.2s ease;
}

.tool-call-item.running {
  border-color: #4f46e5;
  background: #f5f3ff;
}

.tool-call-item.done {
  border-color: #e8e8e8;
  background: #f0fdf4;
}

.tool-call-item.failed {
  border-color: #f53f3f;
  background: #fff2f0;
}

.tool-call-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  font-size: 12px;
  font-weight: 500;
}

summary.tool-call-header {
  cursor: pointer;
  list-style: none;
}

summary.tool-call-header::-webkit-details-marker {
  display: none;
}

.tool-call-icon {
  flex: 0 0 14px;
  font-size: 12px;
}

.tool-call-loading {
  animation: tool-call-spin 1s linear infinite;
}

.tool-call-name {
  color: #1d2129;
  font-family: monospace;
}

.tool-call-time {
  margin-left: auto;
  color: #86909c;
  font-size: 11px;
}

.tool-call-output {
  padding: 6px 10px;
  font-size: 11px;
  color: #4e5969;
  background: #f9fafb;
  border-top: 1px solid #e8e8e8;
  white-space: pre-wrap;
  word-break: break-all;
  font-family: monospace;
}

@keyframes tool-call-spin {
  to { transform: rotate(360deg); }
}

/* ── 思考中指示器 ───────────────────────────────────────────────── */
.thinking-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 0;
}

.thinking-dots {
  display: flex;
  gap: 4px;
}

.thinking-dots span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #4f46e5;
  animation: dot-bounce 1.4s ease-in-out infinite;
}

.thinking-dots span:nth-child(1) { animation-delay: 0s; }
.thinking-dots span:nth-child(2) { animation-delay: 0.2s; }
.thinking-dots span:nth-child(3) { animation-delay: 0.4s; }

.thinking-text {
  font-size: 13px;
  color: #86909c;
  animation: fade-pulse 1.5s ease-in-out infinite;
}

/* ── 流式光标 ───────────────────────────────────────────────────── */
.streaming-cursor {
  display: inline;
  color: #4f46e5;
  animation: cursor-blink 0.8s step-end infinite;
  margin-left: 1px;
  font-weight: 300;
}

/* ── 动画 ───────────────────────────────────────────────────────── */
@keyframes dot-bounce {
  0%, 80%, 100% { transform: translateY(0); opacity: 0.4; }
  40% { transform: translateY(-6px); opacity: 1; }
}

@keyframes fade-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

@keyframes cursor-blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

/* ── Markdown 内容样式 ───────────────────────────────────────────── */
.message-body :deep(h2),
.message-body :deep(h3),
.message-body :deep(h4) {
  margin: 12px 0 6px;
  font-weight: 600;
  line-height: 1.4;
}
.message-body :deep(h2) { font-size: 16px; }
.message-body :deep(h3) { font-size: 15px; }
.message-body :deep(h4) { font-size: 14px; }

.message-body :deep(ul),
.message-body :deep(ol) {
  margin: 6px 0;
  padding-left: 20px;
}
.message-body :deep(li) {
  margin: 2px 0;
  line-height: 1.5;
}

.message-body :deep(pre) {
  margin: 8px 0;
  padding: 12px;
  background: #f8f9fa;
  border-radius: 8px;
  overflow-x: auto;
}
.message-body :deep(pre code) {
  font-size: 12px;
  line-height: 1.5;
  background: none;
  padding: 0;
}

.message-body :deep(code) {
  padding: 1px 4px;
  border-radius: 4px;
  background: #f2f3f5;
  font-size: 12px;
  font-family: 'SF Mono', 'Monaco', 'Menlo', monospace;
}

.message-body :deep(a) {
  color: #4f46e5;
  text-decoration: none;
}
.message-body :deep(a:hover) {
  text-decoration: underline;
}

.message-body :deep(strong) {
  font-weight: 600;
}
</style>
