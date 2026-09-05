<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from '../../../api'
import { renderMarkdownLite } from '../../../utils/markdown-lite.mjs'

interface ToolRecord {
  tool_call_id: string
  name: string
  argument_keys: string[]
  output_excerpt: string
  error: string
  duration_ms: number | null
  started_at: string | null
  ended_at: string | null
  schema?: ToolSchema | null
}

interface StepRecord {
  iteration: number
  thought: string
  tools: ToolRecord[]
  llm: {
    duration_ms?: number
    model?: string
    usage?: { prompt_tokens: number; completion_tokens: number; cached_tokens?: number; reasoning_tokens?: number }
  }
  started_at: string | null
  ended_at: string | null
}

interface ToolSchema {
  name: string
  description: string
  required: string[]
  properties: Record<string, string>
}

interface TurnRecord {
  request_id: string
  seq_range: [number, number]
  started_at: string | null
  completed_at: string | null
  mode: string
  model_id: string
  stopped_reason: string
  duration_ms: number | null
  error: string
  user: { content: string; images: number; attachments: any[]; mentioned_items: number; channel: string } | null
  assistant: { content: string }
  retrievals: { query: string; kb_count: number; top_k: number | null; count: number | null; intent: string; degradations: string[]; refs: { chunk_id: string; title: string }[] }[]
  steps: StepRecord[]
  actors: { actor_id: string; agent_type: string; event: string; status: string }[]
  request: { model: string; temperature: number | null; tools: string[]; tool_schemas?: Record<string, ToolSchema>; max_iterations: number | null; history_messages: number | null; agent_mode: string } | null
  provider: string
  retries: { attempt: number | null; reason: string; wait_seconds: number | null }[]
  compactions: { before_tokens: number | null; after_tokens: number | null; iteration: number | null }[]
  usage: { prompt_tokens: number; completion_tokens: number; llm_calls: number; total_tokens: number }
}

type RecordFilter = 'all' | 'retrieval' | 'thinking' | 'tool' | 'answer'

const FILTERS: { key: RecordFilter; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'retrieval', label: '检索' },
  { key: 'thinking', label: '思考' },
  { key: 'tool', label: '工具' },
  { key: 'answer', label: '回答' },
]

const props = defineProps<{ sessionId: string }>()

const turns = ref<TurnRecord[]>([])
const loading = ref(false)
const errorText = ref('')
const loadedFor = ref('')
const activeFilter = ref<RecordFilter>('all')
const expanded = ref<Record<string, boolean>>({})
const schemaOpen = ref<Record<string, boolean>>({})

const hasTrajectory = computed(() => turns.value.length > 0)

async function load(sessionId: string) {
  if (!sessionId || loadedFor.value === sessionId) return
  loading.value = true
  errorText.value = ''
  try {
    const res: any = await api.sessionTrajectory(sessionId)
    turns.value = res?.data?.turns || []
    loadedFor.value = sessionId
  } catch (err: any) {
    // axios 拦截器 reject 的是 response.data（{success, message, error}），非 AxiosError
    const status = err?.response?.status
    const notFound = status === 404 || err?.message === 'session not found' || err?.error?.message === 'session not found'
    errorText.value = notFound ? '会话不存在或不可见' : '轨迹加载失败'
    turns.value = []
  } finally {
    loading.value = false
  }
}

watch(() => props.sessionId, (id) => { loadedFor.value = ''; expanded.value = {}; activeFilter.value = 'all'; load(id) }, { immediate: true })

function toggleExpanded(key: string) {
  expanded.value = { ...expanded.value, [key]: !expanded.value[key] }
}

function isExpanded(key: string) {
  return !!expanded.value[key]
}

function toggleSchema(key: string) {
  schemaOpen.value = { ...schemaOpen.value, [key]: !schemaOpen.value[key] }
}

function isSchemaOpen(key: string) {
  return !!schemaOpen.value[key]
}

/** 内容足够长才会被 3 行截断；只有这类记录显示展开指示。 */
function isLong(text: string | null | undefined): boolean {
  if (!text) return false
  return text.length > 160 || text.split('\n').length > 3
}

    /** 折叠态预览：剥离 Markdown 标记（井号标题、星号加粗等）与 Wiki 双链，只留可读文本。 */
function plainPreview(text: string | null | undefined): string {
  if (!text) return ''
  return text
    .replace(/```[\s\S]*?```/g, ' [代码块] ')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, '')
    .replace(/\[\[([^\]|]+)\|([^\]]+)\]\]/g, '$2')
    .replace(/\[\[([^\]]+)\]\]/g, '$1')
    .replace(/\[\[([^\]]*)$/, '$1')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/^>\s?/gm, '')
    .trim()
}

function markdownHtml(text: string | null | undefined): string {
  if (!text) return ''
  try {
    return renderMarkdownLite(text)
  } catch {
    return ''
  }
}

function filterOf(kind: 'retrieval' | 'thinking' | 'tool' | 'answer' | 'other'): boolean {
  if (activeFilter.value === 'all') return true
  return activeFilter.value === kind
}

function formatDuration(ms: number | null | undefined) {
  if (ms === null || ms === undefined) return '—'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function formatClock(iso: string | null) {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleTimeString('zh-CN', { hour12: false })
  } catch {
    return ''
  }
}

/** 时间轴段：用事件真实时间戳把思考/工具映射到轮次时长比例轴上。 */
interface TimelineSegment { kind: 'thinking' | 'tool'; label: string; left: number; width: number; title: string }

function timelineSegments(turn: TurnRecord): TimelineSegment[] {
  if (!turn.started_at || !turn.completed_at) return []
  const start = new Date(turn.started_at).getTime()
  const end = new Date(turn.completed_at).getTime()
  const span = end - start
  if (!Number.isFinite(span) || span <= 0) return []
  const segments: TimelineSegment[] = []
  const push = (kind: 'thinking' | 'tool', label: string, from: string | null, to: string | null, exact: string) => {
    if (!from || !to) return
    const fromMs = new Date(from).getTime()
    const toMs = new Date(to).getTime()
    if (!Number.isFinite(fromMs) || !Number.isFinite(toMs) || toMs <= fromMs) return
    const left = Math.max(0, Math.min(100, ((fromMs - start) / span) * 100))
    const right = Math.max(0, Math.min(100, ((toMs - start) / span) * 100))
    if (right - left < 0.5) return
    segments.push({ kind, label, left, width: right - left, title: exact })
  }
  for (const step of turn.steps) {
    push('thinking', `步骤 ${step.iteration} 思考`, step.started_at, step.ended_at,
      `步骤 ${step.iteration} 思考：${formatClock(step.started_at)} → ${formatClock(step.ended_at)}（${formatDuration(step.llm.duration_ms)}）`)
    for (const tool of step.tools) {
      push('tool', tool.name, tool.started_at, tool.ended_at,
        `${tool.name}：${formatClock(tool.started_at)} → ${formatClock(tool.ended_at)}（${formatDuration(tool.duration_ms)}）`)
    }
  }
  return segments.sort((a, b) => a.left - b.left)
}

const stoppedReasonLabels: Record<string, string> = {
  completed: '正常完成',
  error: '出错',
  cancelled: '已取消',
  degraded: '降级完成',
  stuck: '重复中止',
}

function stoppedLabel(turn: TurnRecord) {
  if (turn.stopped_reason === 'error' && turn.error) return `出错：${turn.error}`
  return stoppedReasonLabels[turn.stopped_reason] || turn.stopped_reason
}
</script>

<template>
  <div class="trajectory-panel" data-testid="trajectory-panel">
    <div v-if="loading" class="trajectory-status">轨迹加载中…</div>
    <div v-else-if="errorText" class="trajectory-status trajectory-error" data-testid="trajectory-error">{{ errorText }}</div>
    <div v-else-if="!hasTrajectory" class="trajectory-status" data-testid="trajectory-empty">该会话还没有轨迹记录。发送一条消息后，这里会展示检索、思考与工具调用的完整过程。</div>

    <template v-else>
      <div class="trajectory-filter" role="group" aria-label="记录过滤" data-testid="trajectory-filter">
        <button
          v-for="f in FILTERS"
          :key="f.key"
          type="button"
          :class="{ active: activeFilter === f.key }"
          :data-testid="`filter-${f.key}`"
          @click="activeFilter = f.key"
        >{{ f.label }}</button>
      </div>

      <section
        v-for="(turn, turnIndex) in turns"
        :key="turn.request_id || turnIndex"
        class="trajectory-turn"
        :data-testid="`trajectory-turn-${turnIndex}`"
      >
        <header class="turn-rule">
          <span class="turn-rule-line" aria-hidden="true" />
          <span class="turn-rule-label">第 {{ turnIndex + 1 }} 轮</span>
          <span class="turn-rule-meta">
            {{ formatClock(turn.started_at) }}
            <template v-if="turn.mode"> · {{ turn.mode === 'agent' ? 'Agent' : 'RAG' }}</template>
          </span>
          <span class="turn-rule-line" aria-hidden="true" />
        </header>

        <!-- 请求上下文（SYSTEM）：调用时的模型/工具清单/轮次上限 -->
        <article v-if="turn.request && filterOf('other')" class="turn-record turn-request" :data-testid="`request-${turnIndex}`">
          <div class="record-head"><span class="record-kind request">REQUEST</span><span class="record-clock">{{ turn.provider || turn.request.model }}</span></div>
          <p class="record-text">
            允许工具 {{ turn.request.tools.length }} 个（{{ turn.request.tools.slice(0, 4).join('、') }}<template v-if="turn.request.tools.length > 4"> 等</template>）
            <template v-if="turn.request.temperature != null"> · temperature {{ turn.request.temperature }}</template>
            <template v-if="turn.request.max_iterations"> · 最多 {{ turn.request.max_iterations }} 轮</template>
            <template v-if="turn.request.history_messages != null"> · 携带历史 {{ turn.request.history_messages }} 条</template>
          </p>
        </article>

        <article
          v-if="turn.user && filterOf('other')"
          class="turn-record turn-user"
          :class="{ expandable: isLong(turn.user.content) }"
          :data-testid="`user-${turnIndex}`"
          @click="isLong(turn.user.content) && toggleExpanded(`u-${turnIndex}`)"
        >
          <div class="record-head">
            <span class="record-kind user">USER</span>
            <span v-if="isLong(turn.user.content)" class="record-chevron" :class="{ open: isExpanded(`u-${turnIndex}`) }" aria-hidden="true">▾</span>
            <span class="record-clock">{{ formatClock(turn.started_at) }}</span>
          </div>
          <p v-if="!isExpanded(`u-${turnIndex}`)" class="record-text" :class="{ clamp: isLong(turn.user.content) }">{{ plainPreview(turn.user.content) }}</p>
          <div v-else class="record-text markdown-lite" data-testid="expanded-content" v-html="markdownHtml(turn.user.content)" />
          <p v-if="turn.user.attachments.length || turn.user.images || turn.user.mentioned_items" class="record-sub">
            <template v-if="turn.user.attachments.length">{{ turn.user.attachments.map((a: any) => a.file_name).join('、') }}</template>
            <template v-if="turn.user.images">{{ turn.user.attachments.length ? ' · ' : '' }}{{ turn.user.images }} 张图片</template>
            <template v-if="turn.user.mentioned_items">{{ turn.user.attachments.length || turn.user.images ? ' · ' : '' }}@{{ turn.user.mentioned_items }} 项引用</template>
          </p>
        </article>

        <template v-for="(r, ri) in turn.retrievals" :key="`r-${turnIndex}-${ri}`">
          <article v-if="filterOf('retrieval')" class="turn-record turn-retrieval" :data-testid="`retrieval-${turnIndex}-${ri}`">
            <div class="record-head"><span class="record-kind retrieval">RETRIEVAL</span><span class="record-clock" /></div>
            <p class="record-text">查询「{{ r.query }}」→ {{ r.count === null ? '检索中' : `${r.count} 条结果` }}<template v-if="r.intent"> · 意图 {{ r.intent }}</template></p>
            <p v-if="r.refs.length" class="record-sub">引用：{{ r.refs.map((ref) => ref.title || ref.chunk_id).join('、') }}</p>
            <p v-if="r.degradations.length" class="record-sub degraded">降级：{{ r.degradations.join('、') }}</p>
          </article>
        </template>

        <template v-for="step in turn.steps" :key="`s-${turnIndex}-${step.iteration}`">
          <article
            v-if="(step.thought || step.llm.duration_ms != null) && filterOf('thinking')"
            class="turn-record turn-thinking"
            :class="{ expandable: isLong(step.thought) }"
            :data-testid="`thinking-${turnIndex}-${step.iteration}`"
            @click="isLong(step.thought) && toggleExpanded(`t-${turnIndex}-${step.iteration}`)"
          >
            <div class="record-head">
              <span class="record-kind thinking">THINKING</span>
              <span class="record-name" v-if="step.llm.usage">
                步骤 {{ step.iteration }} · {{ step.llm.usage.prompt_tokens }}+{{ step.llm.usage.completion_tokens }} tokens
                <template v-if="step.llm.usage.cached_tokens"> · 缓存 {{ step.llm.usage.cached_tokens }}</template>
                <template v-if="step.llm.usage.reasoning_tokens"> · 推理 {{ step.llm.usage.reasoning_tokens }}</template>
              </span>
              <span class="record-name" v-else>步骤 {{ step.iteration }}</span>
              <span v-if="isLong(step.thought)" class="record-chevron" :class="{ open: isExpanded(`t-${turnIndex}-${step.iteration}`) }" aria-hidden="true">▾</span>
              <span class="record-clock">{{ step.llm.duration_ms != null ? formatDuration(step.llm.duration_ms) : '' }}</span>
            </div>
            <p v-if="!isExpanded(`t-${turnIndex}-${step.iteration}`)" class="record-text" :class="{ clamp: isLong(step.thought), 'record-muted': !step.thought }" :data-testid="`thought-preview-${turnIndex}-${step.iteration}`">{{ plainPreview(step.thought) || '（本轮无文本输出，直接调用工具）' }}</p>
            <div v-else class="record-text markdown-lite" data-testid="expanded-content" v-html="markdownHtml(step.thought)" />
          </article>

          <template v-for="tool in step.tools" :key="`t-${turnIndex}-${step.iteration}-${tool.tool_call_id || tool.name}`">
            <article
              v-if="filterOf('tool')"
              class="turn-record turn-tool"
              :class="{ expandable: isLong(tool.output_excerpt) }"
              :data-testid="`tool-${turnIndex}-${tool.name}`"
              @click="isLong(tool.output_excerpt) && toggleExpanded(`tool-${turnIndex}-${tool.tool_call_id}`)"
            >
              <div class="record-head">
                <span class="record-kind tool" :class="{ 'tool-error': tool.error }">TOOL</span>
                <span class="record-name">{{ tool.name }}</span>
                <span v-if="isLong(tool.output_excerpt)" class="record-chevron" :class="{ open: isExpanded(`tool-${turnIndex}-${tool.tool_call_id}`) }" aria-hidden="true">▾</span>
                <span class="record-clock">{{ tool.duration_ms != null ? formatDuration(tool.duration_ms) : '' }}</span>
              </div>
              <p class="record-sub">参数键：{{ tool.argument_keys.length ? tool.argument_keys.join('、') : '（无）' }}</p>
              <p v-if="tool.error" class="record-text tool-error-text">{{ tool.error }}</p>
              <p
                v-else-if="tool.output_excerpt && !isExpanded(`tool-${turnIndex}-${tool.tool_call_id}`)"
                class="record-text"
                :class="{ clamp: isLong(tool.output_excerpt) }"
                :data-testid="`tool-output-${turnIndex}-${tool.name}`"
              >{{ plainPreview(tool.output_excerpt) }}</p>
              <div
                v-else-if="tool.output_excerpt"
                class="record-text"
                data-testid="expanded-content"
              >{{ tool.output_excerpt }}</div>
              <p class="record-sub timing-source" v-if="tool.started_at && tool.ended_at">计时来源：服务端事件时间戳（{{ formatClock(tool.started_at) }} → {{ formatClock(tool.ended_at) }}）</p>
              <template v-if="tool.schema">
                <button class="schema-toggle" type="button" :data-testid="`schema-toggle-${turnIndex}-${tool.name}`" @click.stop="toggleSchema(`${turnIndex}-${tool.tool_call_id}`)">
                  {{ isSchemaOpen(`${turnIndex}-${tool.tool_call_id}`) ? '▾ 调用时 Schema' : '▸ 调用时 Schema' }}
                </button>
                <pre v-if="isSchemaOpen(`${turnIndex}-${tool.tool_call_id}`)" class="schema-block" :data-testid="`schema-${turnIndex}-${tool.name}`">{{ JSON.stringify(tool.schema, null, 2) }}</pre>
              </template>
            </article>
          </template>
        </template>

        <article v-for="actor in turn.actors" :key="`a-${turnIndex}-${actor.actor_id}-${actor.event}`" class="turn-record turn-actor">
          <div class="record-head"><span class="record-kind actor">ACTOR</span><span class="record-clock" /></div>
          <p class="record-text">{{ actor.agent_type }}（{{ actor.actor_id }}）{{ actor.event }} · {{ actor.status }}</p>
        </article>

        <article v-for="(c, ci) in turn.compactions" :key="`c-${turnIndex}-${ci}`" class="turn-record turn-compaction" :data-testid="`compaction-${turnIndex}-${ci}`">
          <div class="record-head"><span class="record-kind compaction">CONTEXT</span><span class="record-clock" /></div>
          <p class="record-text">上下文压缩：{{ c.before_tokens }} → {{ c.after_tokens }} tokens<template v-if="c.iteration">（步骤 {{ c.iteration }}）</template></p>
        </article>

        <article
          v-if="(turn.assistant.content || turn.error) && filterOf('answer')"
          class="turn-record turn-assistant"
          :class="{ expandable: isLong(turn.assistant.content) }"
          :data-testid="`assistant-${turnIndex}`"
          @click="isLong(turn.assistant.content) && toggleExpanded(`a-${turnIndex}`)"
        >
          <div class="record-head">
            <span class="record-kind assistant">ASSISTANT</span>
            <span v-if="isLong(turn.assistant.content)" class="record-chevron" :class="{ open: isExpanded(`a-${turnIndex}`) }" aria-hidden="true">▾</span>
            <span class="record-clock">{{ formatClock(turn.completed_at) }}</span>
          </div>
          <p
            v-if="!isExpanded(`a-${turnIndex}`)"
            class="record-text"
            :class="{ clamp: isLong(turn.assistant.content) }"
            :data-testid="`answer-${turnIndex}`"
          >{{ plainPreview(turn.assistant.content || turn.error) }}</p>
          <div v-else-if="turn.assistant.content" class="record-text markdown-lite" data-testid="expanded-content" v-html="markdownHtml(turn.assistant.content)" />
          <p v-else class="record-text tool-error-text">{{ turn.error }}</p>
        </article>

        <div v-if="activeFilter === 'all' && timelineSegments(turn).length" class="turn-timeline" :data-testid="`timeline-${turnIndex}`">
          <span class="timeline-label">时间轴</span>
          <div class="timeline-track">
            <div
              v-for="(seg, si) in timelineSegments(turn)"
              :key="`seg-${turnIndex}-${si}`"
              class="timeline-seg"
              :class="seg.kind"
              :style="{ left: `${seg.left}%`, width: `${seg.width}%` }"
              :title="seg.title"
            />
          </div>
        </div>

        <footer class="turn-footer" :data-testid="`turn-footer-${turnIndex}`">
          <span :class="{ 'footer-error': turn.stopped_reason !== 'completed' }">{{ stoppedLabel(turn) }}</span>
          <span v-if="turn.model_id"> · {{ turn.model_id }}</span>
          <span> · 总耗时 {{ formatDuration(turn.duration_ms) }}</span>
          <span v-if="turn.usage.total_tokens"> · {{ turn.usage.prompt_tokens }}+{{ turn.usage.completion_tokens }} tokens（{{ turn.usage.llm_calls }} 次调用）</span>
          <span v-if="turn.retries.length" class="footer-warn"> · LLM 重试 {{ turn.retries.length }} 次</span>
        </footer>
      </section>
    </template>
  </div>
</template>

<style scoped>
.trajectory-panel {
  flex: 1;
  overflow-y: auto;
  padding: 12px 20px 32px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.trajectory-status {
  margin: 48px auto;
  color: var(--td-text-color-secondary, #666);
  font-size: 14px;
  max-width: 420px;
  text-align: center;
}

.trajectory-error { color: var(--td-error-color, #d54941); }

.trajectory-filter { display: flex; gap: 6px; padding: 2px 0 6px; }

.trajectory-filter button {
  border: 1px solid var(--td-component-stroke, #e7e7e7);
  background: transparent;
  color: var(--td-text-color-secondary, #666);
  border-radius: 999px;
  padding: 2px 12px;
  font-size: 12px;
  cursor: pointer;
}

.trajectory-filter button.active {
  background: var(--td-brand-color, #2f6bff);
  border-color: var(--td-brand-color, #2f6bff);
  color: #fff;
}

.trajectory-turn { display: flex; flex-direction: column; gap: 8px; }

.turn-rule { display: flex; align-items: center; gap: 10px; margin: 14px 0 4px; }

.turn-rule-line { flex: 1; height: 3px; background: var(--td-component-stroke, #e7e7e7); border-radius: 2px; }

.turn-rule-label { font-size: 13px; font-weight: 600; color: var(--td-text-color-primary, #1a1a1a); }

.turn-rule-meta { font-size: 12px; color: var(--td-text-color-placeholder, #999); }

.turn-record {
  border: 1px solid var(--td-component-stroke, #e7e7e7);
  border-radius: 10px;
  padding: 10px 14px;
  background: var(--td-bg-color-container, #fff);
}

.turn-record.expandable { cursor: pointer; }

.turn-record.expandable:hover { border-color: var(--td-brand-color-light, #b5c7ff); }

.turn-user { border-left: 4px solid #4b9bfd; }
.turn-request { border-left: 4px solid #8c8c8c; background: var(--td-bg-color-secondarycontainer, #f7f8fa); }
.turn-retrieval { border-left: 4px solid #8f8cf5; }
.turn-thinking { border-left: 4px solid #d4b106; }
.turn-tool { border-left: 4px solid #2ba471; }
.turn-actor { border-left: 4px solid #ed7b2f; }
.turn-compaction { border-left: 4px solid #14c0cc; }
.turn-assistant { border-left: 4px solid #d54941; }

.record-head { display: flex; align-items: baseline; gap: 8px; }

.record-kind { font-size: 11px; font-weight: 700; letter-spacing: 0.5px; color: var(--td-text-color-placeholder, #999); }

.record-name { font-size: 12px; font-weight: 600; color: var(--td-text-color-secondary, #666); }

.record-chevron { font-size: 10px; color: var(--td-text-color-placeholder, #999); transition: transform 0.15s ease; }

.record-chevron.open { transform: rotate(180deg); }

.record-clock { margin-left: auto; font-size: 12px; color: var(--td-text-color-placeholder, #999); }

.record-text { margin: 6px 0 0; font-size: 13px; line-height: 1.55; color: var(--td-text-color-primary, #1a1a1a); white-space: pre-wrap; word-break: break-word; }

.record-text.clamp { display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }

.record-text.record-muted { color: var(--td-text-color-placeholder, #999); font-style: italic; }

.record-text.markdown-lite { white-space: normal; }

.record-text :deep(h1),
.record-text :deep(h2),
.record-text :deep(h3) { margin: 8px 0 4px; font-size: 14px; }

.record-text :deep(p) { margin: 4px 0; }

.record-text :deep(pre) { margin: 6px 0; padding: 8px; border-radius: 6px; overflow-x: auto; background: var(--td-bg-color-secondarycontainer, #f7f8fa); font-size: 12px; }

.record-text :deep(code) { font-size: 12px; }

.record-text :deep(ul),
.record-text :deep(ol) { margin: 4px 0; padding-left: 20px; }

.record-text :deep(table) { border-collapse: collapse; margin: 6px 0; font-size: 12px; }

.record-text :deep(th),
.record-text :deep(td) { border: 1px solid var(--td-component-stroke, #e7e7e7); padding: 4px 8px; }

.record-text.tool-error-text { color: var(--td-error-color, #d54941); }

.record-sub { margin: 6px 0 0; font-size: 12px; color: var(--td-text-color-secondary, #666); }

.record-sub.degraded { color: var(--td-warning-color, #e37318); }

.timing-source { color: var(--td-text-color-placeholder, #999); }

.schema-toggle {
  margin-top: 6px;
  border: none;
  background: transparent;
  color: var(--td-text-color-secondary, #666);
  font-size: 12px;
  cursor: pointer;
  padding: 0;
}

.schema-block {
  margin: 6px 0 0;
  padding: 8px;
  border-radius: 6px;
  background: var(--td-bg-color-secondarycontainer, #f7f8fa);
  font-size: 11px;
  line-height: 1.5;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

.turn-timeline { display: flex; align-items: center; gap: 10px; margin-top: 2px; padding: 0 2px; }

.timeline-label { font-size: 11px; color: var(--td-text-color-placeholder, #999); white-space: nowrap; }

.timeline-track { position: relative; flex: 1; height: 10px; border-radius: 5px; background: var(--td-component-stroke, #ececec); overflow: hidden; }

.timeline-seg { position: absolute; top: 0; bottom: 0; border-radius: 3px; }

.timeline-seg.thinking { background: #d4b106; }

.timeline-seg.tool { background: #2ba471; }

.turn-footer { margin-top: 2px; padding: 0 2px; font-size: 12px; color: var(--td-text-color-placeholder, #999); }

.footer-error { color: var(--td-error-color, #d54941); }

.footer-warn { color: var(--td-warning-color, #e37318); }
</style>
