import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'

const source = fs.readFileSync(new URL('./KnowledgeDetail.vue', import.meta.url), 'utf8')
const settings = fs.readFileSync(new URL('./Settings.vue', import.meta.url), 'utf8')
const api = fs.readFileSync(new URL('../api/index.ts', import.meta.url), 'utf8')

test('chunk drawer exposes multimodal type, preview and parent relationship', () => {
  assert.match(source, /image_ocr/)
  assert.match(source, /image_caption/)
  assert.match(source, /chunkImageUrls\[chunk\.image_info\?\.image_id\]/)
  assert.match(source, /URL\.createObjectURL/)
  assert.match(source, /chunk\.parent_chunk_id/)
  assert.match(api, /responseType:\s*'blob'/)
})

test('parser settings is a read-only capability view', () => {
  assert.match(settings, /engine\.formats/)
  assert.match(settings, /engine\.capabilities/)
  assert.doesNotMatch(settings, /v-model="kv\.parser\.notes"/)
  assert.doesNotMatch(settings, /saveKv\('parser-engine-config'/)
})
