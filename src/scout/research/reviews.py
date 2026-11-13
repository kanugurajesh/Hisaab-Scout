"""Where reviews come from. Only the text, rating, date and thumbs-up count are kept: reviewer names
and avatars are dropped as soon as they're read, because the report is about problems, not people."""

import csv
import datetime as dt
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Review:
    id: str
    source: str  # app id, or the CSV's "source" column
    text: str
    score: int | None
    thumbs_up: int
    at: dt.date | None


def from_play_store(app_id: str, count: int, *, country: str = "in", lang: str = "en") -> list[Review]:
    """Newest reviews first. Needs the optional extra: `uv sync --extra research`."""
    try:
        from google_play_scraper import Sort, reviews
    except ImportError as err:
        raise SystemExit("Install the research extra first: uv sync --extra research") from err

    out: list[Review] = []
    token = None
    while len(out) < count:
        batch, token = reviews(app_id, lang=lang, country=country, sort=Sort.NEWEST,
                               count=min(200, count - len(out)), continuation_token=token)
        if not batch:
            break
        for r in batch:
            text = (r.get("content") or "").strip()
            if text:
                at = r.get("at")
                out.append(Review(id=f"{app_id}:{r['reviewId']}", source=app_id, text=text,
                                  score=r.get("score"), thumbs_up=r.get("thumbsUpCount") or 0,
                                  at=at.date() if at else None))
        if token is None:
            break
    return out[:count]


def from_csv(path: str | Path) -> list[Review]:
    """Columns: text (required), and optionally score, source, thumbs_up, date (YYYY-MM-DD).
    For posts copied from Reddit, forums or interview notes."""
    out = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for i, row in enumerate(csv.DictReader(f)):
            text = (row.get("text") or "").strip()
            if not text:
                continue
            score = row.get("score")
            date = row.get("date")
            out.append(Review(
                id=f"csv:{i}", source=(row.get("source") or Path(path).stem).strip(), text=text,
                score=int(score) if score and score.strip().isdigit() else None,
                thumbs_up=int(row["thumbs_up"]) if (row.get("thumbs_up") or "").strip().isdigit() else 0,
                at=dt.date.fromisoformat(date.strip()) if date and date.strip() else None))
    return out
