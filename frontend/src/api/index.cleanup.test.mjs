import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const apiSource = readFileSync(resolve(__dirname, 'index.ts'), 'utf8')

const removedMethods = [
  'updateKnowledge',
  'previewKnowledgeUrl',
  'downloadKnowledgeUrl',
  'updateTag',
  'deleteTag',
  'updateSession',
  'suggestedQuestions',
  'modelProviders',
  'listEmbedChannels',
  'createEmbedChannel',
  'rotateEmbedToken',
  'previewEmbedSession',
  'listImChannels',
  'createImChannel',
  'toggleImChannel',
]

for (const method of removedMethods) {
  assert.doesNotMatch(
    apiSource,
    new RegExp(`\\b${method}\\s*:`),
    `${method} should not remain in the frontend API client when no frontend code calls it`,
  )
}

console.log('frontend API cleanup assertions passed')
