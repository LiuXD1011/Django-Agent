import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'

export function publicStaticShell() {
  return {
    name: 'personal-kb-public-static-shell',
    apply: 'build',
    enforce: 'post',
    generateBundle(_options, bundle) {
      const html = bundle['index.html']
      if (!html || html.type !== 'asset') this.error('Missing static index.html')
      const assets = Object.keys(bundle).filter((name) => /^assets\/[^/]+-[\w-]{8,}\.(js|css|svg|png|jpg|webp|woff2?)$/.test(name)).sort()
      const digest = createHash('sha256').update(String(html.source))
      for (const name of assets) {
        const asset = bundle[name]
        digest.update(name).update(asset.type === 'chunk' ? asset.code : asset.source)
      }
      const version = digest.digest('hex').slice(0, 20)
      const shell = `/pwa-shell/shell-${version}.html`
      const template = readFileSync(new URL('./service-worker.template.js', import.meta.url), 'utf8')
      const worker = template.replace('__STATIC_VERSION__', JSON.stringify(version))
        .replace('__STATIC_SHELL__', JSON.stringify(shell))
        .replace('__STATIC_ASSETS__', JSON.stringify(assets.map((name) => `/${name}`)))
      this.emitFile({ type: 'asset', fileName: shell.slice(1), source: html.source })
      this.emitFile({ type: 'asset', fileName: 'sw.js', source: worker })
    },
  }
}
