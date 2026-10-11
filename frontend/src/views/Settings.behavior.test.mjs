import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import vm from 'node:vm'
import { transformSync } from 'esbuild'
import { parse, compileScript } from '@vue/compiler-sfc'

const require = createRequire(import.meta.url)
const vue = require('vue')
const { descriptor } = parse(readFileSync(new URL('./Settings.vue', import.meta.url), 'utf8'))
const script = transformSync(compileScript(descriptor, { id: 'settings-behavior' }).content, {
  loader: 'ts', format: 'cjs', target: 'es2022',
}).code

function mountSettings(chatHistory = {}, changePassword = async () => { throw { error: { message: '当前密码不正确' } } }, systemInfo = {}) {
  const errors = []
  const passwordCalls = []
  const successes = []
  const navigations = []
  const api = new Proxy({
    systemInfo: async () => ({ data: systemInfo }),
    me: async () => ({ data: { user: { username: 'fixture-user', email: 'fixture@invalid.test' } } }),
    getTenantKv: async (key) => ({ data: { value: key === 'chat-history-config' ? chatHistory : {} } }),
  }, { get: (target, key) => target[key] || (async () => ({ data: {} })) })
  const scope = vue.effectScope()
  const context = vm.createContext({
    module: { exports: {} }, console,
    require: (name) => {
      if (name === 'vue') return { ...vue, onMounted: () => {} }
      if (name === 'vue-router') return { useRoute: () => ({ query: {} }), useRouter: () => ({ replace: (path) => navigations.push(path) }) }
      if (name === '../api') return { api }
      if (name === '../stores/auth') return { useAuthStore: () => ({ changePassword: async (data) => {
        passwordCalls.push({ ...data })
        return changePassword(data)
      } }) }
      if (name === 'tdesign-vue-next') return { MessagePlugin: { success: (message) => successes.push(message), warning: () => {}, error: (message) => errors.push(message) } }
      if (name.endsWith('.vue')) return { default: {} }
      if (name.endsWith('model-presets')) return { modelPresets: [], presetsForType: () => [] }
      throw new Error(`Unexpected import: ${name}`)
    },
  })
  vm.runInContext(script, context)
  const b = scope.run(() => context.module.exports.default.setup({}, { expose: () => {} }))
  return { b, errors, passwordCalls, successes, navigations, dispose: () => scope.stop() }
}

test('history checkbox agrees with the enabled default and preserves an explicit opt-out', async () => {
  for (const [saved, expected] of [[{}, true], [{ enabled: false }, false]]) {
    const { b, dispose } = mountSettings(saved)
    try { await b.load(); assert.equal(b.kv.value.chatHistory.enabled, expected) }
    finally { dispose() }
  }
})

test('system dimensions never fabricate 384 and distinguish declared values from actual indexed verification', async () => {
  for (const [info, expected] of [
    [{}, '未配置'],
    [{ embedding: { dimension: null } }, '未配置'],
    [{ embedding: { dimension: 1536, dimension_verified: false } }, '1536（待索引验证）'],
    [{ embedding: { dimension: 1024, dimension_verified: true } }, '1024（已索引验证）'],
    [{ bailian: { local_embedding_dimension: 768 } }, '768（待索引验证）'],
  ]) {
    const { b, dispose } = mountSettings({}, undefined, info)
    try { await b.load(); assert.equal(b.embeddingDimensionLabel?.value, expected) }
    finally { dispose() }
  }
})

test('closing and reopening the password dialog clears passwords, visibility toggles, and errors', () => {
  const { b, dispose } = mountSettings()
  try {
    assert.equal(b.passwordDialogVisible.value, false)
    b.openPasswordDialog()
    assert.equal(b.passwordDialogVisible.value, true)
    b.passwordForm.value.old_password = 'fixture-password'
    b.passwordShown.value.old_password = true
    b.passwordErrors.value.old_password = 'fixture-error'
    b.passwordError.value = 'fixture-error'
    b.closePasswordDialog()
    assert.equal(b.passwordDialogVisible.value, false)
    b.openPasswordDialog()
    assert.deepEqual(Object.values(b.passwordForm.value), ['', '', ''])
    assert.deepEqual(Object.values(b.passwordShown.value), [false, false, false])
    assert.deepEqual(Object.values(b.passwordErrors.value), ['', '', ''])
    assert.equal(b.passwordError.value, '')
  } finally { dispose() }
})

test('incomplete or mismatched passwords show field errors without calling the API', async () => {
  const { b, passwordCalls, dispose } = mountSettings()
  try {
    b.openPasswordDialog()
    await b.changePassword()
    assert.equal(b.passwordErrors.value.old_password, '请输入当前密码')
    assert.equal(b.passwordErrors.value.new_password, '请输入新密码')
    assert.equal(b.passwordErrors.value.confirm_password, '请再次输入新密码')
    b.passwordForm.value = { old_password: 'fixture-current', new_password: 'fixture-new', confirm_password: 'different' }
    await b.changePassword()
    assert.equal(b.passwordErrors.value.old_password, '')
    assert.equal(b.passwordErrors.value.new_password, '')
    assert.equal(b.passwordErrors.value.confirm_password, '两次输入的新密码不一致')
    assert.equal(passwordCalls.length, 0)
    assert.equal(b.passwordDialogVisible.value, true)
  } finally { dispose() }
})

test('wrong password stays in the dialog and displays the API validation message', async () => {
  const { b, passwordCalls, dispose } = mountSettings()
  try {
    b.openPasswordDialog()
    b.passwordForm.value = { old_password: 'wrong', new_password: 'fixture-password', confirm_password: 'fixture-password' }
    await b.changePassword()
    assert.equal(b.passwordError.value, '当前密码不正确')
    assert.equal(b.passwordDialogVisible.value, true)
    assert.equal(b.passwordForm.value.new_password, 'fixture-password')
    assert.equal(b.passwordSaving.value, false)
    assert.equal(passwordCalls.length, 1)
  } finally { dispose() }
})

// PWD-UI-01/02: real core error codes, reported by the owned account UI audit.
for (const [id, code, message, nextPassword, expected] of [
  ['PWD-UI-01', 'old_password_mismatch', 'Old password mismatch', 'fixture-password', '当前密码不正确'],
  ['PWD-UI-02', 'invalid_password', 'Password is required', 'x'.repeat(4097), '新密码不能为空或过长，请重新输入'],
]) {
  test(`${id} localizes the known password code without changing the submission or dialog`, async () => {
    const failure = { success: false, message, error: { code, message, details: {} }, status: 400 }
    const { b, passwordCalls, successes, navigations, dispose } = mountSettings({}, async () => { throw failure })
    try {
      b.openPasswordDialog()
      b.passwordForm.value = { old_password: 'fixture-current', new_password: nextPassword, confirm_password: nextPassword }
      await b.changePassword()
      assert.equal(b.passwordError.value, expected)
      assert.equal(b.passwordDialogVisible.value, true)
      assert.equal(b.passwordSaving.value, false)
      assert.equal(passwordCalls.length, 1)
      assert.equal(passwordCalls[0].old_password, 'fixture-current')
      assert.ok(passwordCalls[0].new_password === nextPassword, 'submitted password is never trimmed or truncated')
      assert.ok(b.passwordForm.value.new_password === nextPassword, 'validation failure retains the entered password')
      assert.deepEqual(successes, [])
      assert.deepEqual(navigations, [])
    } finally { dispose() }
  })
}

test('PWD-UI-03/04 preserves unknown error priority, session messages, and the generic fallback', async () => {
  for (const [failure, expected] of [
    [{ error: { code: 'unknown_password_error', message: '具体服务错误' }, message: 'outer message' }, '具体服务错误'],
    [{ message: '顶层具体消息', response: { data: { message: 'response message' } } }, '顶层具体消息'],
    [{ response: { data: { message: '响应具体消息' } } }, '响应具体消息'],
    [new Error('登录已结束'), '登录已结束'],
    [{ status: 401, error: { code: 'unauthorized', message: 'Authentication required' } }, 'Authentication required'],
    [{ code: 'old_password_mismatch', message: '顶层非业务码消息' }, '顶层非业务码消息'],
    [{}, '密码修改失败，请重试'],
  ]) {
    const { b, passwordCalls, successes, navigations, dispose } = mountSettings({}, async () => { throw failure })
    try {
      b.openPasswordDialog()
      b.passwordForm.value = { old_password: 'fixture-current', new_password: 'fixture-next', confirm_password: 'fixture-next' }
      await b.changePassword()
      assert.equal(b.passwordError.value, expected)
      assert.equal(passwordCalls.length, 1)
      assert.equal(b.passwordDialogVisible.value, true)
      assert.equal(b.passwordSaving.value, false)
      assert.deepEqual(successes, [])
      assert.deepEqual(navigations, [])
    } finally { dispose() }
  }
})

test('password submission prevents repeat requests and closing until completion, then clears secrets and redirects', async () => {
  let resolveRequest
  const request = new Promise((resolve) => { resolveRequest = resolve })
  const { b, passwordCalls, successes, navigations, dispose } = mountSettings({}, () => request)
  try {
    b.openPasswordDialog()
    b.passwordForm.value = { old_password: 'fixture-current', new_password: 'fixture-new', confirm_password: 'fixture-new' }
    const pending = b.changePassword()
    assert.equal(b.passwordSaving.value, true)
    b.closePasswordDialog()
    assert.equal(b.passwordDialogVisible.value, true)
    await b.changePassword()
    assert.equal(passwordCalls.length, 1)
    resolveRequest()
    await pending
    assert.equal(b.passwordSaving.value, false)
    assert.equal(b.passwordDialogVisible.value, false)
    assert.deepEqual(Object.values(b.passwordForm.value), ['', '', ''])
    assert.deepEqual(navigations, ['/login'])
    assert.deepEqual(successes, ['密码修改成功，所有设备已退出，请重新登录'])
  } finally { dispose() }
})
