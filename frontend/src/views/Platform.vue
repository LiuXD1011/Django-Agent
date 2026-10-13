<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { api, subscribeKnowledgeBaseChanges } from '../api'
import { MessagePlugin } from 'tdesign-vue-next'
import {
  ChatIcon,
  DataBaseIcon,
  SettingIcon,
  BookOpenIcon,
  ChevronDownIcon,
  AddIcon,
} from 'tdesign-icons-vue-next'

type SidebarRecentItem = { id: string; label: string; path: string }

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const mainNav = [
  { path: '/platform/creatChat', label: '对话', icon: ChatIcon, match: '/platform/chat' },
  { path: '/platform/knowledge-bases', label: '知识库', icon: DataBaseIcon, match: '/platform/knowledge-bases' },
]
const mobileNav = [
  { id: 'knowledge', path: '/platform/knowledge-bases', label: '知识库', icon: DataBaseIcon, match: '/platform/knowledge-bases' },
  { id: 'chat', path: '/platform/creatChat', label: '问答', icon: ChatIcon, match: '/platform/chat' },
  { id: 'collect', path: '', label: '收集', icon: AddIcon },
  { id: 'account', path: '/platform/settings', label: '我的', icon: SettingIcon },
]
const collectVisible = ref(false)
const collectLoading = ref(false)
const collectError = ref('')
const collectTargets = ref<Array<{ id: string; name: string }>>([])

async function navigateMobile(item: typeof mobileNav[number]) {
  if (item.id === 'chat') return goChat()
  if (item.id === 'account') return goAccount('user')
  if (item.id !== 'collect') return router.push(item.path)
  collectVisible.value = true
  collectLoading.value = true
  collectError.value = ''
  try {
    const res: any = await api.searchKbs({ page: 1, page_size: 100 })
    collectTargets.value = res.data?.items || res.data?.knowledge_bases || []
  } catch {
    collectError.value = '知识库加载失败，请重试'
  } finally {
    collectLoading.value = false
  }
}

function chooseCollection(target: { id: string }) {
  collectVisible.value = false
  router.push({ path: `/platform/knowledge-bases/${target.id}`, query: { collect: '1' } })
}

/** 点「对话」：优先回到最近一个会话；没有任何会话才进入新对话草稿页。
 *  新建对话的入口保留在会话侧栏的「+ 新对话」，两个语义不再混用。 */
async function goChat() {
  try {
    const res: any = await api.listSessions({ page: 1, page_size: 1 })
    const latest = res.data?.items?.[0]
    if (latest?.id) {
      router.push(`/platform/chat/${latest.id}`)
      return
    }
  } catch {
    // 查询失败时退回草稿页，与旧行为一致
  }
  router.push('/platform/creatChat')
}
const recentItems = ref<SidebarRecentItem[]>([])
const recentLoading = ref(false)
const accountMenuOpen = ref(false)
const title = computed(() => {
  if (route.path.startsWith('/platform/settings')) return '设置'
  if (route.path.startsWith('/platform/evaluation')) return '评测工作台'
  if (route.path.startsWith('/platform/chat') || route.path.endsWith('/creatChat')) return '对话'
  return '知识库'
})

function isActive(item: { path: string; match?: string }) {
  if (item.path.endsWith('/creatChat')) return route.path.endsWith('/creatChat') || route.path.startsWith('/platform/chat/')
  return !!item.path && route.path.startsWith(item.match || item.path)
}

let recentRequest = 0
let recentDisposed = false
let unsubscribeKnowledgeBaseChanges: (() => void) | undefined

async function loadRecentItems() {
  const request = ++recentRequest
  const isCurrent = () => !recentDisposed && request === recentRequest
  if (!isCurrent()) return
  if (route.path.startsWith('/platform/evaluation')) {
    recentItems.value = []
    recentLoading.value = false
    return
  }
  recentLoading.value = true
  try {
    if (route.path.startsWith('/platform/chat') || route.path.endsWith('/creatChat')) {
      const res: any = await api.listSessions({ page: 1, page_size: 5 })
      if (!isCurrent()) return
      recentItems.value = (res.data?.items || []).slice(0, 5).map((item: any) => ({
        id: item.id,
        label: item.title || '新的对话',
        path: `/platform/chat/${item.id}`,
      }))
    } else {
      const res: any = await api.searchKbs({ page: 1, page_size: 5 })
      if (!isCurrent()) return
      recentItems.value = (res.data?.items || res.data?.knowledge_bases || []).slice(0, 5).map((item: any) => ({
        id: item.id,
        label: item.name || '未命名知识库',
        path: `/platform/knowledge-bases/${item.id}`,
      }))
    }
  } catch {
    if (isCurrent()) recentItems.value = []
  } finally {
    if (isCurrent()) recentLoading.value = false
  }
}

function goAccount(section = 'user') {
  accountMenuOpen.value = false
  router.push({ path: '/platform/settings', query: { section } })
}

async function logout() {
  accountMenuOpen.value = false
  try { await auth.logout() }
  catch (error: any) { MessagePlugin.warning(error?.message || '此设备已退出，服务器撤销尚未确认') }
  finally { router.push('/login') }
}

watch(() => route.path, loadRecentItems)
onMounted(() => {
  unsubscribeKnowledgeBaseChanges = subscribeKnowledgeBaseChanges(() => {
    if (route.path.startsWith('/platform/evaluation') || route.path.startsWith('/platform/chat') || route.path.endsWith('/creatChat')) return
    void loadRecentItems()
  })
  return loadRecentItems()
})
onUnmounted(() => {
  recentDisposed = true
  ++recentRequest
  unsubscribeKnowledgeBaseChanges?.()
})
</script>

<template>
  <div class="shell">
    <aside class="sidebar">
      <div class="logo"><BookOpenIcon /><span>个人轻量知识库</span></div>
      <nav class="nav-main">
        <button
          v-for="item in mainNav"
          :key="item.path"
          type="button"
          class="nav-item"
          :class="{ active: isActive(item) }"
          :aria-label="item.label"
          :title="item.label"
          :aria-current="isActive(item) ? 'page' : undefined"
          @click="item.label === '对话' ? goChat() : router.push(item.path)"
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
          <button class="account-main" type="button" aria-label="账户与设置" title="账户与设置" @click="goAccount('user')">
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
        <button type="button" aria-label="我的账户" class="mobile-user-entry" @click="goAccount('user')">{{ String(auth.user?.username || 'A').slice(0, 1).toUpperCase() }}</button>
      </header>
      <router-view />
    </section>
    <nav class="mobile-tab-bar" aria-label="移动端主导航">
      <button
        v-for="item in mobileNav"
        :key="item.id"
        type="button"
        class="mobile-tab-item"
        :class="{ active: item.id === 'collect' ? collectVisible : isActive(item) }"
        :aria-current="item.id !== 'collect' && isActive(item) ? 'page' : undefined"
        @click="navigateMobile(item)"
      >
        <component :is="item.icon" />
        <span>{{ item.label }}</span>
      </button>
    </nav>
    <t-dialog v-model:visible="collectVisible" header="收集到知识库" :footer="false" attach="body" dialog-class-name="mobile-collect-dialog">
      <p class="dialog-hint">先选目标知识库，再选择文件或主动拍照，确认后才上传到服务器。</p>
      <p v-if="collectLoading" role="status">正在加载知识库…</p>
      <div v-else-if="collectError" role="alert">
        <p>{{ collectError }}</p>
        <button class="text-link" type="button" @click="navigateMobile(mobileNav[2])">重试</button>
      </div>
      <div v-else class="mobile-collect-targets">
        <button v-for="target in collectTargets" :key="target.id" class="text-link" type="button" @click="chooseCollection(target)">{{ target.name }}</button>
        <template v-if="!collectTargets.length">
          <p>还没有知识库，请先创建一个。</p>
          <button class="text-link" type="button" @click="collectVisible = false; router.push('/platform/knowledge-bases')">前往知识库</button>
        </template>
      </div>
    </t-dialog>
  </div>
</template>
