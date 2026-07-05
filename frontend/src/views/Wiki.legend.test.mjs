import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import assert from 'node:assert/strict'

const __dirname = dirname(fileURLToPath(import.meta.url))
const wikiVue = readFileSync(resolve(__dirname, './Wiki.vue'), 'utf8')

const legendItemsMatch = wikiVue.match(/const legendItems = computed\(\(\) => (?<body>[^\n]+)/)

assert.ok(legendItemsMatch, 'Wiki graph legendItems computed value should exist')
assert.match(
  legendItemsMatch.groups.body,
  /\.filter\(\(\[type\]\) => type !== ['"]page['"]\)/,
  'Wiki graph legend should exclude the deprecated page type'
)

const removedTypeNames = ['syn' + 'thesis', 'com' + 'parison']
for (const typeName of removedTypeNames) {
  assert.ok(
    !wikiVue.includes(typeName),
    'Wiki graph should not expose removed reserved page types'
  )
}

const removedTypeLabels = [String.fromCharCode(0x7efc, 0x5408), String.fromCharCode(0x5bf9, 0x6bd4)]
for (const label of removedTypeLabels) {
  assert.ok(
    !wikiVue.includes(label),
    'Wiki graph should not show removed page type labels in the legend'
  )
}
