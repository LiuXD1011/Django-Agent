'use strict';
const { app, BrowserWindow, dialog, shell, session, ipcMain, Tray, Menu, nativeImage, net } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const { Runtime, isLocal, isExternal } = require('./runtime.cjs');
const { installIpc } = require('./ipc.cjs');
const { createProtocolHandler } = require('./protocol.cjs');
const { LangfuseWindows } = require('./langfuse.cjs');

let window, runtime, tray, ipc, langfuse;
let quitting = false, ready = false;
const allowed = new Set(), origin = 'https://marlin.local';
const webPreferences = { nodeIntegration: false, contextIsolation: true, sandbox: true,
  webSecurity: true, allowRunningInsecureContent: false, webviewTag: false, preload: path.join(__dirname, 'preload.cjs') };
function protectWindow(target, origin) {
  allowed.add(target.webContents);
  target.webContents.once('destroyed', () => { ipc?.detach(target.webContents); allowed.delete(target.webContents); });
  target.webContents.on('did-start-navigation', (_event, _url, isInPlace, isMainFrame) => { if (isMainFrame && !isInPlace) ipc?.detach(target.webContents); });
  target.setMenu(null);
  target.webContents.setWindowOpenHandler(({ url }) => {
    if (isLocal(url, origin)) return { action: 'allow', overrideBrowserWindowOptions: { webPreferences } };
    if (isExternal(url)) shell.openExternal(url).catch(() => {});
    return { action: 'deny' };
  });
  const navigate = (event, url) => {
    if (!isLocal(url, origin)) {
      event.preventDefault();
      if (isExternal(url)) shell.openExternal(url).catch(() => {});
    }
  };
  target.webContents.on('will-navigate', navigate);
  target.webContents.on('will-redirect', navigate);
  target.webContents.on('will-attach-webview', (event) => event.preventDefault());
  target.webContents.on('did-create-window', (child) => protectWindow(child, origin));
}
const smoke = process.argv.includes('--smoke-test');
const dataIndex = process.argv.indexOf('--data-dir');
const dataDir = dataIndex >= 0 && process.argv[dataIndex + 1]
  ? path.resolve(process.argv[dataIndex + 1]) : path.join(process.env.LOCALAPPDATA || app.getPath('appData'), 'Marlin');
// Backend data is separate from installation files and Chromium's profile.
fs.mkdirSync(path.join(dataDir, 'desktop-profile'), { recursive: true });
app.setPath('userData', path.join(dataDir, 'desktop-profile'));

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (window) { window.show(); if (window.isMinimized()) window.restore(); window.focus(); }
  });
  app.on('window-all-closed', () => app.quit());
  app.on('before-quit', (event) => {
    if (quitting) return;
    event.preventDefault();
    quitting = true;
    ipc?.close(); tray?.destroy();
    Promise.resolve(langfuse?.close()).finally(() => runtime?.stop()).finally(() => app.quit());
  });
  app.whenReady().then(async () => {
    fs.mkdirSync(dataDir, { recursive: true });
    const canWriteClipboard = (contents, permission) => permission === 'clipboard-sanitized-write'
      && !!contents && isLocal(contents.getURL(), origin);
    session.defaultSession.setPermissionRequestHandler((contents, permission, callback) => callback(canWriteClipboard(contents, permission)));
    session.defaultSession.setPermissionCheckHandler((contents, permission) => canWriteClipboard(contents, permission));
    window = new BrowserWindow({
      title: 'Marlin · 个人知识库', width: 1280, height: 860,
      minWidth: 800, minHeight: 600, show: !smoke, autoHideMenuBar: true,
      webPreferences,
    });
    protectWindow(window, origin);
    window.on('close', (event) => {
      if (!quitting) { event.preventDefault(); if (ready && tray) window.hide(); else app.quit(); }
    });
    await window.loadFile(path.join(__dirname, 'loading.html'));
    if (quitting) return;
    const fail = async (message) => {
      if (quitting) return;
      if (smoke) {
        fs.writeFileSync(path.join(dataDir, 'smoke-result.json'), JSON.stringify({ ok: false, message }));
      } else {
        await dialog.showMessageBox(window, { type: 'error', title: 'Marlin 启动失败',
          message, detail: `用户数据保留在：${dataDir}` });
      }
      app.quit();
    };
    const root = app.isPackaged ? path.join(process.resourcesPath, 'runtime') : path.join(__dirname, 'payload');
    runtime = new Runtime(root, dataDir, fail);
    langfuse = new LangfuseWindows({ BrowserWindow, session }, runtime);
    ipc = installIpc(ipcMain, runtime, allowed, origin, langfuse);
    session.defaultSession.protocol.handle('https', createProtocolHandler(path.join(root, 'frontend'), runtime, origin,
      request => net.fetch(request, { bypassCustomProtocolHandlers: true })));
    try {
      const started = performance.now(), handshake = await runtime.start();
      if (quitting || window.isDestroyed()) return;
      await window.loadURL(origin);
      ready = true;
      const iconPath = fs.existsSync(path.join(__dirname, 'icon.png')) ? path.join(__dirname, 'icon.png') : path.join(root, 'frontend/icons/icon-512.png');
      const icon = nativeImage.createFromPath(iconPath).resize({ width: 20, height: 20 });
      if (!icon.isEmpty()) {
        tray = new Tray(icon); tray.setToolTip('Marlin · 个人知识库');
        const show = () => { window.show(); if (window.isMinimized()) window.restore(); window.focus(); };
        tray.setContextMenu(Menu.buildFromTemplate([{ label: '打开 Marlin', click: show }, { type: 'separator' }, { label: '退出', click: () => app.quit() }]));
        tray.on('double-click', show);
      }
      if (smoke) {
        const result = await window.webContents.executeJavaScript(`new Promise(resolve => {
          const state = () => ({title: document.title, mounted: !!document.querySelector('#app')?.children.length, url: location.href, nodeExposed: typeof process !== 'undefined' || typeof require !== 'undefined', nativeProtocol: window.marlinDesktop?.protocol, nativeTransport: window.marlinDesktop?.transport});
          let observer, deadline;
          const check = () => { const result = state(); if (result.mounted) { observer?.disconnect(); clearTimeout(deadline); resolve(result); return true; } return false; };
          if (check()) return;
          observer = new MutationObserver(check); observer.observe(document.documentElement, {childList: true, subtree: true});
          deadline = setTimeout(() => { observer.disconnect(); resolve(state()); }, 15000);
          check();
        })`);
        const screenshot = await window.webContents.capturePage();
        fs.writeFileSync(path.join(dataDir, 'smoke-window.png'), screenshot.toPNG());
        fs.writeFileSync(path.join(dataDir, 'smoke-result.json'), JSON.stringify({ ok: result.mounted && !result.nodeExposed && result.nativeProtocol === 1 && result.nativeTransport === 'ipc', ...result, core: handshake, startup_ms: performance.now() - started }));
        app.quit();
      }
    } catch (error) { await fail(error.message); }
  }).catch((error) => { if (!quitting) dialog.showErrorBox('Marlin', error.message); app.quit(); });
}
