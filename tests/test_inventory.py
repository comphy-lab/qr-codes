from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from scripts.inventory import (
    InventoryValidationError,
    load_inventory,
    is_first_party_url,
    require_valid_inventory,
    validate_inventory,
)
from tests.helpers import PUBLIC_PAYLOAD, valid_inventory


class InventoryTests(unittest.TestCase):
    def assert_error_contains(self, inventory: dict, fragment: str) -> None:
        errors = validate_inventory(inventory)
        self.assertTrue(
            any(fragment in error for error in errors),
            f"missing {fragment!r} in {errors!r}",
        )

    def test_valid_inventory_satisfies_complete_contract(self) -> None:
        inventory = valid_inventory()
        self.assertEqual(validate_inventory(inventory), [])
        self.assertIs(require_valid_inventory(inventory), inventory)

    def test_requires_exactly_71_unique_ids_and_slugs(self) -> None:
        inventory = valid_inventory()
        inventory["codes"].pop()
        inventory["codes"][1]["id"] = inventory["codes"][0]["id"]
        inventory["codes"][1]["slug"] = inventory["codes"][0]["slug"]
        self.assert_error_contains(inventory, "expected exactly 71")
        self.assert_error_contains(inventory, "duplicate of codes[0].id")
        self.assert_error_contains(inventory, "duplicate of codes[0].slug")

    def test_rejects_vendor_and_signed_public_urls(self) -> None:
        cases = (
            ("qr_payload", "https://qrco.de/liveCode", "provenance only"),
            (
                "destination",
                "https://cdn.qr-code-generator.com/account/file.pdf",
                "vendor/CDN URL is forbidden",
            ),
            (
                "destination",
                "https://assets.example.org/file.pdf?Expires=9&Signature=secret",
                "signed URL query keys",
            ),
            (
                "destination",
                "https://files.example.org/public.pdf?rlkey=capability",
                "signed URL query keys",
            ),
        )
        for field, value, fragment in cases:
            with self.subTest(field=field):
                inventory = valid_inventory()
                inventory["codes"][0][field] = value
                self.assert_error_contains(inventory, fragment)

    def test_private_entry_cannot_leak_urls_or_links(self) -> None:
        inventory = valid_inventory()
        private = inventory["codes"][1]
        private["source_short_url"] = "https://qrco.de/private"
        private["destination"] = "https://example.org/private"
        private["qr_payload"] = "https://example.org/private"
        private["links"] = [{"label": "Leak", "url": "https://example.org/private"}]
        for field in ("source_short_url", "destination", "qr_payload"):
            self.assert_error_contains(inventory, f"{field}: private entries must be null")
        self.assert_error_contains(inventory, "private entries must not publish links")

    def test_private_entry_requires_opaque_placeholder_metadata(self) -> None:
        fields = {
            "id": "source-record-123",
            "slug": "internal-schedule",
            "name": "Internal schedule",
            "folder": "Internal",
        }
        for field, value in fields.items():
            with self.subTest(field=field):
                inventory = valid_inventory()
                inventory["codes"][1][field] = value
                self.assert_error_contains(inventory, f".{field}: private entries must use")

    def test_active_dynamic_entry_must_be_replacement_ready_with_payload(self) -> None:
        inventory = valid_inventory()
        public = inventory["codes"][0]
        public["migration_status"] = "source-preserved"
        public["qr_payload"] = None
        self.assert_error_contains(inventory, "active dynamic entries must be replacement-ready")
        self.assert_error_contains(inventory, "needs a replacement payload")

    def test_active_dynamic_payload_must_match_owned_slug_and_keep_provenance(self) -> None:
        inventory = valid_inventory()
        public = inventory["codes"][0]
        public["source_short_url"] = None
        public["qr_payload"] = "https://qr.comphy-lab.org/a-different-path/"
        self.assert_error_contains(inventory, "active public dynamic entry needs provenance")
        self.assert_error_contains(inventory, "path must be exactly /social-hub/")

    def test_direct_static_requires_equal_public_destination_and_payload(self) -> None:
        inventory = valid_inventory()
        public = inventory["codes"][0]
        public.update(
            source_kind="static",
            source_status="static",
            content_type="website",
            source_short_url=None,
            destination="https://example.org/canonical",
            qr_payload="https://example.org/different",
            migration_status="direct-static",
            links=[],
        )
        self.assert_error_contains(inventory, "equal non-null destination and qr_payload")

    def test_source_preserved_requires_paused_dynamic_without_payload(self) -> None:
        inventory = valid_inventory()
        public = inventory["codes"][0]
        public["source_status"] = "active"
        public["migration_status"] = "source-preserved"
        self.assert_error_contains(inventory, "source-preserved requires a paused dynamic source")

    def test_active_non_link_content_needs_destination_and_cannot_publish_links(self) -> None:
        inventory = valid_inventory()
        public = inventory["codes"][0]
        public["content_type"] = "pdf"
        public["destination"] = None
        self.assert_error_contains(inventory, "active pdf entry needs a destination")
        self.assert_error_contains(inventory, "only content_type=links may publish links")

    def test_public_link_page_needs_summary_links_and_no_destination(self) -> None:
        inventory = valid_inventory()
        public = inventory["codes"][0]
        public["summary"] = ""
        public["links"] = []
        public["destination"] = "https://example.org/"
        self.assert_error_contains(inventory, "public link pages need at least one link")
        self.assert_error_contains(inventory, "public link pages need a non-empty summary")
        self.assert_error_contains(inventory, "link pages must use links")

    def test_source_short_url_is_strict_qrco_provenance(self) -> None:
        inventory = valid_inventory()
        inventory["codes"][0]["source_short_url"] = "https://example.org/code"
        self.assert_error_contains(inventory, "may only record qrco.de provenance")

    def test_links_must_be_https_and_have_no_unknown_fields(self) -> None:
        inventory = valid_inventory()
        inventory["codes"][0]["links"][0] = {
            "label": "Unsafe",
            "url": "javascript:alert(1)",
            "html": "<b>unsafe</b>",
        }
        self.assert_error_contains(inventory, "must use HTTPS")
        self.assert_error_contains(inventory, "unknown keys: html")

    def test_first_party_paths_are_safe_canonical_directories(self) -> None:
        inventory = valid_inventory()
        inventory["codes"][0]["qr_payload"] = (
            "https://qr.comphy-lab.org/%2e%2e/escape"
        )
        self.assert_error_contains(inventory, "non-root trailing-slash path")
        self.assert_error_contains(inventory, "lowercase kebab-case")

    def test_destination_cannot_loop_to_first_party_page(self) -> None:
        inventory = valid_inventory()
        inventory["codes"][0]["destination"] = PUBLIC_PAYLOAD
        self.assert_error_contains(inventory, "must not loop back")

    def test_first_party_site_may_use_a_project_base_path(self) -> None:
        inventory = valid_inventory()
        origin = "https://comphy-lab.org/qr-codes"
        inventory["first_party_origin"] = origin
        inventory["codes"][0]["qr_payload"] = origin + "/social-hub/"
        self.assertEqual(validate_inventory(inventory), [])
        self.assertTrue(is_first_party_url(origin + "/social-hub/", origin))
        for url in (
            "https://comphy-lab.org/contact-card/",
            "https://comphy-lab.org/qr-codes-other/social-hub/",
            "https://example.org/qr-codes/social-hub/",
        ):
            self.assertFalse(is_first_party_url(url, origin), url)

    def test_first_party_base_path_rejects_ambiguous_or_unsafe_segments(self) -> None:
        for suffix in ("/../escape", "/%2e%2e/escape", "/a//b", "/a//", "/A", "/a?x=1", "/a#x"):
            with self.subTest(suffix=suffix):
                inventory = valid_inventory()
                inventory["first_party_origin"] = "https://example.org" + suffix
                self.assert_error_contains(inventory, "first_party_origin:")

    def test_unknown_schema_keys_are_rejected(self) -> None:
        inventory = valid_inventory()
        inventory["generated_at"] = "now"
        inventory["codes"][0]["raw_vendor_export"] = "secret"
        self.assert_error_contains(inventory, "unknown keys: generated_at")
        self.assert_error_contains(inventory, "unknown keys: raw_vendor_export")

    def test_json_loader_rejects_duplicate_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "codes.json"
            path.write_text(
                '{"schema_version": 1, "schema_version": 1}', encoding="utf-8"
            )
            with self.assertRaisesRegex(InventoryValidationError, "duplicate JSON key"):
                load_inventory(path)

    def test_fixture_copy_is_independent(self) -> None:
        first = valid_inventory()
        second = valid_inventory()
        second["codes"][0]["name"] = "Changed"
        self.assertNotEqual(first["codes"][0]["name"], second["codes"][0]["name"])


if __name__ == "__main__":
    unittest.main()
