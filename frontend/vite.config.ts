import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Where the FastAPI backend runs during development.
const BACKEND_URL = 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Not Vite's default 5173, so this app never collides with other Vite projects.
    port: 5180,
    strictPort: true, // fail loudly instead of silently picking another port
    // The browser calls `/api/...` on the Vite server, and Vite forwards it
    // to FastAPI. No CORS setup needed, and no backend URL in frontend code.
    proxy: {
      '/api': {
        target: BACKEND_URL,
        changeOrigin: false,
      },
    },
  },
})
  