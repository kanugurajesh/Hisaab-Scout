import asyncio

import httpx
import pytest

from scout.errors import ScoutError
from scout.fetch import check_url, fetch_page, normalize_url

from .conftest import settings


def resolver(mapping: dict[str, list[str]]):
    async def resolve(host: str, _port: int) -> list[str]:
        if host not in mapping:
            raise OSError("no such host")
        return mapping[host]
    return resolve


PUBLIC = resolver({"example.org": ["93.184.215.14"], "events.example.org": ["93.184.215.15"],
                   "evil.example": ["10.0.0.5"], "mixed.example": ["93.184.215.14", "127.0.0.1"],
                   "mapped.example": ["::ffff:192.168.1.1"]})


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("raw,expected", [
    ("lu.ma/diwali", "https://lu.ma/diwali"),
    ("  https://Example.org/e?utm_source=wa&id=7#top ", "https://example.org/e?id=7"),
    ("https://example.org", "https://example.org/"),
    ("https://example.org/e?fbclid=abc", "https://example.org/e"),
])
def test_normalize_url(raw, expected):
    assert normalize_url(raw) == expected


@pytest.mark.parametrize("raw", ["", "ftp://example.org/x", "javascript:alert(1)", "https://"])
def test_normalize_url_rejects(raw):
    with pytest.raises(ScoutError) as e:
        normalize_url(raw)
    assert e.value.code == "invalid_url"


@pytest.mark.parametrize("url,code", [
    ("http://localhost/admin", "blocked_address"),
    ("http://127.0.0.1/", "blocked_address"),
    ("http://169.254.169.254/latest/meta-data/", "blocked_address"),
    ("http://[::1]/", "blocked_address"),
    ("https://evil.example/", "blocked_address"),
    ("https://mixed.example/", "blocked_address"),
    ("https://mapped.example/", "blocked_address"),
    ("https://example.org:8080/", "blocked_address"),
    ("https://user:pw@example.org/", "invalid_url"),
    ("https://nowhere.example/", "fetch_failed"),
])
def test_check_url_blocks_private_and_odd_targets(url, code):
    with pytest.raises(ScoutError) as e:
        run(check_url(url, PUBLIC))
    assert e.value.code == code


def test_check_url_allows_public():
    run(check_url("https://example.org/e", PUBLIC))


def page(handler):
    return httpx.MockTransport(handler)


def test_fetch_follows_redirect_and_decodes_charset():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/short":
            return httpx.Response(301, headers={"location": "https://events.example.org/e/1"})
        body = '<meta charset="windows-1252"><title>Caf\xe9</title>'.encode("cp1252")
        return httpx.Response(200, headers={"content-type": "text/html"}, content=body)

    p = run(fetch_page("https://example.org/short", settings(), resolver=PUBLIC, transport=page(handler)))
    assert p.final_url == "https://events.example.org/e/1"
    assert "Café" in p.html


def test_fetch_rechecks_every_redirect_hop():
    def handler(req):
        return httpx.Response(302, headers={"location": "http://evil.example/internal"})

    with pytest.raises(ScoutError) as e:
        run(fetch_page("https://example.org/", settings(), resolver=PUBLIC, transport=page(handler)))
    assert e.value.code == "blocked_address"


def test_fetch_stops_redirect_loops():
    def handler(req):
        return httpx.Response(302, headers={"location": "https://example.org/again"})

    with pytest.raises(ScoutError) as e:
        run(fetch_page("https://example.org/", settings(), resolver=PUBLIC, transport=page(handler)))
    assert e.value.code == "too_many_redirects"


def test_fetch_rejects_non_html():
    def handler(req):
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF")

    with pytest.raises(ScoutError) as e:
        run(fetch_page("https://example.org/poster.pdf", settings(), resolver=PUBLIC, transport=page(handler)))
    assert e.value.code == "not_html"


def test_fetch_caps_size():
    def handler(req):
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"x" * 5000)

    with pytest.raises(ScoutError) as e:
        run(fetch_page("https://example.org/", settings(fetch_max_bytes=1000), resolver=PUBLIC,
                       transport=page(handler)))
    assert e.value.code == "too_large"


def test_fetch_explains_bot_blocks():
    def handler(req):
        return httpx.Response(403, headers={"content-type": "text/html"}, content=b"no")

    with pytest.raises(ScoutError) as e:
        run(fetch_page("https://example.org/", settings(), resolver=PUBLIC, transport=page(handler)))
    assert e.value.code == "http_error" and e.value.upstream_status == 403
    assert "by hand" in e.value.message
