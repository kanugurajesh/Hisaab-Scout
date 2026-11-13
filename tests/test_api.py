import warnings

import pytest

from scout.main import create_app

from .conftest import FakeLlm, fixture_html, importer_for, settings

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from fastapi.testclient import TestClient


def client(**kw):
    s = settings(**kw)
    return TestClient(create_app(s, importer=importer_for(fixture_html("jsonld_full.html"), FakeLlm())))


def test_health_is_open():
    with client(scout_api_keys="k1") as c:
        assert c.get("/health").json()["ok"] is True


def test_import_returns_the_contract():
    with client() as c:
        body = c.post("/v1/events/import", json={"url": "https://example.org/diwali"}).json()
    assert body["found"] is True
    assert body["event"]["per_head_amount"] == {"value": 500, "source": "jsonld", "confidence": "high",
                                                "evidence": None}
    assert body["event"]["date"]["value"] == "2026-11-28"


@pytest.mark.parametrize("header,status", [(None, 401), ("Bearer nope", 401), ("Bearer k1", 200),
                                           ("Bearer k2", 200)])
def test_api_keys(header, status):
    with client(scout_api_keys="k1, k2") as c:
        headers = {"Authorization": header} if header else {}
        r = c.post("/v1/vendors/check", json={"gstin": "27AAPFU0939F1ZV"}, headers=headers)
    assert r.status_code == status
    if status == 401:
        assert r.json()["error"]["code"] == "unauthorized"


def test_rate_limit():
    with client(scout_rate_limit_per_minute=2) as c:
        codes = [c.post("/v1/vendors/check", json={"gstin": "27AAPFU0939F1ZV"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_errors_use_one_envelope():
    with TestClient(create_app(settings())) as c:
        blocked = c.post("/v1/events/import", json={"url": "http://127.0.0.1/admin"})
        invalid = c.post("/v1/events/import", json={"nope": 1})
    assert blocked.status_code == 422 and blocked.json()["error"]["code"] == "blocked_address"
    assert invalid.status_code == 422 and invalid.json()["error"]["code"] == "invalid_request"


def test_openapi_lists_both_endpoints():
    with client() as c:
        paths = c.get("/openapi.json").json()["paths"]
    assert {"/v1/events/import", "/v1/vendors/check", "/health"} <= set(paths)
