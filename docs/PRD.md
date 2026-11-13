# PRD: hisaab-scout

**Status:** prototype built · **Date:** 12 Nov 2026 · Companion service to [Hisaab](https://github.com/kanugurajesh/Hisaab), the collection tracker built for Choruss

## Problem
Hisaab answers "who has paid?", "is this payment real?" and "where did the money go?". Three gaps remain, and each needs information that lives on some other web page.

1. **Starting a collection means retyping what's already written.** Most collections already have a page somewhere: a Luma, Townscript, Meetup or AllEvents listing, a Google Form, or a notice on the society website. The organizer types the name, date, venue and amount again. A mistyped date or amount then goes into every reminder Hisaab writes.
2. **A bill can add up and still be fake.** Hisaab checks a bill's arithmetic, its date and whether it was uploaded before. It doesn't check whether the shop exists. Most Indian shop bills print a GSTIN, and that number can be checked. Hisaab's own demo bill prints `36ABCDE1234F1Z5`, which fails the GSTIN check digit. No real business can have it.
3. **The product thinking rests on a handful of interviews.** One Ganesh-fund organizer is a strong signal, but it's still one person. Public app reviews are a cheap way to see which pains repeat at scale.

## Users
- **Organizer** (primary): sets up the collection from their phone, usually by pasting a link they've already shared on WhatsApp. Later, photographs bills.
- **Contributor**: never calls this service directly. They benefit when the details are right and the ledger's bills are real.
- **Product builder** (internal): runs the research tool before writing a PRD.

## Goals and metrics
| Goal | Metric | Target | Measured |
|---|---|---|---|
| Setup takes seconds | Time from pasting a link to a saved collection | < 30 s (typing takes ~3 min) | Pilot |
| Links work | Pasted links that return `found: true` | ≥ 70% overall, ≥ 95% on pages with structured data | Pilot logs |
| Accurate prefill | Field accuracy on the eval set | 100% for structured data, ≥ 90% with AI | 100% (43/43) structured; AI pending a working key |
| **Safety** | Fields marked high confidence that are wrong | **0** (hard gate) | 0 |
| **Safety** | AI values shown without their quote on the page | **0** (hard gate) | 0 |
| **Safety** | An injection page imports ₹1 | **Never** (hard gate) | Not yet run with a model |
| Vendor checks are trustworthy | Wrong GSTIN fixes suggested | **0** (hard gate) | 0 out of 2,000 |
| Vendor checks catch typos | Single-character errors caught offline | 100% (guaranteed by the check digit) | 100% |

Non-goals: finding events for people to attend, crawling sites, reading pages behind a login, and filing GST.

## Solution

### 1. Import an event from a link
`POST /v1/events/import {url}` returns the fields of Hisaab's create-collection form: name, date, start time, venue, per-head amount, notes, image and organizer.

The service tries sources in order of how much it can trust them:
1. **schema.org Event data** (JSON-LD or microdata). Event platforms embed it so search engines can show rich results. These fields are marked `high` confidence. Malformed JSON-LD is repaired where possible (trailing commas, HTML comments).
2. **Link-preview tags** (Open Graph): what WhatsApp shows when the link is shared. Marked `medium` confidence.
3. **AI**, only for fields still missing. For each value, the model must quote the exact words on the page it came from. Code then checks that the quote is on the page and that it supports the value: the right day and month for a date, the right hour and am/pm for a time, a money word next to the right number for a price. Values that fail are dropped, never shown.

Each field returns its `source`, its `confidence` and, for AI values, its `evidence`. `needs_confirmation` lists the fields the organizer should check before saving.

Warnings explain anything unusual:
- the event is past, cancelled or postponed;
- it's free, online, or priced in another currency;
- the page lists several ticket prices, or several events;
- the timezone was assumed to be IST;
- the site hides details behind a login;
- the AI reader was unavailable;
- the page has text written to steer AI readers.

### 2. Check the vendor on a bill
`POST /v1/vendors/check {gstin, vendor_name?, bill_date?}`

**Offline checks** need no network:
- the format (state code, PAN, entity number, the letter Z, check digit);
- the mod-36 check digit;
- the state code.

When a misread number is one OCR mistake away from a valid one (O for 0, I for 1 and so on), the service suggests the fix. It does so only when exactly one reading is valid, so the organizer compares it with the bill.

**Registry checks** run when a registry is connected:
- the GSTIN is registered;
- it was active on the bill date;
- the shop name on the bill matches the registered name (spelling variants and filler words like "M/s", "Pvt Ltd" and "Sri" are tolerated).

The verdict is one of:
- `verified`: the registry confirms everything;
- `format_ok`: the number is well-formed, but no registry was checked;
- `mismatch`: registered, but the name or dates don't fit this bill;
- `invalid`: the number can't be real, or isn't registered.

### 3. Turn reviews into research (`scout-research`)
A command-line tool, not an endpoint. It collects:
- Google Play reviews (newest first);
- or a CSV of posts and interview notes.

It tags each review with a fixed list of themes Hisaab cares about, and writes a Markdown report:
- the share of complaints per theme;
- the most-liked quotes under each theme, copied word for word.

Reviewer names are dropped as soon as reviews are read.

**First finding** ([reports/splitwise-playstore.md](../reports/splitwise-playstore.md)): 300 recent Splitwise reviews average 2.1★, and 70% are 1–2★. 68% of the complaints are about the paywall. Splitwise now limits free users to a few expenses a day, and users call it "a glorified calculator". For Hisaab this supports a clear rule: **contributors never need an account, an app or a plan.** Only the organizer's side could ever carry a price.

## Key decisions
- **A separate service in its own repo.** It's a different language (Python), deploys on its own, and isn't specific to Hisaab. The contract is frozen in `openapi.json`, and CI fails if the code drifts from it. Hisaab generates its TypeScript types from that file.
- **A link preview, not a crawler.** One fetch per request a person makes, of a URL that person pasted. No following links, no listing pages crawled, no logins and no stored pages; results are cached in memory for 15 minutes. That's the same footprint as WhatsApp building a preview of the link. It also means robots.txt (which governs crawlers) isn't consulted. The User-Agent says what the fetch is, and it can be configured.
- **Trust is earned by the source, not by the model's opinion of itself.** Structured data is `high` and everything else is `medium`. The model never sets confidence.
- **The model reads; code decides.** This is the same contract as Hisaab's payment and bill checks. Hidden text (`display:none`, `hidden`, `aria-hidden`) is removed before the model sees the page. Text addressed to AI readers raises a warning on the form.
- **A synchronous API, not background jobs.** One fetch (10-second limit) plus at most one AI call fits in a single request. Jobs would add polling to the frontend for no gain at this size. Revisit if a headless browser is ever added.
- **No headless browser.** Render's free tier has 512 MB of memory. Pages that build themselves with JavaScript (Luma's discover page, for one) aren't supported. The organizer types the details, as today.
- **The government GST portal isn't scraped.** Its taxpayer search is behind a captcha, and getting past it would mean circumventing an access control. Registry lookups go through an adapter. A licensed GSP or paid GSTIN API plugs in as one class. The demo uses a fixture registry of made-up businesses, and every response it shapes says "Demo registry".
- **Vendor verdicts are for the organizer only**, as with Hisaab's bill flags. A flagged GSTIN is often an OCR slip or an unregistered small shop, which is legal below the GST threshold. That's not fraud.
- **Research is a tool, not an endpoint.** It reads hundreds of reviews in one go. As a public endpoint it would be slow and easy to abuse.

## What testing against real pages found (12 Nov 2026)
- AllEvents and Meetup event pages embed full schema.org Event data, so all five fields came out with no AI call. One AllEvents concert listed tiers from ₹999 to ₹4,999. The import used ₹999 and raised `several_prices`.
- **Fixed:** AllEvents tags price-less offers with `"priceCurrency": "USD"`, which made a rupee event read as "not in rupees". A currency with no amount is now ignored.
- **Fixed:** event sites put the whole postal address into `streetAddress`, so the venue came out as a 150-character line. The venue is now the place name plus the locality ("I-Venture @ ISB, Hyderabad"), which is what a maps search needs.
- Luma's discover page is client-rendered, with no event data in the HTML. The old `lu.ma` domain timed out. Townscript's discover page served a notice page. Individual event pages are what organizers share, and those are what this service targets.
- Hisaab's demo bill GSTIN fails the check digit (see Problem).
- The Groq key in Hisaab's local `.env` has expired (`401 expired_api_key`). AI calls failed cleanly, with a warning and empty fields. That's the intended behaviour, and it's also why the AI eval cases are pending.

## Risks
| Risk | Mitigation |
|---|---|
| A pasted URL targets the server's own network (SSRF) | http(s) only, ports 80 and 443 only, no credentials in the URL. The host must resolve only to public addresses, checked again on every redirect. Responses are capped at 2 MB and must be HTML. **Known gap:** DNS rebinding between the check and the connect. The fix is to connect to the checked IP directly. |
| Sites block automated reads, or their terms forbid them | A 401, 403 or 429 shows "fill the details in by hand". Only pages the organizer chose to share are read, once, like a link preview. Nothing is stored or republished beyond their own collection. |
| AI invents or is steered to a value | It must quote the page, and code checks the quote. Hidden text is removed and injection text raises a warning. Every AI value is `medium` and listed in `needs_confirmation`. |
| A listing page imports the wrong event | The next upcoming event is chosen, the rest are returned as `alternatives`, and `several_events` is raised |
| Demo registry data is mistaken for real | `registry.source = "demo_fixture"`, and the summary and check messages say "demo registry" |
| A GSTIN suggestion is wrong | Offered only when exactly one reading is valid. The eval gate is 0 wrong out of 2,000. It's always phrased as a question ("Did the bill say …?"). |
| Rate limits or an expired key | No retries on auth errors; the import still answers with structured data and a warning. `/health` reports whether AI is on. |

## Integration with Hisaab (next step)
1. **"Import from a link" on the create-collection form.** The response prefills the form. Fields in `needs_confirmation` get a "check this" highlight, warnings appear above the form, and AI evidence shows on tap ("from: 'Contribution: ₹1,500 per flat'").
2. **Bills.** Add `gstin` to Hisaab's bill-reading schema. When a bill has one, call `/v1/vendors/check`. An `invalid` or `mismatch` verdict becomes one more "Worth a look" reason, organizer-only.
3. **Types.** `npx openapi-typescript ../hisaab-scout/openapi.json -o src/lib/scout/types.ts`.
4. **Configuration.** `SCOUT_URL` and `SCOUT_API_KEY` in Hisaab. If they're unset, the import box is hidden and bills skip the vendor check.

## Rollout and validation
1. Renew the Groq key and run `uv run python eval/run.py` to measure the AI-only pages. The gate is that an injection page never imports ₹1.
2. Collect 30 real links from the pilot organizers' WhatsApp groups, run them and record `found`, the fields fixed by hand, and the time to save. This becomes `eval/fixtures/real/`. Store outputs, not third-party pages.
3. Ask organizers whether the highlighted fields made sense and whether a vendor flag ever felt unfair.
4. Choose a licensed GSTIN provider only if flagged bills show up in practice. Until then, offline checks already catch every made-up or mistyped number.

## How it's tested
- **Unit tests** (`tests/`, 136 tests):
  - SSRF blocking, including redirects to private IPs, IPv4-mapped IPv6 and the cloud metadata address;
  - parsing of dates, prices and venues (Indian digit grouping, UTC to IST, day-first dates);
  - every evidence check, every importer path, and the not-an-event page;
  - hidden injection text never reaching the model;
  - GSTIN checksums against published samples, and random misreadings never getting a wrong fix;
  - API auth, the rate limit and the error envelope;
  - verbatim quotes in research reports.
- **Eval** (`eval/run.py`):
  - 16 synthetic pages covering platforms, broken data, a Google Form, a notice board, a poster page, an injection attack and a non-event;
  - 2,000 GSTIN typo and misreading trials;
  - four hard gates.
- **CI** runs lint, the tests, the no-AI eval and the `openapi.json` drift check on every push.
