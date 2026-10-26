import httpx
import pytest
import respx
from sqlalchemy.orm import Session

from app.db.repos import boards
from app.errors import AppError
from app.ingest import links
from app.ingest.common import ItemMeta
from tests.media import image_bytes

PAGE = (
    '<html><head><title>T</title><meta property="og:image" content="/img/a.png">'
    '<meta property="og:title" content="Nice Page"></head></html>'
)


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(links, "resolver", lambda host: ["93.184.216.34"])


@pytest.fixture
def board_id(session: Session) -> str:
    return boards.create(session, "b").id


@respx.mock
def test_og_image_page_becomes_image_item(session: Session, data_dir, board_id: str) -> None:
    route = respx.get("https://example.com/p").respond(200, text=PAGE)
    respx.get("https://example.com/img/a.png").respond(
        200, content=image_bytes(), headers={"content-type": "image/png"}
    )
    item = links.ingest_link(session, board_id, "https://example.com/p", ItemMeta()).item
    assert item.kind == "image" and item.origin == "link"
    assert item.page_url == "https://example.com/p"
    assert item.source_url == "https://example.com/img/a.png"
    assert item.page_title == "Nice Page" and item.creator_handle is None
    ua = route.calls[0].request.headers["user-agent"]
    assert ua.startswith("DesignLanguageEngine/0.1 (+")


@respx.mock
def test_login_wall_becomes_link_item(session: Session, data_dir, board_id: str) -> None:
    respx.get("https://insta.example/p/abc").respond(
        200, text="<html><head><title>Login</title></head><body>log in</body></html>"
    )
    item = links.ingest_link(session, board_id, "https://insta.example/p/abc", ItemMeta()).item
    assert item.kind == "link" and item.parse_status == "failed"
    assert item.parse_error_code == "LINK_NEEDS_EXTENSION"
    assert item.sha256 is None and item.page_url == "https://insta.example/p/abc"


@pytest.mark.parametrize(
    "url", ["http://10.0.0.1/x", "http://127.0.0.1/", "http://169.254.169.254/latest",
            "http://[::1]/", "http://192.168.1.5/"]
)  # fmt: skip
def test_literal_private_ips_blocked(session: Session, board_id: str, url: str) -> None:
    with pytest.raises(AppError) as e:
        links.ingest_link(session, board_id, url, ItemMeta())
    assert e.value.code == "SSRF_BLOCKED"


def test_hostname_resolving_private_blocked(
    session: Session, board_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(links, "resolver", lambda host: ["10.1.2.3"])
    with pytest.raises(AppError) as e:
        links.ingest_link(session, board_id, "https://sneaky.example/", ItemMeta())
    assert e.value.code == "SSRF_BLOCKED"


def test_non_http_scheme_rejected(session: Session, board_id: str) -> None:
    with pytest.raises(AppError) as e:
        links.ingest_link(session, board_id, "file:///etc/passwd", ItemMeta())
    assert e.value.code == "INVALID_URL"


@respx.mock
def test_redirect_to_private_blocked(session: Session, board_id: str) -> None:
    respx.get("https://example.com/r").respond(302, headers={"location": "http://10.0.0.1/"})
    with pytest.raises(AppError) as e:
        links.ingest_link(session, board_id, "https://example.com/r", ItemMeta())
    assert e.value.code == "SSRF_BLOCKED"


@respx.mock
def test_more_than_three_redirects_rejected(session: Session, board_id: str) -> None:
    for i in range(6):
        respx.get(f"https://example.com/{i}").respond(
            302, headers={"location": f"https://example.com/{i + 1}"}
        )
    with pytest.raises(AppError) as e:
        links.ingest_link(session, board_id, "https://example.com/0", ItemMeta())
    assert e.value.code == "TOO_MANY_REDIRECTS"


@respx.mock
def test_body_capped_at_2mib() -> None:
    respx.get("https://example.com/big").respond(200, content=b"a" * (3 * 1024 * 1024))
    _u, _c, body = links.fetch("https://example.com/big")
    assert len(body) == 2 * 1024 * 1024


@respx.mock
def test_timeout_maps_to_error() -> None:
    respx.get("https://example.com/slow").mock(side_effect=httpx.ConnectTimeout("x"))
    with pytest.raises(AppError) as e:
        links.fetch("https://example.com/slow")
    assert e.value.code == "LINK_FETCH_FAILED"


def test_parse_page_variants() -> None:
    p = links.parse_page(
        b'<link rel="image_src" href="a.jpg"><meta name="twitter:image" content="t.jpg">',
        "https://x.test/dir/",
    )
    assert p.image == "https://x.test/dir/t.jpg"
    p2 = links.parse_page(b'<link rel="image_src" href="a.jpg">', "https://x.test/dir/")
    assert p2.image == "https://x.test/dir/a.jpg"
    p3 = links.parse_page(
        b'<meta property="og:video" content="https://v.test/a.mp4">', "https://x.test"
    )
    assert p3.video == "https://v.test/a.mp4" and p3.image is None


def test_connection_pinned_to_vetted_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpcore

    answers = iter([["93.184.216.34"], ["10.0.0.5"], ["10.0.0.5"]])
    monkeypatch.setattr(links, "resolver", lambda host: next(answers))
    seen: list[str] = []

    def fake_connect(self, host, port, timeout=None, local_address=None, socket_options=None):  # type: ignore[no-untyped-def]
        seen.append(host)
        raise httpcore.ConnectError("stop")

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", fake_connect)
    with pytest.raises(AppError) as e:
        links.fetch("https://rebind.example/")
    assert e.value.code == "LINK_FETCH_FAILED"
    assert seen == ["93.184.216.34"]


def test_proxy_env_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpcore

    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    seen: list[str] = []

    def fake_connect(self, host, port, timeout=None, local_address=None, socket_options=None):  # type: ignore[no-untyped-def]
        seen.append(f"{host}:{port}")
        raise httpcore.ConnectError("stop")

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", fake_connect)
    with pytest.raises(AppError):
        links.fetch("http://example.com/")
    assert seen == ["93.184.216.34:80"]
