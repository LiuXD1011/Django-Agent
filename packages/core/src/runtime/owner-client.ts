import { randomUUID } from 'node:crypto';
import { isAbsolute } from 'node:path';
import { Worker } from 'node:worker_threads';
import { CoreBinary, CoreStream, errorResponse, validateCoreRequest, type CoreFrame, type PrivateBinding, type PrivateDispatch } from '../application.js';
import type { CoreRequest, CoreResponse } from '../contracts.js';
import type { IpcOptions, IpcResponse, IpcStream, NativeLangfuseResponse } from '../adapters/ipc.js';
import { AppError } from '../errors.js';
import { isAuthorityChange } from '../routing.js';
import { QueryClient } from './query-client.js';
import { isQueryRequest } from './query-dispatcher.js';
import type { QueryBinding } from './query-contracts.js';
import { AttemptRegistry } from './attempt-registry.js';
import { isDocumentCancelRequest, type CancelTarget } from './document-cancel-preflight.js';
import type { CoreHttpTransport, CoreOwnerConfig, OwnerBootstrap, OwnerCall, OwnerFailure, OwnerInput, OwnerOutput, OwnerSessionState, OwnerValue } from './owner-contracts.js';

const failure = (code: string, status = 503) => new AppError(status, code, ({
  owner_closed: '核心服务已关闭。', owner_failed: '核心服务已退出，请重新启动应用。',
  owner_start_failed: '核心服务无法启动，请检查应用诊断。', owner_start_timeout: '核心服务启动超时。',
  owner_busy: '核心请求过多，请稍后重试。', owner_protocol_invalid: '核心连接返回格式不正确。',
  invalid_owner_config: '核心运行配置不正确。', owner_input_uncloneable: '核心请求不能通过私有连接传输。',
} as Record<string, string>)[code] ?? '核心连接失败。');
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && Object.getPrototypeOf(value) === Object.prototype;
function serializable(value: unknown, parents = new Set<object>()): boolean {
  if (value === undefined || value === null || typeof value === 'string' || typeof value === 'boolean') return true;
  if (typeof value === 'number') return Number.isFinite(value);
  if (!value || typeof value !== 'object' || parents.has(value) || !Array.isArray(value) && !object(value)) return false;
  parents.add(value); const valid = Object.values(value).every(item => serializable(item, parents)); parents.delete(value); return valid;
}
function validateConfig(config: CoreOwnerConfig): void {
  if (!object(config) || !serializable(config) || Object.keys(config).some(key => !['dataRoot', 'allowAutoSetup', 'parser', 'evaluation'].includes(key))
    || typeof config.dataRoot !== 'string' || !isAbsolute(config.dataRoot) || config.allowAutoSetup !== undefined && typeof config.allowAutoSetup !== 'boolean') throw failure('invalid_owner_config', 400);
  if (config.parser !== undefined && (!object(config.parser) || Object.keys(config.parser).some(key => !['pythonExecutable', 'workerPath', 'timeoutMs', 'maxInputBytes', 'maxOutputBytes', 'maxArtifactBytes', 'maxRequestBytes'].includes(key)))) throw failure('invalid_owner_config', 400);
  if (config.evaluation !== undefined && (!object(config.evaluation) || Object.keys(config.evaluation).some(key => !['ragas', 'publicCacheRoot', 'publicDatasetSpecs', 'publicOrigin', 'legacyCacheRoot'].includes(key))
    || config.evaluation.ragas !== undefined && (!object(config.evaluation.ragas) || Object.keys(config.evaluation.ragas).some(key => !['pythonExecutable', 'workerPath'].includes(key))))) throw failure('invalid_owner_config', 400);
}
function remoteError(error: OwnerFailure): AppError { return new AppError(error.status, error.code, error.message); }

/** One reader, one outstanding frame; ACK means the consumer asked to advance. */
class RemoteFrames implements AsyncIterableIterator<CoreFrame> {
  #buffer?: { sequence: number; frame: CoreFrame };
  #consumed?: number;
  #sequence = 0;
  #done = false;
  #failed = false;
  #error: unknown;
  #waiting?: { resolve(result: IteratorResult<CoreFrame>): void; reject(error: unknown): void };
  constructor(readonly acknowledge: (sequence: number) => void, readonly cancel: () => void) {}
  [Symbol.asyncIterator](): AsyncIterableIterator<CoreFrame> { return this; }
  next(): Promise<IteratorResult<CoreFrame>> {
    if (this.#failed) return Promise.reject(this.#error);
    if (this.#done) return Promise.resolve({ done: true, value: undefined });
    if (this.#waiting) return Promise.reject(new AppError(409, 'owner_stream_busy', '流数据只能由一个读取操作消费。'));
    if (this.#consumed !== undefined) { this.acknowledge(this.#consumed); this.#consumed = undefined; }
    if (this.#buffer) { const item = this.#buffer; this.#buffer = undefined; this.#consumed = item.sequence; return Promise.resolve({ done: false, value: item.frame }); }
    return new Promise((resolve, reject) => { this.#waiting = { resolve, reject }; });
  }
  push(sequence: number, frame: CoreFrame): void {
    if (this.#done || this.#failed) return;
    if (sequence !== this.#sequence++ || this.#buffer || this.#consumed !== undefined) throw failure('owner_protocol_invalid');
    if (this.#waiting) { const waiting = this.#waiting; this.#waiting = undefined; this.#consumed = sequence; waiting.resolve({ done: false, value: frame }); }
    else this.#buffer = { sequence, frame };
  }
  finish(): void { this.#done = true; this.#waiting?.resolve({ done: true, value: undefined }); this.#waiting = undefined; }
  fail(error: unknown): void { this.#failed = true; this.#error = error; this.#buffer = undefined; this.#waiting?.reject(error); this.#waiting = undefined; }
  async return(): Promise<IteratorResult<CoreFrame>> { this.#buffer = undefined; this.finish(); this.cancel(); return { done: true, value: undefined }; }
  async throw(error: unknown): Promise<IteratorResult<CoreFrame>> { this.fail(error); this.cancel(); throw error; }
}
interface Pending {
  epoch: string;
  operation: OwnerCall['operation'];
  changesAuthority: boolean;
  requestId: string;
  cancelled?: boolean;
  resolve(result: { value: OwnerValue; frames?: RemoteFrames }): void;
  reject(error: unknown): void;
  signal?: AbortSignal;
  abort(): void;
  frames?: RemoteFrames;
}

/** Trusted transport proxy. Only its owned Worker constructs a business database. */
export class CoreOwner {
  #serviceId = '';
  #closed = false;
  #failure?: AppError;
  #closePromise?: Promise<void>;
  #httpPromise?: Promise<CoreHttpTransport>;
  #bootstrap?: OwnerBootstrap;
  #session?: OwnerSessionState;
  #query?: QueryClient;
  readonly #authority: BigUint64Array;
  readonly #authorityTickets = new Set<string>();
  readonly #pending = new Map<string, Pending>();
  readonly #attempts = new AttemptRegistry();
  readonly #cancellations = new Map<string, { requestId: string; settled: Promise<void>; settle(): void; resolve(response: CoreResponse): void; reject(error: unknown): void; release(): void; signal?: AbortSignal; abort(): void }>();
  readonly #exited: Promise<number>;
  readonly #ready: Promise<void>;
  #closedReply?: { error?: OwnerFailure };
  #resolveReady!: () => void;
  #rejectReady!: (error: unknown) => void;
  private constructor(readonly worker: Worker, readonly generation: string, authority: SharedArrayBuffer) {
    this.#authority = new BigUint64Array(authority);
    this.#ready = new Promise((resolve, reject) => { this.#resolveReady = resolve; this.#rejectReady = reject; });
    this.#exited = new Promise(resolve => worker.once('exit', code => {
      resolve(code);
      if (!this.#closedReply) this.#fault(failure('owner_failed'));
    }));
    worker.on('message', (message: OwnerOutput) => this.#receive(message));
    worker.on('messageerror', () => this.#fault(failure('owner_protocol_invalid')));
    worker.on('error', () => this.#fault(failure('owner_failed')));
    // Private helper failures must never echo native paths, credentials or payloads.
    worker.stdout.resume(); worker.stderr.resume();
  }
  static async start(config: CoreOwnerConfig): Promise<CoreOwner> {
    validateConfig(config);
    const workerUrl = new URL(import.meta.url.endsWith('.ts') ? './owner-worker.ts' : './owner-worker.js', import.meta.url);
    const authority = new SharedArrayBuffer(8), generation = randomUUID();
    let worker: Worker;
    try { worker = new Worker(workerUrl, { workerData: { config, authority, generation }, execArgv: [], name: 'marlin-core-owner', stdout: true, stderr: true }); }
    catch { throw failure('owner_start_failed'); }
    return this.connect(worker, { authority, generation });
  }
  /** Trusted Node-only attachment, also used by real-worker integration fixtures. */
  static async connect(worker: Worker, binding: { authority: SharedArrayBuffer; generation: string }): Promise<CoreOwner> {
    if (!(binding.authority instanceof SharedArrayBuffer) || binding.authority.byteLength !== 8 || typeof binding.generation !== 'string' || !binding.generation) throw failure('invalid_owner_config', 400);
    const owner = new CoreOwner(worker, binding.generation, binding.authority);
    const timer = setTimeout(() => owner.#fault(failure('owner_start_timeout')), 30000);
    try {
      await owner.#ready;
      const bootstrap = owner.#bootstrap!;
      owner.#query = await QueryClient.start({ databasePath: bootstrap.databasePath, dataRoot: bootstrap.dataRoot, generation: bootstrap.generation, parserEnabled: bootstrap.parserEnabled }, binding.authority, () => !owner.#closed);
      if (owner.#closed) { await owner.#query.close(); throw owner.#failure ?? failure('owner_closed'); }
      return owner;
    }
    catch (error) { await owner.worker.terminate(); await owner.#exited; throw error; }
    finally { clearTimeout(timer); }
  }
  get serviceId(): string { return this.#serviceId; }
  #send(message: OwnerInput): void { this.worker.postMessage(message); }
  #release(id: string): void {
    const pending = this.#pending.get(id);
    pending?.signal?.removeEventListener('abort', pending.abort); this.#pending.delete(id);
  }
  #fault(error: AppError): void {
    if (this.#failure) return;
    this.#failure = error; this.#closed = true; this.#rejectReady(error);
    this.#attempts.close();
    for (const pending of this.#cancellations.values()) { pending.signal?.removeEventListener('abort', pending.abort); pending.release(); pending.reject(error); pending.settle(); }
    this.#cancellations.clear();
    this.#authorityTickets.clear(); this.#session = undefined;
    void this.#query?.close().catch(() => {});
    for (const [id, pending] of this.#pending) { pending.reject(error); pending.frames?.fail(error); this.#release(id); }
    if (this.worker.threadId !== -1) void this.worker.terminate().catch(() => {});
  }
  #cleanupFailed(error: unknown): void {
    // Normal shutdown has already closed query admission; its owner flushes
    // outstanding receipts while SQLite is still open.
    if (!this.#closed) this.#fault(failure('owner_failed'));
  }
  #receive(message: OwnerOutput): void {
    if (!message || message.protocol !== 1 || typeof message.type !== 'string') { this.#fault(failure('owner_protocol_invalid')); return; }
    if (message.type === 'attempt-register') {
      let error: OwnerFailure | undefined;
      try {
        if (message.generation !== this.generation || this.#closed) throw this.#failure ?? failure('owner_closed');
        this.#attempts.register(message.identity, message.shared);
      } catch (reason) {
        const response = errorResponse('', reason), body = response.body as { error: { code: string; message: string } };
        error = { status: response.status, ...body.error };
      }
      this.#send({ protocol: 1, type: 'attempt-registration-result', id: message.id, generation: this.generation, ...(error ? { error } : {}) }); return;
    }
    if (message.type === 'attempt-unregister') { if (message.generation === this.generation) this.#attempts.unregister(message.identity); return; }
    if (message.type === 'cancel-response') {
      const pending = this.#cancellations.get(message.id);
      if (pending) { this.#cancellations.delete(message.id); pending.signal?.removeEventListener('abort', pending.abort); pending.release(); pending.resolve(message.response); pending.settle(); }
      return;
    }
    if (message.type === 'ready') {
      if (this.#serviceId || typeof message.serviceId !== 'string' || !message.serviceId || !message.bootstrap || message.bootstrap.generation !== this.generation) { this.#fault(failure('owner_protocol_invalid')); return; }
      this.#serviceId = message.serviceId; this.#bootstrap = message.bootstrap; this.#session = message.bootstrap.session; this.#resolveReady(); return;
    }
    if (message.type === 'startup-error') { this.#fault(remoteError(message.error)); return; }
    if (message.type === 'closed') { this.#closedReply = message; return; }
    if (this.#closed) return;
    // A caller abort ends its Promise, but a mutation stays pending until owner ACK.
    if (message.type === 'response' || message.type === 'error') {
      if (!message.session || typeof message.session.epoch !== 'string' || message.session.access !== undefined && typeof message.session.access !== 'string') { this.#fault(failure('owner_protocol_invalid')); return; }
      this.#authorityTickets.delete(message.id);
      if (message.session.epoch === Atomics.load(this.#authority, 0).toString()) this.#session = message.session;
    }
    const pending = this.#pending.get(message.id);
    const change = message.type === 'response' && message.value && typeof message.value === 'object' && 'authChange' in message.value ? message.value.authChange : undefined;
    const stale = !!pending && (pending.changesAuthority || !!change) && pending.epoch !== Atomics.load(this.#authority, 0).toString();
    if (message.type === 'response' && message.ipcCommit) {
      const accept = !!pending && !pending.cancelled && !stale;
      const settled = this.#call({ operation: 'settle-ipc', commit: message.ipcCommit, accept });
      if (pending) {
        if (accept) {
          // Acceptance linearizes in this coordinator message turn: enqueue
          // receipt confirmation and resolve together, before any later intent.
          pending.resolve({ value: message.value }); this.#release(message.id);
          void settled.catch(error => this.#cleanupFailed(error));
          return;
        }
        const value = errorResponse(pending.requestId, new AppError(409, 'auth_superseded', '登录状态已改变，请重新操作。'));
        void settled.then(() => { pending.resolve({ value }); this.#release(message.id); }, error => { this.#cleanupFailed(error); pending.reject(error); this.#release(message.id); });
      } else void settled.catch(error => this.#cleanupFailed(error));
      return;
    }
    if (change?.issue && (!pending || pending.cancelled || stale)) {
      // Owner's save check and delivery are separate operations. A later intent
      // can arrive between them; never expose its older cookies to the adapter.
      const cleanup = this.#call({ operation: 'discard-issue', issue: change.issue });
      if (pending) {
        const response = errorResponse(pending.requestId, new AppError(409, 'auth_superseded', '登录状态已改变，请重新操作。'));
        void cleanup.then(() => { pending.resolve({ value: pending.operation === 'dispatch' ? { response } : response }); this.#release(message.id); }, error => { this.#cleanupFailed(error); pending.reject(error); this.#release(message.id); });
      } else void cleanup.catch(error => this.#cleanupFailed(error));
      return;
    }
    if (!pending) return;
    try {
      if (message.type === 'response') {
        if (pending.cancelled) { if (!message.streaming) this.#release(message.id); return; }
        if (stale) {
          const response = errorResponse(pending.requestId, new AppError(409, 'auth_superseded', '登录状态已改变，请重新操作。'));
          pending.resolve({ value: pending.operation === 'dispatch' ? { response } : response }); this.#release(message.id); return;
        }
        if (message.streaming) pending.frames = new RemoteFrames(sequence => this.#send({ protocol: 1, type: 'ack', id: message.id, sequence }), () => {
          pending.cancelled = true;
          this.#send({ protocol: 1, type: 'abort', id: message.id });
          pending.signal?.removeEventListener('abort', pending.abort);
        });
        pending.resolve({ value: message.value, ...(pending.frames ? { frames: pending.frames } : {}) });
        if (!message.streaming) this.#release(message.id);
      } else if (message.type === 'frame') {
        if (pending.cancelled) return;
        if (!pending.frames) throw failure('owner_protocol_invalid');
        pending.frames.push(message.sequence, message.frame);
      } else if (message.type === 'end') { pending.frames?.finish(); this.#release(message.id); }
      else if (message.type === 'error') { const error = remoteError(message.error); pending.reject(error); pending.frames?.fail(error); this.#release(message.id); }
      else throw failure('owner_protocol_invalid');
    } catch { this.#fault(failure('owner_protocol_invalid')); }
  }
  #call(call: OwnerCall, signal?: AbortSignal): Promise<{ value: OwnerValue; frames?: RemoteFrames }> {
    if (this.#closed) return Promise.reject(this.#failure ?? failure('owner_closed'));
    if (signal?.aborted) return Promise.reject(signal.reason);
    const terminalControl = call.operation === 'discard-issue' || call.operation === 'settle-ipc';
    // Each terminal control corresponds to an already admitted call. Reserve
    // its slot so saturated caller admission cannot prevent credential cleanup.
    if (!terminalControl && this.#pending.size + this.#authorityTickets.size + (this.#query?.pendingCount ?? 0) >= 128) return Promise.reject(failure('owner_busy', 429));
    return new Promise((resolve, reject) => {
      const id = randomUUID();
      let changesAuthority = false;
      try {
        const request = call.operation === 'dispatch' ? call.request : call.operation === 'invoke' || call.operation === 'stream' ? call.input : undefined;
        if (request !== undefined) { validateCoreRequest(request); changesAuthority = isAuthorityChange(request); }
      } catch { /* Invalid requests retain the owner's normal validation response. */ }
      if (changesAuthority) {
        if (Atomics.load(this.#authority, 0) === 18446744073709551615n) { reject(failure('owner_failed')); this.#fault(failure('owner_failed')); return; }
        Atomics.add(this.#authority, 0, 1n); this.#authorityTickets.add(id);
      }
      const epoch = Atomics.load(this.#authority, 0).toString();
      if (call.operation === 'discard-issue' || call.operation === 'settle-ipc' && !call.accept) this.#authorityTickets.add(id);
      const input = call.operation === 'dispatch' ? call.request : call.operation === 'invoke' || call.operation === 'stream' ? call.input : undefined;
      const requestId = input && typeof input === 'object' && 'id' in input && typeof input.id === 'string' ? input.id : '';
      const pending: Pending = { epoch, operation: call.operation, changesAuthority, requestId, resolve, reject, signal, abort: () => {
        if (pending.cancelled) return;
        pending.cancelled = true;
        const reason = signal?.reason;
        reject(reason); pending.frames?.fail(reason);
        this.#send({ protocol: 1, type: 'abort', id });
        signal?.removeEventListener('abort', pending.abort);
      } };
      this.#pending.set(id, pending); signal?.addEventListener('abort', pending.abort, { once: true });
      try { this.#send({ protocol: 1, type: 'call', id, call, epoch }); }
      catch {
        this.#authorityTickets.delete(id);
        if (changesAuthority && this.#session) this.#session = { ...this.#session, epoch };
        this.#release(id); reject(failure('owner_input_uncloneable', 400));
      }
    });
  }
  #canQuery(input: unknown): input is CoreRequest {
    try { validateCoreRequest(input); return isQueryRequest(input); } catch { return false; }
  }
  #canCancel(input: unknown): input is CoreRequest {
    try { validateCoreRequest(input); return isDocumentCancelRequest(input); } catch { return false; }
  }
  #cancelCommand(target: CancelTarget, requestId: string, release: () => void, signal?: AbortSignal): Promise<CoreResponse> {
    if (this.#closed || this.#cancellations.size >= 64) { release(); return Promise.reject(this.#failure ?? failure(this.#closed ? 'owner_closed' : 'owner_busy', this.#closed ? 503 : 429)); }
    return new Promise((resolve, reject) => {
      let settle!: () => void;
      const settled = new Promise<void>(resolveSettled => { settle = resolveSettled; });
      const id = randomUUID(), pending = { requestId, settled, settle, resolve, reject, release, signal, abort: () => { reject(signal?.reason); signal?.removeEventListener('abort', pending.abort); } };
      this.#cancellations.set(id, pending); signal?.addEventListener('abort', pending.abort, { once: true });
      try {
        // CAS has already linearized a valid intent. Keep its private control
        // slot until actual owner ACK even if the requesting window disconnects.
        this.#send({ protocol: 1, type: 'cancel-attempt', id, requestId, identity: target.identity });
        if (signal?.aborted) pending.abort();
      } catch { this.#cancellations.delete(id); signal?.removeEventListener('abort', pending.abort); release(); pending.settle(); reject(failure('owner_input_uncloneable', 400)); }
    });
  }
  /** Trusted transport lifetime; an aborted caller Promise is not an owner ACK. */
  async waitForCancellation(requestId: string): Promise<void> {
    // Desktop enforces unique in-flight IDs. Other trusted transports may reuse
    // an external ID, so conservatively wait for every currently matching call.
    await Promise.all([...this.#cancellations.values()].filter(pending => pending.requestId === requestId).map(pending => pending.settled));
  }
  async #cancel(request: CoreRequest, binding: QueryBinding, signal?: AbortSignal): Promise<CoreResponse> {
    if (this.#closed) throw this.#failure ?? failure('owner_closed');
    if (signal?.aborted) throw signal.reason;
    let target: CancelTarget | undefined, release: (() => void) | undefined;
    try {
      const epoch = Atomics.load(this.#authority, 0).toString();
      if (this.#authorityTickets.size || this.#session?.epoch !== epoch) throw new AppError(409, 'auth_superseded', '登录状态正在改变，请稍后重试。');
      const response = await this.#query!.cancelPreflight(request, binding, epoch, result => {
        if (this.#closed) throw this.#failure ?? failure('owner_closed');
        if (this.#authorityTickets.size || epoch !== Atomics.load(this.#authority, 0).toString()) throw new AppError(409, 'auth_superseded', '登录状态已改变，请重新操作。');
        if (signal?.aborted) throw signal.reason;
        if (this.#cancellations.size >= 64) throw failure('owner_busy', 429);
        if (result) { release = this.#attempts.request(result); target = result; }
      }, signal);
      if (response.status !== 200) return response;
      // Absence is a terminal no-op from the authorized snapshot. Never select
      // a future job by falling back to the owner's document route.
      if (!target) return response;
      const command = this.#cancelCommand(target, request.id, release!, signal); release = undefined;
      return await command;
    } catch (error) { release?.(); if (signal?.aborted) throw signal.reason; return errorResponse(request.id, error); }
  }
  async #read(request: CoreRequest, binding: QueryBinding, signal?: AbortSignal): Promise<CoreResponse> {
    if (this.#closed) throw this.#failure ?? failure('owner_closed');
    if (signal?.aborted) throw signal.reason;
    try {
      if (this.#pending.size + this.#authorityTickets.size + (this.#query?.pendingCount ?? 0) >= 128) throw failure('owner_busy', 429);
      const epoch = Atomics.load(this.#authority, 0).toString();
      if (this.#authorityTickets.size || this.#session?.epoch !== epoch) throw new AppError(409, 'auth_superseded', '登录状态正在改变，请稍后重试。');
      const result = await this.#query!.dispatch(request, binding, epoch, signal);
      if (this.#closed) throw this.#failure ?? failure('owner_closed');
      if (this.#authorityTickets.size || epoch !== Atomics.load(this.#authority, 0).toString()) throw new AppError(409, 'auth_superseded', '登录状态已改变，请重新操作。');
      return result;
    } catch (error) { if (signal?.aborted) throw signal.reason; return errorResponse(request.id, error); }
  }
  async dispatch(request: CoreRequest, binding: PrivateBinding, signal?: AbortSignal): Promise<PrivateDispatch> {
    if (this.#canCancel(request)) {
      return { response: await this.#cancel(request, { transport: binding.transport, access: binding.access, bearer: binding.bearer, apiKey: binding.apiKey, selectedTenant: binding.selectedTenant }, signal) };
    }
    if (this.#canQuery(request)) return { response: await this.#read(request, { transport: binding.transport, access: binding.access, bearer: binding.bearer, apiKey: binding.apiKey, selectedTenant: binding.selectedTenant }, signal) };
    const result = await this.#call({ operation: 'dispatch', request, binding }, signal);
    const value = result.value as Omit<PrivateDispatch, 'stream'>;
    return { ...value, ...(value.binary ? { binary: new CoreBinary(value.binary.bytes, value.binary.name, value.binary.mimeType, value.binary.sha256) } : {}), ...(result.frames ? { stream: new CoreStream(result.frames) } : {}) };
  }
  async invoke(input: unknown, options: IpcOptions = {}, signal?: AbortSignal): Promise<IpcResponse> {
    if (this.#canCancel(input) && options && typeof options === 'object' && !Array.isArray(options) && Object.keys(options).every(key => key === 'tenantId') && (options.tenantId === undefined || typeof options.tenantId === 'string' && !!options.tenantId && options.tenantId.length <= 128)) {
      if (Buffer.byteLength(JSON.stringify(input)) > 2 * 1024 * 1024) return errorResponse(input.id, new AppError(413, 'body_too_large', '请求正文超过限制。'));
      return this.#cancel(input, { transport: 'ipc', access: this.#session?.access, selectedTenant: options.tenantId }, signal);
    }
    if (this.#canQuery(input) && options && typeof options === 'object' && !Array.isArray(options) && Object.keys(options).every(key => key === 'tenantId') && (options.tenantId === undefined || typeof options.tenantId === 'string' && !!options.tenantId && options.tenantId.length <= 128)) {
      if (Buffer.byteLength(JSON.stringify(input)) > 2 * 1024 * 1024) return errorResponse(input.id, new AppError(413, 'body_too_large', '请求正文超过限制。'));
      return this.#read(input, { transport: 'ipc', access: this.#session?.access, selectedTenant: options.tenantId }, signal);
    }
    return (await this.#call({ operation: 'invoke', input, options }, signal)).value as IpcResponse;
  }
  async openStream(input: unknown, options: IpcOptions = {}, signal?: AbortSignal): Promise<IpcStream> {
    const result = await this.#call({ operation: 'stream', input, options }, signal);
    return { ...(result.value as { response: IpcStream['response'] }), ...(result.frames ? { frames: result.frames } : {}) };
  }
  async nativeLangfuse(input: unknown, signal?: AbortSignal): Promise<NativeLangfuseResponse> {
    return (await this.#call({ operation: 'langfuse', input }, signal)).value as NativeLangfuseResponse;
  }
  async startupLog(level: string, event: string): Promise<void> { await this.#call({ operation: 'log', level, event }); }
  httpTransport(): Promise<CoreHttpTransport> {
    const owner = this;
    return this.#httpPromise ??= this.#call({ operation: 'http' }).then(result => ({
      get isAlive() { return !owner.#closed; },
      serviceId: this.serviceId, csrfKey: (result.value as { csrfKey: string }).csrfKey,
      dispatch: this.dispatch.bind(this),
      preflightUpload: async (binding, kind, resourceId, signal) => { await this.#call({ operation: 'upload-preflight', binding, kind, resourceId }, signal); },
    }));
  }
  close(): Promise<void> {
    if (this.#closePromise) return this.#closePromise;
    this.#closed = true;
    this.#attempts.close(false); // Owner shutdown decides existing commit/cancel gates.
    for (const pending of this.#cancellations.values()) { pending.signal?.removeEventListener('abort', pending.abort); pending.release(); pending.reject(failure('owner_closed')); pending.settle(); }
    this.#cancellations.clear();
    for (const [id, pending] of this.#pending) { const error = failure('owner_closed'); pending.reject(error); pending.frames?.fail(error); this.#release(id); }
    this.#closePromise = (async () => {
      await this.#query?.close();
      if (!this.#failure) this.#send({ protocol: 1, type: 'close' });
      const code = await this.#exited;
      if (this.#failure) throw this.#failure;
      if (this.#closedReply?.error) throw remoteError(this.#closedReply.error);
      if (!this.#closedReply || code !== 0) throw failure('owner_failed');
    })();
    return this.#closePromise;
  }
}
