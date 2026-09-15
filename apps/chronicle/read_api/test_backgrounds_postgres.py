"""HTTP integration coverage for the Chronicle background sidecar contract."""

from __future__ import annotations

from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
import uuid
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb
from PIL import Image

HERE = Path(__file__).resolve().parent
PERSISTENCE = HERE.parent / "persistence"
ROOT = HERE.parents[2]
for candidate in (str(HERE), str(PERSISTENCE)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from migrations import apply_migrations  # noqa: E402
from server import handler_class  # noqa: E402


DEFAULT_CONTROL_URL = "postgresql://loom:loom@127.0.0.1:15432/loom_control"


def _control_url() -> str:
    explicit = os.environ.get("LOOM_TEST_POSTGRES_URL")
    url = explicit or DEFAULT_CONTROL_URL
    try:
        with psycopg.connect(url, connect_timeout=2):
            return url
    except psycopg.Error:
        if explicit:
            raise
    subprocess.run(
        ["bash", "tools/postgres-test.sh", "up"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    with psycopg.connect(url, connect_timeout=10):
        return url


def _database_conninfo(control_url: str, database_name: str) -> str:
    params = conninfo_to_dict(control_url)
    params["dbname"] = database_name
    return make_conninfo(**params)


def _image() -> bytes:
    output = BytesIO()
    Image.new("RGB", (4, 3), (60, 100, 140)).save(output, format="PNG")
    return output.getvalue()


def _seed_edition(conn, version: str) -> list[str]:
    paragraph_ids = [f"hp_{index:024x}" for index in range(3)]
    with conn.transaction():
        conn.execute(
            """
            INSERT INTO chronicle.history_editions(
                edition_version, manifest_sha256, content_sha256,
                fragment_count, paragraph_count, manifest, metadata
            ) VALUES (%s, %s, %s, 1, 3, %s, %s)
            """,
            (version, version, version, Jsonb({}), Jsonb({})),
        )
        for ordinal, paragraph_id in enumerate(paragraph_ids):
            conn.execute(
                """
                INSERT INTO chronicle.history_edition_paragraph_index(
                    edition_version, ordinal, paragraph_id, fragment_version,
                    source_paragraph_id, source_ordinal, phase_id,
                    conclusion_ids, content_ref
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    version,
                    ordinal,
                    paragraph_id,
                    "c" * 64,
                    f"source-{ordinal}",
                    ordinal,
                    f"hphase_{ordinal:024x}",
                    Jsonb([]),
                    Jsonb({}),
                ),
            )
    return paragraph_ids


class BackgroundSidecarHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_background_http_{uuid.uuid4().hex}"
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database_name)))
        self.database_url = _database_conninfo(self.control_url, self.database_name)
        self.storage = tempfile.TemporaryDirectory(prefix="chronicle-background-http-")
        self.storage_dir = Path(self.storage.name)
        self.edition = "d" * 64
        with psycopg.connect(self.database_url) as conn:
            apply_migrations(conn)
            self.paragraphs = _seed_edition(conn, self.edition)
        handler = handler_class(
            self.database_url,
            self.storage_dir,
            1024 * 1024,
            1024 * 1024,
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=10)
        self.server.server_close()
        self.storage.cleanup()
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(self.database_name))
            )

    def _request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        content_type: str | None = None,
    ) -> tuple[int, bytes, str]:
        request = Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=body,
            method=method,
        )
        if content_type:
            request.add_header("Content-Type", content_type)
        try:
            with urlopen(request, timeout=10) as response:
                return response.status, response.read(), response.headers.get("Content-Type", "")
        except HTTPError as error:
            try:
                body = error.read()
            finally:
                error.close()
            return error.code, body, error.headers.get("Content-Type", "")

    def test_candidate_save_public_read_disable_and_validation(self) -> None:
        upload_path = (
            "/api/v1/studio/background-assets?"
            + urllib.parse.urlencode(
                {
                    "filename": "river.png",
                    "source": "operator",
                    "era": "late Han",
                    "prompt": "quiet river",
                    "metadata": json.dumps({"license": "internal"}),
                }
            )
        )
        status, body, media = self._request("POST", upload_path, _image(), "image/png")
        self.assertEqual(status, 201, body)
        self.assertIn("application/json", media)
        asset = json.loads(body)["asset"]
        self.assertEqual(asset["format"], "png")

        status, body, _ = self._request(
            "POST",
            f"/api/v1/studio/background-assets/{asset['asset_id']}/versions?filename=river-v2.png",
            _image(),
            "image/png",
        )
        self.assertEqual(status, 201, body)
        self.assertEqual(json.loads(body)["asset"]["version"], 2)

        status, candidate_bytes, media = self._request(
            "GET", f"/api/v1/studio/background-assets/{asset['asset_id']}/preview"
        )
        self.assertEqual((status, media), (200, "image/png"))
        self.assertEqual(candidate_bytes, _image())

        public_path = f"/v0/background-assets/{asset['asset_id']}"
        status, body, _ = self._request("GET", public_path)
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"]["code"], "bad_request")
        candidate_public_path = (
            f"{public_path}?version={self.edition}&paragraph_id={self.paragraphs[0]}"
        )
        status, body, _ = self._request("GET", candidate_public_path)
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"]["code"], "not_found")

        binding_payload = json.dumps(
            {
                "edition_version": self.edition,
                "start_paragraph_id": self.paragraphs[0],
                "end_paragraph_id": self.paragraphs[1],
                "asset_id": asset["asset_id"],
                "asset_version_id": asset["asset_version_id"],
                "display": {"opacity": 0.45, "position": {"x": 0.2, "y": 0.7}},
                "actor": "http-test",
            }
        ).encode("utf-8")
        status, body, _ = self._request(
            "POST", "/api/v1/studio/background-bindings", binding_payload, "application/json"
        )
        self.assertEqual(status, 201, body)
        binding = json.loads(body)["binding"]

        status, body, media = self._request(
            "GET",
            f"/v0/backgrounds?version={self.edition}&paragraph_id={self.paragraphs[0]}",
        )
        self.assertEqual(status, 200, body)
        self.assertIn("application/json", media)
        public = json.loads(body)["background"]
        self.assertEqual(public["binding_id"], binding["binding_id"])
        self.assertNotIn("prompt", public["asset"])
        self.assertEqual(
            public["image_href"],
            f"/api/v1/public/background-assets/{asset['asset_id']}"
            f"?version={self.edition}&paragraph_id={self.paragraphs[0]}",
        )

        status, body, _ = self._request(
            "GET",
            f"/v0/backgrounds/not-a-uuid?version={self.edition}&paragraph_id={self.paragraphs[0]}",
        )
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"]["code"], "not_found")

        status, public_bytes, media = self._request(
            "GET",
            f"{public_path}?version={self.edition}&paragraph_id={self.paragraphs[0]}",
        )
        self.assertEqual((status, media), (200, "image/png"))
        self.assertEqual(public_bytes, _image())

        status, body, _ = self._request(
            "DELETE", f"/api/v1/studio/background-bindings/{binding['binding_id']}"
        )
        self.assertEqual(status, 200, body)
        status, body, _ = self._request(
            "GET",
            f"{public_path}?version={self.edition}&paragraph_id={self.paragraphs[0]}",
        )
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"]["code"], "not_found")

        status, body, _ = self._request(
            "POST", "/api/v1/studio/background-assets?filename=not-image.png", b"<html>no</html>", "image/png"
        )
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"]["code"], "decode_failed")

    def test_unknown_paragraph_and_oversize_upload_fail_without_binding(self) -> None:
        status, body, _ = self._request(
            "POST",
            "/api/v1/studio/background-assets?filename=too-large.png",
            b"x" * (1024 * 1024 + 1),
            "image/png",
        )
        self.assertEqual(status, 413)
        self.assertEqual(json.loads(body)["error"]["code"], "payload_too_large")

        status, body, _ = self._request(
            "POST",
            "/api/v1/studio/background-assets?filename=scene.png",
            _image(),
            "image/png",
        )
        asset = json.loads(body)["asset"]
        payload = json.dumps(
            {
                "edition_version": self.edition,
                "start_paragraph_id": self.paragraphs[0],
                "end_paragraph_id": "hp_ffffffffffffffffffffffff",
                "asset_id": asset["asset_id"],
                "asset_version_id": asset["asset_version_id"],
            }
        ).encode("utf-8")
        status, body, _ = self._request(
            "POST", "/api/v1/studio/background-bindings", payload, "application/json"
        )
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"]["code"], "unknown_paragraph")


if __name__ == "__main__":
    unittest.main()
