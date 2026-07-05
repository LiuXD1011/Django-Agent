import assert from 'node:assert/strict'
import { renderMarkdownLite } from './markdown-lite.mjs'

const html = renderMarkdownLite('## 概述\n\n- 工业结构健康监测\n- 远程生理信号检测\n\n<script>alert(1)</script>')

assert.match(html, /<h3>概述<\/h3>/, 'level-2 Markdown headings should render as h3')
assert.match(html, /<ul><li>工业结构健康监测<\/li><li>远程生理信号检测<\/li><\/ul>/, 'dash lists should render as unordered lists')
assert.doesNotMatch(html, /## 概述/, 'raw Markdown heading markers should not remain visible')
assert.doesNotMatch(html, /<script>/, 'raw HTML should stay escaped')
assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/, 'escaped HTML text should remain readable')

