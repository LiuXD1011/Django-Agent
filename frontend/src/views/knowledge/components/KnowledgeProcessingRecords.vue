<script setup lang="ts">
import { computed, ref } from 'vue'
import KnowledgeTraceTimeline from '../../chat/components/KnowledgeTraceTimeline.vue'

export type ProcessingRecord = {
  id: string
  title: string
  parse_status?: string
  updated_at?: string
  processed_at?: string
  error_message?: string
  file_name?: string
}

const props = defineProps<{
  records: ProcessingRecord[]
  loading?: boolean
}>()

const expandedId = ref('')
const statusFilter = ref('')
const statusLabels: Record<string, string> = {
  pending: '等待解析',
  processing: '解析中',
  finalizing: '索引中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

const visibleRecords = computed(() => statusFilter.value
  ? props.records.filter((record) => record.parse_status === statusFilter.value)
  : props.records)

function toggleRecord(id: string) {
  expandedId.value = expandedId.value === id ? '' : id
}
</script>

<template>
  <section class="processing-workbench workspace-panel">
    <header class="processing-head">
      <div><h3>解析记录</h3><p>查看文档解析、索引、图谱与 Wiki 生成阶段。</p></div>
      <t-select v-model="statusFilter" clearable placeholder="全部状态">
        <t-option v-for="(label, value) in statusLabels" :key="value" :value="value" :label="label" />
      </t-select>
    </header>
    <div v-if="loading && !records.length" class="processing-skeleton"><span v-for="n in 4" :key="n"></span></div>
    <div v-else-if="visibleRecords.length" class="processing-list">
      <article v-for="record in visibleRecords" :key="record.id" class="processing-record">
        <button type="button" class="processing-record-summary" :aria-expanded="expandedId === record.id" @click="toggleRecord(record.id)">
          <span class="processing-record-copy"><strong>{{ record.title }}</strong><small>{{ record.file_name || '知识文档' }}</small></span>
          <span :class="['processing-state', record.parse_status || 'pending']">{{ statusLabels[record.parse_status || 'pending'] || record.parse_status }}</span>
          <span class="processing-time">{{ record.updated_at ? new Date(record.updated_at).toLocaleString() : '-' }}</span>
          <span class="processing-chevron">⌄</span>
        </button>
        <div v-if="record.error_message" class="processing-error">{{ record.error_message }}</div>
        <div v-if="expandedId === record.id" class="processing-record-detail">
          <KnowledgeTraceTimeline :knowledge-id="record.id" :active="['pending', 'processing', 'finalizing'].includes(record.parse_status || '')" />
        </div>
      </article>
    </div>
    <div v-else class="empty-state">暂无解析记录</div>
  </section>
</template>
