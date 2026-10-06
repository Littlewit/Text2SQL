import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

// 开发模式下 /api 代理到本地 FastAPI（docker-compose.dev.yml 的 api 服务）
export default defineConfig({
  plugins: [
    vue(),
    // Element Plus 按需导入：组件/指令/ElMessage 等 API 自动注入并携带样式（优化构建体积）
    AutoImport({ resolvers: [ElementPlusResolver()] }),
    Components({ resolvers: [ElementPlusResolver()] }),
  ],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
