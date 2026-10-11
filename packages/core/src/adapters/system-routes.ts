import type { CoreApplication } from '../application.js';
import { AppError } from '../errors.js';
import { SystemDiagnostics, type SystemDiagnosticOptions } from '../system/diagnostics.js';

export function registerSystemRoutes(app: CoreApplication, options: SystemDiagnosticOptions = {}): SystemDiagnostics {
  const diagnostics = new SystemDiagnostics(app.database, app.auth, app.vault, app.models, options);
  const check = (body: Record<string, unknown>, parser: boolean) => {
    const names = parser ? ['engine', 'name', 'parser_engine'] : ['engine', 'name', 'provider', 'storage_engine'];
    const allowed = parser ? ['builtin'] : ['local', 'sqlite', 'sqlite-vec'];
    if (Object.entries(body).some(([key, value]) => !names.includes(key) || typeof value !== 'string' || !allowed.includes(value))) throw new AppError(400, 'diagnostic_parameters_unsupported', '诊断仅检查当前应用拥有的解析器和存储，不接受外部地址、路径或命令。');
  };
  app.route('GET', '/api/v1/system/parser-engines', c => diagnostics.parserEngines(c.auth, { signal: c.signal }));
  app.route('POST', '/api/v1/system/parser-engines/check', c => { check(c.body, true); return diagnostics.parserEngines(c.auth, { signal: c.signal }); });
  app.route('GET', '/api/v1/system/storage-engine-status', c => diagnostics.storageStatus(c.auth));
  app.route('POST', '/api/v1/system/storage-engine-check', c => { check(c.body, false); return diagnostics.storageStatus(c.auth); });
  app.route('GET', '/api/v1/system/info', c => diagnostics.info(c.auth));
  return diagnostics;
}
