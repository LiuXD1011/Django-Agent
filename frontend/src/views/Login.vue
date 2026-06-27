<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const email = ref('admin@knowledge.local')
const password = ref('admin123456')
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
    <section class="login-panel">
      <div class="brand-mark">知</div>
      <h1>个人轻量知识库</h1>
      <p>知识库、检索、Agent 与 Wiki 工作台</p>
      <div class="meta-line">
        <span class="meta-pill">SQLite</span>
        <span class="meta-pill">FTS5</span>
        <span class="meta-pill">本地存储</span>
      </div>
      <t-input v-model="email" size="large" placeholder="邮箱" />
      <t-input v-model="password" size="large" type="password" placeholder="密码" @enter="submit" />
      <t-alert v-if="error" theme="error" :message="error" />
      <t-button block size="large" theme="primary" :loading="loading" @click="submit">登录</t-button>
      <t-button block variant="outline" :loading="loading" @click="quickStart">自动初始化</t-button>
    </section>
  </main>
</template>
