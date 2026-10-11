import { posix, win32 } from 'node:path';
import { AppError } from '../errors.js';

function invalid(): never { throw new AppError(503, 'python_environment_invalid', '可信 Python 运行环境配置不完整。'); }

/** Native runtime configuration only; never accept executable paths from renderer input. */
export function pythonWorkerEnv(pythonExecutable: string, source: NodeJS.ProcessEnv = process.env, platform: NodeJS.Platform = process.platform): NodeJS.ProcessEnv {
  const windows = platform === 'win32', paths = windows ? win32 : posix;
  const delimiter = windows ? ';' : ':';
  const absolute = (value: string): boolean => paths.isAbsolute(value) && (!windows || paths.parse(paths.normalize(value)).root !== '\\');
  if (typeof pythonExecutable !== 'string' || !absolute(pythonExecutable) || /[\x00-\x1f\x7f]/.test(pythonExecutable)) invalid();
  const directory = paths.dirname(pythonExecutable);
  if (directory.includes(delimiter)) invalid();
  const get = (name: string): string | undefined => {
    if (!windows) return source[name];
    const values = Object.entries(source).filter(([key, value]) => key.toLowerCase() === name.toLowerCase() && value !== undefined).map(([, value]) => value!);
    if (new Set(values).size > 1) invalid();
    return values[0];
  };
  const env: NodeJS.ProcessEnv = {};
  // Avoid developer PATH, provider credentials and Python/Django import overrides.
  // Canonical spelling also prevents duplicate case-insensitive Windows keys.
  for (const name of ['SystemRoot', 'WINDIR', 'ComSpec', 'TEMP', 'TMP', 'TMPDIR', 'USERPROFILE', 'LOCALAPPDATA', 'APPDATA', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TIKTOKEN_CACHE_DIR']) {
    const value = get(name); if (typeof value === 'string') env[name] = value;
  }
  if (windows) {
    const systemRoot = get('SystemRoot');
    if (!systemRoot || !absolute(systemRoot) || systemRoot.includes(delimiter) || /[\x00-\x1f\x7f]/.test(systemRoot)) invalid();
    env.SystemRoot = paths.normalize(systemRoot);
    env.PATH = [directory, paths.join(systemRoot, 'System32')].join(delimiter);
  } else env.PATH = [directory, '/usr/bin', '/bin'].join(delimiter);
  return { ...env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8', PYTHONNOUSERSITE: '1' };
}
