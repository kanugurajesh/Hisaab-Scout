import datetime as dt
import random

import pytest

from scout.main import build_registry
from scout.vendors.check import check_vendor, names_match
from scout.vendors.gstin import CHARS, check_digit, checksum_ok, inspect, suggest_fix
from scout.vendors.models import VendorCheckRequest
from scout.vendors.registry import FixtureRegistry, RegistryUnavailable

from .conftest import settings

SWEETS = "36AGXPG4821K1ZX"
CANCELLED = "36BRCPR5517M1ZC"
LATE = "29AAKFK3390P1ZI"  # registered 1 Aug 2026


@pytest.fixture(scope="module")
def registry() -> FixtureRegistry:
    return build_registry(settings(gst_registry="fixture"))


def test_published_sample_gstins_pass_the_checksum():
    assert checksum_ok("27AAPFU0939F1ZV")
    assert checksum_ok("33AAACH7409R1Z8")


def test_made_up_gstin_fails():
    f = inspect("36ABCDE1234F1Z5")  # the GSTIN on Hisaab's own demo bill
    assert f.format_ok and not f.checksum_ok and f.state == "Telangana"


def test_inspect_normalizes_and_reads_parts():
    f = inspect(" 27aapfu0939f1zv ")
    assert f.gstin == "27AAPFU0939F1ZV" and f.entity_type == "Firm or LLP" and f.pan == "AAPFU0939F"


@pytest.mark.parametrize("misread,real", [
    ("27AAPFUO939F1ZV", "27AAPFU0939F1ZV"),  # letter O in a digit slot
    ("27AAPFU0939F12V", "27AAPFU0939F1ZV"),  # 2 for Z in the fixed slot
    ("2I AAPFU0939F1ZV".replace(" ", ""), None),  # 'I' in the state code: one fix, but checksum decides
])
def test_suggest_fix(misread, real):
    got = suggest_fix(misread)
    if real:
        assert got == real
    else:
        assert got is None or checksum_ok(got)


def test_suggestions_are_never_wrong_on_random_misreads():
    """Never suggest a different valid number than the real one. Silence is fine; wrong is not."""
    rng = random.Random(7)
    confusable = {"0": "O", "1": "I", "5": "S", "8": "B"}
    wrong = 0
    for _ in range(500):
        body = (f"{rng.randint(1, 37):02d}" + "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(5))
                + f"{rng.randint(0, 9999):04d}" + rng.choice("ABCDEFGHJK") + "1Z")
        real = body + check_digit(body)
        slots = [i for i in (0, 1, 7, 8, 9, 10) if real[i] in confusable]
        if not slots:
            continue
        i = rng.choice(slots)
        misread = real[:i] + confusable[real[i]] + real[i + 1:]
        got = suggest_fix(misread)
        if got is not None and got != real:
            wrong += 1
    assert wrong == 0


@pytest.mark.parametrize("bill,registered,ok", [
    ("Sri Lakshmi Sweets", "Sri Lakshmi Sweets", True),
    ("SRI LAKSHMI SWEETS & BAKERS", "Sri Lakshmi Sweets", True),
    ("M/s Balaji Tent House", "Balaji Tent House", True),
    ("Annapurna Fresh Mart Pvt Ltd", "Annapurna Fresh Mart Private Limited", True),
    ("Royal Caterers", "Sri Lakshmi Sweets", False),
])
def test_names_match(bill, registered, ok):
    assert names_match(bill, registered) is ok


def req(gstin, name=None, date=None):
    return VendorCheckRequest(gstin=gstin, vendor_name=name, bill_date=date)


def test_verified(registry):
    r = check_vendor(req(SWEETS, "Sri Lakshmi Sweets", dt.date(2026, 10, 20)), registry)
    assert r.verdict == "verified" and r.registry.source == "demo_fixture"
    assert "Demo registry" in r.summary


def test_cancelled_before_bill_date_is_a_mismatch(registry):
    r = check_vendor(req(CANCELLED, "Royal Caterers", dt.date(2026, 10, 20)), registry)
    assert r.verdict == "mismatch"
    assert next(c for c in r.checks if c.id == "active_on_bill_date").passed is False


def test_bill_dated_before_registration_is_a_mismatch(registry):
    assert check_vendor(req(LATE, "Kalpana Flower Decorators", dt.date(2026, 3, 1)), registry).verdict == "mismatch"


def test_wrong_shop_name_is_a_mismatch(registry):
    r = check_vendor(req(SWEETS, "Royal Caterers"), registry)
    name_check = next(c for c in r.checks if c.id == "name_matches")
    assert r.verdict == "mismatch" and "Sri Lakshmi Sweets" in name_check.message


def test_valid_but_unregistered_is_invalid(registry):
    body = "36AAACZ9999Z1Z"
    r = check_vendor(req(body + check_digit(body)), registry)
    assert r.verdict == "invalid" and r.registry.status == "not_found"


def test_bad_checksum_never_reaches_the_registry(registry):
    class Exploding:
        source = "x"

        def lookup(self, g):
            raise AssertionError("looked up an impossible GSTIN")

    r = check_vendor(req("36ABCDE1234F1Z5"), Exploding())
    assert r.verdict == "invalid" and r.summary.startswith("This can't be a real GSTIN")


def test_misread_suggestion_in_summary():
    r = check_vendor(req("27AAPFUO939F1ZV"), None)
    assert r.verdict == "invalid" and r.suggested_gstin == "27AAPFU0939F1ZV" and "27AAPFU0939F1ZV" in r.summary


def test_no_registry_is_honest():
    r = check_vendor(req("27AAPFU0939F1ZV", "Anything"), None)
    assert r.verdict == "format_ok" and r.registry.status == "not_configured"
    assert next(c for c in r.checks if c.id == "registered").passed is None


def test_registry_outage():
    class Down:
        source = "x"

        def lookup(self, g):
            raise RegistryUnavailable()

    r = check_vendor(req("27AAPFU0939F1ZV"), Down())
    assert r.verdict == "format_ok" and r.registry.status == "unavailable"


def test_demo_registry_rows_all_have_valid_checksums(registry):
    assert all(checksum_ok(g) for g in registry._by_gstin)
    assert all(c in CHARS for g in registry._by_gstin for c in g)
