import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import assert from 'node:assert/strict'

const __dirname = dirname(fileURLToPath(import.meta.url))
const css = readFileSync(resolve(__dirname, './app.css'), 'utf8')
const platformVue = readFileSync(resolve(__dirname, '../views/Platform.vue'), 'utf8')

const topbarBlock = css.match(/\.topbar\s*\{(?<body>[\s\S]*?)\n\}/)?.groups.body || ''
const topbarHeadingBlock = css.match(/\.topbar h1\s*\{(?<body>[\s\S]*?)\n\}/)?.groups.body || ''
const userChipBlock = css.match(/\.user-chip\s*\{(?<body>[\s\S]*?)\n\}/)?.groups.body || ''

assert.match(topbarBlock, /min-height:\s*52px;/, 'topbar should use a compact desktop height')
assert.match(topbarBlock, /padding:\s*0 24px;/, 'topbar should use tighter horizontal padding')
assert.match(topbarHeadingBlock, /font-size:\s*21px;/, 'topbar title should be scaled down for the compact header')
assert.match(userChipBlock, /padding:\s*6px 11px;/, 'user chip should be thinner inside the compact topbar')
assert.doesNotMatch(platformVue, /<div class="paper-kicker">Workspace<\/div>/, 'topbar should not render the Workspace kicker')
assert.doesNotMatch(platformVue, /auth\.tenant\?\.name \|\| '默认空间'/, 'topbar should not render the tenant-space subtitle')
