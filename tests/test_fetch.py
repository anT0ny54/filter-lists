import functools
import gzip
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
from config import canonical_url
from fetch import collect_sources, include_urls, validate_download


from _helpers import curl_stream_limits_available


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

    def test_curl_stream_size_limit_version_gate(self):
        version_cases = [
            ("curl 8.3.0 (x86_64-pc-linux-gnu)", False),
            ("curl 8.4.0 (x86_64-pc-linux-gnu)", True),
            ("curl unknown-version", False),
        ]
        for output, expected_supported in version_cases:
            with self.subTest(output=output):
                supported, _ = fetch._curl_size_limit_status_from_output(output)
                self.assertEqual(supported, expected_supported)

    def test_download_fails_closed_when_curl_cannot_enforce_stream_size_limits(self):
        reason = "curl-version-too-old: 8.3.0; curl >= 8.4.0 is required for safe download-size limits"
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "source.txt"
            with patch.object(fetch, "_curl_stream_size_limit_status", return_value=(False, reason)), \
                 patch.object(fetch, "_public_address_for_url") as resolve, \
                 patch.object(fetch.subprocess, "run") as run:
                ok, actual_reason, transferred = fetch.download(
                    "http://example.test/list.txt", output, 10, 1024
                )
        self.assertFalse(ok)
        self.assertEqual(actual_reason, reason)
        self.assertEqual(transferred, 0)
        resolve.assert_not_called()
        run.assert_not_called()
        self.assertFalse(output.exists())

    def test_dns_resolution_preserves_an_explicit_zero_port(self):
        fetch._ADDRESS_PIN_CACHE.pop(("example.test", 0), None)
        try:
            with patch.object(fetch.socket, "getaddrinfo", return_value=[
                (fetch.socket.AF_INET, fetch.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
            ]) as resolver:
                address, reason = fetch._public_address_for_url("http://example.test:0/list.txt")
            self.assertEqual((address, reason), ("93.184.216.34", ""))
            resolver.assert_called_once_with("example.test", 0, type=fetch.socket.SOCK_STREAM)
        finally:
            fetch._ADDRESS_PIN_CACHE.pop(("example.test", 0), None)

    @unittest.skipUnless(curl_stream_limits_available(), "curl >= 8.4.0 required for transfer-limit integration tests")
    def test_download_preserves_an_explicit_zero_port_in_dns_pin(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "source.txt"
            headers = output.with_suffix(output.suffix + ".headers")
            response = type("Proc", (), {"returncode": 0, "stdout": "200", "stderr": ""})()

            def fake_run(command, **kwargs):
                output.write_text("||example.com^\n! enough padding for validation\n", encoding="utf-8")
                headers.write_text("HTTP/1.1 200 OK\r\n\r\n", encoding="iso-8859-1")
                self.assertIn("example.test:0:93.184.216.34", command)
                return response

            with patch.object(fetch, "_public_address_for_url", return_value=("93.184.216.34", "")), \
                 patch.object(fetch.subprocess, "run", side_effect=fake_run):
                ok, reason, _ = fetch.download("http://example.test:0/list.txt", output, 10, 1024)

        self.assertTrue(ok, reason)

    @unittest.skipUnless(curl_stream_limits_available(), "curl >= 8.4.0 required for transfer-limit integration tests")
    def test_encoded_response_is_not_decompressed_past_download_budget(self):
        expanded = b"||example.com^\n" + (b"x" * (2 * 1024 * 1024))
        encoded = gzip.compress(expanded)
        observed_accept_encoding = []

        class GzipHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                observed_accept_encoding.append(self.headers.get("Accept-Encoding"))
                self.send_response(200)
                # Deliberately ignore the client's identity preference to model
                # a misconfigured or hostile server.
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, *_args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), GzipHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / "encoded.txt"
                url = f"http://example.test:{server.server_port}/feed"
                with patch.object(fetch, "_public_address_for_url", return_value=("127.0.0.1", "")):
                    ok, reason, transferred = fetch.download(url, output, 10, 16 * 1024)
                self.assertFalse(ok)
                self.assertEqual(reason, "unsupported-content-encoding")
                self.assertEqual(observed_accept_encoding, ["identity"])
                self.assertEqual(transferred, len(encoded))
                self.assertLess(transferred, 16 * 1024)
                self.assertFalse(output.exists())
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

    @unittest.skipUnless(curl_stream_limits_available(), "curl >= 8.4.0 required for transfer-limit integration tests")
    def test_chunked_response_is_stopped_at_download_budget(self):
        payload = b"x" * (256 * 1024)

        class ChunkedHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                for offset in range(0, len(payload), 1024):
                    chunk = payload[offset:offset + 1024]
                    try:
                        self.wfile.write(f"{len(chunk):x}\r\n".encode("ascii") + chunk + b"\r\n")
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        break

            def log_message(self, *_args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ChunkedHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / "chunked.txt"
                url = f"http://example.test:{server.server_port}/feed"
                with patch.object(fetch, "_public_address_for_url", return_value=("127.0.0.1", "")):
                    ok, reason, transferred = fetch.download(url, output, 10, 16 * 1024)
                self.assertFalse(ok, reason)
                self.assertIn("size", reason.lower())
                self.assertNotIn("curl-version-too-old", reason)
                self.assertLessEqual(transferred, 16 * 1024)
                self.assertFalse(output.exists())
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

    @unittest.skipUnless(curl_stream_limits_available(), "curl >= 8.4.0 required for transfer-limit integration tests")
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
                ok, reason, transferred = fetch.download("http://example.test/start", output, 10, 1024)

        self.assertFalse(ok)
        self.assertEqual(reason, "redirect-blocked-non-public-address")
        self.assertEqual(transferred, 0)
        self.assertEqual(len(calls), 1)
        self.assertIn("--resolve", calls[0])
        self.assertIn("--noproxy", calls[0])
        self.assertNotIn("--location", calls[0])

    @unittest.skipUnless(curl_stream_limits_available(), "curl >= 8.4.0 required for transfer-limit integration tests")
    def test_failed_transfer_reports_bytes_from_deleted_partial_output(self):
        body = b"||example.com^\npartial transfer body"
        response = type(
            "Proc",
            (),
            {"returncode": 18, "stdout": "", "stderr": "curl: (18) partial file"},
        )()

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "source.txt"

            def fake_run(command, **kwargs):
                output.write_bytes(body)
                return response

            with patch.object(fetch, "_public_address_for_url", return_value=("93.184.216.34", "")), \
                 patch.object(fetch.subprocess, "run", side_effect=fake_run):
                ok, reason, transferred = fetch.download("http://example.test/list", output, 10, 1024)

        self.assertFalse(ok)
        self.assertEqual(reason, "curl: (18) partial file")
        self.assertEqual(transferred, len(body))
        self.assertFalse(output.exists())

    @unittest.skipUnless(curl_stream_limits_available(), "curl >= 8.4.0 required for transfer-limit integration tests")
    def test_redirect_bodies_share_the_per_source_byte_budget(self):
        calls = []
        redirect_body = b"r" * 40
        final_body = b"||example.com^\n!! enough padding for validation\n"
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
                    output.write_bytes(redirect_body)
                    headers.write_text(
                        "HTTP/1.1 302 Found\r\n"
                        "Location: https://example.org/final\r\n\r\n",
                        encoding="iso-8859-1",
                    )
                else:
                    output.write_bytes(final_body)
                    headers.write_text("HTTP/1.1 200 OK\r\n\r\n", encoding="iso-8859-1")
                return proc

            with patch.object(fetch, "_public_address_for_url", return_value=("93.184.216.34", "")), \
                 patch.object(fetch.subprocess, "run", side_effect=fake_run):
                ok, reason, transferred = fetch.download("http://example.com/start", output, 10, 100)

        self.assertTrue(ok, reason)
        self.assertEqual(transferred, len(redirect_body) + len(final_body))
        self.assertEqual(calls[0][calls[0].index("--max-filesize") + 1], "100")
        self.assertEqual(calls[1][calls[1].index("--max-filesize") + 1], str(100 - len(redirect_body)))

    @unittest.skipUnless(curl_stream_limits_available(), "curl >= 8.4.0 required for transfer-limit integration tests")
    def test_redirect_that_consumes_budget_stops_before_next_request(self):
        calls = []
        response = type("Proc", (), {"returncode": 0, "stdout": "302", "stderr": ""})()

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "source.txt"
            headers = output.with_suffix(output.suffix + ".headers")

            def fake_run(command, **kwargs):
                calls.append(command)
                output.write_bytes(b"x" * 40)
                headers.write_text(
                    "HTTP/1.1 302 Found\r\n"
                    "Location: https://example.org/final\r\n\r\n",
                    encoding="iso-8859-1",
                )
                return response

            with patch.object(fetch, "_public_address_for_url", return_value=("93.184.216.34", "")), \
                 patch.object(fetch.subprocess, "run", side_effect=fake_run):
                ok, reason, transferred = fetch.download("http://example.com/start", output, 10, 40)

        self.assertFalse(ok)
        self.assertEqual(reason, "download-size-limit-exceeded")
        self.assertEqual(transferred, 40)
        self.assertEqual(len(calls), 1)
        self.assertFalse(output.exists())

    @unittest.skipUnless(curl_stream_limits_available(), "curl >= 8.4.0 required for transfer-limit integration tests")
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
                ok, reason, transferred = fetch.download("http://example.com/start", output, 10, 1024)
                self.assertTrue(ok)
                self.assertEqual(reason, "")
                self.assertEqual(len(calls), 2)
                self.assertTrue(output.exists())
                self.assertNotIn("--location", calls[0])
                self.assertEqual(output.read_text(encoding="utf-8").splitlines()[0], "||example.com^")
                self.assertEqual(transferred, output.stat().st_size)


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

    @unittest.skipUnless(curl_stream_limits_available(), "curl >= 8.4.0 required for transfer-limit integration tests")
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
            return True, "", output.stat().st_size

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

    @unittest.skipUnless(curl_stream_limits_available(), "curl >= 8.4.0 required for transfer-limit integration tests")
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

    def test_include_cycle_at_source_limit_does_not_count_as_explosion(self):
        url = "https://example.com/root"

        def fake_download(_url, output, _timeout, _max_download_bytes):
            output.write_text(
                f"!#include {url}\n||root.example^\n! enough padding for validation\n",
                encoding="utf-8",
            )
            return True, "", output.stat().st_size

        with tempfile.TemporaryDirectory() as tmp, patch.object(fetch, "download", side_effect=fake_download):
            files, stats = collect_sources(
                [url], Path(tmp), time.monotonic(), 1, lambda _: None,
                total_timeout=10, max_include_depth=5, max_download_bytes=1024,
                max_total_download_bytes=1024, max_total_sources=1,
            )

        self.assertEqual(len(files), 1)
        self.assertFalse(stats["source_limit_reached"])
        self.assertEqual((stats["successful"], stats["failed"], stats["requested"]), (1, 0, 1))
        self.assertEqual([item["url"] for item in stats["results"]], [url])

    def test_source_limit_marks_only_unvisited_include_after_a_cycle(self):
        root = "https://example.com/root"
        child = "https://example.com/child"

        def fake_download(_url, output, _timeout, _max_download_bytes):
            output.write_text(
                f"!#include {root}\n!#include {child}\n||root.example^\n! enough padding for validation\n",
                encoding="utf-8",
            )
            return True, "", output.stat().st_size

        with tempfile.TemporaryDirectory() as tmp, patch.object(fetch, "download", side_effect=fake_download):
            _, stats = collect_sources(
                [root], Path(tmp), time.monotonic(), 1, lambda _: None,
                total_timeout=10, max_include_depth=5, max_download_bytes=1024,
                max_total_download_bytes=1024, max_total_sources=1,
            )

        results = {item["url"]: item for item in stats["results"]}
        self.assertTrue(stats["source_limit_reached"])
        self.assertEqual(results[root]["status"], "ok")
        self.assertEqual(results[child]["reason"], "source-limit")
        self.assertEqual(stats["failed"], 1)


class FetchSchedulingTests(unittest.TestCase):
    def test_include_order_is_deterministic_under_source_limit(self):
        def run_with_delay(root_a_delay, root_z_delay):
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)

                def fake_download(url, output, timeout, max_download_bytes):
                    if url.endswith("/root-a"):
                        time.sleep(root_a_delay)
                        content = "!#include https://example.com/a-child\n||root-a.example^\n"
                    elif url.endswith("/root-z"):
                        time.sleep(root_z_delay)
                        content = "!#include https://example.com/z-child\n||root-z.example^\n"
                    elif url.endswith("/a-child"):
                        content = "||a-child.example^\n! padding for validation\n"
                    else:
                        content = "||z-child.example^\n! padding for validation\n"
                    output.write_text(content, encoding="utf-8")
                    return True, "", output.stat().st_size

                with patch.object(fetch, "download", side_effect=fake_download):
                    files, stats = collect_sources(
                        ["https://example.com/root-z", "https://example.com/root-a"],
                        tmp_path,
                        time.monotonic(),
                        2,
                        lambda _: None,
                        total_timeout=10,
                        max_include_depth=1,
                        max_download_bytes=1024,
                        max_total_download_bytes=4096,
                        max_total_sources=3,
                    )

                results = {item["url"]: item for item in stats["results"]}
                return files, results, stats

        _, first, first_stats = run_with_delay(0.03, 0.001)
        _, second, second_stats = run_with_delay(0.001, 0.03)

        self.assertEqual(set(first), set(second))
        self.assertEqual(first["https://example.com/a-child"]["status"], "ok")
        self.assertEqual(first["https://example.com/z-child"]["reason"], "source-limit")
        self.assertEqual(second["https://example.com/a-child"]["status"], "ok")
        self.assertEqual(second["https://example.com/z-child"]["reason"], "source-limit")
        self.assertEqual(first_stats["visited"], second_stats["visited"])

    def test_unattempted_duplicate_include_is_reported_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            def fake_download(url, output, timeout, max_download_bytes):
                output.write_text("!#include https://example.com/shared-child\n||root.example^\n", encoding="utf-8")
                return True, "", output.stat().st_size

            with patch.object(fetch, "download", side_effect=fake_download):
                _, stats = collect_sources(
                    ["https://example.com/root-a", "https://example.com/root-b"],
                    tmp_path,
                    time.monotonic(),
                    2,
                    lambda _: None,
                    total_timeout=10,
                    max_include_depth=1,
                    max_download_bytes=1024,
                    max_total_download_bytes=4096,
                    max_total_sources=2,
                )

        child_results = [x for x in stats["results"] if x["url"] == "https://example.com/shared-child"]
        self.assertEqual(len(child_results), 1)
        self.assertEqual(child_results[0]["reason"], "source-limit")



class FetchBudgetWaveTests(unittest.TestCase):
    setUpClass = FetchTests.setUpClass
    tearDownClass = FetchTests.tearDownClass

    def allow_local_fixture_fetch(self):
        return patch.object(fetch, "_public_address_for_url", return_value=("127.0.0.1", ""))

    @unittest.skipUnless(curl_stream_limits_available(), "curl >= 8.4.0 required for transfer-limit integration tests")
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
            return True, "", output.stat().st_size

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

    def test_rejected_responses_consume_global_download_budget(self):
        """Invalid but fully transferred responses must still burn budget.

        Regression: only accepted files incremented
        `stats["total_download_bytes"]`, so several large invalid responses
        (e.g. HTML error pages) could transfer far more than
        `max_total_download_bytes` before fetching stopped.
        """
        original_download = fetch.download
        body = b"<!doctype html><html><head><title>404</title></head><body>" + b"x" * 1024
        budget = (2 * len(body)) + len(body) // 2  # 2.5 bodies

        def invalid_download(url, output, timeout, max_download_bytes):
            output.write_bytes(body)
            return True, "", len(body)

        try:
            fetch.download = invalid_download
            with tempfile.TemporaryDirectory() as tmp:
                files, stats = collect_sources(
                    [f"https://example.test/invalid-{i}" for i in range(4)],
                    Path(tmp),
                    time.monotonic(),
                    4,
                    lambda _: None,
                    total_timeout=30,
                    max_include_depth=0,
                    max_download_bytes=50 * 1024,
                    max_total_download_bytes=budget,
                    max_total_sources=10,
                )
        finally:
            fetch.download = original_download

        self.assertEqual(files, [])
        self.assertTrue(stats["budget_exhausted"])
        # Two bodies fit, the third transfer trips the budget, and the fourth
        # source is never attempted. Every transferred byte is accounted for,
        # including the two responses that failed validation.
        self.assertEqual(stats["total_download_bytes"], 3 * len(body))
        self.assertEqual(
            sum(item.get("reason") == "global-download-budget-exhausted" for item in stats["results"]),
            1,
        )

    def test_concurrent_requests_near_budget_boundary_get_reserved_limits(self):
        original_download = fetch.download
        child_barrier = threading.Barrier(2)
        limits: dict[str, int] = {}

        def body_of_size(prefix: bytes, size: int) -> bytes:
            if len(prefix) > size:
                raise AssertionError("test fixture body exceeds requested size")
            return prefix + (b"#" * (size - len(prefix)))

        def fake_download(url, output, timeout, max_download_bytes):
            if url == "https://example.test/root":
                body = body_of_size(
                    b"!#include child-a\n!#include child-b\n",
                    50,
                )
            else:
                # Barrier.wait() returns an integer barrier state, not a success flag.
                child_barrier.wait(timeout=5)
                body = body_of_size(b"||example.com^\n", max_download_bytes)
            output.write_bytes(body)
            limits[url] = max_download_bytes
            return True, "", len(body)

        try:
            fetch.download = fake_download
            with tempfile.TemporaryDirectory() as tmp:
                files, stats = collect_sources(
                    ["https://example.test/root"],
                    Path(tmp),
                    time.monotonic(),
                    2,
                    lambda _: None,
                    total_timeout=30,
                    max_include_depth=1,
                    max_download_bytes=60,
                    max_total_download_bytes=130,
                    max_total_sources=10,
                )
        finally:
            fetch.download = original_download

        self.assertEqual(limits["https://example.test/child-a"], 60)
        self.assertEqual(limits["https://example.test/child-b"], 20)
        self.assertEqual(stats["total_download_bytes"], 130)
        self.assertEqual(stats["successful"], 3)
        self.assertFalse(stats["budget_exhausted"])
        self.assertEqual(len(files), 3)

    def test_failed_download_still_contributes_transferred_bytes(self):
        original_download = fetch.download
        partial_size = 47

        def failing_download(url, output, timeout, max_download_bytes):
            return False, "connection reset", partial_size

        try:
            fetch.download = failing_download
            with tempfile.TemporaryDirectory() as tmp:
                files, stats = collect_sources(
                    ["https://example.test/partial-failure"],
                    Path(tmp),
                    time.monotonic(),
                    2,
                    lambda _: None,
                    total_timeout=30,
                    max_include_depth=0,
                    max_download_bytes=1024,
                    max_total_download_bytes=100,
                    max_total_sources=10,
                )
        finally:
            fetch.download = original_download

        result = stats["results"][0]
        self.assertEqual(files, [])
        self.assertEqual(stats["total_download_bytes"], partial_size)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason"], "connection reset")
        self.assertEqual(result["bytes"], partial_size)

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
