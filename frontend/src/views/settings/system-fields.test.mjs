import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { createRequire } from 'node:module'
import vm from 'node:vm'
import { transformSync } from 'esbuild'
import { parse, compileScript, compileTemplate } from '@vue/compiler-sfc'
import { configPayload, configSections } from './system-fields.ts'

const require = createRequire(import.meta.url)
const vue = require('vue')
const { renderToString } = require('@vue/server-renderer')
const { descriptor } = parse(readFileSync(new URL('./SystemConfiguration.vue', import.meta.url), 'utf8'))
const compiledScript = compileScript(descriptor, { id: 'system-state-behavior' })
const componentScript = transformSync(compiledScript.content, { loader: 'ts', format: 'cjs', target: 'es2022' }).code
const template = compileTemplate({ source: descriptor.template.content, filename: 'SystemConfiguration.vue', id: 'system-state-behavior', compilerOptions: { bindingMetadata: compiledScript.bindings } })
assert.deepEqual(template.errors, [])
const templateScript = transformSync(template.code, { format: 'cjs', target: 'es2022' }).code

function mountConfiguration(section, data) {
  const scope = vue.effectScope()
  const calls = []
  const context = vm.createContext({ module: { exports: {} }, console, require: name => {
    if (name === 'vue') return { ...vue, onMounted: () => {} }
    if (name === '../../api/client') return { get: async () => ({ data }), put: async (path, body) => { calls.push({ path, body }); return { data } } }
    if (name === './system-fields') return { configPayload, configSections }
    throw new Error(`Unexpected import ${name}`)
  } })
  vm.runInContext(componentScript, context)
  const component = context.module.exports.default
  const b = scope.run(() => component.setup({ section }, { expose: () => {}, emit: () => {} }))
  const renderContext = vm.createContext({ module: { exports: {} }, require })
  vm.runInContext(templateScript, renderContext)
  return { b, calls, dispose: () => scope.stop(), render: () => {
    const app = vue.createSSRApp({ ...component, setup: () => b, render: renderContext.module.exports.render }, { section })
    for (const name of ['t-space', 't-button', 't-dialog']) app.component(name, { setup: (_, { slots }) => () => vue.h('div', slots.default?.()) })
    return renderToString(app)
  } }
}

const startupFixture = { values: { task_workers: 4, model_retries: 2 }, active: { task_workers: 4 }, restart_required: false,
  field_support: { task_workers: { applied: true, reason: 'Applied by the native core at startup' },
    model_retries: { applied: false, reason: 'Retained legacy field; uncertain paid requests are never replayed automatically' } } }

test('startup form renders actual applied and retained field reasons without removing editable legacy controls', async () => {
  const { b, render, dispose } = mountConfiguration('startup', startupFixture)
  try {
    await b.load()
    const html = await render()
    assert.match(html, /Applied by the native core at startup/)
    assert.match(html, /Retained legacy field; uncertain paid requests are never replayed automatically/)
    assert.match(html, /当前运行时未提供支持状态/)
    assert.match(html, /模型请求重试次数/)
    assert.match(html, /type="number"[^>]*value="2"/)
  } finally { dispose() }
})

test('startup save does not claim retained fields became active when the actual active snapshot is unchanged', async () => {
  for (const restart of [false, true]) {
    const { b, calls, dispose } = mountConfiguration('startup', { ...startupFixture, restart_required: restart })
    try {
      await b.load(); b.form.value.model_retries = 3; await b.save()
      assert.equal(calls.length, 1)
      assert.equal(calls[0].body.model_retries, 3)
      assert.match(b.message.value, /保留字段不参与当前运行/)
      assert.match(b.message.value, restart ? /将在重启后生效/ : /当前生效值未改变/)
      assert.doesNotMatch(b.message.value, /已保存并生效/)
    } finally { dispose() }
  }
})

async function connectionMessage(response) {
  const scope = vue.effectScope()
  const context = vm.createContext({ module: { exports: {} }, console, require: name => {
    if (name === 'vue') return { ...vue, onMounted: () => {} }
    if (name === '../../api/client') return { post: async () => { if (response instanceof Error) throw response; return { data: response } } }
    if (name === './system-fields') return { configPayload, configSections }
    throw new Error(`Unexpected import ${name}`)
  } })
  vm.runInContext(componentScript, context)
  const bindings = scope.run(() => context.module.exports.default.setup({ section: 'neo4j' }, { expose: () => {}, emit: () => {} }))
  try { await bindings.testConnection(); assert.equal(bindings.busy.value, false); return bindings.message.value }
  finally { scope.stop() }
}

test('saved integration test only reports success for the actual connected state', async () => {
  assert.equal(await connectionMessage({ state: 'connected' }), '已保存配置的连接测试通过')
  assert.equal(await connectionMessage({ state: 'disabled' }), '服务已停用，请先启用并保存配置')
  assert.equal(await connectionMessage({ state: 'not_configured' }), '连接配置不完整，请先保存地址和凭据')
  assert.equal(await connectionMessage({ state: 'unknown' }), '服务尚未就绪，连接测试未通过')
  assert.equal(await connectionMessage({}), '服务尚未就绪，连接测试未通过')
})

test('saved integration connection errors retain the existing safe failure message', async () => {
  assert.equal(await connectionMessage(new Error('连接测试失败，请检查已保存的地址、凭据与服务状态')), '连接测试失败，请检查已保存的地址、凭据与服务状态')
})

test('blank secret edits are omitted and populated secrets only occur in the outgoing request', () => {
  const fields = configSections.neo4j.fields
  assert.deepEqual(configPayload(fields, { enabled: true, uri: 'bolt://localhost:7687', username: 'neo4j', password: '' }),
    { enabled: true, uri: 'bolt://localhost:7687', username: 'neo4j' })
  assert.equal(configPayload(fields, { password: 'fixture-secret' }).password, 'fixture-secret')
})
test('startup list controls produce trimmed JSON arrays without empty entries', () => {
  const payload = configPayload(configSections.startup.fields, { allowed_hosts: 'localhost, 127.0.0.1, ',
    cors_origins: 'http://localhost:5173', task_workers: 6 })
  assert.deepEqual(payload.allowed_hosts, ['localhost', '127.0.0.1'])
  assert.deepEqual(payload.cors_origins, ['http://localhost:5173'])
  assert.equal(payload.task_workers, 6)
})
test('secrets only belong to the database forms, never startup configuration', () => {
  assert.equal(configSections.startup.fields.some(field => field.kind === 'secret'), false)
  assert.equal(configSections.local_services.fields.find(field => field.key === 'password').kind, 'secret')
})
test('configuration editor does not cache credentials in browser storage and blocks unloaded saves', () => {
  const component = readFileSync(new URL('./SystemConfiguration.vue', import.meta.url), 'utf8')
  assert.doesNotMatch(component, /localStorage|sessionStorage/)
  assert.match(component, /if \(!status.value \|\| busy.value\) return/)
  assert.match(component, /field.kind === 'secret' \? ''/)
  assert.match(component, /重启/)
  assert.match(component, /Cache-Control|配置已保存/)
})
