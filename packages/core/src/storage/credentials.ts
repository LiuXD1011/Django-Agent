import { createCipheriv, createDecipheriv, randomBytes } from 'node:crypto';
import { closeSync, constants, existsSync, fsyncSync, lstatSync, mkdirSync, openSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import type { Json } from '../contracts.js';

const PREFIX = 'enc:v1:';
const SECRET_KEYS = new Set([
  'api_key', 'apikey', 'secret_key', 'app_secret', 'access_key', 'access_token',
  'token', 'password', 'private_key', 'client_secret', 'secret', 'webhook_secret',
  'public_key', 'authorization',
]);

export function isSecretKey(name: string): boolean {
  const normalized = name.toLowerCase();
  return SECRET_KEYS.has(normalized) || /_(api_key|token|secret)$/.test(normalized);
}

export function publicParameters<T extends Json>(value: T): T {
  if (Array.isArray(value)) return value.map((item) => publicParameters(item)) as T;
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value)
      .filter(([name]) => !isSecretKey(name))
      .map(([name, item]) => [name, publicParameters(item)])) as T;
  }
  return value;
}

/** Stored secrets remain inside the core. Reading never creates replacement key material. */
export class CredentialVault {
  readonly keyPath: string;

  constructor(private readonly dataRoot: string) {
    this.keyPath = join(dataRoot, '.secrets', 'credentials.key');
  }

  private key(create: boolean): Buffer {
    if (!existsSync(this.keyPath) && !create) {
      throw new Error('凭据加密密钥缺失，请恢复原始密钥。');
    }
    if (create && !existsSync(this.keyPath)) {
      mkdirSync(join(this.dataRoot, '.secrets'), { recursive: true, mode: 0o700 });
      let fd: number;
      try {
        fd = openSync(this.keyPath, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL, 0o600);
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== 'EEXIST') throw error;
        return this.key(false);
      }
      try {
        writeFileSync(fd, randomBytes(32));
        fsyncSync(fd);
      } finally { closeSync(fd); }
    }
    if (!lstatSync(this.keyPath).isFile()) throw new Error('凭据加密密钥不是正常文件，请恢复原始密钥。');
    const key = readFileSync(this.keyPath);
    if (key.length !== 32) throw new Error('凭据加密密钥损坏，请恢复原始密钥。');
    return key;
  }

  encrypt<T extends Json>(value: T): T {
    return this.transform(value, true) as T;
  }

  decrypt<T extends Json>(value: T): T {
    return this.transform(value, false) as T;
  }

  private transform(value: Json, encrypt: boolean): Json {
    if (Array.isArray(value)) return value.map((item) => this.transform(item, encrypt));
    if (!value || typeof value !== 'object') return value;
    return Object.fromEntries(Object.entries(value).map(([name, item]) => {
      if (!isSecretKey(name) || typeof item !== 'string' || !item) {
        return [name, this.transform(item, encrypt)];
      }
      if (item.startsWith(PREFIX)) {
        const plaintext = this.open(name, item); // Authenticate input before preserving it.
        return [name, encrypt ? item : plaintext];
      }
      if (!encrypt) return [name, item]; // Explicit legacy plaintext migration remains possible.
      const nonce = randomBytes(12);
      const cipher = createCipheriv('aes-256-gcm', this.key(true), nonce);
      cipher.setAAD(Buffer.from(name, 'utf8'));
      const ciphertext = Buffer.concat([cipher.update(item, 'utf8'), cipher.final()]);
      // Python's strict urlsafe-base64 decoder requires the original padding.
      return [name, PREFIX + Buffer.concat([nonce, ciphertext, cipher.getAuthTag()]).toString('base64').replaceAll('+', '-').replaceAll('/', '_')];
    }));
  }

  private open(name: string, value: string): string {
    const key = this.key(false);
    try {
      const encoded = value.slice(PREFIX.length);
      if (!/^[A-Za-z0-9_-]+={0,2}$/.test(encoded)) throw new Error();
      const raw = Buffer.from(encoded, 'base64url');
      if (raw.length < 28) throw new Error();
      const decipher = createDecipheriv('aes-256-gcm', key, raw.subarray(0, 12));
      decipher.setAAD(Buffer.from(name, 'utf8'));
      decipher.setAuthTag(raw.subarray(-16));
      const plaintext = Buffer.concat([decipher.update(raw.subarray(12, -16)), decipher.final()]);
      return new TextDecoder('utf-8', { fatal: true }).decode(plaintext);
    } catch {
      throw new Error('存储凭据无法解密，请恢复原始密钥。');
    }
  }
}
