# Preserved legacy tenant and channel services

`registerLegacyRoutes(app)` runs after models, knowledge and chat exist and returns
`{tenants: LegacyTenantService, channels: ChannelService}`. The application retains
this object and begins `channels.close()` before closing SQLite, awaiting it and
other owned services. Both use the same authoritative AuthService and real SQLite
business tables. There are no Django requests or transactions spanning awaits.

`LegacyTenantService(db, auth)` preserves tenant CRUD/search/list/switch, members,
soft deletion, retained revocation markers, random API key rotation and real audit
rows. GET projections never contain API keys. Only a trusted HTTP binding can
select `rotateApiKey(ctx,id,{revealKey:true})`; IPC receives rotated/configured
status. Renderer body fields cannot choose transport or secret delivery.

`ChannelService(db,auth,vault,chat,{now?})` preserves embed/IM scoped CRUD, toggle,
explicit token rotation, preview and measured embed session/message statistics.
Channel secrets are encrypted by the core vault; blank/null/****** secret edits
preserve existing values, encrypted storage strings are rejected, and nested
secret writes require authoritative credentials.manage. Normal channel GETs show
configured flags. Secret rotation is revealed only by the explicit HTTP contract.

The ten registered public embed paths retain the legacy channel URL structure.
The root-owned HTTP binding supplies origin and bearer/header alias, enforces the
existing loopback Host/Origin/CSRF policy, and permits only a fixed public allowlist.
Native IPC public entrypoints return 404. No new remote listener or cloud hosting
is introduced. The query-token legacy alias is accepted by the scoped service.

Opaque guest grants expire after one hour. Only their digest is stored, bound to
channel/version/origin/guest and a frozen KB scope. Every domain call rechecks the
actual channel, enabled source KBs, sponsor membership and active tenant/user.
Configuration changes, rotation, source deletion or sponsor revocation invalidate
old grants. The real creator user ID is used only for accounting/FK ownership;
the context has a separate channel principal and cannot use ordinary account,
device, password, preferences, credentials or memory operations. It never becomes
an ordinary bearer credential. Legacy channels with no saved owner require an
explicit authorized administrator binding instead of guessing an owner.

Public guest sessions are isolated by channel + grant + guest. Other guests and
ordinary owner history routes cannot retrieve them. Owner list/search/statistics
and batch delete exclude guest sessions. Public outputs omit sponsor user and
internal grant identifiers. Model and agent choices are fixed by channel config;
explicit model IDs use ModelConfigurationService's real role normalization,
including imported `chat` rows. A guest cannot supply arbitrary KBs, models, MCP,
attachments or agent options. Selected public agents must use supported scoped
knowledge/Wiki/graph/thinking/actor tools; incompatible external/admin tool configs
return `channel_agent_not_public`. A resource-free public agent uses a fixed eight
tool list, explicitly stored and passed by core code. Actor presets share the same
scope and grant checks. Memory retrieval and maintenance are disabled for guests.

Knowledge/Agent chat delegates to actual ChatService, SearchIndex, JobQueue and
ModelRuntime. Streams, messages, journal events, stop and interrupted-job manual
recovery retain the core lifecycle. An uncertain paid result is never replayed
automatically. `close()` makes grants unavailable, waits tracked public work and
unregisters the authority; the existing worker monitor aborts stale owned calls.

Validation uses real independent SQLite, actual HTTP/IPC transport and a controlled
loopback model protocol server. The fixture exercises FTS followed by streamed
Agent tool execution, three actual runtime calls and three token-usage records;
malicious stats/skill/web/MCP requests are all denied and the external probe sees
zero requests. Shutdown aborts a held provider connection and settles under two
seconds; reopened SQLite has no running/queued worker or memory job. Nine focused
checks and 62 related auth/chat/agent/transport checks pass; typecheck/build pass.
Evidence: `docs/evidence/20261010-legacy-channel-parser-worker.json` and companion
TAP/build logs at repository root. This is not a real vendor, GUI, installer,
remote/PWA hosting or disk durability acceptance. TMPDIR=/dev/shm only bypasses the
known host disk journal stall. Old placeholder IM QR/callback, invitation/share
and admin-promote endpoints have not been fabricated or deleted.
