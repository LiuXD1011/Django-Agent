<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import { MoreIcon, PinIcon, DeleteIcon, ClearIcon } from 'tdesign-icons-vue-next'
import { groupSessions } from './sessionGroups'

const props = defineProps<{
  sessions: any[]
  activeId?: string
  loading?: boolean
  batchMode?: boolean
  selectedIds?: string[]
}>()
const emit = defineEmits<{
  newChat: []
  open: [id: string]
  delete: [id: string]
  clear: [id: string]
  pin: [session: any]
  batch: []
  toggleSelect: [id: string]
  deleteSelected: []
  deleteAll: []
}>()

const collapsed = ref(false)
const groups = computed(() => groupSessions(props.sessions || []))

// ── Floating menu state ──────────────────────────────────────────────
const menuOpenId = ref<string | null>(null)
const menuStyle = ref<Record<string, string>>({})
const triggerRefs = ref<Record<string, HTMLButtonElement>>({})

const MENU_WIDTH = 152
const MENU_GAP = 6
const VIEWPORT_MARGIN = 8

function setTriggerRef(id: string, el: any) {
  if (el) triggerRefs.value[id] = el as HTMLButtonElement
}

function updateMenuPosition(id: string) {
  const trigger = triggerRefs.value[id]
  if (!trigger) return
  const rect = trigger.getBoundingClientRect()
  const left = Math.max(
    VIEWPORT_MARGIN,
    Math.min(rect.right - MENU_WIDTH, window.innerWidth - MENU_WIDTH - VIEWPORT_MARGIN),
  )
  menuStyle.value = {
    top: `${rect.bottom + MENU_GAP}px`,
    left: `${left}px`,
  }
}

function closeMenu() {
  menuOpenId.value = null
  removeMenuListeners()
}

function removeMenuListeners() {
  document.removeEventListener('click', closeMenu)
  window.removeEventListener('resize', closeMenu)
  window.removeEventListener('scroll', closeMenu, true)
}

function toggleMenu(id: string) {
  if (menuOpenId.value === id) {
    closeMenu()
    return
  }
  updateMenuPosition(id)
  menuOpenId.value = id
  nextTick(() => {
    document.addEventListener('click', closeMenu)
    window.addEventListener('resize', closeMenu)
    window.addEventListener('scroll', closeMenu, true)
  })
}

function handleMenuAction(session: any, action: string) {
  closeMenu()
  if (action === 'pin') emit('pin', session)
  else if (action === 'clear') confirmAction('清空这个对话的全部消息？', () => emit('clear', session.id))
  else if (action === 'delete') confirmAction('删除这个对话？', () => emit('delete', session.id))
}

// ── Confirm helper ───────────────────────────────────────────────────
function confirmAction(message: string, action: () => void) {
  if (window.confirm(message)) action()
}

onBeforeUnmount(() => removeMenuListeners())
</script>

<template>
  <aside class="wk-session-sidebar" :class="{ collapsed }">
    <!-- Header -->
    <div class="session-sidebar-head">
      <button class="new-chat-btn" @click="$emit('newChat')">
        <span class="new-chat-icon">+</span>
        <span v-if="!collapsed">新对话</span>
      </button>
      <button class="collapse-btn" @click="collapsed = !collapsed" :title="collapsed ? '展开' : '收起'">
        <svg v-if="collapsed" width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M6 3l5 5-5 5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
        <svg v-else width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M10 3l-5 5 5 5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
      </button>
    </div>

    <!-- Batch bar -->
    <div v-if="!collapsed" class="session-batch-bar">
      <button class="batch-btn" @click="$emit('batch')">{{ batchMode ? '退出管理' : '批量管理' }}</button>
      <template v-if="batchMode">
        <button class="batch-btn danger" @click="confirmAction('删除已选择的对话？', () => $emit('deleteSelected'))">删除所选</button>
        <button class="batch-btn danger" @click="confirmAction('清空全部历史对话？', () => $emit('deleteAll'))">清空全部</button>
      </template>
    </div>

    <!-- Skeleton -->
    <div v-if="loading && !sessions.length" class="session-skeleton">
      <span></span><span></span><span></span>
    </div>

    <!-- Session list -->
    <div v-if="!collapsed" class="session-group-list">
      <div v-for="group in groups" :key="group.key" class="session-group">
        <div class="session-group-title">{{ group.label }}</div>
        <div
          v-for="session in group.items"
          :key="session.id"
          class="session-row"
          :class="{
            active: session.id === activeId,
            selected: selectedIds?.includes(session.id),
          }"
        >
          <!-- Batch checkbox -->
          <label v-if="batchMode" class="row-checkbox-wrap" @click.stop>
            <input
              type="checkbox"
              :checked="selectedIds?.includes(session.id)"
              @change="$emit('toggleSelect', session.id)"
            />
            <span class="row-checkbox-visual"></span>
          </label>

          <!-- Title area -->
          <button class="session-open" @click="$emit('open', session.id)">
            <PinIcon v-if="session.is_pinned" class="pin-icon" />
            <span class="session-title-text">{{ session.title || '新的对话' }}</span>
          </button>

          <!-- "..." menu trigger — hidden by default, shown on row hover -->
          <div v-if="!batchMode" class="session-menu-wrap" @click.stop>
            <button
              :ref="(el) => setTriggerRef(session.id, el)"
              type="button"
              class="menu-trigger"
              :aria-label="`管理对话 ${session.title || ''}`"
              :aria-expanded="menuOpenId === session.id"
              @click.stop="toggleMenu(session.id)"
            >
              <MoreIcon />
            </button>
          </div>
        </div>
      </div>

      <!-- Empty state -->
      <div v-if="!sessions.length && !loading" class="empty-state">
        <div class="empty-icon">💬</div>
        <span>暂无历史对话</span>
      </div>
    </div>

    <!-- Floating dropdown menu (teleported to body) -->
    <Teleport to="body">
      <Transition name="menu-fade">
        <div
          v-if="menuOpenId"
          class="session-dropdown"
          role="menu"
          :style="menuStyle"
          @click.stop
        >
          <button
            type="button"
            class="session-dropdown__item"
            role="menuitem"
            @click="handleMenuAction(sessions.find(s => s.id === menuOpenId), 'pin')"
          >
            <PinIcon class="session-dropdown__icon" />
            <span class="session-dropdown__text">
              {{ sessions.find(s => s.id === menuOpenId)?.is_pinned ? '取消置顶' : '置顶' }}
            </span>
          </button>
          <button
            type="button"
            class="session-dropdown__item"
            role="menuitem"
            @click="handleMenuAction(sessions.find(s => s.id === menuOpenId), 'clear')"
          >
            <ClearIcon class="session-dropdown__icon" />
            <span class="session-dropdown__text">清空消息</span>
          </button>
          <div class="session-dropdown__divider"></div>
          <button
            type="button"
            class="session-dropdown__item session-dropdown__item--danger"
            role="menuitem"
            @click="handleMenuAction(sessions.find(s => s.id === menuOpenId), 'delete')"
          >
            <DeleteIcon class="session-dropdown__icon" />
            <span class="session-dropdown__text">删除对话</span>
          </button>
        </div>
      </Transition>
    </Teleport>
  </aside>
</template>

<style scoped>
/* ── Sidebar container ─────────────────────────────────────────────── */
.wk-session-sidebar {
  display: flex;
  flex-direction: column;
  width: 260px;
  height: 100%;
  background: #f8f9fa;
  border-right: 1px solid #e8e8e8;
  transition: width 0.25s cubic-bezier(0.2, 0, 0, 1);
  overflow: hidden;
}
.wk-session-sidebar.collapsed {
  width: 56px;
}

/* ── Header ────────────────────────────────────────────────────────── */
.session-sidebar-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 12px 8px;
  gap: 8px;
}
.new-chat-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
  height: 36px;
  padding: 0 14px;
  border: none;
  border-radius: 8px;
  background: var(--brand-color, #4f46e5);
  color: #fff;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s, transform 0.1s;
  white-space: nowrap;
}
.new-chat-btn:hover {
  background: var(--brand-hover, #4338ca);
}
.new-chat-btn:active {
  transform: scale(0.97);
}
.new-chat-icon {
  font-size: 18px;
  line-height: 1;
  font-weight: 600;
}
.collapse-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: #86909c;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
  flex-shrink: 0;
}
.collapse-btn:hover {
  background: #e8e8e8;
  color: #4e5969;
}

/* ── Batch bar ─────────────────────────────────────────────────────── */
.session-batch-bar {
  display: flex;
  gap: 6px;
  padding: 0 12px 8px;
  flex-wrap: wrap;
}
.batch-btn {
  padding: 4px 10px;
  border: 1px solid #e0e0e0;
  border-radius: 6px;
  background: #fff;
  color: #4e5969;
  font-size: 12px;
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s;
}
.batch-btn:hover {
  border-color: #c9cdd4;
  color: #1d2129;
}
.batch-btn.danger {
  color: #f53f3f;
  border-color: #f53f3f40;
}
.batch-btn.danger:hover {
  background: #f53f3f0a;
  border-color: #f53f3f;
}

/* ── Skeleton ──────────────────────────────────────────────────────── */
.session-skeleton {
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.session-skeleton span {
  display: block;
  height: 36px;
  border-radius: 8px;
  background: linear-gradient(90deg, #f0f0f0 25%, #e8e8e8 50%, #f0f0f0 75%);
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
}
@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* ── Group list ────────────────────────────────────────────────────── */
.session-group-list {
  flex: 1;
  overflow-y: auto;
  padding: 0 8px 12px;
  scrollbar-width: thin;
  scrollbar-color: transparent transparent;
  transition: scrollbar-color 0.3s;
}
.session-group-list:hover {
  scrollbar-color: #c9cdd4 transparent;
}
.session-group-list::-webkit-scrollbar {
  width: 4px;
}
.session-group-list::-webkit-scrollbar-thumb {
  border-radius: 4px;
  background: transparent;
  transition: background 0.3s;
}
.session-group-list:hover::-webkit-scrollbar-thumb {
  background: #c9cdd4;
}

/* ── Group title ───────────────────────────────────────────────────── */
.session-group-title {
  padding: 12px 8px 4px;
  font-size: 11px;
  font-weight: 600;
  color: #c9cdd4;
  letter-spacing: 0.02em;
  text-transform: uppercase;
  user-select: none;
}

/* ── Session row ───────────────────────────────────────────────────── */
.session-row {
  display: flex;
  align-items: center;
  gap: 4px;
  position: relative;
  border-radius: 8px;
  margin: 1px 0;
  transition: background 0.15s;
  min-height: 40px;
}
.session-row:hover {
  background: #f2f3f5;
}
/* Show the "..." trigger on row hover */
.session-row:hover .menu-trigger {
  opacity: 1;
}
.session-row.active {
  background: #fff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}
.session-row.active .session-open {
  color: var(--brand-color, #4f46e5);
  font-weight: 500;
}
.session-row.selected {
  background: var(--brand-color-light, #eef2ff);
}

/* ── Checkbox (batch mode) ─────────────────────────────────────────── */
.row-checkbox-wrap {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  cursor: pointer;
}
.row-checkbox-wrap input {
  display: none;
}
.row-checkbox-visual {
  width: 16px;
  height: 16px;
  border: 1.5px solid #c9cdd4;
  border-radius: 4px;
  background: #fff;
  transition: border-color 0.15s, background 0.15s;
  position: relative;
}
.row-checkbox-wrap input:checked + .row-checkbox-visual {
  border-color: var(--brand-color, #4f46e5);
  background: var(--brand-color, #4f46e5);
}
.row-checkbox-wrap input:checked + .row-checkbox-visual::after {
  content: '';
  position: absolute;
  left: 4px;
  top: 1px;
  width: 5px;
  height: 9px;
  border: solid #fff;
  border-width: 0 2px 2px 0;
  transform: rotate(45deg);
}

/* ── Session open button ───────────────────────────────────────────── */
.session-open {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 1;
  min-width: 0;
  padding: 6px 8px;
  border: none;
  background: transparent;
  color: #1d2129;
  font-size: 13px;
  line-height: 1.4;
  text-align: left;
  cursor: pointer;
  border-radius: 8px;
  transition: color 0.15s;
}
.session-open:hover {
  color: var(--brand-color, #4f46e5);
}
.pin-icon {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--brand-color, #4f46e5);
  transform: rotate(-45deg);
}
.session-title-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ── Menu trigger ("...") ──────────────────────────────────────────── */
.session-menu-wrap {
  flex-shrink: 0;
  padding-right: 4px;
}
.menu-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #86909c;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.2s ease, background 0.15s, color 0.15s;
  font-size: 16px;
}
.session-row.active .menu-trigger {
  opacity: 1;
}
.menu-trigger:hover {
  background: #e8e8e8;
  color: #4e5969;
}

/* ── Floating dropdown menu ────────────────────────────────────────── */
.session-dropdown {
  position: fixed;
  z-index: 3000;
  min-width: 152px;
  padding: 4px;
  border: 1px solid #e8e8e8;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.96);
  backdrop-filter: blur(20px) saturate(180%);
  -webkit-backdrop-filter: blur(20px) saturate(180%);
  box-shadow:
    0 4px 16px rgba(0, 0, 0, 0.08),
    0 1px 4px rgba(0, 0, 0, 0.04);
}
.session-dropdown__item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  min-height: 34px;
  padding: 0 12px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #1d2129;
  font-size: 13px;
  line-height: 20px;
  text-align: left;
  cursor: pointer;
  transition: background 0.12s;
}
.session-dropdown__item:hover {
  background: #f2f3f5;
}
.session-dropdown__item--danger {
  color: #f53f3f;
  margin-top: 2px;
  border-top: 1px solid #f2f3f3;
  padding-top: 2px;
}
.session-dropdown__item--danger:hover {
  background: #f53f3f0a;
}
.session-dropdown__icon {
  flex-shrink: 0;
  font-size: 16px;
}
.session-dropdown__text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.session-dropdown__divider {
  height: 1px;
  margin: 4px 8px;
  background: #f2f3f5;
}

/* ── Menu transition ───────────────────────────────────────────────── */
.menu-fade-enter-active {
  animation: menuSlideIn 0.18s cubic-bezier(0.2, 0, 0, 1);
}
.menu-fade-leave-active {
  animation: menuSlideIn 0.12s cubic-bezier(0.2, 0, 0, 1) reverse;
}
@keyframes menuSlideIn {
  from {
    opacity: 0;
    transform: translateY(-4px) scale(0.96);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

/* ── Empty state ───────────────────────────────────────────────────── */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 32px 16px;
  color: #c9cdd4;
  font-size: 13px;
}
.empty-icon {
  font-size: 28px;
  opacity: 0.6;
}
</style>
