import { randomUUID } from 'node:crypto';
import { constants } from 'node:fs';
import { access, mkdir, rename, rm, stat, writeFile } from 'node:fs/promises';
import { request as httpRequest } from 'node:http';
import { request as httpsRequest } from 'node:https';
import { delimiter, isAbsolute, join } from 'node:path';
import { performance } from 'node:perf_hooks';
import { setTimeout as delay } from 'node:timers/promises';
import type BetterSqlite3 from 'better-sqlite3';
import { OwnedProcessRegistry } from '../jobs/owned-process.js';
import { openNativeDatabase } from '../storage/database.js';

export type LocalServicesStartupState = 'disabled' | 'external' | 'healthy' | 'missing_server_configuration'
  | 'docker_unavailable' | 'compose_failed' | 'startup_timeout' | 'startup_failed' | 'cancelled';
export interface LocalServicesStartupResult { state: LocalServicesStartupState; checked_at: number }
export interface LocalServicesSnapshot { autostart?: unknown; timeoutSeconds?: unknown; baseUrl?: unknown }
interface Executable { file: string; args: string[] }
/** Trusted constructor option for controlled real CLI fixtures; never an OwnerCall/HTTP field. */
export interface LocalServicesOptions { executable?: Executable }
const nonempty = (value: unknown): string => typeof value === 'string' && value.length ? value : '';
export function resolveLocalServicesConfiguration(saved: LocalServicesSnapshot, env: NodeJS.ProcessEnv) {
  const enabled = nonempty(env.LANGFUSE_AUTOSTART);
  const value = nonempty(env.LANGFUSE_STARTUP_TIMEOUT_SECONDS) || (saved.timeoutSeconds ?? 45);
  const numeric = typeof value === 'number' ? value : typeof value === 'string' && /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(value.trim()) ? Number(value) : NaN;
  return {
    autostart: enabled ? ['true', '1', 'yes', 'on'].includes(enabled.trim().toLowerCase()) : saved.autostart === true,
    timeoutSeconds: Number.isFinite(numeric) ? Math.min(120, Math.max(1, numeric)) : 45,
    baseUrl: (nonempty(env.LANGFUSE_BASE_URL) || nonempty(saved.baseUrl) || nonempty(env.LANGFUSE_HOST) || 'http://localhost:3000').replace(/\/+$/, ''),
  };
}
class StartupFailure extends Error { constructor(readonly state: LocalServicesStartupState) { super(state); } }
function code(error: unknown): string | undefined { return error && typeof error === 'object' && 'code' in error ? String(error.code) : undefined; }

/** Resolve only the fixed Docker executable. Access errors are not "not installed".
 * Pin an absolute executable for the supervisor; do not use a shell or PATHEXT scripts. */
async function dockerExecutable(env: NodeJS.ProcessEnv): Promise<Executable> {
  let inaccessible = false;
  for (const directory of (env.PATH ?? env.Path ?? '').split(delimiter).filter(Boolean)) {
    if (!isAbsolute(directory)) continue;
    const file = join(directory, process.platform === 'win32' ? 'docker.exe' : 'docker');
    try {
      if (!(await stat(file)).isFile()) { inaccessible = true; continue; }
      await access(file, constants.X_OK); return { file, args: [] };
    } catch (error) {
      if (!['ENOENT', 'ENOTDIR'].includes(code(error) ?? '')) inaccessible = true;
    }
  }
  throw new StartupFailure(inaccessible ? 'startup_failed' : 'docker_unavailable');
}

/** Direct native requests do not use system proxy settings or follow redirects.
 * A wall timer bounds DNS/connect/headers as well as idle sockets. */
function healthy(url: URL, timeoutMs: number, signal: AbortSignal): Promise<boolean> {
  return new Promise(resolve => {
    let settled = false;
    const finish = (value: boolean) => { if (settled) return; settled = true; clearTimeout(timer); signal.removeEventListener('abort', abort); request.destroy(); resolve(value); };
    const request = (url.protocol === 'https:' ? httpsRequest : httpRequest)(url, { method: 'GET', agent: false, signal }, response => {
      const value = response.statusCode === 200; response.destroy(); finish(value);
    });
    const abort = () => finish(false);
    const timer = setTimeout(() => finish(false), Math.max(1, timeoutMs));
    request.once('error', () => finish(false)); signal.addEventListener('abort', abort, { once: true });
    request.end(); if (signal.aborted) abort();
  });
}

export class LocalServicesStartupService {
  readonly #processes = new OwnedProcessRegistry();
  readonly #controllers = new Set<AbortController>();
  readonly #pending = new Set<Promise<LocalServicesStartupResult>>();
  #closed = false;
  #closePromise?: Promise<void>;
  constructor(readonly dataRoot: string, readonly snapshot: () => LocalServicesSnapshot, readonly options: LocalServicesOptions = {}) {}
  start(input: { sourceRoot: string; environ?: NodeJS.ProcessEnv; signal?: AbortSignal }): Promise<LocalServicesStartupResult> {
    const controller = new AbortController(); this.#controllers.add(controller);
    if (this.#closed) controller.abort();
    const pending = this.#start(input.sourceRoot, { ...(input.environ ?? process.env) }, input.signal ? AbortSignal.any([input.signal, controller.signal]) : controller.signal);
    this.#pending.add(pending);
    void pending.finally(() => { this.#controllers.delete(controller); this.#pending.delete(pending); }).catch(() => {});
    return pending;
  }
  async #start(sourceRoot: string, env: NodeJS.ProcessEnv, signal: AbortSignal): Promise<LocalServicesStartupResult> {
    const result = (state: LocalServicesStartupState): LocalServicesStartupResult => ({ state, checked_at: Date.now() / 1000 });
    let lock: BetterSqlite3.Database | undefined, directory: string | undefined;
    let state: LocalServicesStartupState;
    try {
      if (signal.aborted) return result('cancelled');
      const config = resolveLocalServicesConfiguration(this.snapshot(), env);
      if (!config.autostart) return result('disabled');
      const base = new URL(config.baseUrl);
      if (!['127.0.0.1', 'localhost', '[::1]', '::1'].includes(base.hostname)) return result('external');
      if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password || base.search || base.hash || !isAbsolute(sourceRoot)) throw new StartupFailure('startup_failed');
      const deadline = performance.now() + config.timeoutSeconds * 1000;
      const remaining = () => {
        if (signal.aborted) throw new StartupFailure('cancelled');
        const value = deadline - performance.now(); if (value <= 0) throw new StartupFailure('startup_timeout'); return value;
      };
      directory = join(this.dataRoot, '.cache', 'langfuse'); remaining();
      await mkdir(directory, { recursive: true, mode: 0o700 }); remaining();
      lock = openNativeDatabase(join(directory, 'startup-lock.sqlite3'), { timeout: 0 });
      for (;;) {
        remaining();
        try { lock.exec('BEGIN IMMEDIATE'); break; }
        catch (error) { if (!['SQLITE_BUSY', 'SQLITE_LOCKED'].includes(code(error) ?? '')) throw error; }
        await delay(Math.min(50, remaining()), undefined, { signal });
      }
      remaining();
      try {
        if (!(await stat(join(sourceRoot, '.env.langfuse'))).isFile()) throw new StartupFailure('missing_server_configuration');
        await access(join(sourceRoot, '.env.langfuse'), constants.R_OK);
      }
      catch (error) { if (code(error) === 'ENOENT') throw new StartupFailure('missing_server_configuration'); throw error; }
      remaining(); const executable = this.options.executable ?? await dockerExecutable(env); remaining();
      const prefix = ['compose', '--env-file', join(sourceRoot, '.env.langfuse'), '-f', join(sourceRoot, 'docker-compose.langfuse.yml')];
      for (const suffix of [['config', '--quiet'], ['up', '-d']]) {
        const timeoutMs = remaining();
        try { await this.#processes.spawn(executable.file, [...executable.args, ...prefix, ...suffix], signal, { cwd: sourceRoot, env, timeoutMs, discardOutput: true }).completion; }
        catch (error) {
          if (signal.aborted) throw new StartupFailure('cancelled');
          if (code(error) === 'child_timeout' || deadline - performance.now() <= 0) throw new StartupFailure('startup_timeout');
          throw new StartupFailure(['child_failed', 'child_output_limit'].includes(code(error) ?? '') ? 'compose_failed' : 'startup_failed');
        }
        remaining();
      }
      const url = new URL(config.baseUrl + '/api/public/health');
      for (;;) {
        const timeoutMs = Math.min(2000, remaining());
        if (await healthy(url, timeoutMs, signal)) { remaining(); break; }
        await delay(Math.min(500, remaining()), undefined, { signal });
      }
      state = 'healthy';
    } catch (error) { state = signal.aborted ? 'cancelled' : error instanceof StartupFailure ? error.state : 'startup_failed'; }
    const checked = result(state);
    try {
      // Match the old diagnostic behavior, including a timed-out lock waiter.
      if (directory) {
        const temporary = join(directory, `startup-${randomUUID()}.tmp`);
        try { await writeFile(temporary, JSON.stringify(checked) + '\n', { mode: 0o600, flag: 'wx' }); await rename(temporary, join(directory, 'startup.json')); }
        finally { await rm(temporary, { force: true }); }
      }
    } catch { checked.state = 'startup_failed'; }
    finally { try { if (lock?.inTransaction) lock.exec('ROLLBACK'); } finally { lock?.close(); } }
    return checked;
  }
  close(): Promise<void> {
    if (this.#closePromise) return this.#closePromise;
    this.#closed = true; for (const controller of this.#controllers) controller.abort();
    return this.#closePromise = (async () => { await Promise.allSettled([...this.#pending]); await this.#processes.close(); })();
  }
}
