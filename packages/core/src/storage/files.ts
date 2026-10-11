import { createHash, randomUUID } from 'node:crypto';
import { chmodSync, closeSync, copyFileSync, existsSync, fstatSync, lstatSync, mkdirSync, openSync, readSync, readdirSync, realpathSync, renameSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { basename, dirname, isAbsolute, join, relative, resolve } from 'node:path';
import { openNativeDatabase } from './database.js';

export interface FileRecord { path: string; size: number; sha256: string }
export const dataDirectories = ['media', '.settings', '.secrets', '.cache', 'archives'] as const;

/** Bounded memory, and reject a concurrent modification instead of reporting a false hash. */
export function fileHash(path: string): string {
  if (!lstatSync(path).isFile()) throw new Error('文件不是普通文件。');
  const fd = openSync(path, 'r');
  try {
    const before = fstatSync(fd);
    const buffer = Buffer.allocUnsafe(128 * 1024);
    const hash = createHash('sha256');
    for (;;) {
      const count = readSync(fd, buffer, 0, buffer.length, null);
      if (!count) break;
      hash.update(buffer.subarray(0, count));
    }
    const after = fstatSync(fd);
    if (before.size !== after.size || before.mtimeMs !== after.mtimeMs) throw new Error('文件在校验过程中发生变化，请重试。');
    return hash.digest('hex');
  } finally { closeSync(fd); }
}

export function safeDataPath(root: string, path: string): string {
  const name = path.replaceAll('\\', '/');
  if (!name || isAbsolute(name) || /^[A-Za-z]:/.test(name) || name.split('/').some((part) => !part || part === '.' || part === '..')) throw new Error('文件路径不在应用数据目录内。');
  const absoluteRoot = resolve(root);
  let current = absoluteRoot;
  if (existsSync(current) && lstatSync(current).isSymbolicLink()) throw new Error('数据目录不能是符号链接。');
  for (const part of name.split('/')) {
    current = join(current, part);
    if (existsSync(current) && lstatSync(current).isSymbolicLink()) throw new Error('数据文件不能是符号链接。');
  }
  return current;
}

export function listFiles(root: string, directories: readonly string[] = dataDirectories): string[] {
  const files: string[] = [];
  const walk = (path: string): void => {
    const absolute = safeDataPath(root, path);
    const info = lstatSync(absolute);
    if (info.isDirectory()) for (const name of readdirSync(absolute).sort()) walk(`${path}/${name}`);
    else if (info.isFile()) {
      if (!path.endsWith('-wal') && !path.endsWith('-shm') && !path.endsWith('.lock')) files.push(path);
    } else throw new Error('数据目录包含不支持的文件类型。');
  };
  for (const name of directories) if (existsSync(safeDataPath(root, name))) walk(name);
  return files.sort();
}

export function records(root: string, paths: readonly string[]): FileRecord[] {
  return [...paths].sort().map((path) => {
    const absolute = safeDataPath(root, path);
    return { path, size: statSync(absolute).size, sha256: fileHash(absolute) };
  });
}

export function verifyFiles(root: string, expected: readonly FileRecord[]): void {
  const seen = new Set<string>();
  for (const file of expected) {
    if (!file || typeof file.path !== 'string' || !Number.isSafeInteger(file.size) || file.size < 0 || typeof file.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(file.sha256) || seen.has(file.path)) throw new Error('备份文件清单无效。');
    seen.add(file.path);
    const path = safeDataPath(root, file.path);
    if (!existsSync(path) || statSync(path).size !== file.size || fileHash(path) !== file.sha256) throw new Error(`文件完整性校验失败：${file.path}`);
  }
}

export function copyVerifiedFiles(source: string, target: string, expected: readonly FileRecord[]): void {
  verifyFiles(source, expected);
  for (const file of expected) {
    const input = safeDataPath(source, file.path);
    const output = safeDataPath(target, file.path);
    mkdirSync(dirname(output), { recursive: true, mode: 0o700 });
    copyFileSync(input, output);
    chmodSync(output, 0o600);
  }
  verifyFiles(source, expected);
  verifyFiles(target, expected);
}

export function assertSeparateRoots(source: string, target: string): void {
  const input = realpathSync(source);
  const output = resolve(target);
  let ancestor = dirname(output);
  const missing: string[] = [];
  while (!existsSync(ancestor)) { missing.unshift(basename(ancestor)); ancestor = dirname(ancestor); }
  const destination = join(realpathSync(ancestor), ...missing, basename(output));
  for (const [left, right] of [[input, destination], [destination, input]]) {
    const rel = relative(left!, right!);
    if (!rel || (!rel.startsWith('..') && !isAbsolute(rel))) throw new Error('源与目标数据目录不能重叠。');
  }
}

export async function copyDataFiles(source: string, target: string, directories: readonly string[] = dataDirectories): Promise<FileRecord[]> {
  assertSeparateRoots(source, target);
  const paths = listFiles(source, directories);
  for (const path of paths) {
    const input = safeDataPath(source, path);
    const output = safeDataPath(target, path);
    mkdirSync(dirname(output), { recursive: true, mode: 0o700 });
    if (/\.sqlite3?$|\.db$/i.test(path)) {
      const db = openNativeDatabase(input, { readonly: true, fileMustExist: true });
      try { await db.backup(output); } finally { db.close(); }
    } else {
      const hash = fileHash(input);
      copyFileSync(input, output);
      if (fileHash(input) !== hash || fileHash(output) !== hash) throw new Error('复制文件期间内容发生变化。');
    }
    chmodSync(output, 0o600);
  }
  return records(target, paths);
}

/** A sibling staging directory plus exclusive lock; failure only removes our own artifacts. */
export class StagedDirectory {
  readonly path: string;
  readonly target: string;
  private readonly lockPath: string;
  private readonly lockFd: number;
  private published = false;

  constructor(target: string, source?: string) {
    this.target = resolve(target);
    if (source) assertSeparateRoots(source, this.target);
    if (existsSync(this.target) && (lstatSync(this.target).isSymbolicLink() || !lstatSync(this.target).isDirectory() || readdirSync(this.target).length)) throw new Error('目标数据目录已有内容，请选择新的空目录。');
    mkdirSync(dirname(this.target), { recursive: true, mode: 0o700 });
    this.lockPath = join(dirname(this.target), `.${basename(this.target)}.migration.lock`);
    try { this.lockFd = openSync(this.lockPath, 'wx', 0o600); }
    catch { throw new Error('该目标正在导入或恢复，请等待当前操作完成。'); }
    this.path = join(dirname(this.target), `.${basename(this.target)}.import-${randomUUID()}`);
    try { mkdirSync(this.path, { mode: 0o700 }); }
    catch (error) { closeSync(this.lockFd); rmSync(this.lockPath); throw error; }
  }

  publish(): void {
    if (existsSync(this.target)) {
      if (lstatSync(this.target).isSymbolicLink() || !lstatSync(this.target).isDirectory() || readdirSync(this.target).length) throw new Error('目标目录在操作期间已被占用。');
      rmSync(this.target);
    }
    renameSync(this.path, this.target);
    this.published = true;
  }

  finish(): void {
    if (!this.published) rmSync(this.path, { recursive: true, force: true });
    closeSync(this.lockFd);
    rmSync(this.lockPath, { force: true });
  }
}

export function writePrivateJson(path: string, value: unknown): void {
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
  writeFileSync(path, JSON.stringify(value, null, 2), { mode: 0o600, flag: 'wx' });
}
