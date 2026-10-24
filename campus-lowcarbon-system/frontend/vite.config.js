import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src')
    }
  },
  server: {
    host: '0.0.0.0', // 允许局域网访问
    port: 5173,
    open: true,
    proxy: {
      // Python Flask 服务（图片验证接口）- 必须放在 /api 之前，优先匹配
      '/api/verify': {
        target: 'http://localhost:5000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '') // 去掉 /api 前缀，Python服务没有context-path
      },
      // Spring Boot 后端服务（所有业务接口：登录、注册、打卡等）
      // 注意：后端设置了 context-path: /api，所以需要保留 /api 前缀
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        rewrite: (path) => path // 保留完整路径，因为后端已经有 context-path: /api
      }
    }
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    sourcemap: false
  }
})
