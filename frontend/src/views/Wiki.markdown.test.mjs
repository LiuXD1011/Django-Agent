import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import assert from 'node:assert/strict'

const __dirname = dirname(fileURLToPath(import.meta.url))
const wikiVue = readFileSync(resolve(__dirname, './Wiki.vue'), 'utf8')

assert.match(
  wikiVue,
  /import\s+\{\s*renderMarkdownLite\s*\}\s+from\s+['"]\.\.\/utils\/markdown-lite\.mjs['"]/,
  'Wiki drawer should import the shared Markdown renderer'
)
assert.match(
  wikiVue,
  /const\s+renderedDrawerContent\s*=\s*computed\(\(\)\s*=>\s*renderMarkdownLite\(/,
  'Wiki drawer should compute rendered Markdown content'
)
assert.match(
  wikiVue,
  /<article\s+class="wiki-drawer-content markdown-lite"\s+v-html="renderedDrawerContent"><\/article>/,
  'Wiki drawer should render Markdown as HTML instead of interpolating raw content'
)

