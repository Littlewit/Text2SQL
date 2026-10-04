import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发模式下 /api 代理到本地 FastAPI（docker-compose.dev.yml 的 api 服务）
export default defineConfig({
  plugins: [vue()],
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
