import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
const read = (name) => readFileSync(new URL(name, import.meta.url), 'utf8')

test('mobile navigation has four real destinations and capture reuses the authorized upload confirmation', () => {
  const platform = read('../views/Platform.vue'), detail = read('../views/KnowledgeDetail.vue')
  for (const label of ['知识库', '问答', '收集', '我的']) assert(platform.includes(`label: '${label}'`))
  assert.match(platform, /api\.searchKbs/)
  assert.match(platform, /query: \{ collect: '1' \}/)
  assert.match(detail, /capture="environment"/)
  assert.match(detail, /@change="queueUpload"/)
  assert.match(detail, /上传期间请保持页面在前台/)
  assert.match(detail, /api\.uploadFile/)
  assert.match(detail, /unsupportedPhotoExtensions/)
})

test('mobile styles use dynamic viewport, safe area, bounded readers and 44px controls', () => {
  const css = read('./mobile.css')
  assert.match(css, /--app-viewport-height, 100dvh/)
  assert.match(css, /safe-area-inset-top/)
  assert.match(css, /safe-area-inset-bottom/)
  assert.match(css, /repeat\(4, minmax\(0, 1fr\)\)/)
  assert.match(css, /min-height: 44px/)
  assert.match(css, /mobile-keyboard-open \.mobile-tab-bar \{ display: none/)
  const input = read('../views/chat/components/ChatInput.vue')
  assert.match(input, /event\.isComposing \|\| event\.keyCode === 229/)
  assert.match(input, /window\.matchMedia\('\(max-width: 760px\)'\)\.matches\) return/)
  assert.doesNotMatch(input, /keydown\.enter[^=]*\.prevent=/)
})

test('manifest has stable installation identity and real icon dimensions', () => {
  const manifest = JSON.parse(read('../../public/manifest.webmanifest'))
  assert.equal(manifest.id, '/'); assert.equal(manifest.scope, '/'); assert.equal(manifest.display, 'standalone')
  for (const icon of manifest.icons) {
    const data = readFileSync(new URL(`../../public${icon.src}`, import.meta.url))
    const size = Number(icon.sizes.split('x')[0])
    assert.equal(data.readUInt32BE(16), size); assert.equal(data.readUInt32BE(20), size)
  }
})
