"""scout-research: turn app reviews into a theme report for PRDs.

  uv sync --extra research
  uv run scout-research playstore --app com.Splitwise.SplitwiseMobile --count 300 --out reports/splitwise.md
  uv run scout-research csv --file notes/reddit-posts.csv --out reports/reddit.md

This is a research tool you run by hand, not an API endpoint: it reads hundreds of reviews in one go,
and a public endpoint doing that on demand would be slow and easy to abuse.
"""

import argparse
import sys
from pathlib import Path

from ..config import Settings
from ..llm import make_llm
from .classify import tag_all
from .report import render
from .reviews import from_csv, from_play_store


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="scout-research", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    ps = sub.add_parser("playstore", help="Newest Google Play reviews of one or more apps")
    ps.add_argument("--app", action="append", required=True, help="Package id, e.g. com.Splitwise.SplitwiseMobile")
    ps.add_argument("--count", type=int, default=200, help="Reviews per app (default 200)")
    ps.add_argument("--country", default="in")
    cs = sub.add_parser("csv", help="Reviews or posts from a CSV with a 'text' column")
    cs.add_argument("--file", required=True)
    for sp in (ps, cs):
        sp.add_argument("--out", required=True, help="Markdown report to write")
        sp.add_argument("--title", default="What users complain about")
        sp.add_argument("--no-ai", action="store_true", help="Keyword tagging only")
    args = p.parse_args(argv)

    if args.cmd == "playstore":
        reviews = []
        for app in args.app:
            got = from_play_store(app, args.count, country=args.country)
            print(f"{app}: {len(got)} reviews", file=sys.stderr)
            reviews += got
    else:
        reviews = from_csv(args.file)
        print(f"{args.file}: {len(reviews)} rows", file=sys.stderr)
    if not reviews:
        print("No reviews found.", file=sys.stderr)
        return 1

    llm = None if args.no_ai else make_llm(Settings())
    tagged, method = tag_all(reviews, llm)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(tagged, method, args.title), encoding="utf-8")
    print(f"Wrote {out} ({method})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
