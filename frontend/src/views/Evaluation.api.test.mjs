import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import { transformSync } from 'esbuild'

test('manual evaluation resume forwards explicit unknown-paid acknowledgement to core', async () => {
  const requests = []
  const script = transformSync(readFileSync(new URL('../api/index.ts', import.meta.url), 'utf8'), { loader: 'ts', format: 'cjs', target: 'es2022' }).code
  const context = vm.createContext({ module: { exports: {} }, require: name => {
    if (name === './client') return { post: async (...args) => { requests.push(args); return {} } }
    if (name === './auth-transport.mjs') return { authTransport: {} }
    if (name === './endpoint.mjs') return { endpoint: {} }
    throw new Error(`Unexpected import: ${name}`)
  } })
  vm.runInContext(script, context)
  await context.module.exports.api.ragEvalRunResume('run/id', { acknowledge_unknown_paid_request: true })
  assert.equal(requests[0][0], '/api/v1/rag-eval/runs/run%2Fid/resume')
  assert.equal(requests[0][1].acknowledge_unknown_paid_request, true)
})
