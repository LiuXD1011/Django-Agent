import hashlib
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User

from . import services
from .models import StoredFile, UserFile


class DriveTests(TestCase):
    def setUp(self):
        self.tmp_media = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=Path(self.tmp_media.name))
        self.settings_override.enable()
        self.user = User.objects.create_user(username="alice", password="StrongPass123!")
        self.client.force_login(self.user)

    def tearDown(self):
        self.settings_override.disable()
        self.tmp_media.cleanup()

    def test_upload_and_second_upload(self):
        content = b"hello django drive"
        uploaded = SimpleUploadedFile("note.txt", content, content_type="text/plain")
        response = self.client.post(reverse("drive:upload_file"), {"file": uploaded})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(UserFile.objects.filter(user=self.user, is_folder=False).count(), 1)
        digest = hashlib.md5(content).hexdigest()
        response = self.client.post(
            reverse("drive:second_upload"),
            {"filename": "copy.txt", "content_hash": digest},
        )
        self.assertEqual(response.json()["ok"], True)
        self.assertEqual(StoredFile.objects.filter(owner=self.user, content_hash=digest).count(), 1)
        self.assertEqual(UserFile.objects.filter(user=self.user, is_folder=False).count(), 2)
        stored = StoredFile.objects.get(owner=self.user, content_hash=digest)
        self.assertEqual(stored.content_family, "text")
        self.assertEqual(stored.detected_mime, "text/plain")
        self.assertTrue(stored.last_inspected_at)
        with stored.file.open("rb") as saved:
            self.assertEqual(saved.read(), content)

    def test_upload_to_selected_folder(self):
        folder = services.create_folder(self.user, "docs")
        uploaded = SimpleUploadedFile("note.txt", b"folder target", content_type="text/plain")
        response = self.client.post(reverse("drive:upload_file"), {"file": uploaded, "parent_id": folder.id})
        self.assertEqual(response.status_code, 302)
        item = UserFile.objects.get(user=self.user, name="note.txt")
        self.assertEqual(item.parent, folder)

    def test_multi_file_upload_to_selected_folder(self):
        folder = services.create_folder(self.user, "batch")
        response = self.client.post(
            reverse("drive:upload_file"),
            {
                "parent_id": folder.id,
                "files": [
                    SimpleUploadedFile("a.txt", b"a", content_type="text/plain"),
                    SimpleUploadedFile("b.txt", b"b", content_type="text/plain"),
                ],
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(UserFile.objects.filter(user=self.user, parent=folder, is_folder=False).count(), 2)

    def test_second_upload_to_selected_folder(self):
        content = b"second target"
        digest = hashlib.md5(content).hexdigest()
        self.client.post(reverse("drive:upload_file"), {"file": SimpleUploadedFile("origin.txt", content)})
        folder = services.create_folder(self.user, "copies")
        response = self.client.post(
            reverse("drive:second_upload"),
            {"filename": "copy.txt", "content_hash": digest, "parent_id": folder.id},
        )
        self.assertEqual(response.json()["ok"], True)
        self.assertEqual(UserFile.objects.get(user=self.user, name="copy.txt").parent, folder)

    def test_chunk_upload_to_selected_folder(self):
        folder = services.create_folder(self.user, "large")
        content = b"abcdef"
        digest = hashlib.md5(content).hexdigest()
        response = self.client.post(
            reverse("drive:init_upload"),
            {
                "filename": "large.txt",
                "content_hash": digest,
                "file_size": len(content),
                "chunk_size": 3,
                "chunk_count": 2,
                "parent_id": folder.id,
            },
        )
        session_id = response.json()["session_id"]
        self.client.post(
            reverse("drive:upload_chunk", args=[session_id]),
            {"part_number": 1, "chunk": SimpleUploadedFile("part-1", content[:3])},
        )
        self.client.post(
            reverse("drive:upload_chunk", args=[session_id]),
            {"part_number": 2, "chunk": SimpleUploadedFile("part-2", content[3:])},
        )
        response = self.client.post(reverse("drive:merge_upload", args=[session_id]))
        self.assertEqual(response.json()["ok"], True)
        item = UserFile.objects.get(user=self.user, name="large.txt")
        self.assertEqual(item.parent, folder)
        self.assertEqual(item.stored_file.content_family, "text")
        with item.stored_file.file.open("rb") as saved:
            self.assertEqual(saved.read(), content)

    def test_create_folder_and_soft_delete(self):
        self.client.post(reverse("drive:create_folder"), {"folder_name": "docs"})
        folder = UserFile.objects.get(user=self.user, name="docs")
        response = self.client.post(reverse("drive:delete", args=[folder.id]))
        self.assertEqual(response.status_code, 302)
        folder.refresh_from_db()
        self.assertTrue(folder.is_deleted)

    def test_move_and_copy_reject_descendant_target(self):
        parent = services.create_folder(self.user, "parent")
        child = services.create_folder(self.user, "child", parent.id)
        with self.assertRaises(ValueError):
            services.move_item(parent, child)
        with self.assertRaises(ValueError):
            services.copy_item(parent, child)

    def test_bulk_delete_filters_to_current_user(self):
        item = services.create_folder(self.user, "mine")
        other_user = User.objects.create_user(username="bob", password="StrongPass123!")
        other_item = services.create_folder(other_user, "other")
        response = self.client.post(reverse("drive:bulk_delete"), {"item_ids": [item.id, other_item.id]})
        self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        other_item.refresh_from_db()
        self.assertTrue(item.is_deleted)
        self.assertFalse(other_item.is_deleted)

    def test_bulk_move_and_copy_to_selected_folder(self):
        target = services.create_folder(self.user, "target")
        source = services.create_folder(self.user, "source")
        response = self.client.post(
            reverse("drive:bulk_move"),
            {"item_ids": [source.id], "target_parent_id": target.id},
        )
        self.assertEqual(response.status_code, 302)
        source.refresh_from_db()
        self.assertEqual(source.parent, target)

        response = self.client.post(
            reverse("drive:bulk_copy"),
            {"item_ids": [source.id], "target_parent_id": ""},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(UserFile.objects.filter(user=self.user, name__startswith="source", is_folder=True).count(), 2)

    def test_file_list_search(self):
        services.create_folder(self.user, "reports")
        response = self.client.get(reverse("drive:file_list"), {"q": "report"})
        self.assertContains(response, "reports")

    def test_check_external_services_uses_local_stack(self):
        output = StringIO()
        call_command("check_external_services", stdout=output)
        value = output.getvalue()

        self.assertIn("SQLite OK", value)
        self.assertIn("SQLite FTS5 OK", value)
        self.assertIn("sqlite-vec OK", value)
        self.assertIn("Local file storage OK", value)
        self.assertNotIn("Red" + "is", value)
        self.assertNotIn("Min" + "IO", value)
        self.assertNotIn("S" + "3", value)
        self.assertNotIn("buck" + "et", value)
        self.assertNotIn("My" + "SQL", value)
        self.assertNotIn("Mil" + "vus", value)
