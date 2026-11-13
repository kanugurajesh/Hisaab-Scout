# hisaab-scout eval report

Run 2026-11-12 10:43 UTC · text model `none` · fixed clock 12 Nov 2026 10:00 IST

## Hard gates

| Gate | Result | |
|---|---|---|
| Fields marked high confidence that are wrong | 0 | ✅ |
| AI values shown without their quote on the page | 0 | ✅ |
| Injection page imported ₹1 | not run (needs a model) | ✅ |
| Wrong GSTIN fixes suggested | 0 | ✅ |

## Event import

11 pages (11 with structured data, 0 needing AI, **skipped: no model**).

| Metric | Value |
|---|---|
| Field accuracy, structured-data pages | 100.0% (43/43) |
| Expected warnings missed | 0 |

| Page | Fields right | Wrong | Warnings |
|---|---|---|---|
| Luma-style page, full schema.org Event | 5/5 | – | – |
| @graph, UTC start time | 5/5 | – | – |
| ticket tiers ₹799–₹2,499 | 5/5 | – | several_prices |
| free online event | 4/4 | – | online_event, free_event |
| listing of 3 events, one past | 5/5 | – | several_events |
| cancelled event | 3/3 | – | event_cancelled |
| broken JSON-LD (comments, trailing commas) | 5/5 | – | – |
| microdata instead of JSON-LD | 5/5 | – | – |
| event already over | 1/1 | – | event_in_past |
| time without timezone, price with paise | 3/3 | – | timezone_assumed, rounded_amount |
| price in dollars | 2/2 | – | not_rupees |

## GSTIN checks

2000 random valid GSTINs, each with one random wrong character; and 2000 with one OCR-style misreading in any position (0↔O, 1↔I, 5↔S, 8↔B, 2↔Z).

The check digit is a Luhn mod-36 code, which by design catches every single wrong character. A misreading is only fixable when the slot tells digit from letter; where both fit (entity number, check digit) a fix is offered only if exactly one reading is valid.

| Metric | Value |
|---|---|
| Random typos caught offline (format + check digit) | 100.0% |
| Misreadings fixed by the suggestion | 99.7% |
| Misreadings left without a suggestion | 0.3% |
| **Wrong fixes suggested** (must be 0) | 0 |
