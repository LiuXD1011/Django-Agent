import { randomUUID } from 'node:crypto';
import { existsSync, mkdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import BetterSqlite3 from 'better-sqlite3';
import { drizzle } from 'drizzle-orm/better-sqlite3';
import * as sqliteVec from 'sqlite-vec';
import type { Json } from '../contracts.js';
import { migrate } from './migrations.js';
import * as schema from './schema.js';
import { tableDefinitions } from './schema-manifest.js';
import type { ColumnDefinition, TableDefinition } from './schema-types.js';
import { parseStoredJson } from './json.js';

export type Row = Record<string, Json>;
export type BindValue = string | number | bigint | Buffer | null;

const require = createRequire(import.meta.url);
const localBinding = join(dirname(require.resolve('better-sqlite3/package.json')), 'build', 'Release', 'better_sqlite3.node');

export function openNativeDatabase(path: string, options: BetterSqlite3.Options = {}): BetterSqlite3.Database {
  return new BetterSqlite3(path, { timeout: 5000, ...options, ...(existsSync(localBinding) ? { nativeBinding: localBinding } : {}) });
}

function validateJson(value: unknown, ancestors = new Set<object>()): void {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return;
  if (typeof value === 'number' && Number.isFinite(value)) return;
  if (!value || typeof value !== 'object' || ancestors.has(value)) throw new Error('Invalid JSON value');
  if (!Array.isArray(value) && Object.getPrototypeOf(value) !== Object.prototype && Object.getPrototypeOf(value) !== null) throw new Error('Invalid JSON object');
  ancestors.add(value);
  for (const item of Array.isArray(value) ? value : Object.values(value)) validateJson(item, ancestors);
  ancestors.delete(value);
}

function normalized(value: unknown): Json {
  if (typeof value === 'bigint') return value <= BigInt(Number.MAX_SAFE_INTEGER) && value >= BigInt(Number.MIN_SAFE_INTEGER) ? Number(value) : value.toString();
  if (value === null || typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return value;
  if (Array.isArray(value)) return value.map(normalized);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([name, item]) => [name, normalized(item)]));
  throw new Error('数据库返回了不支持的值。');
}

function encoded(column: ColumnDefinition, value: unknown): BindValue {
  if (value === null) {
    if (!column.nullable) throw new Error(`字段 ${column.name} 不允许为空。`);
    return null;
  }
  if (column.type === 'json') {
    try {
      const parsed = typeof value === 'string' ? parseStoredJson(value) : value;
      validateJson(parsed);
      const result = JSON.stringify(parsed);
      if (result === undefined) throw new Error();
      return result;
    } catch { throw new Error(`字段 ${column.name} 必须是有效 JSON。`); }
  }
  if (column.type === 'boolean') {
    if (value !== true && value !== false && value !== 0 && value !== 1 && value !== 0n && value !== 1n) throw new Error(`字段 ${column.name} 必须是布尔值。`);
    return value === true || value === 1 || value === 1n ? 1 : 0;
  }
  if (column.type === 'integer') {
    if (typeof value === 'bigint') return value;
    if (typeof value === 'string' && /^-?\d+$/.test(value)) return BigInt(value);
    if (typeof value === 'number' && Number.isSafeInteger(value)) return value;
    throw new Error(`字段 ${column.name} 必须是精度安全的整数。`);
  }
  if (column.type === 'real') {
    if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error(`字段 ${column.name} 必须是有限数值。`);
    return value;
  }
  if (typeof value !== 'string') throw new Error(`字段 ${column.name} 必须是字符串。`);
  return value;
}

function defaults(column: ColumnDefinition): unknown {
  if (column.factory === 'uuid') return randomUUID();
  if (column.factory === 'now') return new Date().toISOString();
  if ('defaultValue' in column) return column.defaultValue;
  if (column.nullable) return null;
  if (column.primary) throw new Error(`字段 ${column.name} 必填。`);
  if (column.type === 'json') return {};
  if (column.type === 'text') return '';
  return 0;
}

/** The core process owns this synchronous write connection; workers return data only. */
export class CoreDatabase {
  readonly path: string;
  readonly sqlite: BetterSqlite3.Database;
  readonly orm;
  private readonly tables = new Map(tableDefinitions.map((table) => [table.name, table]));
  private readonly statements = new Map<string, BetterSqlite3.Statement<BindValue[]>>();

  constructor(readonly dataRoot: string) {
    mkdirSync(dataRoot, { recursive: true, mode: 0o700 });
    this.path = join(dataRoot, 'marlin.sqlite3');
    this.sqlite = openNativeDatabase(this.path);
    try {
      this.sqlite.defaultSafeIntegers();
      this.sqlite.pragma('foreign_keys=ON');
      this.sqlite.pragma('journal_mode=WAL');
      this.sqlite.pragma('synchronous=NORMAL');
      sqliteVec.load(this.sqlite);
      migrate(this.sqlite);
      this.orm = drizzle(this.sqlite, { schema });
    } catch (error) {
      this.sqlite.close();
      throw error;
    }
  }

  private statement(sql: string): BetterSqlite3.Statement<BindValue[]> {
    const statement = this.statements.get(sql) ?? this.sqlite.prepare<BindValue[]>(sql);
    this.statements.delete(sql);
    this.statements.set(sql, statement);
    if (this.statements.size > 128) this.statements.delete(this.statements.keys().next().value!);
    return statement;
  }

  get<T extends Row = Row>(sql: string, ...parameters: BindValue[]): T | undefined {
    const value = this.statement(sql).get(...parameters);
    return value === undefined ? undefined : normalized(value) as T;
  }

  all<T extends Row = Row>(sql: string, ...parameters: BindValue[]): T[] {
    return this.statement(sql).all(...parameters).map((value) => normalized(value) as T);
  }

  run(sql: string, ...parameters: BindValue[]): BetterSqlite3.RunResult {
    return this.statement(sql).run(...parameters);
  }

  transaction<T>(work: () => T): T {
    if (work.constructor.name === 'AsyncFunction') throw new Error('数据库事务必须同步执行。');
    return this.sqlite.transaction(() => {
      const result = work();
      if (result && typeof (result as { then?: unknown }).then === 'function') throw new Error('数据库事务必须同步执行。');
      return result;
    }).immediate();
  }

  private table(name: string): TableDefinition {
    const table = this.tables.get(name);
    if (!table) throw new Error(`未知业务表 ${name}。`);
    return table;
  }

  private decoded(table: TableDefinition, row: Row): Row {
    return Object.fromEntries(Object.entries(row).map(([name, value]) => {
      const column = table.columns.find((item) => item.name === name);
      if (column?.type === 'json' && typeof value === 'string') return [name, parseStoredJson(value)];
      if (column?.type === 'boolean' && value !== null) return [name, value === 1];
      return [name, value];
    }));
  }

  insert(name: string, values: Record<string, unknown>): Row {
    const table = this.table(name);
    if (Object.keys(values).some((key) => !table.columns.some((column) => column.name === key))) throw new Error(`表 ${name} 包含未知字段。`);
    const columns = table.columns.filter((column) => !(column.auto && values[column.name] === undefined));
    const bound = columns.map((column) => encoded(column, values[column.name] === undefined ? defaults(column) : values[column.name]));
    const result = this.run(`INSERT INTO "${name}" (${columns.map((column) => `"${column.name}"`).join(',')}) VALUES (${columns.map(() => '?').join(',')})`, ...bound);
    const primary = table.columns.find((column) => column.primary)!;
    const key = primary.auto && values[primary.name] === undefined ? result.lastInsertRowid : bound[columns.findIndex((column) => column.primary)];
    const row = this.get(`SELECT * FROM "${name}" WHERE "${primary.name}"=?`, key!);
    if (!row) throw new Error('数据库插入后未找到记录。');
    return this.decoded(table, row);
  }

  read(name: string, id: BindValue): Row | undefined {
    const table = this.table(name);
    const primary = table.columns.find((column) => column.primary)!;
    const row = this.get(`SELECT * FROM "${name}" WHERE "${primary.name}"=?`, id);
    return row ? this.decoded(table, row) : undefined;
  }

  update(name: string, id: BindValue, values: Record<string, unknown>): Row | undefined {
    const table = this.table(name);
    const primary = table.columns.find((column) => column.primary)!;
    const entries = Object.entries(values);
    if (entries.some(([key]) => !table.columns.some((column) => column.name === key) || key === primary.name)) throw new Error(`表 ${name} 包含未知或不可修改字段。`);
    if (!entries.length) return this.read(name, id);
    const parameters = entries.map(([key, value]) => encoded(table.columns.find((column) => column.name === key)!, value));
    this.run(`UPDATE "${name}" SET ${entries.map(([key]) => `"${key}"=?`).join(',')} WHERE "${primary.name}"=?`, ...parameters, id);
    return this.read(name, id);
  }

  async backup(destination: string): Promise<void> {
    await this.sqlite.backup(destination);
  }

  close(): void {
    this.statements.clear();
    if (this.sqlite.open) this.sqlite.close();
  }
}
