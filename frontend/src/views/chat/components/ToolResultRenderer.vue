<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ name: string; output: string; error?: string; durationMs?: number }>()

const formattedOutput = computed(() => {
  if (props.error) return props.error
  if (!props.output) return ''

  // knowledge_search: 解析编号列表
  if (props.name === 'knowledge_search') {
    const items = props.output.split(/\n\n(?=\[\d+\])/).filter(Boolean)
    return items.map(item => {
      const match = item.match(/^\[(\d+)\]\s*(.*?)\s*\(score:\s*([\d.]+)\)\n([\s\S]*)$/)
      if (match) {
        return { index: match[1], title: match[2], score: match[3], content: match[4].trim() }
      }
      return { index: '?', title: '', score: '', content: item }
    })
  }

  // grep_chunks: 解析分隔线
  if (props.name === 'grep_chunks') {
    return props.output.split(/\n---\n/).filter(Boolean)
  }

  // list_knowledge_docs: 解析列表
  if (props.name === 'list_knowledge_docs') {
    return props.output.split('\n').filter(l => l.startsWith('- '))
  }

  // database_query: 直接显示
  if (props.name === 'database_query') {
    return props.output
  }

  // web_search: 解析搜索结果
  if (props.name === 'web_search') {
    return props.output.split(/\n\n(?=- )/).filter(Boolean)
  }

  return props.output
})

const icon = computed(() => {
  const icons: Record<string, string> = {
    knowledge_search: '🔍',
    grep_chunks: '🔎',
    list_knowledge_docs: '📋',
    get_document_info: '📄',
    database_query: '🗄️',
    web_search: '🌐',
    web_fetch: '🔗',
    thinking: '🧠',
    todo_write: '📝',
  }
  return icons[props.name] || '⚙️'
})
</script>

<template>
  <div class="tool-result-renderer" :class="{ 'has-error': !!error }">
    <!-- knowledge_search 结果 -->
    <template v-if="name === 'knowledge_search' && Array.isArray(formattedOutput)">
      <div v-for="(item, idx) in formattedOutput" :key="idx" class="search-result-item">
        <div class="search-result-header">
          <span class="search-result-index">{{ item.index }}</span>
          <span class="search-result-title">{{ item.title }}</span>
          <span v-if="item.score" class="search-result-score">{{ item.score }}</span>
        </div>
        <div class="search-result-content">{{ item.content }}</div>
      </div>
    </template>

    <!-- grep_chunks 结果 -->
    <template v-else-if="name === 'grep_chunks' && Array.isArray(formattedOutput)">
      <div v-for="(chunk, idx) in formattedOutput" :key="idx" class="grep-result-item">
        {{ chunk }}
      </div>
    </template>

    <!-- list_knowledge_docs 结果 -->
    <template v-else-if="name === 'list_knowledge_docs' && Array.isArray(formattedOutput)">
      <div class="doc-list">
        <div v-for="(line, idx) in formattedOutput" :key="idx" class="doc-list-item">{{ line }}</div>
      </div>
    </template>

    <!-- web_search 结果 -->
    <template v-else-if="name === 'web_search' && Array.isArray(formattedOutput)">
      <div v-for="(result, idx) in formattedOutput" :key="idx" class="web-result-item">{{ result }}</div>
    </template>

    <!-- 默认渲染 -->
    <template v-else>
      <pre class="tool-result-raw">{{ typeof formattedOutput === 'string' ? formattedOutput : JSON.stringify(formattedOutput, null, 2) }}</pre>
    </template>

    <!-- 错误信息 -->
    <div v-if="error" class="tool-result-error">{{ error }}</div>
  </div>
</template>

<style scoped>
.tool-result-renderer {
  max-height: 200px;
  overflow-y: auto;
  font-size: 12px;
  line-height: 1.5;
}

.tool-result-renderer.has-error {
  border-left: 2px solid #f53f3f;
}

/* 搜索结果 */
.search-result-item {
  padding: 4px 0;
  border-bottom: 1px solid #f2f3f5;
}
.search-result-item:last-child { border-bottom: none; }

.search-result-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 2px;
}

.search-result-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #4f46e5;
  color: #fff;
  font-size: 10px;
  font-weight: 600;
  flex-shrink: 0;
}

.search-result-title {
  font-weight: 500;
  color: #1d2129;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.search-result-score {
  margin-left: auto;
  color: #86909c;
  font-size: 10px;
  flex-shrink: 0;
}

.search-result-content {
  color: #4e5969;
  padding-left: 24px;
  max-height: 60px;
  overflow: hidden;
}

/* Grep 结果 */
.grep-result-item {
  padding: 3px 0;
  border-bottom: 1px solid #f2f3f5;
  font-family: monospace;
  font-size: 11px;
}
.grep-result-item:last-child { border-bottom: none; }

/* 文档列表 */
.doc-list { padding: 2px 0; }
.doc-list-item {
  padding: 2px 0;
  color: #4e5969;
}

/* Web 搜索结果 */
.web-result-item {
  padding: 4px 0;
  border-bottom: 1px solid #f2f3f5;
  white-space: pre-wrap;
}
.web-result-item:last-child { border-bottom: none; }

/* 默认原始输出 */
.tool-result-raw {
  margin: 0;
  padding: 4px;
  background: #f9fafb;
  border-radius: 4px;
  font-family: monospace;
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 150px;
  overflow-y: auto;
}

/* 错误 */
.tool-result-error {
  padding: 4px 8px;
  margin-top: 4px;
  background: #fff2f0;
  border-radius: 4px;
  color: #f53f3f;
  font-size: 11px;
}
</style>
