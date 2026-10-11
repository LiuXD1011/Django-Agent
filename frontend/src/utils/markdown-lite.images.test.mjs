import assert from 'node:assert/strict'
import test, { before, after } from 'node:test'
import { chromium } from '@playwright/test'
import { renderMarkdownLite } from './markdown-lite.mjs'

// Goal F02: actual Chromium decoding, not an HTML substring or mocked image element.
const pixel = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jq1kAAAAASUVORK5CYII=', 'base64')
let browser
before(async () => { browser = await chromium.launch({ headless: true }) })
after(async () => { await browser?.close() })

async function renderedPage(markdown, callback) {
  const page = await browser.newPage()
  const imageRequests = []
  try {
    await page.route('**/*', async route => {
      if (route.request().isNavigationRequest()) {
        await route.fulfill({ contentType: 'text/html; charset=utf-8', body: `<meta charset="utf-8"><main style="width:80px">${renderMarkdownLite(markdown, { wikiLinks: true })}</main>` })
      } else if (route.request().resourceType() === 'image') {
        imageRequests.push({ url: route.request().url(), referer: route.request().headers().referer })
        await route.fulfill({ contentType: 'image/png', body: pixel })
      } else {
        await route.abort()
      }
    })
    await page.goto('http://markdown-fixture.invalid/wiki/page', { waitUntil: 'networkidle' })
    await callback(page, imageRequests)
  } finally { await page.close() }
}

test('F02 images load in Chromium with natural width and balanced absolute/relative URLs', async () => {
  const urls = [
    'http://images-fixture.invalid/a.png',
    'https://images-fixture.invalid/items_(archived).png?filter=(active)&size=1',
    '/images/root.png', './images/local.png', '../images/parent.png', 'images/plain.png',
  ]
  await renderedPage(urls.map((url, i) => `![图片 ${i}](${url})`).join('\n'), async (page, requests) => {
    assert.equal(await page.locator('img').count(), urls.length, 'standard image syntax must create actual image nodes')
    await page.locator('img').last().scrollIntoViewIfNeeded()
    await page.waitForFunction(() => [...document.images].every(image => image.complete && image.naturalWidth > 0), null, { timeout: 3000 })
    const images = await page.locator('img').evaluateAll(nodes => nodes.map(node => ({
      alt: node.alt, width: node.naturalWidth, height: node.naturalHeight,
      source: node.getAttribute('src'), maxWidth: node.style.maxWidth,
      loading: node.loading, decoding: node.decoding, referrerPolicy: node.referrerPolicy,
    })))
    assert.deepEqual(images.map(image => image.source), urls)
    for (const [i, image] of images.entries()) {
      assert.equal(image.alt, `图片 ${i}`)
      assert.equal(image.width, 1)
      assert.equal(image.height, 1)
      assert.equal(image.maxWidth, '100%')
      assert.equal(image.loading, 'lazy')
      assert.equal(image.decoding, 'async')
      assert.equal(image.referrerPolicy, 'no-referrer')
    }
    assert.equal(requests.length, urls.length)
    assert.ok(requests.every(request => request.referer === undefined))
    assert.equal(await page.locator('a').count(), 0, 'image syntax is not a normal hyperlink')
  })
})

test('F02 forbidden image URLs show readable alt without image requests', async () => {
  const urls = [
    'javascript:alert(1)', 'data:image/png;base64,abcd', 'file:///tmp/photo.png',
    'mailto:user@example.invalid', '//outside.invalid/a.png', '/\\outside.invalid/a.png',
    '/%5coutside.invalid/a.png', '/%255coutside.invalid/a.png', '/&#92;outside.invalid/a.png',
    '/&#x5c;outside.invalid/a.png', 'java\tscript:alert(1)', 'java%0ascript:alert(1)',
    'javascript%3aalert(1)', 'javascript&#58;alert(1)', 'javascript&colon;alert(1)',
    '%2f%2foutside.invalid/a.png', '/%2foutside.invalid/a.png', '\\outside.invalid/a.png',
    'https:\\outside.invalid/a.png', 'https:/outside.invalid/a.png',
  ]
  await renderedPage(urls.map((url, i) => `![拒绝图片 ${i}](${url})`).join('\n'), async (page, requests) => {
    assert.equal(await page.locator('img').count(), 0)
    assert.equal(await page.locator('a').count(), 0, 'rejected image syntax must not become a clickable unsafe link')
    const text = await page.locator('main').innerText()
    for (let i = 0; i < urls.length; i += 1) assert.ok(text.includes(`拒绝图片 ${i}`))
    assert.equal(requests.length, 0)
  })
})

test('F02 image alt and URL cannot inject attributes or HTML', async () => {
  await renderedPage('![" onerror="alert(1) <script> & test](https://images-fixture.invalid/quote"onload="bad.png?a=1&b=2)', async (page, requests) => {
    assert.equal(await page.locator('img').count(), 1)
    const image = page.locator('img')
    assert.equal(await image.getAttribute('alt'), '" onerror="alert(1) <script> & test')
    assert.equal(await image.getAttribute('src'), 'https://images-fixture.invalid/quote"onload="bad.png?a=1&b=2')
    assert.equal(await image.getAttribute('onerror'), null)
    assert.equal(await image.getAttribute('onload'), null)
    assert.equal(await page.locator('script').count(), 0)
    assert.equal(requests.length, 1)
  })
})

test('F02 math in image attributes stays readable text while adjacent math renders', async () => {
  await renderedPage('![公式 $x$ " <b>](./images/$x$.png)\n\n正常公式 $y$', async page => {
    assert.equal(await page.locator('img').count(), 1)
    const image = page.locator('img')
    assert.equal(await image.getAttribute('alt'), '公式 $x$ " <b>')
    assert.equal(await image.getAttribute('src'), './images/$x$.png')
    assert.equal(await page.locator('.katex').count(), 1)
    assert.equal(await page.locator('b').count(), 0)
    assert.doesNotMatch(await image.evaluate(node => node.outerHTML), /katex|\uE000|\uE001/)
  })
})

test('F02 image syntax and formula delimiters inside inline/fenced code stay literal', async () => {
  const literal = '![公式 $x$](./images/$x$.png)'
  await renderedPage('`' + literal + '`\n\n```md\n' + literal + '\n```', async (page, requests) => {
    assert.equal(await page.locator('img').count(), 0)
    assert.equal(await page.locator('a').count(), 0)
    assert.equal(await page.locator('.katex').count(), 0)
    assert.deepEqual(await page.locator('code').allTextContents(), [literal, literal])
    assert.equal(requests.length, 0)
  })
})

test('F02 image rendering also works in headings, lists, tables, and link labels', () => {
  const html = renderMarkdownLite('# ![h](a.png)\n\n- ![l](b.png)\n\n| Image | Note |\n|---|---|\n| ![t](c.png) | test |\n\n[![linked](d.png)](https://example.invalid)', { wikiLinks: true })
  assert.equal((html.match(/<img /g) || []).length, 4)
  assert.match(html, /<h2><img /)
  assert.match(html, /<li><img /)
  assert.match(html, /<td><img /)
  assert.match(html, /<a [^>]+><img /)
})

test('F02 leading/trailing URL controls are rejected before whitespace normalization', async () => {
  const urls = ['\thttps://images-fixture.invalid/a.png', 'https://images-fixture.invalid/a.png\t', 'https://images-fixture.invalid/a.png\u0000', 'https://images-fixture.invalid/a.png%09']
  await renderedPage(urls.map((url, i) => `![控制符 ${i}](${url})`).join('\n'), async (page, requests) => {
    assert.equal(await page.locator('img').count(), 0)
    assert.equal(requests.length, 0)
    const text = await page.locator('main').innerText()
    for (let i = 0; i < urls.length; i += 1) assert.ok(text.includes(`控制符 ${i}`))
  })
})

test('F02 restored math containing placeholder-shaped text cannot reinsert KaTeX into image attributes', async () => {
  await renderedPage('![公式 $x\uE0001\uE001$](./image.png)\n\n$y$', async page => {
    const image = page.locator('img')
    assert.equal(await image.count(), 1)
    assert.equal(await image.getAttribute('alt'), '公式 $x\uE0001\uE001$')
    assert.doesNotMatch(await image.evaluate(node => node.outerHTML), /<span|katex|style=.*style=/)
    assert.equal(await page.locator('.katex').count(), 1)
  })
})

test('F02 normal percent-encoded relative filenames remain loadable', async () => {
  const urls = ['images/中文%20文件.png', './images/100%25.png', '/images/caf%C3%A9.png']
  await renderedPage(urls.map(url => `![filename](${url})`).join('\n'), async (page, requests) => {
    assert.equal(await page.locator('img').count(), urls.length)
    await page.waitForFunction(() => [...document.images].every(image => image.complete && image.naturalWidth === 1), null, { timeout: 3000 })
    assert.deepEqual(await page.locator('img').evaluateAll(nodes => nodes.map(node => node.getAttribute('src'))), urls)
    assert.equal(requests.length, urls.length)
  })
})
