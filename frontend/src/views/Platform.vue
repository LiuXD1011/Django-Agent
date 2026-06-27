<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import {
  ChatIcon,
  DataBaseIcon,
  LogoGithubIcon,
  SettingIcon,
  BookOpenIcon,
} from 'tdesign-icons-vue-next'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const nav = [
  { path: '/platform/knowledge-bases', label: '知识库', icon: DataBaseIcon },
  { path: '/platform/creatChat', label: '对话', icon: ChatIcon },
  { path: '/platform/agents', label: 'Agent', icon: LogoGithubIcon },
  { path: '/platform/settings', label: '设置', icon: SettingIcon },
]
const title = computed(() => nav.find((n) => route.path.startsWith(n.path))?.label || '知识库')
</script>

<template>
  <div class="shell">
    <aside class="sidebar">
      <div class="logo"><BookOpenIcon /><span>个人轻量知识库</span></div>
      <button
        v-for="item in nav"
        :key="item.path"
        class="nav-item"
        :class="{ active: route.path.startsWith(item.path) }"
        @click="router.push(item.path)"
      >
        <component :is="item.icon" />
        <span>{{ item.label }}</span>
      </button>
    </aside>
    <section class="workspace">
      <header class="topbar">
        <div>
          <div class="paper-kicker">Workspace</div>
          <h1>{{ title }}</h1>
          <p>{{ auth.tenant?.name || '默认空间' }}</p>
        </div>
        <div class="user-chip">
          <span>{{ auth.user?.username || 'admin' }}</span>
        </div>
      </header>
      <router-view />
    </section>
  </div>
</template>
