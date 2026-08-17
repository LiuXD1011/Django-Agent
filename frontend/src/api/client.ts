import axios from 'axios'

const client = axios.create({
  baseURL: '',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

client.interceptors.request.use((config) => {
  const token = localStorage.getItem('personal_kb_token')
  const tenant = localStorage.getItem('personal_kb_selected_tenant_id')
  if (token) config.headers.Authorization = `Bearer ${token}`
  if (tenant) config.headers['X-Tenant-ID'] = tenant
  config.headers['X-Request-ID'] = Math.random().toString(36).slice(2)
  return config
})

function persistAuth(data: any) {
  if (!data?.token) return
  localStorage.setItem('personal_kb_token', data.token)
  if (data.refresh_token) localStorage.setItem('personal_kb_refresh_token', data.refresh_token)
  if (data.user) localStorage.setItem('personal_kb_user', JSON.stringify(data.user))
  if (data.tenant) {
    localStorage.setItem('personal_kb_tenant', JSON.stringify(data.tenant))
    localStorage.setItem('personal_kb_selected_tenant_id', String(data.tenant.id || ''))
  }
}

function clearAuth() {
  ;[
    'personal_kb_user',
    'personal_kb_tenant',
    'personal_kb_token',
    'personal_kb_selected_tenant_id',
    'personal_kb_refresh_token',
  ].forEach((key) => localStorage.removeItem(key))
}

// 单飞锁：并发 401 只触发一次 refresh，共享同一结果
let refreshInFlight: Promise<any> | null = null

async function refreshAccessToken(): Promise<any> {
  const refreshToken = localStorage.getItem('personal_kb_refresh_token')
  if (!refreshToken) throw new Error('missing refresh token')
  const response = await axios.post(
    '/api/v1/auth/refresh',
    { refresh_token: refreshToken },
    { headers: { 'Content-Type': 'application/json' } },
  )
  const data = response.data?.data || response.data
  if (!data?.token) throw new Error('refresh response missing token')
  persistAuth(data)
  return data
}

function refreshAccessTokenSingleFlight() {
  if (!refreshInFlight) {
    refreshInFlight = refreshAccessToken().finally(() => {
      refreshInFlight = null
    })
  }
  return refreshInFlight
}

client.interceptors.response.use(
  (response) => response.data,
  async (error) => {
    const original = error.config as any
    const status = error.response?.status
    const url = String(original?.url || '')
    // 登出后 localStorage 已无 refresh_token，refresh 会立即失败，
    // 不会像旧 auto-setup 逻辑那样把新凭证写回、导致登出被"撤销"
    if (status === 401 && original && !original._retry && !url.includes('/api/v1/auth/')) {
      original._retry = true
      try {
        const data = await refreshAccessTokenSingleFlight()
        original.headers = original.headers || {}
        original.headers.Authorization = `Bearer ${data.token}`
        if (data.tenant?.id) original.headers['X-Tenant-ID'] = String(data.tenant.id)
        return client(original)
      } catch {
        clearAuth()
        if (location.pathname !== '/login') location.href = '/login'
      }
    }
    return Promise.reject(error.response?.data || { message: error.message })
  },
)

export default client
