import { randomUUID } from 'node:crypto';
import type { JsonObject } from '../contracts.js';
import { OwnedProcessRegistry } from '../jobs/owned-process.js';
import { AppError } from '../errors.js';
import { pythonWorkerEnv } from '../tools/python-env.js';
import { object, fail } from './common.js';
export interface RagasRow { example_id: string; question: string; answer: string; reference: string; contexts: string[] }
export interface RagasOptions { pythonExecutable: string; workerPath: string }
export type RagasModelCall = JsonObject & { operation: 'chat' | 'embed'; call_id: string };
export interface RagasCallOptions { signal?: AbortSignal; timeoutMs?: number; onProgress?: (completed: number, total: number) => void; }
/** Only this owned helper sees evaluation text; it receives no model credentials or DB path. */
export class RagasBridge {
  private readonly registry = new OwnedProcessRegistry();
  private readonly calls = new Set<Promise<JsonObject>>();
  private readonly controllers = new Set<AbortController>();
  private closed = false;
  constructor(readonly options: RagasOptions) {}
  capabilities(options: RagasCallOptions = {}): Promise<JsonObject> { return this.run('capabilities', [], undefined, options); }
  evaluate(rows: RagasRow[], model: (request: RagasModelCall, signal: AbortSignal) => Promise<JsonObject>, options: RagasCallOptions = {}): Promise<JsonObject> { return this.run('evaluate', rows, model, options); }
  private run(operation: string, rows: RagasRow[], model: ((request: RagasModelCall, signal: AbortSignal) => Promise<JsonObject>) | undefined, options: RagasCallOptions): Promise<JsonObject> {
    if (this.closed) return Promise.reject(new AppError(503, 'evaluation_closed', 'Evaluation is closed'));
    const work = this.perform(operation, rows, model, options); this.calls.add(work); void work.finally(() => this.calls.delete(work)).catch(() => {}); return work;
  }
  private async perform(operation: string, rows: RagasRow[], model: ((request: RagasModelCall, signal: AbortSignal) => Promise<JsonObject>) | undefined, options: RagasCallOptions): Promise<JsonObject> {
    const timeoutMs = options.timeoutMs ?? 300000;
    if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 3600000) return fail(400, 'invalid_evaluation_input', 'Worker timeout is outside supported bounds');
    const id = randomUUID(), input = JSON.stringify({ protocol: 1, id, operation, rows });
    if (Buffer.byteLength(input) > 2 * 1024 * 1024) return fail(413, 'evaluation_input_limit', 'Evaluation input exceeds the limit');
    const env: NodeJS.ProcessEnv = { ...pythonWorkerEnv(this.options.pythonExecutable), OPENBLAS_NUM_THREADS: '1', OMP_NUM_THREADS: '1', RAGAS_DO_NOT_TRACK: 'true', HF_HUB_DISABLE_TELEMETRY: '1' };
    const controller = new AbortController(), abort = () => controller.abort(); this.controllers.add(controller);
    options.signal?.addEventListener('abort', abort, { once: true }); if (options.signal?.aborted) abort();
    let result: JsonObject | undefined, error: unknown, pending = '', processing = false, count = 0;
    let progressed = 0; const decoder = new TextDecoder('utf-8', { fatal: true }), modelCalls = new Set<Promise<void>>(), seen = new Set<string>();
    // The bridge owns the deadline so model RPCs abort before helper cleanup
    // and audit settlement. Preserve this first error if cancellation arrives later.
    const deadline = setTimeout(() => { if (controller.signal.aborted) return; error ??= new AppError(504, 'evaluation_timeout', 'Evaluation worker did not complete'); controller.abort(); }, timeoutMs);
    deadline.unref();
    let owned;
    try { owned = this.registry.spawn(this.options.pythonExecutable, ['-B', '-u', this.options.workerPath], controller.signal, { env, maxOutputBytes: 32 * 1024 * 1024 }); }
    catch { clearTimeout(deadline); options.signal?.removeEventListener('abort', abort); this.controllers.delete(controller); return fail(499, 'evaluation_cancelled', 'Evaluation was cancelled before helper startup'); }
    const invalid = () => { error ??= new AppError(502, 'ragas_protocol_invalid', 'Invalid evaluation worker protocol'); controller.abort(); };
    const write = (message: JsonObject) => { const line = JSON.stringify(message); if (Buffer.byteLength(line) > 2 * 1024 * 1024) return invalid(); if (!controller.signal.aborted) owned.child.stdin.write(`${line}\n`); };
    const accept = (message: JsonObject) => {
      if (message.protocol !== 1 || message.id !== id || result || error || ++count > 5000) return invalid();
      if (message.type === 'error') { error = new AppError(502, 'ragas_scoring_failed', 'Ragas could not produce valid scores'); controller.abort(); return; }
      if (message.type === 'result') { if (message.operation !== operation || processing) return invalid(); result = object(message.result); return; }
      if (message.type === 'progress') { if (!Number.isSafeInteger(message.completed) || !Number.isSafeInteger(message.total) || message.total !== rows.length || Number(message.completed) !== progressed + 1 || Number(message.completed) > rows.length || message.example_id !== rows[progressed]?.example_id) return invalid(); progressed++; options.onProgress?.(Number(message.completed), Number(message.total)); return; }
      if (message.type !== 'model_call' || !model || processing || typeof message.call_id !== 'string' || !/^[a-f0-9-]{36}$/.test(message.call_id) || seen.has(message.call_id) || !['chat', 'embed'].includes(String(message.operation))) return invalid();
      if (!rows.some(row => row.example_id === message.example_id) || !Number.isSafeInteger(message.call_index) || Number(message.call_index) < 1 || Number(message.call_index) > 4096) return invalid();
      if (message.operation === 'chat' && (typeof message.prompt !== 'string' || !message.prompt || Buffer.byteLength(message.prompt) > 1024 * 1024 || !Object.keys(object(message.schema)).length) || message.operation === 'embed' && (!Array.isArray(message.texts) || !message.texts.length || message.texts.length > 100 || message.texts.some(text => typeof text !== 'string' || !text.trim()))) return invalid();
      seen.add(message.call_id); processing = true;
      const call = (async () => {
        try { const value = await model(message as RagasModelCall, controller.signal); write({ protocol: 1, id, type: 'model_result', call_id: message.call_id!, result: value }); }
        catch (cause) { error ??= cause; controller.abort(); }
        finally { processing = false; }
      })(); modelCalls.add(call); void call.finally(() => modelCalls.delete(call)).catch(() => {});
    };
    owned.child.stdout.on('data', (bytes: Buffer) => {
      try { pending += decoder.decode(bytes, { stream: true }); } catch { return invalid(); } if (Buffer.byteLength(pending) > 2 * 1024 * 1024) return invalid();
      for (;;) { const newline = pending.indexOf('\n'); if (newline < 0) break; const line = pending.slice(0, newline); pending = pending.slice(newline + 1); try { accept(object(JSON.parse(line))); } catch { invalid(); } }
    });
    try {
      owned.child.stdin.write(`${input}\n`);
      try { await owned.completion; } catch (cause) { if (!error) { const code = object(cause).code; error = new AppError(code === 'child_timeout' ? 504 : 502, code === 'child_timeout' ? 'evaluation_timeout' : options.signal?.aborted || this.closed ? 'evaluation_cancelled' : 'evaluation_worker_failed', 'Evaluation worker did not complete'); } controller.abort(); }
      await Promise.allSettled([...modelCalls]);
      if (error) throw error;
      try { pending += decoder.decode(); } catch { return fail(502, 'ragas_protocol_invalid', 'Invalid evaluation worker encoding'); }
      if (pending || !result) return fail(502, 'ragas_protocol_invalid', 'Evaluation worker returned no complete result');
      if (operation === 'evaluate') {
        const values = result.rows;
        if (!Array.isArray(values) || values.length !== rows.length || values.some((raw, index) => { const value = object(raw); return value.example_id !== rows[index]!.example_id || ['faithfulness', 'answer_relevancy', 'context_precision'].some(key => typeof value[key] !== 'number' || !Number.isFinite(value[key]) || Number(value[key]) < (key === 'answer_relevancy' ? -1 : 0) || Number(value[key]) > 1); })) return fail(502, 'ragas_protocol_invalid', 'Evaluation scores are incomplete or invalid');
      } else if (result.ragas_version !== '0.4.3' || result.django_imported !== false) return fail(502, 'ragas_protocol_invalid', 'Unsupported evaluation worker capability');
      return result;
    } finally { clearTimeout(deadline); controller.abort(); owned.stop(); await owned.completion.catch(() => {}); await Promise.allSettled([...modelCalls]); options.signal?.removeEventListener('abort', abort); this.controllers.delete(controller); }
  }
  async close(): Promise<void> { this.closed = true; this.controllers.forEach(controller => controller.abort()); await this.registry.close(); await Promise.allSettled([...this.calls]); }
}
