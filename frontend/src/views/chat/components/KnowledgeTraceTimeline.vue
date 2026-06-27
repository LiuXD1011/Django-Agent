<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from '../../../api'

const props = defineProps<{ knowledgeId: string; active?: boolean }>()

interface Span {
  id: string
  parent_id: string
  name: string
  kind: string
  status: string
  input: Record<string, any>
  output: Record<string, any>
  error_message: string
  started_at: string | null
  finished_at: string | null
  duration_ms: number
}

const spans = ref<Span[]>([])
const loading = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null

const stageOrder = ['docreader', 'chunking', 'embedding', 'multimodal', 'postprocess']
const stageLabels: Record<string, string> = {
  docreader: '文件读取',
  chunking: '文本分块',
  embedding: '向量索引',
  multimodal: '图谱提取',
  postprocess: '后处理',
}

const rootSpan = computed(() => spans.value.find(s => s.kind === 'root'))
const stageSpans = computed(() => {
  const stages = spans.value.filter(s => s.kind === 'stage')
  return stageOrder
    .map(name => stages.find(s => s.name === name))
    .filter(Boolean) as Span[]
})

const isActive = computed(() => {
  return rootSpan.value?.status === 'running' || stageSpans.value.some(s => s.status === 'running')
})

const totalTime = computed(() => {
  if (!rootSpan.value?.started_at) return 0
  const end = rootSpan.value.finished_at ? new Date(rootSpan.value.finished_at).getTime() : Date.now()
  return end - new Date(rootSpan.value.started_at).getTime()
})

function stageProgress(span: Span): number {
  if (span.status === 'done') return 100
  if (span.status === 'failed' || span.status === 'skipped') return 100
  if (!span.started_at || !totalTime.value) return 0
  const elapsed = Date.now() - new Date(span.started_at).getTime()
  return Math.min(95, (elapsed / totalTime.value) * 100)
}

function stageLeft(span: Span): number {
  if (!rootSpan.value?.started_at || !totalTime.value) return 0
  const offset = new Date(span.started_at!).getTime() - new Date(rootSpan.value.started_at).getTime()
  return (offset / totalTime.value) * 100
}

function stageWidth(span: Span): number {
  if (!totalTime.value) return 0
  const duration = span.duration_ms || (span.status === 'running' ? Date.now() - new Date(span.started_at!).getTime() : 0)
  return Math.max(2, (duration / totalTime.value) * 100)
}

function statusIcon(status: string): string {
  const icons: Record<string, string> = { done: '✅', failed: '❌', running: '⚙️', pending: '⏳', skipped: '⏭️', cancelled: '🚫' }
  return icons[status] || '❓'
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60000).toFixed(1)}min`
}

async function loadSpans() {
  if (!props.knowledgeId) return
  loading.value = true
  try {
    const res: any = await api.getKnowledgeSpans(props.knowledgeId)
    spans.value = res.data?.items || []
  } catch {
    spans.value = []
  } finally {
    loading.value = false
  }
}

function startPolling() {
  stopPolling()
  loadSpans()
  pollTimer = setInterval(loadSpans, 2000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

watch(() => props.active, (active) => {
  if (active) startPolling()
  else stopPolling()
}, { immediate: true })

watch(isActive, (active) => {
  if (!active) stopPolling()
})

onMounted(() => { if (props.active) startPolling() })
onUnmounted(stopPolling)
</script>

<template>
  <div class="trace-timeline" v-if="spans.length">
    <!-- 标题 -->
    <div class="trace-header">
      <span class="trace-title">解析进度</span>
      <span v-if="isActive" class="trace-live">LIVE</span>
      <span v-if="rootSpan?.duration_ms" class="trace-duration">{{ formatDuration(rootSpan.duration_ms) }}</span>
    </div>

    <!-- 瀑布图 -->
    <div class="trace-waterfall">
      <div v-for="span in stageSpans" :key="span.id" class="trace-row">
        <div class="trace-label">
          <span class="trace-icon">{{ statusIcon(span.status) }}</span>
          <span class="trace-name">{{ stageLabels[span.name] || span.name }}</span>
        </div>
        <div class="trace-bar-container">
          <div
            class="trace-bar"
            :class="[`trace-bar--${span.status}`]"
            :style="{ left: `${stageLeft(span)}%`, width: `${stageWidth(span)}%` }"
          >
            <span v-if="span.duration_ms" class="trace-bar-time">{{ formatDuration(span.duration_ms) }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 错误信息 -->
    <div v-if="stageSpans.some(s => s.error_message)" class="trace-errors">
      <div v-for="span in stageSpans.filter(s => s.error_message)" :key="span.id" class="trace-error">
        <strong>{{ stageLabels[span.name] || span.name }}:</strong> {{ span.error_message }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.trace-timeline {
  padding: 12px;
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  background: #fafbfc;
  margin: 8px 0;
}

.trace-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.trace-title {
  font-weight: 600;
  font-size: 13px;
  color: #1d2129;
}

.trace-live {
  padding: 1px 6px;
  border-radius: 4px;
  background: #00b42a;
  color: #fff;
  font-size: 10px;
  font-weight: 600;
  animation: live-pulse 1.5s ease-in-out infinite;
}

.trace-duration {
  margin-left: auto;
  color: #86909c;
  font-size: 12px;
}

/* 瀑布图 */
.trace-waterfall {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.trace-row {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 24px;
}

.trace-label {
  display: flex;
  align-items: center;
  gap: 4px;
  width: 80px;
  flex-shrink: 0;
  font-size: 11px;
}

.trace-icon {
  font-size: 10px;
}

.trace-name {
  color: #4e5969;
  white-space: nowrap;
}

.trace-bar-container {
  flex: 1;
  height: 16px;
  background: #f2f3f5;
  border-radius: 4px;
  position: relative;
  overflow: hidden;
}

.trace-bar {
  position: absolute;
  top: 0;
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s ease;
  display: flex;
  align-items: center;
  padding: 0 4px;
  min-width: 2px;
}

.trace-bar--done {
  background: #00b42a;
}

.trace-bar--running {
  background: #4f46e5;
  animation: bar-shimmer 1.5s ease-in-out infinite;
}

.trace-bar--failed {
  background: #f53f3f;
}

.trace-bar--pending {
  background: #c9cdd4;
}

.trace-bar--skipped {
  background: #86909c;
  opacity: 0.5;
}

.trace-bar-time {
  color: #fff;
  font-size: 9px;
  font-weight: 600;
  white-space: nowrap;
}

/* 错误 */
.trace-errors {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid #e8e8e8;
}

.trace-error {
  font-size: 11px;
  color: #f53f3f;
  padding: 2px 0;
}

@keyframes live-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

@keyframes bar-shimmer {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}
</style>
