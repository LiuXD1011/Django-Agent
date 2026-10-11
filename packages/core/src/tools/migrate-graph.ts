import { constants, closeSync, fstatSync, lstatSync, openSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { parseArgs } from 'node:util';
import { AuthError, AuthService } from '../auth/index.js';
import type { AuthContext } from '../contracts.js';
import { AppError } from '../errors.js';
import { IntegrationService } from '../integrations/index.js';
import { SettingsService } from '../settings/settings.js';
import { CoreDatabase } from '../storage/database.js';
import { CredentialVault } from '../storage/credentials.js';
import { safeDataPath, writePrivateJson } from '../storage/files.js';
import { LegacyGraphMigration } from '../storage/graph-legacy.js';

const usage = 'migrate-graph.ts inspect|import --data-root PRIVATE_IMPORTED_COPY (--auth-file PRIVATE_0600_JSON|--login-stdin) [--summary SAFE_JSON] [--timeout-ms 5000]';

function privateInput(path: string): unknown {
  const absolute = resolve(path);
  if (!lstatSync(absolute).isFile()) throw new AppError(400, 'private_auth_file_required', 'Authentication input must be a private regular file');
  const fd = openSync(absolute, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
  try {
    const info = fstatSync(fd);
    if (!info.isFile() || info.size > 16384 || process.platform !== 'win32' && ((info.mode & 0o077) !== 0 || info.uid !== process.getuid!())) throw new AppError(400, 'private_auth_file_required', 'Authentication input must belong to the current user and allow no group or public access');
    try { return JSON.parse(readFileSync(fd, 'utf8')); } catch { throw new AppError(400, 'invalid_auth_input', 'Invalid private authentication input'); }
  } finally { closeSync(fd); }
}
async function loginInput(): Promise<unknown> {
  if (process.stdin.isTTY) throw new AppError(400, 'private_stdin_required', 'Pipe private login JSON through stdin; interactive echo is not supported');
  let input = '';
  for await (const bytes of process.stdin) {
    input += Buffer.from(bytes).toString('utf8');
    if (Buffer.byteLength(input) > 16384) throw new AppError(400, 'invalid_auth_input', 'Authentication input exceeds the size limit');
  }
  try { return JSON.parse(input); } catch { throw new AppError(400, 'invalid_auth_input', 'Invalid private authentication input'); }
}
function authenticate(auth: AuthService, value: unknown, login: boolean): AuthContext {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new AppError(400, 'invalid_auth_input', 'Invalid private authentication input');
  const input = value as Record<string, unknown>;
  if (input.tenant_id !== undefined && typeof input.tenant_id !== 'string') throw new AppError(400, 'invalid_auth_input', 'Tenant identities must be exact strings');
  const tenant = input.tenant_id as string | undefined;
  if (login) {
    if (Object.keys(input).some(key => !['login', 'password', 'tenant_id'].includes(key)) || typeof input.login !== 'string' || typeof input.password !== 'string') throw new AppError(400, 'invalid_auth_input', 'Provide an existing account login and password');
    const issued = auth.login({ login: input.login, password: input.password, deviceName: 'Private graph migration', clientType: 'desktop' });
    return tenant ? auth.authenticateAccess(issued.credentials.access, tenant) : issued.context;
  }
  if (Object.keys(input).some(key => !['mode', 'credential', 'tenant_id'].includes(key)) || typeof input.credential !== 'string' || !input.credential) throw new AppError(400, 'invalid_auth_input', 'Provide an existing private credential');
  if (input.mode === 'access') return auth.authenticateAccess(input.credential, tenant);
  if (input.mode === 'legacy_bearer') return auth.authenticateLegacyBearer(input.credential, tenant);
  if (input.mode === 'api_key') return auth.authenticateApiKey(input.credential, tenant);
  throw new AppError(400, 'invalid_auth_input', 'Unsupported private authentication mode');
}
async function main(): Promise<void> {
  const { positionals, values } = parseArgs({ allowPositionals: true, strict: true, options: { 'data-root': { type: 'string' }, 'auth-file': { type: 'string' }, 'login-stdin': { type: 'boolean' }, summary: { type: 'string' }, 'timeout-ms': { type: 'string' } } });
  const operation = positionals[0], root = values['data-root'];
  if (positionals.length !== 1 || !['inspect', 'import'].includes(operation ?? '') || !root || Boolean(values['auth-file']) === Boolean(values['login-stdin'])) throw new AppError(400, 'usage', usage);
  const timeoutMs = Number(values['timeout-ms'] ?? 5000);
  if (!Number.isInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 60000) throw new AppError(400, 'invalid_timeout', 'Timeout must be between 1 and 60000 milliseconds');
  // Never create an empty installation or open a legacy db.sqlite3 as the destination.
  if (!lstatSync(safeDataPath(root, 'marlin.sqlite3')).isFile()) throw new AppError(400, 'imported_copy_required', 'An existing private imported copy is required');
  const db = new CoreDatabase(root), auth = new AuthService(db), integrations = new IntegrationService(db, auth, new SettingsService(db, auth, new CredentialVault(db.dataRoot)));
  const controller = new AbortController(), cancel = () => controller.abort();
  process.on('SIGINT', cancel); process.on('SIGTERM', cancel);
  try {
    const context = authenticate(auth, values['auth-file'] ? privateInput(values['auth-file']) : await loginInput(), values['login-stdin'] === true);
    const migration = new LegacyGraphMigration(db, auth, integrations), started = performance.now(), options = { timeoutMs, signal: controller.signal };
    const result = operation === 'inspect' ? await migration.inspect(context, options) : await migration.import(context, options);
    const summary = { operation, ...result, duration_ms: performance.now() - started };
    if (values.summary) { writePrivateJson(resolve(values.summary), summary); process.stdout.write(`Completed ${operation}; safe summary saved.\n`); }
    else process.stdout.write(JSON.stringify(summary, null, 2) + '\n');
  } finally { process.removeListener('SIGINT', cancel); process.removeListener('SIGTERM', cancel); await integrations.close(); db.close(); }
}
main().catch((error: unknown) => {
  // Do not include native driver errors, endpoints, raw parameters, or private authentication data.
  const code = error instanceof AuthError || error instanceof AppError ? error.code : 'migration_failed';
  process.stderr.write(`Graph migration failed: ${code}\n`); process.exitCode = 1;
});
