import axios from 'axios'
import { authTransport } from './auth-transport.mjs'
import { endpoint } from './endpoint.mjs'
import { desktopAxiosAdapter } from './desktop-transport.mjs'

const client = axios.create({
  baseURL: endpoint.origin,
  timeout: 30000,
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
  ...(desktopAxiosAdapter ? { adapter: desktopAxiosAdapter } : {}),
})

client.interceptors.request.use(async (config) => {
  config.url = endpoint.resolve(String(config.url || ''))
  const method = String(config.method || 'GET').toUpperCase()
  ;(config as any)._authGeneration ??= authTransport.generation()
  const anonymous = /\/api\/v1\/auth\/(?:login|register|auto-setup|csrf)$/.test(config.url) || config.url.endsWith('/api/v1/capabilities')
  config.headers.set(authTransport.headers(method, {}, { anonymous }))
  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method) && (anonymous || authTransport.mode() !== 'legacy_bearer')) {
    const token = await authTransport.csrf({ revalidate: anonymous })
    if (token) config.headers.set('X-CSRFToken', token)
  }
  if ((config as any)._authGeneration !== authTransport.generation()) throw new Error('登录已结束')
  authTransport.assertSensitiveSession()
  return config
})

client.interceptors.response.use(
  (response) => response.data,
  async (error) => {
    const original = error.config as any
    const status = error.response?.status
    const url = String(original?.url || '')
    if (status === 401 && original?.skipAuthRefresh && original._authGeneration === authTransport.generation()) {
      authTransport.invalidate()
      if (location.pathname !== '/login') location.href = '/login'
    }
    if (status === 401 && original && !original.skipAuthRefresh && !original._retry && !(/\/api\/v1\/auth\/(?:login|register|auto-setup|refresh|csrf|logout)$/.test(url)) && authTransport.mode()) {
      original._retry = true
      try {
        const data = await authTransport.refresh()
        if (original._authGeneration !== authTransport.generation()) throw new Error('登录已结束')
        original.headers.delete('Authorization')
        if (data.token) original.headers.set('Authorization', `Bearer ${data.token}`)
        if (data.tenant?.id) original.headers.set('X-Tenant-ID', String(data.tenant.id))
        return client(original)
      } catch (refreshError: any) {
        if (original._authGeneration === authTransport.generation() && [401, 403].includes(refreshError?.status)) {
          authTransport.invalidate()
          if (location.pathname !== '/login') location.href = '/login'
        }
      }
    }
    return Promise.reject({ ...(error.response?.data || { message: error.message }), status: error.response?.status })
  },
)

export default client
