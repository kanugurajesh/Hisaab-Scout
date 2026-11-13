"""Fetch one public web page, safely.

This service fetches URLs that users paste, so it must never become a way to reach the server's own
network (SSRF). Every hop of a redirect chain is checked: http(s) only, default ports only, no
credentials in the URL, and the host must resolve only to public addresses.

Known gap: the address is checked, then httpx resolves the name again to connect. A DNS server that
answers differently the second time (DNS rebinding) could slip past. Closing it needs connecting to
the checked IP directly; it's listed in docs/PRD.md under risks.
"""

import asyncio
import ipaddress
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx

from .config import Settings
from .errors import ScoutError

Resolver = Callable[[str, int], Awaitable[list[str]]]

TRACKING_PARAMS = re.compile(r"^(utm_\w+|fbclid|gclid|igshid|mc_cid|mc_eid|ref_src)$", re.I)
META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?([\w-]+)""", re.I)


@dataclass(frozen=True)
class FetchedPage:
    requested_url: str
    final_url: str
    status: int
    content_type: str
    html: str
    elapsed_ms: int


async def system_resolver(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, proto=0)
    return sorted({info[4][0] for info in infos})


def normalize_url(raw: str) -> str:
    """Trim, add https:// when missing, drop the fragment and tracking parameters.

    The result is also the cache key, so two shares of the same page hit the same entry.
    """
    raw = raw.strip()
    if not raw:
        raise ScoutError("invalid_url", "Paste a link to the event page.")
    if "://" not in raw:
        if re.match(r"^[a-z][a-z0-9+.\-]*:(?!\d)", raw, re.I):  # javascript:, mailto:, data: ...
            raise ScoutError("invalid_url", "Only http and https links can be imported.")
        raw = "https://" + raw
    parts = urlsplit(raw)
    if parts.scheme.lower() not in ("http", "https"):
        raise ScoutError("invalid_url", "Only http and https links can be imported.")
    if not parts.hostname:
        raise ScoutError("invalid_url", "That doesn't look like a web link.")
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                       if not TRACKING_PARAMS.match(k)])
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", query, ""))


def _is_public(addr: str) -> bool:
    ip = ipaddress.ip_address(addr.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


async def check_url(url: str, resolver: Resolver) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise ScoutError("invalid_url", "Only http and https links can be imported.")
    if parts.username or parts.password:
        raise ScoutError("invalid_url", "Links with a username or password can't be imported.")
    try:
        port = parts.port
    except ValueError:
        raise ScoutError("invalid_url", "That link has an invalid port.") from None
    if port not in (None, 80, 443):
        raise ScoutError("blocked_address", "Only links on the standard web ports can be imported.")
    host = parts.hostname or ""
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ScoutError("blocked_address", "That link points to a private address.")
    try:
        ipaddress.ip_address(host)
        addrs = [host]  # an IP literal: nothing to resolve
    except ValueError:
        addrs = None
    try:
        addrs = addrs or await resolver(host, port or (443 if parts.scheme == "https" else 80))
    except OSError:
        raise ScoutError("fetch_failed", "That website's address couldn't be found.") from None
    if not addrs or not all(_is_public(a) for a in addrs):
        raise ScoutError("blocked_address", "That link points to a private address.")


def _decode(body: bytes, header_charset: str | None) -> str:
    charset = header_charset
    if not charset:
        m = META_CHARSET.search(body[:4096])
        charset = m.group(1).decode("ascii", "ignore") if m else "utf-8"
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


async def fetch_page(
    url: str,
    settings: Settings,
    *,
    resolver: Resolver = system_resolver,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FetchedPage:
    started = time.monotonic()
    current = url
    headers = {
        "User-Agent": settings.scout_user_agent,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
        "Accept-Language": "en-IN,en;q=0.9",
    }
    timeout = httpx.Timeout(settings.fetch_timeout_seconds, connect=5.0)
    async with httpx.AsyncClient(follow_redirects=False, timeout=timeout, headers=headers,
                                 transport=transport) as client:
        for _ in range(settings.fetch_max_redirects + 1):
            await check_url(current, resolver)
            try:
                async with client.stream("GET", current) as resp:
                    if resp.is_redirect and "location" in resp.headers:
                        current = urljoin(current, resp.headers["location"])
                        continue
                    if resp.status_code >= 400:
                        blocked = resp.status_code in (401, 403, 429)
                        raise ScoutError(
                            "http_error",
                            "The website refused automatic reading. Fill the details in by hand."
                            if blocked else f"The website answered with an error ({resp.status_code}).",
                            upstream_status=resp.status_code,
                        )
                    ctype = resp.headers.get("content-type", "").lower()
                    if "html" not in ctype:
                        raise ScoutError("not_html", "That link isn't a web page (it may be an image or a PDF).")
                    body = bytearray()
                    async for chunk in resp.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > settings.fetch_max_bytes:
                            raise ScoutError("too_large", "That page is too large to read.")
                    return FetchedPage(
                        requested_url=url,
                        final_url=current,
                        status=resp.status_code,
                        content_type=ctype,
                        html=_decode(bytes(body), resp.charset_encoding),
                        elapsed_ms=int((time.monotonic() - started) * 1000),
                    )
            except httpx.TimeoutException:
                raise ScoutError("timeout", "The website took too long to answer.") from None
            except httpx.HTTPError as err:
                raise ScoutError("fetch_failed", f"Couldn't reach the website ({type(err).__name__}).") from None
    raise ScoutError("too_many_redirects", "That link redirects too many times.")
