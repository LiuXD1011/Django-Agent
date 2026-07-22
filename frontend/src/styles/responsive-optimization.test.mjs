import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import assert from 'node:assert/strict'

const __dirname = dirname(fileURLToPath(import.meta.url))
const css = readFileSync(resolve(__dirname, './app.css'), 'utf8')
const platform = readFileSync(resolve(__dirname, '../views/Platform.vue'), 'utf8')
const detail = readFileSync(resolve(__dirname, '../views/KnowledgeDetail.vue'), 'utf8')
const settings = readFileSync(resolve(__dirname, '../views/Settings.vue'), 'utf8')
const mobileBreakpointStart = css.indexOf('@media (max-width: 760px)')
const mobileBreakpointEnd = css.indexOf('/* ── Memory warning', mobileBreakpointStart)
const mobileCss = css.slice(mobileBreakpointStart, mobileBreakpointEnd)

assert.match(css, /\.mobile-tab-bar\s*\{/, 'mobile navigation should have a dedicated bottom bar')
assert.match(css, /position:\s*fixed;/, 'mobile tab bar should stay visible while scrolling')
assert.match(platform, /mobile-tab-bar/, 'platform should render mobile navigation')
assert.match(detail, /document-card-list/, 'knowledge detail should expose mobile document cards')
assert.match(detail, /v-if="isMobileDocumentView"/, 'mobile document view should be explicit')
assert.match(
  mobileCss,
  /\.kb-detail-shell\s*\{[^}]*grid-template-columns:\s*1fr;/s,
  'mobile knowledge detail should stack filters above the document workbench',
)
assert.match(settings, /Promise\.allSettled/, 'settings bootstrap should tolerate partial API failures')
