import { defineStore } from 'pinia'
import { api } from '../api'

const readStorage = (key: string) => localStorage.getItem(key)

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: JSON.parse(readStorage('personal_kb_user') || 'null'),
    tenant: JSON.parse(readStorage('personal_kb_tenant') || 'null'),
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
      this.persist(res.data)
    },
    async login(email: string, password: string) {
      const res: any = await api.login({ email, password })
      this.persist(res.data)
    },
    logout() {
      this.user = null
      this.tenant = null
      this.token = ''
      ;['personal_kb_user', 'personal_kb_tenant', 'personal_kb_token', 'personal_kb_selected_tenant_id', 'personal_kb_refresh_token'].forEach((key) => localStorage.removeItem(key))
    },
  },
})
