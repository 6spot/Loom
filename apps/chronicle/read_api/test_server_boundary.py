from __future__ import annotations

import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from server import handler_class


class ChronicleSidecarBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Unknown/browser paths must be rejected without a PostgreSQL connection.
        handler = handler_class(
            "host=127.0.0.1 port=1 dbname=invalid user=invalid connect_timeout=1"
        )
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        host, port = cls.server.server_address
        cls.base_url = f"http://{host}:{port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def _get(self, path: str):
        return urlopen(Request(self.base_url + path, method="GET"), timeout=3)

    def test_browser_and_unknown_paths_are_typed_404s_without_database_access(self) -> None:
        for path in ("/", "/history", "/timeline", "/search", "/events/some-id",
                     "/route_safe.mjs", "/search_ui.mjs", "/assets/index.js",
                     "/api/v1/public/no-such-route"):
            for method in ("GET", "POST"):
                with self.subTest(path=path, method=method):
                    with self.assertRaises(HTTPError) as caught:
                        urlopen(Request(self.base_url + path, method=method), timeout=3)
                    response = caught.exception
                    self.assertEqual(response.code, 404)
                    self.assertTrue(response.headers["Content-Type"].startswith("application/json"))
                    self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                    self.assertEqual(json.load(response)["error"]["code"], "not_found")

    def test_healthz_remains_database_independent_json(self) -> None:
        with self._get("/healthz") as response:
            payload = json.load(response)
            self.assertEqual(response.status, 200)
            self.assertEqual(payload, {"status": "ok"})

    def test_v0_routes_remain_database_backed(self) -> None:
        for path in ("/v0/timeline", "/v0/search?q=%E6%9B%B9%E6%93%8D"):
            with self.subTest(path=path):
                with self.assertRaises(HTTPError) as caught:
                    self._get(path)
                error = caught.exception
                self.assertEqual(error.code, 503)
                payload = json.loads(error.read().decode("utf-8"))
                self.assertEqual(payload["schema"], "chronicle.error")
                self.assertEqual(payload["error"]["code"], "database_unavailable")


if __name__ == "__main__":
    unittest.main()
