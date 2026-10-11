import { createHash } from 'node:crypto';
import type BetterSqlite3 from 'better-sqlite3';
import { tableDefinitions } from './schema-manifest.js';
import type { ColumnDefinition } from './schema-types.js';

function literal(value: unknown): string {
  if (value === null) return 'NULL';
  if (typeof value === 'boolean') return value ? '1' : '0';
  if (typeof value === 'number') return String(value);
  const text = typeof value === 'string' ? value : JSON.stringify(value);
  return `'${text.replaceAll("'", "''")}'`;
}

function definition(column: ColumnDefinition): string {
  const type = column.type === 'integer' || column.type === 'boolean' ? 'INTEGER'
    : column.type === 'real' ? 'REAL' : 'TEXT';
  let result = `"${column.name}" ${type}`;
  if (column.primary) result += ` PRIMARY KEY${column.auto ? ' AUTOINCREMENT' : ''}`;
  else if (!column.nullable) result += ' NOT NULL';
  if (column.unique && !column.primary) result += ' UNIQUE';
  if ('defaultValue' in column) result += ` DEFAULT ${literal(column.defaultValue)}`;
  if (column.reference) {
    result += ` REFERENCES "${column.reference.table}"("${column.reference.column}") ON DELETE ${column.on_delete}`;
  }
  if (column.type === 'json') result += ` CHECK ("${column.name}" IS NULL OR json_valid("${column.name}"))`;
  if (column.type === 'boolean') result += ` CHECK ("${column.name}" IN (0,1)${column.nullable ? ` OR "${column.name}" IS NULL` : ''})`;
  return result;
}

const businessSql = tableDefinitions.map((table) => {
  const columns = table.columns.map(definition);
  if (table.name === 'tenants') {
    columns.push("CONSTRAINT tenant_personal_owner_kind CHECK ((space_type='legacy' AND personal_owner_id IS NULL) OR (space_type='personal' AND personal_owner_id IS NOT NULL))");
  }
  return `CREATE TABLE "${table.name}" (${columns.join(',\n')});`;
}).join('\n');

const indexesSql = `
CREATE UNIQUE INDEX uniq_active_personal_owner ON tenants(personal_owner_id) WHERE space_type='personal' AND status='active' AND deleted_at IS NULL;
CREATE UNIQUE INDEX tenant_members_identity ON tenant_members(user_id,tenant_id);
CREATE UNIQUE INDEX uniq_active_kb_file_hash_name ON knowledges(knowledge_base_id,file_hash,file_name) WHERE deleted_at IS NULL AND type='file' AND file_hash>'' AND file_name>'';
CREATE UNIQUE INDEX semantic_cache_unique_key ON semantic_chunk_cache(content_hash,model_signature,algorithm_version,window_size,percentile);
CREATE UNIQUE INDEX stream_event_message_offset_unique ON stream_events(message_id,offset);
CREATE UNIQUE INDEX session_event_sequence_unique ON session_events(session_id,seq);
CREATE UNIQUE INDEX uniq_active_context_snapshot ON context_snapshots(session_id,mode) WHERE is_active=1;
CREATE UNIQUE INDEX actor_identity ON agent_actors(session_id,actor_id);
CREATE UNIQUE INDEX tag_identity ON knowledge_tags(tenant_id,knowledge_base_id,name);
CREATE UNIQUE INDEX wiki_page_identity ON wiki_pages(knowledge_base_id,slug);
CREATE INDEX models_tenant_type ON models(tenant_id,type);
CREATE INDEX knowledge_base_space ON knowledge_bases(tenant_id,deleted_at);
CREATE INDEX document_space_library ON knowledges(tenant_id,knowledge_base_id,deleted_at);
CREATE INDEX chunks_space_library ON chunks(tenant_id,knowledge_base_id,knowledge_id,is_enabled);
CREATE INDEX chunks_parent ON chunks(context_parent_id);
CREATE INDEX chunks_media_parent ON chunks(media_parent_id);
CREATE INDEX session_user_space ON sessions(tenant_id,user_id,deleted_at);
CREATE INDEX message_history ON messages(session_id,visible_to_user,created_at);
CREATE INDEX session_event_request ON session_events(session_id,request_id,seq);
CREATE INDEX stream_event_offsets ON stream_events(message_id,offset);
CREATE INDEX resource_space_type ON generic_resources(tenant_id,resource_type,deleted_at);
CREATE INDEX task_status_queue ON task_records(status,queue_name,lease_expires_at);
CREATE INDEX processing_attempt ON knowledge_processing_spans(knowledge_id,attempt);
CREATE INDEX model_usage_time ON model_usage(tenant_id,created_at);
CREATE INDEX wiki_log_time ON wiki_log_entries(knowledge_base_id,created_at);
CREATE INDEX device_user_state ON device_sessions(user_id,revoked_at);
CREATE INDEX refresh_device ON device_refresh_tokens(session_id,expires_at);
`;

const desktopSql = `
CREATE TABLE desktop_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL CHECK(json_valid(value)));
CREATE TABLE desktop_imports (fingerprint TEXT PRIMARY KEY, imported_at TEXT NOT NULL, source_version TEXT NOT NULL, manifest TEXT NOT NULL CHECK(json_valid(manifest)));
CREATE TABLE desktop_jobs (
  id TEXT PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
  user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
  request_id TEXT NOT NULL UNIQUE, kind TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('queued','running','completed','failed','cancelled','interrupted')),
  progress REAL NOT NULL DEFAULT 0 CHECK(progress>=0 AND progress<=1),
  payload TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(payload)), result TEXT CHECK(result IS NULL OR json_valid(result)),
  error TEXT NOT NULL DEFAULT '', attempt INTEGER NOT NULL DEFAULT 0,
  recovery_policy TEXT NOT NULL CHECK(recovery_policy IN ('safe','manual')),
  cancel_requested_at TEXT, started_at TEXT, finished_at TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE desktop_job_steps (
  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES desktop_jobs(id) ON DELETE CASCADE,
  attempt INTEGER NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL,
  data TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(data)), started_at TEXT, finished_at TEXT,
  UNIQUE(job_id,attempt,name)
);
CREATE TABLE desktop_job_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES desktop_jobs(id) ON DELETE CASCADE,
  seq INTEGER NOT NULL, type TEXT NOT NULL, data TEXT NOT NULL CHECK(json_valid(data)), created_at TEXT NOT NULL,
  UNIQUE(job_id,seq)
);
CREATE INDEX desktop_job_queue ON desktop_jobs(status,created_at);
CREATE VIRTUAL TABLE chunks_fts USING fts5(content, tokenize='trigram');
CREATE TABLE search_index_meta (
  id TEXT PRIMARY KEY, tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
  model_signature TEXT NOT NULL, dimension INTEGER NOT NULL CHECK(dimension>0),
  generation TEXT NOT NULL, status TEXT NOT NULL, updated_at TEXT NOT NULL
);
`;

const migrationSql = businessSql + indexesSql + desktopSql;
const checksum = createHash('sha256').update(migrationSql).digest('hex');

/** Only our versioned SQL runs here. Legacy Django data migrations are never executed. */
export function migrate(database: BetterSqlite3.Database): void {
  database.exec('CREATE TABLE IF NOT EXISTS desktop_schema_versions(version INTEGER PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)');
  const current = database.prepare('SELECT version,checksum FROM desktop_schema_versions ORDER BY version').all() as Array<{ version: number | bigint; checksum: string }>;
  if (current.some((entry) => Number(entry.version) > 1)) throw new Error('数据库版本比当前应用更新，请使用对应版本。');
  if (current.length) {
    if (current[0]?.checksum !== checksum) throw new Error('数据库迁移校验不一致，请恢复备份或使用正确版本。');
    return;
  }
  database.transaction(() => {
    database.exec(migrationSql);
    database.prepare('INSERT INTO desktop_schema_versions(version,checksum,applied_at) VALUES(1,?,?)').run(checksum, new Date().toISOString());
  }).immediate();
}
