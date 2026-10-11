import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { build } from 'esbuild'
import { compileScript, parse } from '@vue/compiler-sfc'
import { chromium } from '@playwright/test'

const directory = fileURLToPath(new URL('.', import.meta.url))
const reference = { knowledge_base_id: 'kb-a', knowledge_id: 'doc-a', chunk_id: 'chunk-a', content: '真实引用正文' }
let bundled

async function fixture(references) {
  bundled ??= build({
    stdin: { contents: `import Citations from 'citation:component';
      import {createApp,h} from 'vue';
      import {createRouter,createMemoryHistory,RouterView} from 'vue-router';
      const router=createRouter({history:createMemoryHistory(),routes:[
        {path:'/chat',component:{render:()=>h(Citations,{references:window.fixtureReferences})}},
        {path:'/platform/knowledge-bases/:kbId',component:{render:()=>h('h1','已打开来源')}}
      ]});
      window.fixtureRouter=router;
      const app=createApp({render:()=>h(RouterView)});app.use(router);
      router.push('/chat').then(()=>router.isReady()).then(()=>app.mount('#app'));`, loader: 'ts', resolveDir: directory },
    bundle: true, write: false, format: 'iife',
    plugins: [{ name: 'actual-citation-component', setup(builder) {
      builder.onResolve({ filter: /^citation:component$/ }, () => ({ path: 'CitationList.vue', namespace: 'component' }))
      builder.onLoad({ filter: /.*/, namespace: 'component' }, () => {
        const { descriptor } = parse(readFileSync(new URL('./CitationList.vue', import.meta.url), 'utf8'))
        return { contents: compileScript(descriptor, { id: 'citation-score-regression', inlineTemplate: true }).content, loader: 'ts', resolveDir: directory }
      })
    } }],
  }).then(result => result.outputFiles[0].text)
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage(), errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.setContent('<div id="app"></div>')
    await page.evaluate(values => { window.fixtureReferences = values }, references)
    await page.addScriptTag({ content: await bundled })
    await page.getByRole('button', { name: `展开 ${references.length} 条引用`, exact: true }).click({ timeout: 2000 })
    return { page, errors, close: () => browser.close() }
  } catch (error) { await browser.close(); throw error }
}

// Native Agent grep references legitimately have no score. They must retain
// their source action without presenting an invented relevance value.
test('actual citation rendering omits missing and invalid relevance scores', async () => {
  const values = [undefined, null, '', ' \t\n ', NaN, Infinity, -Infinity, 'NaN', 'Infinity', 'invalid']
  const references = [{ ...reference }, ...values.map((score, index) => ({ ...reference, chunk_id: `chunk-${index}`, score }))]
  const f = await fixture(references)
  try {
    assert.equal(await f.page.locator('.citation-card').count(), references.length)
    assert.deepEqual(await f.page.locator('.citation-card span').allTextContents(), [])
    assert.equal(await f.page.getByRole('button', { name: '查看来源', exact: true }).count(), references.length)
    assert.deepEqual(f.errors, [])
  } finally { await f.close() }
})

test('actual citation rendering preserves zero and finite numeric string scores', async () => {
  const values = [0, 0.8, -0.25, '0', '0.734', ' 0.5 ', '1e-2']
  const f = await fixture(values.map((score, index) => ({ ...reference, chunk_id: `chunk-${index}`, score })))
  try {
    assert.deepEqual(await f.page.locator('.citation-card span').allTextContents(), [
      '相关度 0.00', '相关度 0.80', '相关度 -0.25', '相关度 0.00', '相关度 0.73', '相关度 0.50', '相关度 0.01',
    ])
    assert.deepEqual(f.errors, [])
  } finally { await f.close() }
})

test('a reference without a relevance score still opens its exact source in the real router', async () => {
  const f = await fixture([reference, { content: '无来源引用' }])
  try {
    const actions = f.page.getByRole('button', { name: '查看来源', exact: true })
    assert.equal(await actions.nth(0).isEnabled(), true)
    assert.equal(await actions.nth(1).isDisabled(), true)
    await actions.nth(0).focus(); await actions.nth(0).press('Enter')
    await f.page.getByRole('heading', { name: '已打开来源', exact: true }).waitFor({ timeout: 2000 })
    assert.deepEqual(await f.page.evaluate(() => ({ path: window.fixtureRouter.currentRoute.value.path, query: window.fixtureRouter.currentRoute.value.query })), {
      path: '/platform/knowledge-bases/kb-a', query: { document: 'doc-a', chunk: 'chunk-a' },
    })
    assert.deepEqual(f.errors, [])
  } finally { await f.close() }
})
