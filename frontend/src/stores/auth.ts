import { clearLangfuseSession } from '../services/langfuse'
import { defineStore } from 'pinia'
import { api } from '../api'
import { safeParseStorage } from './auth-storage.mjs'
import { authTransport } from '../api/auth-transport.mjs'
import { endpoint } from '../api/endpoint.mjs'
import { deviceStore } from './device-store.mjs'

const readStorage = (key: string) => localStorage.getItem(key)
let restoreInFlight: Promise<boolean> | null = null

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: safeParseStorage(readStorage('personal_kb_user'), 'personal_kb_user'),
    tenant: safeParseStorage(readStorage('personal_kb_tenant'), 'personal_kb_tenant'),
    token: readStorage('personal_kb_token') || '', // Existing Bearer sessions only; new web credentials stay HttpOnly.
    authenticated: false,
    restored: false,
    subscribed: false,
  }),
  actions: {
    subscribe() {
      if (this.subscribed) return
      this.subscribed = true
      authTransport.onSession((data: any) => this.applySession(data))
      authTransport.onInvalidate(() => {
        this.user = null
        this.tenant = null
        this.token = ''
        this.authenticated = false
        this.restored = false
      })
    },
    async bindService() {
      const res: any = await api.capabilities()
      const oldService = readStorage('personal_kb_service_id')
      const service = endpoint.bind(res.data)
      if (oldService && oldService !== service.service_id) {
        authTransport.invalidate({ clearCache: false })
        localStorage.setItem('personal_kb_service_id', service.service_id)
        throw Object.assign(new Error('服务身份已改变，请重新登录'), { code: 'service_identity_changed' })
      }
      localStorage.setItem('personal_kb_service_id', service.service_id)
      return service
    },
    persist(data: any, options: { explicitLogin?: boolean } = {}) {
      this.subscribe()
      authTransport.persist(data, options)
    },
    applySession(data: any) {
      this.user = data.user
      this.tenant = data.tenant
      this.token = ['cookie', 'ipc'].includes(data.auth_mode) ? '' : data.token || this.token
      this.authenticated = true
      this.restored = true
      if (endpoint.service) deviceStore.bind(endpoint.service.service_id, data.user?.id, data.tenant?.id)
    },
    async restore() {
      this.subscribe()
      if (this.restored) return this.authenticated
      if (restoreInFlight) return restoreInFlight
      const generation = authTransport.generation()
      const promise = (async () => {
        try {
          await this.bindService()
          let res: any
          try { res = await api.me() }
          catch (error: any) {
            if (error?.status !== 401 || !authTransport.mode()) throw error
            await authTransport.refresh()
            res = await api.me()
          }
          if (generation !== authTransport.generation()) return false
          this.persist({ ...res.data, token: this.token })
          return true
        } catch (error: any) {
          if (generation === authTransport.generation()) {
            this.authenticated = false
            // A network outage must not delete the user's unsubmitted local drafts.
            if ([401, 403].includes(error?.status)) authTransport.invalidate()
          }
          return false
        } finally { this.restored = this.authenticated }
      })()
      restoreInFlight = promise
      try { return await promise }
      finally { if (restoreInFlight === promise) restoreInFlight = null }
    },
    async authenticate(kind: 'login' | 'register' | 'autoSetup', data: any = {}) {
      this.subscribe()
      // Capture the user's intent before the first await, not after a slow capabilities request.
      authTransport.invalidate({ clearCache: false })
      const generation = authTransport.generation()
      return authTransport.sessionOperation(generation, async (check: () => void) => {
        await this.bindService()
        check()
        const res: any = kind === 'autoSetup' ? await api.autoSetup(data) : await api[kind](data)
        check()
        if (res.data?.auth_mode !== (authTransport.isNative() ? 'ipc' : 'cookie')) throw new Error('服务未建立受保护的设备会话')
        this.persist(res.data, { explicitLogin: true }) // Keep the lock until Set-Cookie response processing and local binding finish.
        return res.data
      })
    },
    async autoSetup(data: { email?: string; password?: string } = {}) {
      return this.authenticate('autoSetup', data) // Initial credentials stay in Login component memory.
    },
    async login(email: string, password: string) {
      await this.authenticate('login', { email, password })
    },
    async register(email: string, password: string) {
      await this.authenticate('register', { email, password })
    },
    async changePassword(data: any) {
      this.subscribe()
      const mode = authTransport.mode()
      const generation = authTransport.generation()
      if (!mode) throw new Error('登录已结束，请重新登录')
      return authTransport.authenticatedSessionOperation(generation, async (check: () => void) => {
        const response = await api.changePassword(data, { skipAuthRefresh: true, _authGeneration: generation })
        check()
        authTransport.invalidate() // The server revokes every device, including the current one.
        return response
      })
    },
    async logout() {
      this.subscribe()
      const legacy = authTransport.mode() === 'legacy_bearer'
      const authorization = legacy ? authTransport.headers('GET').Authorization : undefined
      authTransport.invalidate()
      const generation = authTransport.generation()
      try {
        await authTransport.sessionOperation(generation, async (check: () => void) => {
          await clearLangfuseSession()
          check()
          // CSRF is read by the client interceptor inside the lock, after any previous Cookie rotation.
          await api.logout({ headers: authorization ? { Authorization: authorization } : {}, _authGeneration: generation })
          check()
        }, { cookie: !legacy })
      } catch {
        throw new Error('此设备已退出，服务器撤销尚未确认；联网后请在其他设备撤销该会话。')
      }
    },
  },
})
