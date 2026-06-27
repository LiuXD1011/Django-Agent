<script setup lang="ts">
import { computed } from 'vue'
import CitationList from './CitationList.vue'
import RagProgress from './RagProgress.vue'
import ToolResultRenderer from './ToolResultRenderer.vue'

const props = defineProps<{ message: any; loading?: boolean }>()

const isThinking = computed(() => props.loading && !props.message?.content?.trim())
const isStreaming = computed(() => props.loading && props.message?.content?.trim() && !props.message?.is_completed)
const toolCalls = computed(() => props.message?.agent_tool_calls || [])

/** 简易 markdown → HTML（处理常用语法） */
function renderMarkdown(text: string): string {
  if (!text) return ''
  let html = text
    // 转义 HTML
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    // 标题
    .replace(/^### (.+)$/gm, '<h4>$1</h4>')
    .replace(/^## (.+)$/gm, '<h3>$1</h3>')
    .replace(/^# (.+)$/gm, '<h2>$1</h2>')
    // 粗体 + 斜体
    .replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    // 行内代码
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    // 无序列表
    .replace(/^[*-] (.+)$/gm, '<li>$1</li>')
    // 有序列表
    .replace(/^\d+\. (.+)$/gm, '<li>$1</li>')
    // 换行
    .replace(/\n\n/g, '</p><p>')
    .replace(/\n/g, '<br>')
  return `<p>${html}</p>`
}

const renderedContent = computed(() => renderMarkdown(props.message?.content || ''))

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
      <div v-for="(tc, idx) in toolCalls" :key="idx" class="tool-call-item" :class="{ running: tc.status === 'running', done: tc.status === 'done' }">
        <div class="tool-call-header">
          <span class="tool-call-icon">{{ tc.status === 'running' ? '⚙️' : '✅' }}</span>
          <span class="tool-call-name">{{ tc.name }}</span>
          <span v-if="tc.duration_ms" class="tool-call-time">{{ tc.duration_ms }}ms</span>
        </div>
        <div v-if="tc.status === 'done'" class="tool-call-output">
          <ToolResultRenderer :name="tc.name" :output="tc.output || ''" :error="tc.error" :duration-ms="tc.duration_ms" />
        </div>
      </div>
    </div>

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

.tool-call-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  font-size: 12px;
  font-weight: 500;
}

.tool-call-icon {
  font-size: 12px;
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
  max-height: 120px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
  font-family: monospace;
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
</style>
