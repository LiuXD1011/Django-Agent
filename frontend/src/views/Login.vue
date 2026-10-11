<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const email = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')
const registration = ref(false)
const initialization = ref(false)
const confirmPassword = ref('')
// 一次性初始凭据只放组件内存：用户确认后才导航，离开页面即释放；
// 绝不写入 localStorage/sessionStorage、URL、日志或分析事件。
const setupCredentials = ref<{ email: string; password: string } | null>(null)
const setupCompletedWithoutCredentials = ref(false)

const SETUP_ERROR_MESSAGES: Record<string, string> = {
  setup_busy: '自动初始化正在进行中，请稍后重试。',
  auto_setup_disabled: '当前环境未开启自动初始化，请联系管理员或使用已有账号登录。',
  setup_already_completed: '自动初始化已完成，请使用已有账号登录。',
  service_identity_changed: '服务身份已改变，旧登录已失效。请重新登录；首次使用可再次点击自动初始化。',
}

async function submit() {
  if (loading.value) return
  if ((registration.value || initialization.value) && password.value !== confirmPassword.value) {
    error.value = '两次输入的密码不一致'
    return
  }
  loading.value = true
  error.value = ''
  try {
    if (initialization.value) {
      if (!email.value.trim() || !password.value) throw new Error('请填写管理员邮箱和密码')
      await auth.autoSetup({ email: email.value.trim(), password: password.value })
      password.value = ''
      confirmPassword.value = ''
    } else if (registration.value) await auth.register(email.value, password.value)
    else await auth.login(email.value, password.value)
    router.push('/platform/knowledge-bases')
  } catch (e: any) {
    error.value = !registration.value && !initialization.value && e?.error?.code === 'invalid_credentials'
      ? '邮箱或密码错误'
      : e?.message || e?.error?.message || '登录失败'
  } finally {
    loading.value = false
  }
}

async function quickStart() {
  if (loading.value) return
  loading.value = true
  error.value = ''
  setupCompletedWithoutCredentials.value = false
  try {
    const service = await auth.bindService()
    if (service.setup_requires_password) {
      if (!service.setup_required) {
        error.value = SETUP_ERROR_MESSAGES.setup_already_completed!
        return
      }
      initialization.value = true
      registration.value = false
      email.value ||= 'admin@knowledge.local'
      confirmPassword.value = ''
      return
    }
    const data: any = await auth.autoSetup()
    if (data?.temp_password) {
      setupCredentials.value = {
        email: data?.user?.email || 'admin',
        password: String(data.temp_password),
      }
    } else {
      // 未返回临时密码时不能伪造凭据：提示初始化已完成、需用已知凭据登录，
      // 留在当前页，不再自动触发初始化。
      setupCredentials.value = null
      setupCompletedWithoutCredentials.value = true
    }
  } catch (e: any) {
    error.value = SETUP_ERROR_MESSAGES[e?.error?.code || e?.code] || '自动初始化失败，请稍后重试或使用已有账号登录。'
  } finally {
    loading.value = false
  }
}

function confirmSetupCredentials() {
  setupCredentials.value = null
  router.push('/platform/knowledge-bases')
}
</script>

<template>
  <main class="login-page">
    <section class="login-brand">
      <div class="login-brand-logo"><span class="brand-mark">知</span><strong>个人轻量知识库</strong></div>
      <div class="login-brand-copy">
        <span class="paper-kicker">Knowledge workspace</span>
        <h1>让资料成为<br />可检索的知识</h1>
        <p>统一管理文档、Wiki 与知识图谱，通过智能检索和多 Agent 协作快速找到可靠答案。</p>
        <div class="login-capabilities"><span>混合检索</span><span>Wiki</span><span>知识图谱</span><span>多 Agent</span></div>
      </div>
    </section>
    <section class="login-form-area">
      <div class="login-panel">
        <div class="login-mobile-brand"><span class="brand-mark">知</span><strong>个人轻量知识库</strong></div>
        <span class="paper-kicker">Knowledge workspace</span>
        <h2>{{ initialization ? '初始化桌面工作台' : registration ? '创建个人账号' : '登录知识工作台' }}</h2>
        <p>{{ initialization ? '设置你自己的管理员密码，资料保存在本机的数据目录中' : registration ? '建立私有知识空间，在其他设备登录同一账号即可继续使用' : '使用同一账号，在电脑与手机访问你的知识库' }}</p>
        <t-input v-model="email" size="large" autocomplete="email" placeholder="邮箱" />
        <t-input v-model="password" size="large" type="password" :autocomplete="registration || initialization ? 'new-password' : 'current-password'" placeholder="密码" @enter="submit" />
        <t-input v-if="registration || initialization" v-model="confirmPassword" size="large" type="password" autocomplete="new-password" placeholder="确认密码" @enter="submit" />
        <t-alert v-if="error" theme="error" :message="error" />
        <div v-if="setupCredentials">
          <t-alert theme="success" message="自动初始化完成，请先保存以下初始管理员信息：" />
          <p>账号：{{ setupCredentials.email }}</p>
          <p>临时密码：{{ setupCredentials.password }}</p>
          <p>这是仅显示一次的初始凭据，建议立即保存，并尽快在「设置」中修改密码。</p>
        </div>
        <t-alert v-else-if="setupCompletedWithoutCredentials" theme="success" message="自动初始化已完成，本次未返回初始密码，请使用已有账号登录。" />
        <t-button block size="large" theme="primary" :loading="loading" @click="submit">{{ initialization ? '创建管理员并进入' : registration ? '注册并进入' : '登录' }}</t-button>
        <t-button v-if="initialization" block variant="text" :disabled="loading" @click="initialization = false; error = ''; password = ''; confirmPassword = ''">返回登录</t-button>
        <t-button v-else block variant="text" :disabled="loading" @click="registration = !registration; error = ''; confirmPassword = ''">{{ registration ? '已有账号，返回登录' : '创建个人账号' }}</t-button>
        <t-button v-if="setupCredentials" block size="large" theme="primary" @click="confirmSetupCredentials">已保存登录信息，进入工作台</t-button>
        <t-button v-else-if="!registration && !initialization" block variant="outline" :loading="loading" @click="quickStart">自动初始化</t-button>
      </div>
    </section>
  </main>
</template>
