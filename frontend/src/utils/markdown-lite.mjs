import katex from 'katex'

const MATH_OPEN = '\uE000'
const MATH_CLOSE = '\uE001'
const FENCE_OPEN = '\uE002'
const FENCE_CLOSE = '\uE003'

// 数学片段收集器：先把 LaTeX 抠成占位符（躲过 markdown 转义与行内格式化），
// 渲染完成后用 KaTeX HTML 回填。
function createMathExtractor() {
  const segments = []

  function stash(latex, displayMode, original) {
    const trimmed = latex.trim()
    if (!trimmed) return ''
    segments.push({ latex: trimmed, displayMode, original })
    return `${MATH_OPEN}${segments.length - 1}${MATH_CLOSE}`
  }

  return {
    segments,
    stash,
  }
}

function looksLikeLatex(content) {
  if (!content || content.length > 300) return false
  if (/^[A-Za-z]/.test(content)) return true
  if (/[\\^_{}=]/.test(content)) return true
  return false
}

function extractMathSegments(rawText) {
  const fence = maskFences(rawText)
  const math = createMathExtractor()
  let text = fence.text

  // 块级公式：\[...\] 与 $$...$$（允许跨行）
  text = text.replace(/\\\[([\s\S]+?)\\\]/g, (match, latex) => math.stash(latex, true, match))
  text = text.replace(/\$\$([\s\S]+?)\$\$/g, (match, latex) => math.stash(latex, true, match))

  // 行内公式：\(...\) 与 $...$（不跨行；$ 需要像公式而非货币符号）
  text = text.replace(/\\\(([\s\S]+?)\\\)/g, (match, latex) => math.stash(latex, false, match))
  text = text.replace(/\$([^$\n]+)\$/g, (match, content) => {
    const opensLikeMath = !/^\s/.test(content) && !/^\d/.test(content)
    const closesLikeMath = !/\s$/.test(content)
    if (opensLikeMath && closesLikeMath && looksLikeLatex(content)) {
      return math.stash(content, false, match)
    }
    return match
  })

  // 还原被保护的代码块
  text = text.replace(new RegExp(`${FENCE_OPEN}(\\d+)${FENCE_CLOSE}`, 'g'), (_, index) => fence.stored[Number(index)])
  return { text, segments: math.segments }
}

function maskFences(text) {
  const lines = text.split(/\r?\n/)
  const stored = []
  const out = []
  let inFence = false
  let fenceLength = 0
  let buffer = []

  for (const line of lines) {
    if (!inFence) {
      const opening = fenceOpening(line)
      if (opening) {
        inFence = true
        fenceLength = opening.length
        buffer = [line]
        continue
      }
      out.push(line)
    } else {
      buffer.push(line)
      if (isFenceClosing(line, fenceLength)) {
        inFence = false
        stored.push(buffer.join('\n'))
        out.push(`${FENCE_OPEN}${stored.length - 1}${FENCE_CLOSE}`)
      }
    }
  }
  if (inFence) {
    // 未闭合围栏：原样保留，交给常规渲染
    out.push(...buffer)
  }
  return { text: out.join('\n'), stored }
}

function renderMathHtml(segments, html) {
  if (!segments.length) return html
  // Generated tags contain escaped attributes. Never insert KaTeX HTML inside them.
  return html.replace(new RegExp(`<[^>]*>|${MATH_OPEN}(\\d+)${MATH_CLOSE}`, 'g'), (match, index) => {
    if (index === undefined) return match
    const segment = segments[Number(index)]
    if (!segment) return match
    try {
      return katex.renderToString(segment.latex, {
        displayMode: segment.displayMode,
        throwOnError: false,
        strict: false,
        output: 'html',
      })
    } catch {
      return `<code>${escapeHtml(segment.latex)}</code>`
    }
  })
}

function escapeHtml(value) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function safeHref(value) {
  const href = value.trim()
  const protocolProbe = href
    .replace(/&amp;/gi, '&')
    .replace(/&#(?:x0*3a|0*58);?/gi, ':')
    .replace(/&colon;?/gi, ':')
    .replace(/&#(?:x0*5c|0*92);?/gi, '\\')
    .replace(/%5c/gi, '\\')
    .replace(/[\u0000-\u0020]/g, '')

  if (protocolProbe.includes('\\')) return '#'
  if (protocolProbe.startsWith('//')) return '#'
  if (/^(?:https?|mailto):/i.test(protocolProbe)) return href
  if (protocolProbe.startsWith('#')) return href
  if (protocolProbe.startsWith('/')) return href
  if (protocolProbe.startsWith('./') || protocolProbe.startsWith('../') || protocolProbe.startsWith('?')) return href
  if (!/^[a-z][a-z0-9+.-]*:/i.test(protocolProbe)) return href

  return '#'
}

function escapeAttribute(value) {
  return value.replace(/"/g, '&quot;').replace(/'/g, '&#39;')
}

function literalMath(value, segments = []) {
  return value.replace(new RegExp(`${MATH_OPEN}(\\d+)${MATH_CLOSE}`, 'g'), (match, index) => {
    const segment = segments[Number(index)]
    return segment ? escapeHtml(segment.original) : match
  })
}

function safeImageSrc(value) {
  if (/[\u0000-\u001f\u007f-\u009f]/.test(value)) return null
  const source = value.trim()
  let probe = source
  // Decode only for validation; emit the already HTML-escaped source unchanged.
  // Repeated encodings must not disguise an external authority or a backslash.
  for (let iteration = 0; iteration < 4; iteration += 1) {
    const previous = probe
    probe = probe.replace(/&amp;/gi, '&')
      .replace(/&#(x[0-9a-f]+|[0-9]+);?/gi, (match, number) => {
        const code = number[0].toLowerCase() === 'x' ? parseInt(number.slice(1), 16) : Number(number)
        return code <= 0x10ffff ? String.fromCodePoint(code) : match
      })
      .replace(/&colon;?/gi, ':').replace(/&bsol;?/gi, '\\')
      .replace(/&(?:Tab|NewLine);?/gi, '\n')
    probe = probe.replace(/(?:%[0-9a-f]{2})+/gi, encoded => {
      try { return decodeURIComponent(encoded) } catch { return encoded }
    })
    if (probe === previous) break
  }
  if (!probe || /[\u0000-\u001f\u007f-\u009f\\]/.test(probe) || /%25/i.test(probe) || probe.trimStart().startsWith('//')) return null
  if (/^[a-z][a-z0-9+.-]*:/i.test(probe.replace(/ /g, ''))) {
    if (!/^https?:\/\//i.test(probe)) return null
    try { if (!new URL(probe).hostname) return null } catch { return null }
  }
  return source
}

function findLabelEnd(value, openingIndex) {
  let depth = 0
  for (let index = openingIndex; index < value.length; index += 1) {
    if (value[index] === '\\') { index += 1; continue }
    if (value[index] === '[') depth += 1
    if (value[index] !== ']') continue
    depth -= 1
    if (depth === 0) return index
  }
  return -1
}

function findBalancedLinkEnd(value, openingIndex) {
  let depth = 0
  for (let index = openingIndex; index < value.length; index += 1) {
    if (value[index] === '\\') {
      index += 1
      continue
    }
    if (value[index] === '(') depth += 1
    if (value[index] !== ')') continue
    depth -= 1
    if (depth === 0) return index
  }
  return -1
}

function formatInline(value, options = {}) {
  let html = ''

  for (let index = 0; index < value.length;) {
    if (value[index] === '`') {
      const closingIndex = value.indexOf('`', index + 1)
      if (closingIndex !== -1) {
        html += `<code>${literalMath(value.slice(index + 1, closingIndex), options.mathSegments)}</code>`
        index = closingIndex + 1
        continue
      }
    }

    if (value.startsWith('![', index)) {
      const labelEnd = findLabelEnd(value, index + 1)
      if (labelEnd !== -1 && value[labelEnd + 1] === '(') {
        const imageEnd = findBalancedLinkEnd(value, labelEnd + 1)
        if (imageEnd !== -1) {
          const alt = literalMath(value.slice(index + 2, labelEnd), options.mathSegments)
          const source = safeImageSrc(literalMath(value.slice(labelEnd + 2, imageEnd), options.mathSegments))
          html += source === null ? alt : `<img src="${escapeAttribute(source)}" alt="${escapeAttribute(alt)}" style="max-width:100%;height:auto" loading="lazy" decoding="async" referrerpolicy="no-referrer">`
          index = imageEnd + 1
          continue
        }
      }
    }

    if (value[index] === '[') {
      const wiki = options.wikiLinks && value.slice(index).match(/^\[\[([^\[\]\n|]+)(?:\|([^\[\]\n]*))?\]\]/)
      if (wiki) {
        const slug = wiki[1].trim().replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&')
        const label = wiki[2] || wiki[1]
        html += `<a href="#wiki-${encodeURIComponent(slug)}" data-wiki-slug="${escapeAttribute(escapeHtml(slug))}">${label}</a>`
        index += wiki[0].length
        continue
      }
      const labelEnd = findLabelEnd(value, index)
      if (labelEnd !== -1 && value[labelEnd + 1] === '(') {
        const linkEnd = findBalancedLinkEnd(value, labelEnd + 1)
        if (linkEnd !== -1) {
          const label = value.slice(index + 1, labelEnd)
          const href = value.slice(labelEnd + 2, linkEnd)
          html += `<a href="${escapeAttribute(safeHref(href))}" target="_blank" rel="noopener noreferrer">${formatInline(label, options)}</a>`
          index = linkEnd + 1
          continue
        }
      }
    }

    const emphasis = [
      ['***', '<strong><em>', '</em></strong>'],
      ['**', '<strong>', '</strong>'],
      ['*', '<em>', '</em>'],
    ].find(([marker]) => value.startsWith(marker, index) && value.indexOf(marker, index + marker.length) !== -1)
    if (emphasis) {
      const [marker, openingTag, closingTag] = emphasis
      const closingIndex = value.indexOf(marker, index + marker.length)
      html += `${openingTag}${formatInline(value.slice(index + marker.length, closingIndex), options)}${closingTag}`
      index = closingIndex + marker.length
      continue
    }

    html += value[index]
    index += 1
  }

  return html
}

function tableCells(line) {
  const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '')
  return trimmed.split('|').map((cell) => cell.trim())
}

function isTableDelimiter(line, expectedCellCount) {
  const cells = tableCells(line)
  return cells.length === expectedCellCount && cells.every((cell) => /^:?-{3,}:?$/.test(cell))
}

function isTableRow(line) {
  return line.includes('|') && tableCells(line).length >= 2
}

function fenceOpening(line) {
  const match = line.match(/^ {0,3}(`{3,})([\w-]*)[\t ]*$/)
  if (!match) return null
  return { length: match[1].length, language: match[2] || 'text' }
}

function isFenceClosing(line, openingLength) {
  const match = line.match(/^ {0,3}(`{3,})[\t ]*$/)
  return Boolean(match && match[1].length >= openingLength)
}

function isBlockStart(lines, index) {
  const line = lines[index]
  if (fenceOpening(line)) return true
  if (/^#{1,3}\s+/.test(line) || /^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/.test(line)) return true
  if (/^\s*[-*+]\s+/.test(line) || /^\s*\d+\.\s+/.test(line)) return true
  return isTableRow(line) && index + 1 < lines.length && isTableDelimiter(lines[index + 1], tableCells(line).length)
}

export function renderMarkdownLite(text, options = {}) {
  if (!text) return ''

  const { text: textWithoutMath, segments } = extractMathSegments(text)
  options = { ...options, mathSegments: segments }

  const lines = escapeHtml(textWithoutMath).split(/\r?\n/)
  const blocks = []

  for (let index = 0; index < lines.length;) {
    const line = lines[index]
    if (!line.trim()) {
      index += 1
      continue
    }

    const openingFence = fenceOpening(line)
    if (openingFence) {
      index += 1
      const codeLines = []
      while (index < lines.length && !isFenceClosing(lines[index], openingFence.length)) {
        codeLines.push(lines[index])
        index += 1
      }
      if (index < lines.length) index += 1
      blocks.push(`<pre><code class="lang-${openingFence.language}">${codeLines.join('\n')}</code></pre>`)
      continue
    }

    const heading = line.match(/^(#{1,3})\s+(.+?)\s*#*\s*$/)
    if (heading) {
      blocks.push(`<h${heading[1].length + 1}>${formatInline(heading[2], options)}</h${heading[1].length + 1}>`)
      index += 1
      continue
    }

    if (/^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/.test(line)) {
      blocks.push('<hr>')
      index += 1
      continue
    }

    if (isTableRow(line) && index + 1 < lines.length) {
      const headers = tableCells(line)
      if (isTableDelimiter(lines[index + 1], headers.length)) {
        index += 2
        const rows = []
        while (index < lines.length && isTableRow(lines[index])) {
          const cells = tableCells(lines[index])
          if (cells.length !== headers.length) break
          rows.push(`<tr>${cells.map((cell) => `<td>${formatInline(cell, options)}</td>`).join('')}</tr>`)
          index += 1
        }
        blocks.push(`<table><thead><tr>${headers.map((cell) => `<th>${formatInline(cell, options)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table>`)
        continue
      }
    }

    const unorderedItems = []
    while (index < lines.length) {
      const item = lines[index].match(/^\s*[-*+]\s+(.+)$/)
      if (!item) break
      unorderedItems.push(`<li>${formatInline(item[1], options)}</li>`)
      index += 1
    }
    if (unorderedItems.length) {
      blocks.push(`<ul>${unorderedItems.join('')}</ul>`)
      continue
    }

    const orderedItems = []
    while (index < lines.length) {
      const item = lines[index].match(/^\s*\d+\.\s+(.+)$/)
      if (!item) break
      orderedItems.push(`<li>${formatInline(item[1], options)}</li>`)
      index += 1
    }
    if (orderedItems.length) {
      blocks.push(`<ol>${orderedItems.join('')}</ol>`)
      continue
    }

    const paragraph = [line]
    index += 1
    while (index < lines.length && lines[index].trim() && !isBlockStart(lines, index)) {
      paragraph.push(lines[index])
      index += 1
    }
    blocks.push(`<p>${paragraph.map((line) => formatInline(line, options)).join('<br>')}</p>`)
  }

  return renderMathHtml(segments, blocks.join(''))
}
