import io
import json
from pathlib import Path

import pytest
from PIL import Image

from app.corpus import hashing
from app.corpus.provenance import LICENSE_ALLOWLIST, check_provenance
from app.corpus.sources.base import ManifestItem

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "corpus"


def item(**over: object) -> ManifestItem:
    base: dict[str, object] = {
        "id": "cx_test_fixture_a",
        "domain": "thing",
        "source": "test_fixture",
        "source_id": "a",
        "landing_url": "x/a.jpg",
        "image_url": "a.jpg",
        "creator_name": "Someone",
        "license_code": "CC0-1.0",
        "attribution_text": "credit",
        "fetched_at": "2026-01-01",
    }
    return ManifestItem.model_validate({**base, **over})


def test_cc0_test_fixture_is_valid() -> None:
    assert check_provenance(item()) == ("valid", None)


@pytest.mark.parametrize("code", ["CC-BY-4.0", "CC-BY-SA-3.0"])
def test_by_without_creator_invalid(code: str) -> None:
    assert check_provenance(item(license_code=code, creator_name=None)) == (
        "invalid", "MISSING_CREATOR",
    )  # fmt: skip
    assert check_provenance(item(license_code=code, creator_name="  ")) == (
        "invalid", "MISSING_CREATOR",
    )  # fmt: skip
    assert check_provenance(item(license_code=code)) == ("valid", None)


def test_cc0_without_creator_is_valid() -> None:
    assert check_provenance(item(creator_name=None)) == ("valid", None)


@pytest.mark.parametrize("code", ["All rights reserved", "CC-BY-NC-4.0", "CC-BY-ND-2.0", ""])
def test_license_off_allowlist_invalid(code: str) -> None:
    assert check_provenance(item(license_code=code)) == ("invalid", "LICENSE_NOT_ALLOWED")


@pytest.mark.parametrize("field", ["source", "source_id", "landing_url"])
def test_missing_source_invalid(field: str) -> None:
    assert check_provenance(item(**{field: ""})) == ("invalid", "MISSING_SOURCE")


def test_allowlist_is_exactly_the_agreed_set() -> None:
    assert LICENSE_ALLOWLIST == {
        "CC0-1.0", "PDM-1.0", "CC-BY-2.0", "CC-BY-2.5", "CC-BY-3.0", "CC-BY-4.0",
        "CC-BY-SA-2.0", "CC-BY-SA-3.0", "CC-BY-SA-4.0", "Pexels", "MIT", "Apache-2.0",
        "BSD-3-Clause", "GPL-3.0-only",
    }  # fmt: skip


def test_fixture_manifest_edge_cases_are_judged_by_the_same_rules() -> None:
    rows = [json.loads(ln) for ln in (FIXTURES / "manifest.jsonl").read_text().splitlines()]
    verdict = {r["source_id"]: check_provenance(ManifestItem.model_validate(r)) for r in rows}
    assert verdict["watch_01"] == ("valid", None)
    assert verdict["watch_reserved"] == ("invalid", "LICENSE_NOT_ALLOWED")
    assert verdict["watch_by_nocreator"] == ("invalid", "MISSING_CREATOR")
    assert {r["source"] for r in rows} == {"test_fixture"}


def _png(size: tuple[int, int]) -> bytes:
    img = Image.open(FIXTURES / "images" / "interior_03.jpg").resize(size)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def test_dhash_is_16_hex_and_resized_copy_is_within_six() -> None:
    a, b = _png((256, 256)), _png((100, 100))
    ha, hb = hashing.dhash(a), hashing.dhash(b)
    assert len(ha) == 16 and int(ha, 16) >= 0
    assert hashing.hamming(ha, hb) <= 6
    assert hashing.hamming(ha, ha) == 0


def test_dhash_of_different_images_differs() -> None:
    other = (FIXTURES / "images" / "ui_03.jpg").read_bytes()
    assert hashing.hamming(hashing.dhash(_png((256, 256))), hashing.dhash(other)) > 6


def test_sha256_matches_hashlib() -> None:
    assert hashing.sha256(b"abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
