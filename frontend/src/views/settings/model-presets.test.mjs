import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { test } from 'node:test'
import { inferPreset, modelPresets, presetFields, presetsForType } from './model-presets.ts'

const settings = readFileSync(new URL('../Settings.vue', import.meta.url), 'utf8')

test('common remote providers have ready-to-save names, endpoints and empty credentials', () => {
  for (const id of ['aliyun-bailian', 'deepseek', 'openai', 'siliconflow', 'zhipu', 'gemini']) {
    const fields = presetFields(id, 'KnowledgeQA')
    assert.ok(fields?.name, id)
    assert.equal(fields.parameters.model, fields.name)
    assert.match(fields.parameters.base_url, /^https:\/\//)
    assert.equal(fields.parameters.api_key, '')
    assert.ok(fields.display_name)
  }
})

test('provider selection filters unsupported model types instead of inventing endpoints', () => {
  assert.deepEqual(presetsForType('Rerank').map((p) => p.id), ['siliconflow', 'custom'])
  assert.ok(!presetsForType('Embedding').some((p) => p.id === 'deepseek'))
  assert.ok(!presetsForType('VLLM').some((p) => p.id === 'deepseek'))
  assert.equal(presetFields('deepseek', 'Embedding'), null)
})

test('embedding dimensions follow the default model, not the previous provider', () => {
  assert.equal(presetFields('openai', 'Embedding').parameters.dimension, 1536)
  assert.equal(presetFields('aliyun-bailian', 'Embedding').parameters.dimension, 1024)
  assert.equal(presetFields('siliconflow', 'Embedding').parameters.dimension, 1024)
})

test('local and custom providers remain available without API keys', () => {
  for (const type of ['KnowledgeQA', 'Embedding', 'Rerank', 'VLLM']) {
    assert.ok(presetsForType(type).some((p) => p.id === 'custom'))
  }
  assert.equal(modelPresets.find((p) => p.id === 'local').requiresKey, false)
  assert.equal(modelPresets.find((p) => p.id === 'custom').requiresKey, false)
  assert.equal(presetFields('custom', 'KnowledgeQA'), null)
  assert.equal(presetFields('local', 'KnowledgeQA').parameters.base_url, 'http://localhost:11434/v1')
})

test('existing compatible endpoints are recognized without modifying saved values', () => {
  const model = { type: 'KnowledgeQA', source: 'openai', parameters: { base_url: 'https://api.deepseek.com/v1/', model: 'my-model' } }
  const original = structuredClone(model)
  assert.equal(inferPreset(model), 'deepseek')
  assert.deepEqual(model, original)
  assert.equal(inferPreset({ type: 'KnowledgeQA', source: 'openai', parameters: { base_url: 'https://proxy.example/v1' } }), 'custom')
})

test('preset results do not share mutable state between dialogs', () => {
  const fields = presetFields('openai', 'KnowledgeQA')
  fields.parameters.api_key = 'fixture-only'
  fields.parameters.model = 'custom-model'
  assert.equal(presetFields('openai', 'KnowledgeQA').parameters.api_key, '')
  assert.equal(presetFields('openai', 'KnowledgeQA').parameters.model, 'gpt-4o-mini')
})

test('UI keeps saved keys on blank edit but clears keys on explicit provider changes', () => {
  assert.match(settings, /storedModelKey.value = false/)
  assert.match(settings, /form.value.parameters.api_key = ''/)
  assert.match(settings, /currentPreset.value\?\.requiresKey && !storedModelKey.value/)
  assert.match(settings, /if \(!secret\) delete payload.parameters.api_key/)
  const open = settings.slice(settings.indexOf('function openModel'), settings.indexOf('async function load()'))
  assert.match(open, /selectedPreset.value = inferPreset\(model\)/)
  assert.ok(!open.includes('changeProvider()'))
})

test('UI retains advanced overrides and refreshes defaults only on explicit changes', () => {
  assert.match(settings, /@change="changeModelType"/)
  assert.match(settings, /@change="changeProvider"/)
  assert.match(settings, /<details class="wide model-advanced"/)
  for (const field of ['form.name', 'form.display_name', 'form.parameters.base_url', 'form.parameters.model', 'form.parameters.dimension']) {
    assert.ok(settings.includes(field), field)
  }
})

test('application configuration no longer depends on root environment files', () => {
  for (const name of ['.env', '.env.example']) {
    assert.equal(existsSync(new URL('../../../../' + name, import.meta.url)), false)
  }
  const backend = readFileSync(new URL('../../../../packages/core/src/settings/startup.ts', import.meta.url), 'utf8')
  assert.ok(!backend.includes('load_dotenv'))
  assert.doesNotMatch(backend, /\b(?:from|require)\s*\(?\s*['"]dotenv(?:\/|['"])/)
})

test('blank edit cannot forward an existing key to a changed endpoint', () => {
  assert.match(settings, /originalCredentialEndpoint.value = storedModelKey.value/)
  assert.match(settings, /!== originalCredentialEndpoint.value/)
  assert.match(settings, /更换 API 地址时请输入新密钥/)
})
