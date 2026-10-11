<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { registerStaticWorker } from '../pwa/client.mjs'
import { desktopBridge } from '../api/desktop-transport.mjs'

type InstallEvent = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: string }> }
const route = useRoute()
const online = ref(navigator.onLine)
const updateReady = ref(false)
const dismissedUpdate = ref(false)
const helpVisible = ref(false)
const installEvent = ref<InstallEvent | null>(null)
const nativeDesktop = Boolean(desktopBridge)
const installed = ref(nativeDesktop || window.matchMedia('(display-mode: standalone)').matches)
const showInstall = computed(() => route.path === '/platform/settings' && !installed.value)
const syncNetwork = () => { online.value = navigator.onLine }
const captureInstall = (event: Event) => { event.preventDefault(); installEvent.value = event as InstallEvent }
const completeInstall = () => { installed.value = true; installEvent.value = null }

async function install() {
  if (!installEvent.value) { helpVisible.value = !helpVisible.value; return }
  const event = installEvent.value
  installEvent.value = null
  await event.prompt()
  if ((await event.userChoice).outcome === 'accepted') installed.value = true
}

onMounted(() => {
  window.addEventListener('online', syncNetwork)
  window.addEventListener('offline', syncNetwork)
  window.addEventListener('beforeinstallprompt', captureInstall)
  window.addEventListener('appinstalled', completeInstall)
  if (import.meta.env.PROD && !nativeDesktop) void registerStaticWorker({ navigator, location, onWaiting: () => { updateReady.value = true } })
})
onUnmounted(() => {
  window.removeEventListener('online', syncNetwork)
  window.removeEventListener('offline', syncNetwork)
  window.removeEventListener('beforeinstallprompt', captureInstall)
  window.removeEventListener('appinstalled', completeInstall)
})
</script>

<template>
  <aside v-if="!online || (updateReady && !dismissedUpdate) || showInstall" class="pwa-status" aria-label="应用连接与安装">
    <p v-if="!online" role="status">{{ nativeDesktop ? '网络已断开。在线模型和远程服务暂不可用，本地资料仍可查看。' : '网络已断开。云端内容、登录和问答需要联网；未提交输入仅留在当前页面。' }}</p>
    <div v-if="updateReady && !dismissedUpdate" role="status">
      <p>新版已就绪。请先保存输入并等待上传结束，再关闭此站点的所有页面与主屏幕窗口，重新打开更新。</p>
      <button type="button" @click="dismissedUpdate = true">暂不更新</button>
    </div>
    <button v-if="showInstall" type="button" @click="install">{{ installEvent ? '安装到主屏幕' : '主屏幕安装说明' }}</button>
    <p v-if="showInstall && helpVisible">Android：在支持的浏览器菜单中选择“安装应用”或“添加到主屏幕”。iPhone：在 Safari 分享菜单中选择“添加到主屏幕”。当前浏览器提供的选项为准；此入口不提供完整离线知识库。</p>
  </aside>
</template>
