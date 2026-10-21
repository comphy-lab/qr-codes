#!/usr/bin/env python3
"""Verify every published page and QR asset against its checked-in source."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import time
from urllib.error import URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
import zlib

import png

try:
    from .inventory import load_valid_inventory
except ImportError:
    from inventory import load_valid_inventory


ROOT = Path(__file__).resolve().parents[1]
# Cloudflare may append this beacon to HTML served through the lab domain.
# Accept only the observed empty external tag at the end of the body; the
# generated CSP and every other byte still have to match the source.
HOST_TRANSFORM_ALLOWANCE = 4096
CLOUDFLARE_BEACON = re.compile(
    rb'<script type="module" src="https://static\.cloudflareinsights\.com/beacon\.min\.js/v[0-9a-f]+" '
    rb'integrity="sha512-[A-Za-z0-9+/=]+" data-cf-beacon=\'[^\'<>\r\n]*\' '
    rb'crossorigin="anonymous"></script>\n(?=</body>\n</html>\n\Z)'
)
# Post-deploy CDN edges (Cloudflare max-age=14400 on assets, GitHub edge caches)
# can keep serving the previous bytes briefly. Retry with a fresh cache-busting
# query and exponential backoff until origin catches up, without relaxing the
# byte-for-byte match once a response is accepted.
DEFAULT_ATTEMPTS = 8
MAX_ATTEMPTS = 12
MAX_BACKOFF_SECONDS = 60


def retry_delay_seconds(attempt: int) -> int:
    """Seconds to wait after a failed attempt before the next try (0-based)."""
    return min(2 ** attempt, MAX_BACKOFF_SECONDS)


def cache_busted_url(url: str, *, attempt: int, nonce: int) -> str:
    """Append a unique query so CDN keys cannot reuse a stale object."""
    return f"{url}?{urlencode({'v': f'{nonce}-{attempt}'})}"


def matches_content(actual: bytes, expected: bytes, *, html: bool) -> bool:
    """Match exact bytes, allowing only the known host-injected HTML beacon."""
    return actual == expected or (
        html and CLOUDFLARE_BEACON.sub(b"", actual, count=1) == expected
    )


def matches_png(actual: bytes, expected: bytes) -> bool:
    """Require identical visible pixels and alpha; ignore RGB where alpha is zero."""
    try:
        width, height, rows, _ = png.Reader(bytes=expected).asRGBA8()
        actual_width, actual_height, actual_rows, _ = png.Reader(bytes=actual).asRGBA8()
        if (width, height) != (actual_width, actual_height):
            return False
        for left, right in zip(rows, actual_rows, strict=True):
            if bytes(left) == bytes(right):
                continue
            for offset in range(0, width * 4, 4):
                alpha = left[offset + 3]
                if alpha != right[offset + 3]:
                    return False
                # Polish may clear invisible RGB without changing the image.
                if alpha and left[offset:offset + 3] != right[offset:offset + 3]:
                    return False
        return True
    except (png.Error, ValueError, TypeError, zlib.error):
        return False


def verify_file(
    path: Path,
    *,
    site: Path,
    origin: str,
    attempts: int = DEFAULT_ATTEMPTS,
    nonce: int | None = None,
) -> str | None:
    """Return a diagnostic on HTTP failure or stale/wrong content, else None."""
    relative = path.relative_to(site).as_posix()
    route = relative.removesuffix("index.html") if path.name == "index.html" else relative
    url = origin.rstrip("/") + "/" + quote(route, safe="/")
    expected = path.read_bytes()
    error = "no attempt made"
    bust_nonce = int(time.time()) if nonce is None else nonce
    for attempt in range(attempts):
        request_url = cache_busted_url(url, attempt=attempt, nonce=bust_nonce)
        try:
            request = Request(
                request_url,
                headers={"User-Agent": "CoMPhy-QR-deployment-check/1.0"},
            )
            with urlopen(request, timeout=20) as response:
                # Bound reads even if a proxy returns an unrelated large document.
                is_html = path.suffix == ".html"
                is_png = path.suffix == ".png"
                allowance = HOST_TRANSFORM_ALLOWANCE if is_html or is_png else 0
                limit = len(expected) + allowance
                actual = response.read(limit + 1)
                if response.status == 200 and len(actual) <= limit:
                    if matches_content(actual, expected, html=is_html):
                        return None
                    if is_png and matches_png(actual, expected):
                        return None
                error = f"HTTP {response.status}, content differs from {relative}"
        except (URLError, OSError) as exc:
            error = str(exc)
        if attempt + 1 < attempts:
            time.sleep(retry_delay_seconds(attempt))
    return f"{url}: {error}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempts", type=int, default=DEFAULT_ATTEMPTS)
    args = parser.parse_args()
    if not 1 <= args.attempts <= MAX_ATTEMPTS:
        parser.error(f"--attempts must be between 1 and {MAX_ATTEMPTS}")
    inventory = load_valid_inventory(ROOT / "inventory/codes.json")
    site = ROOT / "site"
    paths = sorted(path for path in site.rglob("*") if path.is_file())
    if not paths:
        parser.error("no generated site files found")

    def check(path: Path) -> str | None:
        return verify_file(
            path,
            site=site,
            origin=inventory["first_party_origin"],
            attempts=args.attempts,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        errors = [error for error in executor.map(check, paths) if error]
    for error in errors:
        print(error)
    print(f"Verified {len(paths) - len(errors)}/{len(paths)} deployed files against local source")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
