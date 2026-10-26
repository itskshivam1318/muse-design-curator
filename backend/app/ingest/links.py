import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

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


def check_url(url: str) -> str:
    """Validate scheme and that every resolved address is public. Returns the host."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise AppError(400, "INVALID_URL", "Only http(s) URLs are accepted")
    host = parts.hostname
    try:
        ips = [str(ipaddress.ip_address(host))]
    except ValueError:
        try:
            ips = resolver(host)
        except OSError as e:
            raise AppError(400, "LINK_UNREACHABLE", "Host could not be resolved") from e
    if not ips or any(_blocked(ip) for ip in ips):
        raise AppError(400, "SSRF_BLOCKED", "URL points to a disallowed address")
    return host


def user_agent() -> str:
    st = get_settings()
    return f"DesignLanguageEngine/0.1 (+{st.CONTACT_EMAIL or st.PUBLIC_APP_URL})"


def fetch(url: str, max_bytes: int = MAX_PAGE_BYTES) -> tuple[str, str, bytes]:
    """GET with manual redirects (<=3), SSRF check on every hop. Returns (final_url, ctype, body)."""
    timeout = get_settings().LINK_FETCH_TIMEOUT_S
    headers = {"User-Agent": user_agent()}
    current = url
    with httpx.Client(follow_redirects=False, timeout=timeout, headers=headers) as client:
        for _hop in range(MAX_REDIRECTS + 1):
            check_url(current)
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
