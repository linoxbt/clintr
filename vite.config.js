import { defineConfig } from 'vite'

export default defineConfig({
  publicDir: false,
  build: {
    outDir: 'web',
    emptyOutDir: false,
    lib: { entry: 'web/wallet-entry.js', formats: ['es'], fileName: () => 'wallet.bundle.js' },
    rollupOptions: { output: { codeSplitting: false } }
  }
})
