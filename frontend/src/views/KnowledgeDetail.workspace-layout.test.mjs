import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import assert from 'node:assert/strict'

const __dirname = dirname(fileURLToPath(import.meta.url))
const detailVue = readFileSync(resolve(__dirname, './KnowledgeDetail.vue'), 'utf8')
const wikiVue = readFileSync(resolve(__dirname, './Wiki.vue'), 'utf8')
const css = readFileSync(resolve(__dirname, '../styles/app.css'), 'utf8')

const compactHeaderBlock = css.match(/\.kb-workspace-header\s*\{(?<body>[\s\S]*?)\n\}/)?.groups.body || ''
const detailPageBlock = css.match(/\.kb-detail-page\s*\{(?<body>[\s\S]*?)\n\}/)?.groups.body || ''
const noSideWorkbenchBlock = css.match(/\.kb-detail-shell\.no-side \.kb-main-workbench\s*\{(?<body>[\s\S]*?)\n\}/)?.groups.body || ''
const graphPageBlock = css.match(/\.wiki-graph-page\.embedded\.view-graph\s*\{(?<body>[\s\S]*?)\n\}/)?.groups.body || ''
const graphStageBlock = css.match(/\.wiki-graph-page\.embedded\.view-graph \.wiki-graph-stage\s*\{(?<body>[\s\S]*?)\n\}/)?.groups.body || ''
const graphCanvasBlock = css.match(/\.wiki-graph-page\.embedded\.view-graph \.wiki-graph-canvas\s*\{(?<body>[\s\S]*?)\n\}/)?.groups.body || ''
const pagesPanelBlock = css.match(/\.wiki-graph-page\.embedded\.view-pages \.wiki-pages-panel\s*\{(?<body>[\s\S]*?)\n\}/)?.groups.body || ''
const startPollingBlock = detailVue.match(/function startPolling\(\)\s*\{(?<body>[\s\S]*?)\n\}/)?.groups.body || ''

assert.match(detailVue, /<section class="kb-workspace-header">/, 'knowledge detail should use the compact workspace header')
assert.doesNotMatch(
  detailVue,
  /archive-hero detail-hero kb-profile-strip/,
  'knowledge detail should not render the old large hero profile strip'
)
assert.match(
  detailVue,
  /<aside v-if="activeTab === 'documents'" class="kb-side-panel"/,
  'documents tab should keep the management sidebar'
)
assert.doesNotMatch(detailVue, /loadAllDocs/, 'knowledge detail should not make a duplicate document-list request')
assert.doesNotMatch(detailVue, /page_size:\s*1000/, 'knowledge detail should keep document-list requests bounded')
assert.match(detailVue, /processingRecords\.value\s*=\s*res\.data\?\.processing_records\s*\|\|\s*\[\]/, 'processing records should come from the collection payload')
assert.doesNotMatch(startPollingBlock, /refreshAll\(\)/, 'starting initial polling should not duplicate the collection request already made by load')

assert.match(detailPageBlock, /grid-template-rows:\s*112px minmax\(0,\s*1fr\);/, 'detail page should reserve a compact two-row workspace header')
assert.match(compactHeaderBlock, /grid-template-columns:\s*max-content minmax\(180px,\s*1fr\) auto auto;/, 'workspace header should fit return, title, actions, and stats')
assert.match(noSideWorkbenchBlock, /grid-template-rows:\s*minmax\(0,\s*1fr\);/, 'wiki and graph tabs should let the embedded workspace fill the main area')

assert.match(
  wikiVue,
  /<main class="wiki-graph-page" :class="\[\{ embedded \}, `view-\$\{tab\}`\]">/,
  'embedded Wiki should expose the active view class for layout-specific sizing'
)
assert.match(graphPageBlock, /height:\s*100%;/, 'embedded graph page should be full height')
assert.match(graphStageBlock, /height:\s*100%;/, 'embedded graph stage should fill its parent')
assert.match(graphCanvasBlock, /min-height:\s*0;/, 'embedded graph canvas should not keep the old fixed minimum height')

assert.match(wikiVue, /class="wiki-pages-list"/, 'embedded wiki pages should include a page index column')
assert.match(wikiVue, /class="wiki-page-reader"/, 'embedded wiki pages should include a reader/details column')
assert.match(pagesPanelBlock, /grid-template-columns:\s*245px minmax\(0,\s*1fr\) 170px;/, 'embedded Wiki should use index, reader, and outline columns')
