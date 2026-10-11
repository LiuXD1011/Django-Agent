import assert from 'node:assert/strict';
import { createCipheriv, randomBytes } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync, mkdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

async function implementation() {
  const implementation = await import('../src/storage/credentials.js').catch(() => null);
  assert.ok(implementation, 'TypeScript credential vault must exist');
  return implementation;
}

function legacyCipher(key: Buffer, field: string, value: string) {
  const nonce = randomBytes(12);
  const cipher = createCipheriv('aes-256-gcm', key, nonce);
  cipher.setAAD(Buffer.from(field));
  return `enc:v1:${Buffer.concat([nonce, cipher.update(value), cipher.final(), cipher.getAuthTag()]).toString('base64url')}`;
}

test('credential vault reads legacy AES-GCM, encrypts nested credentials, and removes secrets from public config', async () => {
  const { CredentialVault, publicParameters } = await implementation();
  const root = mkdtempSync(join(tmpdir(), 'marlin-vault-'));
  try {
    mkdirSync(join(root, '.secrets'));
    const key = randomBytes(32);
    writeFileSync(join(root, '.secrets', 'credentials.key'), key);
    const vault = new CredentialVault(root);
    const original = { base_url: 'https://example.invalid/v1', api_key: 'test-only-not-real', nested: [{ password: 'sample-password', enabled: true }] };
    const sealed = vault.encrypt(original);
    assert.match(sealed.api_key, /^enc:v1:/);
    assert.equal(JSON.stringify(sealed).includes(original.api_key), false);
    assert.deepEqual(vault.decrypt(sealed), original);
    assert.equal(vault.decrypt({ api_key: legacyCipher(key, 'api_key', 'legacy-test-value') }).api_key, 'legacy-test-value');
    assert.deepEqual(publicParameters(original), { base_url: original.base_url, nested: [{ enabled: true }] });
    assert.deepEqual(vault.encrypt(sealed), sealed, 'valid existing ciphertext must not be double-encrypted');
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('missing, corrupted, wrong and mismatched-AAD keys fail without creating or overwriting key material', async () => {
  const { CredentialVault } = await implementation();
  const root = mkdtempSync(join(tmpdir(), 'marlin-vault-error-'));
  const keyPath = join(root, '.secrets', 'credentials.key');
  try {
    const vault = new CredentialVault(root);
    const encrypted = legacyCipher(randomBytes(32), 'api_key', 'test-secret');
    assert.throws(() => vault.decrypt({ api_key: encrypted }), /密钥|key/i);
    assert.equal(existsSync(keyPath), false, 'reading ciphertext cannot create a new key');
    mkdirSync(join(root, '.secrets'), { recursive: true });
    writeFileSync(keyPath, 'corrupt-key');
    assert.throws(() => vault.encrypt({ api_key: 'test-secret' }), /密钥|key/i);
    assert.equal(readFileSync(keyPath, 'utf8'), 'corrupt-key');
    const key = randomBytes(32);
    writeFileSync(keyPath, key);
    assert.throws(() => vault.decrypt({ api_key: encrypted }), /解密|decrypt/i);
    assert.throws(() => vault.decrypt({ password: legacyCipher(key, 'api_key', 'test-secret') }), /解密|decrypt/i);
    assert.deepEqual(readFileSync(keyPath), key);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('first credential write creates one persistent 32-byte key and later vault instances read it', async () => {
  const { CredentialVault } = await implementation();
  const root = mkdtempSync(join(tmpdir(), 'marlin-vault-first-'));
  try {
    const first = new CredentialVault(root);
    const sealed = first.encrypt({ api_key: 'test-secret' });
    const originalKey = readFileSync(join(root, '.secrets', 'credentials.key'));
    assert.equal(originalKey.length, 32);
    assert.equal(new CredentialVault(root).decrypt(sealed).api_key, 'test-secret');
    first.encrypt({ password: 'another-test-secret' });
    assert.deepEqual(readFileSync(join(root, '.secrets', 'credentials.key')), originalKey);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('actual Python AESGCM and strict padded base64 decrypt TypeScript ciphertext in both directions', async () => {
  const { CredentialVault } = await implementation();
  const root = mkdtempSync(join(tmpdir(), 'marlin-vault-python-'));
  try {
    const vault = new CredentialVault(root);
    const values = ['a', 'abc', 'eighteen-byte-text', '中文密钥🪸'];
    const sealed = values.map((api_key) => vault.encrypt({ api_key }).api_key);
    const script = join(root, 'compat.py');
    writeFileSync(script, 'import base64,json,os,sys\nfrom cryptography.hazmat.primitives.ciphers.aead import AESGCM\nx=json.load(sys.stdin)\na=AESGCM(bytes.fromhex(x["key"]))\nopened=[]\nsealed=[]\nfor item in x["sealed"]:\n raw=base64.b64decode(item[7:],altchars=b"-_",validate=True)\n opened.append(a.decrypt(raw[:12],raw[12:],b"api_key").decode())\nfor item in x["values"]:\n nonce=os.urandom(12)\n sealed.append("enc:v1:"+base64.urlsafe_b64encode(nonce+a.encrypt(nonce,item.encode(),b"api_key")).decode())\njson.dump({"opened":opened,"sealed":sealed},sys.stdout)\n');
    const result = JSON.parse(execFileSync(process.env.MARLIN_CRYPTO_TEST_PYTHON || 'python', [script], { input: JSON.stringify({ key: readFileSync(join(root, '.secrets', 'credentials.key')).toString('hex'), values, sealed }), encoding: 'utf8' })) as { opened: string[]; sealed: string[] };
    assert.deepEqual(result.opened, values);
    assert.deepEqual(result.sealed.map((api_key) => vault.decrypt({ api_key }).api_key), values);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
