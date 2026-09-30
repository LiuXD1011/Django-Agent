<script setup lang="ts">
import { onMounted, ref } from 'vue'
import client from '../../api/client'
import { openLangfuse } from '../../services/langfuse'
const status = ref<any>(null)
const busy = ref(false)
const message = ref('')
async function refresh() {
  busy.value = true
  try {
    const response: any = await client.get('/api/v1/observability/langfuse/status')
    status.value = response.data
    message.value = ''
  } catch (e: any) { message.value = e.message || e.error?.message || e.response?.data?.message || '服务状态暂时不可用' }
  finally { busy.value = false }
}
async function open() {
  busy.value = true
  try {
    await openLangfuse()
    message.value = status.value?.auto_login === false ? '已打开 Langfuse，请在新页面手动登录' : '已验证登录并打开 Langfuse'
  }
  catch (e: any) { message.value = e.message || e.error?.message || e.response?.data?.message || '登录暂时失败，请刷新状态后重试' }
  finally { busy.value = false }
}
onMounted(refresh)
</script>
<template>
  <section class="settings-section" data-testid="langfuse-settings">
    <h3>Langfuse 追踪</h3>
    <p>本地模式可自动启动服务并登录；关闭自动登录时，打开配置的 Langfuse 界面后手动登录。</p>
    <p v-if="status">服务：{{ status.state === 'healthy' ? '运行中' : '尚未就绪' }} ·
      账号：{{ status.credentials_configured ? '已配置' : '待配置' }} ·
      自动登录：{{ status.auto_login ? '开启' : '关闭' }}</p>
    <p>本地自动登录向已配置的本地账号和系统管理员开放，项目与 Langfuse 需使用相同主机名。</p>
    <t-space>
      <t-button :loading="busy" @click="open">打开 Langfuse</t-button>
      <t-button variant="outline" :disabled="busy" @click="refresh">刷新状态</t-button>
    </t-space>
    <p role="status">{{ message }}</p>
  </section>
</template>
