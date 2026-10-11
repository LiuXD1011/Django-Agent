import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { publicStaticShell } from './src/pwa/static-shell-plugin.mjs'

export default defineConfig({
  plugins: [vue(), publicStaticShell()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/files': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
    },
  },
})
