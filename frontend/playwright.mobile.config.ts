import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  testMatch: 'mobile-pwa.spec.ts',
  outputDir: '../.cache/cross-device-p1/mobile-playwright-results',
  fullyParallel: false,
  workers: 1,
  reporter: 'line',
  use: { baseURL: 'http://127.0.0.1:4178', browserName: 'chromium', screenshot: 'only-on-failure', trace: 'retain-on-failure' },
  webServer: { command: 'npm run preview -- --port 4178 --host 127.0.0.1', url: 'http://127.0.0.1:4178', reuseExistingServer: false },
})
