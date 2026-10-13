import { spawn } from 'node:child_process'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { createServer as createPortProbe } from 'node:net'
import { tmpdir } from 'node:os'
import { resolve } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'

const frontendRoot = fileURLToPath(new URL('../../', import.meta.url))
const coreRoot = resolve(frontendRoot, '../packages/core')
const uiOrigin = 'http://127.0.0.1:4180'
const coreOrigin = 'http://127.0.0.1:8180'
/** @type {import('node:child_process').ChildProcess | undefined} */
let core
/** @type {Promise<{ code: number | null, signal: NodeJS.Signals | null }> | undefined} */
let coreClosed
/** @type {import('vite').ViteDevServer | undefined} */
let ui
/** @type {string | undefined} */
let temporaryRoot
/** @type {Promise<void> | undefined} */
let shutdown
let closing = false

/** @param {number} port */
async function assertUnusedPort(port) {
  const probe = createPortProbe()
  await new Promise((accept, reject) => {
    probe.once('error', reject)
    probe.listen(port, '127.0.0.1', accept)
  })
  await new Promise((accept, reject) => probe.close(error => error ? reject(error) : accept(undefined)))
}

/** @param {number} pid */
async function identity(pid) {
  if (process.platform !== 'linux') return { pid }
  const stat = await readFile(`/proc/${pid}/stat`, 'utf8')
  return { pid, startTicks: stat.slice(stat.lastIndexOf(')') + 2).split(' ')[19] }
}

async function close() {
  if (shutdown) return shutdown
  closing = true
  shutdown = (async () => {
    await ui?.close()
    if (core && core.exitCode === null && core.signalCode === null) core.kill('SIGTERM')
    const result = await coreClosed
    if (result && result.code !== 0) process.exitCode = 1
    // Remove only our fresh directory, after the exact child has actually closed.
    if (temporaryRoot) await rm(temporaryRoot, { recursive: true })
    process.stdout.write(`auth-e2e ${JSON.stringify({ phase: 'closed', core: result ?? null, temporaryRootRemoved: Boolean(temporaryRoot) })}\n`)
  })()
  return shutdown
}

async function main() {
  await assertUnusedPort(4180)
  await assertUnusedPort(8180)
  temporaryRoot = await mkdtemp(resolve(tmpdir(), 'marlin-auth-e2e-'))
  const dataRoot = resolve(temporaryRoot, 'data')
  const args = ['--import', 'tsx', 'src/tools/dev-server.ts', '--data-root', dataRoot, '--port', '8180', '--ui-origin', uiOrigin]
  core = spawn(process.execPath, args, {
    cwd: coreRoot, stdio: ['ignore', 'pipe', 'pipe'],
    // This isolated core needs no provider/parser environment or copied user credentials.
    env: { PATH: process.env.PATH, NODE_ENV: 'test', TZ: 'UTC' },
  })
  coreClosed = new Promise((accept, reject) => {
    core.once('error', reject)
    core.once('close', (code, signal) => accept({ code, signal }))
  })
  core.stdout?.pipe(process.stdout)
  core.stderr?.pipe(process.stderr)
  const coreIdentity = core.pid ? await identity(core.pid) : null
  process.stdout.write(`auth-e2e ${JSON.stringify({ phase: 'starting', helper: await identity(process.pid), core: coreIdentity, args, dataRoot, uiOrigin, coreOrigin })}\n`)
  const deadline = Date.now() + 30000
  for (;;) {
    if (closing) return
    if (core.exitCode !== null || core.signalCode !== null) throw new Error('Isolated TypeScript core exited before readiness')
    try {
      const response = await fetch(`${coreOrigin}/health`, { signal: AbortSignal.timeout(1000) })
      const result = await response.json()
      if (response.ok && result.runtime === 'typescript' && result.status === 'ok') break
    } catch { /* The freshly spawned core has not started listening yet. */ }
    if (Date.now() >= deadline) throw new Error('Isolated TypeScript core startup timed out')
    await delay(100)
  }
  if (closing) return
  ui = await createServer({
    root: frontendRoot, configFile: resolve(frontendRoot, 'vite.config.ts'),
    cacheDir: resolve(temporaryRoot, 'vite-cache'), clearScreen: false,
    server: { host: '127.0.0.1', port: 4180, strictPort: true, open: false,
      proxy: { '/api': coreOrigin, '/files': coreOrigin, '/health': coreOrigin } },
  })
  if (closing) { await ui.close(); return }
  await ui.listen()
  for (const path of ['/api', '/files', '/health']) {
    if (ui.config.server.proxy?.[path] !== coreOrigin) throw new Error('Auth E2E proxy did not resolve to its isolated core')
  }
  const response = await fetch(`${uiOrigin}/health`)
  const health = await response.json()
  if (!response.ok || health.runtime !== 'typescript') throw new Error('Auth E2E UI is not connected to the TypeScript core')
  process.stdout.write(`auth-e2e ${JSON.stringify({ phase: 'ready', uiOrigin, coreOrigin, proxyVerified: true, cacheDir: ui.config.cacheDir })}\n`)
  void coreClosed.then(() => {
    if (!closing) { process.exitCode = 1; void close() }
  }).catch(() => { process.exitCode = 1; void close() })
}

for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, () => {
  void close().catch(error => { process.stderr.write(`${String(error)}\n`); process.exitCode = 1 })
})
await main().catch(async error => {
  process.stderr.write(`${String(error)}\n`)
  process.exitCode = 1
  await close()
})
