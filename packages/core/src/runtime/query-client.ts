import { randomUUID } from 'node:crypto';
import { Worker } from 'node:worker_threads';
import type { CoreRequest, CoreResponse } from '../contracts.js';
import { AppError } from '../errors.js';
import type { QueryBinding, QueryBootstrap, QueryInput, QueryOutput } from './query-contracts.js';
import type { CancelTarget } from './document-cancel-preflight.js';

const failed = (code = 'query_failed', status = 503) => new AppError(status, code,
  code === 'query_busy' ? '页面读取请求过多，请稍后重试。' : code === 'query_timeout' ? '页面读取超时，请重试。' : '页面读取服务暂时不可用，请重试。');
interface PendingQuery {
  id: string; request: CoreRequest; binding: QueryBinding; epoch: string; deadline: number;
  resolve(response: CoreResponse): void; reject(error: unknown): void;
  timer: NodeJS.Timeout; signal?: AbortSignal; abort(): void;
  control: boolean; authorized?: (target?: CancelTarget) => void;
}
/** One executing query and at most 32 waiting queries; deadlines start at admission. */
export class QueryClient {
  #worker?: Worker;
  #active?: PendingQuery;
  readonly #queue: PendingQuery[] = [];
  readonly #controls: PendingQuery[] = [];
  #ready = false;
  #closed = false;
  #restarted = false;
  #restart?: Promise<void>;
  #closePromise?: Promise<void>;
  readonly #terminations = new Set<Promise<number>>();
  private constructor(readonly bootstrap: QueryBootstrap, readonly authority: SharedArrayBuffer, readonly ownerAlive: () => boolean) {}
  static async start(bootstrap: QueryBootstrap, authority: SharedArrayBuffer, ownerAlive: () => boolean): Promise<QueryClient> {
    const client = new QueryClient(bootstrap, authority, ownerAlive);
    try { await client.spawn(); return client; }
    catch (error) { await client.close(); throw error; }
  }
  /** Trusted Node fixture attachment; renderer contracts never expose Workers. */
  static async connect(worker: Worker, bootstrap: QueryBootstrap, authority: SharedArrayBuffer, ownerAlive: () => boolean): Promise<QueryClient> {
    const client = new QueryClient(bootstrap, authority, ownerAlive);
    try { await client.attach(worker); return client; }
    catch (error) { await client.close(); throw error; }
  }
  get pendingCount(): number { return this.#queue.length + this.#controls.length + Number(!!this.#active); }
  private spawn(): Promise<void> {
    const worker = new Worker(new URL(import.meta.url.endsWith('.ts') ? './query-worker.ts' : './query-worker.js', import.meta.url), {
      workerData: { bootstrap: this.bootstrap, authority: this.authority }, execArgv: [], name: 'marlin-core-query', stdout: true, stderr: true,
    });
    return this.attach(worker);
  }
  private attach(worker: Worker): Promise<void> {
    this.#worker = worker; worker.stdout.resume(); worker.stderr.resume();
    return new Promise((resolve, reject) => {
      let settled = false;
      const timer = setTimeout(() => { reject(failed('query_start_timeout')); this.fault(worker); }, 30000);
      const fault = () => {
        if (!settled) { settled = true; clearTimeout(timer); reject(failed()); }
        this.fault(worker);
      };
      worker.on('error', fault); worker.on('messageerror', fault);
      worker.on('exit', () => { if (!this.#closed && this.#worker === worker) fault(); });
      worker.on('message', (message: QueryOutput) => {
        if (this.#worker !== worker || this.#closed) return;
        if (!message || message.protocol !== 1) { fault(); return; }
        if (message.type === 'ready') {
          if (settled || message.generation !== this.bootstrap.generation) { fault(); return; }
          settled = true; clearTimeout(timer); this.#ready = true; resolve(); return;
        }
        if (message.type === 'startup-error') { fault(); return; }
        if (message.type === 'closed') return;
        if (!this.#ready || message.type !== 'result' || !this.#active || message.id !== this.#active.id || message.generation !== this.bootstrap.generation || message.epoch !== this.#active.epoch) { fault(); return; }
        const query = this.#active; this.#active = undefined; this.release(query);
        if (!this.ownerAlive()) query.reject(failed('owner_failed'));
        else if (query.epoch !== Atomics.load(new BigUint64Array(this.authority), 0).toString()) query.reject(new AppError(409, 'auth_superseded', '登录状态已改变，请重新操作。'));
        else {
          try {
            if (Date.now() >= query.deadline) throw failed('query_timeout', 408);
            if (query.signal?.aborted) throw query.signal.reason;
            // The coordinator validates and CASes the shared attempt here,
            // before resolving or yielding to another authority intent.
            if (query.control && message.response.status === 200) query.authorized?.(message.target);
            query.resolve(message.response);
          } catch (error) { query.reject(error); }
        }
        this.pump();
      });
    });
  }
  private release(query: PendingQuery): void { clearTimeout(query.timer); query.signal?.removeEventListener('abort', query.abort); }
  private fault(worker: Worker, error = failed()): void {
    if (this.#worker !== worker || this.#closed) return;
    this.#worker = undefined; this.#ready = false;
    for (const query of [...this.#queue.splice(0), ...this.#controls.splice(0), ...(this.#active ? [this.#active] : [])]) { this.release(query); query.reject(error); }
    this.#active = undefined;
    const terminated = worker.terminate().catch(() => -1);
    this.#terminations.add(terminated);
    void terminated.finally(() => this.#terminations.delete(terminated));
    if (!this.#restarted && this.ownerAlive()) {
      this.#restarted = true;
      this.#restart = terminated.then(async () => { if (!this.#closed && this.ownerAlive()) await this.spawn(); }).catch(() => {});
    }
  }
  private pump(): void {
    if (this.#closed || !this.#ready || !this.#worker || this.#active || !this.#queue.length && !this.#controls.length) return;
    const query = (this.#controls.length ? this.#controls : this.#queue).shift()!; this.#active = query;
    const message: QueryInput = { protocol: 1, type: 'query', id: query.id, generation: this.bootstrap.generation, epoch: query.epoch, deadline: query.deadline, request: query.request, binding: query.binding, ...(query.control ? { operation: 'cancel-preflight' as const } : {}) };
    try { this.#worker.postMessage(message); }
    catch { this.fault(this.#worker, failed('query_input_uncloneable', 400)); }
  }
  dispatch(request: CoreRequest, binding: QueryBinding, epoch: string, signal?: AbortSignal): Promise<CoreResponse> {
    return this.enqueue(request, binding, epoch, signal);
  }
  cancelPreflight(request: CoreRequest, binding: QueryBinding, epoch: string, authorized: (target?: CancelTarget) => void, signal?: AbortSignal): Promise<CoreResponse> {
    return this.enqueue(request, binding, epoch, signal, authorized);
  }
  private enqueue(request: CoreRequest, binding: QueryBinding, epoch: string, signal?: AbortSignal, authorized?: (target?: CancelTarget) => void): Promise<CoreResponse> {
    if (signal?.aborted) return Promise.reject(signal.reason);
    if (this.#closed || !this.#ready || !this.ownerAlive()) return Promise.reject(failed());
    const control = !!authorized, queue = control ? this.#controls : this.#queue;
    if (control ? queue.length + Number(!!this.#active?.control) >= 8 : queue.length >= 32) return Promise.reject(failed('query_busy', 429));
    return new Promise((resolve, reject) => {
      const query: PendingQuery = { id: randomUUID(), request, binding, epoch, deadline: Date.now() + 15000, resolve, reject, signal, control, authorized,
        timer: setTimeout(() => {
          if (this.#active === query && this.#worker) this.fault(this.#worker, failed('query_timeout', 408));
          else { const index = queue.indexOf(query); if (index !== -1) queue.splice(index, 1); this.release(query); reject(failed('query_timeout', 408)); }
        }, 15000),
        abort: () => {
          reject(signal?.reason);
          const index = queue.indexOf(query);
          if (index !== -1) { queue.splice(index, 1); this.release(query); }
          // A synchronous SQLite query cannot consume an abort message. Keep its
          // slot/deadline until terminal response, and discard its late Promise result.
        },
      };
      queue.push(query); signal?.addEventListener('abort', query.abort, { once: true }); this.pump();
    });
  }
  close(): Promise<void> { return this.#closePromise ??= this.closeWorker(); }
  private async closeWorker(): Promise<void> {
    this.#closed = true; this.#ready = false;
    for (const query of [...this.#queue.splice(0), ...this.#controls.splice(0), ...(this.#active ? [this.#active] : [])]) { this.release(query); query.reject(failed('query_closed')); }
    this.#active = undefined;
    const worker = this.#worker; this.#worker = undefined;
    if (worker) {
      const exited = new Promise<void>(resolve => { if (worker.threadId === -1) resolve(); else worker.once('exit', () => resolve()); });
      const timer = setTimeout(() => { void worker.terminate(); }, 2500);
      try { worker.postMessage({ protocol: 1, type: 'close' } satisfies QueryInput); await exited; }
      finally { clearTimeout(timer); }
    }
    await this.#restart;
    await Promise.allSettled([...this.#terminations]);
  }
}
