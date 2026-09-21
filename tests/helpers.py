"""Deterministic inventory fixtures shared by tooling tests."""

from __future__ import annotations

from typing import Any


FIRST_PARTY_ORIGIN = "https://qr.comphy-lab.org"
PUBLIC_PAYLOAD = f"{FIRST_PARTY_ORIGIN}/social-hub/"


def valid_inventory() -> dict[str, Any]:
    codes: list[dict[str, Any]] = [
        {
            "id": "public-social-hub",
            "slug": "social-hub",
            "name": "CoMPhy <social> & links",
            "folder": "Public links",
            "source_kind": "dynamic",
            "source_status": "active",
            "content_type": "links",
            "visibility": "public",
            "source_short_url": "https://qrco.de/AbC123",
            "destination": None,
            "qr_payload": PUBLIC_PAYLOAD,
            "migration_status": "replacement-ready",
            "summary": "Five useful routes; <script>alert('no')</script>",
            "links": [
                {"label": "Lab website", "url": "https://comphy-lab.org/"},
                {"label": "GitHub", "url": "https://github.com/comphy-lab"},
                {"label": "YouTube", "url": "https://www.youtube.com/@VatsalSanjay"},
                {"label": "Bluesky", "url": "https://bsky.app/profile/comphy-lab.org"},
                {"label": "LinkedIn", "url": "https://www.linkedin.com/company/comphy-lab"},
            ],
        }
    ]
    for index in range(1, 71):
        codes.append(
            {
                "id": f"private-redacted-{index}",
                "slug": f"private-redacted-{index}",
                "name": f"Private code {index}",
                "folder": "Private",
                "source_kind": "dynamic",
                "source_status": "paused",
                "content_type": "website",
                "visibility": "private",
                "source_short_url": None,
                "destination": None,
                "qr_payload": None,
                "migration_status": "private-redacted",
            }
        )
    return {
        "schema_version": 1,
        "source": "sanitised QR Code Generator account inventory",
        "first_party_origin": FIRST_PARTY_ORIGIN,
        "codes": codes,
    }
