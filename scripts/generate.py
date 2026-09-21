#!/usr/bin/env python3
"""Generate deterministic QR artwork and the first-party static link site."""

from __future__ import annotations

import argparse
import html
import io
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

import segno

try:  # Support both ``python scripts/generate.py`` and test imports.
    from .inventory import InventoryValidationError, is_first_party_url, load_valid_inventory
except ImportError:  # pragma: no cover - exercised by the command-line entry point.
    from inventory import InventoryValidationError, is_first_party_url, load_valid_inventory


REPO_ROOT = Path(__file__).resolve().parents[1]
QR_COLOUR = "#67236C"
BACKGROUND = "#FFFFFF"
SVG_WIDTH = 600
PNG_SCALE = 12
PDF_MODULE_PT = 12
QR_BORDER = 4
DOWNLOAD_KINDS = ("svg", "png", "pdf")
CONTENT_TYPE_LABELS = {
    "website": "Website",
    "links": "Links",
    "pdf": "PDF",
    "vcard": "Contact card",
}
CSP = (
    "default-src 'none'; img-src 'self'; style-src 'self'; font-src 'self'; "
    "base-uri 'none'; form-action 'none'"
)
SAFE_ROUTE_SEGMENT_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")

LAB_URL = "https://comphy-lab.org/"
LEDGER_URL = "https://github.com/comphy-lab/qr-codes"
LEDGER_LABEL = "github.com/comphy-lab/qr-codes"
INDEX_DESCRIPTION = "Useful logos, links, and QR codes."
# Populated sections follow the menu at https://comphy-lab.org/.
CATEGORIES = ("Team", "Research", "Teaching", "Blog")
LOGOS = (
    ("CoMPhy Lab", "CoMPhy-lab/CoMPhy-Lab", ("png", "svg", "pdf")),
    ("CoMPhy Lab mark", "CoMPhy-lab/CoMPhy-Lab-no-name", ("png", "pdf")),
    ("Durham University", "Durham/Durham-University", ("png", "pdf")),
    ("Durham University mark", "Durham/Durham-University_NoText", ("png", "svg", "pdf")),
)
LOGO_FILES = tuple(f"{stem}.{ext}" for _, stem, formats in LOGOS for ext in formats)


def _category(code: dict[str, Any]) -> str:
    if code["slug"] in {"github-profiles", "vatsal-links", "vatsal-sanjay"} or code["folder"] == "Public links":
        return "Team"
    if code["folder"] in {"Teaching", "workshops"} or code["slug"] in {
        "scott-kellly-playing-ping-pong", "bursting-soap-bubbles",
        "culinary-fluid-dynamics", "a-thermomechanical-material-point-method-for-baking-and-cooking",
    }:
        return "Teaching"
    return "Research"


def _link_category(url: str, default: str) -> str:
    if url == "https://blogs.comphy-lab.org/":
        return "Blog"
    return default

# ---------------------------------------------------------------------------
# Self-hosted type. The files are tracked inputs under assets/fonts/ and are
# emitted byte-identically under site/assets/fonts/, so the pages need no
# third-party request and the CSP can stay at font-src 'self'.
# ---------------------------------------------------------------------------
FONT_DIR = REPO_ROOT / "assets/fonts"
FONT_LICENCE = "OFL.txt"
FONT_FACES: tuple[tuple[str, str, int, str], ...] = (
    ("Fraunces", "normal", 600, "fraunces-normal-600"),
    ("Cormorant Garamond", "italic", 500, "cormorant-garamond-italic-500"),
    ("IBM Plex Sans", "normal", 400, "ibm-plex-sans-normal-400"),
    ("IBM Plex Sans", "normal", 600, "ibm-plex-sans-normal-600"),
    ("IBM Plex Mono", "normal", 400, "ibm-plex-mono-normal-400"),
)
FONT_SUBSETS: tuple[tuple[str, str], ...] = (
    (
        "latin-ext",
        "U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, U+02DD-02FF, U+0304, "
        "U+0308, U+0329, U+1D00-1DBF, U+1E00-1E9F, U+1EF2-1EFF, U+2020, U+20A0-20AB, "
        "U+20AD-20C0, U+2113, U+2C60-2C7F, U+A720-A7FF",
    ),
    (
        "latin",
        "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, "
        "U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, "
        "U+2212, U+2215, U+FEFF, U+FFFD",
    ),
)
FONT_FILES: tuple[str, ...] = tuple(
    f"{stem}-{subset}.woff2" for *_, stem in FONT_FACES for subset, _ in FONT_SUBSETS
)


class GenerationError(RuntimeError):
    """Raised when generated output cannot be applied or verified safely."""


@dataclass(frozen=True)
class GeneratedOutputs:
    """Byte-for-byte expected files for both generated output roots."""

    qr: dict[PurePosixPath, bytes]
    site: dict[PurePosixPath, bytes]


def _qr_for(payload: str) -> segno.QRCode:
    return segno.make(
        payload,
        error="h",
        micro=False,
        boost_error=False,
    )


def _module_rects(qr: segno.QRCode, border: int) -> tuple[tuple[int, int, int, int], ...]:
    """Return dark modules as ``(x, y, width, height)`` in SVG coordinates."""

    rects: list[tuple[int, int, int, int]] = []
    for row_index, row in enumerate(qr.matrix):
        start: int | None = None
        for column_index, dark in enumerate((*row, False)):
            if dark and start is None:
                start = column_index
            elif not dark and start is not None:
                rects.append((start + border, row_index + border, column_index - start, 1))
                start = None
    return tuple(rects)


def _module_path(qr: segno.QRCode, border: int) -> str:
    return "".join(
        f"M{x} {y}h{width}v{height}h-{width}z"
        for x, y, width, height in _module_rects(qr, border)
    )


def render_svg(payload: str) -> bytes:
    """Render a minimal, byte-reproducible purple-on-white QR SVG."""

    qr = _qr_for(payload)
    size = len(qr.matrix) + 2 * QR_BORDER
    title = html.escape(payload, quote=True)
    document = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {size} {size}" width="{SVG_WIDTH}" height="{SVG_WIDTH}" '
        'role="img" shape-rendering="crispEdges">\n'
        f"  <title>{title}</title>\n"
        f'  <rect width="{size}" height="{size}" fill="{BACKGROUND}"/>\n'
        f'  <path d="{_module_path(qr, QR_BORDER)}" fill="{QR_COLOUR}"/>\n'
        "</svg>\n"
    )
    return document.encode("utf-8")


def render_png(payload: str) -> bytes:
    """Render the matching lossless PNG used by portable decoder tests."""

    stream = io.BytesIO()
    _qr_for(payload).save(
        stream,
        kind="png",
        scale=PNG_SCALE,
        border=QR_BORDER,
        dark=QR_COLOUR,
        light=BACKGROUND,
    )
    return stream.getvalue()


def _pdf_unit(channel: int) -> str:
    """Format one 0–255 channel as a deterministic six-decimal PDF number."""

    millionths = (channel * 1_000_000 + 127) // 255
    return f"{millionths // 1_000_000}.{millionths % 1_000_000:06d}"


def _pdf_document(page_points: int, stream: bytes) -> bytes:
    """Wrap one content stream in a byte-stable single-page PDF."""

    objects = (
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
        (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_points} {page_points}] "
            f"/Contents 4 0 R /Resources << >> >>"
        ).encode("ascii"),
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"endstream",
    )
    chunks: list[bytes] = [b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"]
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(sum(len(chunk) for chunk in chunks))
        chunks.append(f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n")
    xref_at = sum(len(chunk) for chunk in chunks)
    size = len(objects) + 1
    xref = [f"xref\n0 {size}\n".encode("ascii"), b"0000000000 65535 f \n"]
    xref.extend(f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets[1:])
    trailer = (
        f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n"
    ).encode("ascii")
    return b"".join([*chunks, *xref, trailer])


def render_pdf(payload: str) -> bytes:
    """Render a deterministic vector PDF of the same modules as the SVG.

    The locked ``resvg-py`` package rasterizes SVG and does not write PDF.
    This writer draws the module runs directly, so the file stays vector,
    byte-stable, and free of an extra PDF package or system library.
    """

    qr = _qr_for(payload)
    size = len(qr.matrix) + 2 * QR_BORDER
    page = size * PDF_MODULE_PT
    purple = " ".join(_pdf_unit(channel) for channel in (0x67, 0x23, 0x6C))
    commands = [
        "q",
        "1 1 1 rg",
        f"0 0 {page} {page} re",
        "f",
        f"{purple} rg",
    ]
    for x, y, width, height in _module_rects(qr, QR_BORDER):
        commands.append(
            f"{x * PDF_MODULE_PT} {(size - y - height) * PDF_MODULE_PT} "
            f"{width * PDF_MODULE_PT} {height * PDF_MODULE_PT} re"
        )
    commands.extend(("f", "Q"))
    stream = ("\n".join(commands) + "\n").encode("ascii")
    return _pdf_document(page, stream)


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _page_head(
    *,
    title: str,
    description: str,
    canonical_url: str,
    css_href: str,
) -> str:
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'  <meta http-equiv="Content-Security-Policy" content="{_escape(CSP)}">\n'
        '  <meta name="referrer" content="no-referrer">\n'
        f"  <title>{_escape(title)}</title>\n"
        f'  <meta name="description" content="{_escape(description)}">\n'
        f'  <link rel="canonical" href="{_escape(canonical_url)}">\n'
        f'  <link rel="stylesheet" href="{_escape(css_href)}">\n'
        "</head>\n"
    )


def _external(href: str, label: str, *, css_class: str, aria_label: str) -> str:
    """Render an outbound link with the fixed new-tab hardening attributes."""

    return (
        f'<a class="{css_class}" href="{_escape(href)}" '
        f'target="_blank" rel="noopener noreferrer" '
        f'aria-label="{_escape(aria_label)}">{_escape(label)}</a>'
    )


def _site_header(*, home_href: str, jump_links: bool, categories: tuple[str, ...] = CATEGORIES) -> str:
    """Sticky header: brand lockup home, the lab site, and index jump pills."""

    jump = (
        '      <nav class="jump" aria-label="Catalogue sections">\n'
        + "".join(f'        <a href="#{name.lower()}">{name}</a>\n' for name in categories)
        + '        <a href="#logos">Logos</a>\n'
        + "      </nav>\n"
        if jump_links
        else ""
    )
    return (
        '  <header class="site-header">\n'
        '    <div class="header-inner">\n'
        f'      <a class="brand" href="{_escape(home_href)}" '
        'aria-label="CoMPhy Lab catalogue">\n'
        '        <span class="brand-name">CoMPhy Lab</span>\n'
        "      </a>\n"
        + jump
        + "      "
        + _external(
            LAB_URL,
            "comphy-lab.org",
            css_class="header-link",
            aria_label="comphy-lab.org (opens in a new tab)",
        )
        + "\n"
        "    </div>\n"
        "  </header>\n"
    )


def _site_footer() -> str:
    return (
        '  <footer class="site-footer">\n'
        '    <div class="footer-inner">\n'
        "      "
        + _external(
            LAB_URL,
            "CoMPhy Lab",
            css_class="footer-mark",
            aria_label="CoMPhy Lab website (opens in a new tab)",
        )
        + "\n"
        '      <p class="footer-meta">'
        + _external(
            LEDGER_URL,
            "Repository",
            css_class="footer-link",
            aria_label=f"{LEDGER_LABEL} (opens in a new tab)",
        )
        + "</p>\n"
        "    </div>\n"
        "  </footer>\n"
    )


def _first_party_route(value: str, origin: str) -> tuple[str, ...]:
    """Return a safe route relative to the configured first-party base path."""

    parsed = urlsplit(value)
    parsed_origin = urlsplit(origin)
    if (parsed.scheme, parsed.netloc.casefold()) != (
        parsed_origin.scheme,
        parsed_origin.netloc.casefold(),
    ):
        raise GenerationError(f"first-party route has a different origin: {value}")
    if parsed.query or parsed.fragment or not parsed.path.endswith("/"):
        raise GenerationError(f"unsafe first-party route: {value}")

    base_segments = tuple(segment for segment in parsed_origin.path.split("/") if segment)
    path_segments = tuple(segment for segment in parsed.path.split("/") if segment)
    if path_segments[: len(base_segments)] != base_segments:
        raise GenerationError(f"first-party route is outside configured base path: {value}")
    route = path_segments[len(base_segments) :]
    if not route or any(SAFE_ROUTE_SEGMENT_RE.fullmatch(segment) is None for segment in route):
        raise GenerationError(f"unsafe first-party route: {value}")
    return route


def _validated_https_url(value: str, slug: str) -> str:
    """Reject destinations that must not be emitted as outbound links."""

    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or any(character.isspace() or ord(character) < 0x20 for character in value)
    ):
        raise GenerationError(f"unsafe outbound URL for {slug}")
    return value


def _action_links(code: dict[str, Any]) -> list[tuple[str, str]]:
    actions: list[tuple[str, str]] = []
    destination = code.get("destination")
    if isinstance(destination, str):
        destination = _validated_https_url(destination, code["slug"])
        label = {
            "website": "Open website",
            "pdf": "Open PDF",
            "vcard": "Open contact card",
            "links": "Open destination",
        }[code["content_type"]]
        actions.append((label, destination))
    for link in code.get("links", []):
        actions.append((link["label"], _validated_https_url(link["url"], code["slug"])))
    return actions


def _downloads_markup(code: dict[str, Any], prefix: str) -> str:
    slug = code["slug"]
    name = code["name"]
    rows = []
    for kind in DOWNLOAD_KINDS:
        rows.append(
            '          <li><a class="pill pill--secondary" '
            f'href="{prefix}assets/qr/{_escape(slug)}.{kind}" '
            f'download="{_escape(slug)}.{kind}" '
            f'aria-label="Download {kind.upper()} QR code for {_escape(name)}">'
            f"Download {kind.upper()}</a></li>"
        )
    return "\n".join(rows)


def _landing_url(origin: str, slug: str) -> str:
    return f"{origin.rstrip('/')}/{slug}/"


def _code_page(code: dict[str, Any], *, origin: str) -> str:
    """Landing page with the QR, its downloads, and any documented outbound links."""

    payload = code["qr_payload"]
    summary = code.get("summary") or code["name"]
    prefix = "../"
    actions = _action_links(code)
    groups = []
    for category in CATEGORIES:
        links = [(label, url) for label, url in actions
                 if _link_category(url, _category(code)) == category]
        if not links:
            continue
        items = "\n".join(
            "          <li>" + _external(
                url, label, css_class="pill pill--external",
                aria_label=f"{label} (opens in a new tab)",
            ) + "</li>" for label, url in links
        )
        groups.append(f'        <section class="link-group"><h2>{category}</h2>\n'
                      '        <ul class="actions" role="list">\n'
                      + items + '\n        </ul></section>\n')
    destination_markup = "".join(groups)
    return (
        _page_head(
            title=f"{code['name']} | CoMPhy Lab QR",
            description=summary,
            canonical_url=_landing_url(origin, code["slug"]),
            css_href=f"{prefix}assets/style.css",
        )
        + "<body>\n"
        + _site_header(home_href=prefix, jump_links=False)
        + '  <main class="shell">\n'
        + '    <article class="detail">\n'
        + '      <div class="detail-copy">\n'
        + f"        <h1>{_escape(code['name'])}</h1>\n"
        + destination_markup
        + '        <ul class="downloads" role="list">\n'
        + _downloads_markup(code, prefix)
        + "\n        </ul>\n"
        + "      </div>\n"
        + '      <figure class="qr-panel">\n'
        + '        <div class="qr-frame">\n'
        + f'          <img src="{prefix}assets/qr/{_escape(code["slug"])}.svg" '
        + 'width="600" height="600" '
        + f'alt="QR code for {_escape(code["name"])}">\n'
        + "        </div>\n"
        + "        <figcaption><code>"
        + _escape(payload)
        + "</code></figcaption>\n"
        + "      </figure>\n"
        + "    </article>\n"
        + "  </main>\n"
        + _site_footer()
        + "</body>\n"
        + "</html>\n"
    )


def _index_card(code: dict[str, Any]) -> str:
    name = code["name"]
    slug = _escape(code["slug"])
    downloads = "\n".join(
        f'            <a class="pill pill--secondary" href="assets/qr/{slug}.{ext}" '
        f'download="{slug}.{ext}" '
        f'aria-label="Download {ext.upper()} QR code for {_escape(name)}">'
        f"{ext.upper()}</a>"
        for ext in DOWNLOAD_KINDS
    )
    return (
        '        <li class="card">\n'
        f'          <h3><a href="{slug}/" '
        f'aria-label="Open {_escape(name)} link page">{_escape(name)}</a></h3>\n'
        + '          <div class="card-foot">\n'
        + downloads
        + "\n          </div>\n"
        "        </li>"
    )


def _index_section(
    codes: list[dict[str, Any]],
    *,
    section_id: str,
    heading: str,
) -> str:
    cards = [_index_card(code) for code in codes]
    body = "\n".join(cards)
    return (
        f'    <section class="group" id="{section_id}">\n'
        '      <div class="group-head">\n'
        f"        <h2>{heading}</h2>\n"
        "      </div>\n"
        f'      <ul class="card-grid" role="list" aria-label="{heading}">\n'
        + body
        + "\n      </ul>\n"
        "    </section>\n"
    )


def _index_page(codes: list[dict[str, Any]], *, origin: str) -> str:
    sections = []
    populated = []
    for category in CATEGORIES:
        grouped = [code for code in codes if _category(code) == category]
        if grouped:
            populated.append(category)
            sections.append(_index_section(grouped,
                            section_id=category.lower(), heading=category))
        if category == "Blog":
            blog_links = dict.fromkeys(
                (link["label"], link["url"])
                for code in codes for link in code.get("links", [])
                if _link_category(link["url"], _category(code)) == "Blog"
            )
            if blog_links:
                populated.append(category)
                items = "".join('<li>' + _external(
                    url, label, css_class="pill pill--external",
                    aria_label=f"{label} (opens in a new tab)") + '</li>'
                    for label, url in blog_links)
                sections.append('<section class="group" id="blog"><h2>Blog</h2>'
                                '<ul class="actions" role="list">' + items + '</ul></section>\n')
    logo_items = []
    for label, stem, formats in LOGOS:
        downloads = "".join(
            f'<a class="pill pill--secondary" href="assets/logos/{stem}.{ext}" '
            f'download aria-label="Download {ext.upper()} for {label}">{ext.upper()}</a>'
            for ext in formats
        )
        logo_items.append(f'<li class="logo"><h3>{label}</h3>'
                          f'<img src="assets/logos/{stem}.png" alt="{label} logo" '
                          'width="320" height="220" loading="lazy">'
                          f'<div class="card-foot">{downloads}</div></li>')
    sections.append('<section class="group" id="logos"><h2>Logos</h2>'
                    '<ul class="logo-grid" role="list">' + "".join(logo_items) + '</ul></section>\n')
    return (
        _page_head(
            title="CoMPhy Lab logos, links, and QR codes",
            description=INDEX_DESCRIPTION,
            canonical_url=f"{origin}/",
            css_href="assets/style.css",
        )
        + "<body>\n"
        + _site_header(home_href="./", jump_links=True, categories=tuple(populated))
        + '  <main class="shell">\n'
        + '    <section class="hero">\n'
        + '      <h1 class="hero-title">Useful logos, links, and QR codes.</h1>\n'
        + "    </section>\n"
        + '    <span id="link-pages" aria-hidden="true"></span>\n'
        + '    <span id="direct-codes" aria-hidden="true"></span>\n'
        + "".join(sections)
        + "  </main>\n"
        + _site_footer()
        + "</body>\n"
        + "</html>\n"
    )


def _font_face_css() -> str:
    """Emit one @font-face per family and subset, pointing at site-local files."""

    blocks: list[str] = []
    for family, style, weight, stem in FONT_FACES:
        for subset, unicode_range in FONT_SUBSETS:
            blocks.append(
                f"/* {subset} */\n"
                "@font-face {\n"
                f"  font-family: '{family}';\n"
                f"  font-style: {style};\n"
                f"  font-weight: {weight};\n"
                "  font-display: swap;\n"
                f"  src: url(fonts/{stem}-{subset}.woff2) format('woff2');\n"
                f"  unicode-range: {unicode_range};\n"
                "}\n"
            )
    return "\n".join(blocks)


# ---------------------------------------------------------------------------
# Presentation layer.
#
# Visual thesis: a warm paper-and-ink catalogue — scholarly, quiet, printed
# rather than app-like — with one deep teal doing every interactive job and
# purple reserved for the brand marks and the QR modules.
#
# Colour, type, spacing, radius, shadow and motion values are the CoMPhy
# design-system tokens. Authored mobile-first (iPhone 15 Pro Max, 430px),
# then >=721px and >=1100px; the detail two-column split is the single
# exception at >=900px, where the QR panel first has room beside the copy.
# ---------------------------------------------------------------------------
BASE_CSS = """\
/* =============================================================
   CoMPhy Lab QR catalogue. Generated by scripts/generate.py.
   Do not hand-edit: site/ is build output.
   Self-hosted faces are SIL OFL; see assets/fonts/OFL.txt.
   ============================================================= */

:root {
  color-scheme: light dark;

  /* ---------- Brand hues ---------- */
  --c-brand-purple: #68236d;
  /* Design-system hero stops, with stop 1 deepened from #ff6b6b so every
     stop clears 3:1 for large text on the paper (2.42 was below). */
  --hero-grad-1: #e2555b;
  --hero-grad-2: #68236d;
  --hero-grad-3: #4c6ef5;
  --hero-grad-4: #2d1b69;

  /* ---------- Interactive accent (the only one) ---------- */
  --c-accent-teal: #254c4a;
  --c-accent-teal-fg: #ffffff;
  --c-accent-teal-hover: #1d3c3a;

  /* ---------- Paper + ink ---------- */
  --c-paper: #f3efe8;
  --c-paper-tint: #ebe5da;
  --c-surface-strong: #fffdf9;
  --c-surface: var(--c-surface-strong);

  --fg-strong: #0f0c08;
  --fg-1: #1f1a15;
  --fg-2: #625648;
  --fg-3: #857867;

  --c-border: rgba(15, 12, 8, 0.09);
  --c-border-strong: rgba(15, 12, 8, 0.18);

  --grid-line: rgba(15, 12, 8, 0.035);
  --eyebrow-fg: #68236d;
  --code-bg: color-mix(in srgb, var(--c-brand-purple) 7%, transparent);
  --code-fg: var(--fg-strong);

  /* ---------- Typography ---------- */
  --t-display: 'Cormorant Garamond', 'Fraunces', Georgia, serif;
  --t-serif: 'Fraunces', 'Source Serif 4', 'Iowan Old Style', Georgia, serif;
  --t-sans: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  --t-mono: 'IBM Plex Mono', ui-monospace, 'SF Mono', Menlo, monospace;

  --t-hero: clamp(36px, 4.5vw, 60px);
  --t-h1: clamp(28px, 3.4vw, 36px);
  --t-h2: clamp(22px, 2.6vw, 28px);
  --t-h3: 20px;
  --t-body-lg: 18px;
  --t-body: 16px;
  --t-small: 14px;
  --t-eyebrow: 12px;

  --t-track-tight: -0.01em;
  --t-track-wide: 0.08em;

  /* ---------- Spacing, radius, shadow ---------- */
  --s-1: 4px;
  --s-2: 8px;
  --s-3: 12px;
  --s-4: 16px;
  --s-5: 24px;
  --s-6: 32px;
  --s-7: 48px;
  --s-8: 64px;

  --r-sm: 12px;
  --r-md: 18px;
  --r-lg: 28px;
  --r-pill: 999px;

  --shadow-sm: 0 1px 2px rgba(15, 12, 8, 0.04), 0 1px 3px rgba(15, 12, 8, 0.06);
  --shadow-md: 0 4px 10px rgba(15, 12, 8, 0.06), 0 2px 4px rgba(15, 12, 8, 0.04);
  --shadow-soft: 0 12px 40px rgba(15, 12, 8, 0.06), 0 4px 12px rgba(15, 12, 8, 0.04);

  /* ---------- Layout + motion ---------- */
  --maxw-page: 1200px;
  --maxw-read: 68ch;
  --shell-pad: 14px;
  --tap: 44px;
  --ease: cubic-bezier(0.2, 0.6, 0.2, 1);
  --dur-fast: 160ms;
}

@media (prefers-color-scheme: dark) {
  :root {
    --c-paper: #12100d;
    --c-paper-tint: #1a1713;
    --c-surface-strong: #1c1915;

    --fg-strong: #f8f4ec;
    --fg-1: #e6dfd0;
    --fg-2: #9a8e7d;
    --fg-3: #6e6455;

    --c-border: rgba(248, 244, 236, 0.08);
    --c-border-strong: rgba(248, 244, 236, 0.16);

    --grid-line: rgba(248, 244, 236, 0.04);
    --eyebrow-fg: #c09bc4;
    /* Lift the two darkest hero stops on dark paper (1.85 and 1.33 otherwise). */
    --hero-grad-2: #c09bc4;
    --hero-grad-4: #9b8cf2;
    --code-bg: color-mix(in srgb, var(--c-brand-purple) 22%, transparent);
    --code-fg: #f1dcf4;

    --c-accent-teal: #6ac2bd;
    --c-accent-teal-fg: #0f1c1b;
    --c-accent-teal-hover: #88d2ce;

    --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.4);
    --shadow-md: 0 4px 10px rgba(0, 0, 0, 0.45);
    --shadow-soft: 0 12px 40px rgba(0, 0, 0, 0.5);
  }
}

/* =============================================================
   Base
   ============================================================= */

*,
*::before,
*::after { box-sizing: border-box; }

html {
  min-width: 20rem;
  overflow-x: clip;
  -webkit-text-size-adjust: 100%;
  scroll-padding-top: 7rem;
}

body {
  margin: 0;
  overflow-x: clip;
  /* Column flow so the footer strip reaches the bottom of a short page. */
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  position: relative;
  background: var(--c-paper);
  color: var(--fg-1);
  font-family: var(--t-sans);
  font-size: var(--t-body);
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}

/* Soft grid overlay: the only decoration, and it never takes a click. */
body::before {
  content: "";
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background-image:
    linear-gradient(to right, var(--grid-line) 1px, transparent 1px),
    linear-gradient(to bottom, var(--grid-line) 1px, transparent 1px);
  background-size: 24px 24px;
}

a {
  color: inherit;
  text-decoration: none;
  -webkit-tap-highlight-color: transparent;
}

a:focus-visible {
  outline: 3px solid var(--c-accent-teal);
  outline-offset: 3px;
}

strong { color: inherit; }

h1,
h2,
h3 {
  margin: 0;
  color: var(--fg-strong);
  font-family: var(--t-serif);
  font-weight: 600;
  line-height: 1.2;
  letter-spacing: -0.015em;
}

h1 { font-size: var(--t-h1); }
h2 { font-size: var(--t-h2); }

code {
  padding: 0.08em 0.35em;
  border-radius: 4px;
  background: var(--code-bg);
  color: var(--code-fg);
  font-family: var(--t-mono);
  font-size: 0.92em;
  overflow-wrap: anywhere;
}

.eyebrow {
  margin: 0;
  color: var(--eyebrow-fg);
  font-family: var(--t-sans);
  font-size: var(--t-eyebrow);
  font-weight: 600;
  letter-spacing: var(--t-track-wide);
  text-transform: uppercase;
}

.lede {
  margin: 0;
  max-width: var(--maxw-read);
  color: var(--fg-2);
  font-size: var(--t-body-lg);
  line-height: 1.55;
}

.quiet {
  color: var(--fg-2);
  list-style: none;
}

.shell {
  position: relative;
  z-index: 1;
  flex: 1 0 auto;
  width: 100%;
  max-width: var(--maxw-page);
  margin: 0 auto;
  padding: var(--s-6) var(--shell-pad) var(--s-8);
}

/* =============================================================
   Header
   ============================================================= */

.site-header {
  position: sticky;
  top: 0;
  z-index: 20;
  border-bottom: 1px solid var(--c-border);
  background: color-mix(in srgb, var(--c-paper) 86%, transparent);
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
}

.header-inner {
  display: grid;
  grid-template-columns: auto auto;
  align-items: center;
  gap: 0 var(--s-3);
  max-width: var(--maxw-page);
  margin: 0 auto;
  padding: var(--s-1) var(--shell-pad);
}

.brand {
  grid-column: 1;
  display: inline-flex;
  align-items: center;
  gap: var(--s-2);
  min-height: var(--tap);
  color: var(--fg-strong);
}

.brand-mark {
  display: inline-grid;
  place-items: center;
  width: 2rem;
  height: 2rem;
  border-radius: var(--r-pill);
  background: var(--c-accent-teal);
  color: var(--c-accent-teal-fg);
  font-family: var(--t-display);
  font-style: italic;
  font-size: var(--t-h3);
  line-height: 1;
}

.brand-name {
  font-family: var(--t-serif);
  font-weight: 600;
  font-size: var(--t-body-lg);
  letter-spacing: var(--t-track-tight);
}

.header-link {
  grid-column: -2;
  grid-row: 1;
  justify-self: end;
  display: inline-flex;
  align-items: center;
  min-height: var(--tap);
  padding: 0 var(--s-1);
  color: var(--fg-2);
  font-size: var(--t-small);
  font-weight: 600;
}

.jump {
  grid-column: 1 / -1;
  grid-row: 2;
  display: flex;
  gap: var(--s-2);
  overflow-x: auto;
  overscroll-behavior-x: contain;
  padding-bottom: var(--s-2);
  scrollbar-width: none;
}

.jump a {
  flex: none;
  display: inline-flex;
  align-items: center;
  min-height: var(--tap);
  padding: 0 var(--s-4);
  border: 1px solid var(--c-border-strong);
  border-radius: var(--r-pill);
  background: var(--c-surface);
  color: var(--fg-1);
  font-size: var(--t-small);
  font-weight: 600;
  white-space: nowrap;
}

/* =============================================================
   Index
   ============================================================= */

.hero {
  display: grid;
  gap: var(--s-3);
}

.hero-title {
  margin: 0;
  max-width: 26ch;
  font-family: var(--t-display);
  font-style: italic;
  font-weight: 500;
  font-size: var(--t-hero);
  line-height: 1.02;
  letter-spacing: -0.015em;
  background: linear-gradient(
    90deg,
    var(--hero-grad-1) 0%,
    var(--hero-grad-2) 45%,
    var(--hero-grad-3) 55%,
    var(--hero-grad-4) 100%
  );
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  color: transparent;
}

/* Clipped gradient type has no forced-colours meaning; fall back to ink. */
@media (forced-colors: active) {
  .hero-title {
    background: none;
    -webkit-text-fill-color: CanvasText;
    color: CanvasText;
  }
}

.group { margin-top: var(--s-7); }

.group-head {
  display: grid;
  gap: var(--s-1);
  margin-bottom: var(--s-4);
}

.group-intro {
  margin: 0;
  max-width: var(--maxw-read);
  color: var(--fg-2);
  font-size: var(--t-small);
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 300px), 1fr));
  gap: 14px;
  margin: 0;
  padding: 0;
  list-style: none;
}

/* Flex column rather than grid so a short card still pins its action row to
   the bottom edge instead of leaving a void (audit M5). */
.card {
  display: flex;
  flex-direction: column;
  gap: var(--s-2);
  padding: var(--s-4) 0;
  border-bottom: 1px solid var(--c-border-strong);
}

.card h3 {
  font-size: 18px;
  line-height: 1.25;
  letter-spacing: var(--t-track-tight);
  overflow-wrap: anywhere;
}

.card h3 a {
  display: inline-flex;
  align-items: center;
  min-height: var(--tap);
  color: inherit;
}

.card-summary {
  margin: 0;
  color: var(--fg-2);
  font-size: var(--t-small);
  line-height: 1.5;
}

.card-foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--s-2);
  margin-top: auto;
  padding-top: var(--s-2);
}

.link-group { margin-top: var(--s-5); }
.link-group h2 { font-size: var(--t-h3); }

.logo-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 240px), 1fr));
  gap: var(--s-5);
  padding: 0;
  margin: var(--s-5) 0 0;
  list-style: none;
}

.logo { min-width: 0; }
.logo h3 { font-size: var(--t-h3); }
.logo img {
  display: block;
  width: 100%;
  height: 220px;
  object-fit: contain;
  padding: var(--s-4);
  margin-top: var(--s-3);
  background: #fff;
}

/* =============================================================
   Pills — the single interactive shape
   ============================================================= */

.pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: var(--tap);
  padding: 0 var(--s-4);
  border: 1px solid var(--c-accent-teal);
  border-radius: var(--r-pill);
  background: var(--c-accent-teal);
  color: var(--c-accent-teal-fg);
  font-size: var(--t-small);
  font-weight: 600;
  line-height: 1.25;
  text-align: center;
}

.pill--secondary {
  border-color: var(--fg-3);
  background: var(--c-surface-strong);
  color: var(--fg-1);
}

/* Decorative; every external pill also carries an aria-label. */
.pill--external::after { content: " \\2197"; }

/* =============================================================
   Detail page
   ============================================================= */

.detail {
  display: grid;
  gap: var(--s-5);
}

.detail-copy {
  display: grid;
  gap: var(--s-3);
  align-content: start;
}

.actions,
.downloads {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.actions .pill { font-size: var(--t-body); }

.qr-panel {
  margin: 0;
  max-width: 14rem;
  padding: var(--s-4);
  border: 1px solid var(--c-border);
  border-radius: var(--r-lg);
  background: var(--c-surface-strong);
  box-shadow: var(--shadow-soft);
}

/* The quiet zone stays white in both themes so cameras can still read it. */
.qr-frame {
  padding: 12px;
  border-radius: var(--r-sm);
  background: #fff;
}

.qr-panel img {
  display: block;
  width: 100%;
  height: auto;
}

.qr-panel figcaption {
  margin-top: var(--s-3);
  color: var(--fg-2);
  font-size: var(--t-eyebrow);
  line-height: 1.6;
}

/* =============================================================
   Footer
   ============================================================= */

.site-footer {
  position: relative;
  z-index: 1;
  flex: none;
  margin-top: var(--s-7);
  border-top: 1px solid var(--c-border);
  background: var(--c-paper-tint);
}

.footer-inner {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--s-2);
  max-width: var(--maxw-page);
  margin: 0 auto;
  padding: var(--s-4) var(--shell-pad);
}

.footer-mark {
  display: inline-flex;
  align-items: center;
  min-height: var(--tap);
  color: var(--fg-strong);
  font-family: var(--t-serif);
  font-size: var(--t-small);
  font-weight: 600;
}

.footer-meta {
  margin: 0;
  color: var(--fg-2);
  font-family: var(--t-mono);
  font-size: 11px;
  line-height: 1.5;
}

.footer-link {
  display: inline-flex;
  align-items: center;
  min-height: var(--tap);
  text-decoration: underline;
  text-underline-offset: 3px;
}

/* =============================================================
   Interaction — hover only where a real pointer exists
   ============================================================= */

@media (hover: hover) and (pointer: fine) {
  .pill,
  .card,
  .jump a,
  .brand-name,
  .header-link,
  .footer-mark,
  .footer-link {
    transition:
      background var(--dur-fast) var(--ease),
      border-color var(--dur-fast) var(--ease),
      box-shadow var(--dur-fast) var(--ease),
      color var(--dur-fast) var(--ease);
  }

  .pill:hover {
    border-color: var(--c-accent-teal-hover);
    background: var(--c-accent-teal-hover);
  }

  .pill--secondary:hover {
    border-color: var(--c-accent-teal);
    background: var(--c-surface-strong);
    color: var(--c-accent-teal);
  }

  .card:hover,
  .card:focus-within {
    border-color: color-mix(in srgb, var(--c-accent-teal) 45%, var(--c-border-strong));
  }

  .jump a:hover {
    border-color: var(--c-accent-teal);
    color: var(--c-accent-teal);
  }

  .card:hover h3 a,
  .card:focus-within h3 a,
  .brand:hover .brand-name,
  .header-link:hover,
  .footer-mark:hover,
  .footer-link:hover { color: var(--c-accent-teal); }
}

@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; }
}

/* =============================================================
   Responsive steps
   ============================================================= */

@media (min-width: 721px) {
  body::before { background-size: 32px 32px; }

  .header-inner {
    grid-template-columns: auto auto;
    gap: 0 var(--s-5);
    padding: var(--s-1) 28px;
  }

  .jump {
    grid-column: 1 / -1;
    grid-row: 2;
    justify-self: start;
    max-width: 100%;
    overflow-x: auto;
    padding-bottom: 0;
  }

  .shell { padding-left: 28px; padding-right: 28px; }

  .footer-inner {
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    gap: var(--s-5);
    padding-left: 28px;
    padding-right: 28px;
  }

  .footer-meta { text-align: right; }
}

/* The QR panel only earns a column of its own once the copy keeps 16rem. */
@media (min-width: 900px) {
  .detail {
    grid-template-columns: minmax(0, 1fr) minmax(16rem, 24rem);
    align-items: start;
    gap: var(--s-6);
  }

  .qr-panel { max-width: none; }
}

@media (min-width: 1100px) {
  .shell { padding-top: var(--s-7); }

  .group { margin-top: var(--s-8); }
}
"""

STYLE_CSS = _font_face_css() + "\n" + BASE_CSS

def _font_assets(fonts_dir: Path) -> dict[PurePosixPath, bytes]:
    """Read the tracked woff2 inputs and their licence for byte-identical reuse."""

    if fonts_dir.is_symlink() or not fonts_dir.is_dir():
        raise GenerationError(f"missing self-hosted font directory: {fonts_dir}")
    outputs: dict[PurePosixPath, bytes] = {}
    for name in (*FONT_FILES, FONT_LICENCE):
        source = fonts_dir / name
        if source.is_symlink() or not source.is_file():
            raise GenerationError(f"missing self-hosted font input: {source}")
        outputs[PurePosixPath(f"assets/fonts/{name}")] = source.read_bytes()
    return outputs


def _logo_assets(logos_dir: Path) -> dict[PurePosixPath, bytes]:
    """Copy only the configured regular logo files, without following symlinks."""

    if logos_dir.parent.is_symlink() or logos_dir.is_symlink() or not logos_dir.is_dir():
        raise GenerationError(f"missing or unsafe logo directory: {logos_dir}")
    outputs: dict[PurePosixPath, bytes] = {}
    for name in LOGO_FILES:
        source = logos_dir / name
        if source.parent.is_symlink() or source.is_symlink() or not source.is_file():
            raise GenerationError(f"missing or unsafe logo input: {source}")
        outputs[PurePosixPath(f"assets/logos/{name}")] = source.read_bytes()
    return outputs


def build_outputs(
    inventory: dict[str, Any],
    *,
    fonts_dir: Path | None = None,
) -> GeneratedOutputs:
    """Build every expected file in memory without touching the filesystem."""

    origin = inventory["first_party_origin"].rstrip("/")
    eligible = sorted(
        (
            code
            for code in inventory["codes"]
            if code["visibility"] == "public"
            and code["source_status"] != "paused"
            and isinstance(code.get("qr_payload"), str)
        ),
        key=lambda code: code["slug"],
    )

    qr_outputs: dict[PurePosixPath, bytes] = {}
    artwork: dict[str, dict[str, bytes]] = {}
    for code in eligible:
        slug = code["slug"]
        payload = code["qr_payload"]
        if is_first_party_url(payload, origin) and _first_party_route(payload, origin) != (slug,):
            raise GenerationError(f"{slug}: first-party payload must be the slug landing page")
        rendered = {
            "svg": render_svg(payload),
            "png": render_png(payload),
            "pdf": render_pdf(payload),
        }
        artwork[slug] = rendered
        for kind, content in rendered.items():
            qr_outputs[PurePosixPath(f"{slug}.{kind}")] = content

    catalogue_codes = sorted(
        eligible,
        key=lambda code: (code["name"].casefold(), code["slug"]),
    )
    site_outputs: dict[PurePosixPath, bytes] = {
        PurePosixPath("assets/style.css"): STYLE_CSS.encode("utf-8"),
        PurePosixPath("index.html"): _index_page(catalogue_codes, origin=origin).encode("utf-8"),
    }
    site_outputs.update(_font_assets(FONT_DIR if fonts_dir is None else fonts_dir))
    site_outputs.update(_logo_assets(REPO_ROOT / "assets/logos"))
    for code in catalogue_codes:
        slug = code["slug"]
        for kind in DOWNLOAD_KINDS:
            site_outputs[PurePosixPath(f"assets/qr/{slug}.{kind}")] = artwork[slug][kind]
        site_outputs[PurePosixPath(slug, "index.html")] = _code_page(code, origin=origin).encode("utf-8")

    return GeneratedOutputs(qr=qr_outputs, site=site_outputs)


def _actual_files(root: Path) -> set[PurePosixPath]:
    if not root.exists():
        return set()
    if root.is_symlink() or not root.is_dir():
        raise GenerationError(f"unsafe output root (expected a real directory): {root}")
    files: set[PurePosixPath] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise GenerationError(f"refusing symlink in generated tree: {path}")
        if path.is_file():
            files.add(PurePosixPath(path.relative_to(root).as_posix()))
    return files


def compare_tree(expected: dict[PurePosixPath, bytes], root: Path) -> list[str]:
    """Return missing, unexpected, and byte-drift diagnostics for one tree."""

    actual = _actual_files(root)
    expected_paths = set(expected)
    errors = [f"{root}: missing {path}" for path in sorted(expected_paths - actual)]
    errors.extend(f"{root}: unexpected {path}" for path in sorted(actual - expected_paths))
    for relative in sorted(actual & expected_paths):
        target = root.joinpath(*relative.parts)
        if target.read_bytes() != expected[relative]:
            errors.append(f"{root}: generated content differs: {relative}")
    return errors


def _safe_target(root: Path, relative: PurePosixPath) -> Path:
    if relative.is_absolute() or ".." in relative.parts:
        raise GenerationError(f"unsafe generated path: {relative}")
    root_resolved = root.resolve(strict=False)
    if root.exists() and (root.is_symlink() or not root.is_dir()):
        raise GenerationError(f"unsafe output root (expected a real directory): {root}")
    target = root.joinpath(*relative.parts)
    if target.exists() and target.is_symlink():
        raise GenerationError(f"refusing symlinked output file: {target}")
    current = target.parent
    while current != root and current != current.parent:
        if current.exists() and current.is_symlink():
            raise GenerationError(f"refusing symlinked output path: {current}")
        current = current.parent
    if not target.resolve(strict=False).is_relative_to(root_resolved):
        raise GenerationError(f"generated path escapes output root: {relative}")
    return target


def _atomic_write(target: Path, content: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    stream = tempfile.NamedTemporaryFile(
        dir=target.parent,
        prefix=f".{target.name}.",
        delete=False,
    )
    temporary = Path(stream.name)
    try:
        with stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def write_tree(expected: dict[PurePosixPath, bytes], root: Path) -> None:
    """Write expected files atomically, refusing to delete or overwrite extra files."""

    extras = _actual_files(root) - set(expected)
    if extras:
        rendered = ", ".join(str(path) for path in sorted(extras))
        raise GenerationError(f"{root}: refusing to prune unexpected files: {rendered}")
    for relative, content in sorted(expected.items()):
        _atomic_write(_safe_target(root, relative), content)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=REPO_ROOT / "inventory/codes.json")
    parser.add_argument("--qr-output", type=Path, default=REPO_ROOT / "current/account")
    parser.add_argument("--site-output", type=Path, default=REPO_ROOT / "site")
    parser.add_argument("--fonts", type=Path, default=FONT_DIR)
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare committed outputs without writing",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        inventory = load_valid_inventory(args.inventory)
        outputs = build_outputs(inventory, fonts_dir=args.fonts)
        if args.check:
            errors = compare_tree(outputs.qr, args.qr_output)
            errors.extend(compare_tree(outputs.site, args.site_output))
            if errors:
                for error in errors:
                    print(f"ERROR: {error}")
                return 1
            print(
                f"Generated outputs current: QR files={len(outputs.qr)}, "
                f"site files={len(outputs.site)}"
            )
            return 0
        write_tree(outputs.qr, args.qr_output)
        write_tree(outputs.site, args.site_output)
        print(
            f"Generated QR files={len(outputs.qr)}, site files={len(outputs.site)}"
        )
        return 0
    except (GenerationError, InventoryValidationError, OSError) as exc:
        if isinstance(exc, InventoryValidationError):
            for error in exc.errors:
                print(f"ERROR: {error}")
        else:
            print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
