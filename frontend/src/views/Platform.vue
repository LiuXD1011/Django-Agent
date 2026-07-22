<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { api } from '../api'
import {
  ChatIcon,
  DataBaseIcon,
  SettingIcon,
  BookOpenIcon,
  ChevronDownIcon,
} from 'tdesign-icons-vue-next'

type SidebarRecentItem = { id: string; label: string; path: string }

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const mainNav = [
  { path: '/platform/creatChat', label: '新对话', icon: ChatIcon, match: '/platform/chat' },
  { path: '/platform/knowledge-bases', label: '知识库', icon: DataBaseIcon, match: '/platform/knowledge-bases' },
]
const mobileNav = [
  { path: '/platform/knowledge-bases', label: '知识库', icon: DataBaseIcon, match: '/platform/knowledge-bases' },
  { path: '/platform/creatChat', label: '对话', icon: ChatIcon, match: '/platform/chat' },
  { path: '/platform/settings', label: '设置', icon: SettingIcon },
]
const recentItems = ref<SidebarRecentItem[]>([])
const recentLoading = ref(false)
const accountMenuOpen = ref(false)
const title = computed(() => {
  if (route.path.startsWith('/platform/settings')) return '设置'
  if (route.path.startsWith('/platform/chat') || route.path.endsWith('/creatChat')) return '对话'
  return '知识库'
})

function isActive(item: { path: string; match?: string }) {
  if (item.path.endsWith('/creatChat')) return route.path.endsWith('/creatChat') || route.path.startsWith('/platform/chat/')
  return route.path.startsWith(item.match || item.path)
}

async function loadRecentItems() {
  recentLoading.value = true
  try {
    if (route.path.startsWith('/platform/chat') || route.path.endsWith('/creatChat')) {
      const res: any = await api.listSessions({ page: 1, page_size: 5 })
      recentItems.value = (res.data?.items || []).slice(0, 5).map((item: any) => ({
        id: item.id,
        label: item.title || '新的对话',
        path: `/platform/chat/${item.id}`,
      }))
    } else {
      const res: any = await api.searchKbs({ page: 1, page_size: 5 })
      recentItems.value = (res.data?.items || res.data?.knowledge_bases || []).slice(0, 5).map((item: any) => ({
        id: item.id,
        label: item.name || '未命名知识库',
        path: `/platform/knowledge-bases/${item.id}`,
      }))
    }
  } catch {
    recentItems.value = []
  } finally {
    recentLoading.value = false
  }
}

function goAccount(section = 'user') {
  accountMenuOpen.value = false
  router.push({ path: '/platform/settings', query: { section } })
}

function logout() {
  accountMenuOpen.value = false
  auth.logout()
  router.push('/login')
}

watch(() => route.path, loadRecentItems)
onMounted(loadRecentItems)
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
          :class="{ active: isActive(item) }"
          @click="router.push(item.path)"
        >
          <component :is="item.icon" />
          <span>{{ item.label }}</span>
        </button>
      </nav>
      <section class="sidebar-recent" aria-label="最近访问">
        <div class="sidebar-recent-label">最近访问</div>
        <div v-if="recentLoading" class="sidebar-recent-empty">正在加载…</div>
        <button v-for="item in recentItems" :key="item.id" type="button" @click="router.push(item.path)">
          {{ item.label }}
        </button>
        <div v-if="!recentLoading && !recentItems.length" class="sidebar-recent-empty">暂无最近记录</div>
      </section>
      <div class="account-wrap">
        <div v-if="accountMenuOpen" class="account-menu" role="menu">
          <button type="button" role="menuitem" @click="goAccount('general')">常规设置</button>
          <button type="button" role="menuitem" @click="goAccount('user')">用户资料</button>
          <button type="button" role="menuitem" class="danger" @click="logout">退出登录</button>
        </div>
        <div class="account-entry">
          <button class="account-main" type="button" @click="goAccount('user')">
            <span class="account-avatar">{{ String(auth.user?.username || 'A').slice(0, 1).toUpperCase() }}</span>
            <span class="account-copy"><strong>{{ auth.user?.username || 'admin' }}</strong><small>账户与设置</small></span>
          </button>
          <button class="account-toggle" type="button" :aria-expanded="accountMenuOpen" aria-label="展开账户菜单" @click="accountMenuOpen = !accountMenuOpen">
            <ChevronDownIcon />
          </button>
        </div>
      </div>
    </aside>
    <section class="workspace">
      <header class="mobile-page-header">
        <h1>{{ title }}</h1>
        <button type="button" class="mobile-user-entry" @click="goAccount('user')">{{ String(auth.user?.username || 'A').slice(0, 1).toUpperCase() }}</button>
      </header>
      <router-view />
    </section>
    <nav class="mobile-tab-bar" aria-label="移动端主导航">
      <button
        v-for="item in mobileNav"
        :key="item.path"
        class="mobile-tab-item"
        :class="{ active: isActive(item) || (item.path.includes('settings') && route.path.startsWith('/platform/settings')) }"
        @click="router.push(item.path)"
      >
        <component :is="item.icon" />
        <span>{{ item.label }}</span>
      </button>
    </nav>
  </div>
</template>
