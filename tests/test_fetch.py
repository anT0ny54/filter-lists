import functools
import http.server
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fetch
from fetch import canonical_url, collect_sources, include_urls, validate_download


class FetchSecurityTests(unittest.TestCase):
    def test_private_literal_is_blocked_before_curl(self):
        address, reason = fetch._public_address_for_url("http://127.0.0.1:8080/list.txt")
        self.assertIsNone(address)
        self.assertEqual(reason, "blocked-non-public-address")

    def test_localhost_resolution_is_blocked(self):
        address, reason = fetch._public_address_for_url("http://localhost:8080/list.txt")
        self.assertIsNone(address)
        self.assertEqual(reason, "blocked-non-public-address")

    def test_validate_download_reads_only_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "large.txt"
            path.write_bytes(b"||example.com^\n" + (b"x" * (256 * 1024)))
            with patch.object(Path, "read_bytes", side_effect=AssertionError("whole-file read")):
                ok, reason = validate_download(path, 1024 * 1024)
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_mixed_public_private_dns_answer_is_blocked(self):
        with patch.object(fetch.socket, "getaddrinfo", return_value=[
            (fetch.socket.AF_INET, fetch.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)),
            (fetch.socket.AF_INET, fetch.socket.SOCK_STREAM, 6, "", ("10.0.0.1", 80)),
        ]):
            address, reason = fetch._public_address_for_url("http://example.test/list.txt")
        self.assertIsNone(address)
        self.assertEqual(reason, "blocked-non-public-address")

    def test_redirect_to_private_address_is_rejected_before_second_request(self):
        calls = []
        response = type("Proc", (), {"returncode": 0, "stdout": "302", "stderr": ""})()

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "source.txt"
            headers = output.with_suffix(output.suffix + ".headers")

            def fake_run(command, **kwargs):
                calls.append(command)
                headers.write_text(
                    "HTTP/1.1 302 Found\r\n"
                    "Location: http://127.0.0.1/private\r\n"
                    "\r\n",
                    encoding="iso-8859-1",
                )
                return response

            with patch.object(
                fetch,
                "_public_address_for_url",
                side_effect=[("93.184.216.34", ""), (None, "blocked-non-public-address")],
            ), patch.object(fetch.subprocess, "run", side_effect=fake_run):
                ok, reason = fetch.download("http://example.test/start", output, 10, 1024)

        self.assertFalse(ok)
        self.assertEqual(reason, "redirect-blocked-non-public-address")
        self.assertEqual(len(calls), 1)
        self.assertIn("--resolve", calls[0])
        self.assertIn("--noproxy", calls[0])
        self.assertNotIn("--location", calls[0])

    def test_public_redirect_is_followed_one_hop_at_a_time(self):
        calls = []
        responses = [
            type("Proc", (), {"returncode": 0, "stdout": "302", "stderr": ""})(),
            type("Proc", (), {"returncode": 0, "stdout": "200", "stderr": ""})(),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "source.txt"
            headers = output.with_suffix(output.suffix + ".headers")

            def fake_run(command, **kwargs):
                calls.append(command)
                proc = responses.pop(0)
                if proc.stdout == "302":
                    headers.write_text(
                        "HTTP/1.1 302 Found\r\n"
                        "Location: https://example.org/final\r\n"
                        "\r\n",
                        encoding="iso-8859-1",
                    )
                else:
                    output.write_text("||example.com^\n!! enough padding for validation\n", encoding="utf-8")
                    headers.write_text("HTTP/1.1 200 OK\r\n\r\n", encoding="iso-8859-1")
                return proc

            with patch.object(fetch, "_public_address_for_url", return_value=("93.184.216.34", "")), \
                 patch.object(fetch.subprocess, "run", side_effect=fake_run):
                ok, reason = fetch.download("http://example.com/start", output, 10, 1024)
                self.assertTrue(ok)
                self.assertEqual(reason, "")
                self.assertEqual(len(calls), 2)
                self.assertTrue(output.exists())
                self.assertNotIn("--location", calls[0])
                self.assertEqual(output.read_text(encoding="utf-8").splitlines()[0], "||example.com^")


class FetchTests(unittest.TestCase):
    @staticmethod
    def allow_local_fixture_fetch():
        return patch.object(fetch, "_public_address_for_url", return_value=("127.0.0.1", ""))

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
        started = time.monotonic()
        with self.allow_local_fixture_fetch():
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

    def test_timeout_accounts_for_unattempted_queued_sources(self):
        original_download = fetch.download

        def slow_download(url, output, timeout, max_download_bytes):
            time.sleep(0.15)
            output.write_text("||example.com^\n! enough padding for validation\n", encoding="utf-8")
            return True, ""

        try:
            fetch.download = slow_download
            with tempfile.TemporaryDirectory() as tmp:
                files, stats = collect_sources(
                    [f"https://example.test/timeout-{i}" for i in range(3)],
                    Path(tmp),
                    time.monotonic(),
                    1,
                    lambda _: None,
                    total_timeout=0.10,
                    max_include_depth=0,
                    max_download_bytes=1024,
                    max_total_download_bytes=4096,
                    max_total_sources=10,
                )
        finally:
            fetch.download = original_download

        self.assertEqual(len(files), 1)
        self.assertEqual(stats["root_requested"], 3)
        self.assertEqual(stats["root_successful"], 1)
        self.assertEqual(stats["root_failed"], 2)
        self.assertTrue(stats["timed_out"])
        self.assertEqual(len(stats["results"]), 3)
        self.assertEqual(
            sum(item.get("reason") == "global-timeout" for item in stats["results"]),
            2,
        )

    def test_global_source_limit_stops_include_explosion(self):
        started = time.monotonic()
        with self.allow_local_fixture_fetch():
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


class FetchBudgetWaveTests(unittest.TestCase):
    setUpClass = FetchTests.setUpClass
    tearDownClass = FetchTests.tearDownClass

    def allow_local_fixture_fetch(self):
        return patch.object(fetch, "_public_address_for_url", return_value=("127.0.0.1", ""))

    def test_global_budget_queues_sources_instead_of_marking_them_failed(self):
        # Use unique paths that all resolve to the same fixture, while the
        # global budget allows only two 1-byte-sized reservations at once.
        urls = [FetchTests.base + f"/child.txt?source={i}" for i in range(5)]
        started = time.monotonic()
        with self.allow_local_fixture_fetch():
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

    def test_budget_cutoff_records_unattempted_sources_as_failures(self):
        original_download = fetch.download

        def fixed_size_download(url, output, timeout, max_download_bytes):
            output.write_text("||example.com^\n!! padding for budget cutoff\n", encoding="utf-8")
            return True, ""

        try:
            fetch.download = fixed_size_download
            with tempfile.TemporaryDirectory() as tmp:
                files, stats = collect_sources(
                    [f"https://example.test/budget-{i}" for i in range(3)],
                    Path(tmp),
                    time.monotonic(),
                    1,
                    lambda _: None,
                    total_timeout=10,
                    max_include_depth=0,
                    max_download_bytes=50,
                    max_total_download_bytes=88,
                    max_total_sources=10,
                )
        finally:
            fetch.download = original_download

        self.assertEqual(len(files), 2)
        self.assertEqual(stats["root_successful"], 2)
        self.assertEqual(stats["root_failed"], 1)
        self.assertTrue(stats["budget_exhausted"])
        self.assertEqual(
            sum(item.get("reason") == "global-download-budget-exhausted" for item in stats["results"]),
            1,
        )

    def test_budget_parallelism_is_bounded_by_global_budget(self):
        started = time.monotonic()
        with self.allow_local_fixture_fetch():
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
