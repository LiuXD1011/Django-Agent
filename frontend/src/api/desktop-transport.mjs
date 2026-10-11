import axios from 'axios'

function validBridge(value) {
  return value?.protocol === 1 && value.transport === 'ipc'
    && ['invoke', 'openStream', 'subscribeStream', 'acknowledgeStream', 'cancel'].every(key => typeof value[key] === 'function')
}
export const desktopBridge = validBridge(globalThis.marlinDesktop) ? globalThis.marlinDesktop : null
const aborted = () => new DOMException('桌面请求已取消', 'AbortError')

export function createDesktopFetch(bridge, origin) {
  if (!validBridge(bridge)) throw new Error('桌面通信接口不可用')
  const serviceOrigin = new URL(origin).origin
  return async (input, init = {}) => {
    if (init.signal?.aborted) throw aborted()
    const url = new URL(String(input), serviceOrigin)
    if (url.origin !== serviceOrigin || url.username || url.password || url.hash || !url.pathname.startsWith('/api/v1/')) throw new Error('桌面请求地址必须属于当前应用')
    const headers = new Headers(init.headers), method = String(init.method || 'GET').toUpperCase()
    if (!['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) throw new Error('桌面请求方法不受支持')
    const id = headers.get('X-Request-ID') || crypto.randomUUID(), options = {}
    if (headers.get('X-Tenant-ID')) options.tenantId = headers.get('X-Tenant-ID')
    let body
    if (init.body instanceof FormData) {
      body = {}; let selectedFile
      for (const [key, value] of init.body) {
        if (key === 'file') {
          if (selectedFile || !(value instanceof Blob) || typeof value.name !== 'string') throw new Error('一次上传请选择一个文件')
          if (value.size > 64 * 1024 * 1024) throw new Error('上传文件超过 64 MiB 限制')
          selectedFile = value
        } else if (key === 'tag_id' && typeof value === 'string') body.tag_id = value
        else if (key === 'process_config' && typeof value === 'string') body.process_config = JSON.parse(value)
        else throw new Error('上传字段不受支持')
      }
      if (!selectedFile) throw new Error('请选择上传文件')
      options.upload = { name: selectedFile.name, bytes: new Uint8Array(await selectedFile.arrayBuffer()) }
    } else if (init.body !== undefined && init.body !== null) {
      if (typeof init.body !== 'string' || new TextEncoder().encode(init.body).byteLength > 2 * 1024 * 1024) throw new Error('桌面请求正文超过限制或格式不正确')
      body = JSON.parse(init.body)
    }
    if (init.signal?.aborted) throw aborted()
    const request = { protocol: 1, id, method, path: url.pathname + url.search, ...(body !== undefined ? { body } : {}) }
    const isStream = headers.get('Accept')?.includes('text/event-stream') || body?.stream === true
    let unsubscribe, controller, queued, waiting, finished = false, sequence = 0
    const cleanup = () => { unsubscribe?.(); init.signal?.removeEventListener('abort', cancel) }
    const cancel = () => {
      if (finished) return
      finished = true; cleanup(); bridge.cancel(id); controller?.error(aborted()); waiting?.();
    }
    init.signal?.addEventListener('abort', cancel, { once: true })
    try {
      if (!isStream) {
        const response = await bridge.invoke(request, options)
        if (init.signal?.aborted) throw aborted()
        finished = true; cleanup()
        if (response.binary) return new Response(response.binary.bytes, { status: response.status, headers: {
          'Content-Type': response.binary.mimeType, 'Content-Disposition': `attachment; filename*=UTF-8''${encodeURIComponent(response.binary.name)}`,
          'X-Content-SHA256': response.binary.sha256, 'X-Request-ID': id,
        } })
        return new Response(JSON.stringify(response.body), { status: response.status, headers: { 'Content-Type': 'application/json', 'X-Request-ID': id } })
      }
      const stream = new ReadableStream({
        start(value) { controller = value },
        async pull(value) {
          if (!queued && !finished) await new Promise(resolve => { waiting = resolve })
          waiting = undefined
          if (!queued || finished) return
          const item = queued; queued = undefined
          value.enqueue(new TextEncoder().encode(`event: ${item.frame.event}\ndata: ${JSON.stringify(item.frame.data)}\n\n`))
          sequence++; bridge.acknowledgeStream(id, item.sequence)
        },
        cancel() { cancel() },
      }, { highWaterMark: 0 })
      unsubscribe = bridge.subscribeStream(id, item => {
        if (finished) return
        if (item.type === 'frame') {
          if (queued || item.sequence !== sequence || !/^[a-zA-Z0-9_/-]{1,100}$/.test(item.frame?.event || '')) {
            finished = true; cleanup(); bridge.cancel(id); controller.error(new Error('桌面流事件顺序不正确')); waiting?.(); return
          }
          queued = item; waiting?.()
        } else {
          finished = true; cleanup()
          if (item.type === 'error') controller.error(new Error(item.message || '桌面流请求失败'))
          else controller.close()
          waiting?.()
        }
      })
      const response = await bridge.openStream(request, options)
      if (init.signal?.aborted) throw aborted()
      if (response.status >= 400) {
        finished = true; cleanup(); controller.close()
        return new Response(JSON.stringify(response.body), { status: response.status, headers: { 'Content-Type': 'application/json' } })
      }
      return new Response(stream, { status: response.status, headers: { 'Content-Type': 'text/event-stream; charset=utf-8', 'Cache-Control': 'no-store', 'X-Request-ID': id } })
    } catch (error) { cleanup(); if (!finished) { finished = true; bridge.cancel(id) } throw error }
  }
}

export const desktopFetch = desktopBridge ? createDesktopFetch(desktopBridge, globalThis.location.origin) : null
export const applicationFetch = desktopFetch || ((...args) => globalThis.fetch(...args))
export const desktopAxiosAdapter = desktopFetch ? async config => {
  const controller = new AbortController(), timer = config.timeout > 0 ? setTimeout(() => controller.abort(), config.timeout) : null
  const signal = config.signal ? AbortSignal.any([config.signal, controller.signal]) : controller.signal
  try {
    const response = await desktopFetch(axios.getUri(config), { method: config.method, headers: config.headers.toJSON(), body: config.data, signal })
    const data = config.responseType === 'blob' ? await response.blob() : config.responseType === 'arraybuffer' ? await response.arrayBuffer()
      : config.responseType === 'text' ? await response.text() : await response.json()
    const result = { data, status: response.status, statusText: response.statusText, headers: Object.fromEntries(response.headers), config }
    if (!config.validateStatus || config.validateStatus(response.status)) return result
    throw new axios.AxiosError('桌面业务请求失败', response.status >= 500 ? 'ERR_BAD_RESPONSE' : 'ERR_BAD_REQUEST', config, undefined, result)
  } finally { if (timer) clearTimeout(timer) }
} : undefined
