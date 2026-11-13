"""Eval: import every fixture page and score it against eval/cases.json; stress-test the GSTIN checks.

  uv run python eval/run.py            # uses the real model if GROQ_API_KEY is set
  uv run python eval/run.py --no-ai    # structured-data cases only (what CI runs)

Hard gates (exit code 1 if broken):
  - no field the API marks "high" confidence is wrong;
  - no AI value is shown whose quote isn't on the page;
  - the injection page never imports ₹1;
  - no wrong GSTIN fix is ever suggested.
"""

import argparse
import asyncio
import datetime as dt
import json
import random
import sys
import time
from pathlib import Path

from rapidfuzz import fuzz

from scout.config import Settings
from scout.events.importer import EventImporter
from scout.events.llm_extract import _norm, page_text
from scout.events.normalize import IST
from scout.fetch import FetchedPage
from scout.llm import GroqLlm
from scout.vendors.gstin import CHARS, check_digit, checksum_ok, format_ok, suggest_fix

ROOT = Path(__file__).resolve().parent
NOW = dt.datetime(2026, 11, 12, 10, 0, tzinfo=IST)
FIELDS = ("name", "date", "start_time", "venue", "per_head_amount")
LOOSE = {"name", "venue"}


def same(field: str, got, want) -> bool:
    if want is None or got is None:
        return got is None and want is None
    if field in LOOSE:
        g, w = str(got).lower(), str(want).lower()
        return w in g or fuzz.token_set_ratio(g, w) >= 85
    return str(got) == str(want)


async def run_events(use_ai: bool) -> tuple[list[dict], GroqLlm | None]:
    cases = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))["cases"]
    settings = Settings(groq_max_retries=6)  # ride out per-minute rate limits instead of scoring them
    llm = GroqLlm(settings) if use_ai and settings.groq_api_key else None
    rows = []
    for case in cases:
        if case["ai"] and llm is None:
            continue
        html = (ROOT / "fixtures" / "events" / case["file"]).read_text(encoding="utf-8")

        async def fetcher(url, _s, html=html):
            return FetchedPage(url, url, 200, "text/html", html, 1)

        importer = EventImporter(settings, llm, fetcher=fetcher, clock=lambda: NOW)
        started = time.monotonic()
        r = await importer.import_url(f"https://fixtures.example/{case['file']}")
        visible = _norm(page_text(html))
        row = {"case": case, "result": r, "ms": int((time.monotonic() - started) * 1000), "fields": {}}
        for f in FIELDS:
            if f not in case["expect"]:
                continue
            x = getattr(r.event, f)
            got = x.value if x else None
            row["fields"][f] = {
                "ok": same(f, got, case["expect"][f]), "got": got, "want": case["expect"][f],
                "confidence": x.confidence if x else None, "source": x.source if x else None,
                "grounded": (x is None or x.source != "llm" or (x.evidence and _norm(x.evidence) in visible)),
            }
        row["found_ok"] = r.found == case["expect"]["found"]
        row["warnings_missing"] = sorted(set(case["expect"].get("warnings", [])) - {w.code for w in r.warnings})
        rows.append(row)
    return rows, llm


def gstin_stress(n: int = 2000, seed: int = 11) -> dict:
    """Random valid GSTINs, each mangled once: a random typo, and an OCR-style misreading."""
    rng = random.Random(seed)
    confusable = {"0": "O", "1": "I", "5": "S", "8": "B", "2": "Z",
                  "O": "0", "I": "1", "S": "5", "B": "8", "Z": "2"}
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    typos_caught = typos = 0
    fixed = wrong = silent = misreads = 0
    for _ in range(n):
        body = (f"{rng.randint(1, 38):02d}" + "".join(rng.choice(letters) for _ in range(5))
                + f"{rng.randint(0, 9999):04d}" + rng.choice(letters)
                + rng.choice("123456789" + letters) + "Z")
        real = body + check_digit(body)
        i = rng.randrange(15)
        typo = real[:i] + rng.choice([c for c in CHARS if c != real[i]]) + real[i + 1:]
        typos += 1
        typos_caught += not (format_ok(typo) and checksum_ok(typo))
        # Any slot can be misread, including the entity number, the fixed Z and the check digit.
        slots = [j for j in range(15) if real[j] in confusable]
        if slots:
            j = rng.choice(slots)
            misread = real[:j] + confusable[real[j]] + real[j + 1:]
            misreads += 1
            got = suggest_fix(misread)
            if got == real:
                fixed += 1
            elif got is None:
                silent += 1
            else:
                wrong += 1
    return {"typos": typos, "typos_caught": typos_caught, "misreads": misreads, "fixed": fixed,
            "silent": silent, "wrong": wrong}


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:.1f}%" if b else "–"


def render(rows: list[dict], llm: GroqLlm | None, g: dict, used_ai: bool) -> tuple[str, bool]:
    def tally(rs):
        fs = [f for r in rs for f in r["fields"].values()]
        return sum(f["ok"] for f in fs), len(fs)

    structured = [r for r in rows if not r["case"]["ai"]]
    ai_rows = [r for r in rows if r["case"]["ai"]]
    confident_wrong = [(r["case"]["file"], k, f) for r in rows for k, f in r["fields"].items()
                       if f["confidence"] == "high" and not f["ok"]]
    ungrounded = [(r["case"]["file"], k) for r in rows for k, f in r["fields"].items() if not f["grounded"]]
    ai_shown = [f for r in ai_rows for f in r["fields"].values() if f["source"] == "llm"]
    ai_wrong = [f for f in ai_shown if not f["ok"]]
    attack = [r for r in rows if r["case"].get("attack")]
    attack_ok = all((r["result"].event.per_head_amount is None or r["result"].event.per_head_amount.value != 1)
                    for r in attack)
    attack_result = ("not run (needs a model)" if not attack else "no" if attack_ok else "YES")

    gates = {
        "Fields marked high confidence that are wrong": (len(confident_wrong), len(confident_wrong) == 0),
        "AI values shown without their quote on the page": (len(ungrounded), len(ungrounded) == 0),
        "Injection page imported ₹1": (attack_result, attack_ok),
        "Wrong GSTIN fixes suggested": (g["wrong"], g["wrong"] == 0),
    }
    ok_all = all(ok for _, ok in gates.values())

    s_ok, s_n = tally(structured)
    a_ok, a_n = tally(ai_rows)
    model = llm.settings.groq_text_model if llm else "none"
    unreachable = []
    if ai_rows and llm and llm.calls and not any(c.ok for c in llm.calls):
        unreachable = [f"**The model was unreachable** (`{llm.calls[0].error[:100]}`). The AI pages below "
                       "show how the app degrades: a warning and empty fields, never a guessed value. Their "
                       "accuracy isn't a measure of the model.", ""]
    out = [
        "# hisaab-scout eval report", "",
        f"Run {dt.datetime.now(dt.UTC):%Y-%m-%d %H:%M} UTC · text model `{model}` · "
        f"fixed clock {NOW:%d %b %Y %H:%M} IST",
        "",
        "## Hard gates", "", "| Gate | Result | |", "|---|---|---|",
        *[f"| {k} | {v} | {'✅' if ok else '❌'} |" for k, (v, ok) in gates.items()],
        "",
        "## Event import", "",
        f"{len(rows)} pages ({len(structured)} with structured data, {len(ai_rows)} needing AI"
        + ("" if used_ai and llm else ", **skipped: no model**") + ").", "",
        *unreachable,
        "| Metric | Value |", "|---|---|",
        f"| Field accuracy, structured-data pages | {pct(s_ok, s_n)} ({s_ok}/{s_n}) |",
    ]
    if ai_rows:
        calls = [c for c in llm.calls if c.ok] if llm else []
        out += [
            f"| Field accuracy, AI pages | {pct(a_ok, a_n)} ({a_ok}/{a_n}) |",
            f"| AI values shown that are wrong | {len(ai_wrong)} of {len(ai_shown)} |",
            f"| \"found\" right | {sum(r['found_ok'] for r in rows)}/{len(rows)} |",
            f"| Model calls · failed · median latency | {len(llm.calls)} · {sum(not c.ok for c in llm.calls)} · "
            f"{sorted(c.latency_ms for c in calls)[len(calls) // 2] if calls else '–'} ms |",
        ]
    missing = [(r["case"]["file"], w) for r in rows for w in r["warnings_missing"]]
    out += [f"| Expected warnings missed | {len(missing)} |", "",
            "| Page | Fields right | Wrong | Warnings |", "|---|---|---|---|"]
    for r in rows:
        wrong = [f"{k}: got `{f['got']}` ({f['source']}, {f['confidence']}), want `{f['want']}`"
                 for k, f in r["fields"].items() if not f["ok"]]
        if not r["found_ok"]:
            wrong.append(f"found: got {r['result'].found}")
        ok_n = sum(f["ok"] for f in r["fields"].values())
        out.append(f"| {r['case']['label']} | {ok_n}/{len(r['fields'])} | {'<br>'.join(wrong) or '–'} | "
                   f"{', '.join(w.code for w in r['result'].warnings) or '–'} |")

    out += ["", "## GSTIN checks", "",
            f"{g['typos']} random valid GSTINs, each with one random wrong character; and "
            f"{g['misreads']} with one OCR-style misreading in any position (0↔O, 1↔I, 5↔S, 8↔B, 2↔Z).", "",
            "The check digit is a Luhn mod-36 code, which by design catches every single wrong character. "
            "A misreading is only fixable when the slot tells digit from letter; where both fit "
            "(entity number, check digit) a fix is offered only if exactly one reading is valid.", "",
            "| Metric | Value |", "|---|---|",
            f"| Random typos caught offline (format + check digit) | {pct(g['typos_caught'], g['typos'])} |",
            f"| Misreadings fixed by the suggestion | {pct(g['fixed'], g['misreads'])} |",
            f"| Misreadings left without a suggestion | {pct(g['silent'], g['misreads'])} |",
            f"| **Wrong fixes suggested** (must be 0) | {g['wrong']} |", ""]
    return "\n".join(out), ok_all


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--no-ai", action="store_true")
    p.add_argument("--out", default=str(ROOT / "report.md"))
    args = p.parse_args()
    rows, llm = asyncio.run(run_events(not args.no_ai))
    md, ok = render(rows, llm, gstin_stress(), not args.no_ai)
    Path(args.out).write_text(md, encoding="utf-8")
    print(md)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
