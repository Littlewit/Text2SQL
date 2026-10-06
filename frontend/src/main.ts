import { createApp } from 'vue'
import { createPinia } from 'pinia'
import 'element-plus/theme-chalk/dark/css-vars.css'
import App from './App.vue'
import router from './router'

// 应用入口：Pinia（状态）+ Router（页面）
// Element Plus 组件与样式由 unplugin 按需自动导入（见 vite.config.ts），
// 中文语言包在 App.vue 通过 el-config-provider 注入
createApp(App).use(createPinia()).use(router).mount('#app')
