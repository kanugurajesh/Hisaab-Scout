"""Turn raw page values into the exact shapes Hisaab's form takes. Pure functions, no I/O."""

import datetime as dt
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from dateutil import parser as dateparser

from .structured import RawOffer

IST = ZoneInfo("Asia/Kolkata")
HAS_TIME = re.compile(r"\d{1,2}:\d{2}")
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
VENUE_MAX = 200
NOTES_MAX = 500


@dataclass(frozen=True)
class ParsedStart:
    date: dt.date
    time: str | None  # "HH:MM" IST
    tz_assumed: bool


def parse_start(raw: str | None) -> ParsedStart | None:
    """ISO 8601 first (what structured data uses), then day-first free text (what Indian pages use).

    A time with no timezone is taken as IST, and the caller is told so it can say so.
    """
    if not raw or not raw.strip():
        return None
    raw = raw.strip()
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = dateparser.parse(raw, dayfirst=True, fuzzy=True)
        except (ValueError, OverflowError):
            return None
    if not HAS_TIME.search(raw):
        return ParsedStart(parsed.date(), None, False)
    if parsed.tzinfo is None:
        return ParsedStart(parsed.date(), parsed.strftime("%H:%M"), True)
    local = parsed.astimezone(IST)
    return ParsedStart(local.date(), local.strftime("%H:%M"), False)


def parse_amount(v: object) -> Decimal | None:
    """'₹1,20,000', 'Rs. 500/-', 'INR 499.00', 500, 'Free' -> Decimal. Indian digit grouping is fine
    because commas are simply dropped."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float, Decimal)):
        return Decimal(str(v))
    s = str(v).strip()
    if re.fullmatch(r"(?i)free|0|nil|none", s):
        return Decimal(0)
    m = NUMBER.search(s)
    if not m:
        return None
    try:
        return Decimal(m.group(0).replace(",", ""))
    except InvalidOperation:
        return None


@dataclass(frozen=True)
class PriceResult:
    amount: int | None
    free: bool = False
    several: tuple[int, int] | None = None  # (lowest, highest) when tiers differ
    not_rupees: str | None = None  # the currency, when it isn't INR
    rounded: bool = False


def choose_price(offers: list[RawOffer]) -> PriceResult | None:
    """The lowest positive rupee price. For a group collection the per-head amount is the
    organizer's call; the lowest ticket is the safest default, and tiers are flagged."""
    values: list[Decimal] = []
    for o in offers:
        amounts = [a for a in (parse_amount(r) for r in (o.price, o.low_price, o.high_price))
                   if a is not None and a >= 0]
        if not amounts:
            continue  # a currency with no price says nothing (AllEvents tags priceless offers "USD")
        if o.currency and o.currency.strip().upper() not in ("INR", "RS", "₹"):
            return PriceResult(None, not_rupees=o.currency.strip().upper())
        values.extend(amounts)
    if not values:
        return None
    positive = sorted({v for v in values if v > 0})
    if not positive:
        return PriceResult(None, free=True)
    low = positive[0]
    amount = int(low.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    several = (amount, int(positive[-1].quantize(Decimal(1), rounding=ROUND_HALF_UP))) \
        if len(positive) > 1 else None
    return PriceResult(amount, several=several, rounded=low != low.to_integral_value())


def venue_line(name: str | None, street: str | None, locality: str | None) -> str | None:
    """A line someone can find on a map: 'Nexus Hyderabad Mall, Hyderabad'.

    Event sites stuff the whole postal address into streetAddress, which is noise next to a place
    name, so the street is used only when there's no name. Repeated pieces are dropped."""
    chunks = [name, locality or street] if name else [street, locality]
    segments: list[str] = []
    for chunk in chunks:
        for seg in (s.strip(" ,:") for s in (chunk or "").split(",")):
            if seg and not any(seg.lower() in have.lower() for have in segments):
                segments.append(seg)
    line = ""
    for seg in segments:
        candidate = f"{line}, {seg}" if line else seg
        if len(candidate) > VENUE_MAX:
            break
        line = candidate
    return line or None


def clean_text(raw: str | None, limit: int) -> str | None:
    """Strip any HTML, collapse whitespace, cut at a word boundary."""
    if not raw:
        return None
    text = BeautifulSoup(raw, "lxml").get_text(" ") if "<" in raw else raw
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text or None
    cut = text[: limit - 1].rsplit(" ", 1)[0]
    return cut + "…"


def clean_title(title: str | None, site_name: str | None) -> str | None:
    """'Diwali Night · Luma' -> 'Diwali Night' when the suffix is the site's own name."""
    if not title:
        return None
    t = re.sub(r"\s+", " ", title).strip()
    if site_name:
        t = re.sub(rf"\s*[|·\-–—:]\s*{re.escape(site_name)}\s*$", "", t, flags=re.I).strip() or t
    return t[:120] or None
