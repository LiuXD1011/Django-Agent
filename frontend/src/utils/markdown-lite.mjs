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

function formatInline(value) {
  let html = ''

  for (let index = 0; index < value.length;) {
    if (value[index] === '`') {
      const closingIndex = value.indexOf('`', index + 1)
      if (closingIndex !== -1) {
        html += `<code>${value.slice(index + 1, closingIndex)}</code>`
        index = closingIndex + 1
        continue
      }
    }

    if (value[index] === '[') {
      const labelEnd = value.indexOf(']', index + 1)
      if (labelEnd !== -1 && value[labelEnd + 1] === '(') {
        const linkEnd = findBalancedLinkEnd(value, labelEnd + 1)
        if (linkEnd !== -1) {
          const label = value.slice(index + 1, labelEnd)
          const href = value.slice(labelEnd + 2, linkEnd)
          html += `<a href="${escapeAttribute(safeHref(href))}" target="_blank" rel="noopener noreferrer">${formatInline(label)}</a>`
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
      html += `${openingTag}${formatInline(value.slice(index + marker.length, closingIndex))}${closingTag}`
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

export function renderMarkdownLite(text) {
  if (!text) return ''

  const lines = escapeHtml(text).split(/\r?\n/)
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
      blocks.push(`<h${heading[1].length + 1}>${formatInline(heading[2])}</h${heading[1].length + 1}>`)
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
          rows.push(`<tr>${cells.map((cell) => `<td>${formatInline(cell)}</td>`).join('')}</tr>`)
          index += 1
        }
        blocks.push(`<table><thead><tr>${headers.map((cell) => `<th>${formatInline(cell)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table>`)
        continue
      }
    }

    const unorderedItems = []
    while (index < lines.length) {
      const item = lines[index].match(/^\s*[-*+]\s+(.+)$/)
      if (!item) break
      unorderedItems.push(`<li>${formatInline(item[1])}</li>`)
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
      orderedItems.push(`<li>${formatInline(item[1])}</li>`)
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
    blocks.push(`<p>${paragraph.map(formatInline).join('<br>')}</p>`)
  }

  return blocks.join('')
}
