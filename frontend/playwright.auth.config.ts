import { defineConfig } from '@playwright/test'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const port = 4180

export default defineConfig({
  testDir: './tests', testMatch: 'cross-device-auth.spec.ts',
  outputDir: '../.cache/auth-typescript-e2e-results',
  fullyParallel: false, workers: 1, reporter: 'line', timeout: 60000,
  use: { baseURL: `http://127.0.0.1:${port}`, browserName: 'chromium', screenshot: 'only-on-failure', trace: 'retain-on-failure', serviceWorkers: 'block' },
  webServer: {
    cwd: resolve(root, 'frontend'),
    command: 'node tests/helpers/auth-e2e-server.mjs',
    url: `http://127.0.0.1:${port}/health`, reuseExistingServer: false,
    stdout: 'pipe', stderr: 'pipe', timeout: 60000,
    gracefulShutdown: { signal: 'SIGTERM', timeout: 10000 },
  },
})
