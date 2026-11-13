"""Read what a page says about itself in machine-readable form.

Event platforms (Luma, Townscript, Meetup, Eventbrite, AllEvents, most WordPress event plugins) embed
schema.org Event data so search engines can show rich results. When it's there it's the most reliable
source, so it's read first and trusted most. Open Graph tags (the WhatsApp link preview) come next.
"""

import html
import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from bs4 import BeautifulSoup, Tag

EVENT_TYPES = {"event", "festival", "hackathon"}


@dataclass
class RawOffer:
    price: Any = None
    low_price: Any = None
    high_price: Any = None
    currency: str | None = None


@dataclass
class RawEvent:
    source: Literal["jsonld", "microdata"]
    name: str | None = None
    start: str | None = None
    end: str | None = None
    location_name: str | None = None
    street: str | None = None
    locality: str | None = None
    online: bool = False
    offers: list[RawOffer] = field(default_factory=list)
    description: str | None = None
    image: str | None = None
    organizer: str | None = None
    status: str | None = None
    url: str | None = None


@dataclass
class PageMeta:
    title: str | None = None
    og_title: str | None = None
    og_description: str | None = None
    og_image: str | None = None
    og_site_name: str | None = None
    meta_description: str | None = None
    canonical: str | None = None


def _text(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, list):
        return next((t for t in (_text(x) for x in v) if t), None)
    if isinstance(v, dict):
        return _text(v.get("name") or v.get("url") or v.get("@value"))
    s = html.unescape(str(v)).strip()
    return s or None


def _image(v: Any) -> str | None:
    if isinstance(v, list):
        return next((u for u in (_image(x) for x in v) if u), None)
    if isinstance(v, dict):
        return _text(v.get("url") or v.get("contentUrl"))
    return _text(v)


def _is_event_type(t: Any) -> bool:
    types = t if isinstance(t, list) else [t]
    for x in types:
        name = str(x).rsplit("/", 1)[-1].lower()
        if name in EVENT_TYPES or name.endswith("event"):
            return True
    return False


# ---------------------------------------------------------------- JSON-LD

def _load_jsonld(raw: str) -> Any:
    raw = raw.strip()
    raw = re.sub(r"^\s*(<!--|//\s*<!\[CDATA\[)|(-->|//\s*\]\]>)\s*$", "", raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Common hand-written mistakes: trailing commas, raw newlines inside strings.
        fixed = re.sub(r",\s*([}\]])", r"\1", raw).replace("\n", " ")
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            return None


def _walk(node: Any, out: list[dict]) -> None:
    if isinstance(node, list):
        for x in node:
            _walk(x, out)
    elif isinstance(node, dict):
        if _is_event_type(node.get("@type")):
            out.append(node)
        for k, v in node.items():
            if k != "@type" and isinstance(v, (dict, list)):
                _walk(v, out)


def _location(ev: RawEvent, loc: Any) -> None:
    for item in loc if isinstance(loc, list) else [loc]:
        if isinstance(item, str):
            ev.location_name = ev.location_name or _text(item)
        elif isinstance(item, dict):
            t = str(item.get("@type", "")).lower()
            if "virtual" in t:
                ev.online = True
                continue
            ev.location_name = ev.location_name or _text(item.get("name"))
            addr = item.get("address")
            if isinstance(addr, dict):
                ev.street = _text(addr.get("streetAddress"))
                ev.locality = _text(addr.get("addressLocality"))
            elif addr:
                ev.street = _text(addr)


def _offers(node: Any) -> list[RawOffer]:
    out: list[RawOffer] = []
    for o in node if isinstance(node, list) else [node]:
        if isinstance(o, dict):
            out.append(RawOffer(price=o.get("price"), low_price=o.get("lowPrice"),
                                high_price=o.get("highPrice"), currency=_text(o.get("priceCurrency"))))
            if isinstance(o.get("offers"), (list, dict)):  # AggregateOffer wrapping offers
                out.extend(_offers(o["offers"]))
    return out


def jsonld_events(soup: BeautifulSoup) -> list[RawEvent]:
    nodes: list[dict] = []
    for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        data = _load_jsonld(script.string or script.get_text() or "")
        if data is not None:
            _walk(data, nodes)
    events = []
    for n in nodes:
        ev = RawEvent(source="jsonld", name=_text(n.get("name")), start=_text(n.get("startDate")),
                      end=_text(n.get("endDate")), description=_text(n.get("description")),
                      image=_image(n.get("image")), organizer=_text(n.get("organizer")),
                      status=_text(n.get("eventStatus")), url=_text(n.get("url")))
        _location(ev, n.get("location"))
        mode = str(n.get("eventAttendanceMode", "")).lower()
        if "online" in mode and "mixed" not in mode:
            ev.online = True
        ev.offers = _offers(n.get("offers"))
        events.append(ev)
    return events


# ---------------------------------------------------------------- microdata

def _prop_value(el: Tag) -> str | None:
    for attr in ("content", "datetime", "href", "src"):
        if el.get(attr):
            return str(el.get(attr)).strip()
    return el.get_text(" ", strip=True) or None


def _props(scope: Tag) -> dict[str, list[Tag]]:
    """itemprops that belong to this itemscope, not to a nested one."""
    out: dict[str, list[Tag]] = {}
    for el in scope.find_all(attrs={"itemprop": True}):
        owner = el.find_parent(attrs={"itemscope": True})
        if owner is scope:
            for name in str(el["itemprop"]).split():
                out.setdefault(name, []).append(el)
    return out


def _first(props: dict[str, list[Tag]], name: str) -> str | None:
    return _prop_value(props[name][0]) if props.get(name) else None


def microdata_events(soup: BeautifulSoup) -> list[RawEvent]:
    events = []
    for scope in soup.find_all(attrs={"itemscope": True, "itemtype": True}):
        if not _is_event_type(str(scope["itemtype"]).split()[0]):
            continue
        p = _props(scope)
        ev = RawEvent(source="microdata", name=_first(p, "name"), start=_first(p, "startDate"),
                      end=_first(p, "endDate"), description=_first(p, "description"),
                      image=_first(p, "image"), url=_first(p, "url"))
        for loc in p.get("location", []):
            if loc.has_attr("itemscope"):
                lp = _props(loc)
                ev.location_name = _first(lp, "name")
                for addr in lp.get("address", []):
                    if addr.has_attr("itemscope"):
                        ap = _props(addr)
                        ev.street = _first(ap, "streetAddress")
                        ev.locality = _first(ap, "addressLocality")
                    else:
                        ev.street = _prop_value(addr)
            else:
                ev.location_name = _prop_value(loc)
        for off in p.get("offers", []):
            op = _props(off) if off.has_attr("itemscope") else {"price": [off]}
            ev.offers.append(RawOffer(price=_first(op, "price"), low_price=_first(op, "lowPrice"),
                                      currency=_first(op, "priceCurrency")))
        events.append(ev)
    return events


# ---------------------------------------------------------------- meta tags

def page_meta(soup: BeautifulSoup) -> PageMeta:
    def meta(*keys: str) -> str | None:
        for k in keys:
            el = soup.find("meta", attrs={"property": k}) or soup.find("meta", attrs={"name": k})
            if el and el.get("content"):
                return html.unescape(str(el["content"])).strip() or None
        return None

    canonical = soup.find("link", attrs={"rel": "canonical"})
    return PageMeta(
        title=soup.title.get_text(strip=True) if soup.title else None,
        og_title=meta("og:title", "twitter:title"),
        og_description=meta("og:description", "twitter:description"),
        og_image=meta("og:image", "og:image:url", "twitter:image"),
        og_site_name=meta("og:site_name"),
        meta_description=meta("description"),
        canonical=str(canonical["href"]) if canonical and canonical.get("href") else None,
    )


def parse(html_text: str) -> tuple[BeautifulSoup, list[RawEvent], PageMeta]:
    soup = BeautifulSoup(html_text, "lxml")
    events = jsonld_events(soup) or microdata_events(soup)
    return soup, events, page_meta(soup)
