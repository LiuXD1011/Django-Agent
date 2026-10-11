# Graph deletion outbox and readiness

SQLite source rows and publication generations remain authoritative. Ordinary graph
reads still require an active same-tenant KB and current source/generation evidence.
A KB tombstone never grants graph read access.

The KB DELETE adapter reserves a `delete_knowledge_base` outbox ticket before local
deletion. It commits local deletion before attempting any remote cleanup. The ticket
contains the exact SHA-256 namespace of `[tenantId, knowledgeBaseId]`; its fixed
parameterized template removes that namespace, including unpublished staging and
libraries with no remaining document rows. Remote failure returns an explicit pending
warning and keeps the ticket. A subsequent authorized POST to the existing
`/api/v1/knowledge-bases/:id/graph/cleanup` route can retry a tombstoned KB.

`IntegrationService.cleanupScopedNeo4j(ctx, kbId, pendingKey, options)` is a trusted
core-only transport, not an arbitrary Cypher route. It reads the persisted ticket
itself, accepts neither a statement nor caller-selected query parameters, and checks
authoritative tenant membership, KB ownership, source identity, ticket contents and
integration configuration before and after the request. Active-KB cleanup requires
`document.write`; deleted-KB cleanup requires current `kb.delete`. A namespace ticket
cannot run until the KB is actually tombstoned. No business transaction spans an await.

Document outbox schema 2 pins the preceding published generation. Editing then
publishing a new generation before cleanup does not retire or delete that new graph.
Schema 1 deleted/moved-source tickets remain safely retryable; unpinned live-source
tickets with a publication remain pending with `graph_cleanup_generation_missing`.
Wall-clock timestamps cannot prove the old generation, so those entries are retained
with an explicit warning. Later deletion of the KB safely cleans its whole namespace.

`GraphService.queueKnowledgeBaseCleanup(ctx, kbId)` returns the persisted ticket key.
`processPending(ctx, kbId, {signal?,limit?})` returns
`{processed,remaining,results,warnings}`. Its bounded batch retains unprocessed work;
close/cancellation aborts and awaits owned requests and prevents late acknowledgement.

`scopedNeo4jReadiness(ctx, kbId)` needs only a genuine authorized KB read, including
ordinary viewers. It returns `disabled`, `not_configured` or `configured`, with
booleans `enabled`, `configured`, and `connection_verified:false`. It exposes no
endpoint or credentials and makes no network or paid model call. Graph capabilities
combine this actual configuration readiness with graph enablement and model presence;
the existence of an IntegrationService object no longer implies available Neo4j.

The existing trusted `GraphService.search(ctx, kbIds, query, {signal?,limit?,seenChunkIds?})`
returns `{state,items,warnings}`. Current-source items carry `chunk_id`, content,
document/KB identifiers and titles, metadata, score 1 and `match_type:'graph'`.
Already retrieved chunk IDs are excluded before the graph top-K limit, so repeated
document hits cannot crowd out independent graph evidence. The additional real
SQLite/local HTTP model regression first returned the repeated chunk (RED), then
returned the next independent source (GREEN). Graph, cleanup and independent-top-K
tests passed **30/30** in **22.431s**, with typecheck and build exit 0.
The legacy chat path appended distinct graph items after rerank, then at most three
direct/indirect relation chunks before short-chunk/parent expansion and MMR. Wiring
this hook into Chat is owned separately; this change does not claim that integration.

Verification uses real independent SQLite and controlled local HTTP GraphTransport
fixtures, not a real Neo4j server or vendor model. The initial four regressions failed
for tombstone 404, missing empty-KB ticket, false readiness, and missing dedicated
cleanup transport. The remaining-work and legacy-generation regressions also failed
before their fixes. Existing actual Bolt handshake/refusal, MCP SDK and Langfuse
regressions are included in the related integration suite. Run from `packages/core`:

```sh
TMPDIR=/dev/shm node --import tsx --test test/graph-cleanup.test.ts test/graph.test.ts test/application-knowledge.test.ts test/application-evaluation-graph.test.ts test/integrations.test.ts
npm run typecheck
npm run build
```

The tests cover local deletion during HTTP failure, real application/database
close and reopen, same-namespace-only cleanup, generation preservation, ordinary
viewer readiness, foreign scope rejection, revocation after an actual remote
response, and owned close cancellation. tmpfs fixtures avoid the observed ext4
journal blockage; they do not establish original-disk durability. Real Neo4j server
acceptance remains a separate unverified deployment check. No original user data,
credentials or paid models are used by these fixtures.

Final related verification passed **48/48** in **25.350s**, including all twelve
new cleanup/readiness regressions. Core typecheck and build both returned exit 0.
The invalid imported endpoint regression first returned HTTP 400 after local
deletion; it now returns the accurate local-success response with pending cleanup
warning. These results are controlled fixture acceptance only.
