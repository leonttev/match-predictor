import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Bind every interface: by default the dev server listens on IPv6 ::1 only,
  // so http://127.0.0.1:5173 (and other devices on the network) cannot reach it.
  server: { host: true },
})
