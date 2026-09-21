/// <reference types="node" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))

/**
 * 构建产物直接输出到 Python 包内的 web_static 目录，
 * 这样 `pip install` 之后无需 Node 即可由 pr-review serve 直接提供页面。
 */
export default defineConfig({
  plugins: [react()],
  base: '/static/',
  build: {
    outDir: resolve(here, '../src/ai_pr_review/web_static'),
    emptyOutDir: true,
    assetsDir: 'assets',
    sourcemap: false,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8787',
    },
  },
})
