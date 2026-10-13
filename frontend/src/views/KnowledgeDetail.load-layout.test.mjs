import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { build } from 'esbuild'
import { compileScript, compileStyle, parse } from '@vue/compiler-sfc'
import { chromium } from '@playwright/test'

const directory = fileURLToPath(new URL('.', import.meta.url))
const id = 'data-v-kb-load-layout'
let bundled
async function bundle() {
  bundled ??= build({
    stdin: { contents: `import Detail from 'load-layout:detail';
      import {createApp,h} from 'vue'; import {createRouter,createMemoryHistory,RouterView} from 'vue-router';
      import ActualButton from 'tdesign-vue-next/es/button/button.mjs';
      import 'tdesign-vue-next/es/style/index.css'; import '../styles/app.css'; import '../styles/mobile.css';
      const router=createRouter({history:createMemoryHistory(),routes:[
        {path:'/platform/knowledge-bases/:kbId',component:Detail},
        {path:'/platform/knowledge-bases',component:{render:()=>h('main',{class:'content'},[h('h2','知识库列表')])}}
      ]}); window.fixtureRouter=router;
      const app=createApp({render:()=>h('div',{class:'app-frame'},[h('div',{class:'shell'},[
        h('aside',{class:'sidebar'},'受控侧栏'),h('section',{class:'workspace'},[h(RouterView)])
      ])])}); app.use(router); app.component('t-button',ActualButton);
      for(const name of ['t-input','t-select','t-option','t-tag','t-pagination','t-textarea','t-drawer','t-dialog'])app.component(name,{render:()=>null});
      router.push('/platform/knowledge-bases/removed').then(()=>router.isReady()).then(()=>app.mount('#app'));`, loader: 'ts', resolveDir: directory },
    bundle: true, write: false, format: 'iife', outdir: '/virtual/kb-load-layout',
    plugins: [{ name: 'controlled-load-io', setup(builder) {
      builder.onResolve({ filter: /^load-layout:/ }, args => ({ path: args.path, namespace: 'production' }))
      builder.onLoad({ filter: /.*/, namespace: 'production' }, args => {
        const { descriptor } = parse(readFileSync(new URL('./KnowledgeDetail.vue', import.meta.url), 'utf8'))
        if (args.path.endsWith(':style')) {
          const style = compileStyle({ source: descriptor.styles.map(style => style.content).join('\n'), filename: 'KnowledgeDetail.vue', id, scoped: true })
          assert.deepEqual(style.errors, [])
          return { contents: style.code, loader: 'css', resolveDir: directory }
        }
        const script = compileScript(descriptor, { id, inlineTemplate: true, genDefaultAs: 'Detail' }).content
        return { contents: script + `\nDetail.__scopeId='${id}'; export default Detail; import 'load-layout:style';`, loader: 'ts', resolveDir: directory }
      })
      builder.onResolve({ filter: /^\/src\/assets\// }, args => ({ path: args.path, external: true }))
      builder.onResolve({ filter: /^(tdesign-vue-next|\.\.\/api)$|\.vue$/ }, args => ({ path: args.path, namespace: 'fixture' }))
      builder.onLoad({ filter: /.*/, namespace: 'fixture' }, args => ({ contents:
        args.path === 'tdesign-vue-next' ? `export const MessagePlugin={success(){},warning(){},error(){}};` :
        args.path === '../api' ? `export const normalizeChunkingConfig=v=>v||{}; export const chunkingConfigError=()=>'';
          window.fixtureReads=[];
          export const api={getKb:async id=>{window.fixtureReads.push(id);
            if(window.fixtureMode==='pending')return new Promise(resolve=>window.fixtureRelease=()=>resolve({data:{id,name:'加载成功'}}));
            if(window.fixtureMode==='unavailable')throw {status:404};
            if(window.fixtureReads.length===1)throw {status:500};
            return {data:{id,name:'重试成功'}};
          },listTags:async()=>({data:{items:[]}}),listKnowledge:async()=>({data:{items:[],status_counts:{}}})};` :
        `export default{render:()=>null};`, loader: 'js' }))
    } }],
  }).then(result => ({ script: result.outputFiles.find(file => file.path.endsWith('.js')).text, style: result.outputFiles.find(file => file.path.endsWith('.css')).text }))
  return bundled
}

async function fixture(viewport, mode) {
  const { script, style } = await bundle()
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage({ viewport })
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.route('**/*', route => new URL(route.request().url()).pathname === '/' ? route.fulfill({ contentType: 'text/html', body: '<div id="app"></div>' }) : route.abort())
    await page.goto('http://load-layout.fixture.test/')
    await page.addStyleTag({ content: style })
    await page.evaluate(mode => { window.fixtureMode = mode }, mode)
    await page.addScriptTag({ content: script })
    await page.getByRole(mode === 'pending' ? 'status' : 'alert').waitFor({ timeout: 2000 })
    await page.waitForLoadState('networkidle')
    await page.locator('main').evaluate(async node => { await Promise.all(node.getAnimations().map(animation => animation.finished)) })
    return { page, errors, close: () => browser.close() }
  } catch (error) { await browser.close(); throw error }
}

async function inspectButton(button) {
  return button.evaluate(node => {
    const rect = node.getBoundingClientRect()
    const box = rect => ({ left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom, width: rect.width, height: rect.height })
    const clips = []
    for (let parent = node.parentElement; parent; parent = parent.parentElement) {
      const css = getComputedStyle(parent), bounds = parent.getBoundingClientRect()
      if (css.overflowX !== 'visible' || css.overflowY !== 'visible') clips.push({ className: parent.className, rect: box(bounds), x: css.overflowX, y: css.overflowY })
    }
    const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2)
    return { button: node.textContent, rect: box(rect), viewport: { width: innerWidth, height: innerHeight }, clips, centerHitButton: hit === node || node.contains(hit), hitTag: hit?.tagName }
  })
}

function assertUsable(audit) {
  assert.ok(audit.rect.width > 0 && audit.rect.height > 0)
  assert.ok(audit.rect.left >= 0 && audit.rect.top >= 0 && audit.rect.right <= audit.viewport.width && audit.rect.bottom <= audit.viewport.height, 'button must be entirely inside the viewport')
  for (const clip of audit.clips) {
    if (clip.x !== 'visible') assert.ok(audit.rect.left >= clip.rect.left - 1 && audit.rect.right <= clip.rect.right + 1, `${audit.button} is horizontally clipped by ${clip.className}`)
    if (clip.y !== 'visible') assert.ok(audit.rect.top >= clip.rect.top - 1 && audit.rect.bottom <= clip.rect.bottom + 1, `${audit.button} is vertically clipped by ${clip.className}`)
  }
  assert.equal(audit.centerHitButton, true, `button center hit ${audit.hitTag} instead of its actual button`)
}

// KB-DETAIL-LOAD-002: Root Orca 004/006 found the return button below a clipped
// 112px panel. Test real global/mobile CSS, compiled scoped SFC CSS, real installed
// TDesign Button and the production Vue/router path. The browser is isolated and
// headless; API IO is controlled and no real service/auth/QA state is accessed.
for (const viewport of [{ width: 1289, height: 921 }, { width: 1024, height: 768 }]) {
  for (const mode of ['unavailable', 'retryable', 'pending']) {
    test(`${mode} load actions are unclipped and pointer usable at ${viewport.width}x${viewport.height}`, async () => {
      const f = await fixture(viewport, mode)
      try {
        const back = f.page.getByRole('button', { name: '返回知识库', exact: true })
        const audit = await inspectButton(back)
        console.log(JSON.stringify({ mode, viewport, ...audit }))
        assertUsable(audit)
        if (mode === 'retryable') {
          const retry = f.page.getByRole('button', { name: '重试', exact: true })
          const retryAudit = await inspectButton(retry)
          console.log(JSON.stringify({ mode, viewport, ...retryAudit }))
          assertUsable(retryAudit)
          await retry.click({ timeout: 2000 })
          await f.page.getByRole('heading', { name: '重试成功', exact: true }).waitFor({ timeout: 2000 })
          assert.deepEqual(await f.page.evaluate(() => window.fixtureReads), ['removed', 'removed'])
          await f.page.getByRole('button', { name: '← 返回知识库', exact: true }).click({ timeout: 2000 })
        } else await back.click({ timeout: 2000 })
        await f.page.getByRole('heading', { name: '知识库列表', exact: true }).waitFor({ timeout: 2000 })
        assert.equal(await f.page.evaluate(() => window.fixtureRouter.currentRoute.value.path), '/platform/knowledge-bases')
        assert.deepEqual(f.errors, [])
      } finally { await f.close() }
    })
  }
}
