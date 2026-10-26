"""Map the licence strings sources return onto SPDX-style codes. NC and ND are never mapped."""

import re

RESTRICTED_TOKENS = {"nc", "nd"}


def spdx_from_text(text: str | None) -> str | None:
    """'CC BY-SA 4.0' -> 'CC-BY-SA-4.0'. None for NC/ND and anything unrecognised."""
    if not text:
        return None
    low = text.strip().lower()
    if RESTRICTED_TOKENS & set(re.split(r"[^a-z0-9]+", low)):
        return None
    if re.search(r"\bcc[ -]?0\b|cc zero|publicdomain/zero", low):
        return "CC0-1.0"
    if re.search(r"public domain|\bpdm\b|\bpd\b|publicdomain/mark", low):
        return "PDM-1.0"
    m = re.search(r"\bcc[ -]by[ -]sa[ -](\d\.\d)", low)
    if m:
        return f"CC-BY-SA-{m.group(1)}"
    m = re.search(r"\bcc[ -]by[ -](\d\.\d)", low)
    if m:
        return f"CC-BY-{m.group(1)}"
    return None


def spdx_from_url(url: str | None) -> str | None:
    """Creative Commons deed / legal-code URLs: .../licenses/by-sa/4.0/ -> 'CC-BY-SA-4.0'."""
    if not url:
        return None
    low = url.lower()
    if "publicdomain/zero" in low:
        return "CC0-1.0"
    if "publicdomain/mark" in low:
        return "PDM-1.0"
    m = re.search(r"/licenses/(by|by-sa)/(\d\.\d)", low)
    if m:
        return f"CC-{m.group(1).upper()}-{m.group(2)}"
    return None
