import assert from 'node:assert/strict'
import { renderMarkdownLite } from './markdown-lite.mjs'

const html = renderMarkdownLite('## 概述\n\n- 工业结构健康监测\n- 远程生理信号检测\n\n<script>alert(1)</script>')

assert.match(html, /<h3>概述<\/h3>/, 'level-2 Markdown headings should render as h3')
assert.match(html, /<ul><li>工业结构健康监测<\/li><li>远程生理信号检测<\/li><\/ul>/, 'dash lists should render as unordered lists')
assert.doesNotMatch(html, /## 概述/, 'raw Markdown heading markers should not remain visible')
assert.doesNotMatch(html, /<script>/, 'raw HTML should stay escaped')
assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/, 'escaped HTML text should remain readable')

const tableHtml = renderMarkdownLite('| 名称 | 状态 |\n|---|---|\n| Wiki | success |')
assert.match(tableHtml, /<table><thead><tr><th>名称<\/th><th>状态<\/th><\/tr><\/thead><tbody>/, 'GFM tables should render header and body sections')
assert.match(tableHtml, /<td>success<\/td>/, 'GFM tables should render body cells')
assert.match(renderMarkdownLite('---'), /<hr>/, 'horizontal rules should render as hr elements')

const codeHtml = renderMarkdownLite('```js\nconst markdown = "## unchanged"\n```')
assert.match(codeHtml, /<pre><code class="lang-js">const markdown = "## unchanged"<\/code><\/pre>/, 'fenced code should preserve its contents')
assert.doesNotMatch(codeHtml, /<h3>unchanged<\/h3>/, 'Markdown markers inside fenced code should not be parsed')

const unsafeLinkHtml = renderMarkdownLite('[bad](javascript:alert(1))')
assert.match(unsafeLinkHtml, /<a href="#"/, 'unsafe links should be replaced with a harmless fragment')
assert.doesNotMatch(unsafeLinkHtml, /javascript:/i, 'unsafe link protocols must not be emitted')
assert.match(
  renderMarkdownLite('[external](//example.com)'),
  /<a href="#"/,
  'protocol-relative links should not bypass the protocol allowlist',
)
assert.match(
  renderMarkdownLite('[safe](https://example.com/docs)'),
  /<a href="https:\/\/example\.com\/docs" target="_blank" rel="noopener noreferrer">safe<\/a>/,
  'HTTPS links should remain usable and protected',
)
const quotedLinkHtml = renderMarkdownLite('[quoted](https://example.com" onclick="alert(1))')
assert.doesNotMatch(quotedLinkHtml, /" onclick="/, 'link URLs must not be able to inject HTML attributes')

const reviewFailures = []
const reviewAssertion = (name, callback) => {
  try {
    callback()
  } catch (error) {
    error.message = `${name}: ${error.message}`
    reviewFailures.push(error)
  }
}

const blockCollision = '\u00000\u0000'
reviewAssertion('literal block-placeholder-shaped input remains text', () => {
  const collisionHtml = renderMarkdownLite(`before${blockCollision}after`)
  assert.match(collisionHtml, new RegExp(blockCollision))
  assert.doesNotMatch(collisionHtml, /undefined/)
})
reviewAssertion('literal block-placeholder-shaped input is not replaced by generated code markup', () => {
  const collisionHtml = renderMarkdownLite(`${blockCollision}\n\n\`\`\`text\nactual code\n\`\`\``)
  assert.match(collisionHtml, new RegExp(blockCollision))
  assert.equal((collisionHtml.match(/<pre>/g) || []).length, 1)
})

const inlineCollision = '\u00010\u0001'
reviewAssertion('literal inline-placeholder-shaped input remains text', () => {
  const collisionHtml = renderMarkdownLite(`before${inlineCollision}after`)
  assert.match(collisionHtml, new RegExp(inlineCollision))
  assert.doesNotMatch(collisionHtml, /undefined/)
})
reviewAssertion('literal inline-placeholder-shaped input is not replaced by generated inline markup', () => {
  const collisionHtml = renderMarkdownLite(`${inlineCollision} and \`actual code\``)
  assert.match(collisionHtml, new RegExp(inlineCollision))
  assert.equal((collisionHtml.match(/<code>/g) || []).length, 1)
})

reviewAssertion('backticks inside fenced code do not close the fence', () => {
  const fencedHtml = renderMarkdownLite('```js\nconst marker = "```"\nconst complete = true\n```')
  assert.match(fencedHtml, /<pre><code class="lang-js">const marker = "```"\nconst complete = true<\/code><\/pre>/)
  assert.doesNotMatch(fencedHtml, /<p>"/)
})

reviewAssertion('GFM tables allow omitted outer pipes', () => {
  const noOuterPipesHtml = renderMarkdownLite('名称 | 状态\n--- | ---\nWiki | success')
  assert.match(noOuterPipesHtml, /<table><thead>/)
  assert.match(noOuterPipesHtml, /<th>名称<\/th><th>状态<\/th>/)
  assert.match(noOuterPipesHtml, /<td>Wiki<\/td><td>success<\/td>/)
})

reviewAssertion('safe links preserve balanced URL parentheses', () => {
  const balancedLinkHtml = renderMarkdownLite('[docs](https://example.com/api/items_(archived)?filter=(active))')
  assert.match(
    balancedLinkHtml,
    /<a href="https:\/\/example\.com\/api\/items_\(archived\)\?filter=\(active\)" target="_blank" rel="noopener noreferrer">docs<\/a>/,
  )
  assert.doesNotMatch(balancedLinkHtml, /<\/a>\)/)
})

reviewAssertion('unsafe balanced links are fully consumed and sanitized', () => {
  const balancedUnsafeHtml = renderMarkdownLite('[bad](javascript:alert(1))')
  assert.match(balancedUnsafeHtml, /<a href="#" target="_blank" rel="noopener noreferrer">bad<\/a>/)
  assert.doesNotMatch(balancedUnsafeHtml, /javascript:|<\/a>\)/i)
})

reviewAssertion('mixed slash and backslash root-like links are rejected', () => {
  const mixedSlashHtml = renderMarkdownLite('[bad](/\\evil.example/path)')
  assert.match(mixedSlashHtml, /<a href="#" target="_blank" rel="noopener noreferrer">bad<\/a>/)
})

reviewAssertion('percent-encoded backslashes in path-like links are rejected', () => {
  const encodedSlashHtml = renderMarkdownLite('[bad](/%5Cevil.example/path)')
  assert.match(encodedSlashHtml, /<a href="#" target="_blank" rel="noopener noreferrer">bad<\/a>/)
})

reviewAssertion('HTML-entity-encoded backslashes in path-like links are rejected', () => {
  const encodedSlashHtml = renderMarkdownLite('[bad](/&#92;evil.example/path)')
  assert.match(encodedSlashHtml, /<a href="#" target="_blank" rel="noopener noreferrer">bad<\/a>/)
})

reviewAssertion('control-obfuscated mixed slash links are rejected', () => {
  const obfuscatedSlashHtml = renderMarkdownLite('[bad](/\u0009\\evil.example/path)')
  assert.match(obfuscatedSlashHtml, /<a href="#" target="_blank" rel="noopener noreferrer">bad<\/a>/)
})

reviewAssertion('normal root and relative links remain allowed', () => {
  const rootHtml = renderMarkdownLite('[root](/docs/page)')
  const relativeHtml = renderMarkdownLite('[relative](docs/page)')
  assert.match(rootHtml, /<a href="\/docs\/page" target="_blank" rel="noopener noreferrer">root<\/a>/)
  assert.match(relativeHtml, /<a href="docs\/page" target="_blank" rel="noopener noreferrer">relative<\/a>/)
})

reviewAssertion('inline LaTeX renders as KaTeX markup', () => {
  const mathHtml = renderMarkdownLite('放大因子 $\\alpha$ 控制噪声水平')
  assert.match(mathHtml, /class="katex"/, 'inline math should be rendered by KaTeX')
  assert.match(mathHtml, /α/, 'Greek letters should be rendered as symbols')
  assert.doesNotMatch(mathHtml, /\$\\alpha\$/, 'raw LaTeX delimiters should not remain visible')
})

reviewAssertion('inline LaTeX inside table cells renders as KaTeX markup', () => {
  const tableMathHtml = renderMarkdownLite('| 符号 | 含义 |\n|---|---|\n| $\\delta(t)$ | 微小位移 |')
  assert.match(tableMathHtml, /<td><span class="katex">/, 'math inside table cells should be rendered')
  assert.doesNotMatch(tableMathHtml, /\$\\delta/, 'raw LaTeX should not leak into table cells')
})

reviewAssertion('display math renders as KaTeX display block', () => {
  const displayHtml = renderMarkdownLite('公式如下：\n\n$$\nI(x,t) = f(x + \\delta(t))\n$$\n\n完毕')
  assert.match(displayHtml, /katex-display/, 'display math should use the display block class')
  assert.doesNotMatch(displayHtml, /\$\$/, 'raw $$ delimiters should not remain visible')
})

reviewAssertion('LaTeX in fenced code stays untouched', () => {
  const fencedMathHtml = renderMarkdownLite('```\n$\\alpha$ and $$\\beta$$\n```')
  assert.doesNotMatch(fencedMathHtml, /class="katex"/, 'math inside fenced code must not be rendered')
  assert.match(fencedMathHtml, /\$\\alpha\$ and \$\$\\beta\$\$/, 'fenced code content should be preserved verbatim')
})

reviewAssertion('currency-like dollar amounts are not treated as math', () => {
  const currencyHtml = renderMarkdownLite('价格从 $5 涨到 $10')
  assert.doesNotMatch(currencyHtml, /class="katex"/, 'currency amounts should stay plain text')
  assert.match(currencyHtml, /\$5/, 'currency text should remain visible')
})

reviewAssertion('bracket-delimited LaTeX renders as KaTeX markup', () => {
  const bracketHtml = renderMarkdownLite('设 \\(I(x,t)\\) 为图像信号')
  assert.match(bracketHtml, /class="katex"/, '\\(...\\) inline math should be rendered')
  assert.doesNotMatch(bracketHtml, /\\\(/, 'raw bracket delimiters should not remain visible')
})

if (reviewFailures.length) {
  throw new AggregateError(reviewFailures, `${reviewFailures.length} Markdown review regression assertions failed`)
}
