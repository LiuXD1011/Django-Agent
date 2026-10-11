'use strict';
const { contextBridge, ipcRenderer } = require('electron');
const listeners = new Map();
ipcRenderer.on('marlin:stream-event', (_event, item) => {
  if (!item || typeof item.id !== 'string') return;
  const listener = listeners.get(item.id); if (!listener) return;
  listener(item);
  if (item.type === 'end' || item.type === 'error') listeners.delete(item.id);
});
if (process.isMainFrame) contextBridge.exposeInMainWorld('marlinDesktop', {
  protocol: 1, transport: 'ipc',
  invoke: (request, options = {}) => ipcRenderer.invoke('marlin:invoke', request, options),
  langfuse: request => ipcRenderer.invoke('marlin:langfuse', request),
  openStream: (request, options = {}) => ipcRenderer.invoke('marlin:stream-open', request, options),
  subscribeStream: (id, listener) => {
    if (typeof id !== 'string' || !id || id.length > 200 || typeof listener !== 'function' || listeners.has(id) || listeners.size >= 64) throw new Error('流订阅标识或数量不正确。');
    listeners.set(id, listener); return () => { if (listeners.get(id) === listener) listeners.delete(id); };
  },
  acknowledgeStream: (id, sequence) => { if (typeof id === 'string' && Number.isSafeInteger(sequence)) ipcRenderer.send('marlin:stream-ack', id, sequence); },
  cancel: id => { if (typeof id === 'string') { listeners.delete(id); ipcRenderer.send('marlin:cancel', id); } },
});
