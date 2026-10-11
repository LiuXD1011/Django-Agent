import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

const page = readFileSync(new URL('../Settings.vue', import.meta.url), 'utf8')
const integration = readFileSync(new URL('./IntegrationCredentials.vue', import.meta.url), 'utf8')

test('model form never repopulates a saved key and submits it only once', () => {
  assert.match(page, /api_key: ''/)
  assert.ok(!page.includes('api_key: model.parameters'))
  assert.ok(!page.includes('await api.updateModelCredentials'))
  assert.match(page, /if \(!secret\) delete payload.parameters.api_key/)
  assert.match(page, /@closed="resetForm"/)
})
test('credential clearing requires explicit confirmation and handles failures', () => {
  assert.match(page, /@confirm="confirmClearSecret"/)
  assert.match(page, /credentialBusy.value/)
  assert.match(page, /清除失败/)
})
test('all model types support UI configuration, including embedding dimensions', () => {
  assert.match(page, /form.parameters.dimension/)
  assert.match(page, /摘要、标题、问题生成与抽取使用默认对话模型/)
  assert.ok(!page.includes('>ENV</t-tag>'))
})
test('Langfuse keys use authenticated backend configuration without browser persistence', () => {
  assert.match(integration, /\/api\/v1\/integrations\/langfuse\/credentials/)
  assert.match(integration, /form.value.secret_key = ''/)
  assert.match(integration, /@confirm="save\(true\)"/)
  assert.ok(!integration.includes('localStorage'))
  assert.ok(!integration.includes('sessionStorage'))
})
