export function renderMarkdownLite(text) {
  if (!text) return ''
  let html = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
    return `<pre><code class="lang-${lang || 'text'}">${code.trim()}</code></pre>`
  })

  html = html.replace(/`([^`]+)`/g, '<code>$1</code>')

  html = html
    .replace(/^### (.+)$/gm, '<h4>$1</h4>')
    .replace(/^## (.+)$/gm, '<h3>$1</h3>')
    .replace(/^# (.+)$/gm, '<h2>$1</h2>')

  html = html
    .replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')

  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')

  html = html.replace(/(^|\n)([*-] .+(?:\n[*-] .+)*)/g, (_match, prefix, list) => {
    const items = list.split('\n').map((line) => `<li>${line.replace(/^[*-] /, '')}</li>`).join('')
    return `${prefix}<ul>${items}</ul>`
  })

  html = html.replace(/(^|\n)(\d+\. .+(?:\n\d+\. .+)*)/g, (_match, prefix, list) => {
    const items = list.split('\n').map((line) => `<li>${line.replace(/^\d+\. /, '')}</li>`).join('')
    return `${prefix}<ol>${items}</ol>`
  })

  html = html
    .replace(/\n\n/g, '</p><p>')
    .replace(/\n/g, '<br>')

  return `<p>${html}</p>`
}

