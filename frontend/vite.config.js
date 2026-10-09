import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// Vite 配置：开发服务器代理 /api -> http://localhost:8000
// 避免前端开发时跨域问题，同时保持生产环境可通过 Nginx 反向代理
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    port: 5173,
    proxy: {
      // 所有以 /api 开头的请求转发到后端 FastAPI 服务
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true
      }
    }
  }
})
