import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const proxyTarget = process.env.VITE_PROXY_TARGET ?? 'http://192.168.29.100:8002'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': {
        target: proxyTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
})