import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { build } from 'esbuild'
import { compileScript, compileStyle, parse } from '@vue/compiler-sfc'
import { chromium } from '@playwright/test'

// UI-011: actual Settings markup and application styles, with deterministic API data.
// This browser regression checks visible layout, not vendor calls or desktop acceptance.
const id = 'settings-layout'
const { descriptor } = parse(readFileSync(new URL('./Settings.vue', import.meta.url), 'utf8'))
const script = compileScript(descriptor, { id, inlineTemplate: true }).content
const styles = [
  readFileSync(new URL('../../node_modules/tdesign-vue-next/es/style/index.css', import.meta.url), 'utf8'),
  readFileSync(new URL('../styles/app.css', import.meta.url), 'utf8'),
  readFileSync(new URL('../styles/mobile.css', import.meta.url), 'utf8'),
  ...descriptor.styles.map(style => {
    const result = compileStyle({ source: style.content, filename: 'Settings.vue', id: `data-v-${id}`, scoped: style.scoped })
    assert.deepEqual(result.errors, [])
    return result.code
  }),
].join('\n')

async function bundle() {
  const result = await build({
    stdin: {
      contents: script.replace('export default', 'const SettingsComponent=') + `\nimport {createApp} from 'vue'; import TDesign from 'tdesign-vue-next'; SettingsComponent.__scopeId='data-v-${id}'; createApp(SettingsComponent).use(TDesign).mount('#settings-fixture');`,
      loader: 'ts', resolveDir: fileURLToPath(new URL('.', import.meta.url)),
    },
    bundle: true, write: false, format: 'iife', loader: { '.css': 'empty' },
    plugins: [{ name: 'layout-fixture-boundaries', setup(builder) {
      builder.onResolve({ filter: /^(vue-router|\.\.\/api|\.\.\/stores\/auth)$|\.vue$/ }, args => ({ path: args.path, namespace: 'fixture' }))
      builder.onLoad({ filter: /.*/, namespace: 'fixture' }, args => ({ contents:
        args.path === 'vue-router' ? `export const useRoute=()=>({query:{section:'models'}}); export const useRouter=()=>({replace(){},push(){}});` :
        args.path === '../stores/auth' ? `export const useAuthStore=()=>({});` :
        args.path === '../api' ? `const usage={total:{calls:126,total_tokens:194000,prompt_tokens:130000,completion_tokens:64000,failed:2,success_rate:.98},cache:{cached_tokens:37000,prompt_rate:.282,total_rate:.189},by_model:[{model_id:'chat',model_name:'glm-5.3-flash',total_tokens:182000},{model_id:'embedding',model_name:'BAAI/bge-m3',total_tokens:7746},{model_id:'rerank',model_name:'BAAI/bge-reranker-v2-m3',total_tokens:1448}],cache_series:{buckets:[],models:[]}}; export const api=new Proxy({modelUsage:async()=>({data:usage}),listModels:async()=>({data:{items:[],total:0}}),me:async()=>({data:{user:{username:'layout-fixture'}}}),getTenantKv:async()=>({data:{value:{}}})},{get:(target,key)=>target[key]||(async()=>({data:{}}))});` :
        `export default {render(){return null}};`, loader: 'js' }))
    } }],
  })
  return result.outputFiles[0].text
}

test('UI-011 model usage cards and ranking remain inside the settings content at supported widths', async () => {
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage()
    await page.setContent('<div class="shell"><aside class="sidebar"></aside><section class="workspace"><div id="settings-fixture"></div></section></div>')
    await page.addStyleTag({ content: styles })
    await page.addScriptTag({ content: await bundle() })
    await page.locator('.usage-row').first().waitFor()
    for (const [width, height] of [[1280, 860], [1440, 900], [1024, 768], [390, 844]]) {
      await page.setViewportSize({ width, height })
      const dimensions = await page.evaluate(() => {
        const section = document.querySelector('.settings-section')
        const bounds = section.getBoundingClientRect(), style = getComputedStyle(section)
        return {
          left: bounds.left + parseFloat(style.paddingLeft), right: bounds.right - parseFloat(style.paddingRight),
          cards: [...document.querySelectorAll('.usage-stat,.usage-rank')].map(node => {
            const rect = node.getBoundingClientRect()
            return { className: node.className, left: rect.left, right: rect.right }
          }),
          pageWidth: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth,
        }
      })
      assert.equal(dimensions.cards.length, 4)
      for (const card of dimensions.cards) {
        assert.ok(card.left >= dimensions.left - 1 && card.right <= dimensions.right + 1,
          `${width}×${height}: ${card.className} is clipped: ${JSON.stringify({ card, content: [dimensions.left, dimensions.right] })}`)
      }
      assert.ok(dimensions.scrollWidth <= dimensions.pageWidth + 1, `${width}×${height}: page overflows horizontally`)
    }
  } finally { await browser.close() }
})
