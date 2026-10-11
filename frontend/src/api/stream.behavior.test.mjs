import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import { transformSync } from 'esbuild'

const source = transformSync(readFileSync(new URL('./index.ts', import.meta.url), 'utf8'), { loader: 'ts', format: 'cjs' }).code

for (const operation of ['streamChat', 'continueStream']) {
  test(`${operation} cleans up an aborted browser stream without an unhandled rejection`, async () => {
    const aborted = new DOMException('BodyStreamBuffer was aborted', 'AbortError')
    const body = new ReadableStream({ start(controller) { controller.error(aborted) } })
    const context = vm.createContext({ module: { exports: {} }, TextDecoder, require: name => {
      if (name === './client') return {}
      if (name === './auth-transport.mjs') return { authTransport: { request: async () => ({ ok: true, body }) } }
      if (name === './endpoint.mjs') return { endpoint: {} }
      throw new Error(name)
    } })
    vm.runInContext(source, context)
    const api = context.module.exports
    const pending = operation === 'streamChat'
      ? api.streamChat('session', {}, true, () => {})
      : api.continueStream('session', 'message', () => {})
    await assert.rejects(pending, error => error === aborted)
    await new Promise(resolve => setImmediate(resolve))
  })
}
