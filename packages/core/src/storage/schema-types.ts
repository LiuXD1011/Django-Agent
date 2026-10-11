import type { Json } from '../contracts.js';

export interface ColumnDefinition {
  name: string;
  type: 'text' | 'integer' | 'real' | 'json' | 'boolean';
  nullable: boolean;
  primary: boolean;
  unique: boolean;
  encrypted: boolean;
  auto?: boolean;
  factory?: 'uuid' | 'now';
  defaultValue?: Json;
  reference?: { table: string; column: string };
  on_delete?: 'CASCADE' | 'SET NULL' | 'RESTRICT';
}

export interface TableDefinition {
  name: string;
  columns: ColumnDefinition[];
}
