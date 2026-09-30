import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

const settings = readFileSync(new URL('../Settings.vue', import.meta.url), 'utf8')
const dialog = readFileSync(new URL('./ModelThinkingSettings.vue', import.meta.url), 'utf8')

test('engine settings and their background requests are removed from Settings', () => {
  for (const value of ["key: 'parser'", "key: 'storage'", 'api.parserEngines()', 'api.storageStatus()',
    'parser-engine-config', 'storage-engine-config', 'checkParser', 'checkStorage']) {
    assert.ok(!settings.includes(value), value)
  }
})

test('thinking action belongs to the full-width model action row', () => {
  assert.match(settings, /class="settings-model-actions">\s*<button[^>]*class="thinking-settings-button"/)
  assert.match(settings, /\.settings-model-actions button\s*\{[^}]*white-space:\s*nowrap/s)
  assert.match(settings, /thinking-settings-button\s*\{[^}]*min-width:\s*108px/s)
})

test('dialog escapes page clipping and keeps controls in a separate footer', () => {
  assert.match(dialog, /attach="body" placement="center"/)
  assert.match(dialog, /class="thinking-scroll"/)
  assert.match(dialog, /class="thinking-footer"/)
  assert.match(dialog, /overflow-y:\s*auto/)
  assert.match(dialog, /type="radio"/)
  assert.match(dialog, /@media \(max-width: 480px\)/)
})

test('loading, saving, readonly and dirty states gate submission', () => {
  assert.match(dialog, /if \(disabled.value \|\| !entry.value \|\| !dirty.value\) return/)
  assert.match(dialog, /:disabled="disabled \|\| !dirty"/)
  assert.match(dialog, /role="alert"/)
  assert.match(dialog, /:close-on-esc-keydown="!busy"/)
})
