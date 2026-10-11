import type { ModelConfiguration, JsonObject } from '../contracts.js';

export class ModelRuntimeError extends Error {
  constructor(public readonly code: string, message: string, public readonly status?: number,
    public readonly resultUnknown = false) {
    super(message); this.name = 'ModelRuntimeError';
  }
}

export const providerTypes = [
  { name: 'openai', display_name: 'OpenAI Compatible', types: ['chat', 'embedding', 'rerank', 'vlm'] },
  { name: 'deepseek', display_name: 'DeepSeek', types: ['chat'] },
  { name: 'aliyun-bailian', display_name: '阿里云百炼', types: ['chat', 'embedding', 'rerank', 'vlm'] },
  { name: 'qwen', display_name: 'Qwen', types: ['chat', 'embedding'] },
  { name: 'zhipu', display_name: 'Zhipu', types: ['chat', 'embedding', 'rerank', 'vlm'] },
  { name: 'ollama', display_name: 'Ollama', types: ['chat', 'embedding', 'vlm'] },
  { name: 'local', display_name: '本地 OpenAI 兼容', types: ['chat', 'embedding', 'vlm'] },
  { name: 'gemini', display_name: 'Gemini', types: ['chat', 'embedding', 'vlm'] },
  { name: 'siliconflow', display_name: 'SiliconFlow', types: ['chat', 'embedding', 'rerank', 'vlm'] },
] as const;

export type ModelOperation = 'chat' | 'embedding' | 'rerank';
export interface ProviderConfiguration {
  baseUrl: string;
  model: string;
  timeoutMs: number;
  dimension?: number;
  thinking?: JsonObject;
  endpoint(operation: ModelOperation): string;
  headers(): Record<string, string>;
  rerankBody(query: string, documents: string[]): JsonObject;
}

function text(parameters: JsonObject, keys: string[]): string {
  for (const key of keys) {
    const value = parameters[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
}
function positiveInteger(value: unknown, fallback?: number): number | undefined {
  if (value === undefined || value === null || value === '') return fallback;
  const parsed = typeof value === 'string' ? Number(value) : value;
  if (typeof parsed !== 'number' || !Number.isSafeInteger(parsed) || parsed <= 0) {
    throw new ModelRuntimeError('model_configuration_invalid', 'Model numeric configuration must be a positive integer');
  }
  return parsed;
}

/** Credentials stay in a closure and are never returned as enumerable configuration properties. */
export function resolveProvider(configuration: ModelConfiguration): ProviderConfiguration {
  const parameters = configuration.parameters;
  const raw = text(parameters, ['base_url', 'baseURL']);
  const model = text(parameters, ['model']) || configuration.name;
  if (!raw || !model?.trim()) throw new ModelRuntimeError('model_not_configured', 'Model endpoint and model name are required');
  let url: URL;
  try { url = new URL(raw); } catch { throw new ModelRuntimeError('model_configuration_invalid', 'Model endpoint must be an HTTP URL'); }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) {
    throw new ModelRuntimeError('model_configuration_invalid', 'Model endpoint cannot contain credentials, query parameters or a fragment');
  }
  const key = text(parameters, ['api_key', 'apiKey', 'token']);
  const baseUrl = raw.replace(/\/+$/, '').replace(/\/(chat\/completions|embeddings|rerank|reranks)$/, '');
  // Explicit native Bailian endpoints retain their documented request shape.
  // https://help.aliyun.com/zh/model-studio/text-rerank-api
  const nativeRerank = /\/services\/rerank\/text-rerank(?:\/text-rerank)?$/.test(baseUrl);
  const explicitReranks = /\/reranks\/?$/.test(raw);
  const timeoutMs = positiveInteger(parameters.timeoutMs) ?? (positiveInteger(parameters.timeout, 60)! * 1000);
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs > 2 ** 31 - 1) {
    throw new ModelRuntimeError('model_configuration_invalid', 'Model timeout exceeds the supported timer range');
  }
  const dimension = positiveInteger(parameters.dimension);
  const thinking = parameters.thinking;
  if (thinking !== undefined && (!thinking || typeof thinking !== 'object' || Array.isArray(thinking))) {
    throw new ModelRuntimeError('model_configuration_invalid', 'Thinking configuration must be an object');
  }
  return {
    baseUrl, model: model.trim(), timeoutMs, dimension,
    thinking: thinking === undefined ? undefined : structuredClone(thinking as JsonObject),
    endpoint(operation) {
      if (operation === 'rerank' && nativeRerank) return baseUrl;
      if (operation === 'rerank' && explicitReranks) return raw.replace(/\/+$/, '');
      if (nativeRerank) throw new ModelRuntimeError('model_configuration_invalid', 'A native rerank endpoint cannot serve chat or embeddings');
      return `${baseUrl}/${operation === 'chat' ? 'chat/completions' : operation === 'embedding' ? 'embeddings' : 'rerank'}`;
    },
    headers(): Record<string, string> { return key ? { 'Content-Type': 'application/json', Authorization: `Bearer ${key}` } : { 'Content-Type': 'application/json' }; },
    rerankBody(query, documents): JsonObject {
      return nativeRerank ? { model: model.trim(), input: { query, documents }, parameters: { top_n: documents.length } }
        : { model: model.trim(), query, documents, top_n: documents.length };
    },
  };
}
