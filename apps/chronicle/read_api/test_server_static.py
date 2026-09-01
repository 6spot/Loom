from __future__ import annotations

import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from server import handler_class


class ChronicleServerStaticBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Port 1 is intentionally unusable. Static/UI requests must still work
        # because the server must not connect to PostgreSQL for those paths.
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

    def test_spa_and_module_requests_succeed_with_unusable_database_url(self) -> None:
        for path, expected_type, marker in (
            ("/timeline", "text/html", b"Chronicle"),
            ("/search", "text/html", b"Chronicle"),
            ("/events/01a05cd7-439d-7071-bf00-86c664886b06", "text/html", b"Chronicle"),
            ("/route_safe.mjs", "text/javascript", b"safeRouteFor"),
            ("/search_ui.mjs", "text/javascript", b"renderSearch"),
        ):
            with self.subTest(path=path):
                with self._get(path) as response:
                    self.assertEqual(response.status, 200)
                    self.assertTrue(response.headers["Content-Type"].startswith(expected_type))
                    self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                    self.assertIn(marker, response.read())

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
