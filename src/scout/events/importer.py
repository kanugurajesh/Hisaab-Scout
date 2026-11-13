"""Import an event from a link: fetch -> structured data -> link-preview tags -> AI fallback -> checks."""

import asyncio
import datetime as dt
from collections.abc import Awaitable, Callable
from urllib.parse import urljoin, urlsplit

from cachetools import TTLCache

from ..config import Settings
from ..fetch import FetchedPage, fetch_page, normalize_url
from ..llm import LlmError, StructuredLlm
from .llm_extract import INSTRUCTIONS_FOR_AI, extract_with_llm
from .models import Extracted, ImportedEvent, ImportResponse, ImportWarning
from .normalize import IST, NOTES_MAX, choose_price, clean_text, clean_title, parse_start, venue_line
from .structured import RawEvent, parse

Fetcher = Callable[[str, Settings], Awaitable[FetchedPage]]

FORM_FIELDS = ("name", "date", "start_time", "venue", "per_head_amount", "notes")
CORE_FIELDS = ("name", "date", "venue", "per_head_amount")
LOGIN_WALLED = ("instagram.com", "facebook.com", "fb.me", "x.com", "twitter.com", "linkedin.com")
FAR_FUTURE_DAYS = 400


def _hi[T](value: T, source: str) -> Extracted[T]:
    return Extracted(value=value, source=source, confidence="high")  # type: ignore[arg-type]


def _med[T](value: T, source: str, evidence: str | None = None) -> Extracted[T]:
    return Extracted(value=value, source=source, confidence="medium", evidence=evidence)  # type: ignore[arg-type]


def _from_raw(r: RawEvent, base_url: str, warnings: list[ImportWarning] | None) -> ImportedEvent:
    def warn(code: str, message: str) -> None:
        if warnings is not None:
            warnings.append(ImportWarning(code=code, message=message))  # type: ignore[arg-type]

    ev = ImportedEvent()
    src = r.source
    if name := clean_title(r.name, None):
        ev.name = _hi(name, src)
    if start := parse_start(r.start):
        ev.date = _hi(start.date, src)
        if start.time:
            ev.start_time = (_med if start.tz_assumed else _hi)(start.time, src)
            if start.tz_assumed:
                warn("timezone_assumed", "The page gives a time without a timezone, so it's taken as IST.")
    if r.online and not r.location_name:
        warn("online_event", "This is an online event, so there's no venue.")
    elif venue := venue_line(r.location_name, r.street, r.locality):
        ev.venue = _hi(venue, src)
    if price := choose_price(r.offers):
        if price.not_rupees:
            warn("not_rupees", f"The price is in {price.not_rupees}, not rupees. Enter the amount by hand.")
        elif price.free:
            warn("free_event", "The page lists this event as free. Set the per-head amount yourself.")
        elif price.amount is not None:
            ev.per_head_amount = _hi(price.amount, src)
            if price.several:
                lo, hi = price.several
                warn("several_prices", f"The page lists prices from ₹{lo:,} to ₹{hi:,}. Using ₹{lo:,}.")
            if price.rounded:
                warn("rounded_amount", "The price had paise, so it was rounded to whole rupees.")
    if notes := clean_text(r.description, NOTES_MAX):
        ev.notes = _hi(notes, src)
    if r.image:
        ev.image_url = _hi(urljoin(base_url, r.image), src)
    if r.organizer:
        ev.organizer = _hi(r.organizer[:120], src)
    status = (r.status or "").lower()
    if "cancel" in status:
        warn("event_cancelled", "The page marks this event as cancelled.")
    elif "postpone" in status or "reschedul" in status:
        warn("event_postponed", "The page marks this event as postponed. Check the date.")
    return ev


def _order(events: list[RawEvent], today: dt.date) -> list[RawEvent]:
    """Next upcoming event first, then past ones from most recent. Undated ones last."""
    def key(r: RawEvent) -> tuple[int, int]:
        s = parse_start(r.start)
        if s is None:
            return (2, 0)
        days = (s.date - today).days
        return (0, days) if days >= 0 else (1, -days)

    return sorted(events, key=key)


class EventImporter:
    def __init__(self, settings: Settings, llm: StructuredLlm | None, *,
                 fetcher: Fetcher | None = None, clock: Callable[[], dt.datetime] | None = None):
        self.settings = settings
        self.llm = llm
        self.fetcher = fetcher or (lambda url, s: fetch_page(url, s))
        self.clock = clock or (lambda: dt.datetime.now(IST))
        self.cache: TTLCache[str, ImportResponse] = TTLCache(maxsize=512, ttl=settings.cache_ttl_seconds)

    async def import_url(self, raw_url: str) -> ImportResponse:
        url = normalize_url(raw_url)
        if (hit := self.cache.get(url)) is not None:
            return hit.model_copy(update={"cached": True})
        page = await self.fetcher(url, self.settings)
        result = await self._build(url, page)
        self.cache[url] = result
        return result

    async def _build(self, url: str, page: FetchedPage) -> ImportResponse:
        now = self.clock()
        today = now.astimezone(IST).date()
        soup, raw_events, meta = parse(page.html)
        warnings: list[ImportWarning] = []
        if INSTRUCTIONS_FOR_AI.search(soup.get_text(" ")):
            warnings.append(ImportWarning(
                code="instructions_for_ai",
                message="This page has text written to steer AI readers. Check every field against the page."))

        ordered = _order(raw_events, today)
        event = _from_raw(ordered[0], page.final_url, warnings) if ordered else ImportedEvent()
        alternatives = [_from_raw(r, page.final_url, None) for r in ordered[1:10]]
        if len(ordered) > 1:
            warnings.append(ImportWarning(
                code="several_events",
                message=f"This page lists {len(ordered)} events. Check this is the right one."))

        # Link-preview tags: what WhatsApp shows when the link is shared.
        if event.name is None and (t := clean_title(meta.og_title or meta.title, meta.og_site_name)):
            event.name = _med(t, "opengraph" if meta.og_title else "meta")
        if event.notes is None and (d := clean_text(meta.og_description or meta.meta_description, NOTES_MAX)):
            event.notes = _med(d, "opengraph" if meta.og_description else "meta")
        if event.image_url is None and meta.og_image:
            event.image_url = _hi(urljoin(page.final_url, meta.og_image), "opengraph")

        codes = {w.code for w in warnings}
        expected_gaps = {"venue"} if "online_event" in codes else set()
        if codes & {"free_event", "not_rupees"}:
            expected_gaps.add("per_head_amount")
        gaps = [f for f in CORE_FIELDS if getattr(event, f) is None and f not in expected_gaps]
        # A bare <title> is often the site's boilerplate ("Notice Board"); a quoted name beats it.
        weak_name = event.name is not None and event.name.source == "meta"

        used_ai = False
        if gaps:
            if self.llm is None:
                warnings.append(ImportWarning(
                    code="ai_unavailable", message="Some details couldn't be read. Fill them in by hand."))
            else:
                try:
                    g = await asyncio.to_thread(extract_with_llm, self.llm, page.html, now)
                    used_ai = True
                except LlmError:
                    g = None
                    warnings.append(ImportWarning(
                        code="ai_unavailable",
                        message="The AI reader is busy, so some details couldn't be read. Fill them in by hand."))
                # Not an event page (a recipe, a news story): its numbers aren't an event's details.
                if g is not None and (g.is_event_page or raw_events):
                    if (event.name is None or weak_name) and g.name:
                        event.name = _med(g.name[0], "llm", g.name[1])
                    if event.date is None and g.date:
                        event.date = _med(g.date[0], "llm", g.date[1])
                    # A time only counts when it belongs to the same date (listing pages hold several).
                    if event.start_time is None and g.start_time and g.date and event.date \
                            and event.date.value == g.date[0]:
                        event.start_time = _med(g.start_time[0], "llm", g.start_time[1])
                    if event.venue is None and g.venue and "venue" not in expected_gaps:
                        event.venue = _med(g.venue[0], "llm", g.venue[1])
                    if event.per_head_amount is None and g.price_inr and "per_head_amount" not in expected_gaps:
                        event.per_head_amount = _med(g.price_inr[0], "llm", g.price_inr[1])

        if event.date is not None:
            days = (event.date.value - today).days
            if days < 0:
                warnings.append(ImportWarning(code="event_in_past", message="This event's date has passed."))
            elif days > FAR_FUTURE_DAYS:
                warnings.append(ImportWarning(
                    code="event_far_future", message="This date is over a year away. Check the year."))

        host = (urlsplit(page.final_url).hostname or "").removeprefix("www.")
        if not raw_events and any(host == d or host.endswith("." + d) for d in LOGIN_WALLED):
            warnings.append(ImportWarning(
                code="login_wall",
                message="This site hides most details behind a login. Only the link preview could be read."))

        needs = [f for f in FORM_FIELDS if (x := getattr(event, f)) is not None and x.confidence != "high"]
        if "several_prices" in {w.code for w in warnings} and "per_head_amount" not in needs:
            needs.append("per_head_amount")

        found = event.name is not None and any(
            getattr(event, f) is not None for f in ("date", "venue", "per_head_amount"))
        return ImportResponse(found=found, event=event, alternatives=alternatives, needs_confirmation=needs,
                              warnings=warnings, source_url=url, final_url=page.final_url, used_ai=used_ai)
