import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 3000,
  },

  // Vitest. Coverage is emitted as lcov because the SonarCloud job imports it:
  // a source file Sonar analyses but cannot find in any coverage report is
  // scored 0% covered rather than unmeasured, so the report has to reach the
  // scanner for frontend coverage to mean anything.
  test: {
    environment: 'node',
    restoreMocks: true,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov'],
      include: ['src/**/*.{js,jsx}'],
      exclude: ['src/**/__tests__/**', 'src/main.jsx'],
    },
  },
})
