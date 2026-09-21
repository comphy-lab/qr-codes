"""Strict, dependency-free validation for ``inventory/codes.json``."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit


EXPECTED_CODE_COUNT = 71
SOURCE_KINDS = frozenset({"dynamic", "static"})
SOURCE_STATUSES = frozenset({"active", "paused", "static"})
CONTENT_TYPES = frozenset({"website", "links", "pdf", "vcard"})
VISIBILITIES = frozenset({"public", "private"})
MIGRATION_STATUSES = frozenset(
    {"replacement-ready", "direct-static", "source-preserved", "private-redacted"}
)

TOP_LEVEL_KEYS = frozenset({"schema_version", "source", "first_party_origin", "codes"})
REQUIRED_CODE_KEYS = frozenset(
    {
        "id",
        "slug",
        "name",
        "folder",
        "source_kind",
        "source_status",
        "content_type",
        "visibility",
        "source_short_url",
        "destination",
        "qr_payload",
        "migration_status",
    }
)
OPTIONAL_CODE_KEYS = frozenset({"summary", "links"})
LINK_KEYS = frozenset({"label", "url"})
SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
QRCO_PATH_RE = re.compile(r"/[A-Za-z0-9_-]+\Z")
FIRST_PARTY_SEGMENT_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
PRIVATE_ID_SLUG_RE = re.compile(r"private-redacted-[1-9][0-9]*\Z")
PRIVATE_NAME_RE = re.compile(r"Private code [1-9][0-9]*\Z")

VENDOR_HOST_SUFFIXES = (
    "qr-code-generator.com",
    "qrcgcustomers.s3-eu-west-1.amazonaws.com",
)
SIGNED_QUERY_KEYS = frozenset(
    {
        "expires",
        "key-pair-id",
        "policy",
        "rlkey",
        "sig",
        "signature",
        "sp",
        "spr",
        "sr",
        "srt",
        "st",
        "sv",
        "token",
        "x-amz-algorithm",
        "x-amz-credential",
        "x-amz-date",
        "x-amz-expires",
        "x-amz-security-token",
        "x-amz-signature",
        "x-amz-signedheaders",
    }
)


class DuplicateKeyError(ValueError):
    """Raised when a JSON object repeats a key."""


class InventoryValidationError(ValueError):
    """Raised when the account inventory violates its public contract."""

    def __init__(self, errors: list[str]):
        self.errors = tuple(errors)
        super().__init__("\n".join(errors))


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def load_inventory(path: Path | str) -> dict[str, Any]:
    """Load JSON while rejecting duplicate object keys and non-object roots."""

    inventory_path = Path(path)
    try:
        with inventory_path.open("r", encoding="utf-8") as stream:
            data = json.load(stream, object_pairs_hook=_object_without_duplicate_keys)
    except (OSError, json.JSONDecodeError, DuplicateKeyError) as exc:
        raise InventoryValidationError([f"{inventory_path}: {exc}"]) from exc
    if not isinstance(data, dict):
        raise InventoryValidationError([f"{inventory_path}: top level must be a JSON object"])
    return data


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _append_unknown_and_missing_keys(
    value: dict[str, Any],
    *,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
    location: str,
    errors: list[str],
) -> None:
    keys = frozenset(value)
    missing = sorted(required - keys)
    unknown = sorted(keys - required - optional)
    if missing:
        errors.append(f"{location}: missing keys: {', '.join(missing)}")
    if unknown:
        errors.append(f"{location}: unknown keys: {', '.join(unknown)}")


def _parse_https_url(value: Any, location: str, errors: list[str]):
    if not _is_nonempty_string(value):
        errors.append(f"{location}: must be a non-empty HTTPS URL")
        return None
    assert isinstance(value, str)
    if any(character.isspace() or ord(character) < 0x20 for character in value):
        errors.append(f"{location}: URL contains whitespace or control characters")
        return None
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        errors.append(f"{location}: invalid URL: {exc}")
        return None
    if parsed.scheme != "https" or not parsed.hostname:
        errors.append(f"{location}: must use HTTPS and include a host")
        return None
    if parsed.username is not None or parsed.password is not None:
        errors.append(f"{location}: URL credentials are forbidden")
        return None
    return parsed


def _host_matches(host: str, suffix: str) -> bool:
    return host == suffix or host.endswith(f".{suffix}")


def _reject_vendor_or_signed_url(value: str, location: str, errors: list[str]) -> None:
    parsed = urlsplit(value)
    host = (parsed.hostname or "").casefold()
    if any(_host_matches(host, suffix) for suffix in VENDOR_HOST_SUFFIXES):
        errors.append(f"{location}: vendor/CDN URL is forbidden")
    query_keys = {key.casefold() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
    signed_keys = sorted(query_keys & SIGNED_QUERY_KEYS)
    if signed_keys:
        errors.append(f"{location}: signed URL query keys are forbidden: {', '.join(signed_keys)}")


def _normalise_origin(value: Any, errors: list[str]) -> str | None:
    parsed = _parse_https_url(value, "first_party_origin", errors)
    if parsed is None:
        return None
    if parsed.query or parsed.fragment:
        errors.append("first_party_origin: must not contain a query or fragment")
        return None
    if parsed.path not in {"", "/"}:
        segments = parsed.path.removeprefix("/").removesuffix("/").split("/")
        if any(FIRST_PARTY_SEGMENT_RE.fullmatch(segment) is None for segment in segments):
            errors.append("first_party_origin: base path segments must be lowercase kebab-case")
            return None
    assert isinstance(value, str)
    return value.rstrip("/")


def _validate_first_party_path(
    value: str,
    *,
    origin: str,
    location: str,
    errors: list[str],
) -> None:
    parsed = urlsplit(value)
    if not is_first_party_url(value, origin):
        return
    if parsed.query or parsed.fragment:
        errors.append(f"{location}: first-party URL must not contain a query or fragment")
    if not parsed.path.endswith("/") or parsed.path.rstrip("/") == urlsplit(origin).path.rstrip("/"):
        errors.append(f"{location}: first-party URL must have a non-root trailing-slash path")
    segments = parsed.path.strip("/").split("/")
    if any(FIRST_PARTY_SEGMENT_RE.fullmatch(segment) is None for segment in segments):
        errors.append(f"{location}: first-party path segments must be lowercase kebab-case")


def _validate_nullable_public_url(
    value: Any,
    *,
    location: str,
    errors: list[str],
    origin: str | None = None,
    reject_qrco: bool = False,
) -> None:
    if value is None:
        return
    parsed = _parse_https_url(value, location, errors)
    if parsed is None:
        return
    assert isinstance(value, str)
    _reject_vendor_or_signed_url(value, location, errors)
    host = (parsed.hostname or "").casefold()
    if reject_qrco and _host_matches(host, "qrco.de"):
        errors.append(f"{location}: qrco.de is provenance only, never a QR payload")
    if origin is not None:
        _validate_first_party_path(value, origin=origin, location=location, errors=errors)


def _validate_source_short_url(value: Any, location: str, errors: list[str]) -> None:
    if value is None:
        return
    parsed = _parse_https_url(value, location, errors)
    if parsed is None:
        return
    if (parsed.hostname or "").casefold() != "qrco.de":
        errors.append(f"{location}: source_short_url may only record qrco.de provenance")
    if not QRCO_PATH_RE.fullmatch(parsed.path) or parsed.query or parsed.fragment:
        errors.append(f"{location}: expected canonical https://qrco.de/<code> without query/fragment")


def validate_inventory(data: dict[str, Any]) -> list[str]:
    """Return every schema, URL, privacy, and cross-field contract violation."""

    errors: list[str] = []
    _append_unknown_and_missing_keys(
        data,
        required=TOP_LEVEL_KEYS,
        location="inventory",
        errors=errors,
    )

    if data.get("schema_version") != 1 or isinstance(data.get("schema_version"), bool):
        errors.append("schema_version: must be integer 1")
    if not _is_nonempty_string(data.get("source")):
        errors.append("source: must be a non-empty string")
    origin = _normalise_origin(data.get("first_party_origin"), errors)

    codes = data.get("codes")
    if not isinstance(codes, list):
        errors.append("codes: must be an array")
        return errors
    if len(codes) != EXPECTED_CODE_COUNT:
        errors.append(f"codes: expected exactly {EXPECTED_CODE_COUNT} entries, found {len(codes)}")

    seen_ids: dict[str, int] = {}
    seen_slugs: dict[str, int] = {}
    first_party_paths: dict[str, int] = {}

    for index, code in enumerate(codes):
        location = f"codes[{index}]"
        if not isinstance(code, dict):
            errors.append(f"{location}: must be an object")
            continue
        _append_unknown_and_missing_keys(
            code,
            required=REQUIRED_CODE_KEYS,
            optional=OPTIONAL_CODE_KEYS,
            location=location,
            errors=errors,
        )

        code_id = code.get("id")
        if not _is_nonempty_string(code_id):
            errors.append(f"{location}.id: must be a non-empty string")
        else:
            assert isinstance(code_id, str)
            if code_id in seen_ids:
                errors.append(f"{location}.id: duplicate of codes[{seen_ids[code_id]}].id")
            else:
                seen_ids[code_id] = index

        slug = code.get("slug")
        if not isinstance(slug, str) or SLUG_RE.fullmatch(slug) is None:
            errors.append(f"{location}.slug: must be unique lowercase kebab-case")
        else:
            if slug in seen_slugs:
                errors.append(f"{location}.slug: duplicate of codes[{seen_slugs[slug]}].slug")
            else:
                seen_slugs[slug] = index

        for field in ("name", "folder"):
            if not _is_nonempty_string(code.get(field)):
                errors.append(f"{location}.{field}: must be a non-empty string")

        source_kind = code.get("source_kind")
        source_status = code.get("source_status")
        content_type = code.get("content_type")
        visibility = code.get("visibility")
        migration_status = code.get("migration_status")

        if source_kind not in SOURCE_KINDS:
            errors.append(f"{location}.source_kind: expected one of {sorted(SOURCE_KINDS)}")
        if source_status not in SOURCE_STATUSES:
            errors.append(f"{location}.source_status: expected one of {sorted(SOURCE_STATUSES)}")
        if content_type not in CONTENT_TYPES:
            errors.append(f"{location}.content_type: expected one of {sorted(CONTENT_TYPES)}")
        if visibility not in VISIBILITIES:
            errors.append(f"{location}.visibility: expected one of {sorted(VISIBILITIES)}")
        if migration_status not in MIGRATION_STATUSES:
            errors.append(f"{location}.migration_status: expected one of {sorted(MIGRATION_STATUSES)}")

        if source_kind == "static" and source_status != "static":
            errors.append(f"{location}: static source_kind requires source_status=static")
        if source_kind == "dynamic" and source_status == "static":
            errors.append(f"{location}: dynamic source_kind cannot use source_status=static")
        if source_kind == "dynamic" and source_status == "active" and migration_status != "replacement-ready":
            errors.append(f"{location}: active dynamic entries must be replacement-ready")

        summary = code.get("summary")
        if "summary" in code and not isinstance(summary, str):
            errors.append(f"{location}.summary: must be a string when present")

        links = code.get("links", [])
        if not isinstance(links, list):
            errors.append(f"{location}.links: must be an array when present")
            links = []
        for link_index, link in enumerate(links):
            link_location = f"{location}.links[{link_index}]"
            if not isinstance(link, dict):
                errors.append(f"{link_location}: must be an object")
                continue
            _append_unknown_and_missing_keys(
                link,
                required=LINK_KEYS,
                location=link_location,
                errors=errors,
            )
            if not _is_nonempty_string(link.get("label")):
                errors.append(f"{link_location}.label: must be a non-empty string")
            link_url = link.get("url")
            parsed_link = _parse_https_url(link_url, f"{link_location}.url", errors)
            if parsed_link is not None:
                assert isinstance(link_url, str)
                _reject_vendor_or_signed_url(link_url, f"{link_location}.url", errors)

        if content_type != "links" and links:
            errors.append(f"{location}.links: only content_type=links may publish links")
        if visibility == "public" and content_type == "links":
            if not links:
                errors.append(f"{location}.links: public link pages need at least one link")
            if not _is_nonempty_string(summary):
                errors.append(f"{location}.summary: public link pages need a non-empty summary")
            if code.get("destination") is not None:
                errors.append(f"{location}.destination: link pages must use links, not a destination")

        source_short_url = code.get("source_short_url")
        destination = code.get("destination")
        qr_payload = code.get("qr_payload")

        if visibility == "private":
            if not isinstance(code_id, str) or PRIVATE_ID_SLUG_RE.fullmatch(code_id) is None:
                errors.append(
                    f"{location}.id: private entries must use an opaque private-redacted-N placeholder"
                )
            if not isinstance(slug, str) or PRIVATE_ID_SLUG_RE.fullmatch(slug) is None:
                errors.append(
                    f"{location}.slug: private entries must use an opaque private-redacted-N placeholder"
                )
            name = code.get("name")
            if not isinstance(name, str) or PRIVATE_NAME_RE.fullmatch(name) is None:
                errors.append(
                    f"{location}.name: private entries must use an opaque Private code N placeholder"
                )
            if code.get("folder") != "Private":
                errors.append(f"{location}.folder: private entries must use exactly Private")
            for field, value in (
                ("source_short_url", source_short_url),
                ("destination", destination),
                ("qr_payload", qr_payload),
            ):
                if value is not None:
                    errors.append(f"{location}.{field}: private entries must be null")
            if migration_status != "private-redacted":
                errors.append(f"{location}.migration_status: private entries must be private-redacted")
            if links:
                errors.append(f"{location}.links: private entries must not publish links")
        else:
            _validate_source_short_url(source_short_url, f"{location}.source_short_url", errors)
            if source_kind == "static" and source_short_url is not None:
                errors.append(f"{location}.source_short_url: static entries have no dynamic short URL")
            _validate_nullable_public_url(
                destination,
                location=f"{location}.destination",
                errors=errors,
            )
            _validate_nullable_public_url(
                qr_payload,
                location=f"{location}.qr_payload",
                errors=errors,
                origin=origin,
                reject_qrco=True,
            )
            if source_kind == "dynamic" and source_status == "active" and qr_payload is None:
                errors.append(f"{location}.qr_payload: active public dynamic entry needs a replacement payload")
            if source_kind == "dynamic" and source_status == "active":
                if source_short_url is None:
                    errors.append(f"{location}.source_short_url: active public dynamic entry needs provenance")
                expected_payload = f"{origin}/{slug}/" if origin and isinstance(slug, str) else None
                if expected_payload is not None and qr_payload != expected_payload:
                    errors.append(
                        f"{location}.qr_payload: active public dynamic path must be exactly /{slug}/"
                    )
                if content_type in {"website", "pdf", "vcard"} and destination is None:
                    errors.append(f"{location}.destination: active {content_type} entry needs a destination")

        if migration_status == "direct-static":
            if not (
                source_kind == "static"
                and source_status == "static"
                and visibility == "public"
            ):
                errors.append(
                    f"{location}.migration_status: direct-static requires a public static source"
                )
            if destination is None or qr_payload is None or destination != qr_payload:
                errors.append(
                    f"{location}: direct-static requires equal non-null destination and qr_payload"
                )
        if migration_status == "source-preserved":
            if not (
                source_kind == "dynamic"
                and source_status == "paused"
                and qr_payload is None
            ):
                errors.append(
                    f"{location}.migration_status: source-preserved requires a paused dynamic source with null qr_payload"
                )
        if migration_status == "private-redacted" and visibility != "private":
            errors.append(f"{location}.migration_status: private-redacted requires visibility=private")

        if origin and isinstance(qr_payload, str):
            parsed_payload = urlsplit(qr_payload)
            if is_first_party_url(qr_payload, origin):
                path = parsed_payload.path
                if path in first_party_paths:
                    errors.append(
                        f"{location}.qr_payload: first-party path duplicates codes[{first_party_paths[path]}]"
                    )
                else:
                    first_party_paths[path] = index
                if destination == qr_payload:
                    errors.append(f"{location}.destination: must not loop back to its QR landing page")

    return errors


def require_valid_inventory(data: dict[str, Any]) -> dict[str, Any]:
    """Raise one aggregate exception unless ``data`` satisfies the contract."""

    errors = validate_inventory(data)
    if errors:
        raise InventoryValidationError(errors)
    return data


def load_valid_inventory(path: Path | str) -> dict[str, Any]:
    """Load and validate an inventory in one call."""

    return require_valid_inventory(load_inventory(path))


def is_first_party_url(value: str, origin: str) -> bool:
    """Return whether a URL is within the site's host and optional base path."""

    parsed = urlsplit(value)
    parsed_origin = urlsplit(origin.rstrip("/"))
    same_origin = (parsed.scheme, parsed.netloc.casefold()) == (
        parsed_origin.scheme,
        parsed_origin.netloc.casefold(),
    )
    base_path = parsed_origin.path.rstrip("/")
    return same_origin and (
        parsed.path == base_path or parsed.path.startswith(base_path + "/")
    )
