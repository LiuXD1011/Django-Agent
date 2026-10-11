import type { Json, JsonObject } from '../contracts.js';
import { isSecretKey } from '../storage/credentials.js';

/** External services can reflect authentication. Saved credentials never become tool/search data. */
export function externalProjection<T extends JsonObject>(value: T, configuration: JsonObject): T {
  const secrets = new Set<string>();
  function collect(item: Json): void {
    if (!item || typeof item !== 'object') return;
    for (const [key, value] of Object.entries(item)) {
      if (isSecretKey(key) && typeof value === 'string' && value) {
        for (const candidate of [value, encodeURIComponent(value), Buffer.from(value).toString('base64')]) secrets.add(candidate);
      } else collect(value);
    }
  }
  collect(configuration);
  const ordered = [...secrets].sort((a, b) => b.length - a.length);
  const text = (input: string): string => ordered.reduce((output, secret) => secret.length >= 4 ? output.replaceAll(secret, '[redacted]') : output === secret ? '[redacted]' : output, input);
  function project(item: Json): Json {
    if (typeof item === 'string') return text(item);
    if (Array.isArray(item)) return item.map(project);
    if (item && typeof item === 'object') return Object.fromEntries(Object.entries(item).map(([key, value]) => [text(key), project(value)]));
    return item;
  }
  return project(value) as T;
}
