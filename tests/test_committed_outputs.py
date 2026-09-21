from __future__ import annotations

from pathlib import Path
import unittest

import make_branded_qr_codes as branded
from scripts.inventory import load_valid_inventory
from tests.qr_decode import decode_qr_png, rasterize_pdf, rasterize_svg


REPO_ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = REPO_ROOT / "inventory/codes.json"


class CommittedOutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not INVENTORY_PATH.exists():
            raise unittest.SkipTest("account inventory is being assembled")
        inventory = load_valid_inventory(INVENTORY_PATH)
        cls.expected = {
            code["slug"]: code["qr_payload"]
            for code in inventory["codes"]
            if code["visibility"] == "public"
            and code["source_status"] != "paused"
            and isinstance(code.get("qr_payload"), str)
        }

    def assert_decodes_exactly(self, content: bytes, payload: str, label: Path) -> None:
        results = decode_qr_png(content)
        self.assertEqual(len(results), 1, f"expected one QR code in {label}, got {len(results)}")
        self.assertEqual(results[0].text, payload)

    def test_every_committed_account_png_decodes_to_its_exact_inventory_payload(self) -> None:
        self.assertTrue(self.expected, "inventory has no public non-paused QR payloads")
        output_dir = REPO_ROOT / "current/account"
        for slug, payload in sorted(self.expected.items()):
            with self.subTest(slug=slug):
                png_path = output_dir / f"{slug}.png"
                self.assertTrue(png_path.is_file(), f"missing generated PNG: {png_path}")
                self.assert_decodes_exactly(png_path.read_bytes(), payload, png_path)

    def test_every_committed_account_svg_rasterizes_and_decodes_exactly(self) -> None:
        output_dir = REPO_ROOT / "current/account"
        actual = {path.stem for path in output_dir.glob("*.svg")}
        self.assertEqual(actual, set(self.expected))
        for slug, payload in sorted(self.expected.items()):
            with self.subTest(slug=slug):
                svg_path = output_dir / f"{slug}.svg"
                self.assert_decodes_exactly(rasterize_svg(svg_path), payload, svg_path)

    def test_every_public_code_has_a_landing_page_and_vector_pdf(self) -> None:
        account = REPO_ROOT / "current/account"
        site = REPO_ROOT / "site"
        pdfs = {path.stem for path in account.glob("*.pdf")}
        self.assertEqual(pdfs, set(self.expected))
        for slug, payload in sorted(self.expected.items()):
            with self.subTest(slug=slug):
                pdf_path = account / f"{slug}.pdf"
                page = site / slug / "index.html"
                self.assertTrue(page.is_file(), f"missing landing page: {page}")
                self.assert_decodes_exactly(rasterize_pdf(pdf_path.read_bytes()), payload, pdf_path)
                for ext in ("svg", "png", "pdf"):
                    account_file = account / f"{slug}.{ext}"
                    site_file = site / "assets" / "qr" / f"{slug}.{ext}"
                    self.assertEqual(account_file.read_bytes(), site_file.read_bytes())

    def test_all_bespoke_svgs_rasterize_and_decode_exactly(self) -> None:
        expected = {branded.OUTDIR / f"{asset.stem}.svg": asset.url for asset in branded.ASSETS}
        self.assertEqual(len(expected), 4)
        for svg_path, payload in expected.items():
            with self.subTest(svg=svg_path.name):
                self.assert_decodes_exactly(rasterize_svg(svg_path), payload, svg_path)

    def test_all_bespoke_pngs_decode_exactly(self) -> None:
        expected = {branded.OUTDIR / f"{asset.stem}.png": asset.url for asset in branded.ASSETS}
        self.assertEqual(len(expected), 4)
        for png_path, payload in expected.items():
            with self.subTest(png=png_path.name):
                self.assertTrue(png_path.is_file(), f"missing bespoke PNG: {png_path}")
                self.assert_decodes_exactly(png_path.read_bytes(), payload, png_path)
