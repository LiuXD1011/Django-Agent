// 此模板只由 Vite 构建为 /sw.js。只信任构建时公开静态清单，不按扩展名泛化缓存。
const VERSION = __STATIC_VERSION__
const SHELL = __STATIC_SHELL__
const ASSETS = __STATIC_ASSETS__
const CACHE_PREFIX = 'personal-kb-public-static-'
const CACHE_NAME = CACHE_PREFIX + VERSION
const allowed = new Set([SHELL, ...ASSETS])

function validStaticResponse(path, response) {
  if (!response.ok || response.redirected || response.type !== 'basic') return false
  const contentType = response.headers.get('content-type') || ''
  if (path === SHELL) return contentType.includes('text/html')
  if (path.endsWith('.js')) return /javascript/.test(contentType)
  if (path.endsWith('.css')) return /text\/css/.test(contentType)
  return /^(image\/|font\/|application\/(font|octet-stream))/.test(contentType)
}

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME)
    try {
      for (const path of allowed) {
        // 静态壳和资产不携带用户凭据；禁止重定向到鉴权或私有内容。
        const response = await fetch(new Request(path, { credentials: 'omit', cache: 'no-store', redirect: 'error' }))
        if (!validStaticResponse(path, response)) throw new Error('Invalid public asset')
        await cache.put(path, response)
      }
    } catch (error) {
      await caches.delete(CACHE_NAME)
      throw error
    }
  })())
})

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    for (const name of await caches.keys()) {
      if (name.startsWith(CACHE_PREFIX) && name !== CACHE_NAME) await caches.delete(name)
    }
    await self.clients.claim()
  })())
})

self.addEventListener('fetch', (event) => {
  const request = event.request
  const url = new URL(request.url)
  if (request.method !== 'GET' || url.origin !== self.location.origin || url.search || request.headers.has('authorization')) return
  // API、media、files、uploads、downloads、SSE 等私有路由不在清单中，完全绕过 SW。
  if (allowed.has(url.pathname)) {
    event.respondWith((async () => {
      const cache = await caches.open(CACHE_NAME)
      const cached = await cache.match(url.pathname)
      if (cached) return cached
      // 缓存被 OS 清理时仍只取无凭据的公开清单资产，不补缓存其他响应。
      return fetch(new Request(url.href, { credentials: 'omit', cache: 'no-store', redirect: 'error' }))
    })())
    return
  }
  const appNavigation = url.pathname === '/' || url.pathname === '/login' || url.pathname === '/platform' || url.pathname.startsWith('/platform/')
  if (request.mode === 'navigate' && appNavigation) {
    event.respondWith(fetch(request).catch(async () => {
      const cache = await caches.open(CACHE_NAME)
      return (await cache.match(SHELL)) || Response.error()
    }))
  }
  // 网络导航不写 CacheStorage；离线壳只提供界面，不伪造登录/搜索/问答可用。
})
