import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import Login from '../views/Login.vue'
import Platform from '../views/Platform.vue'

const KnowledgeBases = () => import('../views/KnowledgeBases.vue')
const KnowledgeDetail = () => import('../views/KnowledgeDetail.vue')
const Chat = () => import('../views/Chat.vue')
const Settings = () => import('../views/Settings.vue')
const Evaluation = () => import('../views/Evaluation.vue')
const Wiki = () => import('../views/Wiki.vue')

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
        { path: 'settings', component: Settings },
        { path: 'evaluation', component: Evaluation },
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
