<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from '../../api'

interface SearchProvider {
  id: string; name: string; provider?: string; url?: string; base_url?: string; cx?: string; description?: string
  enabled?: boolean; status?: string; credential_fields?: Record<string, { configured: boolean }>
}
const labels: Record<string, string> = { duckduckgo: 'DuckDuckGo', searxng: 'SearXNG', google: 'Google', bing: 'Bing 兼容服务' }
const providers = ref<SearchProvider[]>([])
const types = ref<string[]>([])
const config = ref<Record<string, any>>({})
const identity = ref<any>(null)
const loading = ref(true), loaded = ref(false), busy = ref(false)
const error = ref(''), message = ref('')
const editorVisible = ref(false), editorError = ref('')
const emptyForm = () => ({ id: '', name: '', provider: 'duckduckgo', url: '', cx: '', description: '', api_key: '', enabled: true })
const form = ref(emptyForm())
const storedFields = ref<Record<string, { configured: boolean }>>({})
const endpointField = ref<'url' | 'base_url'>('url')
const target = ref<{ kind: 'delete' | 'credential'; item: SearchProvider; field?: string } | null>(null)
const results = ref<Record<string, string>>({})
let generation = 0
const editable = computed(() => {
  const me = identity.value, user = me?.user, tenant = me?.tenant
  if (!user || !tenant) return false
  return user.is_system_admin === true || user.can_access_all_tenants === true
    || tenant.space_type === 'personal' && String(tenant.personal_owner_id) === String(user.id)
    || (me.memberships || []).some((member: any) => String(member.tenant_id) === String(tenant.id) && ['owner', 'admin'].includes(member.role))
})
const disabled = computed(() => loading.value || !loaded.value || busy.value || !editable.value)
const enabled = (item: SearchProvider) => item.status === 'active' && item.enabled !== false
const selectable = computed(() => providers.value.filter(item => enabled(item) && types.value.includes(item.provider || '')))
const selected = computed(() => providers.value.find(item => item.id === config.value.provider_id))
const keyConfigured = computed(() => Object.entries(storedFields.value).some(([field, value]) => ['api_key', 'apiKey', 'apikey', 'token'].includes(field) && value.configured))
const credentialFields = (item: SearchProvider) => Object.entries(item.credential_fields || {}).filter(([, value]) => value.configured).map(([field]) => field)
const credentialLabel = (field: string) => ['api_key', 'apiKey', 'apikey'].includes(field) ? 'API Key' : field === 'token' ? 'Token' : field
const failure = (e: any, fallback: string) => e?.error?.message || e?.message || e?.response?.data?.message || fallback

async function load() {
  const version = ++generation
  loading.value = true; loaded.value = false; error.value = ''
  try {
    const [catalog, saved, kv, me]: any[] = await Promise.all([api.webSearchProviderTypes(), api.listWebSearchProviders(), api.getTenantKv('web-search-config'), api.me()])
    if (version !== generation) return
    types.value = (catalog.data.items || []).map((item: any) => item.provider)
    providers.value = saved.data.items || []; config.value = { ...(kv.data.value || {}), enabled: kv.data.value?.enabled !== false }; identity.value = me.data
    loaded.value = true
  } catch (e) { if (version === generation) error.value = failure(e, '搜索配置加载失败，请重试') }
  finally { if (version === generation) loading.value = false }
}
function openEditor(item?: SearchProvider) {
  if (disabled.value) return
  endpointField.value = item && !item.url && item.base_url ? 'base_url' : 'url'
  form.value = item ? { id: item.id, name: item.name, provider: item.provider || '', url: item.url || item.base_url || '', cx: item.cx || '',
    description: item.description || '', api_key: '', enabled: enabled(item) } : emptyForm()
  storedFields.value = item?.credential_fields || {}; editorError.value = ''; editorVisible.value = true
}
function closeEditor() {
  if (busy.value) return
  editorVisible.value = false; form.value.api_key = ''; editorError.value = ''
}
function changeType() { form.value.api_key = ''; editorError.value = '' }
function validate(): string {
  const data = form.value
  if (!data.name.trim()) return '请输入服务名称'
  if (!types.value.includes(data.provider)) return '请选择支持的搜索服务类型'
  if (data.provider !== 'duckduckgo' && !data.url.trim()) return '请输入服务 URL'
  if (data.url) {
    try {
      const url = new URL(data.url)
      if (!['http:', 'https:'].includes(url.protocol) || !url.hostname || url.username || url.password || url.search || url.hash || /[\s\\]/.test(data.url)) return '服务 URL 需为无凭据、查询参数和片段的 HTTP(S) 地址'
    } catch { return '请输入有效的 HTTP(S) 服务 URL' }
  }
  if (data.provider === 'google' && !data.cx.trim()) return '请输入 Google 搜索引擎 ID（cx）'
  if (['google', 'bing'].includes(data.provider) && !keyConfigured.value && !data.api_key) return '请输入 API Key'
  return ''
}
async function saveProvider() {
  if (disabled.value) return
  editorError.value = validate(); if (editorError.value) return
  busy.value = true
  try {
    const data = form.value
    const payload: Record<string, any> = { name: data.name.trim(), provider: data.provider, [endpointField.value]: data.url, cx: data.cx,
      description: data.description, enabled: data.enabled, status: data.enabled ? 'active' : 'inactive' }
    if (data.api_key) payload.api_key = data.api_key
    if (data.id) await api.updateWebSearchProvider(data.id, payload)
    else await api.createWebSearchProvider(payload)
    if (data.id) delete results.value[data.id]
    editorVisible.value = false; form.value.api_key = ''; message.value = '搜索服务已保存'
    await load()
  } catch (e) { editorError.value = failure(e, '保存失败，请重试') }
  finally { busy.value = false }
}
async function saveConfig() {
  if (disabled.value) return
  if (config.value.enabled === true && !selectable.value.some(item => item.id === config.value.provider_id)) { error.value = '启用前请选择可用的默认搜索服务'; return }
  busy.value = true; error.value = ''; message.value = ''
  try {
    const response: any = await api.updateTenantKv('web-search-config', { ...config.value })
    config.value = { ...response.data.value }; message.value = '搜索设置已保存'
  } catch (e) { error.value = failure(e, '保存搜索设置失败，请重试') }
  finally { busy.value = false }
}
async function testProvider(item: SearchProvider) {
  if (disabled.value) return
  busy.value = true; results.value[item.id] = '正在测试连接…'
  try {
    const response: any = await api.testWebSearchProvider(item.id), value = response.data
    results.value[item.id] = value.state === 'connected' ? `连接成功，本次返回 ${value.result_count} 条结果`
      : value.state === 'disabled' ? '服务已停用，未发出搜索请求' : value.state === 'not_configured' ? '服务配置不完整，请检查地址和凭据' : '无法确认连接状态'
  } catch (e) { results.value[item.id] = failure(e, '连接测试失败，请重试') }
  finally { busy.value = false }
}
async function confirmTarget() {
  if (!target.value || disabled.value) return
  busy.value = true; error.value = ''
  try {
    const current = target.value
    if (current.kind === 'delete') await api.deleteWebSearchProvider(current.item.id)
    else await api.clearWebSearchProviderCredential(current.item.id, current.field!)
    target.value = null; message.value = current.kind === 'delete' ? '搜索服务已删除' : `${credentialLabel(current.field!)} 已清除`
    delete results.value[current.item.id]; await load()
  } catch (e) { error.value = failure(e, '操作失败，请重试') }
  finally { busy.value = false }
}
onMounted(load)
onUnmounted(() => { generation++; form.value.api_key = '' })
</script>

<template>
  <section class="settings-section search-settings" data-testid="web-search-settings" :aria-busy="loading || busy">
    <div class="settings-section-head"><div><h3>联网搜索</h3><p>配置 Agent 使用的搜索服务，密钥加密保存且不回显。</p></div>
      <t-button theme="primary" variant="outline" :disabled="disabled" @click="openEditor()">添加搜索服务</t-button>
    </div>
    <p v-if="loading" role="status">正在加载搜索配置…</p>
    <p v-if="error" role="alert" class="search-error">{{ error }}</p>
    <t-button v-if="!loaded && !loading" variant="outline" @click="load">重新加载搜索配置</t-button>
    <template v-if="loaded">
      <p v-if="!editable" class="search-help">当前为只读模式，修改需要租户管理员权限。</p>
      <form class="search-config" @submit.prevent="saveConfig">
        <label class="search-switch"><input v-model="config.enabled" type="checkbox" :disabled="disabled" /> 允许联网搜索</label>
        <div class="search-field"><label for="search-default">默认搜索服务</label>
          <select id="search-default" v-model="config.provider_id" :disabled="disabled">
            <option value="">请选择默认服务</option>
            <option v-if="config.provider_id && !selectable.some(item => item.id === config.provider_id)" :value="config.provider_id" disabled>默认服务不可用，请重新选择</option>
            <option v-for="item in selectable" :key="item.id" :value="item.id">{{ item.name }} · {{ labels[item.provider || ''] || item.provider }}</option>
          </select>
        </div>
        <p v-if="config.provider_id && (!selected || !enabled(selected))" class="search-error">默认搜索服务已删除或停用，请重新选择。</p>
        <p class="search-help">保存后用于下一次搜索；对话中仍需主动开启联网搜索。</p>
        <div class="search-field"><label for="search-notes">备注</label><textarea id="search-notes" v-model="config.notes" :disabled="disabled" rows="2"></textarea></div>
        <t-button type="submit" :disabled="disabled" :loading="busy">保存搜索设置</t-button>
      </form>
      <p v-if="!providers.length" class="search-empty">尚未配置搜索服务</p>
      <div class="search-provider-grid">
        <article v-for="item in providers" :key="item.id" class="search-provider" :data-provider-id="item.id">
          <div class="search-provider-head"><strong>{{ item.name }}</strong><t-tag :theme="enabled(item) ? 'success' : 'default'">{{ enabled(item) ? '已启用' : '已停用' }}</t-tag></div>
          <p>{{ labels[item.provider || ''] || item.provider || '未指定类型' }}</p>
          <p class="search-url">{{ item.url || item.base_url || (item.provider === 'duckduckgo' ? '使用默认匿名搜索地址' : '未配置 URL') }}</p>
          <div class="search-provider-tags"><t-tag v-if="item.id === config.provider_id" theme="primary">默认服务</t-tag><t-tag v-if="credentialFields(item).length" theme="success">凭据已配置</t-tag><t-tag v-else variant="outline">未配置凭据</t-tag></div>
          <p v-if="item.description" class="search-help">{{ item.description }}</p>
          <div class="search-actions"><t-button size="small" variant="outline" :disabled="disabled" @click="openEditor(item)">编辑</t-button>
            <t-button size="small" variant="outline" :disabled="disabled" @click="testProvider(item)">测试连接</t-button>
            <t-button v-for="field in credentialFields(item)" :key="field" size="small" variant="outline" :disabled="disabled" @click="target = { kind: 'credential', item, field }">清除 {{ credentialLabel(field) }}</t-button>
            <t-button size="small" theme="danger" variant="outline" :disabled="disabled" @click="target = { kind: 'delete', item }">删除</t-button>
          </div>
          <p v-if="results[item.id]" role="status" class="search-help">{{ results[item.id] }}</p>
        </article>
      </div>
    </template>
    <p v-if="message" role="status" class="search-success">{{ message }}</p>
    <t-dialog v-if="editorVisible" :visible="true" :header="form.id ? '编辑搜索服务' : '添加搜索服务'" attach="body" placement="center"
      width="min(560px, calc(100vw - 32px))" :footer="false" destroy-on-close :confirm-on-enter="false" :close-btn="!busy"
      :close-on-esc-keydown="!busy" :close-on-overlay-click="!busy" @close="closeEditor">
      <form v-if="editorVisible" class="search-editor" @submit.prevent="saveProvider">
        <div class="search-field"><label for="search-name">服务名称</label><input id="search-name" v-model="form.name" :disabled="busy" /></div>
        <div class="search-field"><label for="search-type">服务类型</label><select id="search-type" v-model="form.provider" :disabled="busy" @change="changeType">
          <option v-if="form.provider && !types.includes(form.provider)" :value="form.provider" disabled>{{ form.provider }}（未支持）</option>
          <option v-for="type in types" :key="type" :value="type">{{ labels[type] || type }}</option>
        </select></div>
        <div class="search-field"><label for="search-url">服务 URL</label><input id="search-url" v-model="form.url" type="url" :disabled="busy" placeholder="http://localhost:8080/search" />
          <p v-if="form.provider === 'duckduckgo'" class="search-help">可留空，使用 DuckDuckGo 默认匿名地址。</p>
          <p v-if="form.provider === 'bing'" class="search-help">Bing 原公共 API 已停用，请填写明确支持的兼容服务地址。</p>
        </div>
        <div v-if="form.provider === 'google'" class="search-field"><label for="search-cx">搜索引擎 ID（cx）</label><input id="search-cx" v-model="form.cx" :disabled="busy" /></div>
        <div class="search-field"><label for="search-key">API Key</label><input id="search-key" v-model="form.api_key" type="password" autocomplete="new-password" :disabled="busy" :placeholder="keyConfigured ? '已配置，留空保留原凭据' : '匿名服务可留空'" /></div>
        <p class="search-help">密钥仅提交到当前核心。更换服务主机时请输入新密钥，或先清除原凭据。</p>
        <div class="search-field"><label for="search-description">用途说明</label><textarea id="search-description" v-model="form.description" rows="2" :disabled="busy"></textarea></div>
        <label class="search-switch"><input v-model="form.enabled" type="checkbox" :disabled="busy" /> 启用服务</label>
        <p v-if="editorError" role="alert" class="search-error">{{ editorError }}</p>
        <div class="search-editor-actions"><t-button variant="outline" :disabled="busy" @click="closeEditor">取消</t-button><t-button type="submit" :loading="busy" :disabled="busy">保存服务</t-button></div>
      </form>
    </t-dialog>
    <t-dialog :visible="!!target" :header="target?.kind === 'delete' ? '删除搜索服务' : '清除搜索凭据'" attach="body" placement="center"
      width="min(440px, calc(100vw - 32px))" confirm-btn="确认" :confirm-loading="busy" :close-btn="!busy"
      :close-on-esc-keydown="!busy" :close-on-overlay-click="!busy" @close="!busy && (target = null)" @confirm="confirmTarget">
      <p>{{ target?.kind === 'delete' ? `确定删除“${target.item.name}”？若它是默认服务，需要重新选择。` : `确定清除“${target?.item.name}”的 ${credentialLabel(target?.field || '')}？` }}</p>
      <p v-if="error" role="alert" class="search-error">{{ error }}</p>
    </t-dialog>
  </section>
</template>

<style scoped>
.search-settings { min-width: 0; }
.search-config, .search-provider { padding: 18px; border: 1px solid var(--border, #dbe3ee); border-radius: 8px; background: var(--surface, #fff); }
.search-config { display: grid; gap: 14px; margin: 18px 0; }
.search-config > .t-button { justify-self: start; }
.search-field { display: grid; gap: 6px; min-width: 0; }
.search-field > label { font-size: 13px; font-weight: 600; color: var(--text-strong, #18212f); }
.search-field input, .search-field select, .search-field textarea { width: 100%; min-width: 0; box-sizing: border-box; border: 1px solid var(--border, #dbe3ee); border-radius: 6px; padding: 9px 10px; background: var(--surface, #fff); color: var(--text-strong, #18212f); font: inherit; }
.search-field input:focus-visible, .search-field select:focus-visible, .search-field textarea:focus-visible { outline: 2px solid var(--primary, #007c91); outline-offset: 2px; }
.search-switch { display: flex; gap: 8px; align-items: center; font-size: 13px; }
.search-provider-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 290px), 1fr)); gap: 14px; }
.search-provider-head, .search-provider-tags, .search-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.search-provider-head { justify-content: space-between; }
.search-provider-head strong { overflow-wrap: anywhere; min-width: 0; }
.search-provider p { margin: 10px 0; }
.search-url { overflow-wrap: anywhere; color: var(--text-muted, #637083); font-size: 12px; }
.search-actions { margin-top: 14px; }
.search-help { margin: 0; color: var(--text-muted, #637083); font-size: 12px; line-height: 1.7; }
.search-empty { padding: 24px; text-align: center; color: var(--text-muted, #637083); border: 1px dashed var(--border, #dbe3ee); border-radius: 8px; }
.search-error { color: #b8322a; font-size: 13px; line-height: 1.6; }
.search-success { color: #16845b; font-size: 13px; }
.search-editor { display: grid; gap: 14px; max-height: calc(100dvh - 180px); overflow-y: auto; padding: 2px; }
.search-editor-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 10px; padding-top: 6px; }
@media (max-width: 600px) { .search-settings .settings-section-head { align-items: flex-start; flex-direction: column; gap: 12px; } }
</style>
