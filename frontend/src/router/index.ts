import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import Login from '../views/Login.vue'
import Platform from '../views/Platform.vue'
import KnowledgeBases from '../views/KnowledgeBases.vue'
import KnowledgeDetail from '../views/KnowledgeDetail.vue'
import Chat from '../views/Chat.vue'
import Agents from '../views/Agents.vue'
import Settings from '../views/Settings.vue'
import Wiki from '../views/Wiki.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/platform/knowledge-bases' },
    { path: '/login', component: Login, meta: { public: true } },
    {
      path: '/platform',
      component: Platform,
      children: [
        { path: '', redirect: '/platform/knowledge-bases' },
        { path: 'knowledge-bases', component: KnowledgeBases },
        { path: 'knowledge-bases/:kbId', component: KnowledgeDetail },
        { path: 'knowledge-bases/:kbId/wiki', component: Wiki },
        { path: 'chat/:chatId', component: Chat },
        { path: 'agents', component: Agents },
        { path: 'settings', component: Settings },
        { path: 'creatChat', component: Chat },
        { path: 'knowledge-bases/:kbId/creatChat', component: Chat },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (to.meta.public) return true
  if (!auth.token) {
    try {
      await auth.autoSetup()
    } catch {
      return '/login'
    }
  }
  return true
})

export default router
