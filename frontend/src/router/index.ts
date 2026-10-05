import { createRouter, createWebHistory } from 'vue-router'
import { currentUser } from '../api'

// 路由表：登录守卫 + 业务/管理导航分离（UX-07）
const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('../views/LoginView.vue') },
    { path: '/', name: 'chat', component: () => import('../views/ChatView.vue') },
    { path: '/history', name: 'history', component: () => import('../views/HistoryView.vue') },
    { path: '/favorites', name: 'favorites', component: () => import('../views/FavoritesView.vue') },
    { path: '/admin', name: 'admin', component: () => import('../views/AdminView.vue') },
  ],
})

router.beforeEach((to) => {
  if (to.name !== 'login' && !currentUser()) return { name: 'login' }
  if (to.name === 'login' && currentUser()) return { name: 'chat' }
})

export default router
