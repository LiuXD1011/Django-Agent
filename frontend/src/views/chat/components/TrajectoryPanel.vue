<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from '../../../api'
import { renderMarkdownLite } from '../../../utils/markdown-lite.mjs'

interface ToolRecord {
  tool_call_id: string
  name: string
  argument_keys: string[]
  /** 低敏白名单参数的取值（非白名单参数不出现在此映射中） */
  arguments?: Record<string, string>
  output_excerpt: string
  error: string
  duration_ms: number | null
  started_at: string | null
  ended_at: string | null
  schema?: ToolSchema | null
  meta?: Record<string, any>
}

interface StepRecord {
  iteration: number
  /** 子代理归组键；主 Agent 步骤为空 */
  actor_id?: string
  agent_type?: string
  thought: string
  /** 思考模型的推理文本（reasoning_content）；非思考模型为空，回退显示 thought */
  reasoning?: string
  tools: ToolRecord[]
  llm: {
    duration_ms?: number
    model?: string
    usage?: { prompt_tokens: number; completion_tokens: number; cached_tokens?: number; reasoning_tokens?: number }
    finish_reason?: string
    /** 模型层降级信息（主模型失败切换备用模型） */
    degradation?: { from_model?: string; to_model?: string; reason?: string } | null
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

interface ActorRecord {
  actor_id: string
  agent_type: string
  event: string
  status: string
  input_prompt?: string
  output_excerpt?: string
  duration_ms?: number | null
  error?: string
  tool_calls?: number
  usage?: { prompt_tokens: number; completion_tokens: number; llm_calls: number }
}

interface TurnRecord {
  request_id: string
  seq_range: [number, number]
  started_at: string | null
  completed_at: string | null
  mode: string
  model_id: string
  stopped_reason: string
  /** 无终结事件的轮次：进程中断或仍在生成 */
  interrupted?: boolean
  duration_ms: number | null
  error: string
  langfuse_trace_id?: string
  user: { content: string; images: number; attachments: any[]; mentioned_items: number; channel: string } | null
  assistant: { content: string }
  retrievals: { query: string; kb_count: number; top_k: number | null; count: number | null; intent: string; degradations: string[]; refs: { chunk_id: string; title: string }[] }[]
  steps: StepRecord[]
  actors: ActorRecord[]
  request: { model: string; temperature: number | null; tools: string[]; tool_schemas?: Record<string, ToolSchema>; max_iterations: number | null; history_messages: number | null; agent_mode: string } | null
  provider: string
  retries: { attempt: number | null; reason: string; wait_seconds: number | null; model?: string; fallback_to?: string; stage?: string }[]
  compactions: { before_tokens: number | null; after_tokens: number | null; iteration: number | null; trigger?: string; actor_id?: string }[]
  maintenance?: { step: string; success: boolean; duration_ms: number | null; error: string }[]
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

/** THINKING 记录正文：思考模型优先展示推理文本，非思考模型回退到可见文本（thought） */
function stepDisplayText(step: StepRecord): string {
  return step.reasoning || step.thought || ''
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

/** 时间轴（对齐 deepseek-harness timeline.ts 的实现方式）：
 *  - span 终点一律是计算值 startedAt + duration，绝不用"结束事件时间戳"做终点
 *    （结束事件的落库时间在并发下有锁等待漂移，会导致宽度与上报时长矛盾）；
 *  - 三种投影模式：
 *      sequence（默认）—— 等宽序列：每条记录占一个等宽槽位，完全不看时间，
 *                          永远没有空窗与漂移；
 *      duration —— 真实时长 + 压缩空闲：宽度=时长，span 之间的空窗从后续
 *                  坐标中扣除（紧凑排列）；
 *      clock —— 会话墙钟：完全按事件时间戳定位（供对比）。
 *  - 三泳道：输入（用户/上下文/请求）、模型（思考与最终回答）、工具（工具与子 Agent）。 */
interface TimelineSegment { lane: 0 | 1 | 2; kind: string; label: string; left: number; width: number; title: string }
type TimelineMode = 'sequence' | 'duration' | 'clock'

interface RawSpan { lane: 0 | 1 | 2; kind: string; label: string; startMs: number; durMs: number; title: string }

function collectSpans(turn: TurnRecord): RawSpan[] {
  const spans: RawSpan[] = []
  const moment = (iso: string | null | undefined, label: string, lane: 0 | 1 | 2) => {
    if (!iso) return
    const t = new Date(iso).getTime()
    if (Number.isFinite(t)) spans.push({ lane, kind: label, label, startMs: t, durMs: 0, title: `${label} ${formatClock(iso)}` })
  }
  moment(turn.started_at, 'USER', 0)
  if (turn.request) moment(turn.started_at, 'REQUEST', 0)
  for (const r of turn.retrievals) moment(turn.started_at, 'CONTEXT', 0)
  for (const step of turn.steps) {
    const started = step.started_at ? new Date(step.started_at).getTime() : NaN
    const dur = step.llm.duration_ms
    if (Number.isFinite(started) && typeof dur === 'number' && dur > 0) {
      spans.push({
        lane: 1,
        kind: 'THINKING',
        label: `步骤 ${step.iteration}`,
        startMs: started,
        durMs: dur,
        title: `步骤 ${step.iteration} 思考：${formatDuration(dur)}（引擎单调时钟）`,
      })
    }
    for (const tool of step.tools) {
      const ts = tool.started_at ? new Date(tool.started_at).getTime() : NaN
      const tdur = tool.duration_ms
      if (Number.isFinite(ts) && typeof tdur === 'number' && tdur > 0) {
        spans.push({
          lane: 2,
          kind: 'TOOL',
          label: tool.name,
          startMs: ts,
          durMs: tdur,
          title: `${tool.name}：${formatDuration(tdur)}`,
        })
      }
    }
  }
  // 子 Agent 是执行类记录 → 工具泳道；最终回答是产出 → 模型泳道末尾。
  // 两者都是零时长时刻标记，输入泳道只保留用户/上下文/请求。
  for (const a of turn.actors) moment(turn.completed_at, `ACTOR ${a.agent_type}`, 2)
  if (turn.assistant.content) moment(turn.completed_at, 'ASSISTANT', 1)
  return spans
}

function timelineModel(turn: TurnRecord, mode: TimelineMode): { lanes: TimelineSegment[][]; windowLabel: string } | null {
  // 三种模式使用同一份记录集合：零时长时刻记录（用户/上下文/回答等）在
  // 时长/时钟模式下渲染为最小宽度刻度，避免切模式时记录凭空消失。
  const spans = collectSpans(turn)
  if (!spans.length) return null

  let projected: { span: RawSpan; fromMs: number; toMs: number }[]
  if (mode === 'sequence') {
    // 等宽序列：按开始顺序每条记录占一个等宽槽位
    const ordered = [...spans].sort((a, b) => a.startMs - b.startMs)
    projected = ordered.map((span, index) => ({ span, fromMs: index, toMs: index + 1 }))
  } else {
    // duration / clock：起点=startedAt，宽度=上报时长
    projected = spans.map(span => ({ span, fromMs: span.startMs, toMs: span.startMs + span.durMs }))
    if (mode === 'duration') {
      // 压缩空闲：span 之间的空窗从后续 span 坐标中扣除（紧凑排列）
      const byStart = [...projected].sort((a, b) => a.fromMs - b.fromMs || a.toMs - b.toMs)
      const offsets = new Map<typeof byStart[number], number>()
      let removedIdle = 0
      let coveredUntil: number | null = null
      for (const item of byStart) {
        if (coveredUntil !== null && item.fromMs > coveredUntil) removedIdle += item.fromMs - coveredUntil
        offsets.set(item, removedIdle)
        coveredUntil = coveredUntil === null ? item.toMs : Math.max(coveredUntil, item.toMs)
      }
      projected = byStart.map(item => {
        const offset = offsets.get(item) ?? 0
        return { span: item.span, fromMs: item.fromMs - offset, toMs: item.toMs - offset }
      })
    }
  }

  const fromValues = projected.map(p => p.fromMs)
  const toValues = projected.map(p => p.toMs)
  const min = Math.min(...fromValues)
  const max = Math.max(...toValues)
  const range = max - min
  if (!Number.isFinite(range) || range <= 0) return null

  // 零时长时刻记录的最小可视宽度（%），保证切模式时记录仍然可见
  const MIN_TICK_PERCENT = 0.8
  const lanes: TimelineSegment[][] = [[], [], []]
  for (const { span, fromMs, toMs } of projected) {
    let left = ((fromMs - min) / range) * 100
    let width = ((toMs - fromMs) / range) * 100
    if (width < MIN_TICK_PERCENT) {
      // 右边界不越界：贴近 100% 时向左对齐
      left = Math.min(left, 100 - MIN_TICK_PERCENT)
      width = MIN_TICK_PERCENT
    }
    lanes[span.lane].push({ lane: span.lane, kind: span.kind, label: span.label, left, width, title: span.title })
  }
  return { lanes, windowLabel: mode === 'sequence' ? `${spans.length} 条记录` : formatDuration(range) }
}

const timelineMode = ref<TimelineMode>('sequence')
const TIMELINE_MODES: { key: TimelineMode; label: string }[] = [
  { key: 'sequence', label: '序列' },
  { key: 'duration', label: '时长' },
  { key: 'clock', label: '时钟' },
]
function cycleTimelineMode() {
  const index = TIMELINE_MODES.findIndex(m => m.key === timelineMode.value)
  timelineMode.value = TIMELINE_MODES[(index + 1) % TIMELINE_MODES.length].key
}
function timelineLanes(turn: TurnRecord) {
  return timelineModel(turn, timelineMode.value)
}

const stoppedReasonLabels: Record<string, string> = {
  completed: '正常完成',
  error: '出错',
  cancelled: '已取消',
  degraded: '降级完成',
  stuck: '重复中止',
  max_iterations: '达到最大轮数',
}

function stoppedLabel(turn: TurnRecord) {
  if (turn.stopped_reason === 'error' && turn.error) return `出错：${turn.error}`
  if (turn.stopped_reason) return stoppedReasonLabels[turn.stopped_reason] || turn.stopped_reason
  // 无终结事件：进程崩溃或轮次仍在生成
  return turn.interrupted ? '中断（无终结事件）' : ''
}

/** 步骤的折叠键 / testid：主步骤保持历史格式（thinking-<turn>-<n>），子代理步骤插入 actor_id 保证唯一 */
function stepKey(turnIndex: number, step: StepRecord): string {
  return step.actor_id ? `t-${turnIndex}-${step.actor_id}-${step.iteration}` : `t-${turnIndex}-${step.iteration}`
}

/** 子代理步骤的展示前缀（主 Agent 步骤无前缀） */
function stepLabelPrefix(step: StepRecord): string {
  return step.actor_id ? `${step.agent_type || 'subagent'}（${step.actor_id}） · ` : ''
}

/** 工具白名单参数的取值摘要 */
function toolArgumentsText(tool: ToolRecord): string {
  const entries = Object.entries(tool.arguments || {}).filter(([, v]) => v !== '')
  if (!entries.length) return ''
  return entries.map(([k, v]) => `${k}=${v}`).join(' · ')
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

        <template v-for="step in turn.steps" :key="`s-${turnIndex}-${step.actor_id || 'main'}-${step.iteration}`">
          <article
            v-if="(stepDisplayText(step) || step.llm.duration_ms != null) && filterOf('thinking')"
            class="turn-record turn-thinking"
            :class="{ expandable: isLong(stepDisplayText(step)) }"
            :data-testid="step.actor_id ? `thinking-${turnIndex}-${step.actor_id}-${step.iteration}` : `thinking-${turnIndex}-${step.iteration}`"
            @click="isLong(stepDisplayText(step)) && toggleExpanded(stepKey(turnIndex, step))"
          >
            <div class="record-head">
              <span class="record-kind thinking">THINKING</span>
              <span class="record-name" v-if="step.llm.usage">
                {{ stepLabelPrefix(step) }}步骤 {{ step.iteration }} · {{ step.llm.usage.prompt_tokens }}+{{ step.llm.usage.completion_tokens }} tokens
                <template v-if="step.llm.usage.cached_tokens"> · 缓存 {{ step.llm.usage.cached_tokens }}</template>
                <template v-if="step.llm.usage.reasoning_tokens"> · 推理 {{ step.llm.usage.reasoning_tokens }}</template>
              </span>
              <span class="record-name" v-else>{{ stepLabelPrefix(step) }}步骤 {{ step.iteration }}</span>
              <span v-if="isLong(stepDisplayText(step))" class="record-chevron" :class="{ open: isExpanded(stepKey(turnIndex, step)) }" aria-hidden="true">▾</span>
              <span class="record-clock">{{ step.llm.duration_ms != null ? formatDuration(step.llm.duration_ms) : '' }}</span>
            </div>
            <p v-if="!isExpanded(stepKey(turnIndex, step))" class="record-text" :class="{ clamp: isLong(stepDisplayText(step)), 'record-muted': !stepDisplayText(step) }" :data-testid="`thought-preview-${turnIndex}-${step.iteration}`">{{ plainPreview(stepDisplayText(step)) || '（本轮无文本输出，直接调用工具）' }}</p>
            <div v-else class="record-text markdown-lite" data-testid="expanded-content" v-html="markdownHtml(stepDisplayText(step))" />
            <p v-if="step.llm.finish_reason" class="record-sub">finish_reason：{{ step.llm.finish_reason }}</p>
            <p v-if="step.llm.degradation" class="record-sub degraded">模型降级：{{ step.llm.degradation.from_model }} → {{ step.llm.degradation.to_model }}（{{ step.llm.degradation.reason }}）</p>
            <p class="record-sub timing-source" v-if="step.started_at && step.ended_at && step.llm.duration_ms != null">计时来源：引擎单调时钟（时长 {{ formatDuration(step.llm.duration_ms) }}）</p>
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
              <p v-if="toolArgumentsText(tool)" class="record-sub">参数值：{{ toolArgumentsText(tool) }}</p>
              <p v-if="tool.meta && tool.meta.count != null" class="record-sub">命中 {{ tool.meta.count }} 条<template v-if="tool.meta.chunk_ids && tool.meta.chunk_ids.length">（{{ tool.meta.chunk_ids.join('、') }}）</template></p>
              <p v-if="tool.meta && tool.meta.error_type" class="record-sub degraded">
                错误类型：{{ tool.meta.error_type }}<template v-if="tool.meta.retryable != null"> · 可重试：{{ tool.meta.retryable ? '是' : '否' }}</template><template v-if="tool.meta.failed_fields && tool.meta.failed_fields.length"> · 失败字段：{{ tool.meta.failed_fields.join('、') }}</template>
              </p>
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

        <article v-for="actor in turn.actors" :key="`a-${turnIndex}-${actor.actor_id}`" class="turn-record turn-actor" :data-testid="`actor-${turnIndex}-${actor.actor_id}`">
          <div class="record-head"><span class="record-kind actor">ACTOR</span><span class="record-clock">{{ actor.duration_ms != null ? formatDuration(actor.duration_ms) : '' }}</span></div>
          <p class="record-text">{{ actor.agent_type }}（{{ actor.actor_id }}）{{ actor.event }} · {{ actor.status }}</p>
          <p v-if="actor.input_prompt" class="record-sub">委派：{{ actor.input_prompt }}</p>
          <p v-if="actor.output_excerpt" class="record-sub">产出：{{ actor.output_excerpt }}</p>
          <p v-if="actor.error" class="record-sub degraded">错误：{{ actor.error }}</p>
          <p v-if="actor.tool_calls || (actor.usage && actor.usage.llm_calls)" class="record-sub">
            <template v-if="actor.tool_calls">工具调用 {{ actor.tool_calls }} 次</template>
            <template v-if="actor.usage && actor.usage.llm_calls">{{ actor.tool_calls ? ' · ' : '' }}{{ actor.usage.prompt_tokens }}+{{ actor.usage.completion_tokens }} tokens</template>
          </p>
        </article>

        <article v-for="(mt, mi) in turn.maintenance || []" :key="`mt-${turnIndex}-${mi}`" class="turn-record turn-maintenance" :data-testid="`maintenance-${turnIndex}-${mi}`">
          <div class="record-head"><span class="record-kind compaction">MAINTENANCE</span><span class="record-clock">{{ mt.duration_ms != null ? formatDuration(mt.duration_ms) : '' }}</span></div>
          <p class="record-text">后置维护 · {{ mt.step }}：<template v-if="mt.success">完成</template><template v-else>失败</template><template v-if="mt.error">（{{ mt.error }}）</template></p>
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

        <div v-if="activeFilter === 'all' && timelineLanes(turn)" class="turn-timeline" :data-testid="`timeline-${turnIndex}`">
          <button class="timeline-label" type="button" :data-testid="`timeline-mode-${turnIndex}`" @click="cycleTimelineMode" title="切换时间轴投影模式（序列 / 时长 / 时钟）">
            {{ TIMELINE_MODES.find(m => m.key === timelineMode)?.label }} · {{ timelineLanes(turn)!.windowLabel }}
          </button>
          <div class="timeline-lanes">
            <div v-for="(laneSegments, lane) in timelineLanes(turn)!.lanes" :key="`lane-${turnIndex}-${lane}`" class="timeline-lane" :data-testid="`timeline-lane-${turnIndex}-${lane}`">
              <span class="timeline-lane-label">{{ ['输入', '模型', '工具'][lane] }}</span>
              <div class="timeline-track">
                <div
                  v-for="(seg, si) in laneSegments"
                  :key="`seg-${turnIndex}-${lane}-${si}`"
                  class="timeline-seg"
                  :class="`lane${lane}`"
                  :style="{ left: `${seg.left}%`, width: `${seg.width}%` }"
                  :title="seg.title"
                />
              </div>
            </div>
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
.turn-maintenance { border-left: 4px solid #14c0cc; background: var(--td-bg-color-secondarycontainer, #f7f8fa); }
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

.turn-timeline { display: flex; align-items: flex-start; gap: 10px; margin-top: 2px; padding: 0 2px; }

.timeline-label {
  border: 1px solid var(--td-component-stroke, #e7e7e7);
  border-radius: 999px;
  background: transparent;
  color: var(--td-text-color-secondary, #666);
  font-size: 11px;
  white-space: nowrap;
  padding: 2px 10px;
  cursor: pointer;
}

.timeline-lanes { flex: 1; display: flex; flex-direction: column; gap: 2px; }

.timeline-lane { display: flex; align-items: center; gap: 8px; }

.timeline-lane-label { font-size: 10px; color: var(--td-text-color-placeholder, #999); white-space: nowrap; width: 26px; }

.timeline-track { position: relative; flex: 1; height: 8px; border-radius: 4px; background: var(--td-component-stroke, #ececec); overflow: hidden; }

.timeline-seg { position: absolute; top: 0; bottom: 0; border-radius: 3px; min-width: 2px; }

.timeline-seg.lane0 { background: #8f8cf5; }

.timeline-seg.lane1 { background: #d4b106; }

.timeline-seg.lane2 { background: #2ba471; }

.turn-footer { margin-top: 2px; padding: 0 2px; font-size: 12px; color: var(--td-text-color-placeholder, #999); }

.footer-error { color: var(--td-error-color, #d54941); }

.footer-warn { color: var(--td-warning-color, #e37318); }
</style>
