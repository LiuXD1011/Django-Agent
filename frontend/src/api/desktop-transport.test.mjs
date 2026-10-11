import assert from 'node:assert/strict'
import test from 'node:test'

async function implementation() {
  const module = await import('./desktop-transport.mjs').catch(() => null)
  assert.ok(module, 'packaged renderer requires its bounded private IPC fetch adapter')
  return module
}
// Unit protocol fixture; actual child/SQLite/model integration lives in desktop/runtime.test.cjs.
function fixture() {
  const calls = [], listeners = new Map(), acks = [], cancels = []
  const bridge = { protocol: 1, transport: 'ipc',
    invoke: async (request, options) => { calls.push([request, options]); return { protocol: 1, id: request.id, status: 200, body: { success: true, data: { total: 1 } } } },
    subscribeStream: (id, callback) => { listeners.set(id, callback); return () => listeners.delete(id) },
    openStream: async request => { calls.push([request]); return { protocol: 1, id: request.id, status: 200, body: { success: true, data: { streaming: true } } } },
    acknowledgeStream: (id, sequence) => acks.push([id, sequence]), cancel: id => cancels.push(id),
  }
  return { bridge, calls, listeners, acks, cancels }
}

test('desktop fetch restricts origin, forwards only public requests and translates an actual selected file to bounded bytes', async () => {
  const { createDesktopFetch } = await implementation(), f = fixture()
  const fetcher = createDesktopFetch(f.bridge, 'https://marlin.local')
  const response = await fetcher('https://marlin.local/api/v1/sessions?q=%E6%B5%B7%E7%9B%90', { method: 'POST',
    headers: { 'X-Request-ID': 'chosen-request', 'X-Tenant-ID': 'owned-space', Authorization: 'must-not-forward' }, body: JSON.stringify({ title: '海盐' }) })
  assert.equal((await response.json()).data.total, 1)
  assert.deepEqual(f.calls[0], [{ protocol: 1, id: 'chosen-request', method: 'POST', path: '/api/v1/sessions?q=%E6%B5%B7%E7%9B%90', body: { title: '海盐' } }, { tenantId: 'owned-space' }])
  await assert.rejects(fetcher('https://evil.invalid/api/v1/auth/me'))
  await assert.rejects(fetcher('https://marlin.local/private/file'))
  const form = new FormData(); form.append('file', new File(['海盐资料'], '中文 文档.md', { type: 'text/markdown' })); form.append('process_config', '{"chunk_size":512}')
  await fetcher('/api/v1/knowledge-bases/kb/knowledge/file', { method: 'POST', body: form })
  assert.equal(f.calls[1][1].upload.name, '中文 文档.md'); assert.equal(new TextDecoder().decode(f.calls[1][1].upload.bytes), '海盐资料')
  assert.deepEqual(f.calls[1][0].body.process_config, { chunk_size: 512 })
  const abort = new AbortController(); abort.abort(); const before = f.calls.length
  await assert.rejects(fetcher('/api/v1/sessions', { signal: abort.signal }), { name: 'AbortError' }); assert.equal(f.calls.length, before)
})

test('desktop SSE preserves frame ordering and acknowledges only when the consumer reads; cancellation disconnects its own subscription', async () => {
  const { createDesktopFetch } = await implementation(), f = fixture(), abort = new AbortController()
  const response = await createDesktopFetch(f.bridge, 'https://marlin.local')('/api/v1/knowledge-chat/session', { method: 'POST',
    headers: { 'X-Request-ID': 'native-stream', Accept: 'text/event-stream' }, body: '{"query":"海盐","stream":true}', signal: abort.signal })
  assert.match(response.headers.get('Content-Type'), /^text\/event-stream/)
  f.listeners.get('native-stream')({ type: 'frame', sequence: 0, frame: { event: 'message_start', data: { id: 'reply' } } })
  assert.equal(f.acks.length, 0)
  const reader = response.body.getReader(), first = await reader.read()
  assert.match(new TextDecoder().decode(first.value), /event: message_start\ndata: \{"id":"reply"\}/)
  assert.deepEqual(f.acks, [['native-stream', 0]])
  f.listeners.get('native-stream')({ type: 'frame', sequence: 1, frame: { event: 'done', data: { content: '真实输出' } } })
  assert.match(new TextDecoder().decode((await reader.read()).value), /真实输出/)
  abort.abort(); assert.deepEqual(f.cancels, ['native-stream']); assert.equal(f.listeners.has('native-stream'), false)
  await assert.rejects(reader.read(), { name: 'AbortError' })
})

test('desktop binary response retains file bytes, MIME and download name without exposing a filesystem path', async () => {
  const { createDesktopFetch } = await implementation(), f = fixture()
  f.bridge.invoke = async request => ({ protocol: 1, id: request.id, status: 200, body: { success: true, data: {} }, binary: { bytes: new Uint8Array([1, 2, 3]), name: '评测报告.json', mimeType: 'application/json', sha256: 'checksum' } })
  const response = await createDesktopFetch(f.bridge, 'https://marlin.local')('/api/v1/rag-eval/reports/owned')
  assert.deepEqual([...new Uint8Array(await response.arrayBuffer())], [1, 2, 3]); assert.equal(response.headers.get('Content-Type'), 'application/json')
  assert.match(response.headers.get('Content-Disposition'), /filename\*=UTF-8''/)
})
