import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'

const source = fs.readFileSync(new URL('./KnowledgeDetail.vue', import.meta.url), 'utf8')
const settings = fs.readFileSync(new URL('./Settings.vue', import.meta.url), 'utf8')
const api = fs.readFileSync(new URL('../api/index.ts', import.meta.url), 'utf8')

test('chunk drawer exposes multimodal hierarchy and immutable containers', () => {
  assert.match(source, /image_ocr/)
  assert.match(source, /image_caption/)
  assert.match(source, /parent_text:\s*'上下文父块'/)
  assert.match(source, /chunkImageUrls\[chunk\.image_info\?\.image_id\]/)
  assert.match(source, /URL\.createObjectURL/)
  assert.match(source, /chunk\.context_parent_id/)
  assert.match(source, /chunk\.media_parent_id/)
  assert.match(source, /chunk\.anchor_chunk_id/)
  assert.match(source, /上下文父块/)
  assert.match(source, /媒体容器/)
  assert.match(source, /锚定正文/)
  assert.doesNotMatch(source, /chunk\.parent_chunk_id/)
  assert.match(source, /isReadOnlyChunk\(chunk\)/)
  assert.match(source, /v-if="!isReadOnlyChunk\(chunk\)"/)
  assert.match(source, /class="chunk-readonly-content"/)
  for (const extension of [
    'pdf', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx', 'md', 'markdown',
    'html', 'htm', 'csv', 'json', 'txt', 'log', 'py', 'jpg', 'jpeg', 'png',
    'gif', 'bmp', 'tif', 'tiff', 'webp', 'svg',
  ]) {
    assert.match(source, new RegExp(`['"]${extension}['"]`), extension)
  }
  assert.match(api, /responseType:\s*'blob'/)
})

test('parser settings is a read-only capability view', () => {
  assert.match(settings, /engine\.formats/)
  assert.match(settings, /engine\.capabilities/)
  assert.doesNotMatch(settings, /v-model="kv\.parser\.notes"/)
  assert.doesNotMatch(settings, /saveKv\('parser-engine-config'/)
})
