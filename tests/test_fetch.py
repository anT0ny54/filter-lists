import functools
import shutil
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
        cls.server.server_close()
        shutil.rmtree(cls.root, ignore_errors=True)

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
        self.assertTrue(all(len(item["sha256"]) == 64 for item in stats["results"]))

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

class FetchBudgetWaveTests(unittest.TestCase):
    setUpClass = FetchTests.setUpClass
    tearDownClass = FetchTests.tearDownClass

    def test_global_budget_queues_sources_instead_of_marking_them_failed(self):
        urls = [FetchTests.base + "/main.txt"] * 11
        # Use unique paths that all resolve to the same fixture, while the
        # global budget allows only two 1-byte-sized reservations at once.
        urls = [FetchTests.base + f"/child.txt?source={i}" for i in range(5)]
        started = __import__("time").monotonic()
        with tempfile.TemporaryDirectory() as tmp:
            files, stats = collect_sources(
                urls, Path(tmp), started, 8, lambda _: None,
                total_timeout=30,
                max_include_depth=0,
                max_download_bytes=64,
                max_total_download_bytes=256,
                max_total_sources=20,
            )
        self.assertEqual(stats["root_requested"], 5)
        self.assertEqual(stats["root_successful"], 5)
        self.assertEqual(stats["root_failed"], 0)
        self.assertEqual(len(files), 5)
        self.assertLessEqual(stats["total_download_bytes"], 256)

    def test_budget_parallelism_is_bounded_by_global_budget(self):
        started = __import__("time").monotonic()
        with tempfile.TemporaryDirectory() as tmp:
            _, stats = collect_sources(
                [FetchTests.base + "/child.txt"], Path(tmp), started, 32, lambda _: None,
                total_timeout=30,
                max_include_depth=0,
                max_download_bytes=50,
                max_total_download_bytes=500,
                max_total_sources=10,
            )
        self.assertEqual(stats["max_parallel_by_budget"], 10)
        self.assertEqual(stats["parallelism"], 10)
