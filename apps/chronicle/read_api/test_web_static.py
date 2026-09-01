from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from web_static import WEB_ROOT, web_response


class ChronicleWebStaticTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "index.html").write_text("<main>Chronicle</main>", encoding="utf-8")
        (self.root / "styles.css").write_text("body{}", encoding="utf-8")
        (self.root / "app.mjs").write_text("export const app = true;", encoding="utf-8")
        (self.root / "ui.mjs").write_text("export const ui = true;", encoding="utf-8")
        (self.root / "route_safe.mjs").write_text("export const routeSafe = true;", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_spa_routes_return_shell_without_database(self) -> None:
        for path in (
            "/",
            "/timeline",
            "/timeline/",
            "/events/01a05cd7-439d-7071-bf00-86c664886b06",
            "/entities/01a05cd7-439d-7071-bf00-86c664886b06",
        ):
            with self.subTest(path=path):
                status, content_type, body = web_response("GET", path, root=self.root)
                self.assertEqual(status, 200)
                self.assertEqual(content_type, "text/html; charset=utf-8")
                self.assertIn(b"Chronicle", body)

    def test_assets_are_allowlisted(self) -> None:
        for asset, marker in (
            ("/ui.mjs", b"ui = true"),
            ("/route_safe.mjs", b"routeSafe = true"),
        ):
            with self.subTest(asset=asset):
                status, content_type, body = web_response("GET", asset, root=self.root)
                self.assertEqual(status, 200)
                self.assertEqual(content_type, "text/javascript; charset=utf-8")
                self.assertIn(marker, body)

    def test_unknown_and_traversal_paths_are_not_filesystem_paths(self) -> None:
        for path in (
            "/missing.js",
            "/../persistence/migrations/0001_chronicle_v0.sql",
            "/%2e%2e/persistence/migrations/0001_chronicle_v0.sql",
            "/events/id/extra",
        ):
            with self.subTest(path=path):
                status, _, _ = web_response("GET", path, root=self.root)
                self.assertEqual(status, 404)

    def test_non_get_static_request_is_rejected(self) -> None:
        status, content_type, body = web_response("POST", "/", root=self.root)
        self.assertEqual(status, 405)
        self.assertEqual(content_type, "text/plain; charset=utf-8")
        self.assertEqual(body, b"method not allowed\n")

    def test_production_ui_has_no_artifact_or_database_escape_hatch(self) -> None:
        forbidden = (
            ".artifacts",
            "CHRONICLE_DATABASE_URL",
            "LOOM_DATABASE_URL",
            "postgresql://",
            "persistence/migrations",
        )
        production_files = [
            WEB_ROOT / "index.html",
            WEB_ROOT / "styles.css",
            WEB_ROOT / "app.mjs",
            WEB_ROOT / "ui.mjs",
            WEB_ROOT / "route_safe.mjs",
        ]
        for path in production_files:
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                with self.subTest(path=path.name, token=token):
                    self.assertNotIn(token, text)


if __name__ == "__main__":
    unittest.main()
