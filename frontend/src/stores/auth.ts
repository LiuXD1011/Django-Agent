import { clearLangfuseSession } from '../services/langfuse'
import { defineStore } from 'pinia'
import { api } from '../api'
import { safeParseStorage } from './auth-storage.mjs'

const readStorage = (key: string) => localStorage.getItem(key)

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: safeParseStorage(readStorage('personal_kb_user'), 'personal_kb_user'),
    tenant: safeParseStorage(readStorage('personal_kb_tenant'), 'personal_kb_tenant'),
    token: readStorage('personal_kb_token') || '',
  }),
  actions: {
    persist(data: any) {
      this.user = data.user
      this.tenant = data.tenant
      this.token = data.token
      localStorage.setItem('personal_kb_user', JSON.stringify(data.user))
      localStorage.setItem('personal_kb_tenant', JSON.stringify(data.tenant))
      localStorage.setItem('personal_kb_token', data.token)
      localStorage.setItem('personal_kb_selected_tenant_id', String(data.tenant?.id || ''))
      if (data.refresh_token) localStorage.setItem('personal_kb_refresh_token', data.refresh_token)
    },
    async autoSetup() {
      const res: any = await api.autoSetup()
      // persist 只落已知认证字段；temp_password 仅通过返回值交给调用方一次性展示，
      // 不得写入 localStorage/sessionStorage、日志、URL 或分析事件。
      this.persist(res.data)
      return res.data
    },
    async login(email: string, password: string) {
      const res: any = await api.login({ email, password })
      this.persist(res.data)
    },
    async logout() {
      await clearLangfuseSession()
      this.user = null
      this.tenant = null
      this.token = ''
      ;['personal_kb_user', 'personal_kb_tenant', 'personal_kb_token', 'personal_kb_selected_tenant_id', 'personal_kb_refresh_token'].forEach((key) => localStorage.removeItem(key))
    },
  },
})
