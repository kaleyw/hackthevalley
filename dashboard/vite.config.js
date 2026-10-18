import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Port the FastAPI backend runs on. Set BACKEND_PORT if 8000 is taken, e.g. BACKEND_PORT=8001 npm run dev
const backendPort = process.env.BACKEND_PORT ?? '8000'
// Port vision/run.py serves its live camera preview on (STREAM_PORT in .env)
const streamPort = process.env.STREAM_PORT ?? '8090'

// The dev server forwards /api, /ws and /camera, so no CORS setup is needed.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': { target: `http://localhost:${backendPort}`, rewrite: (p) => p.replace(/^\/api/, '') },
      '/ws': { target: `ws://localhost:${backendPort}`, ws: true },
      '/camera': { target: `http://127.0.0.1:${streamPort}`, rewrite: (p) => p.replace(/^\/camera/, '') },
    },
  },
})
