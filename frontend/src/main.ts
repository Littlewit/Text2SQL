import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'

// 应用入口：Pinia（状态）+ Router（页面）
createApp(App).use(createPinia()).use(router).mount('#app')
