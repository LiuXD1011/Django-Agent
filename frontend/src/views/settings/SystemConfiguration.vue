<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import client from '../../api/client'
import { configPayload, configSections } from './system-fields'

const props = defineProps<{ section: string }>()
const emit = defineEmits<{ saved: [] }>()
const schema = computed(() => configSections[props.section])
const status = ref<any>(null)
const form = ref<Record<string, any>>({})
const busy = ref(false)
const message = ref('')
const clearField = ref('')
const clearVisible = ref(false)

async function load() {
  busy.value = true
  status.value = null
  try {
    const response = await client.get('/api/v1/system/config/' + props.section)
    const data = response.data as any
    const values = data.values || {}
    form.value = Object.fromEntries(schema.value.fields.map(field => [
      field.key, field.kind === 'secret' ? '' : field.kind === 'list' ? (values[field.key] || []).join(', ') : values[field.key],
    ]))
    status.value = data
  } catch (error: any) {
    message.value = error.error?.message || error.message || '配置加载失败，请重试'
  } finally { busy.value = false }
}
async function save() {
  if (!status.value || busy.value) return
  busy.value = true
  try {
    await client.put('/api/v1/system/config/' + props.section, configPayload(schema.value.fields, form.value))
    await load()
    message.value = props.section === 'startup'
      ? status.value?.restart_required
        ? '启动配置已保存，支持字段将在重启后生效；保留字段不参与当前运行'
        : '启动配置已保存，当前生效值未改变；保留字段不参与当前运行'
      : '配置已保存并生效'
    emit('saved')
  } catch (error: any) {
    message.value = error.error?.message || error.message || '保存失败，请检查字段后重试'
  } finally { busy.value = false }
}
async function clearSecret() {
  if (!clearField.value || busy.value) return
  busy.value = true
  try {
    await client.delete('/api/v1/system/config/' + props.section, { data: { field: clearField.value } })
    clearVisible.value = false
    await load()
    message.value = '凭据已清除，相关服务已停用'
    emit('saved')
  } catch (error: any) { message.value = error.error?.message || error.message || '清除失败' }
  finally { busy.value = false }
}
async function testConnection() {
  busy.value = true
  try {
    const response = await client.post('/api/v1/system/config/' + props.section + '/test')
    const state = (response.data as any)?.state
    message.value = state === 'connected' ? '已保存配置的连接测试通过'
      : state === 'disabled' ? '服务已停用，请先启用并保存配置'
        : state === 'not_configured' ? '连接配置不完整，请先保存地址和凭据'
          : '服务尚未就绪，连接测试未通过'
  } catch (error: any) { message.value = error.error?.message || error.message || '连接测试失败' }
  finally { busy.value = false }
}
onMounted(load)
</script>
<template>
  <section class="configuration-panel" :data-testid="'system-config-' + section">
    <h4>{{ schema.title }}</h4>
    <p>{{ schema.description }}</p>
    <form v-if="status" @submit.prevent="save">
      <label v-for="field in schema.fields" :key="field.key" class="config-field">
        <span>{{ field.label }}</span>
        <input v-if="field.kind === 'boolean'" v-model="form[field.key]" type="checkbox" :disabled="busy" />
        <select v-else-if="field.kind === 'choice'" v-model="form[field.key]" :disabled="busy">
          <option v-for="choice in field.choices" :key="choice" :value="choice">{{ choice }}</option>
        </select>
        <input v-else-if="field.kind === 'number'" v-model.number="form[field.key]" type="number"
          :min="field.min" :max="field.max" :step="field.step || 1" :disabled="busy" required />
        <span v-else-if="field.kind === 'secret'" class="secret-control">
          <input v-model="form[field.key]" type="password" autocomplete="new-password" :disabled="busy"
            :placeholder="status.fields?.[field.key]?.configured ? '已配置，留空不修改' : '请输入凭据'" />
          <button type="button" :disabled="busy || !status.fields?.[field.key]?.configured"
            @click="clearField = field.key; clearVisible = true">清除</button>
        </span>
        <input v-else v-model="form[field.key]" type="text" :disabled="busy" />
        <small v-if="section === 'startup'" class="field-support">
          <template v-if="status.field_support?.[field.key]?.applied === true">由桌面核心启动时应用。</template>
          <template v-else-if="status.field_support?.[field.key]?.applied === false">保留兼容字段，当前桌面核心不应用。</template>
          <template v-else>当前运行时未提供支持状态。</template>
          {{ status.field_support?.[field.key]?.reason || '' }}
        </small>
      </label>
      <div v-if="section === 'startup'" class="runtime-status">
        <p>数据目录：{{ status.data_root }}</p>
        <p>数据库：{{ status.database_path }}</p>
        <p v-if="status.environment_overrides?.length">部署环境覆盖：{{ status.environment_overrides.join('、') }}；这些字段以当前部署环境为准。</p>
        <details><summary>查看当前生效值</summary><pre>{{ JSON.stringify(status.active, null, 2) }}</pre></details>
        <p v-if="status.restart_required">有启动配置等待重启生效。</p>
      </div>
      <t-space>
        <t-button type="submit" :loading="busy">保存{{ schema.title }}</t-button>
        <t-button variant="outline" :disabled="busy" @click="load">重新加载</t-button>
        <t-button v-if="['neo4j', 'langfuse'].includes(section)" variant="outline" :disabled="busy"
          @click="testConnection">测试已保存连接</t-button>
      </t-space>
    </form>
    <t-button v-else :loading="busy" @click="load">重新加载配置</t-button>
    <p role="status">{{ message }}</p>
    <t-dialog v-model:visible="clearVisible" header="清除凭据" :confirm-loading="busy" @confirm="clearSecret">
      确认清除这个凭据并停用相关服务？
    </t-dialog>
  </section>
</template>
<style scoped>
.configuration-panel { margin: 20px 0; padding: 20px; border: 1px solid var(--border-color, #dce2e8); border-radius: 12px; }
.configuration-panel p { color: var(--text-secondary, #667085); line-height: 1.6; overflow-wrap: anywhere; }
form { display: grid; gap: 16px; }
.config-field { display: grid; gap: 7px; }
.config-field input:not([type=checkbox]), select { box-sizing: border-box; width: 100%; min-width: 0; padding: 9px 12px; border: 1px solid var(--border-color, #cdd5df); border-radius: 6px; background: var(--bg-primary, #fff); color: inherit; }
.config-field input[type=checkbox] { justify-self: start; }
.field-support { color: var(--text-secondary, #667085); line-height: 1.6; overflow-wrap: anywhere; }
.secret-control { display: flex; gap: 8px; }
.runtime-status pre { white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
