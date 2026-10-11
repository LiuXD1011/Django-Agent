# Native settings and model configuration

`ModelConfigurationService(database, auth, vault)` and `SettingsService(database,
auth, vault)` use the existing `models`, `model_usage`, `tenants`,
`integration_configs`, `generic_resources` and `search_index_meta` tables. They do
not import Django, change the shared schema, or read the original application DB.

Model methods: `list/get/create/update/delete`, `credentials/updateCredentials/
clearCredential`, `thinking/updateThinking`, `providers`, `test`, and `usage`.
Every tenant call revalidates the authoritative principal using `AuthService`.
Writes and model tests require tenant owner/admin; global integration and startup
configuration require the real active system administrator from `auth.me()`.
Models soft delete; embedding changes mark affected existing indexes
`needs_rebuild` and preserve their generations and business records. Four role
types are KnowledgeQA, Embedding, Rerank, VLLM. Auxiliary text roles select the
default KnowledgeQA model. An unset context window projects 128000 tokens.

`configuration(ctx, idOrRole)` returns decrypted `ModelConfiguration`, and
`runtime(ctx, idOrRole)` constructs the actual `ModelRuntime`. These two methods
are trusted core interfaces and must never become renderer GET responses.
Normal GET responses exclude secret values and ciphertext, exposing only
configured state. Imported credential aliases are normalized. Empty, null and
`******` edits preserve saved credentials; clear methods explicitly remove or
empty them. Ciphertext is rejected as input. Changing endpoint origin (including
port or scheme) requires explicit replacement of every saved secret, including
nested provider authorization, or clearing it beforehand.

`recordUsage(ctx, configuration, usage, outcome)` is another trusted core-only
method, never an HTTP/IPC route. The caller must authorize the real request before
dispatch. Recording does not reauthorize after dispatch: revocation must not erase
the audit of an issued request. It still verifies that the retained model belongs
to the original tenant. Outcome contains scenario, success, durationMs, optional
errorCode, metadata, invocationId. Numeric counters and duration must be finite,
nonnegative safe integers; scenario/error are fixed identifiers. Only known
resource IDs, operation, numeric attempt/dimension, verified thinking fields and
result_unknown survive the metadata whitelist. Parameters, prompts and raw errors
are excluded. An invocation UUID is the record primary key; identical repeats
return the existing safe projection, and conflicting recorded content raises 409.
Without an invocation ID, the method generates a UUID. The caller should retain
an ID for each actual upstream invocation when retries of audit persistence are
possible; it must not assign a new ID to the same invocation.

Settings methods: `getKV/setKV/clearKVCredential`, `getIntegration/
updateIntegration/clearIntegrationCredential`, `langfuseCredentials`, and
`get/list/create/update/deleteProvider`. Provider credential methods are
`providerCredentials/updateProviderCredentials/clearProviderCredential`;
individual nested credential paths use dot notation. Provider resource types are
`mcp_services`, `web_search_providers`, `vector_stores`, `system_settings`.
Thinking PUT takes `{revision, role: 'model', policy: {mode, effort}}`; the SQLite
transaction compares and advances the workspace revision while preserving keys.

Model tests send one real bounded sample request for each supported role. A valid
1x1 PNG data URL is used for vision. Remote configurations require saved keys;
explicit local/Ollama configurations can perform a real anonymous request. Each
attempt records actual reported token counts, duration, success and a safe error
code in `model_usage`; unreported usage is zero. Tests do not return generated
content or credentials. No request is automatically replayed. `usage(ctx, query)`
returns the previous total/cache/by_type/by_model/by_scenario/daily/cache_series
shape, including day/hour/15m buckets and tenant filters. Bucket timestamps and
labels are explicitly UTC, unlike the legacy server's configured Django timezone.

`SettingsService.startup` is a `StartupConfiguration(dataRoot, {environ?})`.
`readStartupConfiguration(dataRoot)` reads and validates `.settings/startup.json`
without opening a DB. Startup writes synchronously merge, fsync and atomically
rename a unique 0600 temporary file in the single owning core; temporary files
are removed. Two independent owning cores writing the same data root are outside
this single-owner contract. Reads fail on invalid or oversized configuration.

The active native snapshot contains task_workers, sqlite_timeout, model_timeout,
log_level. `runTask(work)` enforces FIFO worker concurrency;
`applyDatabase(db)` applies real SQLite busy_timeout; models without either
timeoutMs or timeout use the active model_timeout.
`log(level, safeEvent)` writes only fixed event identifiers (for example
`worker.failed`), filters by the active log level, and rotates at 5MiB. It accepts
no exception messages, prompts, SQL, credentials or arbitrary payload. The root
application must call these worker/DB/log helpers for its owning runtime.

Environment precedence is MARLIN_TASK_WORKERS, MARLIN_SQLITE_TIMEOUT,
MARLIN_MODEL_TIMEOUT, MARLIN_LOG_LEVEL, with corresponding legacy aliases
APP_TASK_WORKERS, SQLITE_TIMEOUT, LLM_CHAT_MODEL_TIMEOUT, DJANGO_LOG_LEVEL.
Startup GET returns saved values, the active snapshot, restart_required and
field_support. Legacy debug/allowed_hosts/cors_origins/model_retries/no_proxy/
proxy_url fields remain stored and explicitly unapplied. They do not change
native HTTP security or silently enable proxies/retries. Supported changes take
effect after recreation of the owning runtime.

Verification (2026-10-10):

- Initial `node --import tsx --test test/settings.test.ts`: 8 red assertions for
  the absent independent domain, then 8 green.
- Additional red/green regressions covered fallback embedding invalidation,
  nested Authorization host changes, readable unsupported imported model rows,
  native startup persistence/effect, creation-order default selection and explicit
  provider/KV credential clearing.
- `node --import tsx --test test/settings.test.ts test/models.test.ts`: native
  SQLite and controlled local HTTP cover four roles, real usage, no-key refusal,
  sanitized failure, timeout, cancellation, retry isolation, private tenant scope,
  forged admin flags, credential preservation/encryption/clearing and index data
  preservation. 18 settings and 16 runtime tests pass. The audit test additionally
  proves revocation does not prevent recording, matching UUID repeats are
  idempotent, conflicting counts fail, and private metadata/nonfinite counts
  are rejected or removed. No remote paid request or original password/data
  mutation occurs.
- `npm run typecheck`: passed after correcting readonly provider catalog types.

Graph, Langfuse and provider external connection tests are deliberately pending
their actual integration adapters. `testIntegration/testProvider` return explicit
501 errors; saved configuration is not presented as a verified connection.
Environment-backed legacy models are not fabricated. Startup fs permissions and
atomic rename were exercised on Linux; Windows execution has not been verified.
