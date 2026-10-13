import { defineConfig } from '@playwright/test'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const python = process.env.E2E_PYTHON || '/home/liuxuedeng/anaconda3/envs/django-agent/bin/python'
const port = 4180

export default defineConfig({
  testDir: './tests', testMatch: 'cross-device-auth.spec.ts',
  outputDir: '../.cache/cross-device-p1/auth-playwright-results',
  fullyParallel: false, workers: 1, reporter: 'line', timeout: 60000,
  use: { baseURL: `http://127.0.0.1:${port}`, browserName: 'chromium', screenshot: 'only-on-failure', trace: 'retain-on-failure', serviceWorkers: 'block' },
  webServer: {
    cwd: root,
    command: `"${python}" manage.py migrate --noinput && "${python}" -c "from django.core.management import execute_from_command_line; execute_from_command_line(['manage.py', 'runserver', '127.0.0.1:${port}', '--noreload'])"`,
    env: {
      APP_DATA_DIR: resolve(root, '.cache/cross-device-p1/auth-browser-runtime'), APP_MODE: 'api',
      DATABASE_URL: '', DJANGO_DB_PATH: '', DJANGO_SETTINGS_MODULE: 'config.settings', DJANGO_DEBUG: 'true',
      DJANGO_ALLOWED_HOSTS: '127.0.0.1,localhost', ALLOW_AUTO_SETUP: 'false',
    },
    url: `http://127.0.0.1:${port}/api/v1/capabilities`, reuseExistingServer: false,
    gracefulShutdown: { signal: 'SIGTERM', timeout: 3000 },
  },
})
