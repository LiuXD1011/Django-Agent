from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.db import close_old_connections
from django.test import Client, TestCase, TransactionTestCase, override_settings

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


class AutoSetupConcurrencyTests(TransactionTestCase):
    @override_settings(ALLOW_AUTO_SETUP=True)
    def test_concurrent_auto_setup_creates_exactly_one_user(self):
        worker_count = 8
        start = Barrier(worker_count)

        def request_auto_setup():
            close_old_connections()
            client = Client(raise_request_exception=False)
            try:
                start.wait(timeout=5)
                return client.post("/api/v1/auth/auto-setup", content_type="application/json").status_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            statuses = list(executor.map(lambda _index: request_auto_setup(), range(worker_count)))

        self.assertEqual(statuses.count(201), 1)
        self.assertEqual(statuses.count(401), worker_count - 1)
        self.assertNotIn(500, statuses)
        self.assertEqual(User.objects.count(), 1)
