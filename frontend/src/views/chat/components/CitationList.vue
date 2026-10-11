<script setup lang="ts">
import { ref, useId } from 'vue'
import { useRouter } from 'vue-router'

interface CitationReference {
  chunk_id?: string
  id?: string
  knowledge_id?: string
  knowledge_base_id?: string
  knowledge_title?: string
  knowledge_base_name?: string
  content?: string
  score?: number | string | null
}
defineProps<{ references?: CitationReference[] }>()
const router = useRouter()
const expanded = ref(false)
const navigationError = ref('')
const regionId = useId()

function formatScore(score: CitationReference['score']) {
  if (typeof score !== 'number' && (typeof score !== 'string' || !score.trim())) return null
  const value = Number(score)
  return Number.isFinite(value) ? value.toFixed(2) : null
}

function hasSource(reference: CitationReference) {
  return [reference.knowledge_base_id, reference.knowledge_id, reference.chunk_id]
    .every(id => typeof id === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(id))
}

async function openSource(reference: CitationReference) {
  if (!hasSource(reference)) return
  navigationError.value = ''
  try {
    await router.push({
      path: `/platform/knowledge-bases/${encodeURIComponent(reference.knowledge_base_id!)}`,
      query: { document: reference.knowledge_id, chunk: reference.chunk_id },
    })
  } catch {
    navigationError.value = '无法打开引用来源，请稍后重试'
  }
}
</script>

<template>
  <section v-if="references?.length" class="citation-list">
    <button class="citation-disclosure" type="button" :aria-expanded="expanded" :aria-controls="regionId" @click="expanded = !expanded">
      {{ expanded ? '收起' : '展开' }} {{ references.length }} 条引用
    </button>
    <div v-show="expanded" :id="regionId">
    <article v-for="(ref, index) in references" :key="ref.chunk_id || ref.id || index" class="citation-card">
      <div class="paper-kicker">引用 {{ index + 1 }}</div>
      <strong>{{ ref.knowledge_title || ref.knowledge_base_name || '知识片段' }}</strong>
      <p>{{ ref.content }}</p>
      <span v-if="formatScore(ref.score) !== null">相关度 {{ formatScore(ref.score) }}</span>
      <button class="citation-source-button" type="button" :disabled="!hasSource(ref)" @click="openSource(ref)">查看来源</button>
      <small v-if="!hasSource(ref)">缺少有效的来源标识</small>
    </article>
    </div>
    <p v-if="navigationError" role="alert">{{ navigationError }}</p>
  </section>
</template>

<style scoped>
.citation-disclosure, .citation-source-button {
  color: var(--primary);
  font: inherit;
  cursor: pointer;
}
.citation-disclosure { border: 0; background: none; padding: 0; font-weight: 750; }
.citation-source-button { display: block; margin-top: 8px; }
.citation-source-button:disabled { color: var(--text-muted); cursor: default; }
.citation-card small { display: block; margin-top: 4px; color: var(--text-muted); }
</style>
