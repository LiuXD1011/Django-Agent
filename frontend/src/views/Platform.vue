<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import {
  ChatIcon,
  DataBaseIcon,
  SettingIcon,
  BookOpenIcon,
} from 'tdesign-icons-vue-next'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const mainNav = [
  { path: '/platform/knowledge-bases', label: '知识库', icon: DataBaseIcon },
  { path: '/platform/creatChat', label: '对话', icon: ChatIcon },
]
const bottomNav = [
  { path: '/platform/settings', label: '设置', icon: SettingIcon },
]
const title = computed(() => [...mainNav, ...bottomNav].find((n) => route.path.startsWith(n.path))?.label || '知识库')
</script>

<template>
  <div class="shell">
    <aside class="sidebar">
      <div class="logo"><BookOpenIcon /><span>个人轻量知识库</span></div>
      <nav class="nav-main">
        <button
          v-for="item in mainNav"
          :key="item.path"
          class="nav-item"
          :class="{ active: route.path.startsWith(item.path) }"
          @click="router.push(item.path)"
        >
          <component :is="item.icon" />
          <span>{{ item.label }}</span>
        </button>
      </nav>
      <nav class="nav-bottom">
        <button
          v-for="item in bottomNav"
          :key="item.path"
          class="nav-item"
          :class="{ active: route.path.startsWith(item.path) }"
          @click="router.push(item.path)"
        >
          <component :is="item.icon" />
          <span>{{ item.label }}</span>
        </button>
      </nav>
    </aside>
    <section class="workspace">
      <header class="topbar">
        <div>
          <h1>{{ title }}</h1>
        </div>
        <div class="user-chip">
          <span>{{ auth.user?.username || 'admin' }}</span>
        </div>
      </header>
      <router-view />
    </section>
  </div>
</template>
