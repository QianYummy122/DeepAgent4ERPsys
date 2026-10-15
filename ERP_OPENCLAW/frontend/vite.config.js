import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    // 显式绑定 IPv4 回环地址。
    // Vite 默认只监听 localhost，在 Windows 上通常解析为 IPv6 的 ::1，
    // 导致 http://127.0.0.1:3000 无法访问（脚本/工具按 IPv4 探测时会误判为「未启动」）。
    // 这里绑定 127.0.0.1 以保证 127.0.0.1 与 localhost 都能访问；
    // 如需让局域网其它设备访问，改成 host: '0.0.0.0'（注意会暴露到局域网）。
    host: '127.0.0.1',
    port: 3000,  // 前端开发服务器端口
    strictPort: true,  // 端口被占用时直接报错，避免静默切到 3001 导致文档地址失效
    proxy: {
      // 将 /api 请求代理到后端
      '/api': {
        target: 'http://localhost:8090',  // 后端地址
        changeOrigin: true,
        // 不需要 rewrite，因为后端路由已经带 /api 前缀
      }
    }
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets'
  }
})
