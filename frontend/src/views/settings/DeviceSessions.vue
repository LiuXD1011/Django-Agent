<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../../api'
import { useAuthStore } from '../../stores/auth'
import { authTransport } from '../../api/auth-transport.mjs'

const router = useRouter()
const auth = useAuthStore()
const devices = ref<any[]>([])
const loading = ref(false)
const busy = ref('')
const error = ref('')
const selected = ref<any>(null)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res: any = await api.devices()
    devices.value = res.data?.items || []
  } catch (e: any) { error.value = e?.error?.message || e?.message || '设备列表加载失败，请重试。' }
  finally { loading.value = false }
}

async function revoke() {
  if (!selected.value || busy.value) return
  const device = selected.value
  const mode = authTransport.mode()
  const generation = authTransport.generation()
  if (!mode) { error.value = '登录已结束，请重新登录'; return }
  busy.value = device.id
  error.value = ''
  try {
    await authTransport.authenticatedSessionOperation(generation, async (check: () => void) => {
      await api.revokeDevice(device.id, { skipAuthRefresh: true, _authGeneration: generation })
      check()
      selected.value = null
      if (device.current) authTransport.invalidate()
    })
    if (device.current) await router.replace('/login')
    else await load()
  } catch (e: any) { error.value = e?.error?.message || e?.message || '撤销失败，请重试。' }
  finally { busy.value = '' }
}

async function logoutAll() {
  if (busy.value) return
  const mode = authTransport.mode()
  const generation = authTransport.generation()
  if (!mode) { error.value = '登录已结束，请重新登录'; return }
  busy.value = 'all'
  error.value = ''
  try {
    await authTransport.authenticatedSessionOperation(generation, async (check: () => void) => {
      await api.logoutAll({ skipAuthRefresh: true, _authGeneration: generation })
      check()
      authTransport.invalidate()
    })
    await router.replace('/login')
  } catch (e: any) { error.value = e?.error?.message || e?.message || '撤销所有设备失败，请重试。' }
  finally { busy.value = '' }
}

onMounted(() => { auth.subscribe(); load() })
</script>

<template>
  <main class="content device-page">
    <header class="device-header">
      <div><button type="button" @click="router.push({ path: '/platform/settings', query: { section: 'user' } })">返回用户资料</button><h2>登录设备</h2><p>每个设备独立登录；撤销旧设备不会影响其他设备。</p></div>
      <button type="button" :disabled="loading || !!busy" @click="load">刷新</button>
    </header>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="loading" role="status">正在加载设备…</p>
    <ul v-else class="device-list">
      <li v-for="device in devices" :key="device.id">
        <div><strong>{{ device.name || device.client_type || '浏览器' }}</strong><span v-if="device.current"> · 当前设备</span><span v-if="device.is_revoked"> · 已撤销</span><p>最近使用：{{ device.last_seen_at || device.created_at || '-' }}</p><small>不活动到期：{{ device.expires_at || '-' }} · 最长到期：{{ device.absolute_expires_at || '-' }}</small></div>
        <button type="button" :disabled="!!busy || device.is_revoked" @click="selected = device">撤销登录</button>
      </li>
    </ul>
    <p v-if="!loading && !devices.length && !error">暂无设备会话。旧版登录请重新登录以建立独立设备会话。</p>
    <details class="device-all"><summary>退出所有设备</summary><p>此操作也会退出当前设备。所有设备需要重新登录。</p><button type="button" :disabled="!!busy" @click="logoutAll">确认退出所有设备</button></details>
    <t-dialog :visible="!!selected" header="撤销设备登录" confirm-btn="撤销" :confirm-loading="!!busy" @close="selected = null" @confirm="revoke"><p>确定撤销“{{ selected?.name || '该设备' }}”的登录？{{ selected?.current ? '当前设备也将退出。' : '其他设备保持登录。' }}</p></t-dialog>
  </main>
</template>

<style scoped>
.device-page { max-width: 920px; margin: 0 auto; }
.device-header, .device-list li { display: flex; justify-content: space-between; gap: 16px; align-items: center; }
.device-list { padding: 0; list-style: none; }
.device-list li { padding: 20px 0; border-bottom: 1px solid var(--border, #ddd); overflow-wrap: anywhere; }
.device-list p { margin: 8px 0; }
.device-list small, .device-header p { color: var(--text-muted, #637083); }
.device-all { margin-top: 32px; }
.device-page button { min-height: 44px; cursor: pointer; }
@media (max-width: 640px) { .device-header, .device-list li { align-items: flex-start; flex-direction: column; } }
</style>
