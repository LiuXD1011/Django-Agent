'use strict';
const path = require('node:path');
const { performance } = require('node:perf_hooks');

function loadWindowsJob(root, modulePath = path.join(root, 'owned-runtime', 'runtime-job.node')) {
  return require(modulePath);
}

function finishDesktopQuit(closeWindows, stopRuntime, reportFailure, quit) {
  return Promise.resolve().then(closeWindows).finally(stopRuntime).catch(error => {
    try { reportFailure(error); } catch { /* OS still closes the retained Job when main exits. */ }
  }).then(quit);
}

// One lifetime retains one ChildProcess and one opaque Job. No PID lookup occurs
// after the bootstrap's creation identity has been bound by the native adapter.
class RuntimeLifetime {
  constructor(child, generation) {
    Object.assign(this, { child, generation, job: null, authorized: false, closed: false, stopPromise: null });
    this.rootExited = child.exitCode !== null || child.signalCode !== null;
    this.exited = new Promise(resolve => {
      this.resolveExit = resolve;
      if (this.rootExited) resolve();
      else child.once('exit', () => { this.rootExited = true; resolve(); });
    });
    child.once('error', () => {
      if (!child.pid) { this.rootExited = true; this.resolveExit(); }
    });
  }
  stop(sendShutdown) {
    if (this.stopPromise) return this.stopPromise;
    let timer;
    this.stopPromise = (async () => {
      if (!this.rootExited) {
        const gracefulDeadline = new Promise(resolve => { timer = setTimeout(resolve, 30000); });
        const signalOriginal = () => {
          // IPC callbacks can arrive after sendShutdown returns. Signal failure
          // cannot escape the callback; the retained deadline and Job escalation
          // must still establish a real terminal state or reject stop.
          if (!this.rootExited) { try { this.child.kill('SIGTERM'); } catch { /* Keep the bounded owned cleanup below. */ } }
        };
        try { sendShutdown(error => { if (error) signalOriginal(); }); }
        catch { signalOriginal(); }
        await Promise.race([this.exited, gracefulDeadline]);
        clearTimeout(timer);
      }
      const status = () => {
        if (!this.job) return { rootExited: this.rootExited, activeProcesses: this.rootExited ? 0 : 1 };
        const value = this.job.status();
        if (!value || typeof value.rootExited !== 'boolean' || !Number.isSafeInteger(value.activeProcesses) || value.activeProcesses < 0) {
          throw new Error('无法确认应用自有进程的退出状态。');
        }
        return value;
      };
      const first = status();
      if (!first.rootExited || first.activeProcesses !== 0) {
        if (this.job) this.job.terminate();
        else if (!this.rootExited) this.child.kill('SIGKILL');
      }
      const deadline = performance.now() + 5000;
      while (true) {
        const current = status();
        if (this.rootExited && current.rootExited && current.activeProcesses === 0) break;
        if (performance.now() >= deadline) throw new Error('应用自有进程清理超时，无法确认完整退出。');
        await new Promise(resolve => { timer = setTimeout(resolve, 10); });
      }
      this.job?.close();
      this.closed = true;
    })().finally(() => clearTimeout(timer));
    return this.stopPromise;
  }
}

module.exports = { RuntimeLifetime, loadWindowsJob, finishDesktopQuit };
