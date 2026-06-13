import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import StorageQuota, User


class AccountTests(TestCase):
    def test_register_creates_user_and_quota(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "username": "alice",
                "phone": "13800000000",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            },
        )
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="alice")
        self.assertTrue(StorageQuota.objects.filter(user=user).exists())

    def test_admin_users_requires_admin(self):
        user = User.objects.create_user(username="bob", password="StrongPass123!")
        self.client.force_login(user)
        response = self.client.get(reverse("accounts:admin_users"))
        self.assertEqual(response.status_code, 302)

    def test_regular_user_menu_contains_settings_without_admin(self):
        user = User.objects.create_user(username="carol", password="StrongPass123!")
        self.client.force_login(user)
        response = self.client.get(reverse("accounts:profile"))

        self.assertContains(response, "user-menu")
        self.assertContains(response, "用户信息")
        self.assertContains(response, "回收站")
        self.assertContains(response, "退出")
        self.assertNotContains(response, "用户管理")

    def test_admin_user_menu_contains_user_management(self):
        user = User.objects.create_user(username="admin", password="StrongPass123!", role=User.ROLE_ADMIN)
        self.client.force_login(user)
        response = self.client.get(reverse("accounts:profile"))

        self.assertContains(response, "用户管理")

    def test_share_routes_are_removed(self):
        user = User.objects.create_user(username="dave", password="StrongPass123!")
        self.client.force_login(user)

        self.assertEqual(self.client.get("/shares/").status_code, 404)
        self.assertEqual(self.client.get("/s/example-token/").status_code, 404)

    def test_profile_avatar_upload_renders_image(self):
        avatar_bytes = (
            b"GIF87a\x01\x00\x01\x00\x80\x01\x00\x00\x00\x00\xff\xff\xff,"
            b"\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
        )
        user = User.objects.create_user(username="erin", password="StrongPass123!")
        self.client.force_login(user)

        with tempfile.TemporaryDirectory() as tmpdir, override_settings(MEDIA_ROOT=Path(tmpdir)):
            response = self.client.post(
                reverse("accounts:profile"),
                {
                    "username": "erin",
                    "phone": "",
                    "avatar": SimpleUploadedFile("avatar.gif", avatar_bytes, content_type="image/gif"),
                },
            )
            self.assertEqual(response.status_code, 302)
            user.refresh_from_db()
            self.assertTrue(user.avatar.name.startswith("avatars/"))

            response = self.client.get(reverse("accounts:profile"))
            self.assertContains(response, "profile-avatar has-image")
            self.assertContains(response, user.avatar.url)

# Create your tests here.
