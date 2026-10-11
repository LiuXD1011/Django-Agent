<script setup lang="ts">
import { onMounted, ref } from 'vue'
import client from '../../api/client'

interface Status {
  enabled: boolean
  base_url: string
  fields: Record<string, { configured: boolean }>
}
const form = ref({ enabled: false, base_url: 'http://localhost:3000', public_key: '', secret_key: '' })
const status = ref<Status | null>(null)
const busy = ref(false)
const message = ref('')
const clearVisible = ref(false)

async function load() {
  busy.value = true
  try {
    const response = await client.get('/api/v1/integrations/langfuse/credentials')
    const data = response.data as Status
    status.value = data
    form.value = { enabled: data.enabled, base_url: data.base_url, public_key: '', secret_key: '' }
  } catch {
    message.value = '仅系统管理员可管理追踪 API 凭据；加载失败时请重试。'
  } finally { busy.value = false }
}
async function save(clear = false) {
  if (busy.value || !status.value) return
  busy.value = true
  try {
    if (clear) await client.delete('/api/v1/integrations/langfuse/credentials')
    else await client.put('/api/v1/integrations/langfuse/credentials', form.value)
    form.value.public_key = ''
    form.value.secret_key = ''
    clearVisible.value = false
    message.value = clear ? '追踪凭据已清除并停用' : '追踪凭据已加密保存'
    await load()
  } catch {
    message.value = '保存失败，请检查权限及 API 地址、凭据和启用状态。'
  } finally { busy.value = false }
}
onMounted(load)
</script>
<template>
  <section class="settings-group" data-testid="integration-credentials">
    <h4>追踪 API 凭据</h4>
    <p>系统管理员配置，全局生效。密钥加密保存，留空保留原值，不回显密钥。</p>
    <div v-if="status" class="editor-grid">
      <t-input v-model="form.base_url" label="API 地址" :disabled="busy" />
      <t-input v-model="form.public_key" type="password" label="Public Key" autocomplete="off"
        :placeholder="status.fields.public_key?.configured ? '已配置，留空不修改' : '请输入 Public Key'" :disabled="busy" />
      <t-input v-model="form.secret_key" type="password" label="Secret Key" autocomplete="new-password"
        :placeholder="status.fields.secret_key?.configured ? '已配置，留空不修改' : '请输入 Secret Key'" :disabled="busy" />
      <label><input v-model="form.enabled" type="checkbox" :disabled="busy" />启用追踪</label>
      <t-button :loading="busy" @click="save()">保存 API 配置</t-button>
      <t-button theme="danger" variant="outline" :disabled="busy" @click="clearVisible = true">清除凭据</t-button>
    </div>
    <t-button v-else :loading="busy" @click="load">重新加载 API 配置</t-button>
    <p role="status">{{ message }}</p>
    <t-dialog v-model:visible="clearVisible" header="清除追踪凭据" :confirm-loading="busy" @confirm="save(true)">
      清除后将停止向 Langfuse 上报，确定继续？
    </t-dialog>
  </section>
</template>
