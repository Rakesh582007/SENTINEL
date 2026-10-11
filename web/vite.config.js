import fs from 'node:fs'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { viteSingleFile } from 'vite-plugin-singlefile'

// Where the FastAPI backend runs. The dev server proxies /api and /ws to it,
// so the browser only ever talks to the Vite origin (no CORS, works from
// another laptop on the same hotspot too). Override: BACKEND_URL=http://192.168.1.20:8000 npm run dev
const BACKEND = process.env.BACKEND_URL || 'http://localhost:8000'

const proxy = {
  '/api': { target: BACKEND, changeOrigin: true },
  '/ws': { target: BACKEND.replace(/^http/, 'ws'), ws: true, changeOrigin: true },
}

// `--mode standalone` swaps the real backend for an in-browser copy that replays
// the bundled 19-minute real sample (src/standalone/). Used for UI work without
// Python, and for the one-file build that can be opened anywhere. Never present
// it as live data: the UI shows a permanent banner in this mode.
function gzipAsBase64() {
  return {
    name: 'gzip-as-base64',
    load(id) {
      if (!id.endsWith('.json.gz')) return null
      return `export default ${JSON.stringify(fs.readFileSync(id).toString('base64'))}`
    },
  }
}

export default defineConfig(({ mode }) => {
  const standalone = mode === 'standalone'
  return {
    plugins: [react(), gzipAsBase64(), ...(standalone ? [viteSingleFile()] : [])],
    define: {
      __STANDALONE__: JSON.stringify(standalone),
    },
    server: { port: 5173, proxy },
    preview: { port: 4173, proxy },
    build: {
      outDir: standalone ? 'dist-standalone' : 'dist',
      chunkSizeWarningLimit: 1600,
    },
  }
})
