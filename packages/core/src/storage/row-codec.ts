import type { Json } from '../contracts.js';
import { parseStoredJson } from './json.js';
import { tableDefinitions } from './schema-manifest.js';
import type { TableDefinition } from './schema-types.js';

export type Row = Record<string, Json>;
export type BindValue = string | number | bigint | Buffer | null;
const tables = new Map(tableDefinitions.map(table => [table.name, table]));

/** Native safe integers become JSON-safe numbers or exact decimal strings. */
export function normalized(value: unknown): Json {
  if (typeof value === 'bigint') return value <= BigInt(Number.MAX_SAFE_INTEGER) && value >= BigInt(Number.MIN_SAFE_INTEGER) ? Number(value) : value.toString();
  if (value === null || typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return value;
  if (Array.isArray(value)) return value.map(normalized);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([name, item]) => [name, normalized(item)]));
  throw new Error('数据库返回了不支持的值。');
}

export function businessTable(name: string): TableDefinition {
  const table = tables.get(name);
  if (!table) throw new Error(`未知业务表 ${name}。`);
  return table;
}

export function decoded(table: TableDefinition, row: Row): Row {
  return Object.fromEntries(Object.entries(row).map(([name, value]) => {
    const column = table.columns.find(item => item.name === name);
    if (column?.type === 'json' && typeof value === 'string') return [name, parseStoredJson(value)];
    if (column?.type === 'boolean' && value !== null) return [name, value === 1];
    return [name, value];
  }));
}
