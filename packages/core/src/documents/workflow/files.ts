import { constants, closeSync, existsSync, fstatSync, fsyncSync, lstatSync, mkdirSync, openSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { createHash, randomUUID } from 'node:crypto';
import { dirname, isAbsolute, join, relative, resolve, sep } from 'node:path';
import { AppError } from '../../errors.js';
export const digest = (value: string | Uint8Array) => createHash('sha256').update(value).digest('hex');
export const fileError = (code: string, message: string): never => { throw new AppError(409, code, message); };
export function controlled(root: string, reference: string): string {
    if (!reference || isAbsolute(reference) || /[\\:\0]/.test(reference) || reference.split('/').some(p => !p || p === '.' || p === '..'))
        fileError('source_invalid', 'Invalid application file reference');
    const base = resolve(root), path = resolve(base, reference), rel = relative(base, path);
    if (rel.startsWith('..' + sep) || isAbsolute(rel))
        fileError('source_invalid', 'File reference escapes application storage');
    let cursor = base;
    for (const part of reference.split('/')) {
        cursor = join(cursor, part);
        if (existsSync(cursor) && lstatSync(cursor).isSymbolicLink())
            fileError('source_invalid', 'Application files cannot use symbolic links');
    }
    if (realpathSync(base) !== base)
        fileError('source_invalid', 'Application storage cannot use symbolic links');
    return path;
}
export function directory(root: string, reference: string): string {
    const path = controlled(root, reference);
    mkdirSync(path, { recursive: true, mode: 0o700 });
    if (realpathSync(path) !== path)
        fileError('source_invalid', 'Invalid application directory');
    return path;
}
export function readControlled(root: string, reference: string, hash: string, max = 128 * 1024 * 1024): Buffer {
    const path = controlled(root, reference);
    let fd: number;
    try {
        fd = openSync(path, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
    }
    catch {
        return fileError('source_unavailable', 'Application file is unavailable');
    }
    try {
        const info = fstatSync(fd);
        if (!info.isFile() || info.size > max)
            fileError('source_invalid', 'Application file is invalid or exceeds limits');
        const bytes = readFileSync(fd);
        if (bytes.length !== info.size || digest(bytes) !== hash)
            fileError('source_hash_mismatch', 'Application file content changed');
        return bytes;
    }
    finally {
        closeSync(fd);
    }
}
export function writeOwned(root: string, reference: string, bytes: Uint8Array): void {
    const path = controlled(root, reference);
    directory(root, relative(resolve(root), dirname(path)).split(sep).join('/'));
    const fd = openSync(path, 'wx', 0o600);
    try {
        writeFileSync(fd, bytes);
        fsyncSync(fd);
    }
    finally {
        closeSync(fd);
    }
}
export function removeOwned(root: string, reference: string, hash: string): void {
    try {
        readControlled(root, reference, hash);
        rmSync(controlled(root, reference));
    }
    catch { /* Changed/unavailable references are retained; never remove arbitrary files. */ }
}
export function temporary(root: string): {
    relative: string;
    path: string;
} { const reference = `.document-work/${randomUUID()}`; return { relative: reference, path: directory(root, reference) }; }
export function removeTemporary(root: string, reference: string): void { if (!/^\.document-work\/[a-f0-9-]{36}$/.test(reference))
    return; rmSync(controlled(root, reference), { recursive: true, force: true }); }
