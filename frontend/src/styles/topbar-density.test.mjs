import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import assert from 'node:assert/strict'

const __dirname = dirname(fileURLToPath(import.meta.url))
const css = readFileSync(resolve(__dirname, './app.css'), 'utf8')
const platformVue = readFileSync(resolve(__dirname, '../views/Platform.vue'), 'utf8')

const mobileHeaderBlock = css.match(/\.mobile-page-header\s*\{(?<body>[\s\S]*?)\n\}/)?.groups.body || ''

assert.match(mobileHeaderBlock, /display:\s*none;/, 'desktop layout should not reserve a generic topbar row')
assert.match(css, /@media \(max-width:\s*760px\)[\s\S]*?\.mobile-page-header\s*\{[\s\S]*?display:\s*flex;/, 'mobile layout should restore a compact page header')
assert.doesNotMatch(platformVue, /<div class="paper-kicker">Workspace<\/div>/, 'topbar should not render the Workspace kicker')
assert.doesNotMatch(platformVue, /auth\.tenant\?\.name \|\| '默认空间'/, 'topbar should not render the tenant-space subtitle')
