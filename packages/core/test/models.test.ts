import assert from 'node:assert/strict';
import { once } from 'node:events';
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import { setTimeout as delay } from 'node:timers/promises';
import test from 'node:test';
import type { ModelConfiguration, ModelDelta } from '../src/contracts.js';
import { ModelRuntime, ModelRuntimeError } from '../src/models/runtime.js';
import { providerTypes, resolveProvider } from '../src/models/providers.js';
import { capability, normalizeThinking, thinkingWireOptions } from '../src/models/thinking.js';

// Controlled HTTP protocol integration tests; these do not certify vendor models.
async function server(run: (req: IncomingMessage, res: ServerResponse, body: any) => void | Promise<void>) {
  const requests: any[] = [];
  const app = createServer(async (req, res) => {
    try {
      let raw = '';
      for await (const chunk of req) raw += chunk;
      const body = JSON.parse(raw);
      requests.push({ url: req.url, authorization: req.headers.authorization, body });
      await run(req, res, body);
    } catch { res.destroy(); }
  });
  app.listen(0, '127.0.0.1');
  await once(app, 'listening');
  const address = app.address();
  assert(address && typeof address !== 'string');
  return { url: `http://127.0.0.1:${address.port}/v1`, requests, close: async () => {
    app.closeAllConnections(); app.close(); await once(app, 'close');
  } };
}
function config(url: string, parameters: Record<string, any> = {}, source = 'openai'): ModelConfiguration {
  return { id: 'protocol-model', name: 'model', type: 'KnowledgeQA', source,
    parameters: { base_url: url, api_key: 'test-only-credential', model: 'model', ...parameters } };
}
const messages = [{ role: 'user' as const, content: '你好' }];
const response = { choices: [{ message: { content: 'answer', reasoning_content: 'reason',
  tool_calls: [{ id: 'call-1', type: 'function', function: { name: 'lookup', arguments: '{}' } }] }, finish_reason: 'tool_calls' }],
  usage: { prompt_tokens: 8, completion_tokens: 5, total_tokens: 13,
    prompt_tokens_details: { cached_tokens: 3 }, completion_tokens_details: { reasoning_tokens: 2 } } };
async function collect(stream: AsyncGenerator<ModelDelta>) { const result: ModelDelta[] = []; for await (const delta of stream) result.push(delta); return result; }
function json(res: ServerResponse, payload: unknown) { res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(payload)); }

 test('complete and vision use real HTTP, preserve messages/tools and actual detailed usage', async () => {
  const app = await server((_req, res) => json(res, response));
  try {
    const runtime = new ModelRuntime(config(app.url + '/chat/completions/'));
    const result = await runtime.complete(messages, { tools: [{ type: 'function' }], maxTokens: 100, temperature: 0 });
    assert.deepEqual(result.usage, { prompt_tokens: 8, completion_tokens: 5, total_tokens: 13, cached_tokens: 3, reasoning_tokens: 2 });
    assert.equal(result.content, 'answer'); assert.equal(result.reasoning_content, 'reason'); assert.equal(result.tool_calls.length, 1);
    assert.equal(app.requests[0].url, '/v1/chat/completions'); assert.equal(app.requests[0].body.max_tokens, 100);
    assert.equal(app.requests[0].body.temperature, 0); assert.equal(app.requests[0].authorization, 'Bearer test-only-credential');
    await runtime.vision('data:image/png;base64,YQ==', 'describe');
    assert.deepEqual(app.requests[1].body.messages[0].content, [{ type: 'text', text: 'describe' }, { type: 'image_url', image_url: { url: 'data:image/png;base64,YQ==' } }]);
  } finally { await app.close(); }
});

test('SSE handles fragmented UTF8/CRLF/multiline data and preserves reasoning, tool patches, trailing usage', async () => {
  const app = await server(async (_req, res) => {
    res.setHeader('Content-Type', 'text/event-stream');
    const events = ': heartbeat\r\n\r\n' +
      'data: {"choices":[{"delta":{"content":"你好","reasoning_content":"想"}}]}\r\n\r\n' +
      'data: {"choices":[\r\ndata: {"delta":{"tool_calls":[{"index":0,"id":"c","function":{"name":"lookup","arguments":"{"}}]}}]}\r\n\r\n' +
      'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"}"}}]},"finish_reason":"tool_calls"}]}\n\n' +
      'data: {"choices":[],"usage":{"prompt_tokens":4,"completion_tokens":2,"total_tokens":6,"prompt_cache_hit_tokens":1,"completion_tokens_details":{"reasoning_tokens":1}}}\n\n' +
      'data: [DONE]\n\n';
    const bytes = Buffer.from(events);
    for (let i = 0; i < bytes.length; i += 3) { res.write(bytes.subarray(i, i + 3)); await delay(1); }
    res.end();
  });
  try {
    const deltas = await collect(new ModelRuntime(config(app.url)).chat(messages));
    assert.deepEqual(deltas.map(d => d.type), ['content', 'reasoning', 'tool_calls', 'tool_calls', 'usage', 'done']);
    assert.equal((deltas[0] as any).content, '你好'); assert.equal((deltas.at(-1) as any).finish_reason, 'tool_calls');
    assert.equal((deltas[4] as any).usage.cached_tokens, 1);
    assert.equal(app.requests[0].body.stream_options.include_usage, true);
  } finally { await app.close(); }
});

test('embedding reorders indexed results and validates count, configured dimension and finite numbers', async () => {
  let payload: any = { data: [{ index: 1, embedding: [3, 4] }, { index: 0, embedding: [1, 2] }], usage: { prompt_tokens: 4, total_tokens: 4 } };
  const app = await server((_req, res) => json(res, payload));
  try {
    const runtime = new ModelRuntime(config(app.url, { dimension: 2 }));
    const result = await runtime.embed(['first', 'second']);
    assert.deepEqual(result.vectors, [[1, 2], [3, 4]]); assert.equal(result.usage.total_tokens, 4);
    assert.equal(app.requests[0].url, '/v1/embeddings');
    for (const invalid of [[], [{ index: 0, embedding: [1] }, { index: 1, embedding: [2] }], [{ index: 0, embedding: [null, 2] }, { index: 1, embedding: [3, 4] }], [{ index: 0, embedding: [1, 2] }, { index: 0, embedding: [3, 4] }]]) {
      payload = { data: invalid }; await assert.rejects(runtime.embed(['first', 'second']), ModelRuntimeError);
    }
    assert.deepEqual((await runtime.embed([])).vectors, []);
  } finally { await app.close(); }
});

test('rerank accepts native output and rejects incomplete/duplicate/out-of-range/nonfinite results', async () => {
  let payload: any = { output: { results: [{ index: 1, relevance_score: 0.9 }, { document_index: 0, score: 0.2 }] }, usage: { total_tokens: 9 } };
  const app = await server((_req, res) => json(res, payload));
  try {
    const runtime = new ModelRuntime(config(app.url));
    assert.deepEqual((await runtime.rerank('q', ['a', 'b'])).results, [{ index: 1, relevance_score: 0.9 }, { index: 0, relevance_score: 0.2 }]);
    assert.equal(app.requests[0].url, '/v1/rerank');
    for (const invalid of [[], [{ index: 0, score: 1 }], [{ index: -1, score: 1 }, { index: 1, score: 2 }], [{ index: 0, score: 1 }, { index: 0, score: 2 }], [{ index: 0, score: null }, { index: 1, score: 2 }]]) {
      payload = { results: invalid }; await assert.rejects(runtime.rerank('q', ['a', 'b']), ModelRuntimeError);
    }
    await assert.rejects(runtime.rerank('', ['a']), ModelRuntimeError);
    await assert.rejects(runtime.rerank('q', ['']), ModelRuntimeError);
  } finally { await app.close(); }
});

test('HTTP denial, stream errors and malformed JSON never echo upstream credentials and never retry', async () => {
  const app = await server((_req, res) => { res.statusCode = 403; json(res, { error: { message: 'test-only-credential Authorization Bearer danger' } }); });
  try {
    await assert.rejects(new ModelRuntime(config(app.url)).complete(messages), (e: unknown) => {
      assert(e instanceof ModelRuntimeError); assert.equal(e.status, 403); assert.equal(e.code, 'model_access_denied');
      assert(!JSON.stringify(e).includes('test-only-credential')); assert(!String(e).includes('Bearer')); return true;
    });
    assert.equal(app.requests.length, 1);
  } finally { await app.close(); }
  for (const event of ['data: {"error":{"message":"test-only-credential"}}\n\n', 'data: invalid test-only-credential\n\n', 'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n']) {
    const upstream = await server((_req, res) => { res.setHeader('Content-Type', 'text/event-stream'); res.end(event); });
    try { await assert.rejects(collect(new ModelRuntime(config(upstream.url)).chat(messages)), (e: unknown) => {
      assert(e instanceof ModelRuntimeError); assert(!String(e).includes('test-only-credential')); return true;
    }); assert.equal(upstream.requests.length, 1); } finally { await upstream.close(); }
  }
});

test('timeout covers response body, cancellation honors AbortSignal and iterator return closes upstream', async () => {
  let closed = false;
  const app = await server((_req, res) => {
    res.on('close', () => { closed = true; });
    res.setHeader('Content-Type', 'text/event-stream'); res.write('data: {"choices":[{"delta":{"content":"first"}}]}\n\n');
  });
  try {
    const runtime = new ModelRuntime(config(app.url));
    const stream = runtime.chat(messages); await stream.next(); await stream.return(undefined);
    for (let i = 0; i < 20 && !closed; i++) await delay(10);
    assert.equal(closed, true);
    await assert.rejects(collect(runtime.chat(messages, { timeoutMs: 30 })), (e: any) => e.code === 'model_timeout' && e.resultUnknown === true);
    const controller = new AbortController();
    const cancelled = runtime.chat(messages, { signal: controller.signal }); await cancelled.next();
    controller.abort('test-only-credential'); await assert.rejects(cancelled.next(), (e: any) => e.code === 'model_cancelled' && !String(e).includes('test-only-credential'));
    const count = app.requests.length; const already = new AbortController(); already.abort();
    await assert.rejects(runtime.complete(messages, { signal: already.signal }), (e: any) => e.code === 'model_cancelled');
    assert.equal(app.requests.length, count);
  } finally { await app.close(); }
});

test('thinking profiles preserve capability checks and mandatory GLM thinking across auxiliary calls', () => {
  const glm = 'https://open.bigmodel.cn/api/paas/v4';
  assert.equal(capability(glm, 'glm-5.3-flash').profile, 'glm-5.3-required-thinking');
  assert.deepEqual(thinkingWireOptions(glm, 'glm-5.3-flash'), { thinking: { type: 'enabled' } });
  assert.deepEqual(thinkingWireOptions(glm, 'glm-5.3-flash', { mode: 'on', effort: 'low' }), { thinking: { type: 'enabled' }, reasoning_effort: 'low' });
  assert.throws(() => normalizeThinking({ mode: 'off' }, capability(glm, 'glm-5.3-flash')));
  assert.deepEqual(thinkingWireOptions('https://api.deepseek.com/v1', 'deepseek-v4-pro', { mode: 'off' }), { thinking: { type: 'disabled' } });
  assert.throws(() => thinkingWireOptions('https://other.example/v1', 'unknown', { mode: 'on' }));
  assert.throws(() => normalizeThinking({ mode: 'default', effort: 'high' }, capability(glm, 'glm-5.3-flash')));
});

test('all existing providers retain configurable OpenAI-compatible endpoints without fabricated fallback URLs', () => {
  for (const name of ['openai','deepseek','aliyun-bailian','qwen','zhipu','ollama','gemini','siliconflow','local']) {
    assert(providerTypes.some(p => p.name === name));
    assert.equal(resolveProvider(config('http://localhost:11434/v1', {}, name)).endpoint('chat'), 'http://localhost:11434/v1/chat/completions');
  }
  assert.throws(() => new ModelRuntime(config('')));
  assert.throws(() => new ModelRuntime(config('https://test-only-credential@example.com/v1')));
});

test('native Bailian rerank and explicit plural reranks use the configured endpoint and documented body', async () => {
  const app = await server((_req, res) => json(res, { output: { results: [{ index: 0, relevance_score: 0.8 }] }, usage: { total_tokens: 2 } }));
  try {
    const native = `${app.url}/services/rerank/text-rerank/text-rerank`;
    await new ModelRuntime(config(native, {}, 'aliyun-bailian')).rerank('q', ['a']);
    assert.equal(app.requests[0].url, '/v1/services/rerank/text-rerank/text-rerank');
    assert.deepEqual(app.requests[0].body, { model: 'model', input: { query: 'q', documents: ['a'] }, parameters: { top_n: 1 } });
    await assert.rejects(new ModelRuntime(config(native)).complete(messages), (e: any) => e.code === 'model_configuration_invalid');
    await new ModelRuntime(config(`${app.url}/reranks`)).rerank('q', ['a']);
    assert.equal(app.requests[1].url, '/v1/reranks');
  } finally { await app.close(); }
});

test('invalid model input, policies and numeric configuration fail before HTTP dispatch', async () => {
  const app = await server((_req, res) => json(res, response));
  try {
    const runtime = new ModelRuntime(config(app.url));
    for (const options of [{ maxTokens: 0 }, { temperature: NaN }, { timeoutMs: -1 }, { thinking: { mode: 'on' } }]) {
      await assert.rejects(runtime.complete(messages, options), ModelRuntimeError);
    }
    await assert.rejects(runtime.complete([]), ModelRuntimeError);
    await assert.rejects(runtime.embed(['']), ModelRuntimeError);
    await assert.rejects(runtime.embed(['text']), (e: any) => e.code === 'model_configuration_invalid');
    await assert.rejects(runtime.vision('file:///private/image', 'q'), ModelRuntimeError);
    await assert.rejects(runtime.vision('https://example.com/image', ''), ModelRuntimeError);
    assert.equal(app.requests.length, 0);
    for (const parameters of [{ dimension: -1 }, { timeout: 0 }, { timeoutMs: 'oops' }, { thinking: 'bad' }]) {
      assert.throws(() => new ModelRuntime(config(app.url, parameters)), ModelRuntimeError);
    }
    for (const url of ['ftp://example.com', 'https://example.com/v1?api_key=secret', 'https://example.com/v1#secret', 'not a url']) {
      assert.throws(() => new ModelRuntime(config(url)), ModelRuntimeError);
    }
  } finally { await app.close(); }
});

test('rate limit, invalid usage, malformed JSON and missing completion shape are failures with one request', async () => {
  for (const payload of [{ choices: [] }, { choices: [{ message: { content: 'x' } }] }, { ...response, usage: { prompt_tokens: -1 } },
    { ...response, usage: { prompt_tokens: Number.MAX_SAFE_INTEGER, completion_tokens: Number.MAX_SAFE_INTEGER } }]) {
    const app = await server((_req, res) => json(res, payload));
    try { await assert.rejects(new ModelRuntime(config(app.url)).complete(messages), ModelRuntimeError); assert.equal(app.requests.length, 1); }
    finally { await app.close(); }
  }
  const app = await server((_req, res) => { res.statusCode = 429; res.setHeader('Retry-After', '0'); res.end('test-only-credential'); });
  try { await assert.rejects(new ModelRuntime(config(app.url)).complete(messages), (e: any) => e.code === 'model_http_error' && e.status === 429); assert.equal(app.requests.length, 1); }
  finally { await app.close(); }
  const malformed = await server((_req, res) => { res.end('test-only-credential'); });
  try { await assert.rejects(new ModelRuntime(config(malformed.url)).complete(messages), (e: any) => e.code === 'model_response_invalid' && !String(e).includes('test-only-credential')); }
  finally { await malformed.close(); }
});

test('stream done marker alone and unterminated events cannot claim a completed generation', async () => {
  for (const content of ['data: [DONE]\n\n', 'data: {"choices":[{"delta":{"content":"x"},"finish_reason":"stop"}]}', 'event: error\ndata: secret\n\n']) {
    const app = await server((_req, res) => { res.setHeader('Content-Type', 'text/event-stream'); res.end(content); });
    try { await assert.rejects(collect(new ModelRuntime(config(app.url)).chat(messages)), ModelRuntimeError); }
    finally { await app.close(); }
  }
});

test('independent calls share no cancellation state and a cloned configuration preserves credentials', async () => {
  const app = await server(async (_req, res, body) => { if (body.messages[0].content === 'slow') await delay(100); json(res, response); });
  try {
    const cfg = config(app.url); const runtime = new ModelRuntime(cfg); cfg.parameters.api_key = 'changed';
    const controller = new AbortController();
    const slow = runtime.complete([{ role: 'user', content: 'slow' }], { signal: controller.signal });
    const fast = runtime.complete(messages);
    controller.abort(); await assert.rejects(slow, ModelRuntimeError); assert.equal((await fast).content, 'answer');
    assert(app.requests.every(request => request.authorization === 'Bearer test-only-credential'));
    assert(!JSON.stringify(runtime).includes('test-only-credential'));
  } finally { await app.close(); }
});

test('JSON body timeout and abruptly closed transport fail safely without automatic replay', async () => {
  const hanging = await server((_req, res) => { res.setHeader('Content-Type', 'application/json'); res.write('{'); });
  try { await assert.rejects(new ModelRuntime(config(hanging.url)).complete(messages, { timeoutMs: 30 }), (e: any) => e.code === 'model_timeout'); assert.equal(hanging.requests.length, 1); }
  finally { await hanging.close(); }
  const disconnected = await server((_req, res) => res.destroy(new Error('test-only-credential')));
  try { await assert.rejects(new ModelRuntime(config(disconnected.url)).complete(messages), (e: any) => e.code === 'model_network_error' && e.resultUnknown && !String(e).includes('test-only-credential')); assert.equal(disconnected.requests.length, 1); }
  finally { await disconnected.close(); }
});

test('timeouts outside the Node timer range are rejected before issuing a request', async () => {
  const app = await server((_req, res) => json(res, response));
  try {
    await assert.rejects(new ModelRuntime(config(app.url)).complete(messages, { timeoutMs: 2 ** 31 }), ModelRuntimeError);
    assert.throws(() => new ModelRuntime(config(app.url, { timeout: Number.MAX_SAFE_INTEGER })), ModelRuntimeError);
    assert.equal(app.requests.length, 0);
  } finally { await app.close(); }
});

test('thinking validation rejects nonobject policies, unknown fields and an explicit null mode', () => {
  const cap = capability('https://open.bigmodel.cn/api/paas/v4', 'glm-5.3-flash');
  for (const value of [true, 'default', [], { mode: null }, { mode: 'on', effort: 'unsupported' }, { mode: 'on', secret: 'test-only-credential' }]) {
    assert.throws(() => normalizeThinking(value as any, cap));
  }
});
