import datetime as dt
from decimal import Decimal

import pytest

from scout.events.normalize import choose_price, clean_text, clean_title, parse_amount, parse_start, venue_line
from scout.events.structured import RawOffer


@pytest.mark.parametrize("raw,date,time,assumed", [
    ("2026-11-28T18:30:00+05:30", dt.date(2026, 11, 28), "18:30", False),
    ("2026-12-19T13:30:00Z", dt.date(2026, 12, 19), "19:00", False),
    ("2026-12-31T20:00:00Z", dt.date(2027, 1, 1), "01:30", False),  # UTC evening is the next IST day
    ("2026-12-31T21:00", dt.date(2026, 12, 31), "21:00", True),
    ("2026-12-12", dt.date(2026, 12, 12), None, False),
    ("05/12/2026 5:00 PM", dt.date(2026, 12, 5), "17:00", True),  # day first, as Indian pages write it
])
def test_parse_start(raw, date, time, assumed):
    p = parse_start(raw)
    assert (p.date, p.time, p.tz_assumed) == (date, time, assumed)


@pytest.mark.parametrize("raw", [None, "", "TBA", "soon"])
def test_parse_start_gives_up(raw):
    assert parse_start(raw) is None


@pytest.mark.parametrize("raw,expected", [
    ("₹1,20,000", Decimal(120000)), ("Rs. 500/-", Decimal(500)), ("INR 499.00", Decimal("499.00")),
    (750, Decimal(750)), ("Free", Decimal(0)), ("call us", None), (None, None), (True, None),
])
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected


def test_price_tiers_take_lowest_and_say_so():
    r = choose_price([RawOffer(low_price="799.00", high_price="2499.00", currency="INR")])
    assert (r.amount, r.several) == (799, (799, 2499))


def test_price_free():
    assert choose_price([RawOffer(price="0", currency="INR")]).free


def test_price_foreign_currency():
    assert choose_price([RawOffer(price="20", currency="USD")]).not_rupees == "USD"


def test_price_ignores_currency_without_amount():
    # AllEvents tags priceless offers with "USD"; that must not hide a real INR price or warn.
    assert choose_price([RawOffer(currency="USD")]) is None
    assert choose_price([RawOffer(currency="USD"), RawOffer(price="300", currency="INR")]).amount == 300


def test_price_rounds_paise():
    r = choose_price([RawOffer(price="750.50", currency="INR")])
    assert (r.amount, r.rounded) == (751, True)


@pytest.mark.parametrize("name,street,locality,expected", [
    ("Nexus Mall", "Kukatpally Housing Board, KPHB Phase 9, Telangana 500085, India", "Hyderabad",
     "Nexus Mall, Hyderabad"),
    ("Clubhouse, Prestige Lakeside", None, "Bengaluru", "Clubhouse, Prestige Lakeside, Bengaluru"),
    ("Lakeview Ground", "Sector 4, HSR Layout, Bengaluru", None, "Lakeview Ground, Sector 4, HSR Layout, Bengaluru"),
    (None, "12 MG Road", "Pune", "12 MG Road, Pune"),
    ("Saras Baug", None, "Saras Baug", "Saras Baug"),
    (None, None, None, None),
])
def test_venue_line(name, street, locality, expected):
    assert venue_line(name, street, locality) == expected


def test_venue_line_is_capped():
    assert len(venue_line("A" * 150, None, "B" * 100)) <= 200


def test_clean_text_strips_html_and_cuts_at_word():
    assert clean_text("<p>Dinner, <b>rangoli</b></p>", 500) == "Dinner, rangoli"
    cut = clean_text("word " * 200, 50)
    assert len(cut) <= 50 and cut.endswith("…")


def test_clean_title_drops_site_suffix():
    assert clean_title("Diwali Night · Luma", "Luma") == "Diwali Night"
    assert clean_title("Luma", "Luma") == "Luma"
