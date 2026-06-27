import axios from 'axios'

const client = axios.create({
  baseURL: '',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

client.interceptors.request.use((config) => {
  const token = localStorage.getItem('personal_kb_token') || localStorage.getItem('weknora_token')
  const tenant = localStorage.getItem('personal_kb_selected_tenant_id') || localStorage.getItem('weknora_selected_tenant_id')
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
    'weknora_user',
    'weknora_tenant',
    'weknora_token',
    'weknora_selected_tenant_id',
    'weknora_refresh_token',
  ].forEach((key) => localStorage.removeItem(key))
}

client.interceptors.response.use(
  (response) => response.data,
  async (error) => {
    const original = error.config as any
    const status = error.response?.status
    const url = String(original?.url || '')
    if (status === 401 && original && !original._retry && !url.includes('/api/v1/auth/')) {
      original._retry = true
      try {
        const refresh = await axios.post('/api/v1/auth/auto-setup', {}, { headers: { 'Content-Type': 'application/json' } })
        const data = refresh.data?.data || refresh.data
        persistAuth(data)
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
