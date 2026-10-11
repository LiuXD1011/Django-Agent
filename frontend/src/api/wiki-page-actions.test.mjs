import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import { transformSync } from 'esbuild'

test('Wiki page mutations use the authenticated client and encode each immutable slug segment', async () => {
  const requests = []
  const client = Object.fromEntries(['put', 'delete'].map(method => [method, async (path, body) => { requests.push({ method, path, body }); return { data: {} } }]))
  const script = transformSync(readFileSync(new URL('./index.ts', import.meta.url), 'utf8'), { loader: 'ts', format: 'cjs' }).code
  const context = vm.createContext({ module: { exports: {} }, require: name => {
    if (name === './client') return client
    if (name === './auth-transport.mjs') return { authTransport: {} }
    if (name === './endpoint.mjs') return { endpoint: {} }
    throw new Error(`Unexpected import: ${name}`)
  } })
  vm.runInContext(script, context)
  const { api } = context.module.exports
  assert.equal(typeof api.updateWikiPage, 'function', 'Existing core Wiki update needs a frontend binding')
  assert.equal(typeof api.deleteWikiPage, 'function', 'Existing core Wiki deletion needs a frontend binding')
  const values = { title: '已编辑', content: '# 保留正文', version: 7 }
  await api.updateWikiPage('kb-a', 'concept/中文 ?#', values)
  await api.deleteWikiPage('kb-a', 'concept/中文 ?#')
  assert.deepEqual(requests, [
    { method: 'put', path: '/api/v1/knowledge-bases/kb-a/wiki/pages/concept/%E4%B8%AD%E6%96%87%20%3F%23', body: values },
    { method: 'delete', path: '/api/v1/knowledge-bases/kb-a/wiki/pages/concept/%E4%B8%AD%E6%96%87%20%3F%23', body: undefined },
  ])
})
