<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import client from '../../api/client'

const props = defineProps<{ model: any }>()
const emit = defineEmits<{ close: [] }>()
const data = ref<any>(null)
const role = ref('chat')
const mode = ref('default')
const effort = ref('')
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const saved = ref(false)
const entry = computed(() => data.value?.entries?.find((e: any) => e.role === role.value))
const disabled = computed(() => loading.value || busy.value || !data.value?.editable)
const dirty = computed(() => !!entry.value && (
  entry.value.stale || mode.value !== entry.value.policy.mode ||
  (mode.value === 'on' ? effort.value || null : null) !== (entry.value.policy.effort || null)
))
const labels: Record<string, string> = {
  chat: '对话 / Agent', summary: '摘要', title: '标题', question: '推荐问题',
  extract: '信息抽取', vlm: '视觉理解', model: '当前模型',
}
const modes = [
  { value: 'default', label: '默认', description: '跟随模型设置' },
  { value: 'off', label: '关闭', description: '不启用额外思考' },
  { value: 'on', label: '开启', description: '自定义思考强度' },
]
const effortLabels: Record<string, string> = { low: '低 · 优先响应速度', high: '高 · 深入分析', max: '最高 · 更充分推理' }

function selectRole() {
  mode.value = entry.value?.policy.mode || 'default'
  effort.value = entry.value?.policy.effort || ''
  saved.value = false
  error.value = ''
}
async function load() {
  loading.value = true
  error.value = ''
  saved.value = false
  try {
    const result: any = await client.get('/api/v1/models/' + encodeURIComponent(props.model.id) + '/thinking')
    data.value = result.data
    if (!data.value.entries.some((e: any) => e.role === role.value)) role.value = data.value.entries[0]?.role
    selectRole()
  } catch (e: any) { error.value = e.message || e.error?.message || '加载失败，请重试。' }
  finally { loading.value = false }
}
async function save() {
  if (disabled.value || !entry.value || !dirty.value) return
  busy.value = true
  error.value = ''
  saved.value = false
  try {
    const result: any = await client.put('/api/v1/models/' + encodeURIComponent(props.model.id) + '/thinking', {
      role: role.value, revision: data.value.revision,
      policy: { mode: mode.value, effort: mode.value === 'on' ? effort.value || null : null },
    })
    data.value = result.data
    saved.value = true
  } catch (e: any) { error.value = e.message || e.error?.message || '保存失败，请重试。' }
  finally { busy.value = false }
}
function close() { if (!busy.value) emit('close') }
onMounted(load)
</script>

<template>
  <t-dialog :visible="true" header="模型思考级别" width="min(580px, calc(100vw - 32px))"
    attach="body" placement="center" :z-index="5000" dialog-class-name="thinking-settings-dialog"
    :footer="false" :close-on-overlay-click="false" :close-on-esc-keydown="!busy" :close-btn="!busy" @close="close">
    <div class="thinking-panel" data-testid="thinking-panel" :aria-busy="loading || busy">
      <div class="thinking-scroll">
      <div class="thinking-model">
        <span class="thinking-model-caption">当前模型</span>
        <strong>{{ model.display_name || model.name }}</strong>
        <span class="thinking-model-badge">{{ model.managed_by === 'env' ? '环境配置' : '自定义模型' }}</span>
      </div>

      <div v-if="loading" class="thinking-loading" role="status">正在读取思考设置…</div>
      <div v-else-if="entry" class="thinking-form">
        <div class="thinking-field">
          <label for="thinking-role">生效用途</label>
          <select id="thinking-role" v-model="role" :disabled="busy" @change="selectRole" aria-describedby="thinking-role-help">
            <option v-for="e in data.entries" :key="e.role" :value="e.role">{{ labels[e.role] || e.role }}</option>
          </select>
          <p id="thinking-role-help" class="thinking-help">只修改当前用途，其他用途保持不变。切换用途前请先保存。</p>
        </div>

        <fieldset class="thinking-mode-field">
          <legend>思考模式</legend>
          <div class="thinking-mode-options">
            <label v-for="item in modes" :key="item.value" class="thinking-mode-option"
              :class="{ selected: mode === item.value, unavailable: disabled || !entry.capability.modes.includes(item.value) }">
              <input v-model="mode" type="radio" name="thinking-mode" :value="item.value"
                :aria-label="item.label" :disabled="disabled || !entry.capability.modes.includes(item.value)" @change="saved = false" />
              <span><strong>{{ item.label }}</strong><small>{{ item.description }}</small></span>
            </label>
          </div>
        </fieldset>

        <div v-if="mode === 'on'" class="thinking-field thinking-effort">
          <label for="thinking-effort">思考强度</label>
          <select id="thinking-effort" v-model="effort" :disabled="disabled" @change="saved = false">
            <option value="">供应商默认强度</option>
            <option v-for="e in entry.capability.efforts" :key="e" :value="e">{{ effortLabels[e] || e }}</option>
          </select>
          <p class="thinking-help">更高强度可能增加响应时间与用量。</p>
        </div>

        <div class="thinking-note">
          <p>{{ mode === 'default' ? '保持现有模型行为，不额外发送思考参数。' : '保存后从下一轮调用开始生效，正在进行的对话不受影响。' }}</p>
          <p v-if="entry.capability.note" class="thinking-help">{{ entry.capability.note }}</p>
          <p v-if="entry.stale" class="thinking-warning">模型端点已变化，请重新保存设置。</p>
          <p v-if="!data.editable" class="thinking-warning">当前为只读模式，修改需要租户管理员权限。</p>
        </div>
      </div>
      <p v-else class="thinking-help">当前模型暂无可配置的思考用途。</p>

      <p v-if="error" class="thinking-error" role="alert">{{ error }}</p>
      <p v-if="saved" class="thinking-success" role="status">已保存，下一轮调用生效；其他角色保持不变。</p>

      </div>
      <div class="thinking-footer">
        <t-button variant="text" :disabled="loading || busy" @click="load">重新加载</t-button>
        <div class="thinking-footer-primary">
          <t-button variant="outline" :disabled="busy" @click="close">关闭</t-button>
          <t-button :disabled="disabled || !dirty" :loading="busy" @click="save">保存设置</t-button>
        </div>
      </div>
    </div>
  </t-dialog>
</template>

<style scoped>
.thinking-panel { color: var(--text, #243549); display: flex; flex-direction: column; min-height: 0; max-height: calc(100dvh - 160px); }
.thinking-scroll { min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding: 2px; }
.thinking-footer { flex: 0 0 auto; }
.thinking-model { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 10px; padding: 14px 16px; margin-bottom: 22px; border-radius: 8px; background: var(--surface-soft, #f5f8fc); border: 1px solid var(--border, #dbe3ee); }
.thinking-model-caption { width: 100%; color: var(--text-muted, #637083); font-size: 12px; }
.thinking-model strong { flex: 1; min-width: 0; overflow-wrap: anywhere; font-size: 15px; }
.thinking-model-badge { font-size: 11px; color: var(--text-muted, #637083); white-space: nowrap; }
.thinking-form { display: grid; gap: 22px; }
.thinking-field { display: grid; gap: 8px; min-width: 0; }
.thinking-field > label, .thinking-mode-field legend { font-size: 14px; font-weight: 600; }
.thinking-field select { width: 100%; min-width: 0; min-height: 40px; padding: 8px 12px; box-sizing: border-box; border: 1px solid var(--border, #dbe3ee); border-radius: 6px; background: var(--surface, #fff); color: inherit; font: inherit; }
.thinking-field select:focus-visible { outline: 2px solid var(--primary, #007c91); outline-offset: 2px; }
.thinking-mode-field { min-width: 0; border: 0; padding: 0; margin: 0; }
.thinking-mode-field legend { padding: 0; margin-bottom: 10px; }
.thinking-mode-options { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.thinking-mode-option { display: flex; align-items: flex-start; gap: 8px; min-width: 0; padding: 12px 10px; border: 1px solid var(--border, #dbe3ee); border-radius: 8px; cursor: pointer; }
.thinking-mode-option input { flex: 0 0 auto; width: 16px; height: 16px; margin: 2px 0 0; accent-color: var(--primary, #007c91); }
.thinking-mode-option strong { display: block; font-size: 14px; font-weight: 600; }
.thinking-mode-option small { display: block; margin-top: 5px; font-size: 11px; line-height: 1.5; color: var(--text-muted, #637083); }
.thinking-mode-option.selected { border-color: var(--primary, #007c91); background: var(--surface-soft, #f1f7fa); box-shadow: inset 0 0 0 1px var(--primary, #007c91); }
.thinking-mode-option.unavailable { opacity: .5; cursor: not-allowed; }
.thinking-mode-option:focus-within { outline: 2px solid var(--primary, #007c91); outline-offset: 2px; }
.thinking-help { margin: 0; color: var(--text-muted, #637083); font-size: 12px; line-height: 1.7; }
.thinking-note { display: grid; gap: 6px; padding: 12px 14px; background: var(--surface-soft, #f5f8fc); border-radius: 8px; font-size: 12px; line-height: 1.7; }
.thinking-note p { margin: 0; }
.thinking-warning { color: #8a5900; }
.thinking-error, .thinking-success { padding: 10px 12px; margin: 16px 0 0; font-size: 13px; border-radius: 6px; line-height: 1.6; }
.thinking-error { background: #fff1f0; color: #b42318; }
.thinking-success { background: #eaf8f1; color: #17663e; }
.thinking-loading { padding: 24px 0; text-align: center; color: var(--text-muted, #637083); }
.thinking-footer { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; margin-top: 24px; padding-top: 16px; border-top: 1px solid var(--border, #dbe3ee); }
.thinking-footer-primary { display: flex; flex-wrap: wrap; gap: 8px; }
@media (max-width: 480px) {
  .thinking-form { gap: 18px; }
  .thinking-mode-options { grid-template-columns: 1fr; }
  .thinking-mode-option { align-items: center; padding: 10px 12px; }
  .thinking-mode-option span { display: flex; flex: 1; justify-content: space-between; gap: 8px; align-items: center; }
  .thinking-mode-option small { margin: 0; }
  .thinking-footer { gap: 8px; }
}
</style>

<style>
.thinking-settings-dialog { box-sizing: border-box; max-height: calc(100dvh - 96px); display: flex; flex-direction: column; }
.thinking-settings-dialog .t-dialog__header { flex: 0 0 auto; }
.thinking-settings-dialog .t-dialog__body { min-height: 0; overflow: hidden; display: flex; flex-direction: column; }
</style>
