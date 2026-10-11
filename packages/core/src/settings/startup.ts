import { appendFileSync, closeSync, existsSync, fsyncSync, mkdirSync, openSync, readFileSync, renameSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { randomUUID } from 'node:crypto';
import { join } from 'node:path';
import type { JsonObject } from '../contracts.js';
import type { CoreDatabase } from '../storage/database.js';
import { endpoint, fail, object } from './internal.js';

const defaults: JsonObject = { debug: false, allowed_hosts: ['localhost', '127.0.0.1', '[::1]'], cors_origins: ['http://localhost:5173'], task_workers: 4, sqlite_timeout: 30, model_timeout: 60, model_retries: 2, log_level: 'INFO', no_proxy: 'localhost,127.0.0.1,::1', proxy_url: '' };
const nativeFields = ['task_workers', 'sqlite_timeout', 'model_timeout', 'log_level'];
const levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'];
const envFields: Record<string, string[]> = { task_workers: ['MARLIN_TASK_WORKERS', 'APP_TASK_WORKERS'], sqlite_timeout: ['MARLIN_SQLITE_TIMEOUT', 'SQLITE_TIMEOUT'], model_timeout: ['MARLIN_MODEL_TIMEOUT', 'LLM_CHAT_MODEL_TIMEOUT'], log_level: ['MARLIN_LOG_LEVEL', 'DJANGO_LOG_LEVEL'] };
function validate(value: JsonObject): JsonObject {
  object(value);
  if (Object.keys(value).some(key => !Object.hasOwn(defaults, key))) fail(400, 'invalid_startup', 'Unknown startup configuration field');
  const result = { ...structuredClone(defaults), ...value };
  for (const [key, current] of Object.entries(result)) {
    const expected = defaults[key];
    if (typeof current !== typeof expected || Array.isArray(current) !== Array.isArray(expected)) fail(400, 'invalid_startup', 'Invalid startup configuration type');
  }
  for (const [key, low, high] of [['task_workers', 2, 32], ['sqlite_timeout', 1, 300], ['model_timeout', 1, 600], ['model_retries', 0, 10]] as const) {
    const n = result[key]; if (typeof n !== 'number' || !Number.isInteger(n) || n < low || n > high) fail(400, 'invalid_startup', 'Startup numeric configuration is outside the supported range');
  }
  if (!levels.includes(String(result.log_level))) fail(400, 'invalid_startup', 'Invalid log level');
  for (const key of ['allowed_hosts', 'cors_origins']) if (!(result[key] as unknown[]).every(item => typeof item === 'string' && item.trim() && item.length <= 4096)) fail(400, 'invalid_startup', 'Startup list fields require nonempty strings');
  if (!(result.allowed_hosts as string[]).length || (result.allowed_hosts as string[]).includes('*')) fail(400, 'invalid_startup', 'Explicit legacy allowed hosts are required');
  for (const url of [...result.cors_origins as string[], ...(result.proxy_url ? [String(result.proxy_url)] : [])]) { endpoint(url); if (!['', '/'].includes(new URL(url).pathname)) fail(400, 'invalid_startup', 'Origin and proxy configuration must not contain a path'); }
  if (String(result.no_proxy).length > 4096 || String(result.proxy_url).length > 4096) fail(400, 'invalid_startup', 'Startup configuration is too large');
  return result;
}
export function readStartupConfiguration(dataRoot: string): JsonObject {
  const path = join(dataRoot, '.settings', 'startup.json');
  if (!existsSync(path)) return validate({});
  if (!statSync(path).isFile() || statSync(path).size > 65536) fail(400, 'invalid_startup', 'Startup configuration file is invalid or too large');
  let parsed: unknown;
  try { parsed = JSON.parse(readFileSync(path, 'utf8')); } catch { return fail(400, 'invalid_startup', 'Startup configuration file contains invalid JSON'); }
  return validate(object(parsed));
}

/** Pure TypeScript startup snapshot. File reads do not depend on a business database. */
export class StartupConfiguration {
  readonly path: string;
  readonly environmentOverrides: string[] = [];
  readonly #active: JsonObject;
  #running = 0;
  readonly #pending: Array<() => void> = [];
  constructor(readonly dataRoot: string, options: { environ?: NodeJS.ProcessEnv } = {}) {
    this.path = join(dataRoot, '.settings', 'startup.json');
    const values = readStartupConfiguration(dataRoot), env = options.environ ?? process.env;
    for (const [field, names] of Object.entries(envFields)) {
      const name = names.find(name => env[name] !== undefined); if (!name) continue;
      values[field] = typeof defaults[field] === 'number' ? Number(env[name]) : env[name]!;
      this.environmentOverrides.push(name);
    }
    const checked = validate(values);
    this.#active = Object.fromEntries(nativeFields.map(key => [key, checked[key]!]));
  }
  get active(): JsonObject { return structuredClone(this.#active); }
  projection(databasePath?: string): JsonObject {
    const saved = readStartupConfiguration(this.dataRoot);
    const fieldSupport = Object.fromEntries(Object.keys(defaults).map(key => [key, { applied: nativeFields.includes(key), reason: nativeFields.includes(key) ? 'Applied by the native core at startup' : key === 'model_retries' ? 'Retained legacy field; uncertain paid requests are never replayed automatically' : 'Retained legacy field; not applied by the native core or used as HTTP security policy' }]));
    return { values: saved, active: this.active, restart_required: nativeFields.some(key => saved[key] !== this.#active[key]), path: this.path, data_root: this.dataRoot,
      database_path: databasePath ?? '', environment_overrides: [...this.environmentOverrides], field_support: fieldSupport };
  }
  update(changes: JsonObject, databasePath?: string): JsonObject {
    object(changes);
    if (Object.keys(changes).some(key => !Object.hasOwn(defaults, key))) fail(400, 'invalid_startup', 'Unknown startup configuration field');
    const directory = join(this.dataRoot, '.settings'); mkdirSync(directory, { recursive: true, mode: 0o700 });
    const temporary = join(directory, `startup-${randomUUID()}.tmp`);
    try {
      // The single owning core executes this complete read/merge/rename synchronously.
      // No persistent lock marker survives a crash or conflicts with legacy Python locks.
      const values = validate({ ...readStartupConfiguration(this.dataRoot), ...changes });
      const fd = openSync(temporary, 'wx', 0o600);
      try { writeFileSync(fd, JSON.stringify(values, null, 2) + '\n', 'utf8'); fsyncSync(fd); } finally { closeSync(fd); }
      renameSync(temporary, this.path); return this.projection(databasePath);
    } finally { rmSync(temporary, { force: true }); }
  }
  applyDatabase(db: CoreDatabase): void { db.sqlite.pragma(`busy_timeout=${Number(this.#active.sqlite_timeout) * 1000}`); }
  runTask<T>(work: () => T | Promise<T>): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      this.#pending.push(() => {
        this.#running++;
        const release = () => { this.#running--; this.drain(); };
        Promise.resolve().then(work).then(value => { release(); resolve(value); }, error => { release(); reject(error); });
      });
      this.drain();
    });
  }
  private drain(): void { while (this.#running < Number(this.#active.task_workers) && this.#pending.length) this.#pending.shift()!(); }
  /** Fixed event identifiers only: no exception messages, SQL, prompts, credentials or arbitrary payloads. */
  log(level: string, safeEvent: string): void {
    if (!levels.includes(level) || !/^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,5}$/.test(safeEvent) || safeEvent.length > 100) fail(400, 'invalid_log_event', 'Diagnostics require a fixed event identifier');
    if (levels.indexOf(level) < levels.indexOf(String(this.#active.log_level))) return;
    const directory = join(this.dataRoot, '.logs'); mkdirSync(directory, { recursive: true, mode: 0o700 });
    const path = join(directory, 'core.jsonl');
    if (existsSync(path) && statSync(path).size > 5 * 1024 * 1024) { const previous = join(directory, 'core.previous.jsonl'); rmSync(previous, { force: true }); renameSync(path, previous); }
    appendFileSync(path, JSON.stringify({ time: new Date().toISOString(), level, event: safeEvent }) + '\n', { mode: 0o600 });
  }
}
