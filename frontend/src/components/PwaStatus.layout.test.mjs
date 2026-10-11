import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { build } from 'esbuild'
import { compileScript, parse } from '@vue/compiler-sfc'
import { chromium } from '@playwright/test'

// R-PWA-OCCLUSION: the actual Orca install notice intercepted model role clicks.
// Only routing/remote boundaries are fixtures; App, PwaStatus and application CSS are real.
const compile = path => compileScript(parse(readFileSync(path, 'utf8')).descriptor,
  { id: 'pwa-layout', inlineTemplate: true }).content
const css = ['../styles/app.css', '../styles/mobile.css'].map(path =>
  readFileSync(new URL(path, import.meta.url), 'utf8')).join('\n')

async function bundle() {
  const result = await build({
    stdin: { contents: compile(new URL('../App.vue', import.meta.url)).replace('export default', 'const App=') + `
      import {createApp,h} from 'vue';
      const roles=['全部','对话','Embedding','ReRank','视觉'];
      const Fixture={render(){return h('div',{class:'shell'},[
        h('aside',{class:'sidebar'},h('button',{class:'account-entry'},'账户与设置')),
        h('section',{class:'workspace'},h('main',{class:'fixture-page'},[
          h('div',{class:'fixture-space'},'模型管理'),
          h('div',{class:'fixture-roles'},roles.map(role=>h('button',{onClick:()=>{document.body.dataset.selected=role}},role)))
        ]))
      ])}};
      createApp(App).component('router-view',Fixture).mount('#app');`,
      loader: 'ts', resolveDir: fileURLToPath(new URL('..', import.meta.url)) },
    bundle: true, write: false, format: 'iife', define: { 'import.meta.env.PROD': 'false' },
    plugins: [{ name: 'pwa-layout-boundaries', setup(builder) {
      builder.onResolve({ filter: /PwaStatus\.vue$/ }, args => ({ path: args.path, namespace: 'pwa' }))
      builder.onLoad({ filter: /.*/, namespace: 'pwa' }, () => ({
        contents: compile(new URL('./PwaStatus.vue', import.meta.url)), loader: 'ts',
        resolveDir: fileURLToPath(new URL('.', import.meta.url)) }))
      builder.onResolve({ filter: /^(vue-router)|langfuse$|desktop-transport\.mjs$/ }, args => ({ path: args.path, namespace: 'boundary' }))
      builder.onLoad({ filter: /.*/, namespace: 'boundary' }, args => ({ contents:
        args.path === 'vue-router' ? `export const useRoute=()=>({path:'/platform/settings',fullPath:'/platform/settings?section=models'});` :
        args.path.endsWith('langfuse') ? `export const autoLoginLangfuse=async()=>{};` :
        `export const desktopBridge=null;`, loader: 'js' }))
    } }],
  })
  return result.outputFiles[0].text
}

test('installation notice and expanded help leave model roles and account controls clickable at supported widths', async () => {
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage()
    const script = await bundle()
    for (const [width, height] of [[1280, 860], [1440, 900], [1024, 768], [390, 844]]) {
      await page.setViewportSize({ width, height })
      await page.setContent('<div id="app"></div>')
      await page.addStyleTag({ content: css + `
        .fixture-page{min-height:0;display:flex;flex-direction:column;padding:12px;overflow:auto}
        .fixture-space{flex:1;min-height:100px}
        .fixture-roles{display:flex;justify-content:flex-end;flex-wrap:wrap;gap:4px}
        .fixture-roles button{min-height:44px;min-width:60px}
        @media(min-width:761px){.sidebar{display:flex;flex-direction:column;justify-content:flex-end}}
      ` })
      await page.addScriptTag({ content: script })
      const notice = page.getByRole('complementary', { name: '应用连接与安装' })
      await notice.waitFor()
      for (const expanded of [false, true]) {
        if (expanded) await notice.getByRole('button', { name: '主屏幕安装说明' }).click()
        for (const role of ['ReRank', '视觉']) {
          await page.getByRole('button', { name: role, exact: true }).click({ timeout: 1200 })
          assert.equal(await page.evaluate(() => document.body.dataset.selected), role, `${width}×${height}`)
        }
        const dimensions = await page.evaluate(() => {
          const shell = document.querySelector('.shell').getBoundingClientRect()
          const notice = document.querySelector('.pwa-status').getBoundingClientRect()
          return { noticeBottom: notice.bottom, shellTop: shell.top, shellBottom: shell.bottom,
            viewport: innerHeight, overflow: document.documentElement.scrollWidth > innerWidth }
        })
        assert.ok(dimensions.noticeBottom <= dimensions.shellTop + 1, 'notice occupies layout space above the business page')
        assert.ok(dimensions.shellBottom <= dimensions.viewport + 1, 'shell uses the remaining viewport height')
        assert.equal(dimensions.overflow, false)
        if (width > 760) {
          const box = await page.getByRole('button', { name: '账户与设置' }).boundingBox()
          assert.ok(box && box.y + box.height <= height + 1, 'account controls remain inside the reduced shell')
        }
      }
    }
  } finally { await browser.close() }
})
