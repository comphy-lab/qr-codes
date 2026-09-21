from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re
import unittest
from urllib.parse import unquote, urlsplit
from defusedxml import ElementTree as ET

from scripts.inventory import is_first_party_url, load_valid_inventory


REPO_ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = REPO_ROOT / "inventory/codes.json"
SITE_ROOT = REPO_ROOT / "site"
QR_ROOT = REPO_ROOT / "current/account"
SVG_NAMESPACE = "http://www.w3.org/2000/svg"


class ResourceCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.resources: list[tuple[str, dict[str, str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.resources.append((tag, {key: value or "" for key, value in attrs}))


@unittest.skipUnless(INVENTORY_PATH.exists(), "account inventory is being assembled")
class OutputSafetyTests(unittest.TestCase):
    def test_catalogue_navigation_and_downloads_resolve_to_generated_files(self) -> None:
        parser = ResourceCollector()
        parser.feed((SITE_ROOT / "index.html").read_text(encoding="utf-8"))
        ids = {attrs["id"] for _, attrs in parser.resources if "id" in attrs}
        for tag, attrs in parser.resources:
            if tag != "a":
                continue
            href = urlsplit(attrs.get("href", ""))
            if href.scheme or href.netloc:
                continue
            if href.fragment:
                self.assertIn(href.fragment, ids)
            target = SITE_ROOT / unquote(href.path)
            if target.is_dir():
                target /= "index.html"
            self.assertTrue(target.is_file(), attrs)
        for source in (REPO_ROOT / "assets/logos").rglob("*"):
            if source.is_file():
                published = SITE_ROOT / "assets/logos" / source.relative_to(REPO_ROOT / "assets/logos")
                self.assertEqual(source.read_bytes(), published.read_bytes())

    def test_account_snapshot_has_14_owned_dynamic_routes(self) -> None:
        inventory = load_valid_inventory(INVENTORY_PATH)
        active_dynamic = [
            code
            for code in inventory["codes"]
            if code["visibility"] == "public"
            and code["source_kind"] == "dynamic"
            and code["source_status"] == "active"
        ]
        self.assertEqual(len(active_dynamic), 14)
        self.assertTrue(
            all(
                is_first_party_url(
                    code["qr_payload"], inventory["first_party_origin"]
                )
                for code in active_dynamic
            )
        )

    def test_generated_html_has_no_active_content_or_third_party_assets(self) -> None:
        self.assertTrue(SITE_ROOT.is_dir(), "generated site/ directory is missing")
        pages = sorted(SITE_ROOT.rglob("*.html"))
        self.assertTrue(pages)
        for page in pages:
            with self.subTest(page=page.relative_to(REPO_ROOT)):
                document = page.read_text(encoding="utf-8")
                lowered = document.casefold()
                self.assertNotIn("<script", lowered)
                self.assertNotIn("<style", lowered)
                self.assertNotIn("javascript:", lowered)
                self.assertNotIn("data:text/html", lowered)
                self.assertNotIn("<iframe", lowered)
                self.assertIsNone(re.search(r"\son[a-z]+\s*=", lowered))
                # No inline style attribute survives style-src 'self' anyway;
                # assert it so the generator can never start emitting one.
                self.assertIsNone(re.search(r"\sstyle\s*=", lowered))
                self.assertIn("font-src &#x27;self&#x27;", document)
                self.assertLess(
                    document.index("Content-Security-Policy"),
                    document.index('rel="stylesheet"'),
                )
                self.assertNotIn('http-equiv="refresh"', document)
                if page.parent != SITE_ROOT:
                    self.assertIn("Download PDF", document)
                    self.assertIn('class="qr-panel"', document)

                parser = ResourceCollector()
                parser.feed(document)
                for tag, attributes in parser.resources:
                    self.assertNotIn(tag, {"script", "iframe", "object", "embed"})
                    if tag == "img":
                        src = attributes.get("src", "")
                        self.assertNotIn("://", src)
                        self.assertFalse(src.startswith("//"))
                    if tag == "link" and attributes.get("rel") == "stylesheet":
                        href = attributes.get("href", "")
                        self.assertNotIn("://", href)
                        self.assertFalse(href.startswith("//"))
                    if tag == "ul":
                        self.assertEqual(attributes.get("role"), "list")

    def test_self_hosted_fonts_are_published_byte_identically(self) -> None:
        source = REPO_ROOT / "assets/fonts"
        published = SITE_ROOT / "assets/fonts"
        self.assertTrue(source.is_dir(), "tracked font inputs are missing")
        self.assertTrue(published.is_dir(), "generated font outputs are missing")
        woff2 = sorted(path.name for path in source.glob("*.woff2"))
        self.assertEqual(len(woff2), 10)
        for name in (*woff2, "OFL.txt"):
            with self.subTest(font=name):
                self.assertEqual(
                    (published / name).read_bytes(), (source / name).read_bytes()
                )

    @unittest.skipUnless(QR_ROOT.exists(), "QR output has not been generated")
    def test_generated_svgs_are_plain_local_purple_on_white_artwork(self) -> None:
        svgs = sorted(QR_ROOT.glob("*.svg"))
        self.assertTrue(svgs)
        for svg in svgs:
            with self.subTest(svg=svg.name):
                source = svg.read_text(encoding="utf-8")
                self.assertNotIn("<!DOCTYPE", source)
                root = ET.fromstring(source)
                self.assertEqual(root.tag, f"{{{SVG_NAMESPACE}}}svg")
                tags = {element.tag.rsplit("}", 1)[-1] for element in root.iter()}
                self.assertLessEqual(tags, {"svg", "title", "rect", "path"})
                fills = {
                    element.attrib["fill"]
                    for element in root.iter()
                    if "fill" in element.attrib
                }
                self.assertEqual(fills, {"#67236C", "#FFFFFF"})
                for element in root.iter():
                    for attribute in element.attrib:
                        local_name = attribute.rsplit("}", 1)[-1].casefold()
                        self.assertNotIn(local_name, {"href", "src", "style"})
                        self.assertFalse(local_name.startswith("on"))


if __name__ == "__main__":
    unittest.main()
