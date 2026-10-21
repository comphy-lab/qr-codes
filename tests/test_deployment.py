from __future__ import annotations

from pathlib import Path
from io import BytesIO
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import png

from scripts.verify_deployment import (
    cache_busted_url,
    matches_content,
    matches_png,
    retry_delay_seconds,
    verify_file,
)


class DeploymentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.site = Path(self.directory.name)
        self.path = self.site / "paper" / "index.html"
        self.path.parent.mkdir()
        self.path.write_bytes(b"expected page")

    def check(self, attempts: int = 1, *, nonce: int = 1_700_000_000) -> str | None:
        return verify_file(
            self.path,
            site=self.site,
            origin="https://example.org/qr",
            attempts=attempts,
            nonce=nonce,
        )

    def response(self, body: bytes) -> MagicMock:
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = body
        return response

    @patch("scripts.verify_deployment.urlopen")
    def test_checks_the_public_directory_route_under_the_base_path(self, fetch) -> None:
        fetch.return_value = self.response(b"expected page")
        self.assertIsNone(self.check())
        self.assertEqual(
            fetch.call_args.args[0].full_url,
            "https://example.org/qr/paper/?v=1700000000-0",
        )

    @patch("scripts.verify_deployment.urlopen")
    def test_http_200_with_a_wrong_or_stale_page_is_a_failure(self, fetch) -> None:
        fetch.return_value = self.response(b"unrelated page")
        self.assertIn("content differs", self.check())

    def test_cache_bust_query_is_unique_per_attempt(self) -> None:
        base = "https://example.org/qr/assets/qr/code.svg"
        first = cache_busted_url(base, attempt=0, nonce=42)
        second = cache_busted_url(base, attempt=1, nonce=42)
        self.assertEqual(first, "https://example.org/qr/assets/qr/code.svg?v=42-0")
        self.assertEqual(second, "https://example.org/qr/assets/qr/code.svg?v=42-1")
        self.assertNotEqual(first, second)

    def test_retry_backoff_doubles_until_the_cap(self) -> None:
        self.assertEqual([retry_delay_seconds(n) for n in range(8)], [1, 2, 4, 8, 16, 32, 60, 60])

    def test_allows_only_the_observed_cloudflare_beacon_before_body_end(self) -> None:
        expected = b'<html><body>correct content\n</body>\n</html>\n'
        beacon = (
            b'<script type="module" src="https://static.cloudflareinsights.com/beacon.min.js/v123abc" '
            b'integrity="sha512-YWJjZA==" data-cf-beacon=\'{"token":"public-test-token"}\' '
            b'crossorigin="anonymous"></script>\n'
        )
        actual = expected.replace(b'</body>', beacon + b'</body>')
        self.assertTrue(matches_content(actual, expected, html=True))
        for changed in (
            actual.replace(b'correct content', b'wrong content'),
            actual.replace(b'static.cloudflareinsights.com', b'example.org'),
            actual.replace(b'></script>', b'>alert(1)</script>'),
            actual.replace(b'<script ', b'<script onload="alert(1)" '),
            actual.replace(b'</body>', beacon + b'</body>'),
        ):
            self.assertFalse(matches_content(changed, expected, html=True))
        self.assertFalse(matches_content(actual, expected, html=False))

    def test_png_recompression_must_preserve_dimensions_and_every_pixel(self) -> None:
        indexed = BytesIO()
        png.Writer(2, 1, palette=[(103, 35, 108), (255, 255, 255)]).write(indexed, [[0, 1]])
        rgb = BytesIO()
        png.Writer(2, 1, greyscale=False).write(rgb, [[103, 35, 108, 255, 255, 255]])
        self.assertNotEqual(indexed.getvalue(), rgb.getvalue())
        self.assertTrue(matches_png(rgb.getvalue(), indexed.getvalue()))
        changed = BytesIO()
        png.Writer(2, 1, greyscale=False).write(changed, [[104, 35, 108, 255, 255, 255]])
        self.assertFalse(matches_png(changed.getvalue(), indexed.getvalue()))
        resized = BytesIO()
        png.Writer(1, 2, greyscale=False).write(resized, [[103, 35, 108], [255, 255, 255]])
        self.assertFalse(matches_png(resized.getvalue(), indexed.getvalue()))
        self.assertFalse(matches_png(b'not a PNG', indexed.getvalue()))

    def test_png_allows_only_invisible_rgb_changes(self) -> None:
        def rgba(values: list[int]) -> bytes:
            stream = BytesIO()
            png.Writer(2, 1, greyscale=False, alpha=True).write(stream, [values])
            return stream.getvalue()

        expected = rgba([255, 255, 255, 0, 103, 35, 108, 128])
        normalized = rgba([0, 0, 0, 0, 103, 35, 108, 128])
        self.assertTrue(matches_png(normalized, expected))
        self.assertTrue(matches_png(expected, normalized))
        for changed in (
            [0, 0, 0, 1, 103, 35, 108, 128],
            [0, 0, 0, 0, 104, 35, 108, 128],
            [0, 0, 0, 0, 103, 35, 108, 127],
            [0, 0, 0, 0, 103, 35, 108, 0],
        ):
            with self.subTest(values=changed):
                self.assertFalse(matches_png(rgba(changed), expected))

    @patch("scripts.verify_deployment.time.sleep")
    @patch("scripts.verify_deployment.urlopen")
    def test_retries_a_propagation_404_then_verifies_the_page(self, fetch, sleep) -> None:
        fetch.side_effect = [
            HTTPError("https://example.org/qr/paper/", 404, "missing", {}, None),
            self.response(b"expected page"),
        ]
        self.assertIsNone(self.check(attempts=2))
        self.assertEqual(fetch.call_count, 2)
        sleep.assert_called_once_with(1)
        self.assertEqual(
            [call.args[0].full_url for call in fetch.call_args_list],
            [
                "https://example.org/qr/paper/?v=1700000000-0",
                "https://example.org/qr/paper/?v=1700000000-1",
            ],
        )

    @patch("scripts.verify_deployment.time.sleep")
    @patch("scripts.verify_deployment.urlopen")
    def test_retries_stale_200_with_backoff_and_fresh_cache_bust(
        self, fetch, sleep
    ) -> None:
        fetch.side_effect = [
            self.response(b"stale page"),
            self.response(b"stale page"),
            self.response(b"expected page"),
        ]
        self.assertIsNone(self.check(attempts=3))
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual([call.args for call in sleep.call_args_list], [(1,), (2,)])
        self.assertEqual(
            [call.args[0].full_url for call in fetch.call_args_list],
            [
                "https://example.org/qr/paper/?v=1700000000-0",
                "https://example.org/qr/paper/?v=1700000000-1",
                "https://example.org/qr/paper/?v=1700000000-2",
            ],
        )

    @patch("scripts.verify_deployment.time.sleep")
    @patch("scripts.verify_deployment.urlopen")
    def test_exhausted_stale_retries_still_fail_strictly(self, fetch, sleep) -> None:
        fetch.return_value = self.response(b"stale page")
        error = self.check(attempts=3)
        self.assertIsNotNone(error)
        assert error is not None
        self.assertIn("content differs", error)
        self.assertTrue(error.startswith("https://example.org/qr/paper/:"))
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual([call.args for call in sleep.call_args_list], [(1,), (2,)])
