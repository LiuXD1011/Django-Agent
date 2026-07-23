<script setup lang="ts">
import {
  type ChunkingConfig,
  chunkingStrategyLabel,
  chunkingStrategyOptions,
} from '../api'

defineProps<{
  needsReindex?: boolean
  lastEffectiveStrategy?: string | null
}>()

const config = defineModel<ChunkingConfig>({ required: true })
</script>

<template>
  <div class="chunking-settings">
    <div class="chunking-heading">
      <strong>分块设置</strong>
      <div class="chunking-status-row">
        <t-tag v-if="needsReindex" size="small" theme="warning">需要重建索引</t-tag>
        <t-tag v-if="lastEffectiveStrategy" size="small" variant="outline">当前生效：{{ chunkingStrategyLabel(lastEffectiveStrategy) }}</t-tag>
        <span v-if="config.strategy === 'semantic' || lastEffectiveStrategy === 'semantic'" class="experimental-tag">Experimental</span>
      </div>
    </div>
    <div class="chunking-grid">
      <label class="chunking-field"><span>分块策略</span><select v-model="config.strategy"><option v-for="option in chunkingStrategyOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></label>
      <label class="chunking-field"><span>分块长度</span><input v-model.number="config.chunk_size" type="number" min="128" max="4096" step="1" /></label>
      <label class="chunking-field"><span>重叠字符</span><input v-model.number="config.chunk_overlap" type="number" min="0" :max="Math.floor(config.chunk_size / 2)" step="1" /></label>
      <label class="chunking-toggle"><input v-model="config.enable_parent_child" type="checkbox" /><span>启用父子分块</span></label>
      <template v-if="config.enable_parent_child">
        <label class="chunking-field"><span>父块长度</span><input v-model.number="config.parent_chunk_size" type="number" :min="Math.max(512, config.child_chunk_size)" max="8192" step="1" /></label>
        <label class="chunking-field"><span>子块长度</span><input v-model.number="config.child_chunk_size" type="number" min="128" :max="Math.min(2048, config.parent_chunk_size)" step="1" /></label>
        <label class="chunking-field"><span>子块重叠</span><input v-model.number="config.child_chunk_overlap" type="number" min="0" :max="Math.floor(config.child_chunk_size / 2)" step="1" /></label>
      </template>
      <label class="chunking-field"><span>Token 上限</span><input v-model.number="config.token_limit" type="number" min="0" max="32768" step="1" /></label>
      <template v-if="config.strategy === 'semantic'">
        <label class="chunking-field"><span>语义窗口</span><input v-model.number="config.semantic_window_size" type="number" min="1" max="32" step="1" /></label>
        <label class="chunking-field"><span>语义断点百分位</span><input v-model.number="config.semantic_breakpoint_percentile" type="number" min="0" max="100" step="0.1" /></label>
      </template>
    </div>
  </div>
</template>
