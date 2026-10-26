import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpcore
import httpx
from selectolax.lexbor import LexborHTMLParser as HTMLParser
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.ingest.common import IngestResult, ItemMeta, create_item
from app.ingest.images import ingest_image

MAX_REDIRECTS = 3
MAX_PAGE_BYTES = 2 * 1024 * 1024


def _default_resolver(host: str) -> list[str]:
    return [str(info[4][0]) for info in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)]


# Injectable for tests: host -> list of IP strings.
resolver: Callable[[str], list[str]] = _default_resolver


def _blocked(ip: str) -> bool:
    a = ipaddress.ip_address(ip.split("%")[0])
    if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped:
        a = a.ipv4_mapped
    return (
        a.is_private or a.is_loopback or a.is_link_local or a.is_reserved
        or a.is_multicast or a.is_unspecified or not a.is_global
    )  # fmt: skip


def _exempt_hosts() -> set[str]:
    raw = get_settings().LINK_ALLOW_PRIVATE_HOSTS
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def check_url(url: str) -> str:
    """Validate scheme and that every resolved address is public. Returns a vetted IP.

    Hosts listed in LINK_ALLOW_PRIVATE_HOSTS (test-only, empty by default) skip the address check.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise AppError(400, "INVALID_URL", "Only http(s) URLs are accepted")
    host = parts.hostname
    exempt = host.lower() in _exempt_hosts()
    try:
        ips = [str(ipaddress.ip_address(host))]
    except ValueError:
        try:
            ips = resolver(host)
        except OSError as e:
            raise AppError(400, "LINK_UNREACHABLE", "Host could not be resolved") from e
    if not ips or (not exempt and any(_blocked(ip) for ip in ips)):
        raise AppError(400, "SSRF_BLOCKED", "URL points to a disallowed address")
    return ips[0]


class _PinnedBackend(httpcore.NetworkBackend):
    """Connects to the vetted IP; TLS SNI/verification still use the URL hostname."""

    def __init__(self, ip: str, inner: httpcore.NetworkBackend) -> None:
        self._ip = ip
        self._inner = inner

    def connect_tcp(
        self, host: str, port: int, timeout=None, local_address=None, socket_options=None
    ):  # type: ignore[no-untyped-def]
        return self._inner.connect_tcp(
            self._ip, port, timeout=timeout, local_address=local_address,
            socket_options=socket_options,
        )  # fmt: skip

    def connect_unix_socket(self, *a, **k):  # type: ignore[no-untyped-def]
        raise httpcore.ConnectError("unix sockets are not allowed")

    def sleep(self, seconds: float) -> None:
        self._inner.sleep(seconds)


def _pinned_transport(ip: str) -> httpx.HTTPTransport:
    t = httpx.HTTPTransport()
    t._pool._network_backend = _PinnedBackend(ip, t._pool._network_backend)  # type: ignore[attr-defined]
    return t


def user_agent() -> str:
    st = get_settings()
    return f"DesignLanguageEngine/0.1 (+{st.CONTACT_EMAIL or st.PUBLIC_APP_URL})"


def fetch(url: str, max_bytes: int = MAX_PAGE_BYTES) -> tuple[str, str, bytes]:
    """GET with manual redirects (<=3), SSRF check on every hop. Returns (final_url, ctype, body)."""
    timeout = get_settings().LINK_FETCH_TIMEOUT_S
    headers = {"User-Agent": user_agent()}
    current = url
    for _hop in range(MAX_REDIRECTS + 1):
        ip = check_url(current)
        with httpx.Client(
            follow_redirects=False, timeout=timeout, headers=headers, trust_env=False,
            transport=_pinned_transport(ip),
        ) as client:  # fmt: skip
            try:
                with client.stream("GET", current) as r:
                    if r.status_code in (301, 302, 303, 307, 308):
                        loc = r.headers.get("location")
                        if not loc:
                            raise AppError(502, "LINK_FETCH_FAILED", "Redirect without location")
                        current = urljoin(current, loc)
                        continue
                    if r.status_code >= 400:
                        raise AppError(
                            502, "LINK_FETCH_FAILED", f"Remote server returned {r.status_code}"
                        )
                    body = bytearray()
                    for chunk in r.iter_bytes():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            del body[max_bytes:]
                            break
                    return current, r.headers.get("content-type", ""), bytes(body)
            except httpx.HTTPError as e:
                raise AppError(502, "LINK_FETCH_FAILED", "Could not fetch the URL") from e
    raise AppError(400, "TOO_MANY_REDIRECTS", f"More than {MAX_REDIRECTS} redirects")


@dataclass
class Unfurl:
    title: str | None
    image: str | None
    video: str | None


def parse_page(html: bytes, base_url: str) -> Unfurl:
    tree = HTMLParser(html)

    def meta(attr: str, *names: str) -> str | None:
        for n in names:
            for node in tree.css("meta"):
                if (node.attributes.get(attr) or "").lower() == n:
                    v = (node.attributes.get("content") or "").strip()
                    if v:
                        return v
        return None

    image = meta("property", "og:image", "og:image:url") or meta("name", "twitter:image")
    if image is None:
        for node in tree.css("link"):
            if (node.attributes.get("rel") or "").lower() == "image_src":
                image = (node.attributes.get("href") or "").strip() or None
                if image:
                    break
    title = meta("property", "og:title") or meta("name", "twitter:title")
    if title is None:
        t = tree.css_first("title")
        title = t.text(strip=True) if t else None
    video = meta("property", "og:video", "og:video:url")
    return Unfurl(
        title=title or None,
        image=urljoin(base_url, image) if image else None,
        video=urljoin(base_url, video) if video else None,
    )


def ingest_link(session: Session, board_id: str, url: str, meta: ItemMeta) -> IngestResult:
    final_url, _ctype, body = fetch(url)
    page = parse_page(body, final_url)
    if page.image:
        try:
            _u, _c, img_bytes = fetch(page.image, get_settings().MAX_UPLOAD_BYTES + 1)
            img_meta = ItemMeta(
                origin="link", source_url=page.image, page_url=final_url,
                page_title=page.title, x=meta.x, y=meta.y,
            )  # fmt: skip
            return ingest_image(session, board_id, img_bytes, img_meta)
        except AppError:
            pass  # unusable image: fall through to a link item
    link_meta = ItemMeta(
        origin="link", source_url=final_url, page_url=final_url, page_title=page.title,
        x=meta.x, y=meta.y,
    )  # fmt: skip
    item = create_item(
        session, board_id, link_meta, kind="link", w=240, h=160,
        parse_status="failed", parse_error_code="LINK_NEEDS_EXTENSION",
    )  # fmt: skip
    return IngestResult(item)
