import tempfile
from pathlib import Path

from django.test import SimpleTestCase, override_settings


class PublicClientAssetsTests(SimpleTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.dist = self.base / "frontend" / "dist"
        for folder in [self.dist, self.dist / "icons", self.dist / "assets", self.dist / "pwa-shell"]:
            folder.mkdir(parents=True, exist_ok=True)
        self.override = override_settings(BASE_DIR=self.base, APP_DATA_DIR=self.base, DEBUG=False)
        self.override.enable()
        self.addCleanup(self.override.disable)

    def test_worker_and_manifest_are_public_and_revalidated(self):
        for name, content_type in [("sw.js", "text/javascript"), ("manifest.webmanifest", "application/manifest+json")]:
            (self.dist / name).write_text("public artifact", encoding="utf8")
            response = self.client.get("/" + name)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Cache-Control"], "no-cache")
            self.assertEqual(response["Content-Type"], content_type)
            self.assertEqual(b"".join(response.streaming_content), b"public artifact")
            response.close()

    def test_versioned_shell_and_icons_have_correct_content(self):
        shell = "shell-" + "a" * 20 + ".html"
        (self.dist / "pwa-shell" / shell).write_text("public shell", encoding="utf8")
        response = self.client.get("/pwa-shell/" + shell)
        self.assertEqual(response.status_code, 200)
        self.assertIn("immutable", response["Cache-Control"])
        response.close()
        (self.dist / "icons" / "icon-192.png").write_bytes(b"fixture-png")
        response = self.client.get("/icons/icon-192.png")
        self.assertEqual(response["Content-Type"], "image/png")
        response.close()

    def test_only_compiled_public_assets_are_served(self):
        (self.dist / "assets" / "index-abcdef.js").write_text("public js", encoding="utf8")
        response = self.client.get("/assets/index-abcdef.js")
        self.assertEqual(response.status_code, 200)
        response.close()
        (self.dist / "assets" / "credentials.json").write_text("secret", encoding="utf8")
        self.assertEqual(self.client.get("/assets/credentials.json").status_code, 404)
        self.assertEqual(self.client.get("/pwa-shell/credentials.html").status_code, 404)
        self.assertEqual(self.client.get("/icons/private.png").status_code, 404)

    def test_vite_generated_underscore_helper_is_served_as_javascript(self):
        name = "_plugin-vue_export-helper-DlAUqK2U.js"
        (self.dist / "assets" / name).write_text("export default {};", encoding="utf8")
        response = self.client.get("/assets/" + name)
        self.assertEqual(response.status_code, 200)
        self.assertIn("javascript", response["Content-Type"])
        self.assertIn("immutable", response["Cache-Control"])
        self.assertEqual(b"".join(response.streaming_content), b"export default {};")
        response.close()
        (self.dist / "assets" / ".private.js").write_text("private", encoding="utf8")
        self.assertEqual(self.client.get("/assets/.private.js").status_code, 404)

    def test_missing_artifact_does_not_return_spa_html(self):
        self.assertEqual(self.client.get("/sw.js").status_code, 404)
        self.assertEqual(self.client.get("/manifest.webmanifest").status_code, 404)

    def test_user_media_is_not_a_client_asset(self):
        (self.base / "media").mkdir()
        (self.base / "media" / "secret.png").write_bytes(b"private")
        self.assertEqual(self.client.get("/assets/secret.png").status_code, 404)
        self.assertEqual(self.client.post("/sw.js").status_code, 405)
