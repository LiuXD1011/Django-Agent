<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ message: any; loading?: boolean }>()

interface Step {
  key: string
  label: string
  icon: string
  done: boolean
  active: boolean
}

const steps = computed<Step[]>(() => {
  const m = props.message
  const hasRefs = !!(m?.knowledge_references?.length)
  const hasContent = !!(m?.content?.trim())
  const completed = !!m?.is_completed

  return [
    {
      key: 'understand',
      label: '理解问题',
      icon: '🧠',
      done: hasContent || hasRefs || completed,
      active: props.loading && !hasContent && !hasRefs,
    },
    {
      key: 'retrieve',
      label: '检索知识库',
      icon: '🔍',
      done: hasRefs || (hasContent && completed),
      active: props.loading && !hasRefs && !hasContent,
    },
    {
      key: 'organize',
      label: '整理引用',
      icon: '📎',
      done: hasRefs && hasContent,
      active: props.loading && hasRefs && !hasContent,
    },
    {
      key: 'generate',
      label: '生成回答',
      icon: '✍️',
      done: completed,
      active: props.loading && hasContent && !completed,
    },
  ]
})

const refCount = computed(() => props.message?.knowledge_references?.length || 0)
const showProgress = computed(() => props.loading || (props.message?.agent_steps?.length && !props.message?.is_completed))
</script>

<template>
  <div v-if="showProgress" class="rag-progress-bar">
    <div class="rag-steps">
      <div
        v-for="step in steps"
        :key="step.key"
        class="rag-step"
        :class="{ done: step.done, active: step.active }"
      >
        <span class="rag-step__icon">{{ step.done ? '✓' : step.icon }}</span>
        <span class="rag-step__label">{{ step.label }}</span>
        <span v-if="step.key === 'retrieve' && refCount" class="rag-step__badge">{{ refCount }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.rag-progress-bar {
  padding: 8px 0;
  margin-bottom: 4px;
}

.rag-steps {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.rag-step {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  border-radius: 20px;
  font-size: 12px;
  color: #86909c;
  background: #f2f3f5;
  transition: all 0.3s ease;
  white-space: nowrap;
}

.rag-step.done {
  color: #00b42a;
  background: #e8ffea;
}

.rag-step.active {
  color: #4f46e5;
  background: #eef2ff;
  animation: rag-pulse 1.5s ease-in-out infinite;
}

.rag-step__icon {
  font-size: 12px;
  line-height: 1;
}

.rag-step__label {
  font-weight: 500;
}

.rag-step__badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 8px;
  background: #4f46e5;
  color: #fff;
  font-size: 10px;
  font-weight: 600;
  line-height: 1;
}

@keyframes rag-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}
</style>
