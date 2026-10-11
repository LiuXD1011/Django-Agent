import type { Json } from '../contracts.js';

/** Node 22+ retains the original primitive lexeme in the reviver context. */
export function parseStoredJson(text: string): Json {
  return JSON.parse(text, (_key: string, value: unknown, context?: { source?: string }) => {
    if (typeof value !== 'number') return value;
    if (!Number.isFinite(value)) throw new Error('JSON 数值超出支持范围。');
    if (Number.isInteger(value) && !Number.isSafeInteger(value)) {
      if (!context?.source) throw new Error('当前运行环境无法保真解析 JSON 大整数。');
      return /^-?\d+$/.test(context.source) ? BigInt(context.source).toString() : context.source;
    }
    return value;
  }) as Json;
}
