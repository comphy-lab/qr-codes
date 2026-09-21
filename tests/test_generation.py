from __future__ import annotations

from copy import deepcopy
from pathlib import Path, PurePosixPath
import re
import tempfile
import unittest
from unittest import mock

import zxingcpp

from scripts.generate import (
    FONT_DIR,
    FONT_FILES,
    FONT_LICENCE,
    LOGO_FILES,
    _logo_assets,
    GenerationError,
    build_outputs,
    compare_tree,
    render_pdf,
    render_png,
    render_svg,
    write_tree,
)
from scripts.inventory import require_valid_inventory
from tests.helpers import PUBLIC_PAYLOAD, valid_inventory
from tests.qr_decode import decode_qr_png, rasterize_pdf


class GenerationTests(unittest.TestCase):
    def test_svg_png_and_pdf_generation_is_byte_deterministic_and_decodable(self) -> None:
        first_svg = render_svg(PUBLIC_PAYLOAD)
        second_svg = render_svg(PUBLIC_PAYLOAD)
        first_png = render_png(PUBLIC_PAYLOAD)
        second_png = render_png(PUBLIC_PAYLOAD)
        first_pdf = render_pdf(PUBLIC_PAYLOAD)
        second_pdf = render_pdf(PUBLIC_PAYLOAD)
        self.assertEqual(first_svg, second_svg)
        self.assertEqual(first_png, second_png)
        self.assertEqual(first_pdf, second_pdf)
        self.assertTrue(first_pdf.startswith(b"%PDF-1.4\n"))
        self.assertIn(b"%%EOF\n", first_pdf)
        self.assertIn(b'fill="#67236C"', first_svg)
        self.assertIn(b'fill="#FFFFFF"', first_svg)
        self.assertNotIn(b"<script", first_svg.lower())
        for content in (first_png, rasterize_pdf(first_pdf)):
            results = decode_qr_png(content)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].text, PUBLIC_PAYLOAD)
            self.assertEqual(results[0].format, zxingcpp.BarcodeFormat.QRCode)

    def test_build_outputs_contains_only_eligible_qr_and_first_party_site(self) -> None:
        outputs = build_outputs(require_valid_inventory(valid_inventory()))
        self.assertEqual(
            set(outputs.qr),
            {
                PurePosixPath("social-hub.svg"),
                PurePosixPath("social-hub.png"),
                PurePosixPath("social-hub.pdf"),
            },
        )
        self.assertEqual(
            set(outputs.site),
            {
                PurePosixPath("assets/style.css"),
                PurePosixPath("assets/qr/social-hub.svg"),
                PurePosixPath("assets/qr/social-hub.png"),
                PurePosixPath("assets/qr/social-hub.pdf"),
                PurePosixPath("index.html"),
                PurePosixPath("social-hub/index.html"),
            }
            | {
                PurePosixPath(f"assets/fonts/{name}")
                for name in (*FONT_FILES, FONT_LICENCE)
            }
            | {
                PurePosixPath(f"assets/logos/{name}") for name in LOGO_FILES
            },
        )

    def test_generated_html_escapes_inventory_and_has_early_strict_csp(self) -> None:
        outputs = build_outputs(require_valid_inventory(valid_inventory()))
        page = outputs.site[PurePosixPath("social-hub/index.html")].decode("utf-8")
        self.assertLess(
            page.index('http-equiv="Content-Security-Policy"'),
            page.index('rel="stylesheet"'),
        )
        self.assertIn("default-src &#x27;none&#x27;", page)
        self.assertNotIn("unsafe-inline", page)
        self.assertNotIn("unsafe-eval", page)
        self.assertNotIn("<script", page.casefold())
        self.assertNotIn("javascript:", page.casefold())
        self.assertNotIn("<social>", page)
        self.assertIn("&lt;social&gt;", page)
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;alert", page)
        self.assertNotIn("fonts.googleapis.com", page)
        self.assertIn('target="_blank" rel="noopener noreferrer"', page)
        self.assertNotIn('http-equiv="refresh"', page)
        self.assertIn('download="social-hub.svg"', page)
        self.assertIn('download="social-hub.png"', page)
        self.assertIn('download="social-hub.pdf"', page)
        self.assertNotIn("Public links", page)
        self.assertNotIn("First-party route", page)
        index = outputs.site[PurePosixPath("index.html")].decode("utf-8")
        self.assertNotIn("Public links", index)
        self.assertIn('href="social-hub/"', index)
        self.assertIn('href="assets/qr/social-hub.svg"', index)
        self.assertIn('href="assets/qr/social-hub.png"', index)
        self.assertIn('href="assets/qr/social-hub.pdf"', index)
        self.assertIn("font-src &#x27;self&#x27;", page)
        css = outputs.site[PurePosixPath("assets/style.css")].decode("utf-8")
        self.assertIn(
            "--t-serif: 'Fraunces', 'Source Serif 4', 'Iowan Old Style', Georgia, serif",
            css,
        )
        self.assertIn(
            "--t-display: 'Cormorant Garamond', 'Fraunces', Georgia, serif", css
        )
        self.assertIn("'IBM Plex Sans', -apple-system", css)
        self.assertIn("'IBM Plex Mono', ui-monospace", css)
        self.assertNotIn("Avenir Next", css)
        # The entrance animation is gone: it flashed a half-faded frame on the
        # routes that redirect, and bought nothing below the fold.
        self.assertNotIn("settle-in", css)
        self.assertNotIn("@keyframes", css)
        self.assertIn("@media (hover: hover) and (pointer: fine)", css)
        self.assertIn("transition:\n      background var(--dur-fast) var(--ease)", css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)
        self.assertIn("color-scheme: light dark", css)
        self.assertIn("@media (prefers-color-scheme: dark)", css)
        self.assertIn("@media (forced-colors: active)", css)
        # The QR quiet zone must stay light in both themes.
        self.assertIn("background: #fff;", css)

    def test_base_path_is_removed_from_site_routes_without_allowing_traversal(self) -> None:
        inventory = valid_inventory()
        inventory["first_party_origin"] = "https://comphy-lab.org/qr-codes"
        inventory["codes"][0]["qr_payload"] = (
            "https://comphy-lab.org/qr-codes/social-hub/"
        )
        outputs = build_outputs(inventory)
        self.assertIn(PurePosixPath("social-hub/index.html"), outputs.site)
        self.assertNotIn(
            PurePosixPath("qr-codes/social-hub/index.html"), outputs.site
        )
        index = outputs.site[PurePosixPath("index.html")].decode("utf-8")
        self.assertIn('href="social-hub/"', index)
        self.assertNotIn('href="qr-codes/social-hub/"', index)

        inventory["codes"][0]["qr_payload"] = (
            "https://comphy-lab.org/qr-codes/../escape/"
        )
        with self.assertRaisesRegex(GenerationError, "unsafe first-party route"):
            build_outputs(inventory)

        inventory["codes"][0]["qr_payload"] = (
            "https://comphy-lab.org/qr-codes/other-slug/"
        )
        with self.assertRaisesRegex(GenerationError, "slug landing page"):
            build_outputs(inventory)

    def test_catalogue_includes_downloads_for_external_static_codes(self) -> None:
        inventory = valid_inventory()
        inventory["codes"][1] = {
            "id": "public-paper",
            "slug": "public-paper",
            "name": "Public paper",
            "folder": "Papers",
            "source_kind": "static",
            "source_status": "static",
            "content_type": "pdf",
            "visibility": "public",
            "source_short_url": None,
            "destination": "https://example.org/paper.pdf",
            "qr_payload": "https://example.org/paper.pdf",
            "migration_status": "direct-static",
        }
        outputs = build_outputs(inventory)
        self.assertIn(PurePosixPath("assets/qr/public-paper.svg"), outputs.site)
        self.assertIn(PurePosixPath("assets/qr/public-paper.png"), outputs.site)
        self.assertIn(PurePosixPath("assets/qr/public-paper.pdf"), outputs.site)
        self.assertIn(PurePosixPath("public-paper.pdf"), outputs.qr)
        page = outputs.site[PurePosixPath("public-paper/index.html")].decode("utf-8")
        self.assertIn(
            'href="https://example.org/paper.pdf" target="_blank" '
            'rel="noopener noreferrer" '
            'aria-label="Open PDF (opens in a new tab)">Open PDF</a>',
            page,
        )
        self.assertIn('download="public-paper.pdf"', page)
        self.assertNotIn('http-equiv="refresh"', page)
        self.assertIn(
            '<link rel="canonical" href="https://qr.comphy-lab.org/public-paper/">',
            page,
        )
        index = outputs.site[PurePosixPath("index.html")].decode("utf-8")
        self.assertIn('href="public-paper/"', index)
        self.assertIn(
            'aria-label="Open Public paper link page">Public paper</a>',
            index,
        )
        self.assertNotIn("Open target", index)
        self.assertIn('download="public-paper.svg"', index)
        self.assertIn('download="public-paper.png"', index)
        self.assertIn('download="public-paper.pdf"', index)

    def test_single_destination_link_is_escaped_on_the_landing_page(self) -> None:
        inventory = deepcopy(valid_inventory())
        code = inventory["codes"][0]
        destination = 'https://example.org/open?label="lab"&mode=full'
        code["content_type"] = "website"
        code["destination"] = destination
        code["links"] = []
        outputs = build_outputs(inventory)
        page = outputs.site[PurePosixPath("social-hub/index.html")].decode("utf-8")
        escaped = "https://example.org/open?label=&quot;lab&quot;&amp;mode=full"
        self.assertNotIn('http-equiv="refresh"', page)
        self.assertIn(f'href="{escaped}"', page)
        self.assertIn('download="social-hub.pdf"', page)
        self.assertIn("<figure", page)

    def test_write_then_check_detects_no_drift_and_reports_mutation(self) -> None:
        outputs = build_outputs(require_valid_inventory(valid_inventory()))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            qr_root = root / "current" / "account"
            site_root = root / "site"
            write_tree(outputs.qr, qr_root)
            write_tree(outputs.site, site_root)
            self.assertEqual(compare_tree(outputs.qr, qr_root), [])
            self.assertEqual(compare_tree(outputs.site, site_root), [])
            (qr_root / "social-hub.svg").write_text("changed", encoding="utf-8")
            self.assertTrue(
                any(
                    "generated content differs" in error
                    for error in compare_tree(outputs.qr, qr_root)
                )
            )

    def test_generator_refuses_unexpected_files_instead_of_pruning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "generated"
            root.mkdir()
            (root / "human-note.txt").write_text("keep me", encoding="utf-8")
            with self.assertRaisesRegex(GenerationError, "refusing to prune"):
                write_tree({PurePosixPath("expected.txt"): b"expected\n"}, root)
            self.assertEqual(
                (root / "human-note.txt").read_text(encoding="utf-8"), "keep me"
            )

    def test_generator_refuses_symlinked_output_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            root = temporary / "generated"
            elsewhere = temporary / "elsewhere"
            root.mkdir()
            elsewhere.mkdir()
            (root / "nested").symlink_to(elsewhere, target_is_directory=True)
            with self.assertRaisesRegex(GenerationError, "symlink"):
                write_tree({PurePosixPath("nested/file.txt"): b"blocked\n"}, root)
            self.assertFalse((elsewhere / "file.txt").exists())

    def test_atomic_write_cleans_temporary_file_after_fsync_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "generated"
            with mock.patch(
                "scripts.generate.os.fsync",
                side_effect=OSError("injected fsync failure"),
            ):
                with self.assertRaisesRegex(OSError, "injected fsync failure"):
                    write_tree({PurePosixPath("expected.txt"): b"expected\n"}, root)
            self.assertEqual(list(root.iterdir()), [])

    def test_every_generated_list_restores_the_list_role(self) -> None:
        # Safari drops the implicit list role when list-style computes to none,
        # which is the dominant browser for a QR audience.
        outputs = build_outputs(require_valid_inventory(valid_inventory()))
        for path, content in outputs.site.items():
            if path.suffix != ".html":
                continue
            document = content.decode("utf-8")
            with self.subTest(page=str(path)):
                opens = re.findall(r"<ul\b[^>]*>", document)
                self.assertTrue(opens or path.name != "index.html")
                for tag in opens:
                    self.assertIn('role="list"', tag)

    def test_every_index_card_link_is_labelled_with_its_code_name(self) -> None:
        inventory = valid_inventory()
        inventory["codes"][1] = {
            "id": "public-paper",
            "slug": "public-paper",
            "name": "Public paper",
            "folder": "Papers",
            "source_kind": "static",
            "source_status": "static",
            "content_type": "pdf",
            "visibility": "public",
            "source_short_url": None,
            "destination": "https://example.org/paper.pdf",
            "qr_payload": "https://example.org/paper.pdf",
            "migration_status": "direct-static",
        }
        index = build_outputs(inventory).site[PurePosixPath("index.html")].decode("utf-8")
        cards = re.findall(r'<li class="card">(.*?)</li>', index, re.DOTALL)
        anchors = re.findall(r"<a\b[^>]*>", "".join(cards))
        card_anchors = [tag for tag in anchors if 'class="pill' in tag]
        self.assertEqual(len(card_anchors), 6)
        for tag in card_anchors:
            with self.subTest(anchor=tag):
                label = re.search(r'aria-label="([^"]*)"', tag)
                self.assertIsNotNone(label)
                self.assertTrue(
                    "CoMPhy &lt;social&gt; &amp; links" in label.group(1)
                    or "Public paper" in label.group(1)
                )
        self.assertIn(
            'aria-label="Download SVG QR code for Public paper"', index
        )
        self.assertIn(
            'aria-label="Download PDF QR code for Public paper"', index
        )
        self.assertIn(
            'aria-label="Open CoMPhy &lt;social&gt; &amp; links link page"', index
        )
        self.assertIn('id="team"', index)
        self.assertIn('id="research"', index)

    def test_single_destination_route_is_a_downloadable_landing_page(self) -> None:
        inventory = deepcopy(valid_inventory())
        code = inventory["codes"][0]
        code["content_type"] = "vcard"
        code["destination"] = "https://comphy-lab.org/contact-card/"
        code["links"] = []
        page = (
            build_outputs(inventory)
            .site[PurePosixPath("social-hub/index.html")]
            .decode("utf-8")
        )
        self.assertNotIn('name="robots"', page)
        self.assertNotIn('http-equiv="refresh"', page)
        self.assertIn(
            '<link rel="canonical" href="https://qr.comphy-lab.org/social-hub/">',
            page,
        )
        self.assertIn('download="social-hub.svg"', page)
        self.assertIn('download="social-hub.png"', page)
        self.assertIn('download="social-hub.pdf"', page)
        self.assertIn("<figure", page)
        self.assertIn("<ul", page)
        self.assertIn("Open contact card", page)
        self.assertNotIn("Continue to the contact card", page)
        self.assertNotIn("First-party route", page)

    def test_multi_link_route_keeps_its_collection_and_never_redirects(self) -> None:
        outputs = build_outputs(require_valid_inventory(valid_inventory()))
        page = outputs.site[PurePosixPath("social-hub/index.html")].decode("utf-8")
        self.assertNotIn('http-equiv="refresh"', page)
        self.assertNotIn('name="robots"', page)
        self.assertIn('<ul class="actions" role="list">', page)
        self.assertIn('<ul class="downloads" role="list">', page)
        self.assertIn('<figure class="qr-panel">', page)
        self.assertIn('href="../"', page)
        self.assertNotIn('href="../index.html"', page)

    def test_self_hosted_faces_are_emitted_byte_identically(self) -> None:
        outputs = build_outputs(require_valid_inventory(valid_inventory()))
        self.assertEqual(len(FONT_FILES), 10)
        for name in FONT_FILES:
            with self.subTest(font=name):
                path = PurePosixPath(f"assets/fonts/{name}")
                self.assertIn(path, outputs.site)
                self.assertEqual(
                    outputs.site[path], (FONT_DIR / name).read_bytes()
                )
                self.assertTrue(name.endswith(".woff2"))
        css = outputs.site[PurePosixPath("assets/style.css")].decode("utf-8")
        for name in FONT_FILES:
            self.assertIn(f"url(fonts/{name}) format('woff2')", css)
        self.assertEqual(css.count("@font-face"), len(FONT_FILES))
        self.assertEqual(css.count("font-display: swap"), len(FONT_FILES))
        self.assertIn(
            PurePosixPath(f"assets/fonts/{FONT_LICENCE}"), outputs.site
        )

    def test_generated_pages_carry_no_inline_style_or_script(self) -> None:
        outputs = build_outputs(require_valid_inventory(valid_inventory()))
        for path, content in outputs.site.items():
            if path.suffix != ".html":
                continue
            document = content.decode("utf-8").casefold()
            with self.subTest(page=str(path)):
                self.assertNotIn("<script", document)
                self.assertNotIn("<style", document)
                self.assertIsNone(re.search(r"\sstyle\s*=", document))

    def test_generation_fails_loudly_when_a_font_input_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            empty = Path(directory)
            with self.assertRaisesRegex(GenerationError, "missing self-hosted font"):
                build_outputs(
                    require_valid_inventory(valid_inventory()), fonts_dir=empty
                )

    def test_logo_copy_rejects_missing_files_and_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logos = root / "logos"
            logos.mkdir()
            outside = root / "outside"
            outside.mkdir()
            secret = outside / "CoMPhy-Lab.png"
            secret.write_bytes(b"must not be published")
            with self.assertRaisesRegex(GenerationError, "logo input"):
                _logo_assets(logos)
            (logos / "CoMPhy-lab").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(GenerationError, "logo input"):
                _logo_assets(logos)
            (logos / "CoMPhy-lab").unlink()
            (logos / "CoMPhy-lab").mkdir()
            (logos / "CoMPhy-lab/CoMPhy-Lab.png").symlink_to(secret)
            with self.assertRaisesRegex(GenerationError, "logo input"):
                _logo_assets(logos)
            alias = root / "alias"
            alias.symlink_to(logos, target_is_directory=True)
            with self.assertRaisesRegex(GenerationError, "logo directory"):
                _logo_assets(alias)


if __name__ == "__main__":
    unittest.main()
