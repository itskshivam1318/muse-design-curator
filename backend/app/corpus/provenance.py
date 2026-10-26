"""Provenance gate: only items with a known source, an allowed licence and a credit are usable."""

from typing import Any

LICENSE_ALLOWLIST = frozenset(
    {
        "CC0-1.0", "PDM-1.0", "CC-BY-2.0", "CC-BY-2.5", "CC-BY-3.0", "CC-BY-4.0",
        "CC-BY-SA-2.0", "CC-BY-SA-3.0", "CC-BY-SA-4.0", "Pexels", "MIT", "Apache-2.0",
        "BSD-3-Clause", "GPL-3.0-only",
    }
)  # fmt: skip

# Licences whose terms require naming the creator.
CREDIT_REQUIRED_PREFIXES = ("CC-BY-",)


def _text(item: Any, field: str) -> str:
    value = item.get(field) if isinstance(item, dict) else getattr(item, field, None)
    return value.strip() if isinstance(value, str) else ""


def check_provenance(item: Any) -> tuple[str, str | None]:
    """("valid", None) or ("invalid", reason). `item` is a ManifestItem, CorpusItem or dict."""
    if not (_text(item, "source") and _text(item, "source_id") and _text(item, "landing_url")):
        return "invalid", "MISSING_SOURCE"
    code = _text(item, "license_code")
    if code not in LICENSE_ALLOWLIST:
        return "invalid", "LICENSE_NOT_ALLOWED"
    if code.startswith(CREDIT_REQUIRED_PREFIXES) and not _text(item, "creator_name"):
        return "invalid", "MISSING_CREATOR"
    return "valid", None
