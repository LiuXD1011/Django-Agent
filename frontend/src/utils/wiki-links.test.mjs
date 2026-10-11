import assert from 'node:assert/strict'
import test from 'node:test'
import { renderMarkdownLite } from './markdown-lite.mjs'

test('Wiki references render local navigation links only when enabled', () => {
  const text = 'Read [[entity/orca|Orca]] and [[concept/Django]].'
  const html = renderMarkdownLite(text, { wikiLinks: true })
  assert.match(html, /<a href="#wiki-entity%2Forca" data-wiki-slug="entity\/orca">Orca<\/a>/)
  assert.match(html, /data-wiki-slug="concept\/Django">concept\/Django<\/a>/)
  assert.equal(renderMarkdownLite(text), `<p>${text}</p>`)
})

test('Wiki references cannot inject HTML and code remains literal', () => {
  const html = renderMarkdownLite('[[entity/" onclick="bad|<script>bad</script>]]\n\n`[[entity/orca|Orca]]`\n\n```\n[[entity/orca|Orca]]\n```', { wikiLinks: true })
  assert.doesNotMatch(html, /<script>|" onclick="bad/)
  assert.match(html, /data-wiki-slug="entity\/&quot; onclick=&quot;bad"/)
  assert.match(html, /&lt;script&gt;bad&lt;\/script&gt;<\/a>/)
  assert.match(html, /<code>\[\[entity\/orca\|Orca\]\]<\/code>/)
  assert.equal((html.match(/data-wiki-slug=/g) || []).length, 1)
})
