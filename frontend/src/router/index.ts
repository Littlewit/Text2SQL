import { createRouter, createWebHistory } from 'vue-router'

// 路由表：T0 仅注册占位页；/chat、/admin/* 在 T1/T4 中补充
const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'home',
      component: () => import('../App.vue'),
    },
  ],
})

export default router
