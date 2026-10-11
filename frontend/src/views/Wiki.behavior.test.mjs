import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import vm from 'node:vm'
import { transformSync } from 'esbuild'
import { parse, compileScript } from '@vue/compiler-sfc'

const require = createRequire(import.meta.url)
const vue = require('vue')
const { descriptor } = parse(readFileSync(new URL('./Wiki.vue', import.meta.url), 'utf8'))
const script = transformSync(compileScript(descriptor, { id: 'wiki-behavior' }).content, {
  loader: 'ts', format: 'cjs', target: 'es2022',
}).code

function mountWiki() {
  const warnings = []
  const graphCalls = []
  const scope = vue.effectScope()
  const context = vm.createContext({
    module: { exports: {} }, console, setTimeout,
    require: (name) => {
      if (name === 'vue') return { ...vue, onMounted: () => {}, onUnmounted: () => {} }
      if (name === 'vue-router') return { useRoute: () => ({ params: {}, query: {} }), useRouter: () => ({ replace: () => {} }) }
      if (name === '../api') return { api: {
        getWikiPage: async (_, slug) => ({ data: { slug, title: slug } }),
        wikiGraph: async (_, params) => { graphCalls.push(params); return { data: { nodes: [], edges: [] } } },
      } }
      if (name === '../utils/markdown-lite.mjs') return { renderMarkdownLite: (text) => text }
      if (name === 'tdesign-vue-next') return { MessagePlugin: { warning: (message) => warnings.push(message) } }
      throw new Error(`Unexpected import: ${name}`)
    },
  })
  vm.runInContext(script, context)
  const b = scope.run(() => context.module.exports.default.setup({ kbId: 'kb', view: 'pages', embedded: true }, { expose: () => {} }))
  return { b, warnings, graphCalls, dispose: () => scope.stop() }
}

test('Wiki references select a page, open a graph drawer, and explain missing targets', async () => {
  const { b, warnings, dispose } = mountWiki()
  let prevented = 0
  const event = (slug) => ({ target: { closest: () => ({ dataset: { wikiSlug: slug } }) }, preventDefault: () => { prevented += 1 } })
  try {
    b.pages.value = [{ slug: 'entity/orca' }, { slug: 'entity/django' }]
    await b.navigateWikiLink(event('entity/django'))
    assert.equal(b.selectedSlug.value, 'entity/django')
    b.tab.value = 'graph'
    await b.navigateWikiLink(event('entity/orca'))
    assert.equal(b.drawerVisible.value, true)
    assert.equal(b.drawerPage.value.slug, 'entity/orca')
    await b.navigateWikiLink(event('missing'))
    assert.deepEqual(warnings, ['Wiki 页面不存在'])
    assert.equal(prevented, 3)
  } finally { dispose() }
})

test('node type dropdown filters the graph and clearing restores every type', async () => {
  const { b, graphCalls, dispose } = mountWiki()
  try {
    await b.selectType('entity')
    assert.deepEqual(Array.from(b.activeTypes.value), ['entity'])
    assert.equal(graphCalls.at(-1).types, 'entity')
    await b.selectType('')
    assert.equal(b.activeTypes.value.size, 4)
    assert.equal(graphCalls.at(-1).types, undefined)
  } finally { dispose() }
})
