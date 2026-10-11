import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import { transformSync } from 'esbuild'

test('citation source reads use existing tenant client with encoded document and chunk identifiers', async () => {
  const requests = []
  const client = { get: async (path) => { requests.push(path); return { data: {} } } }
  const script = transformSync(readFileSync(new URL('./index.ts', import.meta.url), 'utf8'), { loader: 'ts', format: 'cjs' }).code
  const context = vm.createContext({ module: { exports: {} }, require: (name) => {
    if (name === './client') return client
    if (name === './auth-transport.mjs') return { authTransport: {} }
    if (name === './endpoint.mjs') return { endpoint: {} }
    throw new Error(`Unexpected import: ${name}`)
  } })
  vm.runInContext(script, context)
  const { api } = context.module.exports
  assert.equal(typeof api.getKnowledge, 'function', 'Existing authenticated document read needs a frontend binding')
  assert.equal(typeof api.getChunk, 'function', 'Existing document-scoped chunk read needs a frontend binding')
  await api.getKnowledge('document /?')
  await api.getChunk('document /?', 'chunk #&')
  assert.deepEqual(requests, ['/api/v1/knowledge/document%20%2F%3F', '/api/v1/chunks/document%20%2F%3F/chunk%20%23%26'])
})
