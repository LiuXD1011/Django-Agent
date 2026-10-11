import type { ChatMessage, ModelConfiguration, ModelCallOptions, ModelDelta, ModelUsage, JsonObject } from '../contracts.js';
import { ModelRuntimeError, resolveProvider, type ProviderConfiguration, type ModelOperation } from './providers.js';
import { thinkingWireOptions } from './thinking.js';
export { ModelRuntimeError } from './providers.js';

export interface ModelCompletion {
  content: string;
  reasoning_content: string;
  tool_calls: JsonObject[];
  finish_reason: string;
  usage: ModelUsage;
}
export interface EmbeddingResult { vectors: number[][]; usage: ModelUsage; }
export interface RerankResult { results: Array<{ index: number; relevance_score: number }>; usage: ModelUsage; }

type ObjectValue = Record<string, unknown>;
function object(value: unknown): ObjectValue {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as ObjectValue : {};
}
function invalid(message = 'Model returned an invalid response'): never {
  throw new ModelRuntimeError('model_response_invalid', message, undefined, true);
}
function usageCount(value: unknown): number {
  if (value === undefined || value === null) return 0;
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) invalid('Model returned invalid usage');
  return value;
}
/** Zero means not reported. No token estimation is presented as vendor usage. */
export function modelUsage(payload: unknown): ModelUsage {
  const data = object(payload);
  const usage = object(data.usage ?? object(data.meta).tokens);
  const prompt = usageCount(usage.prompt_tokens ?? usage.input_tokens);
  const completion = usageCount(usage.completion_tokens ?? usage.output_tokens);
  return {
    prompt_tokens: prompt, completion_tokens: completion,
    total_tokens: usageCount(usage.total_tokens === undefined ? prompt + completion : usage.total_tokens),
    cached_tokens: usageCount(object(usage.prompt_tokens_details).cached_tokens ?? usage.prompt_cache_hit_tokens ?? usage.cached_tokens),
    reasoning_tokens: usageCount(object(usage.completion_tokens_details).reasoning_tokens ?? usage.reasoning_tokens),
  };
}
function array(value: unknown): unknown[] { return Array.isArray(value) ? value : invalid(); }
function string(value: unknown, empty = true): string {
  if ((value === undefined || value === null) && empty) return '';
  return typeof value === 'string' ? value : invalid();
}
function calls(value: unknown): JsonObject[] {
  if (value === undefined || value === null) return [];
  return array(value).map(item => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) invalid('Model returned invalid tool calls');
    return structuredClone(item) as JsonObject;
  });
}
function upstreamError(payload: unknown): void {
  if (object(payload).error !== undefined || (object(payload).code && !object(payload).choices && !object(payload).data && !object(payload).results && !object(payload).output)) {
    throw new ModelRuntimeError('model_upstream_error', 'Model provider returned an error', undefined, true);
  }
}
function decodeJson(raw: string): unknown {
  try { return JSON.parse(raw) as unknown; } catch { return invalid('Model returned malformed JSON'); }
}
function validateMessages(messages: ChatMessage[]): void {
  if (!Array.isArray(messages) || messages.length === 0) throw new ModelRuntimeError('model_input_invalid', 'At least one chat message is required');
  for (const message of messages) {
    if (!message || !['system', 'user', 'assistant', 'tool'].includes(message.role) ||
      (typeof message.content !== 'string' && !Array.isArray(message.content))) {
      throw new ModelRuntimeError('model_input_invalid', 'Chat messages must use supported roles and content');
    }
  }
}
function validateTexts(texts: string[], name: string): void {
  if (!Array.isArray(texts) || texts.some(value => typeof value !== 'string' || !value.trim())) {
    throw new ModelRuntimeError('model_input_invalid', `${name} must contain nonempty strings`);
  }
}

interface CallScope {
  signal: AbortSignal;
  error(error: unknown): ModelRuntimeError;
  close(): void;
}
function callScope(configuration: ProviderConfiguration, options: ModelCallOptions): CallScope {
  const timeout = options.timeoutMs ?? configuration.timeoutMs;
  if (!Number.isSafeInteger(timeout) || timeout <= 0 || timeout > 2 ** 31 - 1) throw new ModelRuntimeError('model_input_invalid', 'Model timeout must be an integer in the supported timer range');
  const controller = new AbortController();
  let timedOut = false;
  const cancel = () => controller.abort();
  if (options.signal?.aborted) cancel();
  else options.signal?.addEventListener('abort', cancel, { once: true });
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, timeout);
  timer.unref();
  return {
    signal: controller.signal,
    error(error) {
      if (timedOut) return new ModelRuntimeError('model_timeout', 'Model request timed out; its upstream result may be unknown', undefined, true);
      if (options.signal?.aborted) return new ModelRuntimeError('model_cancelled', 'Model request was cancelled', undefined, true);
      if (error instanceof ModelRuntimeError) return error;
      // Network/parser exceptions can contain URL, headers, keys or cancellation reasons.
      return new ModelRuntimeError('model_network_error', 'Model connection failed; its upstream result may be unknown', undefined, true);
    },
    close() { clearTimeout(timer); options.signal?.removeEventListener('abort', cancel); controller.abort(); },
  };
}

/** SSE framing retains UTF8 decoder state, arbitrary chunk boundaries and every data line. */
async function* sse(response: Response): AsyncGenerator<{ event: string; data: string }> {
  if (!response.body) invalid('Model stream has no response body');
  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8', { fatal: true });
  let pending = ''; let data: string[] = []; let event = ''; let eventSize = 0;
  const line = (value: string): { event: string; data: string } | undefined => {
    if (value === '') {
      const result = data.length ? { event, data: data.join('\n') } : undefined;
      data = []; event = ''; eventSize = 0; return result;
    }
    if (value.startsWith(':')) return;
    const colon = value.indexOf(':');
    const field = colon < 0 ? value : value.slice(0, colon);
    let body = colon < 0 ? '' : value.slice(colon + 1);
    if (body.startsWith(' ')) body = body.slice(1);
    if (field === 'data') { data.push(body); eventSize += body.length; }
    if (field === 'event') event = body;
    if (eventSize > 8 * 1024 * 1024) invalid('Model stream event exceeded the size limit');
  };
  try {
    while (true) {
      const next = await reader.read();
      pending += next.done ? decoder.decode() : decoder.decode(next.value, { stream: true });
      let start = 0;
      for (let i = 0; i < pending.length; i++) {
        const char = pending[i];
        if (char !== '\r' && char !== '\n') continue;
        if (char === '\r' && i === pending.length - 1 && !next.done) break;
        const result = line(pending.slice(start, i));
        if (char === '\r' && pending[i + 1] === '\n') i++;
        start = i + 1;
        if (result) yield result;
      }
      pending = pending.slice(start);
      if (pending.length > 8 * 1024 * 1024) invalid('Model stream line exceeded the size limit');
      if (next.done) {
        // SSE only dispatches complete events. An unterminated last event is truncated.
        if (pending || data.length) invalid('Model stream ended inside an event');
        return;
      }
    }
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

/** Framework independent HTTP client. One method invocation sends at most one paid request. */
export class ModelRuntime {
  readonly #provider: ProviderConfiguration;
  constructor(configuration: ModelConfiguration) { this.#provider = resolveProvider(structuredClone(configuration)); }

  #chatBody(messages: ChatMessage[], options: ModelCallOptions, stream: boolean): JsonObject {
    validateMessages(messages);
    let thinking: JsonObject;
    try { thinking = thinkingWireOptions(this.#provider.baseUrl, this.#provider.model, options.thinking ?? this.#provider.thinking); }
    catch { throw new ModelRuntimeError('model_thinking_invalid', 'Model does not support the requested thinking policy'); }
    const body: JsonObject = { model: this.#provider.model, messages: messages as unknown as JsonObject[], stream, ...thinking };
    if (stream) body.stream_options = { include_usage: true };
    if (options.tools !== undefined) body.tools = options.tools;
    if (options.temperature !== undefined) {
      if (!Number.isFinite(options.temperature)) throw new ModelRuntimeError('model_input_invalid', 'Model temperature must be finite');
      body.temperature = options.temperature;
    }
    if (options.maxTokens !== undefined) {
      if (!Number.isSafeInteger(options.maxTokens) || options.maxTokens <= 0) throw new ModelRuntimeError('model_input_invalid', 'Max tokens must be a positive integer');
      body.max_tokens = options.maxTokens;
    }
    return body;
  }

  async #send(operation: ModelOperation, body: JsonObject, signal: AbortSignal): Promise<Response> {
    if (signal.aborted) throw new ModelRuntimeError('model_cancelled', 'Model request was cancelled');
    const response = await fetch(this.#provider.endpoint(operation), {
      method: 'POST', headers: this.#provider.headers(), body: JSON.stringify(body), signal, redirect: 'error',
    });
    if (!response.ok) {
      await response.body?.cancel().catch(() => undefined);
      throw new ModelRuntimeError(response.status === 401 || response.status === 403 ? 'model_access_denied' : 'model_http_error',
        `Model provider rejected the request (HTTP ${response.status})`, response.status);
    }
    return response;
  }

  async #json(operation: ModelOperation, body: JsonObject, options: ModelCallOptions): Promise<unknown> {
    const scope = callScope(this.#provider, options);
    try {
      const response = await this.#send(operation, body, scope.signal);
      const result = decodeJson(await response.text()); upstreamError(result); return result;
    } catch (error) { throw scope.error(error); } finally { scope.close(); }
  }

  /** tool_calls events are indexed argument/name fragments; callers merge them by index. */
  async *chat(messages: ChatMessage[], options: ModelCallOptions = {}): AsyncGenerator<ModelDelta> {
    const body = this.#chatBody(messages, options, true);
    const scope = callScope(this.#provider, options);
    let finishReason = '';
    try {
      const response = await this.#send('chat', body, scope.signal);
      if (!response.headers.get('content-type')?.toLowerCase().includes('text/event-stream')) {
        await response.body?.cancel(); invalid('Model did not return an SSE stream');
      }
      for await (const frame of sse(response)) {
        if (scope.signal.aborted) throw scope.error(undefined);
        if (frame.event === 'error') throw new ModelRuntimeError('model_upstream_error', 'Model provider returned a stream error', undefined, true);
        if (frame.data.trim() === '[DONE]') break;
        const payload = decodeJson(frame.data); upstreamError(payload);
        const data = object(payload);
        if (data.usage !== undefined || object(data.meta).tokens !== undefined) yield { type: 'usage', usage: modelUsage(data) };
        const choices = array(data.choices ?? []);
        if (choices.length === 0) continue;
        const choice = object(choices[0]); const delta = object(choice.delta);
        const content = string(delta.content);
        const reasoning = string(delta.reasoning_content ?? delta.reasoning);
        if (content) yield { type: 'content', content };
        if (reasoning) yield { type: 'reasoning', content: reasoning };
        if (delta.tool_calls !== undefined) yield { type: 'tool_calls', tool_calls: calls(delta.tool_calls) };
        if (choice.finish_reason !== undefined && choice.finish_reason !== null) finishReason = string(choice.finish_reason, false);
      }
      if (!finishReason) throw new ModelRuntimeError('model_stream_interrupted', 'Model stream ended before completion; its upstream result may be unknown', undefined, true);
      yield { type: 'done', finish_reason: finishReason };
    } catch (error) { throw scope.error(error); } finally { scope.close(); }
  }

  async complete(messages: ChatMessage[], options: ModelCallOptions = {}): Promise<ModelCompletion> {
    const data = object(await this.#json('chat', this.#chatBody(messages, options, false), options));
    const choices = array(data.choices);
    if (choices.length === 0) invalid('Model returned no completion choices');
    const choice = object(choices[0]); const message = object(choice.message);
    const finish = string(choice.finish_reason, false);
    if (!finish) invalid('Model returned no completion finish reason');
    return { content: string(message.content), reasoning_content: string(message.reasoning_content ?? message.reasoning),
      tool_calls: calls(message.tool_calls), finish_reason: finish, usage: modelUsage(data) };
  }

  async embed(texts: string[], options: ModelCallOptions = {}): Promise<EmbeddingResult> {
    validateTexts(texts, 'Embedding input');
    if (texts.length === 0) return { vectors: [], usage: modelUsage({}) };
    if (!this.#provider.dimension) throw new ModelRuntimeError('model_configuration_invalid', 'Embedding dimension must be configured');
    const body: JsonObject = { model: this.#provider.model, input: texts };
    const data = object(await this.#json('embedding', body, options));
    const rows = array(data.data);
    if (rows.length !== texts.length) invalid('Embedding result count does not match input');
    const vectors: number[][] = new Array(texts.length);
    for (const row of rows) {
      const item = object(row); const index = item.index;
      if (typeof index !== 'number' || !Number.isInteger(index) || index < 0 || index >= texts.length || vectors[index] !== undefined) invalid('Embedding returned invalid or duplicate indices');
      const vector = array(item.embedding);
      if (vector.length !== this.#provider.dimension) throw new ModelRuntimeError('embedding_dimension_mismatch', 'Embedding result does not match configured dimension', undefined, true);
      if (vector.some(value => typeof value !== 'number' || !Number.isFinite(value))) invalid('Embedding contains nonfinite or nonnumeric values');
      vectors[index] = vector as number[];
    }
    return { vectors, usage: modelUsage(data) };
  }

  async rerank(query: string, documents: string[], options: ModelCallOptions = {}): Promise<RerankResult> {
    if (typeof query !== 'string' || !query.trim()) throw new ModelRuntimeError('model_input_invalid', 'Rerank query must be nonempty');
    validateTexts(documents, 'Rerank documents');
    if (documents.length === 0) return { results: [], usage: modelUsage({}) };
    const data = object(await this.#json('rerank', this.#provider.rerankBody(query, documents), options));
    const rows = array(data.results ?? object(data.output).results);
    const seen = new Set<number>();
    const results = rows.map(row => {
      const item = object(row); const index = item.index ?? item.document_index;
      const score = item.relevance_score ?? item.score;
      if (typeof index !== 'number' || !Number.isInteger(index) || index < 0 || index >= documents.length || seen.has(index) ||
        typeof score !== 'number' || !Number.isFinite(score)) invalid('Rerank returned invalid indices or scores');
      seen.add(index); return { index, relevance_score: score };
    });
    if (seen.size !== documents.length) throw new ModelRuntimeError('rerank_result_incomplete', 'Rerank did not return every requested document', undefined, true);
    results.sort((left, right) => right.relevance_score - left.relevance_score);
    return { results, usage: modelUsage(data) };
  }

  async vision(imageUrl: string, prompt: string, options: ModelCallOptions = {}): Promise<ModelCompletion> {
    if (typeof imageUrl !== 'string' || !/^(https?:\/\/|data:image\/[\w.+-]+;base64,)/.test(imageUrl) || typeof prompt !== 'string' || !prompt.trim()) {
      throw new ModelRuntimeError('model_input_invalid', 'Vision requires an image URL or image data URL and a prompt');
    }
    return this.complete([{ role: 'user', content: [{ type: 'text', text: prompt }, { type: 'image_url', image_url: { url: imageUrl } }] }], options);
  }
}
