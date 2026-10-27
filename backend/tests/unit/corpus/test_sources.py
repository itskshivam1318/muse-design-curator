import json
from pathlib import Path

import httpx
import pytest
import respx

from app.config import Settings
from app.corpus.sources import openverse as openverse_module
from app.corpus.sources.aic import AicSource
from app.corpus.sources.cleveland import API as CLEVELAND_API
from app.corpus.sources.cleveland import ClevelandSource
from app.corpus.sources.commons import API as COMMONS_API
from app.corpus.sources.commons import CommonsSource
from app.corpus.sources.europeana import API as EUROPEANA_API
from app.corpus.sources.europeana import EuropeanaSource
from app.corpus.sources.met import OBJECTS_API as MET_OBJECTS
from app.corpus.sources.met import SEARCH_API as MET_SEARCH
from app.corpus.sources.met import MetSource
from app.corpus.sources.openverse import OpenverseSource
from app.corpus.sources.pexels import PexelsSource
from app.corpus.sources.rijks import RijksSource
from app.corpus.sources.self_capture import SelfCaptureSource
from app.corpus.sources.smithsonian import API as SI_API
from app.corpus.sources.smithsonian import BUCKET, SmithsonianSource

NO_SLEEP = lambda _s: None


def settings(**kw: object) -> Settings:
    return Settings(CONTACT_EMAIL="me@example.org", **kw)  # type: ignore[arg-type]


def page(pageid: int, title: str, licence: str, artist: str | None, **extra: str) -> dict:
    meta: dict = {
        "LicenseShortName": {"value": licence},
        **{k: {"value": v} for k, v in extra.items()},
    }
    if artist is not None:
        meta["Artist"] = {"value": artist}
    return {
        "pageid": pageid, "title": f"File:{title}", "index": pageid,
        "imageinfo": [{
            "url": f"https://upload.example/{pageid}.jpg", "thumburl": f"https://upload.example/t{pageid}.jpg",
            "descriptionurl": f"https://commons.wikimedia.org/wiki/File:{title}", "extmetadata": meta,
        }],
    }  # fmt: skip


@respx.mock
def test_commons_drops_nc_nd_and_keeps_licensed_with_user_agent() -> None:
    route = respx.get(COMMONS_API).respond(json={"query": {"pages": [
        page(1, "Dial.jpg", "CC BY-SA 4.0", "A. Maker", LicenseUrl="https://creativecommons.org/licenses/by-sa/4.0"),
        page(2, "NC.jpg", "CC BY-NC 4.0", "B"),
        page(3, "ND.jpg", "CC BY-ND 2.0", "C"),
        page(4, "Zero.jpg", "CC0", None),
    ]}})  # fmt: skip
    src = CommonsSource("thing", settings(), sleep=NO_SLEEP)
    got = list(src.search("wristwatch dial", 10))
    assert [g.source_id for g in got] == ["1", "4"]
    assert got[0].license_code == "CC-BY-SA-4.0"
    assert got[0].id == "cx_commons_1"
    assert got[1].license_code == "CC0-1.0" and got[1].creator_name is None
    ua = route.calls[0].request.headers["user-agent"]
    assert ua == "DesignLanguageEngine/0.1 (contact: me@example.org)"
    assert "filetype:bitmap wristwatch dial" in str(route.calls[0].request.url).replace(
        "+", " "
    ).replace("%3A", ":")


@respx.mock
def test_commons_artist_html_is_stripped() -> None:
    artist = '<a href="//commons.wikimedia.org/wiki/User:X" title="User:X">Jane &amp; Co</a><br/> <span>(2020)</span>'
    respx.get(COMMONS_API).respond(
        json={"query": {"pages": [page(7, "A.jpg", "CC BY 4.0", artist)]}}
    )
    (got,) = CommonsSource("thing", settings(), sleep=NO_SLEEP).search("x", 5)
    assert got.creator_name == "Jane & Co (2020)"
    assert "<" not in got.attribution_text and "Jane & Co" in got.attribution_text


@respx.mock
def test_commons_follows_continue_and_respects_limit() -> None:
    calls = respx.get(COMMONS_API).mock(side_effect=[
        httpx.Response(200, json={"continue": {"gsroffset": 1}, "query": {"pages": [page(1, "a.jpg", "CC0", None)]}}),
        httpx.Response(200, json={"query": {"pages": [page(2, "b.jpg", "CC0", None), page(3, "c.jpg", "CC0", None)]}}),
    ])  # fmt: skip
    got = list(CommonsSource("thing", settings(), sleep=NO_SLEEP).search("x", 2))
    assert [g.source_id for g in got] == ["1", "2"] and calls.call_count == 2


def test_commons_throttles_to_200_per_minute() -> None:
    sleeps: list[float] = []
    src = CommonsSource("thing", settings(), sleep=sleeps.append)
    src._throttle.wait()
    src._throttle.wait()
    assert sleeps and sleeps[0] == pytest.approx(0.3, abs=0.05)


@respx.mock
def test_met_skips_not_public_domain_and_imageless() -> None:
    respx.get(MET_SEARCH).respond(json={"total": 4, "objectIDs": [1, 2, 3, 4]})
    objs = {
        1: {"objectID": 1, "isPublicDomain": True, "primaryImage": "https://i/1.jpg", "objectURL": "https://m/1", "artistDisplayName": "Ann", "title": "Watch"},
        2: {"objectID": 2, "isPublicDomain": False, "primaryImage": "", "objectURL": "https://m/2", "title": "Closed"},
        3: {"objectID": 3, "isPublicDomain": False, "primaryImage": "https://i/3.jpg", "objectURL": "https://m/3", "title": "Flag off"},
        4: {"objectID": 4, "isPublicDomain": True, "primaryImage": "", "objectURL": "https://m/4", "title": "No image"},
    }  # fmt: skip
    for i, o in objs.items():
        respx.get(f"{MET_OBJECTS}/{i}").respond(json=o)
    sleeps: list[float] = []
    got = list(MetSource("thing", settings(), sleep=sleeps.append).search("watch", 10))
    assert [g.source_id for g in got] == ["1"]
    assert got[0].license_code == "CC0-1.0" and got[0].creator_name == "Ann"
    assert sleeps == [0.4] * 4


@respx.mock
def test_pexels_yields_nothing_unless_enabled() -> None:
    route = respx.get("https://api.pexels.com/v1/search").respond(json={"photos": []})
    assert list(PexelsSource("thing", settings(PEXELS_API_KEY="k")).search("x", 5)) == []
    assert list(PexelsSource("thing", settings(PEXELS_ENABLED=True)).search("x", 5)) == []  # no key
    assert route.call_count == 0


@respx.mock
def test_pexels_enabled_credit_and_cap() -> None:
    photos = [
        {"id": i, "url": f"https://pexels.com/photo/{i}", "photographer": "Pat", "src": {"large2x": f"https://p/{i}.jpg"}}
        for i in range(1, 6)
    ]  # fmt: skip
    route = respx.get("https://api.pexels.com/v1/search").respond(json={"photos": photos})
    src = PexelsSource("thing", settings(PEXELS_ENABLED=True, PEXELS_API_KEY="key"))
    got = list(src.search("x", 1000))
    assert len(got) == 5 and got[0].license_code == "Pexels"
    assert got[0].attribution_text == "Photo by Pat on Pexels"
    assert route.calls[0].request.headers["authorization"] == "key"
    assert int(route.calls[0].request.url.params["per_page"]) <= 80


@respx.mock
def test_openverse_uses_returned_attribution_and_licence_filter() -> None:
    route = respx.get("https://api.openverse.org/v1/images/").respond(json={"page_count": 1, "results": [
        {"id": "u1", "url": "https://i/1.jpg", "foreign_landing_url": "https://flickr/1", "creator": "Zed", "license": "by", "license_version": "2.0", "license_url": "https://creativecommons.org/licenses/by/2.0/", "attribution": '"T" by Zed is licensed under CC BY 2.0.'},
        {"id": "u2", "url": "https://i/2.jpg", "foreign_landing_url": "https://flickr/2", "license": "pdm", "license_version": "1.0"},
        {"id": "u3", "url": "https://i/3.jpg", "foreign_landing_url": "https://flickr/3", "license": "by-nc", "license_version": "2.0"},
    ]})  # fmt: skip
    got = list(OpenverseSource("thing", settings()).search("dial", 10))
    assert [g.license_code for g in got] == ["CC-BY-2.0", "PDM-1.0"]
    assert got[0].attribution_text == '"T" by Zed is licensed under CC BY 2.0.'
    assert route.calls[0].request.url.params["license"] == "by,by-sa,cc0,pdm"
    assert route.calls[0].request.url.params["filter_dead"] == "false"
    assert route.calls[0].request.url.params["page_size"] == "10"


OV_ROW = {"id": "u1", "url": "https://i/1.jpg", "license": "cc0", "license_version": "1.0"}


@respx.mock
def test_openverse_token_is_reused_and_pages_stay_within_the_authed_cap(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(openverse_module, "_tokens", {})
    token = respx.post("https://api.openverse.org/v1/auth_tokens/token/").respond(
        json={"access_token": "t1", "expires_in": 43200}
    )
    images = respx.get("https://api.openverse.org/v1/images/").respond(
        json={"page_count": 1, "results": [OV_ROW]}
    )
    s = settings(OPENVERSE_CLIENT_ID="id", OPENVERSE_CLIENT_SECRET="secret")
    list(OpenverseSource("thing", s).search("dial", 200))
    list(OpenverseSource("thing", s).search("case", 200))
    assert token.call_count == 1
    assert images.calls[0].request.headers["authorization"] == "Bearer t1"
    assert images.calls[0].request.url.params["page_size"] == "50"  # above 50 the API sends 401


@respx.mock
def test_openverse_refreshes_a_rejected_token_once(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(openverse_module, "_tokens", {})
    token = respx.post("https://api.openverse.org/v1/auth_tokens/token/").mock(side_effect=[
        httpx.Response(200, json={"access_token": "old", "expires_in": 43200}),
        httpx.Response(200, json={"access_token": "new", "expires_in": 43200}),
    ])  # fmt: skip
    images = respx.get("https://api.openverse.org/v1/images/").mock(side_effect=[
        httpx.Response(401), httpx.Response(200, json={"page_count": 1, "results": [OV_ROW]}),
    ])  # fmt: skip
    s = settings(OPENVERSE_CLIENT_ID="id", OPENVERSE_CLIENT_SECRET="secret")
    assert len(list(OpenverseSource("thing", s).search("dial", 5))) == 1
    assert token.call_count == 2
    assert images.calls[1].request.headers["authorization"] == "Bearer new"


@respx.mock
def test_openverse_never_pages_past_240_results() -> None:
    images = respx.get("https://api.openverse.org/v1/images/").respond(
        json={"page_count": 99, "results": [OV_ROW] * 20}
    )
    assert len(list(OpenverseSource("thing", settings()).search("dial", 1000))) == 240
    assert images.call_count == 12


def test_met_searches_v1_1_but_reads_objects_from_v1() -> None:
    assert MET_SEARCH.endswith("/v1.1/search") and MET_OBJECTS.endswith("/v1/objects")


@respx.mock
def test_aic_keeps_only_public_domain_with_image() -> None:
    route = respx.post("https://api.artic.edu/api/v1/artworks/search").respond(json={
        "pagination": {"total_pages": 1}, "config": {"iiif_url": "https://iiif.example/2"},
        "data": [
            {"id": 1, "title": "Dress", "image_id": "abc", "artist_title": "Ann", "is_public_domain": True},
            {"id": 2, "title": "Closed", "image_id": "def", "is_public_domain": False},
            {"id": 3, "title": "No image", "image_id": None, "is_public_domain": True},
        ],
    })  # fmt: skip
    (got,) = AicSource("thing", settings()).search("dress", 10)
    assert got.image_url == "https://iiif.example/2/abc/full/843,/0/default.jpg"
    assert got.license_code == "CC0-1.0" and got.id == "cx_aic_1"
    # without AIC-User-Agent the museum's Cloudflare answers every request with a 403 challenge
    assert route.calls[0].request.headers["AIC-User-Agent"].startswith("DesignLanguageEngine/")


@respx.mock
def test_smithsonian_reads_bulk_lines_and_requires_cc0_media() -> None:
    def rec(i: int, access: str, title: str = "Floral textile") -> str:
        return json.dumps({"id": f"edanmdm:chndm_{i}", "title": title, "content": {
            "descriptiveNonRepeating": {"record_link": f"https://si.edu/{i}", "title": {"content": title},
                "online_media": {"media": [{"type": "Images", "content": f"https://i/{i}.jpg", "usage": {"access": access}}]}},
            "freetext": {"name": [{"label": "Designer", "content": "Dee"}]},
        }})  # fmt: skip

    body = "\n".join([rec(1, "CC0"), rec(2, "Usage Conditions Apply"), rec(3, "CC0", "Chair"), ""])
    respx.get(f"{BUCKET}/chndm/00.txt").respond(text=body)
    respx.get(url__regex=rf"{BUCKET}/chndm/(?!00).*").respond(404)
    got = list(SmithsonianSource("thing", settings()).search("textile", 10))
    assert [g.source_id for g in got] == ["chndm_1"]
    assert got[0].creator_name == "Dee" and got[0].license_code == "CC0-1.0"


@respx.mock
def test_smithsonian_uses_the_search_api_when_a_key_is_set() -> None:
    def row(i: int, access: str) -> dict:
        return {"id": f"ld1-{i}", "content": {"descriptiveNonRepeating": {
            "record_ID": f"nasm_{i}", "record_link": f"https://si.edu/{i}",
            "title": {"content": "Wristwatch, Hour Angle"},
            "online_media": {"media": [{"type": "Images", "content": f"https://ids/{i}", "usage": {"access": access}}]},
        }}}  # fmt: skip

    route = respx.get(SI_API).respond(
        json={
            "response": {"rowCount": 2, "rows": [row(1, "CC0"), row(2, "Usage Conditions Apply")]}
        }
    )
    bulk = respx.get(url__regex=rf"{BUCKET}/.*").respond(404)
    got = list(
        SmithsonianSource("thing", settings(SMITHSONIAN_API_KEY="k")).search("wristwatch", 10)
    )
    assert [g.source_id for g in got] == ["nasm_1"] and got[0].license_code == "CC0-1.0"
    params = route.calls[0].request.url.params
    assert params["api_key"] == "k" and params["q"].startswith("wristwatch AND")
    assert "media_usage:CC0" in params["q"] and bulk.call_count == 0


@respx.mock
def test_rijks_resolves_ids_and_reads_licence_per_object() -> None:
    respx.get("https://data.rijksmuseum.nl/search/collection").respond(json={"orderedItems": [
        {"id": "https://id.rijksmuseum.nl/200"}, {"id": "https://id.rijksmuseum.nl/201"}]})  # fmt: skip

    def doc(licence: str) -> dict:
        return {
            "identified_by": [{"type": "Name", "content": "Poster"}],
            "produced_by": {"carried_out_by": [{"_label": "Hans"}]},
            "subject_to": [{"classified_as": [{"id": licence}]}],
            "representation": [{"digitally_shown_by": [{"access_point": [{"id": "https://iiif/x.jpg"}]}]}],
        }  # fmt: skip

    respx.get("https://id.rijksmuseum.nl/200").respond(
        json=doc("https://creativecommons.org/publicdomain/zero/1.0/")
    )
    respx.get("https://id.rijksmuseum.nl/201").respond(
        json=doc("https://example.org/all-rights-reserved")
    )
    got = list(RijksSource("thing", settings(), sleep=NO_SLEEP).search("poster", 10))
    assert [(g.source_id, g.license_code, g.creator_name) for g in got] == [
        ("200", "CC0-1.0", "Hans")
    ]


def test_self_capture_reads_hand_written_manifest(tmp_path: Path) -> None:
    m = tmp_path / "m.jsonl"
    m.write_text(json.dumps({
        "source_id": "app1", "landing_url": "https://github.com/x/y", "image_url": "shots/a.png",
        "creator_name": "X contributors", "license_code": "GPL-3.0-only", "attribution_text": "Screenshot of Y (GPL-3.0)",
        "fetched_at": "2026-10-01"}) + "\n")  # fmt: skip
    src = SelfCaptureSource("ui", settings())
    src.manifest = m
    (got,) = src.search("", 5)
    assert (
        got.id == "cx_self_capture_app1"
        and got.license_code == "GPL-3.0-only"
        and got.domain == "ui"
    )


@respx.mock
def test_commons_searches_files_tagged_as_the_subject_first() -> None:
    route = respx.get(COMMONS_API).mock(side_effect=[
        httpx.Response(200, json={"query": {"pages": [page(1, "Watch.jpg", "CC0", "Ann")]}}),
        httpx.Response(200, json={"query": {"pages": [
            page(1, "Watch.jpg", "CC0", "Ann"), page(2, "Dial.jpg", "CC0", "Bo"),
        ]}}),
    ])  # fmt: skip
    got = list(CommonsSource("watch", settings(), sleep=lambda _s: None).search("arabic", 10))
    assert [g.source_id for g in got] == ["1", "2"]  # the tagged file once, then the broad one
    first = route.calls[0].request.url.params["gsrsearch"]
    assert first == "filetype:bitmap haswbstatement:P180=Q178794|P180=Q26965868 arabic"
    assert route.calls[1].request.url.params["gsrsearch"] == "filetype:bitmap arabic"


@respx.mock
def test_europeana_needs_a_key_and_keeps_only_open_rights() -> None:
    route = respx.get(EUROPEANA_API).respond(json={"totalResults": 3, "items": [
        {"id": "/2021009/_E1", "edmIsShownBy": ["https://img/1.jpg"], "title": ["Wristwatch Flipper"],
         "rights": ["http://creativecommons.org/licenses/by/4.0/"], "dcCreator": ["Saarinen, UA"],
         "dataProvider": ["Finnish Heritage Agency"]},
        {"id": "/1/_NC", "edmIsShownBy": ["https://img/2.jpg"], "rights": ["http://creativecommons.org/licenses/by-nc/4.0/"]},
        {"id": "/1/_NOIMG", "rights": ["http://creativecommons.org/publicdomain/zero/1.0/"]},
    ]})  # fmt: skip
    assert list(EuropeanaSource("thing", settings()).search("wristwatch", 10)) == []
    assert route.call_count == 0
    (got,) = EuropeanaSource("thing", settings(EUROPEANA_API_KEY="k")).search("wristwatch", 10)
    assert got.license_code == "CC-BY-4.0" and got.source_id == "2021009__E1"
    assert got.landing_url == "https://www.europeana.eu/item/2021009/_E1"
    assert got.attribution_text == (
        '"Wristwatch Flipper", Saarinen, UA, Finnish Heritage Agency, CC-BY-4.0, via Europeana'
    )
    params = route.calls[0].request.url.params
    assert (
        params["reusability"] == "open" and params["wskey"] == "k" and params["qf"] == "TYPE:IMAGE"
    )


@respx.mock
def test_cleveland_keeps_cc0_with_web_image() -> None:
    route = respx.get(CLEVELAND_API).respond(json={"info": {"total": 3}, "data": [
        {"id": 7, "title": "Armchair", "share_license_status": "CC0", "url": "https://clevelandart.org/art/7",
         "images": {"web": {"url": "https://cdn/7.jpg"}}, "creators": [{"description": "Ann (French)"}]},
        {"id": 8, "title": "Copyrighted", "share_license_status": "Copyrighted", "images": {"web": {"url": "https://cdn/8.jpg"}}},
        {"id": 9, "title": "No image", "share_license_status": "CC0", "images": None},
    ]})  # fmt: skip
    (got,) = ClevelandSource("thing", settings()).search("armchair", 10)
    assert (
        got.source_id == "7"
        and got.license_code == "CC0-1.0"
        and got.creator_name == "Ann (French)"
    )
    assert route.calls[0].request.url.params["cc0"] == "1"
