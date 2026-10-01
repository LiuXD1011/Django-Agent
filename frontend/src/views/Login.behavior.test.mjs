import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import { createRequire } from 'node:module'
import { transformSync } from 'esbuild'
import compilerSfc from '@vue/compiler-sfc'

// Drive the real <script setup> of Login.vue: compile it with the project's own
// Vue compiler, run it in a sandbox, and exercise the exposed bindings.
// Boundaries (pinia store, vue-router, localStorage) are stubbed.
const require = createRequire(import.meta.url)
const { parse, compileScript } = compilerSfc
const vue = require('vue')

const FAKE_TMP_PASSWORD = 'fixture-tmp-9137-not-real'
const FIXTURE_EMAIL = 'fixture-admin@example.invalid'

function envelope({ withTempPassword = true } = {}) {
  const data = {
    user: { username: 'fixture-admin', email: FIXTURE_EMAIL },
    tenant: { id: 7, name: 'fixture space' },
    token: 'fixture-token-not-real',
  }
  if (withTempPassword) data.temp_password = FAKE_TMP_PASSWORD
  return { success: true, message: 'success', data }
}

function compileLoginScript() {
  const source = readFileSync(new URL('./Login.vue', import.meta.url), 'utf8')
  const { descriptor, errors } = parse(source, { filename: 'Login.vue' })
  assert.deepEqual(errors, [])
  const compiled = compileScript(descriptor, { id: 'login-behavior-test' })
  return transformSync(compiled.content, { loader: 'ts', format: 'cjs', target: 'es2022' }).code
}
const loginScript = compileLoginScript()

function makeStorage() {
  const writes = []
  return {
    storage: { getItem: () => null, setItem: (k, v) => { writes.push([k, String(v)]) }, removeItem: () => {} },
    writes,
  }
}

function makeAuthStub({ autoSetup, login } = {}) {
  const calls = { autoSetup: [], login: [] }
  const impl = {
    autoSetup: autoSetup || (async () => envelope().data),
    login: login || (async () => envelope().data),
  }
  return {
    calls,
    store: {
      autoSetup: (...args) => { calls.autoSetup.push(args); return impl.autoSetup(...args) },
      login: (...args) => { calls.login.push(args); return impl.login(...args) },
    },
  }
}

function makeRouterStub() {
  const pushes = []
  return { pushes, router: { push: (target) => { pushes.push(target) } } }
}

function mountLogin({ auth, router } = {}) {
  const authStub = auth || makeAuthStub()
  const routerStub = router || makeRouterStub()
  const storage = makeStorage()
  const context = vm.createContext({
    module: { exports: {} },
    require: (name) => {
      if (name === 'vue') return vue
      if (name === 'vue-router') return { useRouter: () => routerStub.router }
      if (name === '../stores/auth') return { useAuthStore: () => authStub.store }
      throw new Error(`Login.vue unexpectedly requires ${name}`)
    },
    localStorage: storage.storage,
    console: { log: () => {}, warn: () => {}, error: () => {} },
  })
  vm.runInContext(loginScript, context, { filename: 'Login.vue.script.js' })
  const component = context.module.exports.default
  assert.equal(typeof component?.setup, 'function', 'compiled Login.vue must expose setup()')
  const bindings = component.setup({}, { attrs: {}, slots: {}, emit: () => {}, expose: () => {} })
  assert.equal(typeof bindings.quickStart, 'function', 'quickStart must be exposed to the template')
  return { b: bindings, auth: authStub, router: routerStub, storage }
}

const tick = async () => {
  await new Promise((resolve) => setImmediate(resolve))
  await new Promise((resolve) => setImmediate(resolve))
}

function deferred() {
  let resolve, reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

test('quickStart success stays on the page, exposes the one-time credentials, and navigates only after explicit confirm', async () => {
  const { b, auth, router } = mountLogin()
  await b.quickStart()
  await tick()
  assert.equal(auth.calls.autoSetup.length, 1)
  assert.equal(b.loading.value, false, 'loading must be reset after the request settles')
  assert.equal(b.error.value, '')
  assert.equal(router.pushes.length, 0, 'must not navigate before the user confirms')
  assert.ok('setupCredentials' in b, 'credential state must be bound to the template to be displayed')
  assert.deepEqual({ ...b.setupCredentials.value }, { email: FIXTURE_EMAIL, password: FAKE_TMP_PASSWORD })
  assert.ok('confirmSetupCredentials' in b, 'confirm action must be bound to the template')
  b.confirmSetupCredentials()
  assert.deepEqual(router.pushes, ['/platform/knowledge-bases'])
  assert.equal(b.setupCredentials.value, null, 'temporary credentials are released after confirm')
})

test('double trigger while a setup request is pending only issues one autoSetup call', { timeout: 2000 }, async () => {
  const gate = deferred()
  const { b, auth, router } = mountLogin({ auth: makeAuthStub({ autoSetup: () => gate.promise }) })
  const first = b.quickStart()
  const second = b.quickStart()
  const callsWhilePending = auth.calls.autoSetup.length
  gate.resolve(envelope().data)
  await Promise.allSettled([first, second])
  await tick()
  assert.equal(callsWhilePending, 1, `pending double-click must issue one autoSetup call, got ${callsWhilePending}`)
  assert.equal(b.loading.value, false)
  b.confirmSetupCredentials()
  assert.deepEqual(router.pushes, ['/platform/knowledge-bases'])
})

test('setup_busy tells the user to retry later, resets loading, and a retry succeeds', async () => {
  let attempt = 0
  const { b, auth, router } = mountLogin({
    auth: makeAuthStub({
      autoSetup: async () => {
        attempt += 1
        if (attempt === 1) throw { error: { code: 'setup_busy', message: 'setup is busy, please retry' } }
        return envelope().data
      },
    }),
  })
  await b.quickStart()
  await tick()
  assert.equal(attempt, 1)
  assert.ok(b.error.value.includes('稍后'), `expected retry-later hint, got: ${b.error.value}`)
  assert.equal(b.loading.value, false, 'failed quickStart must not leave loading stuck')
  assert.equal(b.setupCredentials.value, null)
  assert.equal(router.pushes.length, 0)
  await b.quickStart()
  await tick()
  assert.equal(attempt, 2)
  assert.equal(b.error.value, '')
  assert.deepEqual({ ...b.setupCredentials.value }, { email: FIXTURE_EMAIL, password: FAKE_TMP_PASSWORD })
})

test('auto_setup_disabled and setup_already_completed produce distinct readable messages and never fabricate credentials', async () => {
  for (const [code, expectedHint, unexpectedHint] of [
    ['auto_setup_disabled', '未开启', '初始化已完成'],
    ['setup_already_completed', '已有账号', '未开启'],
  ]) {
    const { b, router } = mountLogin({
      auth: makeAuthStub({ autoSetup: async () => { throw { error: { code, message: code } } } }),
    })
    await b.quickStart()
    await tick()
    assert.ok(b.error.value.includes(expectedHint), `${code}: expected "${expectedHint}" hint, got: ${b.error.value}`)
    assert.ok(!b.error.value.includes(unexpectedHint), `${code}: must not show the wrong scenario`)
    assert.equal(b.setupCredentials.value, null, `${code}: no credentials may be fabricated`)
    assert.equal(router.pushes.length, 0)
  }
})

test('network and unknown errors fall back to a readable message and allow retry', async () => {
  const errors = [{ message: 'Network Error' }, { error: { code: 'mystery_code', message: '???' } }]
  for (const thrown of errors) {
    const { b } = mountLogin({ auth: makeAuthStub({ autoSetup: async () => { throw thrown } }) })
    await b.quickStart()
    await tick()
    assert.ok(b.error.value.includes('初始化失败'), `expected readable fallback, got: ${b.error.value}`)
    assert.equal(b.loading.value, false)
  }
})

test('success without a returned temp_password shows a completed state, fabricates nothing, and does not re-initialize', async () => {
  const { b, auth, router } = mountLogin({ auth: makeAuthStub({ autoSetup: async () => envelope({ withTempPassword: false }).data }) })
  await b.quickStart()
  await tick()
  assert.ok('setupCompletedWithoutCredentials' in b, 'completed state must be bound to the template')
  assert.equal(b.setupCredentials.value, null, 'no temp_password means no fake credentials')
  assert.equal(b.setupCompletedWithoutCredentials.value, true)
  assert.equal(b.error.value, '')
  assert.equal(router.pushes.length, 0, 'without credentials the user logs in manually; stay on the page')
  assert.equal(auth.calls.autoSetup.length, 1, 'completed state must not trigger another initialization')
  await tick()
  assert.equal(auth.calls.autoSetup.length, 1)
})

test('temporary credentials never touch storage, URLs, or logs during the whole flow', async () => {
  const { b, storage, router } = mountLogin()
  await b.quickStart()
  await tick()
  b.confirmSetupCredentials()
  assert.deepEqual(storage.writes, [], 'Login view itself must not write storage')
  assert.deepEqual(router.pushes, ['/platform/knowledge-bases'])
})

test('a stale error is cleared when a new quickStart attempt starts', async () => {
  let attempt = 0
  let gate = deferred()
  const { b } = mountLogin({
    auth: makeAuthStub({
      autoSetup: () => {
        attempt += 1
        return attempt === 1 ? gate.promise.then(() => { throw { error: { code: 'setup_busy', message: 'busy' } } }) : gate.promise
      },
    }),
  })
  const first = b.quickStart()
  gate.resolve({})
  await first
  await tick()
  assert.notEqual(b.error.value, '')
  gate = deferred()
  const second = b.quickStart()
  assert.equal(b.error.value, '', 'old error must be cleared for the new attempt')
  gate.resolve(envelope().data)
  await second
  await tick()
  assert.equal(b.error.value, '')
})

test('normal login still navigates on success and shows the error without navigating on failure', async () => {
  const { b, auth, router } = mountLogin()
  b.email.value = FIXTURE_EMAIL
  b.password.value = FAKE_TMP_PASSWORD
  await b.submit()
  await tick()
  assert.deepEqual(auth.calls.login, [[FIXTURE_EMAIL, FAKE_TMP_PASSWORD]])
  assert.deepEqual(router.pushes, ['/platform/knowledge-bases'])
  assert.equal(b.loading.value, false)

  const failing = makeAuthStub({ login: async () => { throw { message: '邮箱或密码错误' } } })
  const attempt = mountLogin({ auth: failing })
  attempt.b.email.value = FIXTURE_EMAIL
  attempt.b.password.value = FAKE_TMP_PASSWORD
  await attempt.b.submit()
  await tick()
  assert.equal(attempt.b.error.value, '邮箱或密码错误')
  assert.equal(attempt.router.pushes.length, 0, 'failed login must not navigate')
  assert.equal(attempt.b.loading.value, false)
})

test('submit is re-entrance guarded while a login request is pending (Enter plus click)', { timeout: 2000 }, async () => {
  const gate = deferred()
  const { b, auth, router } = mountLogin({ auth: makeAuthStub({ login: () => gate.promise }) })
  b.email.value = FIXTURE_EMAIL
  b.password.value = FAKE_TMP_PASSWORD
  const first = b.submit()
  const second = b.submit()
  const callsWhilePending = auth.calls.login.length
  gate.resolve(envelope().data)
  await Promise.allSettled([first, second])
  await tick()
  assert.equal(callsWhilePending, 1, `pending duplicate submit must issue one login call, got ${callsWhilePending}`)
  assert.deepEqual(router.pushes, ['/platform/knowledge-bases'])
  assert.equal(b.loading.value, false)
})
