import { randomUUID } from 'node:crypto';
import { Worker } from 'node:worker_threads';
import type { JsonObject, ParsedDocument } from '../contracts.js';
import { chunking, defaultChunking, object, projectedChunking } from '../knowledge/config.js';
import { splitDocument, type ChunkerOptions, type ChunkingResult } from './chunker.js';

export interface ChunkingWorkersOptions {
  concurrency?: number;
  maxQueued?: number;
  /** Explicit startup-inclusive execution deadline; omitted means no new deadline. */
  timeoutMs?: number;
  /** Trusted core-only construction option, never a renderer-controlled URL. */
  workerUrl?: URL;
}
export interface ChunkingWorkerCallOptions extends ChunkerOptions {
  onProgress?: (event: { stage: 'chunking'; progress: number }) => void;
}
export interface ChunkingWorkerRequest {
  protocol: 1;
  id: string;
  parsed: ParsedDocument;
  config: JsonObject;
  title: string;
}
export type ChunkingWorkerMessage =
  | { protocol: 1; id: string; type: 'started' }
  | { protocol: 1; id: string; type: 'result'; result: ChunkingResult }
  | { protocol: 1; id: string; type: 'error'; message: string };

export class ChunkingWorkerError extends Error {
  constructor(readonly code: string, message: string) { super(message); this.name = 'ChunkingWorkerError'; }
}
const failure = (code: string) => new ChunkingWorkerError(code, ({
  invalid_chunking_worker_config: '分块 Worker 配置无效。',
  chunking_busy: '分块任务队列已满，请稍后重试。',
  chunking_closed: '分块服务已关闭。',
  chunking_timeout: '分块计算超时。',
  chunking_worker_failed: '分块 Worker 执行失败。',
  chunking_protocol_invalid: '分块 Worker 返回格式无效。',
} as Record<string, string>)[code] ?? '分块计算失败。');

interface Task {
  request: ChunkingWorkerRequest;
  options: ChunkingWorkerCallOptions;
  resolve(value: ChunkingResult): void;
  reject(error: unknown): void;
  reaped: Promise<void>;
  markReaped(): void;
  abort(): void;
  worker?: Worker;
  exited?: Promise<void>;
  timer?: ReturnType<typeof setTimeout>;
  finishing: boolean;
  started: boolean;
  cancelReason?: unknown;
}
type Outcome = { result: ChunkingResult } | { error: unknown };
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const integer = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value);

/** Shape checks only: the unchanged chunker validates source content in its Worker. */
function resultShape(value: unknown): value is ChunkingResult {
  if (!record(value) || !Array.isArray(value.parents) || !Array.isArray(value.children) || !record(value.diagnostics)) return false;
  const parents = value.parents, children = value.children;
  const draft = (item: unknown): item is ChunkingResult['children'][number] =>
    record(item) && typeof item.content === 'string' && typeof item.context_header === 'string'
    && typeof item.chunk_type === 'string' && integer(item.start_at) && item.start_at >= 0
    && integer(item.end_at) && item.end_at >= item.start_at && record(item.metadata)
    && (item.context_parent_index === null || integer(item.context_parent_index) && item.context_parent_index >= 0);
  if (!parents.every(draft) || !children.every(draft)) return false;
  return parents.every(item => item.context_parent_index === null) && children.every(item => {
    if (item.context_parent_index === null) return true;
    const parent = parents[item.context_parent_index];
    return !!parent && parent.start_at <= item.start_at && item.end_at <= parent.end_at;
  });
}

/** Owns pure computation Workers only; all business writes remain in the caller. */
export class ChunkingWorkers {
  readonly #concurrency: number;
  readonly #maxQueued: number;
  readonly #timeoutMs?: number;
  readonly #workerUrl: URL;
  readonly #queue: Task[] = [];
  readonly #active = new Set<Task>();
  #closed = false;
  #closePromise?: Promise<void>;

  constructor(options: ChunkingWorkersOptions = {}) {
    this.#concurrency = options.concurrency ?? 1;
    this.#maxQueued = options.maxQueued ?? 16;
    this.#timeoutMs = options.timeoutMs;
    if (!Number.isSafeInteger(this.#concurrency) || this.#concurrency < 1 || this.#concurrency > 4
      || !Number.isSafeInteger(this.#maxQueued) || this.#maxQueued < 0
      || this.#timeoutMs !== undefined && (!Number.isSafeInteger(this.#timeoutMs) || this.#timeoutMs <= 0 || this.#timeoutMs > 2147483647)
      || options.workerUrl !== undefined && !(options.workerUrl instanceof URL)) throw failure('invalid_chunking_worker_config');
    const source = import.meta.url.endsWith('.ts');
    this.#workerUrl = options.workerUrl ?? new URL(source ? './chunking-worker.ts' : './chunking-worker.js', import.meta.url);
  }

  async split(parsed: ParsedDocument, rawConfig: unknown, options: ChunkingWorkerCallOptions): Promise<ChunkingResult> {
    if (this.#closed) throw failure('chunking_closed');
    options.signal?.throwIfAborted();
    const config = chunking({ ...projectedChunking({}).config, ...object(rawConfig) });
    if (config.strategy === 'semantic' || options.tokenCounter) return splitDocument(parsed, config, options);
    if (this.#active.size >= this.#concurrency && this.#queue.length >= this.#maxQueued) throw failure('chunking_busy');
    // Opaque stored configuration is unnecessary for computation and is not sent.
    const pureConfig = Object.fromEntries(Object.keys(defaultChunking).map(key => [key, config[key]!]));
    return new Promise<ChunkingResult>((resolve, reject) => {
      let markReaped!: () => void;
      const reaped = new Promise<void>(done => markReaped = done);
      const task: Task = {
        request: { protocol: 1, id: randomUUID(), parsed, config: pureConfig, title: options.title },
        options, resolve, reject, reaped, markReaped, finishing: false, started: false,
        abort: () => {
          if (task.cancelReason === undefined) task.cancelReason = options.signal?.reason;
          void this.#finish(task, { error: task.cancelReason });
        },
      };
      options.signal?.addEventListener('abort', task.abort, { once: true });
      this.#queue.push(task);
      this.#pump();
    });
  }

  #pump(): void {
    while (!this.#closed && this.#active.size < this.#concurrency && this.#queue.length) {
      const task = this.#queue.shift()!;
      if (task.options.signal?.aborted) { task.abort(); continue; }
      this.#start(task);
    }
  }

  #start(task: Task): void {
    this.#active.add(task);
    if (this.#timeoutMs !== undefined) task.timer = setTimeout(() => {
      if (task.cancelReason === undefined) task.cancelReason = failure('chunking_timeout');
      void this.#finish(task, { error: task.cancelReason });
    }, this.#timeoutMs);
    try {
      const worker = new Worker(this.#workerUrl, {
        workerData: task.request, env: {}, execArgv: [], name: 'marlin-chunking',
      });
      task.worker = worker;
      task.exited = new Promise<void>(exited => worker.once('exit', () => exited()));
      worker.on('message', (message: unknown) => {
        if (task.finishing) return;
        if (!record(message) || message.protocol !== 1 || message.id !== task.request.id) {
          void this.#finish(task, { error: failure('chunking_protocol_invalid') }); return;
        }
        if (message.type === 'started' && !task.started) {
          task.started = true;
          try { task.options.onProgress?.({ stage: 'chunking', progress: 0 }); }
          catch (error) { void this.#finish(task, { error }); }
        } else if (message.type === 'result' && resultShape(message.result)) {
          void this.#finish(task, { result: message.result });
        } else if (message.type === 'error' && typeof message.message === 'string') {
          void this.#finish(task, { error: new ChunkingWorkerError('chunking_failed', message.message) });
        } else void this.#finish(task, { error: failure('chunking_protocol_invalid') });
      });
      worker.once('error', () => { void this.#finish(task, { error: failure('chunking_worker_failed') }); });
      worker.once('exit', () => {
        if (!task.finishing) void this.#finish(task, { error: failure('chunking_worker_failed') });
      });
    } catch { void this.#finish(task, { error: failure('chunking_worker_failed') }); }
  }

  async #finish(task: Task, outcome: Outcome): Promise<void> {
    if (task.finishing) return;
    task.finishing = true;
    clearTimeout(task.timer);
    const queued = this.#queue.indexOf(task);
    if (queued !== -1) this.#queue.splice(queued, 1);
    if (task.worker) {
      try { await task.worker.terminate(); }
      catch { outcome = { error: failure('chunking_worker_failed') }; }
      // A failed termination request is never mistaken for an exited Worker.
      await task.exited;
      task.worker.removeAllListeners();
    }
    task.options.signal?.removeEventListener('abort', task.abort);
    this.#active.delete(task);
    task.markReaped();
    if (task.cancelReason !== undefined) task.reject(task.cancelReason);
    else if (task.options.signal?.aborted) task.reject(task.options.signal.reason);
    else if ('error' in outcome) task.reject(outcome.error);
    else task.resolve(outcome.result);
    this.#pump();
  }

  close(): Promise<void> {
    if (this.#closePromise) return this.#closePromise;
    this.#closed = true;
    const tasks = [...this.#active, ...this.#queue];
    this.#queue.length = 0;
    this.#closePromise = Promise.all(tasks.map(task => {
      if (task.cancelReason === undefined) task.cancelReason = failure('chunking_closed');
      void this.#finish(task, { error: task.cancelReason });
      return task.reaped;
    })).then(() => undefined);
    return this.#closePromise;
  }
}
