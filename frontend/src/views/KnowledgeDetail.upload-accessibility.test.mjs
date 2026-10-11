import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { build } from 'esbuild'
import { compileScript, parse } from '@vue/compiler-sfc'
import { chromium } from '@playwright/test'

// Render the actual component; stub only its network/router and unrelated widgets.
// This exercises native browser keyboard activation and the real queueUpload handler.
const source = readFileSync(new URL('./KnowledgeDetail.vue', import.meta.url), 'utf8')
const { descriptor } = parse(source)
const compiled = compileScript(descriptor, { id: 'upload-accessibility', inlineTemplate: true }).content

async function componentBundle() {
  const result = await build({
    stdin: { contents: compiled.replace('export default', 'const DetailComponent=') + `\nimport {createApp,h} from 'vue'; const app=createApp(DetailComponent); const wrapper={props:['visible'],render(){return this.visible===false?null:h('section',this.$slots.default?.())}}; const button={render(){return h('button',this.$slots.default?.())}}; for(const n of ['t-dialog','t-drawer'])app.component(n,wrapper); app.component('t-button',button); for(const n of ['t-input','t-select','t-option','t-tag','t-pagination','t-textarea'])app.component(n,{render(){return null}}); app.mount('#app');`, loader: 'ts', resolveDir: fileURLToPath(new URL('.', import.meta.url)) },
    bundle: true, write: false, format: 'iife',
    plugins: [{ name: 'fixture-boundaries', setup(builder) {
      builder.onResolve({ filter: /^(vue-router|tdesign-vue-next|\.\.\/api)$|\.vue$/ }, args => ({ path: args.path, namespace: 'fixture' }))
      builder.onLoad({ filter: /.*/, namespace: 'fixture' }, args => ({ contents:
        args.path === 'vue-router' ? `export const useRoute=()=>({params:{kbId:'kb'},query:{}}); export const useRouter=()=>({replace(){},push(){}})` :
        args.path === 'tdesign-vue-next' ? `export const MessagePlugin={success(){},warning(){},error(){}}` :
        args.path === '../api' ? `export const normalizeChunkingConfig=(value)=>value||{strategy:'heading',chunk_size:512}; export const chunkingConfigError=()=>''; export const api={getKb:async()=>({data:{id:'kb',name:'keyboard fixture',chunking_config:{strategy:'heading',chunk_size:512}}}),listTags:async()=>({data:{items:[]}}),listKnowledge:async()=>({data:{items:[]}})};` :
        `export default {render(){return null}}`, loader: 'js' }))
    } }],
  })
  return result.outputFiles[0].text
}

test('all file pickers are keyboard buttons that activate only their owned input', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'knowledge-keyboard-'))
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage({ viewport: { width: 390, height: 844 } })
    await page.setContent('<div id="app"></div>')
    await page.addScriptTag({ content: await componentBundle() })
    await page.getByRole('heading', { name: 'keyboard fixture', exact: true }).waitFor()
    const upload = page.getByRole('button', { name: '上传文件', exact: true })
    assert.equal(await upload.count(), 1, 'main upload entry must expose the native button role')
    async function choose(button, key, file) {
      await button.focus()
      const chooserPromise = page.waitForEvent('filechooser', { timeout: 2000 })
      await button.press(key)
      const chooser = await chooserPromise
      if (file) await chooser.setFiles(file)
      return chooser
    }
    const fixture = join(directory, 'keyboard.txt')
    await writeFile(fixture, 'keyboard source')
    const first = await choose(upload, 'Enter', fixture)
    assert.equal(first.isMultiple(), true)
    assert.equal(await page.getByText('keyboard.txt', { exact: true }).count(), 1)
    const more = page.getByRole('button', { name: '+ 添加更多', exact: true })
    assert.equal(await more.getAttribute('type'), 'button')
    assert.equal((await choose(more, 'Space', fixture)).isMultiple(), true)
    assert.equal(await page.getByText('keyboard.txt', { exact: true }).count(), 1, 'same file remains deduplicated')
    await page.getByRole('button', { name: '拍照 / 选图', exact: true }).press('Enter')
    const select = page.getByRole('button', { name: '选择文件', exact: true })
    assert.equal(await select.getAttribute('type'), 'button')
    assert.equal((await choose(select, 'Space')).isMultiple(), true)
    const camera = page.getByRole('button', { name: '拍照 / 选图', exact: true }).last()
    const photoChooser = await choose(camera, 'Enter')
    assert.equal(photoChooser.isMultiple(), false)
    assert.equal(await photoChooser.element().getAttribute('accept'), 'image/jpeg,image/png,image/webp')
    assert.equal(await photoChooser.element().getAttribute('capture'), 'environment')
  } finally { await browser.close(); await rm(directory, { recursive: true, force: true }) }
})
