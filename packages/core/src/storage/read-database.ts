import type BetterSqlite3 from 'better-sqlite3';
import { openNativeDatabase } from './database.js';
import { businessTable, decoded, normalized, type BindValue, type Row } from './row-codec.js';

export interface DatabaseReader {
  readonly path: string;
  readonly dataRoot: string;
  get<T extends Row = Row>(sql: string, ...parameters: BindValue[]): T | undefined;
  all<T extends Row = Row>(sql: string, ...parameters: BindValue[]): T[];
  read(name: string, id: BindValue): Row | undefined;
}

/** Trusted synchronous query connection; never initializes business storage. */
export class ReadDatabase implements DatabaseReader {
  readonly #sqlite: BetterSqlite3.Database;
  readonly #statements = new Map<string, BetterSqlite3.Statement<BindValue[]>>();
  constructor(readonly path: string, readonly dataRoot: string, options: { timeoutMs?: number } = {}) {
    this.#sqlite = openNativeDatabase(path, { readonly: true, fileMustExist: true, timeout: options.timeoutMs ?? 5000 });
    try {
      this.#sqlite.defaultSafeIntegers();
      if (this.#sqlite.pragma('journal_mode', { simple: true }) !== 'wal') throw new Error('只读查询要求已初始化的 WAL 数据库。');
      this.#sqlite.pragma('query_only=ON');
    } catch (error) { this.#sqlite.close(); throw error; }
  }
  private statement(sql: string): BetterSqlite3.Statement<BindValue[]> {
    // Some assigning PRAGMAs act during prepare, before native readonly can
    // reject the statement. Only audited read forms reach native preparation.
    if (!/^\s*(?:SELECT|WITH|VALUES)\b/i.test(sql)
      && !/^\s*EXPLAIN\s+(?:QUERY\s+PLAN\s+)?(?:SELECT|WITH|VALUES)\b/i.test(sql)
      && !/^\s*PRAGMA\s+(?:journal_mode|query_only|foreign_keys)\s*;?\s*$/i.test(sql)) throw new Error('只读连接仅接受只读查询。');
    const statement = this.#statements.get(sql) ?? this.#sqlite.prepare<BindValue[]>(sql);
    if (!statement.reader || !statement.readonly) throw new Error('只读连接仅接受只读查询。');
    this.#statements.delete(sql); this.#statements.set(sql, statement);
    if (this.#statements.size > 128) this.#statements.delete(this.#statements.keys().next().value!);
    return statement;
  }
  get<T extends Row = Row>(sql: string, ...parameters: BindValue[]): T | undefined {
    const value = this.statement(sql).get(...parameters);
    return value === undefined ? undefined : normalized(value) as T;
  }
  all<T extends Row = Row>(sql: string, ...parameters: BindValue[]): T[] {
    return this.statement(sql).all(...parameters).map(value => normalized(value) as T);
  }
  read(name: string, id: BindValue): Row | undefined {
    const table = businessTable(name), primary = table.columns.find(column => column.primary)!;
    const row = this.get(`SELECT * FROM "${name}" WHERE "${primary.name}"=?`, id);
    return row ? decoded(table, row) : undefined;
  }
  snapshot<T>(work: () => T): T {
    if (work.constructor.name === 'AsyncFunction') throw new Error('数据库事务必须同步执行。');
    return this.#sqlite.transaction(() => {
      const result = work();
      if (result && typeof (result as { then?: unknown }).then === 'function') throw new Error('数据库事务必须同步执行。');
      return result;
    }).deferred();
  }
  close(): void { this.#statements.clear(); if (this.#sqlite.open) this.#sqlite.close(); }
}
