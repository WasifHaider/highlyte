import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    // Only the Remotion composition (renderer/src, .tsx) is React; the app itself stays Vue.
    react({ include: /\.(jsx|tsx)$/ }),
  ],
  resolve: {
    alias: {
      '@renderer': fileURLToPath(new URL('../renderer/src', import.meta.url)),
    },
    // renderer/ has its own node_modules. Without dedupe the composition
    // would import a second copy of remotion/react, and the Player's
    // context wouldn't reach it.
    dedupe: ['react', 'react-dom', 'remotion', '@remotion/player', '@remotion/google-fonts', 'zod'],
  },
  server: {
    port: 6100,
    strictPort: true,
    fs: { allow: ['..'] },
    // The API is served from this same origin in development, so the
    // backend's httpOnly login cookies travel with every request.
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
  preview: {
    port: 6100,
    strictPort: true,
    // Same proxy as the dev server, so a production build served by
    // `vite preview` can log in too.
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
