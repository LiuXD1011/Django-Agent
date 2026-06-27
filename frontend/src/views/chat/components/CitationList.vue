<script setup lang="ts">
defineProps<{ references?: any[] }>()
</script>

<template>
  <details v-if="references?.length" class="citation-list">
    <summary>{{ references.length }} 条引用</summary>
    <article v-for="(ref, index) in references" :key="ref.chunk_id || ref.id || index" class="citation-card">
      <div class="paper-kicker">引用 {{ index + 1 }}</div>
      <strong>{{ ref.knowledge_title || ref.knowledge_base_name || '知识片段' }}</strong>
      <p>{{ ref.content }}</p>
      <span>相关度 {{ Number(ref.score || 0).toFixed(2) }}</span>
    </article>
  </details>
</template>
