'use strict';
const assert = require('node:assert/strict');
const { test, before, after } = require('node:test');
const { readFileSync } = require('node:fs');
const { createRequire } = require('node:module');
const path = require('node:path');
const vm = require('node:vm');
const { chromium } = createRequire(path.join(__dirname, '../frontend/package.json'))('@playwright/test');

// Execute the production renderer template and JSON expression, never a copy of
// the readiness predicate. HTML fixtures represent async route stages only.
const main = readFileSync(path.join(__dirname, 'main.cjs'), 'utf8');
const template = main.match(/executeJavaScript\((`[\s\S]*?`)\)/);
assert.ok(template, 'the real smoke renderer template must be present');
const probe = vm.runInNewContext(template[1]);
const projection = main.match(/JSON\.stringify\((\{ ok: result\.mounted[\s\S]*?\})\)/);
assert.ok(projection, 'the real smoke result serialization must be present');
const report = new Function('result', 'handshake', 'startupMs', 'performance', 'started', `return (${projection[1]});`);
const toReport = result => report(result, { runtime: 'typescript' }, 70, { now: () => 70 }, 0);
const login = '<main class="login-page"><section class="login-form-area"><div class="login-panel"><h2>登录知识工作台</h2><input autocomplete="email"><input type="password"><button>登录</button></div></section></main>';
const shell = '<div id="app"><div class="app-frame"><aside class="pwa-status"><button>安装说明</button></aside></div></div>';
let browser;
before(async () => { browser = await chromium.launch({ headless: true }); });
after(async () => { await browser?.close(); });

async function fixture(route, content, run) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 860 } });
  try {
    await page.clock.install({ time: new Date('2026-01-01T00:00:00Z') });
    await page.route('**/*', request => request.fulfill({ contentType: 'text/html', body: '<!doctype html><title>Marlin fixture</title><style>main { padding:24px; min-height:240px; } input,button { margin:8px; padding:8px; }</style>' + content }));
    await page.goto('https://marlin.local' + route);
    await page.clock.pauseAt(new Date('2026-01-01T00:00:01Z'));
    await page.evaluate(() => { window.marlinDesktop = { protocol: 1, transport: 'ipc' }; });
    await run(page);
  } finally { await page.close(); }
}

async function start(page) {
  await page.evaluate(source => {
    window.smokeResolved = false;
    window.smokePromise = (0, eval)(source).then(result => { window.smokeResult = result; window.smokeResolved = true; });
  }, probe);
}
const resolved = page => page.evaluate(() => window.smokeResolved);
const result = page => page.evaluate(() => window.smokeResult);

test('mounted app/PWA shell waits for the delayed visible login route', async () => {
  await fixture('/', shell, async page => {
    await start(page);
    assert.equal(await resolved(page), false, 'async auth/router shell must not complete smoke');
    await page.clock.runFor(400);
    assert.equal(await resolved(page), false);
    await page.evaluate(html => setTimeout(() => {
      history.replaceState({}, '', '/login'); document.querySelector('.app-frame').insertAdjacentHTML('beforeend', html);
    }, 250), login);
    await page.clock.runFor(300);
    const state = await result(page);
    assert.equal(state.mounted, true); assert.equal(state.pageReady, true); assert.equal(state.pageReadyKind, 'login');
    assert.ok(state.page_ready_ms >= 650); assert.ok(state.mounted_ms <= state.page_ready_ms);
    assert.equal(toReport(state).ok, true);
  });
});

test('already visible usable login controls preserve preload and Node isolation checks', async () => {
  await fixture('/login', '<div id="app">' + login + '</div>', async page => {
    await start(page);
    const state = await result(page);
    assert.equal(state.pageReady, true); assert.equal(state.pageReadyKind, 'login');
    assert.equal(state.nodeExposed, false); assert.equal(state.nativeProtocol, 1); assert.equal(state.nativeTransport, 'ipc');
    assert.equal(toReport(state).ok, true);
    for (const patch of [{ nodeExposed: true }, { nativeProtocol: 2 }, { nativeTransport: 'http' }]) {
      assert.equal(toReport({ ...state, ...patch }).ok, false, 'actual host result must retain its boundary checks');
    }
  });
});

test('authenticated shell and sidebar wait for a usable control inside the routed main', async () => {
  const content = '<div id="app"><div class="shell"><aside><button>知识库</button></aside><section class="workspace"></section></div></div>';
  await fixture('/platform/knowledge-bases', content, async page => {
    await start(page);
    assert.equal(await resolved(page), false, 'sidebar actions do not establish routed page readiness');
    await page.evaluate(() => { document.querySelector('.workspace').innerHTML = '<main class="content kb-page"><h2>知识库</h2><button disabled>新建知识库</button></main>'; });
    await page.clock.runFor(100);
    assert.equal(await resolved(page), false, 'disabled business controls must not complete smoke');
    await page.evaluate(() => { document.querySelector('main button').disabled = false; });
    await page.clock.runFor(20);
    const state = await result(page);
    assert.equal(state.pageReady, true); assert.equal(state.pageReadyKind, 'workbench'); assert.equal(toReport(state).ok, true);
  });
});

test('hidden, inert and readonly login inputs must become usable before completion', async () => {
  await fixture('/login', '<div id="app"><div style="opacity:0" inert>' + login + '</div></div>', async page => {
    await start(page);
    assert.equal(await resolved(page), false);
    await page.evaluate(() => { const wrapper = document.querySelector('#app > div'); wrapper.removeAttribute('inert'); wrapper.style.opacity = '1'; document.querySelector('input').readOnly = true; });
    await page.clock.runFor(100);
    assert.equal(await resolved(page), false);
    await page.evaluate(() => { document.querySelector('input').readOnly = false; });
    await page.clock.runFor(20);
    assert.equal((await result(page)).pageReady, true);
  });
});

test('permanent mounted shell reaches the real 15-second deadline with pageReady/ok false', async () => {
  await fixture('/', shell, async page => {
    await start(page);
    assert.equal(await resolved(page), false);
    await page.clock.runFor(14999);
    assert.equal(await resolved(page), false);
    await page.clock.runFor(1);
    const state = await result(page);
    assert.equal(state.mounted, true); assert.equal(state.pageReady, false); assert.equal(state.pageReadyKind, null);
    assert.equal(state.page_ready_ms, null); assert.ok(state.renderer_wait_ms >= 15000);
    assert.equal(toReport(state).ok, false, 'timeout must remain an explicit failed smoke result');
  });
});

test('login affordances on an unrelated route are not a ready application page', async () => {
  await fixture('/unexpected', '<div id="app">' + login + '</div>', async page => {
    await start(page);
    assert.equal(await resolved(page), false);
    await page.clock.runFor(15000);
    assert.equal((await result(page)).pageReady, false);
  });
});
