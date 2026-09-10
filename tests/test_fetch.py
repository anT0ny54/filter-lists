import functools
import http.server
import threading
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from fetch import collect_sources, canonical_url, include_urls


class FetchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="filter-fetch-test-"))
        (cls.root / "main.txt").write_text("! main\n!#include child.txt\n||example.com^\n", encoding="utf-8")
        (cls.root / "child.txt").write_text("||child.example^$script\n", encoding="utf-8")
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(cls.root))
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=5)

    def test_canonical_url_drops_fragment(self):
        self.assertEqual(canonical_url("HTTP://Example.COM/a#frag"), "http://example.com/a")

    def test_nested_include_is_resolved(self):
        self.assertEqual(include_urls(self.root / "main.txt", self.base + "/main.txt"), [self.base + "/child.txt"])

    def test_root_health_is_separate_from_nested_sources(self):
        started = __import__("time").monotonic()
        with tempfile.TemporaryDirectory() as tmp:
            files, stats = collect_sources(
                [self.base + "/main.txt"], Path(tmp), started, 2, lambda _: None,
                total_timeout=30,
                max_include_depth=5,
                max_download_bytes=1024 * 1024,
                max_total_download_bytes=1024 * 1024,
                max_total_sources=10,
            )
        self.assertEqual(len(files), 2)
        self.assertEqual(stats["root_requested"], 1)
        self.assertEqual(stats["root_successful"], 1)
        self.assertEqual(stats["included_successful"], 1)
        self.assertEqual(stats["successful"], 2)

    def test_global_source_limit_stops_include_explosion(self):
        started = __import__("time").monotonic()
        with tempfile.TemporaryDirectory() as tmp:
            _, stats = collect_sources(
                [self.base + "/main.txt"], Path(tmp), started, 2, lambda _: None,
                total_timeout=30,
                max_include_depth=5,
                max_download_bytes=1024 * 1024,
                max_total_download_bytes=1024 * 1024,
                max_total_sources=1,
            )
        self.assertTrue(stats["source_limit_reached"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
