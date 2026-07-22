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

async function submit() {
  loading.value = true
  error.value = ''
  try {
    await auth.login(email.value, password.value)
    router.push('/platform/knowledge-bases')
  } catch (e: any) {
    error.value = e?.message || e?.error?.message || '登录失败'
  } finally {
    loading.value = false
  }
}

async function quickStart() {
  loading.value = true
  await auth.autoSetup()
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
        <h2>登录知识工作台</h2>
        <p>使用账号继续管理你的知识库</p>
        <t-input v-model="email" size="large" autocomplete="email" placeholder="邮箱" />
        <t-input v-model="password" size="large" type="password" autocomplete="current-password" placeholder="密码" @enter="submit" />
        <t-alert v-if="error" theme="error" :message="error" />
        <t-button block size="large" theme="primary" :loading="loading" @click="submit">登录</t-button>
        <t-button block variant="outline" :loading="loading" @click="quickStart">自动初始化</t-button>
      </div>
    </section>
  </main>
</template>
