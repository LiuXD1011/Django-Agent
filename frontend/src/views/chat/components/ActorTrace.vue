<script setup lang="ts">
import { ref, watch } from 'vue'
import {
  CheckCircleIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  ErrorCircleIcon,
  LoadingIcon,
  TimeIcon,
} from 'tdesign-icons-vue-next'
import { renderMarkdownLite } from '../../../utils/markdown-lite.mjs'

const props = defineProps<{ actors: any[] }>()

const expandedById = ref<Record<string, boolean>>({})
const manuallyTouchedActorIds = new Set<string>()
const activeStatuses = new Set(['pending', 'running'])
const successfulStatuses = new Set(['success', 'completed'])

function actorId(actor: any, index = 0) {
  return String(actor?.actor_id || `actor-${index}`)
}

function isActive(actor: any) {
  return activeStatuses.has(String(actor?.status || '').toLowerCase())
}

function effectiveStatus(actor: any) {
  const status = String(actor?.status || '').toLowerCase()
  const lastOutcome = String(actor?.last_outcome || '').toLowerCase()
  if (status === 'idle' && lastOutcome === 'success') return 'success'
  if (status === 'idle' && lastOutcome === 'failure') return 'failed'
  return status
}

function isExpanded(actor: any, index: number) {
  return expandedById.value[actorId(actor, index)] ?? isActive(actor)
}

function toggleActor(actor: any, index: number) {
  const id = actorId(actor, index)
  manuallyTouchedActorIds.add(id)
  expandedById.value[id] = !isExpanded(actor, index)
}

function statusIcon(actor: any) {
  const status = effectiveStatus(actor)
  if (activeStatuses.has(status)) return LoadingIcon
  if (successfulStatuses.has(status)) return CheckCircleIcon
  return ErrorCircleIcon
}

function statusLabel(actor: any) {
  return actor?.last_outcome || actor?.status || 'pending'
}

function duration(actor: any) {
  const durationMs = actor?.metadata?.duration_ms
  return Number.isFinite(Number(durationMs)) && Number(durationMs) > 0 ? `${durationMs}ms` : ''
}

watch(
  () => props.actors,
  (actors) => {
    actors.forEach((actor, index) => {
      const id = actorId(actor, index)
      if (!manuallyTouchedActorIds.has(id)) expandedById.value[id] = isActive(actor)
    })
  },
  { immediate: true, deep: true }
)
</script>

<template>
  <section v-if="actors.length" class="actor-trace" aria-label="子 Agent 执行轨迹">
    <div class="actor-trace-title">子 Agent</div>
    <article v-for="(actor, index) in actors" :key="actorId(actor, index)" class="actor-item" :class="effectiveStatus(actor)">
      <button
        type="button"
        class="actor-summary"
        :aria-expanded="isExpanded(actor, index)"
        :aria-controls="`actor-detail-${actorId(actor, index)}`"
        @click="toggleActor(actor, index)"
      >
        <ChevronDownIcon v-if="isExpanded(actor, index)" class="actor-chevron" aria-hidden="true" />
        <ChevronRightIcon v-else class="actor-chevron" aria-hidden="true" />
        <component :is="statusIcon(actor)" class="actor-status-icon" :class="{ 'is-loading': isActive(actor) }" aria-hidden="true" />
        <span class="actor-name">{{ actor.name || actor.agent_type || actor.actor_id }}</span>
        <span class="actor-status">{{ statusLabel(actor) }}</span>
        <span v-if="duration(actor)" class="actor-duration"><TimeIcon aria-hidden="true" />{{ duration(actor) }}</span>
      </button>
      <div v-show="isExpanded(actor, index)" :id="`actor-detail-${actorId(actor, index)}`" class="actor-details">
        <div v-if="actor.output" class="actor-output markdown-lite" v-html="renderMarkdownLite(actor.output)"></div>
        <pre v-if="actor.error" class="actor-error">{{ actor.error }}</pre>
      </div>
    </article>
  </section>
</template>
