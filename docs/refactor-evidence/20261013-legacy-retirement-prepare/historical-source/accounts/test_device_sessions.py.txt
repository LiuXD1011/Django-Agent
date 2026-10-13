"""CD device contracts: two principals, two devices, CSRF and replay fencing."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from pathlib import Path
import tempfile
from unittest.mock import patch

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections
from asgiref.sync import async_to_sync, sync_to_async
from django.http import StreamingHttpResponse
from django.test import Client, RequestFactory, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from personal_knowledge_base.authentication import hash_password, issue_tokens, require_auth
from personal_knowledge_base.models import AuthToken, Knowledge, TaskRecord, Tenant, TenantMember, User
from personal_knowledge_base.personal_spaces import create_personal_user

from .device_sessions import (
    ACCESS_COOKIE, REFRESH_COOKIE, DeviceSessionCsrfMiddleware, digest_token, rotate_refresh,
)
from .models import DeviceRefreshToken, DeviceSession


def cookie_post(client, path, data=None):
    return client.post(path, data or {}, content_type="application/json", HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)


def login_client(username="alice", name="browser"):
    client = Client(enforce_csrf_checks=True)
    client.get("/api/v1/auth/csrf")
    response = cookie_post(client, "/api/v1/auth/login", {
        "username": username, "password": "password123", "auth_mode": "cookie", "device_name": name,
    })
    if response.status_code != 200:
        raise AssertionError(response.content)
    return client, response


@override_settings(DEBUG=True)
class DeviceSessionTests(TestCase):
    def setUp(self):
        self.alice = create_personal_user(username="alice", email="alice@example.test", password_hash=hash_password("password123"))
        self.bob = create_personal_user(username="bob", email="bob@example.test", password_hash=hash_password("password123"))

    def test_cookie_login_has_http_only_cookies_and_only_digests_in_database(self):
        client, response = login_client()
        data = response.json()["data"]
        self.assertEqual(data["auth_mode"], "cookie")
        self.assertNotIn("token", data)
        self.assertNotIn("refresh_token", data)
        self.assertEqual(AuthToken.objects.count(), 0)
        access, refresh = client.cookies[ACCESS_COOKIE], client.cookies[REFRESH_COOKIE]
        self.assertTrue(access["httponly"])
        self.assertTrue(refresh["httponly"])
        self.assertEqual(access["samesite"], "Lax")
        self.assertEqual(refresh["path"], "/api/v1/auth/")
        session = DeviceSession.objects.get()
        self.assertEqual(session.access_digest, digest_token(access.value))
        self.assertEqual(DeviceRefreshToken.objects.get().digest, digest_token(refresh.value))
        self.assertNotEqual(session.access_digest, access.value)
        self.assertLessEqual((session.access_expires_at - timezone.now()).total_seconds(), 600)
        self.assertLessEqual((session.absolute_expires_at - timezone.now()).days, 90)

    @override_settings(DEBUG=False)
    def test_production_auth_cookies_are_secure(self):
        _client, response = login_client()
        self.assertTrue(response.cookies[ACCESS_COOKIE]["secure"])
        self.assertTrue(response.cookies[REFRESH_COOKIE]["secure"])

    def test_cookie_registration_creates_one_private_space_and_no_legacy_tokens(self):
        client = Client(enforce_csrf_checks=True)
        client.get("/api/v1/auth/csrf")
        response = cookie_post(client, "/api/v1/auth/register", {
            "username": "new", "email": "new@example.test", "password": "password123", "auth_mode": "cookie",
        })
        self.assertEqual(response.status_code, 201)
        user = User.objects.get(username="new")
        self.assertEqual(user.tenant.personal_owner_id, user.pk)
        self.assertEqual(user.tenant.space_type, "personal")
        self.assertNotIn("api_key", response.json()["data"]["tenant"])
        self.assertFalse(AuthToken.objects.filter(user=user).exists())

    def test_two_devices_share_identity_but_have_independent_credentials(self):
        first, _ = login_client(name="A")
        second, _ = login_client(name="B")
        self.assertNotEqual(first.cookies[ACCESS_COOKIE].value, second.cookies[ACCESS_COOKIE].value)
        for client in [first, second]:
            self.assertEqual(client.get("/api/v1/auth/me").json()["data"]["user"]["id"], self.alice.pk)
            items = client.get("/api/v1/auth/devices").json()["data"]["items"]
            self.assertEqual(len(items), 2)
            self.assertEqual(sum(item["current"] for item in items), 1)

    @override_settings(APP_MODE="api", RUN_TASK_BACKGROUND=False, APP_TASKS_SYNC=False)
    def test_cookie_devices_share_uploaded_knowledge_but_revoked_device_and_other_user_do_not(self):
        # CD-01/CD-07: real API/storage/queue, no model and no production media.
        first, first_login = login_client(name="device A")
        second, _ = login_client(name="device B")
        outsider, _ = login_client("bob", name="outsider")
        created = cookie_post(first, "/api/v1/knowledge-bases", {"name": "cross-device upload"})
        self.assertEqual(created.status_code, 201)
        kb_id = created.json()["data"]["id"]
        content = "个人知识库跨设备上传验证。".encode("utf-8")
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            with patch("knowledge.views.process_knowledge", side_effect=AssertionError("API mode must not run a model")) as processor:
                uploaded = first.post(
                    f"/api/v1/knowledge-bases/{kb_id}/knowledge/file",
                    {"file": SimpleUploadedFile("cross-device.txt", content, content_type="text/plain")},
                    HTTP_X_CSRFTOKEN=first.cookies["csrftoken"].value,
                )
                self.assertEqual(uploaded.status_code, 201, uploaded.content)
                processor.assert_not_called()
            payload = uploaded.json()["data"]
            knowledge_id, task_id = payload["knowledge"]["id"], payload["task_id"]
            self.addCleanup(cache.delete, f"task:{task_id}")
            item = Knowledge.objects.get(pk=knowledge_id)
            task = TaskRecord.objects.get(pk=task_id)
            self.assertEqual(item.tenant_id, self.alice.tenant_id)
            self.assertEqual(item.knowledge_base_id, kb_id)
            self.assertEqual(item.parse_status, "pending")
            self.assertEqual(task.payload["knowledge_id"], item.pk)
            self.assertEqual(task.status, "pending")
            self.assertEqual(task.queue_name, "documents")
            self.assertEqual((Path(media_root) / item.file_path).read_bytes(), content)
            paths = [
                f"/api/v1/knowledge-bases/{kb_id}",
                f"/api/v1/knowledge/{knowledge_id}",
                f"/api/v1/knowledge/move/progress/{task_id}",
            ]
            for path in paths:
                self.assertEqual(second.get(path).status_code, 200, path)
                self.assertEqual(outsider.get(path).status_code, 404, path)
            self.assertEqual(second.get(paths[1]).json()["data"]["file_name"], "cross-device.txt")
            self.assertEqual(second.get(paths[2]).json()["data"]["status"], "pending")
            downloaded = second.get(f"/api/v1/knowledge/{knowledge_id}/download")
            self.assertEqual(downloaded.status_code, 200)
            try:
                self.assertEqual(b"".join(downloaded.streaming_content), content)
            finally:
                downloaded.close()
            device_id = first_login.json()["data"]["device"]["id"]
            revoked = second.delete(f"/api/v1/auth/devices/{device_id}", HTTP_X_CSRFTOKEN=second.cookies["csrftoken"].value)
            self.assertEqual(revoked.status_code, 200)
            for path in paths:
                self.assertEqual(first.get(path).status_code, 401, path)
                self.assertEqual(second.get(path).status_code, 200, path)
            self.assertEqual(cookie_post(first, "/api/v1/auth/refresh", {"auth_mode": "cookie"}).status_code, 401)

    def test_device_listing_and_revoke_are_scoped_to_user(self):
        alice, _ = login_client()
        bob, response = login_client("bob")
        bob_id = response.json()["data"]["device"]["id"]
        items = alice.get("/api/v1/auth/devices").json()["data"]["items"]
        self.assertNotIn(bob_id, [item["id"] for item in items])
        response = alice.delete(f"/api/v1/auth/devices/{bob_id}", HTTP_X_CSRFTOKEN=alice.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(bob.get("/api/v1/auth/me").status_code, 200)

    def test_revoke_other_device_does_not_log_out_current_device(self):
        first, _ = login_client()
        second, response = login_client()
        device_id = response.json()["data"]["device"]["id"]
        response = first.delete(f"/api/v1/auth/devices/{device_id}", HTTP_X_CSRFTOKEN=first.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(first.get("/api/v1/auth/me").status_code, 200)
        self.assertEqual(second.get("/api/v1/auth/me").status_code, 401)
        self.assertEqual(cookie_post(second, "/api/v1/auth/refresh", {"auth_mode": "cookie"}).status_code, 401)

    def test_login_register_and_refresh_require_csrf_in_cookie_mode(self):
        client = Client(enforce_csrf_checks=True)
        for path in ["login", "register", "refresh", "auto-setup"]:
            response = client.post(f"/api/v1/auth/{path}", {"auth_mode": "cookie"}, content_type="application/json")
            self.assertEqual(response.status_code, 403, path)
            self.assertEqual(response.json()["error"]["code"], "csrf_failed")

    def test_multipart_cookie_login_cannot_bypass_csrf_initialization(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post("/api/v1/auth/login", {"username": "alice", "password": "password123", "auth_mode": "cookie"})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(DeviceSession.objects.exists())

    def test_legacy_exempt_api_mutations_are_protected_for_cookie_requests(self):
        client, _ = login_client()
        response = client.post("/api/v1/auth/me/preferences", {"language": "zh"}, content_type="application/json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(cookie_post(client, "/api/v1/auth/me/preferences", {"language": "zh"}).status_code, 200)

    def test_foreign_origin_is_rejected_even_with_correct_csrf_token(self):
        client, _ = login_client()
        response = client.post("/api/v1/auth/logout", {}, content_type="application/json",
                               HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value, HTTP_ORIGIN="https://evil.example")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(client.get("/api/v1/auth/me").status_code, 200)

    def test_arbitrary_authorization_header_cannot_bypass_cookie_csrf(self):
        client, _ = login_client()
        response = client.post("/api/v1/auth/me/preferences", {"x": 1}, content_type="application/json", HTTP_AUTHORIZATION="invalid")
        self.assertEqual(response.status_code, 403)
        self.alice.refresh_from_db()
        self.assertNotIn("x", self.alice.preferences)

    def test_refresh_rotates_and_invalidates_previous_access(self):
        client, _ = login_client()
        old_access, old_refresh = client.cookies[ACCESS_COOKIE].value, client.cookies[REFRESH_COOKIE].value
        response = cookie_post(client, "/api/v1/auth/refresh", {"auth_mode": "cookie"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("token", response.json()["data"])
        self.assertNotEqual(old_access, client.cookies[ACCESS_COOKIE].value)
        self.assertNotEqual(old_refresh, client.cookies[REFRESH_COOKIE].value)
        old = Client()
        old.cookies[ACCESS_COOKIE] = old_access
        self.assertEqual(old.get("/api/v1/auth/me").status_code, 401)
        self.assertIsNotNone(DeviceRefreshToken.objects.get(digest=digest_token(old_refresh)).consumed_at)

    def test_refresh_replay_revokes_only_its_family(self):
        first, _ = login_client()
        second, _ = login_client()
        old = first.cookies[REFRESH_COOKIE].value
        self.assertEqual(cookie_post(first, "/api/v1/auth/refresh", {"auth_mode": "cookie"}).status_code, 200)
        replay = Client(enforce_csrf_checks=True)
        replay.get("/api/v1/auth/csrf")
        replay.cookies[REFRESH_COOKIE] = old
        self.assertEqual(cookie_post(replay, "/api/v1/auth/refresh", {"auth_mode": "cookie"}).status_code, 401)
        self.assertEqual(first.get("/api/v1/auth/me").status_code, 401)
        self.assertEqual(second.get("/api/v1/auth/me").status_code, 200)
        self.assertEqual(DeviceSession.objects.filter(revoke_reason="refresh_replay").count(), 1)

    def test_access_expiry_can_refresh_without_old_access_cookie(self):
        client, _ = login_client()
        DeviceSession.objects.update(access_expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(client.get("/api/v1/auth/me").status_code, 401)
        del client.cookies[ACCESS_COOKIE]
        self.assertEqual(cookie_post(client, "/api/v1/auth/refresh", {"auth_mode": "cookie"}).status_code, 200)
        self.assertEqual(client.get("/api/v1/auth/me").status_code, 200)

    def test_idle_and_absolute_expiry_cannot_be_extended(self):
        for field in ["idle_expires_at", "absolute_expires_at"]:
            with self.subTest(field=field):
                client, response = login_client()
                DeviceSession.objects.filter(pk=response.json()["data"]["device"]["id"]).update(**{field: timezone.now() - timedelta(seconds=1)})
                self.assertEqual(cookie_post(client, "/api/v1/auth/refresh", {"auth_mode": "cookie"}).status_code, 401)

    def test_refresh_expiry_never_exceeds_absolute_expiry(self):
        client, _ = login_client()
        deadline = timezone.now() + timedelta(hours=1)
        DeviceSession.objects.update(absolute_expires_at=deadline)
        self.assertEqual(cookie_post(client, "/api/v1/auth/refresh", {"auth_mode": "cookie"}).status_code, 200)
        session = DeviceSession.objects.get()
        self.assertEqual(session.idle_expires_at, deadline)
        self.assertEqual(session.refresh_tokens.filter(consumed_at__isnull=True).get().expires_at, deadline)

    def test_user_and_space_states_invalidate_access_and_refresh(self):
        changes = [("user", "is_active", False), ("user", "deleted_at", timezone.now()),
                   ("tenant", "status", "disabled"), ("tenant", "deleted_at", timezone.now()),
                   ("member", "status", "revoked"), ("member", "deleted_at", timezone.now())]
        for kind, field, value in changes:
            with self.subTest(kind=kind, field=field):
                client, _ = login_client()
                target = {"user": self.alice, "tenant": self.alice.tenant,
                          "member": TenantMember.objects.get(user=self.alice, tenant=self.alice.tenant)}[kind]
                old = getattr(target, field)
                setattr(target, field, value)
                target.save(update_fields=[field])
                self.assertEqual(client.get("/api/v1/auth/me").status_code, 401)
                self.assertEqual(cookie_post(client, "/api/v1/auth/refresh", {"auth_mode": "cookie"}).status_code, 401)
                setattr(target, field, old)
                target.save(update_fields=[field])

    def test_tenant_selector_never_exposes_another_personal_space(self):
        client, _ = login_client()
        TenantMember.objects.create(user=self.alice, tenant=self.bob.tenant, role="owner")
        self.assertEqual(client.get("/api/v1/auth/me", HTTP_X_TENANT_ID=str(self.bob.tenant_id)).status_code, 401)
        items = client.get("/api/v1/tenants").json()["data"]["items"]
        self.assertNotIn(self.bob.tenant_id, [item["id"] for item in items])

    def test_personal_members_cannot_be_added_or_revoked_by_api(self):
        client, _ = login_client()
        path = f"/api/v1/tenants/{self.alice.tenant_id}/members"
        response = cookie_post(client, path, {"user_id": self.bob.pk})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "personal_space_not_shareable")

    def test_logout_only_revokes_current_device(self):
        first, _ = login_client()
        second, _ = login_client()
        self.assertEqual(cookie_post(first, "/api/v1/auth/logout").status_code, 200)
        self.assertEqual(first.get("/api/v1/auth/me").status_code, 401)
        self.assertEqual(second.get("/api/v1/auth/me").status_code, 200)

    def test_logout_with_expired_access_still_revokes_refresh(self):
        client, _ = login_client()
        refresh = client.cookies[REFRESH_COOKIE].value
        del client.cookies[ACCESS_COOKIE]
        self.assertEqual(cookie_post(client, "/api/v1/auth/logout").status_code, 200)
        self.assertIsNone(rotate_refresh(refresh))

    def test_logout_all_revokes_devices_and_legacy_credentials(self):
        first, _ = login_client()
        second, _ = login_client()
        bob, _ = login_client("bob")
        issue_tokens(self.alice)
        self.assertEqual(cookie_post(first, "/api/v1/auth/logout-all").status_code, 200)
        self.assertEqual(second.get("/api/v1/auth/me").status_code, 401)
        self.assertEqual(bob.get("/api/v1/auth/me").status_code, 200)
        self.assertFalse(AuthToken.objects.filter(user=self.alice, is_revoked=False).exists())

    def test_password_change_revokes_all_credentials(self):
        first, _ = login_client()
        second, _ = login_client()
        issue_tokens(self.alice)
        response = cookie_post(first, "/api/v1/auth/change-password", {"old_password": "password123", "new_password": "newpassword"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(second.get("/api/v1/auth/me").status_code, 401)
        self.assertFalse(AuthToken.objects.filter(user=self.alice, is_revoked=False).exists())
        self.assertEqual(cookie_post(second, "/api/v1/auth/refresh", {"auth_mode": "cookie"}).status_code, 401)

    def test_empty_new_password_does_not_revoke_sessions(self):
        client, _ = login_client()
        response = cookie_post(client, "/api/v1/auth/change-password", {"old_password": "password123", "new_password": ""})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(client.get("/api/v1/auth/me").status_code, 200)

    def test_legacy_bearer_login_refresh_and_api_key_still_work(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post("/api/v1/auth/login", {"username": "alice", "password": "password123"}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        tokens = response.json()["data"]
        self.assertEqual(client.get("/api/v1/auth/me", HTTP_AUTHORIZATION=f"Bearer {tokens['token']}").status_code, 200)
        response = client.post("/api/v1/auth/refresh", {"refresh_token": tokens["refresh_token"]}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("token", response.json()["data"])
        self.assertFalse(DeviceSession.objects.exists())
        self.assertEqual(client.get("/api/v1/auth/validate", HTTP_X_API_KEY=self.alice.tenant.api_key).json()["data"]["valid"], True)

    def test_mixed_headers_cannot_bypass_csrf_for_refresh_or_logout(self):
        client, _ = login_client()
        for header in [{"HTTP_AUTHORIZATION": "invalid"}, {"HTTP_X_API_KEY": "invalid"}]:
            for route in ["refresh", "logout"]:
                with self.subTest(header=header, route=route):
                    response = client.post(f"/api/v1/auth/{route}", {}, content_type="application/json", **header)
                    self.assertEqual(response.status_code, 403)
        self.assertEqual(client.get("/api/v1/auth/me").status_code, 200)

    def test_preferences_get_is_read_only_and_patch_preserves_other_fields(self):
        client, _ = login_client()
        before = User.objects.get(pk=self.alice.pk).updated_at
        self.assertEqual(client.get("/api/v1/auth/me/preferences").status_code, 200)
        self.assertEqual(User.objects.get(pk=self.alice.pk).updated_at, before)
        cookie_post(client, "/api/v1/auth/me/preferences", {"language": "zh"})
        response = client.patch("/api/v1/auth/me/preferences", {"theme": "dark"}, content_type="application/json", HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.get(pk=self.alice.pk).preferences, {"language": "zh", "theme": "dark"})

    def test_revocation_during_gate_wait_blocks_password_and_preference_mutation(self):
        from accounts.device_sessions import locked_user as original_locked_user
        for route, data in [("change-password", {"old_password": "password123", "new_password": "other"}),
                            ("me/preferences", {"language": "zz"})]:
            client, response = login_client()
            session_id = response.json()["data"]["device"]["id"]
            def revoke_while_locked(user_id):
                user = original_locked_user(user_id)
                DeviceSession.objects.filter(pk=session_id).update(revoked_at=timezone.now())
                return user
            with patch("accounts.views.locked_user", side_effect=revoke_while_locked):
                result = cookie_post(client, f"/api/v1/auth/{route}", data)
            self.assertEqual(result.status_code, 401)
        self.assertNotIn("language", User.objects.get(pk=self.alice.pk).preferences)

    def test_device_gate_timeout_has_bounded_503_response(self):
        from filelock import Timeout
        client = Client(enforce_csrf_checks=True)
        client.get("/api/v1/auth/csrf")
        with patch("accounts.device_sessions.FileLock.acquire", side_effect=Timeout("private-path")):
            response = cookie_post(client, "/api/v1/auth/login", {"username": "alice", "password": "password123", "auth_mode": "cookie"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "auth_busy")
        self.assertNotIn("private-path", response.content.decode())
        self.assertFalse(DeviceSession.objects.exists())

    @override_settings(ALLOW_AUTO_SETUP=True)
    def test_cookie_auto_setup_reuses_the_device_gate_without_recursive_lock(self):
        Tenant.objects.all().delete()
        User.objects.all().delete()
        client = Client(enforce_csrf_checks=True)
        client.get("/api/v1/auth/csrf")
        response = cookie_post(client, "/api/v1/auth/auto-setup", {"auth_mode": "cookie"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["data"]["auth_mode"], "cookie")
        self.assertEqual(DeviceSession.objects.count(), 1)
        self.assertEqual(AuthToken.objects.count(), 0)

    def test_auth_mode_requires_a_supported_scalar(self):
        client = Client()
        for mode in ["native", ["cookie"], {"mode": "cookie"}]:
            response = client.post("/api/v1/auth/login", {"auth_mode": mode}, content_type="application/json")
            self.assertEqual(response.status_code, 400)

    def test_cookie_creation_failure_rolls_back_registration(self):
        client = Client()
        before = User.objects.count(), Tenant.objects.count()
        with patch("accounts.views.create_device_session", side_effect=RuntimeError("injected")):
            with self.assertRaises(RuntimeError):
                client.post("/api/v1/auth/register", {"username": "bad", "password": "password123", "auth_mode": "cookie"}, content_type="application/json")
        self.assertEqual((User.objects.count(), Tenant.objects.count()), before)


@override_settings(DEBUG=True)
class DeviceRefreshConcurrencyTests(TransactionTestCase):
    def test_two_concurrent_refreshes_issue_once_then_revoke_on_replay(self):
        create_personal_user(username="alice", email="alice@example.test", password_hash=hash_password("password123"))
        client, _ = login_client()
        raw = client.cookies[REFRESH_COOKIE].value
        barrier = Barrier(2)
        def refresh():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                return rotate_refresh(raw) is not None
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _index: refresh(), range(2)))
        self.assertEqual(results.count(True), 1)
        self.assertEqual(DeviceRefreshToken.objects.count(), 2)
        self.assertEqual(DeviceSession.objects.get().revoke_reason, "refresh_replay")

    def test_two_device_preference_updates_do_not_lose_different_fields(self):
        user = create_personal_user(username="alice", email="alice@example.test", password_hash=hash_password("password123"))
        first, _ = login_client(name="A")
        second, _ = login_client(name="B")
        barrier = Barrier(2)
        def update(pair):
            client, data = pair
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                return cookie_post(client, "/api/v1/auth/me/preferences", data).status_code
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(update, [(first, {"theme": "dark"}), (second, {"language": "zh"})]))
        self.assertEqual(statuses, [200, 200])
        user.refresh_from_db()
        self.assertEqual(user.preferences, {"theme": "dark", "language": "zh"})


@override_settings(DEBUG=True)
class DeviceStreamGuardTests(TestCase):
    def setUp(self):
        self.user = create_personal_user(username="alice", email="alice@example.test", password_hash=hash_password("password123"))
        self.client, login = login_client()
        self.device_id = login.json()["data"]["device"]["id"]
        self.request = RequestFactory().get("/stream", HTTP_X_TENANT_ID=str(self.user.tenant_id))
        self.request.COOKIES[ACCESS_COOKIE] = self.client.cookies[ACCESS_COOKIE].value
        require_auth(self.request)
        self.closed = []

    def wrap(self, callback=None):
        def source():
            try:
                yield b"first"
                if callback:
                    callback()
                yield b"second"
            finally:
                self.closed.append(True)
        response = StreamingHttpResponse(source(), content_type="text/event-stream")
        return DeviceSessionCsrfMiddleware(lambda _request: None).process_response(self.request, response)

    @patch("accounts.device_sessions.STREAM_RECHECK_SECONDS", 0)
    def test_revoked_device_stops_open_stream_and_closes_source(self):
        response = self.wrap(lambda: DeviceSession.objects.filter(pk=self.device_id).update(revoked_at=timezone.now()))
        self.assertEqual(list(response.streaming_content), [b"first"])
        self.assertEqual(self.closed, [True])
        response.close()

    @patch("accounts.device_sessions.STREAM_RECHECK_SECONDS", 0)
    def test_membership_revocation_stops_open_stream(self):
        response = self.wrap(lambda: TenantMember.objects.filter(user=self.user, tenant=self.user.tenant).update(status="revoked"))
        self.assertEqual(list(response.streaming_content), [b"first"])
        self.assertEqual(self.closed, [True])
        response.close()

    @patch("accounts.device_sessions.STREAM_RECHECK_SECONDS", 0)
    def test_disabled_user_or_tenant_stops_open_stream(self):
        changes = [lambda: User.objects.filter(pk=self.user.pk).update(is_active=False),
                   lambda: Tenant.objects.filter(pk=self.user.tenant_id).update(status="disabled")]
        for change in changes:
            User.objects.filter(pk=self.user.pk).update(is_active=True)
            Tenant.objects.filter(pk=self.user.tenant_id).update(status="active")
            response = self.wrap(change)
            self.assertEqual(list(response.streaming_content), [b"first"])
            response.close()

    @patch("accounts.device_sessions.STREAM_RECHECK_SECONDS", 0)
    def test_normal_refresh_does_not_break_an_existing_stream(self):
        old_digest = DeviceSession.objects.get(pk=self.device_id).access_digest
        raw_refresh = self.client.cookies[REFRESH_COOKIE].value
        response = self.wrap(lambda: rotate_refresh(raw_refresh))
        self.assertEqual(list(response.streaming_content), [b"first", b"second"])
        self.assertNotEqual(DeviceSession.objects.get(pk=self.device_id).access_digest, old_digest)
        self.assertEqual(self.closed, [True])
        response.close()

    def test_next_chunk_after_a_blocked_interval_revalidates_at_30_seconds(self):
        response = self.wrap(lambda: DeviceSession.objects.filter(pk=self.device_id).update(revoked_at=timezone.now()))
        with patch("accounts.device_sessions.monotonic", side_effect=[100, 100, 131]):
            self.assertEqual(list(response.streaming_content), [b"first"])
        self.assertEqual(self.closed, [True])
        response.close()

    @patch("accounts.device_sessions.STREAM_RECHECK_SECONDS", 0)
    def test_family_user_reassignment_does_not_change_stream_principal(self):
        other = create_personal_user(username="other", email="other@example.test", password_hash=hash_password("password123"))
        response = self.wrap(lambda: DeviceSession.objects.filter(pk=self.device_id).update(user=other))
        self.assertEqual(list(response.streaming_content), [b"first"])
        response.close()

    def test_device_revoked_before_first_iteration_emits_nothing(self):
        response = self.wrap()
        DeviceSession.objects.filter(pk=self.device_id).update(revoked_at=timezone.now())
        self.assertEqual(list(response.streaming_content), [])
        response.close()

    def test_legacy_bearer_stream_remains_unchanged(self):
        token, _ = issue_tokens(self.user)
        request = RequestFactory().get("/stream", HTTP_AUTHORIZATION=f"Bearer {token}")
        require_auth(request)
        response = StreamingHttpResponse([b"legacy"], content_type="text/event-stream")
        original = response._iterator
        result = DeviceSessionCsrfMiddleware(lambda _request: None).process_response(request, response)
        self.assertIs(result._iterator, original)
        self.assertEqual(list(result.streaming_content), [b"legacy"])
        result.close()


@override_settings(DEBUG=True)
class AsyncDeviceStreamGuardTests(TransactionTestCase):
    @patch("accounts.device_sessions.STREAM_RECHECK_SECONDS", 0)
    def test_async_iterator_preserves_refresh_then_revokes_and_acloses_source(self):
        user = create_personal_user(username="alice", email="alice@example.test", password_hash=hash_password("password123"))
        client, login = login_client()
        device_id = login.json()["data"]["device"]["id"]
        raw_refresh = client.cookies[REFRESH_COOKIE].value
        request = RequestFactory().get("/stream", HTTP_X_TENANT_ID=str(user.tenant_id))
        request.COOKIES[ACCESS_COOKIE] = client.cookies[ACCESS_COOKIE].value
        require_auth(request)
        closed = []
        async def source():
            try:
                yield b"first"
                rotated = await sync_to_async(rotate_refresh, thread_sensitive=True)(raw_refresh)
                self.assertIsNotNone(rotated)
                yield b"second"
                await sync_to_async(lambda: DeviceSession.objects.filter(pk=device_id).update(revoked_at=timezone.now()), thread_sensitive=True)()
                yield b"private-third"
            finally:
                closed.append(True)
        response = StreamingHttpResponse(source(), content_type="text/event-stream")
        response = DeviceSessionCsrfMiddleware(lambda _request: None).process_response(request, response)
        self.assertTrue(response.is_async)
        async def collect():
            return [part async for part in response.streaming_content]
        self.assertEqual(async_to_sync(collect)(), [b"first", b"second"])
        self.assertEqual(closed, [True])
        response.close()
