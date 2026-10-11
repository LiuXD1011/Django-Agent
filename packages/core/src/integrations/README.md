# Optional integrations in the independent core

`new IntegrationService(database, auth, settings)` uses the existing encrypted
integration/provider records. It never imports Django, opens the original DB,
stores external credentials in renderer data, or keeps a SQLite transaction across
an await. Public methods revalidate the authoritative AuthService principal.

Connection methods return `{state: 'disabled' | 'not_configured' | 'connected', ...}`.
An attempted failure throws an AppError with a fixed code/message, without raw
upstream errors, URLs, credentials, prompts or headers. `testIntegration(ctx,
section, options?)` supports `neo4j` and `langfuse`, and requires the actual system
administrator. `testProvider(ctx, type, id, options?)` supports `mcp_services` and
`web_search_providers`, and requires tenant admin. Unsupported adapters explicitly
fail with 501 rather than pretending a saved configuration is connected.

`IntegrationCallOptions` is `{signal?: AbortSignal, timeoutMs?: number}`. Default
budget is 5 seconds, with an allowed range of 1–60000ms. The budget includes
connection/handshake, pagination, invocation and session termination. Requests
are limited to 256KiB, each response to 1MiB, and MCP cumulative responses to 4MiB.
HTTP requests stay on the configured origin and never follow redirects. Local
configured services are allowed. No request/model/tool is automatically replayed.
Saved key/host protection remains in SettingsService. Search adapters that send
keys require an explicit URL; switching a provider cannot silently move a saved
key to an inferred default host. External tool/search responses are filtered for
reflected saved credentials before publication.

`queryNeo4j(ctx, statement, parameters?, {database?, write?, ...options}?)` is a
trusted core-only arbitrary Cypher API, restricted to the actual system admin.
Do not expose it as a general tenant query HTTP/IPC route. A later tenant graph
adapter must own its tenant predicates and approved queries. Queries use the
official neo4j-driver 6.2.0, separate parameters, fetch size 100, a 1000-row/1MiB
result cap, and explicit session/driver cleanup. Both managed and auto-commit
retries are disabled. Integer values outside JS's safe range become decimal
strings. Configured bolt/neo4j protocols and TLS are handled by the official
driver; no Bolt port is guessed into an HTTP endpoint.

`queryScopedNeo4j(ctx, knowledgeBaseId, statement, parameters?, options?)` is
also trusted core-only, for the graph domain's fixed templates, never a general
HTTP/IPC Cypher route. It verifies active SQLite KB ownership, authoritative read
permission and document.write for write calls. Parameters must contain exact
tenant_id, knowledge_base_id, and namespace equal to SHA256 of
JSON.stringify([ctx.tenantId, knowledgeBaseId]). The graph caller owns every
Cypher predicate, document ID and generation fence; no string search pretends
to validate Cypher isolation. Parameters are validated and snapshotted before
await; permission, KB and saved configuration are checked before transport and
again before publication. Successful shape is `{state:'connected',records:[...]}`.

Each Neo4j invocation runs in an owned Worker thread. During an incomplete Bolt
handshake, the official driver's TCP connection timeout is already removed, and
driver.close alone may leave an incomplete connection outside its completed
connection pool. Aborting the owning Worker closes its pending sockets and
prevents late results. Normal completion still closes the session and driver.
Only the exact Worker is terminated, never other sockets/processes by name/port.
Compiled builds include `neo4j-worker.js` alongside the integration service.

`neo4j-http.ts` provides an explicit low-level Query API HTTP adapter. It requires
a separate trusted HTTP endpoint and is not selected by saved Bolt configuration
or exposed as a route. It validates Query API's `data.fields/data.values` and
checks query errors even when HTTP status is 202. Its local protocol fixture
does not establish a successful Neo4j Bolt database query.

`search(ctx, providerId, query, options?)` returns at most five
`{title,url,snippet,provider}` sources. DuckDuckGo uses the previous actual HTML
search; redirects in DuckDuckGo result links are decoded, markup removed, and
challenge/unsupported pages are failures rather than empty success. SearXNG uses
q/format=json, Google uses its configured Custom Search endpoint with cx/key,
and explicitly configured Bing-compatible servers use its subscription header
and response schema. The former official Bing Search endpoint was retired and
has no invented working default. Only HTTP(S) result URLs without userinfo are
accepted; credentials are not returned.

`listMcpTools(ctx, providerId, options?)` and `callMcpTool(ctx, providerId, name,
arguments, options?)` use the installed official MCP TypeScript SDK 1.32.1.
Streamable HTTP is the default; explicit `transport: 'sse'` retains SSE support.
These perform initialize/initialized, actual tools/list pagination or tools/call,
then DELETE the Streamable HTTP session when possible and always close the owned
client/transport. Duplicate cursors and oversized lists fail. Annotations and
tool output remain untrusted. Tool calls require tenant admin; callers must also
apply product approval policy for external side effects. Authorization and the
saved provider snapshot are checked again after handshake before invocation.
`untrusted: true` accompanies results. Old REST-only `/tools` services are not
presented as MCP protocol servers. Interactive third-party OAuth and stdio
launching are not implemented; authentication/unsupported transports fail.

`recordTrace(ctx, event, options?)` is a trusted core-only telemetry API, not an
HTTP/IPC route. `TraceEvent` contains a fixed name, traceId/spanId/optional
parentSpanId, actual startedAt/endedAt epoch milliseconds, success, optional
type/sessionId/metadata/ModelUsage/input/output. It sends actual OTLP HTTP/JSON to
Langfuse's `/api/public/otel/v1/traces` with ingestion-version 4, checked against
the current official API. IDs, timing, usage and partial rejection are validated.
Sampling is deterministic per trace ID so children inherit one root decision;
orphan generation/embedding/tool spans respect orphan_mode. Metadata has an
explicit resource-ID/scenario/operation/numeric whitelist. Content is omitted by
default. With saved log_content=true, only explicitly supplied bounded input and
output previews are sent, with saved/inline credentials and secret fields
redacted. Cache/reasoning counts use nonoverlapping buckets. The caller handles
optional telemetry failure separately; it must never repeat a paid model call
because telemetry failed. Accepted means the collector accepted the protocol
request, not a claim that UI aggregation/indexing has finished.

Existing local Langfuse browser login is retained. `langfuseStatus(ctx, options?)`
validates the configured UI/project and makes a real health request. The actual
system admin or configured local_login_user_id is authorized, using real DB
flags. `langfuseSession(ctx, options)` accepts trusted adapter values
`{requestOrigin,remoteAddress,existingCookies?,signal?,timeoutMs?}` and performs
CSRF → credentials callback → session email/project verification. Only the same
loopback hostname is allowed. Other existing accounts raise account_conflict;
failure has a 60-second owning-runtime cooldown. `clearLangfuseSession(ctx,
options)` expires only next-auth session cookies and preserves unrelated cookies.

Session/clear return `{result: JsonObject, cookies: SessionCookie[]}`. This is
trusted HTTP/platform-adapter output: serialize only result; apply cookies using
HttpOnly/SameSite=Lax/Path=/ and the returned Secure/Max-Age fields. Never send
the complete result to renderer JSON, logs or IPC. requestOrigin/remoteAddress
and existingCookies must come from the validated real request/platform, never
from caller JSON. The HTTP adapter must enforce its real mutation Origin check.
Without a browser cookie adapter, return an explicit unavailable diagnostic,
not a successful browser-login claim. Third-party OAuth sessions are not forged.

`close()` aborts active budgets, closes all owned MCP clients/transports and
terminates owned Neo4j Workers, and awaits actual internal work promises through
their finally cleanup even after public cancellation has settled. The application should await it before closing
the DB. No global client/pool or foreign process is closed.

Verification on Linux, 2026-10-10:

- Initial `node --import tsx --test test/integrations.test.ts`: five failures for
  the missing independent domain, then five passed after implementation.
- Further failing regressions proved unsafe externally supplied abort reasons,
  Neo4j's pending socket leak, absent local browser login/OTLP/HTTP Query adapter,
  secret reflection, configuration changes before MCP invocation, and absent
  opt-in content upload. Each was fixed and rerun.
- The 16 integration cases use real temporary SQLite, controlled local HTTP/TCP,
  and official SDK local Streamable HTTP/SSE servers. They cover handshake,
  pagination, tool calls, auth revocation, secret encryption/projection, direct
  and encoded provider keys, real search source URLs, bounded timeout/cancel,
  response limits, redirect rejection, recovery and owning-runtime cleanup.
- Neo4j sends the standard Bolt magic to a controlled TCP peer. Refusal and
  post-handshake cancellation are real; cancelling destroys the owned socket
  while an unrelated socket stays alive. A real Neo4j database's successful
  Bolt/TLS/routed query remains unverified. The HTTP Query API test is explicitly
  a protocol fixture, not a database engine or Bolt-success substitute.
- Langfuse projects authentication, OTLP actual timing/usage/privacy/sampling/
  partial rejection, and NextAuth CSRF/login/account/project/cookie reuse/clear
  are validated with local protocol fixtures. Actual external deployment
  indexing, third-party OAuth, Windows Worker/socket execution and browser cookie
  integration remain unverified.
- New scoped-query and shutdown cases first failed (three failures), then passed.
  A separate publication-boundary unit seam tests post-await revocation/config
  changes; it is not counted as a successful Bolt query.
- `node --import tsx --test test/integrations.test.ts test/settings.test.ts
  test/models.test.ts` passes 50/50. `npm run typecheck` and `npm run build` pass.
  A standalone Node script imports compiled JS without a TS loader and proves
  the owned compiled Worker sends actual Bolt magic and handles peer refusal.
  Evidence: `docs/evidence/20261010-integrations-settings-models.tap` and
  `docs/evidence/20261010-integrations-compiled-worker.txt`.
  No paid endpoint, original user data/password,
  shared schema, settings, application, HTTP adapter or frontend was modified.

Evaluation dataset uploading, trace links in the conversation DTO, local Docker
autostart and third-party OAuth need their owning evaluation/lifecycle/platform
adapters. Existing saved options are retained; this service does not mark those
features applied or fake a completed external operation.

Protocol references: [Neo4j driver](https://neo4j.com/docs/javascript-manual/current/),
[Query API](https://neo4j.com/docs/query-api/current/query/),
[MCP SDK](https://github.com/modelcontextprotocol/typescript-sdk),
[Langfuse OTLP](https://langfuse.com/integrations/native/opentelemetry),
[OTLP specification](https://opentelemetry.io/docs/specs/otlp/),
[Bing retirement](https://learn.microsoft.com/en-us/lifecycle/announcements/bing-search-api-retirement).
