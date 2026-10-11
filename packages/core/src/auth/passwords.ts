import { pbkdf2Sync, randomBytes, timingSafeEqual } from 'node:crypto';

/** Django's PBKDF2 encoded parameters are authoritative, including imported work factors. */
export function verifyPassword(raw: string, encoded: string): boolean {
  if (typeof raw !== 'string' || typeof encoded !== 'string') return false;
  const parts = encoded.split('$');
  if (parts.length !== 4) return false;
  const [algorithm, count, salt, expected] = parts;
  const digest = algorithm === 'pbkdf2_sha256' ? 'sha256' : algorithm === 'pbkdf2_sha1' ? 'sha1' : null;
  const iterations = Number(count);
  if (!digest || !salt || !expected || !/^\d+$/.test(count!) || !Number.isSafeInteger(iterations) || iterations < 1 || iterations > 10000000) return false;
  try {
    const actual = pbkdf2Sync(raw, salt, iterations, digest === 'sha256' ? 32 : 20, digest).toString('base64');
    const left = Buffer.from(actual); const right = Buffer.from(expected);
    return left.length === right.length && timingSafeEqual(left, right);
  } catch { return false; }
}

export function hashPassword(raw: string): string {
  const salt = randomBytes(18).toString('base64url');
  const iterations = 1000000; // Current Django PBKDF2 work factor; encoded for future migration.
  return `pbkdf2_sha256$${iterations}$${salt}$${pbkdf2Sync(raw, salt, iterations, 32, 'sha256').toString('base64')}`;
}
