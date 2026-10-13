'use strict';
const { randomUUID } = require('node:crypto');
const sessionCookieName = /^(?:__Secure-)?next-auth\.session-token(?:\.\d+)?$/;

function validatePublicRequest(input) {
  if (!input || Object.getPrototypeOf(input) !== Object.prototype || Object.keys(input).some(key => !['id', 'action', 'traceUrl', 'tenantId'].includes(key)) || typeof input.id !== 'string' || !input.id || input.id.length > 200 || /[\x00-\x1f\x7f]/.test(input.id) || !['session', 'open', 'clear'].includes(input.action)) throw new Error('Langfuse 桌面请求不正确。');
  if (input.tenantId !== undefined && (typeof input.tenantId !== 'string' || !input.tenantId || input.tenantId.length > 128)) throw new Error('空间标识不正确。');
  if (input.traceUrl !== undefined && (input.action !== 'open' || typeof input.traceUrl !== 'string' || input.traceUrl.length > 8192 || /[\x00-\x20\x7f\\]/.test(input.traceUrl))) throw new Error('Langfuse 追踪地址不正确。');
}
function allowedNavigation(value, plan) {
  if (typeof value !== 'string' || /[\x00-\x20\x7f\\]/.test(value)) return false;
  let url; try { url = new URL(value); } catch { return false; }
  if (url.origin !== plan.origin || url.username || url.password) return false;
  if (url.pathname.startsWith(plan.projectPath)) {
    let tail = url.pathname.slice(plan.projectPath.length);
    for (let round = 0; round < 4; round++) {
      if (/[\\\x00-\x1f\x7f]/.test(tail) || tail.split('/').some(part => part === '.' || part === '..')) return false;
      let decoded; try { decoded = decodeURIComponent(tail); } catch { return false; }
      if (decoded === tail) return true;
      tail = decoded;
    }
    return false;
  }
  if (plan.mode !== 'manual' || !['/auth/sign-in', '/auth/sign-up', '/auth/reset-password', '/auth/error', '/api/auth/signin', '/api/auth/signout', '/api/auth/error', '/api/auth/callback/credentials'].includes(url.pathname)) return false;
  for (const key of ['callbackUrl', 'redirect', 'returnTo']) {
    const targets = url.searchParams.getAll(key);
    if (targets.some(target => !allowedNavigation(target, { ...plan, mode: 'automatic' }))) return false;
  }
  return true;
}
function invalidatesLangfuse(request) {
  if (!request || ['GET', 'HEAD'].includes(request.method)) return false;
  const pathname = String(request.path).split('?')[0];
  return /^\/api\/v1\/auth\/(?:login|register|auto-setup|logout|logout-all|change-password)$/.test(pathname) || /^\/api\/v1\/(?:system\/config\/(?:langfuse|local_services)|integrations\/langfuse\/credentials)(?:\/|$)/.test(pathname);
}
function loadWindow(target, destination, signal) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = error => { if (settled) return; settled = true; clearTimeout(timer); signal.removeEventListener('abort', abort); error ? reject(error) : resolve(); };
    const abort = () => { if (!target.isDestroyed()) target.webContents.stop(); finish(new Error('Langfuse 页面打开已取消。')); };
    const timer = setTimeout(() => { if (!target.isDestroyed()) target.webContents.stop(); finish(new Error('Langfuse 页面打开超时，请检查服务后重试。')); }, 30000);
    signal.addEventListener('abort', abort, { once: true });
    if (signal.aborted) { abort(); return; }
    Promise.resolve(target.loadURL(destination)).then(() => finish(), finish);
  });
}

/** All Electron sessions/windows below are owned by this fixed capability. */
class LangfuseWindows {
  constructor(electron, runtime) {
    Object.assign(this, { electron, runtime, current: null, epoch: 0, closed: false, queue: Promise.resolve(), active: new Set(), cleanup: new Set() });
  }
  publicResponse(id, data) { return { protocol: 1, id, status: 200, body: { success: true, data } }; }
  check(epoch, signal) { if (this.closed || epoch !== this.epoch || signal?.aborted) throw new Error('Langfuse 登录已取消或状态已改变。'); }
  async command(action, extra = {}, signal) {
    const result = await this.runtime.langfuse({ id: randomUUID(), action, ...extra }, signal);
    if (result.response.status >= 400) { const error = new Error(result.response.body.message || result.response.body.error?.message || 'Langfuse 登录失败。'); error.response = result.response; throw error; }
    return result;
  }
  serial(work) {
    const pending = this.queue.then(work); this.queue = pending.catch(() => {}); return pending;
  }
  async disposeCurrent() {
    const current = this.current; this.current = null;
    if (!current) return;
    clearInterval(current.timer);
    if (current.window && !current.window.isDestroyed()) current.window.destroy();
    current.session.webRequest.onBeforeRequest(null);
    current.session.removeListener('will-download', current.preventDownload);
    const work = (async () => { await current.session.closeAllConnections(); await current.session.clearStorageData(); await current.session.clearCache(); })();
    this.cleanup.add(work); try { await work; } finally { this.cleanup.delete(work); }
  }
  invalidate() {
    this.epoch++; for (const controller of this.active) controller.abort();
    return this.disposeCurrent();
  }
  async close() { this.closed = true; await this.invalidate(); await this.queue; await Promise.allSettled([...this.cleanup]); }
  async handle(input, signal) {
    validatePublicRequest(input);
    if (input.action === 'clear') {
      await this.invalidate();
      const result = await this.command('clear', input.tenantId ? { tenantId: input.tenantId } : {}, signal);
      return result.response;
    }
    const epoch = this.epoch, controller = new AbortController(); this.active.add(controller);
    const combined = signal ? AbortSignal.any([signal, controller.signal]) : controller.signal;
    try { return await this.serial(() => this.execute(input, epoch, combined)); }
    finally { this.active.delete(controller); }
  }
  async execute(input, epoch, signal) {
    try {
      this.check(epoch, signal);
      const tenant = input.tenantId ? { tenantId: input.tenantId } : {};
      const prepared = await this.command('prepare', tenant, signal), plan = prepared.plan;
      this.check(epoch, signal);
      if (!plan) throw new Error('Langfuse 登录计划缺失。');
      let current = this.current;
      if (current && (current.plan.ownerScope !== plan.ownerScope || current.plan.origin !== plan.origin || current.plan.projectPath !== plan.projectPath)) { await this.disposeCurrent(); current = null; }
      this.check(epoch, signal);
      if (!current) {
        const owned = this.electron.session.fromPartition(`marlin-langfuse-${randomUUID()}`, { cache: false });
        owned.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
        owned.setPermissionCheckHandler(() => false);
        const preventDownload = event => event.preventDefault(); owned.on('will-download', preventDownload);
        current = { session: owned, plan, tenant, preventDownload, window: null, timer: null }; this.current = current;
        owned.webRequest.onBeforeRequest((details, callback) => {
          let url; try { url = new URL(details.url); } catch { callback({ cancel: true }); return; }
          const top = ['mainFrame', 'subFrame'].includes(details.resourceType);
          const project = /\/project\//.test(url.pathname);
          const allowed = url.origin === current.plan.origin && !url.username && !url.password && (!top && !project || allowedNavigation(details.url, current.plan));
          callback({ cancel: !allowed });
        });
      }
      current.plan = plan; current.tenant = tenant;
      const existing = await current.session.cookies.get({ url: plan.origin }); this.check(epoch, signal);
      const existingCookies = Object.fromEntries(existing.filter(cookie => sessionCookieName.test(cookie.name)).map(cookie => [cookie.name, cookie.value]));
      const result = await this.command('session', { ...tenant, ticket: plan.ticket, existingCookies }, signal); this.check(epoch, signal);
      const cookies = result.cookies || [];
      if (plan.mode === 'automatic') {
        for (const cookie of existing) if (sessionCookieName.test(cookie.name)) { await current.session.cookies.remove(plan.origin, cookie.name); this.check(epoch, signal); }
        for (const cookie of cookies) {
          await current.session.cookies.set({ url: plan.origin, name: cookie.name, value: cookie.value, path: '/', secure: cookie.secure, httpOnly: true, sameSite: 'lax', expirationDate: Date.now() / 1000 + cookie.maxAge });
          this.check(epoch, signal);
        }
      }
      await this.command('validate', { ...tenant, ticket: plan.ticket }, signal); this.check(epoch, signal);
      if (!current.timer) {
        current.timer = setInterval(() => {
          void this.serial(async () => {
            if (this.current !== current || this.closed) return;
            try { await this.command('validate', { ...current.tenant, ticket: current.plan.ticket }); }
            catch { if (this.current === current) await this.invalidate(); }
          }).catch(() => {});
        }, 2000); current.timer.unref?.();
      }
      if (input.action === 'open') {
        const destination = input.traceUrl && allowedNavigation(input.traceUrl, { ...plan, mode: 'automatic' }) ? input.traceUrl : plan.open_url;
        if (!current.window || current.window.isDestroyed()) {
          const target = new this.electron.BrowserWindow({ title: 'Langfuse', width: 1200, height: 820, show: false, autoHideMenuBar: true,
            webPreferences: { session: current.session, nodeIntegration: false, contextIsolation: true, sandbox: true, webSecurity: true, allowRunningInsecureContent: false, webviewTag: false, devTools: false } });
          current.window = target; target.setMenu(null);
          target.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
          target.webContents.on('will-frame-navigate', event => { if (!allowedNavigation(event.url, current.plan)) event.preventDefault(); });
          target.webContents.on('will-redirect', event => { if (!allowedNavigation(event.url, current.plan)) event.preventDefault(); });
          target.webContents.on('will-attach-webview', event => event.preventDefault());
          target.webContents.on('did-navigate-in-page', (_event, url) => { if (!allowedNavigation(url, current.plan)) void this.invalidate(); });
          target.once('closed', () => { if (current.window === target) current.window = null; });
        }
        await loadWindow(current.window, destination, signal); this.check(epoch, signal);
        await this.command('validate', { ...tenant, ticket: plan.ticket }, signal); this.check(epoch, signal);
        current.window.show(); current.window.focus();
      }
      return this.publicResponse(input.id, result.response.body.data);
    } catch (error) { await this.disposeCurrent(); if (error.response) return { ...error.response, id: input.id }; throw error; }
  }
}
module.exports = { LangfuseWindows, allowedNavigation, validatePublicRequest, invalidatesLangfuse };
