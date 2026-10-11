import type { CoreRequest, CoreResponse } from '../contracts.js';
import type { IpcOptions, IpcResponse } from '../adapters/ipc.js';
import { validateCoreRequest } from '../application.js';
import { AppError } from '../errors.js';
import { validateNativeLangfuseRequest, type NativeLangfuseRequest } from '../integrations/langfuse-login.js';

/** Private JSON protocol only. Native renderer IPC keeps its Uint8Array contract. */
export const desktopByteLimit = 64 * 1024 * 1024;
export interface DesktopBytes { encoding: 'base64'; size_bytes: number; data: string }
export type DesktopInput =
  | { type: 'invoke' | 'stream'; id: string; request: CoreRequest; options: IpcOptions }
  | { type: 'langfuse'; id: string; request: NativeLangfuseRequest }
  | { type: 'ack'; id: string; sequence: number }
  | { type: 'cancel'; id: string }
  | { type: 'shutdown' };

function invalid(): never { throw new AppError(400, 'invalid_desktop_wire', '桌面私有进程协议不正确。'); }
function record(value: unknown, fields: readonly string[]): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Object.getPrototypeOf(value) !== Object.prototype || Object.keys(value).some(key => !fields.includes(key))) invalid();
  return value as Record<string, unknown>;
}
function identifier(value: unknown): asserts value is string {
  if (typeof value !== 'string' || !value || value.length > 200 || /[\x00-\x1f\x7f]/.test(value)) invalid();
}
export function encodeDesktopBytes(bytes: Uint8Array): DesktopBytes {
  if (!(bytes instanceof Uint8Array)) invalid();
  if (bytes.byteLength > desktopByteLimit) throw new AppError(413, 'desktop_bytes_too_large', '桌面传输文件超过限制。');
  return { encoding: 'base64', size_bytes: bytes.byteLength, data: Buffer.from(bytes.buffer, bytes.byteOffset, bytes.byteLength).toString('base64') };
}
export function decodeDesktopBytes(input: unknown): Uint8Array {
  const value = record(input, ['encoding', 'size_bytes', 'data']);
  if (value.encoding !== 'base64' || !Number.isSafeInteger(value.size_bytes) || Number(value.size_bytes) < 0 || typeof value.data !== 'string') invalid();
  if (Number(value.size_bytes) > desktopByteLimit || value.data.length > 4 * Math.ceil(desktopByteLimit / 3)) throw new AppError(413, 'desktop_bytes_too_large', '桌面传输文件超过限制。');
  if (value.data.length !== 4 * Math.ceil(Number(value.size_bytes) / 3) || !/^[A-Za-z0-9+/]*={0,2}$/.test(value.data)) invalid();
  const bytes = Buffer.from(value.data, 'base64');
  if (bytes.length !== value.size_bytes || bytes.toString('base64') !== value.data) invalid();
  return new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength);
}
function options(input: unknown): IpcOptions {
  const value = record(input === undefined ? {} : input, ['tenantId', 'upload']);
  if (value.tenantId !== undefined && (typeof value.tenantId !== 'string' || !value.tenantId || value.tenantId.length > 128)) invalid();
  const result: IpcOptions = typeof value.tenantId === 'string' ? { tenantId: value.tenantId } : {};
  if (value.upload !== undefined) {
    const file = record(value.upload, ['name', 'bytes']);
    if (typeof file.name !== 'string' || !file.name || ['.', '..'].includes(file.name) || /[\x00-\x1f\x7f/\\]/.test(file.name) || Buffer.byteLength(file.name) > 255) invalid();
    result.upload = { name: file.name, bytes: decodeDesktopBytes(file.bytes) };
  }
  return result;
}
export function decodeDesktopInput(input: unknown): DesktopInput {
  const value = record(input, ['type', 'id', 'request', 'options', 'sequence']);
  if (value.type === 'shutdown') { record(input, ['type']); return { type: 'shutdown' }; }
  identifier(value.id);
  if (value.type === 'cancel') { record(input, ['type', 'id']); return { type: 'cancel', id: value.id }; }
  if (value.type === 'ack') {
    record(input, ['type', 'id', 'sequence']);
    if (!Number.isSafeInteger(value.sequence) || Number(value.sequence) < 0) invalid();
    return { type: 'ack', id: value.id, sequence: Number(value.sequence) };
  }
  if (value.type === 'langfuse') {
    record(input, ['type', 'id', 'request']); validateNativeLangfuseRequest(value.request);
    if (value.request.id !== value.id) invalid();
    return { type: 'langfuse', id: value.id, request: value.request };
  }
  if (value.type !== 'invoke' && value.type !== 'stream') invalid();
  record(input, ['type', 'id', 'request', 'options']);
  record(value.request, ['protocol', 'id', 'method', 'path', 'body']);
  validateCoreRequest(value.request);
  if (value.request.id !== value.id) invalid();
  if (Buffer.byteLength(JSON.stringify(value.request)) > 2 * 1024 * 1024) throw new AppError(413, 'body_too_large', '请求正文超过限制。');
  return { type: value.type, id: value.id, request: value.request, options: options(value.options) };
}
export function encodeDesktopResponse(response: IpcResponse | CoreResponse): object {
  const value = record(response, ['protocol', 'id', 'status', 'body', 'binary']);
  const output = { protocol: response.protocol, id: response.id, status: response.status, body: response.body };
  if (value.binary === undefined) return output;
  const file = record(value.binary, ['bytes', 'name', 'mimeType', 'sha256']);
  if (typeof file.name !== 'string' || typeof file.mimeType !== 'string' || typeof file.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(file.sha256)) invalid();
  return { ...output, binary: { bytes: encodeDesktopBytes(file.bytes as Uint8Array), name: file.name, mimeType: file.mimeType, sha256: file.sha256 } };
}
