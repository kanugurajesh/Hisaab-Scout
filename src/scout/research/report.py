"""Count the tags and write a Markdown report a PRD can quote."""

import datetime as dt
from collections import Counter, defaultdict

from .classify import THEMES, Tagged, sentence_for


def _pct(n: int, d: int) -> str:
    return f"{(100 * n / d):.0f}%" if d else "–"


def render(tagged: list[Tagged], method: str, title: str, now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now(dt.UTC)
    complaints = [t for t in tagged if t.complaint]
    sources = Counter(t.review.source for t in tagged)
    dates = [t.review.at for t in tagged if t.review.at]

    lines = [f"# {title}", "",
             f"Generated {now:%Y-%m-%d %H:%M} UTC · {len(tagged)} reviews · "
             f"{len(complaints)} describe a problem · tagged by **{method}**", ""]
    if dates:
        lines += [f"Reviews dated {min(dates)} to {max(dates)}.", ""]

    lines += ["## Sources", "", "| Source | Reviews | Avg rating | 1–2★ |", "|---|---|---|---|"]
    for src, n in sources.most_common():
        scores = [t.review.score for t in tagged if t.review.source == src and t.review.score]
        avg = f"{sum(scores) / len(scores):.1f}" if scores else "–"
        low = _pct(sum(1 for s in scores if s <= 2), len(scores)) if scores else "–"
        lines.append(f"| `{src}` | {n} | {avg} | {low} |")

    theme_counts = Counter(th for t in complaints for th in t.themes)
    by_theme: dict[str, list[Tagged]] = defaultdict(list)
    for t in complaints:
        for th in t.themes:
            by_theme[th].append(t)

    lines += ["", "## What people complain about", "",
              "Share of reviews that describe a problem. A review can count under more than one theme.", "",
              "| Theme | Reviews | Share |", "|---|---|---|"]
    for th, n in theme_counts.most_common():
        lines.append(f"| {THEMES[th]} | {n} | {_pct(n, len(complaints))} |")
    untagged = sum(1 for t in complaints if not t.themes)
    if untagged:
        lines.append(f"| (no listed theme) | {untagged} | {_pct(untagged, len(complaints))} |")

    lines += ["", "## In their words", "",
              "Quotes are copied from the reviews exactly. Most-liked first. Reviewer names are never stored.", ""]
    for th, _n in theme_counts.most_common():
        # Prefer the sentence that's about this theme; fall back to the review's tagged quote.
        quotes = [(t, q) for t in by_theme[th] if (q := sentence_for(th, t.review.text) or t.quote)]
        quotes = sorted(quotes, key=lambda tq: -tq[0].review.thumbs_up)[:3]
        if not quotes:
            continue
        lines.append(f"### {THEMES[th]}")
        for t, q in quotes:
            stars = f"{t.review.score}★ · " if t.review.score else ""
            likes = f" · {t.review.thumbs_up} found this helpful" if t.review.thumbs_up else ""
            lines.append(f"- “{q.strip()}” ({stars}`{t.review.source}`{likes})")
        lines.append("")

    lines += ["## Caveats", "",
              "- App-store reviewers skew towards people who are upset; treat shares as a ranking of pains, "
              "not their size in the market.",
              "- Splitwise-style apps serve friends splitting bills, not one organizer collecting from 80 "
              "people. Themes overlap with Hisaab's problem; they don't prove it.",
              f"- Tagging method: {method}. Keyword tags are cruder than model tags; check quotes before "
              "citing a theme.", ""]
    return "\n".join(lines)
