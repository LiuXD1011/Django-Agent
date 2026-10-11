import { AppError } from '../errors.js';

export interface IntegrationCallOptions { signal?: AbortSignal; timeoutMs?: number }
export const fail = (status: number, code: string, message: string): never => { throw new AppError(status, code, message); };
export function endpoint(value: unknown): URL {
  if (typeof value !== 'string' || /[\s\\]/.test(value)) return fail(400, 'integration_invalid_endpoint', 'Invalid service endpoint');
  let url: URL; try { url = new URL(value); } catch { return fail(400, 'integration_invalid_endpoint', 'Invalid service endpoint'); }
  if (!['http:', 'https:'].includes(url.protocol) || !url.hostname || url.username || url.password || url.search || url.hash) return fail(400, 'integration_invalid_endpoint', 'Invalid service endpoint');
  return url;
}
export class CallScope {
  readonly controller = new AbortController();
  readonly signal: AbortSignal;
  readonly timeoutMs: number;
  readonly finished: Promise<void>;
  private finish: () => void = () => {};
  private readonly timer: ReturnType<typeof setTimeout>;
  constructor(options: IntegrationCallOptions = {}) {
    this.finished = new Promise(resolve => { this.finish = resolve; });
    const timeout = options.timeoutMs ?? 5000;
    if (!Number.isInteger(timeout) || timeout < 1 || timeout > 60000) fail(400, 'integration_invalid_timeout', 'Timeout must be between 1 and 60000 milliseconds');
    this.timeoutMs = timeout;
    const signals = [this.controller.signal];
    if (options.signal) signals.push(options.signal);
    this.signal = AbortSignal.any(signals);
    this.timer = setTimeout(() => this.controller.abort(new AppError(504, 'integration_timeout', 'External service timed out')), timeout);
    this.timer.unref();
  }
  check(): void {
    if (this.signal.aborted) throw this.controller.signal.aborted && this.controller.signal.reason instanceof AppError && this.signal.reason === this.controller.signal.reason ? this.controller.signal.reason : new AppError(499, 'integration_cancelled', 'External service request cancelled');
  }
  async wait<T>(work: PromiseLike<T>): Promise<T> {
    this.check(); let listener: () => void = () => {};
    try { return await Promise.race([Promise.resolve(work), new Promise<never>((_resolve, reject) => { listener = () => { try { this.check(); } catch (error) { reject(error); } }; this.signal.addEventListener('abort', listener, { once: true }); })]); }
    finally { this.signal.removeEventListener('abort', listener); }
  }
  dispose(): void { clearTimeout(this.timer); this.finish(); }
}
/** One origin, no credential forwarding redirects, and a bound on bytes consumed by JSON/SSE clients. */
export function restrictedFetch(scope: CallScope, origin: string) {
  let consumed = 0;
  return async (value: string | URL, init?: RequestInit): Promise<Response> => {
    scope.check(); const url = new URL(value);
    if (url.origin !== origin || url.username || url.password) return fail(400, 'integration_endpoint_changed', 'External service cannot change the configured origin');
    if (typeof init?.body === 'string' && Buffer.byteLength(init.body) > 256 * 1024) return fail(413, 'integration_request_too_large', 'External request exceeds the size limit');
    const response = await scope.wait(fetch(url, { ...init, redirect: 'manual', signal: init?.signal ? AbortSignal.any([scope.signal, init.signal]) : scope.signal }));
    if (response.status >= 300 && response.status < 400) { await response.body?.cancel(); return fail(502, 'integration_redirect_rejected', 'External service redirect rejected'); }
    if (Number(response.headers.get('content-length')) > 1024 * 1024) { await response.body?.cancel(); return fail(502, 'integration_response_too_large', 'External response exceeds the size limit'); }
    if (!response.body) return response;
    const reader = response.body.getReader(); let count = 0;
    const stream = new ReadableStream<Uint8Array>({
      async pull(controller) {
        try {
          const item = await scope.wait(reader.read());
          if (item.done) { controller.close(); reader.releaseLock(); return; }
          count += item.value.byteLength; consumed += item.value.byteLength;
          if (count > 1024 * 1024 || consumed > 4 * 1024 * 1024) { await reader.cancel(); fail(502, 'integration_response_too_large', 'External response exceeds the size limit'); }
          controller.enqueue(item.value);
        } catch (error) { void reader.cancel().catch(() => {}); controller.error(error); }
      },
      cancel: reason => reader.cancel(reason),
    });
    return new Response(stream, { status: response.status, statusText: response.statusText, headers: response.headers });
  };
}
export async function responseJSON(response: Response): Promise<unknown> {
  if (!response.ok) { await response.body?.cancel(); return fail(502, 'integration_connection_failed', 'External service request failed'); }
  let text: string; try { text = await response.text(); } catch (error) { if (error instanceof AppError) throw error; return fail(502, 'integration_invalid_response', 'External service returned an invalid response'); }
  try { return JSON.parse(text); } catch { return fail(502, 'integration_invalid_response', 'External service returned an invalid response'); }
}
