import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import assert from 'node:assert/strict'

const __dirname = dirname(fileURLToPath(import.meta.url))
const read = (path) => readFileSync(resolve(__dirname, path), 'utf8')

const css = read('./app.css')
const platform = read('../views/Platform.vue')
const knowledgeBases = read('../views/KnowledgeBases.vue')
const detail = read('../views/KnowledgeDetail.vue')
const wiki = read('../views/Wiki.vue')
const chat = read('../views/Chat.vue')
const chatInput = read('../views/chat/components/ChatInput.vue')
const login = read('../views/Login.vue')

assert.match(platform, /label:\s*'新对话'/, 'desktop navigation should use the approved new-chat label')
assert.match(platform, /class="account-entry"/, 'desktop shell should expose the merged account/settings entry')
assert.match(platform, /账户与设置/, 'merged account entry should name its purpose')
const accountEntry = platform.match(/<div class="account-entry">(?<body>[\s\S]*?)<\/div>\s*<\/div>\s*<\/aside>/)?.groups.body || ''
assert.doesNotMatch(accountEntry, /SettingIcon|Setting1Icon|⚙/, 'merged account entry must not render a settings gear')
assert.match(platform, /class="account-menu"/, 'account chevron should open a menu')
assert.match(platform, /最近访问/, 'desktop sidebar should render recent resources')

assert.match(css, /grid-template-columns:\s*240px minmax\(0,\s*1fr\)/, 'desktop shell should use a 240px sidebar')
assert.match(css, /@media \(max-width:\s*1080px\)/, 'tablet compact-sidebar breakpoint should exist')
assert.match(css, /grid-template-columns:\s*76px minmax\(0,\s*1fr\)/, 'tablet shell should use a 76px sidebar rail')
assert.match(css, /@media \(max-width:\s*760px\)/, 'mobile bottom-navigation breakpoint should remain 760px')
assert.match(css, /prefers-reduced-motion:\s*reduce/, 'motion should respect reduced-motion preferences')

for (const label of ['全部', '收藏', '最近', '本空间']) {
  assert.match(knowledgeBases, new RegExp(`label:\\s*'${label}'`), `knowledge scope should include ${label}`)
}
assert.match(detail, /activeTab === 'processing'/, 'knowledge detail should expose a processing-records tab')
assert.match(detail, />解析记录</, 'knowledge detail should render the processing-records label')
assert.match(detail, /KnowledgeProcessingRecords/, 'knowledge detail should delegate processing records to a focused component')
assert.doesNotMatch(detail, /activeTab === 'settings'/, 'knowledge settings should no longer occupy a workspace tab')

assert.match(wiki, /wiki-index-search/, 'Wiki pages should provide a searchable page index')
assert.match(wiki, /wiki-reader-outline/, 'wide Wiki readers should expose a document outline')
assert.match(wiki, />刷新 Wiki</, 'Wiki refresh should be a real refresh action')

assert.match(chatInput, /function setQuery\(text:\s*string\)/, 'ChatInput should expose setQuery for prompt suggestions')
assert.match(chatInput, /defineExpose\(\{\s*applyState,\s*setQuery\s*\}\)/, 'ChatInput public surface should include setQuery')
assert.match(chat, /quickPrompts/, 'new-chat page should define quick prompts')
assert.match(chat, /class="quick-prompt-list"/, 'new-chat page should render quick prompt buttons')

assert.match(login, /class="login-brand"/, 'login should use an explicit brand panel')
assert.match(login, /const email = ref\(''\)/, 'login email must not be prefilled')
assert.match(login, /const password = ref\(''\)/, 'login password must not be prefilled')

console.log('WeKnora redesign contract assertions passed')
