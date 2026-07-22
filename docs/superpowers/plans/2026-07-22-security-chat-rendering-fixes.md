# Security And Chat Rendering Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the authentication and tenant-isolation holes, render compact collapsible Agent traces correctly, preserve tool failures across SSE, persist recovery failures, and remove duplicate oversized document-list traffic.

**Architecture:** Add a local view-security boundary shared by the knowledge and Wiki apps, then make every routed resource lookup tenant-scoped. Keep streaming compatibility in a small protocol helper consumed by both active and legacy chat views. Move frontend event mutation into pure functions, put Actor rendering in a focused component, and keep one shared dependency-free Markdown renderer.

**Tech Stack:** Django 5.2, SQLite-compatible Django ORM, Vue 3 Composition API, TypeScript/ES modules, TDesign icons, Node assertion tests, Django TestCase, Playwright.

## Global Constraints

- `auto-setup` is allowed only when `ALLOW_AUTO_SETUP=true` and no user exists; otherwise it returns `401`.
- Unauthenticated resource access returns `401`; authenticated cross-tenant access returns `404`.
- Running Actors default expanded; terminal Actors default collapsed; manual choices persist for the component lifetime.
- Raw HTML remains escaped; Markdown links allow only `http`, `https`, `mailto`, root/relative paths, and fragments.
- Do not add frontend or backend dependencies.
- Do not overwrite, revert, or commit unrelated dirty-worktree changes. Because required files already contain user changes, implementation tasks end with diff/test checkpoints rather than git commits.
- Keep active split-app routes and legacy compatibility paths behaviorally aligned where the same stream protocol is duplicated.

---

### Task 1: Lock Down First-Run Auto Setup

**Files:**
- Create: `accounts/test_auto_setup_security.py`
- Modify: `config/settings.py`
- Modify: `accounts/views.py`
- Modify: `personal_knowledge_base/tests.py`
- Modify: `tests/test_delete_session_cleans_neo4j_memory.py`

**Interfaces:**
- Consumes: environment variable `ALLOW_AUTO_SETUP` parsed by existing `env_bool()`.
- Produces: Django setting `settings.ALLOW_AUTO_SETUP: bool`; `POST /api/v1/auth/auto-setup` returns `201` once or `401`.

- [ ] **Step 1: Write failing auto-setup tests**

```python
from django.test import TestCase, override_settings

from personal_knowledge_base.models import User


class AutoSetupSecurityTests(TestCase):
    @override_settings(ALLOW_AUTO_SETUP=False)
    def test_auto_setup_requires_explicit_setting(self):
        response = self.client.post("/api/v1/auth/auto-setup", content_type="application/json")
        self.assertEqual(response.status_code, 401)
        self.assertFalse(User.objects.exists())

    @override_settings(ALLOW_AUTO_SETUP=True)
    def test_auto_setup_only_creates_the_first_user(self):
        first = self.client.post("/api/v1/auth/auto-setup", content_type="application/json")
        second = self.client.post("/api/v1/auth/auto-setup", content_type="application/json")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 401)
        self.assertEqual(User.objects.count(), 1)
```

- [ ] **Step 2: Run the new tests and verify RED**

Run: `python manage.py test accounts.test_auto_setup_security --verbosity 2`

Expected: FAIL because the setting does not exist and the second call currently issues another token.

- [ ] **Step 3: Add the default-off setting and transactional initialization gate**

```python
# config/settings.py
ALLOW_AUTO_SETUP = env_bool("ALLOW_AUTO_SETUP", False)
```

```python
# accounts/views.py
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import transaction

@csrf_exempt
def auth_auto_setup(request):
    if not settings.ALLOW_AUTO_SETUP:
        return fail("auto setup is disabled", 401, "auto_setup_disabled")
    with transaction.atomic():
        ContentType.objects.select_for_update().get(
            app_label=User._meta.app_label,
            model=User._meta.model_name,
        )
        if User.objects.exists():
            return fail("setup already completed", 401, "setup_already_completed")
        random_password = secrets.token_urlsafe(12)
        request._body = json.dumps({
            "username": "admin",
            "email": "admin@knowledge.local",
            "password": random_password,
        }).encode()
        response = auth_register(request)
    # Preserve the existing temp_password response annotation here.
    return response
```

Apply `@override_settings(ALLOW_AUTO_SETUP=True)` to existing test classes that intentionally bootstrap through this endpoint.

- [ ] **Step 4: Run focused and compatibility tests**

Run: `python manage.py test accounts.test_auto_setup_security personal_knowledge_base.tests.PersonalKnowledgeBaseCoreFlowTests tests.test_delete_session_cleans_neo4j_memory --verbosity 1`

Expected: all selected tests PASS; setup creates one user per isolated test database transaction.

- [ ] **Step 5: Review checkpoint**

Run: `git diff --check -- config/settings.py accounts/views.py personal_knowledge_base/tests.py tests/test_delete_session_cleans_neo4j_memory.py accounts/test_auto_setup_security.py`

Expected: no whitespace errors and no unrelated files staged.

---

### Task 2: Enforce Authentication And Tenant-Scoped Resource Lookups

**Files:**
- Create: `personal_knowledge_base/view_security.py`
- Create: `knowledge/test_tenant_security.py`
- Create: `wiki/test_tenant_security.py`
- Modify: `knowledge/views.py`
- Modify: `wiki/views.py`

**Interfaces:**
- Produces: `tenant_required(view)` decorator; `tenant_object_or_404(model_or_qs, tenant, **lookup)` helper.
- Consumes: `request.auth_user` and `request.auth_tenant` populated by the decorator.

- [ ] **Step 1: Write failing cross-tenant and unauthenticated tests**

Create two tenants, one user/token for tenant B, and resources owned by tenant A. Cover unauthenticated GET plus cross-tenant GET/PUT/DELETE for representative KnowledgeBase, Knowledge, Chunk, KnowledgeTag, WikiPage, and WikiFolder routes. Every cross-tenant write assertion must also reload the object and prove it was unchanged.

```python
def test_knowledge_resources_reject_unauthenticated_and_cross_tenant_access(self):
    self.assertEqual(self.client.get(f"/api/v1/knowledge/{self.doc.id}").status_code, 401)
    response = self.client.delete(f"/api/v1/knowledge/{self.doc.id}", **self.tenant_b_headers)
    self.assertEqual(response.status_code, 404)
    self.doc.refresh_from_db()
    self.assertIsNone(self.doc.deleted_at)

def test_wiki_resources_are_tenant_scoped(self):
    self.assertEqual(self.client.get(f"/api/v1/knowledge-bases/{self.kb.id}/wiki/pages").status_code, 401)
    response = self.client.put(
        f"/api/v1/knowledge-bases/{self.kb.id}/wiki/pages/{self.page.slug}",
        data=json.dumps({"title": "cross tenant"}),
        content_type="application/json",
        **self.tenant_b_headers,
    )
    self.assertEqual(response.status_code, 404)
    self.page.refresh_from_db()
    self.assertNotEqual(self.page.title, "cross tenant")
```

- [ ] **Step 2: Run security tests and verify RED**

Run: `python manage.py test knowledge.test_tenant_security wiki.test_tenant_security --verbosity 2`

Expected: FAIL with current `200` responses for unauthenticated and cross-tenant requests.

- [ ] **Step 3: Implement the shared local security boundary**

```python
# personal_knowledge_base/view_security.py
from functools import wraps

from django.shortcuts import get_object_or_404

from .authentication import require_auth
from .responses import fail


def tenant_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            user, tenant = require_auth(request)
        except PermissionError:
            return fail("unauthorized", 401, "unauthorized")
        if tenant is None:
            return fail("unauthorized", 401, "unauthorized")
        request.auth_user = user
        request.auth_tenant = tenant
        return view(request, *args, **kwargs)
    return wrapped


def tenant_object_or_404(model_or_qs, tenant, **lookup):
    return get_object_or_404(model_or_qs, tenant=tenant, **lookup)
```

- [ ] **Step 4: Apply the boundary to every routed knowledge and Wiki view**

Decorate every function referenced by `knowledge/urls.py` and `wiki/urls.py`. Replace raw object lookup/filter patterns as follows:

```python
@csrf_exempt
@tenant_required
def knowledge_detail(request, knowledge_id):
    item = tenant_object_or_404(
        Knowledge,
        request.auth_tenant,
        id=knowledge_id,
        deleted_at__isnull=True,
    )
```

Use `tenant=request.auth_tenant` for KnowledgeBase, Knowledge, Chunk, KnowledgeTag, WikiPage, WikiFolder, WikiLogEntry, WikiPendingOp, batch ID querysets, move source/target querysets, downloads, previews, stats, graph data, and search KB IDs. Pass the already-scoped KnowledgeBase object into Wiki graph helpers instead of querying from a raw `kb_id` again.

- [ ] **Step 5: Run security tests and all knowledge/Wiki tests**

Run: `python manage.py test knowledge wiki knowledge.test_tenant_security wiki.test_tenant_security --verbosity 1`

Expected: PASS; unauthenticated requests return `401`, cross-tenant requests return `404`, owner requests retain current behavior.

- [ ] **Step 6: Audit for remaining unscoped routed lookups**

Run: `rg -n "get_object_or_404\((KnowledgeBase|Knowledge|Chunk|KnowledgeTag|WikiPage|WikiFolder)," knowledge/views.py wiki/views.py`

Expected: every result includes `tenant` directly or is reached from a previously tenant-scoped parent object.

---

### Task 3: Return One Lightweight Document Collection Response

**Files:**
- Create: `knowledge/test_collection_performance.py`
- Modify: `personal_knowledge_base/serializers.py`
- Modify: `knowledge/views.py`
- Modify: `frontend/src/views/KnowledgeDetail.vue`
- Modify: `frontend/src/views/KnowledgeDetail.workspace-layout.test.mjs`

**Interfaces:**
- Produces: `knowledge_list_dict(item) -> dict` without `metadata`, `file_path`, or `file_hash`.
- Produces collection payload: `{items, page, page_size, total, status_counts, tag_counts, processing_records}`.

- [ ] **Step 1: Write failing lightweight-response tests**

```python
def test_collection_uses_one_lightweight_array_and_aggregates(self):
    self.doc.metadata = {"content": "x" * 100_000}
    self.doc.save(update_fields=["metadata"])
    response = self.client.get(
        f"/api/v1/knowledge-bases/{self.kb.id}/knowledge?page=1&page_size=100",
        **self.headers,
    )
    data = response.json()["data"]
    self.assertNotIn("metadata", data["items"][0])
    self.assertNotIn("file_path", data["items"][0])
    self.assertNotIn("knowledge", data)
    self.assertNotIn("data", data)
    self.assertEqual(data["status_counts"][self.doc.parse_status], 1)
    self.assertEqual(data["tag_counts"][self.doc.tag_id], 1)
    self.assertLess(len(response.content), 20_000)
```

- [ ] **Step 2: Run the backend test and existing frontend contract test to verify RED**

Run: `python manage.py test knowledge.test_collection_performance --verbosity 2`

Run: `node frontend/src/views/KnowledgeDetail.workspace-layout.test.mjs`

Expected: backend FAIL because full metadata and duplicate aliases are present; frontend contract FAIL after adding assertions that `loadAllDocs` and `page_size: 1000` must be absent.

- [ ] **Step 3: Add the lightweight serializer and aggregate response**

```python
def knowledge_list_dict(item: Knowledge):
    return {
        "id": item.id,
        "knowledge_base_id": item.knowledge_base_id,
        "type": item.type,
        "title": item.title,
        "description": item.description,
        "source": item.source,
        "parse_status": item.parse_status,
        "enable_status": item.enable_status,
        "file_name": item.file_name,
        "file_type": item.file_type,
        "file_size": item.file_size,
        "storage_size": item.storage_size,
        "tag_id": item.tag_id,
        "summary_status": item.summary_status,
        "pending_subtasks_count": item.pending_subtasks_count,
        "error_message": item.error_message,
        "processed_at": iso(item.processed_at),
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }
```

Build `status_counts` and `tag_counts` from the unfiltered tenant-scoped base QuerySet. Return at most 200 lightweight `processing_records`; serialize the paginated filtered QuerySet once under `items`, without the old `data` and `knowledge` aliases.

- [ ] **Step 4: Remove the second frontend request**

Replace `allDocs` population with `res.data.processing_records`, replace computed counts with response refs, delete `loadAllDocs()`, and replace every paired refresh with one `loadDocs()` call. The request remains bounded to `page_size: 100`.

- [ ] **Step 5: Run focused tests**

Run: `python manage.py test knowledge.test_collection_performance personal_knowledge_base.tests.PersonalKnowledgeBaseCoreFlowTests --verbosity 1`

Run: `node frontend/src/views/KnowledgeDetail.workspace-layout.test.mjs`

Expected: PASS and no source occurrence of `loadAllDocs` or `page_size: 1000`.

---

### Task 4: Preserve Tool Event Fields And Persist Recovery Failures

**Files:**
- Create: `personal_knowledge_base/stream_protocol.py`
- Create: `chat/test_stream_protocol.py`
- Modify: `chat/views.py`
- Modify: `personal_knowledge_base/views.py`

**Interfaces:**
- Produces: `tool_stream_payload(response_type, assistant_message_id, event_data) -> dict`.
- Produces: `complete_message_with_error(message_id, content) -> str`.
- Produces: `CONTINUE_STREAM_MAX_WAIT_SECONDS = 120` in both routed views for test patching.

- [ ] **Step 1: Write failing protocol and recovery tests**

```python
def test_tool_result_keeps_identity_error_and_full_output(self):
    payload = tool_stream_payload("tool_result", "assistant-1", {
        "tool_call_id": "call-1",
        "name": "database_query",
        "output": "x" * 800,
        "error": "query failed",
        "duration_ms": 7,
        "iteration": 2,
    })
    self.assertEqual(payload["tool_call_id"], "call-1")
    self.assertEqual(payload["error"], "query failed")
    self.assertEqual(len(payload["output"]), 800)

@patch("chat.views.CONTINUE_STREAM_MAX_WAIT_SECONDS", 0)
def test_continue_stream_timeout_persists_terminal_error(self):
    response = self.client.get(self.continue_url, **self.headers)
    b"".join(response.streaming_content)
    self.message.refresh_from_db()
    self.assertTrue(self.message.is_completed)
    self.assertEqual(self.message.content, "等待超时")
```

- [ ] **Step 2: Run the new tests and verify RED**

Run: `python manage.py test chat.test_stream_protocol --verbosity 2`

Expected: FAIL because event fields are dropped/truncated and timeout does not update Message.

- [ ] **Step 3: Implement shared protocol helpers**

```python
def tool_stream_payload(response_type, assistant_message_id, event_data):
    payload = {
        "response_type": response_type,
        "assistant_message_id": assistant_message_id,
        "tool_call_id": event_data.get("tool_call_id", ""),
        "name": event_data.get("name", ""),
        "iteration": event_data.get("iteration", 0),
    }
    if response_type == "tool_call":
        payload["arguments"] = event_data.get("arguments", {})
    else:
        payload.update({
            "output": event_data.get("output", ""),
            "error": event_data.get("error", ""),
            "duration_ms": event_data.get("duration_ms", 0),
        })
    return payload

def complete_message_with_error(message_id, content):
    text = str(content or "生成失败")
    Message.objects.filter(id=message_id).update(
        content=text,
        rendered_content=text,
        is_completed=True,
        updated_at=timezone.now(),
    )
    return text
```

- [ ] **Step 4: Use helpers in active and legacy stream loops**

Replace the four active/legacy `tool_call` and `tool_result` payload constructors with `tool_stream_payload()`. In error, missing-stream, and timeout branches call `complete_message_with_error()` before emitting SSE. Use the shared timeout constant rather than a local literal.

- [ ] **Step 5: Run stream tests**

Run: `python manage.py test chat.test_stream_protocol personal_knowledge_base.tests.PersonalKnowledgeBaseCoreFlowTests.test_chat_sse_stream_contract --verbosity 1`

Expected: PASS; 800-character output, `tool_call_id`, and `error` survive SSE serialization; timed-out messages are terminal in the database.

---

### Task 5: Expand The Shared Safe Markdown Renderer

**Files:**
- Modify: `frontend/src/utils/markdown-lite.mjs`
- Modify: `frontend/src/utils/markdown-lite.test.mjs`
- Modify: `frontend/src/styles/app.css`

**Interfaces:**
- Produces: `renderMarkdownLite(text: string) -> string` supporting headings, emphasis, safe links, lists, code fences, horizontal rules, and GFM tables.

- [ ] **Step 1: Extend tests before implementation**

Add assertions for `<table><thead><tbody>`, `<hr>`, fenced code preservation, unsafe `javascript:` links becoming `href="#"`, safe HTTPS links, and raw HTML escaping.

```javascript
const tableHtml = renderMarkdownLite('| 名称 | 状态 |\n|---|---|\n| Wiki | success |')
assert.match(tableHtml, /<table>/)
assert.match(tableHtml, /<th>名称<\/th>/)
assert.match(tableHtml, /<td>success<\/td>/)
assert.match(renderMarkdownLite('---'), /<hr>/)
assert.doesNotMatch(renderMarkdownLite('[bad](javascript:alert(1))'), /javascript:/i)
```

- [ ] **Step 2: Run renderer tests and verify RED**

Run: `node frontend/src/utils/markdown-lite.test.mjs`

Expected: FAIL because tables and horizontal rules are currently emitted as text.

- [ ] **Step 3: Replace chained regex blocks with a small block parser**

Escape raw input first, reserve fenced code blocks with opaque placeholders, parse lines into headings/HR/tables/lists/paragraphs, then apply inline emphasis/code/link formatting. Implement `safeHref()` with the exact allowed protocols from Global Constraints. Restore escaped code placeholders last so Markdown markers inside code are never interpreted.

- [ ] **Step 4: Add shared responsive table styles**

Style `.markdown-lite table`, `th`, and `td` with existing neutral borders and compact typography. Apply `display: block; max-width: 100%; overflow-x: auto` to the table wrapper or table itself so 390px layouts do not widen the page.

- [ ] **Step 5: Run all frontend Node tests**

Run: `find frontend/src -name '*.test.mjs' -print0 | sort -z | xargs -0 -n1 node`

Expected: all scripts exit `0`.

---

### Task 6: Add A Collapsible Actor Trace Component

**Files:**
- Create: `frontend/src/views/chat/components/ActorTrace.vue`
- Create: `frontend/src/views/chat/components/ActorTrace.contract.test.mjs`
- Modify: `frontend/src/views/chat/components/AssistantMessage.vue`
- Modify: `frontend/src/styles/app.css`

**Interfaces:**
- Consumes: `actors: any[]` with `actor_id`, `name`, `agent_type`, `status`, `last_outcome`, `output`, `error`, and `metadata.duration_ms`.
- Produces: accessible per-Actor toggle buttons and rendered Markdown details.

- [ ] **Step 1: Write the failing source contract test**

Assert that `AssistantMessage.vue` imports and renders `<ActorTrace>`, and that `ActorTrace.vue` contains `aria-expanded`, `renderMarkdownLite`, TDesign chevron/status icons, and terminal/running default-state logic.

- [ ] **Step 2: Run the contract test and verify RED**

Run: `node frontend/src/views/chat/components/ActorTrace.contract.test.mjs`

Expected: FAIL because `ActorTrace.vue` does not exist.

- [ ] **Step 3: Implement ActorTrace state and rendering**

Use `expandedById = ref<Record<string, boolean>>({})` plus a non-reactive `Set` of manually touched actor IDs. A watcher updates untouched IDs to `true` for `pending/running` and `false` for terminal states. The summary button toggles one ID and sets `aria-expanded`. Render output through `renderMarkdownLite`; render errors as escaped text. Use `ChevronRightIcon`, `ChevronDownIcon`, `CheckCircleIcon`, `ErrorCircleIcon`, `LoadingIcon`, and `TimeIcon` from `tdesign-icons-vue-next`.

- [ ] **Step 4: Replace inline Actor markup and scoped styles**

In `AssistantMessage.vue`, remove the inline `.actor-trace` loop and its scoped CSS, import `ActorTrace`, and render `<ActorTrace :actors="actorTraces" />`. Put reusable trace styles in `app.css`, with 8px maximum radius, stable icon/button dimensions, visible focus, compact heading scale, and no page-level overflow.

- [ ] **Step 5: Run component contract and frontend build**

Run: `node frontend/src/views/chat/components/ActorTrace.contract.test.mjs`

Run: `npm run build --prefix frontend`

Expected: contract PASS and Vite build exits `0`.

---

### Task 7: Match Tool Results By ID And Show Failures

**Files:**
- Create: `frontend/src/views/chat/tool-call-state.mjs`
- Create: `frontend/src/views/chat/tool-call-state.test.mjs`
- Modify: `frontend/src/views/Chat.vue`
- Modify: `frontend/src/views/chat/components/AssistantMessage.vue`
- Modify: `frontend/src/views/chat/components/ToolResultRenderer.vue`

**Interfaces:**
- Produces: `appendToolCall(calls, event) -> void` and `applyToolResult(calls, event) -> boolean`.
- Tool state values: `running`, `done`, `failed`.

- [ ] **Step 1: Write failing pure-state tests**

```javascript
const calls = []
appendToolCall(calls, { tool_call_id: 'a', name: 'database_query' })
appendToolCall(calls, { tool_call_id: 'b', name: 'database_query' })
applyToolResult(calls, { tool_call_id: 'b', name: 'database_query', error: 'failed' })
assert.equal(calls[0].status, 'running')
assert.equal(calls[1].status, 'failed')
assert.equal(calls[1].error, 'failed')
```

Also test the legacy no-ID fallback updates the first same-name running call.

- [ ] **Step 2: Run the state test and verify RED**

Run: `node frontend/src/views/chat/tool-call-state.test.mjs`

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement state helpers and wire Chat.vue**

`appendToolCall` stores `tool_call_id`, arguments, iteration, and `running`. `applyToolResult` first finds exact `tool_call_id`; only if absent does it find a same-name running call. It copies `output/error/duration_ms` and sets `failed` when error is non-empty, otherwise `done`.

- [ ] **Step 4: Make tool details collapsible and status-correct**

Render each completed tool as a native `<details>` with `<summary>`. Failed tools default open and use `ErrorCircleIcon`; successful tools default closed and use `CheckCircleIcon`; running tools use `LoadingIcon`. Render `<ToolResultRenderer>` for both `done` and `failed`, and ensure the renderer does not print the same error twice.

- [ ] **Step 5: Run state, contract, and build checks**

Run: `node frontend/src/views/chat/tool-call-state.test.mjs`

Run: `node frontend/src/views/chat/components/ActorTrace.contract.test.mjs`

Run: `npm run build --prefix frontend`

Expected: all exit `0`.

---

### Task 8: Full Regression And Playwright Verification

**Files:**
- Modify: `tests/test_frontend_playwright_e2e.py`
- Generated verification artifacts only: `/tmp/django-agent-*.png`

**Interfaces:**
- Verifies all contracts from Tasks 1-7 without mutating production data.

- [ ] **Step 1: Add Playwright regression assertions**

Extend the fake Agent output to include a Markdown heading and table. Assert terminal Actor starts collapsed, clicking its summary reveals heading/table DOM, and `aria-expanded` changes. Add a routed fake SSE tool failure and assert the failed class/icon/error text. Record desktop and 390px metrics for page-level overflow, console errors, failed requests, and non-2xx API responses.

- [ ] **Step 2: Run complete backend tests**

Run: `python manage.py test accounts knowledge wiki chat personal_knowledge_base models_config --verbosity 1`

Expected: all tests PASS with zero failures/errors.

- [ ] **Step 3: Run all frontend Node tests and production build**

Run: `find frontend/src -name '*.test.mjs' -print0 | sort -z | xargs -0 -n1 node`

Run: `npm run build --prefix frontend`

Expected: all Node scripts and Vite build exit `0`.

- [ ] **Step 4: Run Playwright E2E**

Run: `python tests/test_frontend_playwright_e2e.py`

Expected: all browser cases PASS; Actor table DOM appears after expansion; failed tool is visibly failed; desktop/mobile have no page-level overflow or browser errors.

- [ ] **Step 5: Security proof and final workspace audit**

Run unauthenticated and cross-tenant read-only requests against the local server. Expected: `401` and `404`, respectively. Then run:

```bash
git diff --check
git status --short --branch
```

Expected: no whitespace errors; only planned files plus pre-existing user changes are present; no temporary screenshot remains in the repository.
