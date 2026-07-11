import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const knowledgeDetail = readFileSync(resolve(import.meta.dirname, 'KnowledgeDetail.vue'), 'utf8')
const settings = readFileSync(resolve(import.meta.dirname, 'Settings.vue'), 'utf8')

for (const extension of ['mp3', 'wav', 'm4a', 'aac', 'ogg', 'flac', 'mp4', 'mov', 'avi', 'mkv', 'webm']) {
  assert.match(knowledgeDetail, new RegExp(`['\"]${extension}['\"]`), `upload filtering should list .${extension}`)
}

assert.match(knowledgeDetail, /不支持音频或视频文件/, 'file selection should explain why media files were rejected')
assert.doesNotMatch(settings, /\basr\b|\bASR\b|语音转写/, 'settings should not expose the retired ASR capability')
