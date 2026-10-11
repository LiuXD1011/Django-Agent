import { createHash } from 'node:crypto';
import type { Json, JsonObject } from '../contracts.js';
import { AppError } from '../errors.js';

export const fail = (status: number, code: string, message: string): never => { throw new AppError(status, code, message); };
export function object(value: unknown): JsonObject { return value && typeof value === 'object' && !Array.isArray(value) ? value as JsonObject : {}; }
export function canonical(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical((value as JsonObject)[key])}`).join(',')}}`;
}
export const digest = (value: unknown) => createHash('sha256').update(canonical(value)).digest('hex');
export const now = () => new Date().toISOString();
export function text(value: unknown, max = 16384): string { if (typeof value !== 'string' || !value.trim() || Array.from(value).length > max) return fail(400, 'invalid_evaluation_input', 'Evaluation text must be nonempty and within the size limit'); return value.trim(); }
export const clone = <T extends Json>(value: T): T => structuredClone(value);
