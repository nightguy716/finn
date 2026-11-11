# BUILD_LOG

## 2026-11-10 — Datacenter reachability, Washington (iad1)

`api/probe.py` ran on Vercel region `iad1`:

| Source | Result |
| --- | --- |
| BSE announcements, RELIANCE `500325` | HTTP 403 |
| NSE homepage | HTTP 403 |
| NSE corporate-announcements API, RELIANCE | HTTP 200 |
| Screener public RELIANCE page | HTTP 200 |
| yfinance `RELIANCE.NS` daily bars | rows came back |

BSE is blocked from the US region. NSE’s API answered even when the homepage did not. The next probe moves the same function to Mumbai (`bom1`) and checks PDF downloads plus three NSE API calls in a row.

## 2026-11-10 — NSE is the live filings source

Mumbai (`bom1`) still got HTTP 403 from BSE. NSE’s announcement API and NSE PDF downloads succeeded 3/3 from Mumbai. BSE is out of the live path. The data layer calls NSE only.

`finn_core` is a local package and CLI. No UI and no new deploy config. Announcements are cached in SQLite under `.finn_cache/` so a repeat run does not hit NSE again. The cache key is `(source, symbol, start, end)` so it can move to Supabase later without changing callers.

AGENTS.md names results and management changes as the enriched cards and tells us not to over-build the rest. It does not list 16 category names. The digest uses 16 keyword categories (results, concall, m_and_a, fund_raise, management_change, litigation, credit_rating, dividend, buyback, order_contract, board_meeting, shareholder_meeting, insider, esop, shareholding, routine). A weak or generic subject is marked `needs_llm` and is not sent to a model yet. Material rows are priority 60 and above. Routine rows collapse to a count per company.

Bharat Seats is `BHARATSEATS` in the brief and `BHARATSE` on NSE and Yahoo Finance. The digest shows the brief name and requests the exchange symbol.

## 2026-11-10 — Results feed, priorities, alerts

Quarterly results were missing because the announcement subject is usually "Outcome of Board Meeting", and the older `corporates-financial-results` feed does not return this season. Checked live for MARICO, TITAN, TRENT, RELIANCE.

`GET /api/corporates-financial-results?index=equities&period=Quarterly&symbol=...` returns HTTP 200 but the latest rows are from early 2025. Adding `from_date`/`to_date` for Oct–Nov 2026 returns `[]`.

The live feed is `GET /api/integrated-filing-results?index=equities&symbol=...&period=Quarterly`. The body is `{"data": [ ... ]}`. Fields used: `broadcast_Date`, `qe_Date` (period end, e.g. `30-SEP-2026`), `audited`, `consolidated`, `type` (`Integrated Filing- Financials` or `Governance`), `type_Sub`, `xbrl`, `ixbrl`, `pdf_attach`. `pdf_attach` is usually null or a URL ending in `/null`. The file link is the XBRL (and an iXBRL HTML). Governance rows are dropped. One row per period, consolidated preferred.

Verified broadcasts for quarter ended 30 Sep 2026: MARICO consolidated 02-Nov-2026 21:03, TITAN 05-Nov-2026 19:11, TRENT 29-Oct-2026 19:45, RELIANCE 30-Oct-2026 21:32. The board-outcome announcement on the same day carries the results PDF when the attachment text says "financial results" (TITAN `SEoutcomeQ227.pdf`). MARICO's outcome text does not, so that PDF stays a board meeting and the integrated filing is the results row.

A 7-day digest therefore shows results only when the broadcast falls inside the window: TITAN and BHARATFORG (XBRL plus the outcome PDF). MARICO and ITC broadcast on 2 Nov, which is the extra day kept for alert context, so they print under the 3 Nov move and not in the material list. RELIANCE and TRENT are outside both.

Priorities: a concall intimation is 30; a transcript or audio-recording upload is 52; an investor presentation is 48; a change in auditors is 42. "Updates", "General Updates", "Monitoring Agency Report", "Committee Meeting Updates", and "News Verification" are routine unless the attachment text names another event. Material stays priority 60 and above. Medium is 42–59.

Alerts: one row per ticker per day, already merging move and volume. Default thresholds are 5% and 2.5x, still `--move-pct` and `--volume-n`. Severity is absolute move times the volume ratio. `--alert-cap` defaults to 8. Each alert prints filings from that ticker within one calendar day.

Ticker aliases live in `finn_core/config.py`.

## 2026-11-10 — Quarterly results from XBRL

The integrated-filing XBRL does not contain three quarterly columns. Context `OneD` is the current quarter (about 90 days). Context `FourD` is the year-to-date, not the previous quarter. There is no year-ago context. QoQ and YoY are the `OneD` facts from the previous-quarter filing and the year-ago filing. Those are the figures as originally reported. The results PDF can restate a comparative column; that restatement is not in the XBRL. Marico's Sep 2026 statement labels revenue "Restated" and prints the year-ago quarter as 3,450 crore; the Sep 2025 XBRL says 3,482.

Facts on this feed are absolute rupees when the largest of revenue, total income, PBT, or PAT is at least 10 crore of rupees. They are divided by 1e7 to reach crore. `LevelOfRounding` (Crores, Lakhs, Millions) is used only when the anchor is smaller than that. Bharat Forge's file says Millions and still stores rupees, so the anchor rule is what keeps it in crore.

EBITDA = PBT + finance costs + depreciation and amortisation − other income. Margin is EBITDA / revenue. The XBRL `OtherIncome` tag can bundle lines the PDF splits. Titan's tag is 816 crore, which is the PDF's other income 145 plus the fair-value change on the NCI put of 671.

Banks and NBFCs do not get an EBITDA. HDFCBANK, any `INTEGRATED_FILING_BANKING` file, and a statement with interest earned but no product sales and no finance-cost or depreciation line: interest expense is the cost of funds. Revenue for a bank is total income (interest earned + other income), not revenue from operations. BAJFINANCE and any `INTEGRATED_FILING_NBFC` file, or a lender whose finance cost exceeds a quarter of revenue and who reports no product sales, get the same treatment: revenue, PBT, and PAT only, `ebitda` null, with that reason.

PAT prefers profit attributable to owners. A card is flagged, not dropped, when revenue or PAT is missing, not positive, or outside 1 to 10 lakh crore (revenue) or 3 lakh crore (PAT), or when PBT differs from PAT + tax − share of associates by more than 3%.

If the current quarter has no revenue or PAT in the XBRL, the outcome-of-board-meeting PDF is read with pypdf and extracted by `gemini-3.5-flash-lite` (strict JSON, `gemini-2.5-flash-lite` if that model is missing). Those cards are `source=pdf_llm`. XBRL and PDF text are cached by symbol and period, and so is the model JSON, so a repeat does not download or call again. The seven-company run (Titan, Bharat Forge, Marico, Reliance, Trent, ITC, HDFC Bank), quarter ended 30 Sep 2026, all resolved from XBRL. Model tokens: 0. No sanity flags.

Checked against the results PDFs. Titan: sale of products plus other operating revenue is 20,337+277, 20,787+569, and 16,461+2,264, which equals the XBRL revenue 20,614 / 21,356 / 18,725. Statutory PBT 3,001 / 2,427 / 1,521 and PAT 2,393 / 1,777 / 1,120 match. Finance cost 536 and depreciation 263 match. Marico: revenue 3,897 / 3,957 match, year-ago is the restated 3,450 against XBRL 3,482; PBT 674 / 790 / 550 and owner PAT 550 / 630 / 420 match.

## 2026-11-10 — Push feed

`build_feed(as_of, window_hours, symbols, move_pct, volume_n)` is the object the UI will render. A date `as_of` means 23:59:59 that day, so a replay of 6 Nov includes filings broadcast on 6 Nov. The window is `(as_of − hours, as_of]`. A 24-hour window ending 6 Nov 23:59:59 therefore starts 5 Nov 23:59:59. Titan's results (5 Nov 19:11) and Titan's retirement are in the 72-hour feed and not in the 24-hour feed. HDFC's compliance-officer appointment and Marico's two acquisition filings are on 6 Nov, so they are in both.

Clustering is in `finn_core/events.py`. Every results filing for one company on one calendar day is one results event, and the filings stay on it as sources. An investor presentation that day, and a newspaper publication whose text mentions results, join that event instead of becoming their own cards. Other filings group by symbol, category, normalised subject, and day. Marico's two "Acquisition" filings are one `m_and_a` event. Titan's retirement and change of auditors stay two events because the subjects differ.

Management cards call `gemini-3.5-flash-lite` on the attachment PDF (strict JSON, cached as `mgmt_llm` version `v2`). Fields are person, role, change type (appointment, resignation, retirement, change in designation), effective date, and the profile written in the disclosure. If the filing has no education, experience, or previous employers, profile is null and `profile_note` says so. Titan's retirement letter has no bio. HDFC's annexure does, and the card uses that text. No web lookup.

`m_and_a`, `fund_raise`, `litigation`, `credit_rating`, and `order_contract` get one sentence from the PDF, cached as `summary_llm` version `v2`. Results stay on the XBRL card and do not call the model. A cache hit adds nothing to the run's token total.

The first PDF save failed: the filename used the filing timestamp, which contains colons, and Windows rejected the path. That pass spent 986 tokens on the short exchange blurb and is stored under version `v1`, which the feed no longer reads. The saved name is now a sanitized timestamp plus a short hash of the URL.

72-hour feed, `as_of` 2026-11-06, after the fix: management 3 calls, 5,075 tokens; summaries 5 calls, 14,905 tokens; total 19,980. The same 72-hour call again: 0 calls, 3 management cache hits, 5 summary cache hits, 0 tokens. The 24-hour feed reused the HDFC and Marico extractions and also cost 0 tokens.

Alerts are unchanged: one per ticker per day, capped at 8, each linked to events for that ticker within one calendar day. The loader keeps one extra day so a 6 Nov volume alert can point at 5 Nov results even when those results are outside the 24-hour card window.

## 2026-11-10 — Pull documents and the quarterly series

No model calls. `python -m finn_core.pull` discovers transcripts, the latest annual report, and six quarters of results for any NSE symbol.

NSE `corporate-announcements` takes `from_date` and `to_date` and has no page token. One call for Titan from 10 Nov 2022 to 10 Nov 2026 returned 639 rows with the oldest on 10 Nov 2022, so a multi-year window is not capped. The transcript search asks for about fourteen months (five quarters). It splits that window only when a long response has at least 200 rows and the oldest row is more than 60 days after the requested start.

A concall row counts as the transcript when the exchange text says "copy of transcript" or "about Transcript", or the filename says transcript. A "will hold / schedule of" letter is a notice even if it promises a transcript later. An earnings transcript is preferred to a different conference in the same quarter. After download, a one- or two-page letter that says the transcript was uploaded on the company website is not treated as the transcript. The real file is then taken from the public Screener page, then from the company site linked there. Text is stored with page numbers in the `doc_text` cache, keyed by symbol and URL. A PDF with under 40 characters per page is marked scanned. None of the five test companies had one.

`/api/annual-reports?index=equities&symbol=` returns the PDF on `nsearchives` with `fromYr` and `toYr`. All five companies resolved there for 2025–26 (`toYr` 2026). Screener's annual-report links point at BSE, so they stay the fallback.

The quarterly series is each integrated filing's own current-quarter facts, in crore, via the existing XBRL parser. OneD is used only when it spans about a quarter. CG Power's March 2026 file has OneD from 2025-10-01 to 2026-03-31, and its September 2025 file has OneD from 2025-04-01 to 2025-09-30, so those quarters are flagged and left blank. June 2025 is not in the integrated-filing feed for CG Power.

Checked 10 Nov 2026:

| Ticker | Transcripts | Route | Gap | Annual report | Quarters with revenue | Characters |
| --- | --- | --- | --- | --- | --- | --- |
| TITAN | 4/5 | NSE | Sep 2026 audio only (recording filed 5 Nov, transcript not filed) | 2026, NSE | 6/6 | 207,078 |
| MARICO | 5/5 | NSE | none | 2026, NSE | 6/6 | 282,440 |
| CGPOWER | 4/5 | Screener PDFs on cgglobal.com | Sep 2026 audio only. NSE's five "transcript" files are one-page letters pointing at a script-rendered investor page with no PDF | 2026, NSE | 3/6 | 180,656 |
| DMART | 1/5 | NSE | Sep 2026, Mar 2026, Dec 2025, Sep 2025 not filed. Screener's concall list for this company is the August analyst-meet transcript | 2026, NSE | 6/6 | 112,041 |
| ASIANPAINT | 5/5 | NSE | none. The 3 Nov 2026 file is named Q2FY26; the letter is the 29 Oct 2026 conference, so the quarter is Sep 2026 | 2026, NSE | 6/6 | 256,302 |

Titan Sep 2026 revenue 20,614, EBITDA 2,984, PBT 3,001, PAT 2,393 matches the results card. Marico Sep 2026 revenue 3,897, PBT 674, PAT 550 matches it too.

## 2026-11-10 — Promise Ledger

`promise_ledger(symbol)` in `finn_core/ledger.py`. Still no UI. Guidance comes only from the transcript pages. The annual report is discovered and not mined.

Each transcript is reduced to at most eight pages that contain forward-looking words, then sent to `gemini-3.5-flash-lite` (fallback `gemini-2.5-flash-lite`) with a JSON schema. A promise is kept only when the evidence is consecutive words on the page that was sent. Vague lines with no number and no stated movement are dropped. A crore target or a "3x" is not turned into a percent. "Double-digit", "high-teens", "mid-teens", and "high single-digit" become bands only when the quote uses those words and states no number. A portfolio, brand, international business, or a named division is marked not checkable, so it is not later scored against the consolidated series.

The model does not do the arithmetic. It names a metric and a period. Revenue growth, EBITDA margin, EBITDA growth, and PAT growth are computed from the quarterly series. A fiscal year that has not ended, including FY2027 as of 10 Nov 2026, is pending. Volume, capex, and an unnamed "other" are not checkable. The one-line verdict is `gemini-3.6-flash` (fallback `gemini-3.5-flash`) and it sees only the structured rows. `gemini-3.8-flash` is on the free list but a short call to it timed out at 90 seconds, so it is not the first choice. `gemini-2.5-flash` returned 404.

Half-year filings: CG Power's March 2026 OneD is dated 1 Oct 2025 to 31 Mar 2026 and the revenue is 3,441.76 crore. That equals the March year-to-date (12,417.95) minus the December year-to-date (8,976.19), so the figure is the quarter itself and is not produced by subtracting the December quarter. September 2025 stays blank because June 2025 is not in the feed. Subtracting a half year is used only when the other quarter exists and the half is actually the sum.

Cache keys: `guidance_llm` by symbol and transcript URL, `verdict_llm` by a hash of the slim ledger. A failed model call is not cached, so the next call retries that document only. With filings and PDF text already cached, a cold model pass on 10 Nov 2026:

| Ticker | Guidance | Verdict | Total | Tokens |
| --- | --- | --- | --- | --- |
| MARICO | 24.9s | 14.1s | 39.0s | 16,952 |
| TITAN | 13.8s | 7.4s | 21.5s | 8,434 |
| ASIANPAINT | 18.8s | 23.8s | 42.6s | 20,415 |
| CGPOWER | 13.5s | 11.7s | 25.3s | 8,948 |
| DMART | 4.7s | 64.0s | 68.8s | 3,780 |

Flash-Lite returned 404 for Marico's June 2026 transcript, two Titan transcripts, and two CG Power transcripts. Those were extracted on the next call. DMart's first verdict used the 45-second timeout and wrote nothing; the next call wrote it. A later run of all five was 0 tokens and under 0.3 seconds each. The DMart verdict stage is what crossed a 60-second serverless limit, on the failure path. Five uncached transcripts plus a slow verdict can also cross it. The per-document cache means the retry finishes the remainder. Discover and series were already cached in these timings; a ticker with no saved PDFs also pays the download.

## 2026-11-10 — Tracking, not just pending

An open fiscal year is no longer left as "pending" when the same span of last year is in the series. H1 FY27 versus H1 FY26 is computed in code: revenue, EBITDA and PAT growth, and the EBITDA margin change in basis points. Inside the promised range is `tracking_on_track`. Clearly above a floor, or above the top of a range, is `tracking_ahead`. Below the floor is `tracking_behind`. `pending` is only the case where that comparison cannot be made. FY26 growth versus FY25 is pending here: the integrated feed has no quarters before June 2025 for these five names. A target more than three years out (FY2030) goes in `long_term_targets`.

Transcripts now cover seven quarters. Marico: 6 statements aimed at FY26, and no next-quarter statement. Asian Paints: 7 aimed at FY26, and 1 at the next quarter. The model still sees at most eight pages. A page counts as dropped when "FY26" or "next quarter" sits within 180 characters of a forward-looking word and the page was not sent. That is 15 of 29 such Marico pages, and 4 of 20 Asian Paints pages. One dropped Marico line is "we expect the business to see a gradual improvement in growth in the subsequent quarters", which has no number.

A row is kept only when the sentence itself names revenue, EBITDA, margin, PAT, volume, or capex. There is no "Other". Marico's "24%, 25% on the minimum side" does not name the metric, so it is `low_confidence` and is not the figure compared with the 25.8% EBITDA growth. Constant-currency and segment lines are `segment_level`. A sentence about the quarter already reported ("we delivered", "have achieved") is dropped. `quote_check` is `ok` only when the number in the row is in the quote, or comes from a named band such as "double-digit".

The same metric, period, and unit (percent or basis points) across calls is one row. The calls are listed. A changed number is a sequence of set / raised / cut / maintained. A later sentence that does not name the metric does not overwrite a named one.

The verdict sees only delivered, missed, partly, and the three tracking statuses, and it has to cite the numbers. `gemini-3.6-flash` is capped at 20 seconds and then falls back to `gemini-3.5-flash-lite`. Guidance retries a 404, 429, 503, or timeout with backoff, then the other Flash-Lite. Each call extracts at most three uncached transcripts and returns `progress: {stage, done, total}`. Marico's cold run was 3/7, then 6/7, then complete.

Cold, with PDFs already cached, on 10 Nov 2026. Tokens are the guidance calls. The cached run after that was 0 tokens.

| Ticker | Cold seconds | Guidance tokens | Cached seconds |
| --- | --- | --- | --- |
| MARICO | 34.6 over 3 calls | 25,745 | 0.28 |
| TITAN | 27.8 over 2 calls | 13,006 | 0.88 |
| ASIANPAINT | 51.8 over 3 calls | 20,340 | 0.32 |
| CGPOWER | 21.2 over 2 calls | 10,857 | 0.75 |
| DMART | 16.8 in 1 call | 4,177 | 0.34 |

No single call exceeded 27 seconds. The 20-second verdict cap is what keeps a hung Flash model inside a 60-second limit. The old failure path, a 45-second timeout followed by another model, was the thing that crossed it.

## 2026-11-10 — Scope, and a Supabase cache

Titan's scored margin row was jewellery guidance. Page 6 of `TITAN_12052025105522_SEinvestorcalltranscriptQ4.pdf` says "As far as coming to 11% to 11.5% margin guidance, I think that stays." The lines above it are about the jewellery business. The same range is repeated on page 4 of the 11 Aug 2025 transcript. Extraction now has `scope` (`consolidated`, `segment`, `geography`, `other`) and `scope_name`. A division named in the passage around the quote wins over a consolidated label. Only consolidated guidance is scored. Segment and geography rows stay on the ledger as `segment_level`, with the note that they are not compared with the consolidated series. Titan's 11–11.5% row is `segment_level` / Jewellery, actual blank, and the verdict no longer treats it as a company result.

The pre-filter keeps 12 pages, ranked by forward-looking words per word of text. Hint pages still dropped: Marico 5 of 29 (was 15 of 29), Asian Paints 2 of 20 (was 4 of 20). A sentence that names two bands keeps the band next to that metric, so "double-digit revenue" and "high-teen EBITDA" in one sentence are not given the same range. A later quote with no number does not replace a numbered promise. "We've been able to stay at…" with no forward word is a reported result and is dropped, which removes Asian Paints' false 43% EBITDA miss (that sentence is the gross margin).

Guidance tokens for the new extraction, against the previous run: Titan 15,959 (extra 2,953), Marico 40,807 (extra 15,062, including one failed fallback and one re-read of the 6 Nov transcript), Asian Paints 23,762 (extra 3,422). Hand-checked figures held on the local cache. Marico revenue 16.51% is `tracking_ahead` of at least 10%. Marico EBITDA margin +144 bps (19.46% versus 18.02%) is `tracking_on_track` inside the scored 140–150 bps band. The 120–150 bps sentence is on page 17 of the 6 Nov transcript, where the speaker says he is not giving margin-percentage guidance, and the model did not return it. Asian Paints H1 FY2027 margin 18.16% is inside 18–20%, and FY2026 18.37% is delivered against that band. "24%, 25% on the minimum side" is not scored.

`CACHE_BACKEND=supabase` sends extracted text, model output, and verdicts to `cache_entries` through the REST API with `httpx`. The secret key is a header and is not logged. Raw XBRL stays in the local sqlite file. PDF bytes stay on disk. The table has row level security and no policies.

Marico, cold, against an empty table, 10 Nov 2026: 35,085 guidance tokens and 348 verdict tokens over three passes, about 66 seconds. The same ledger again: 7 guidance hits, 1 verdict hit, 0 tokens, 4.1 seconds. The table then held 17 Marico rows (7 transcripts, 7 guidance outputs, 1 verdict, the announcement list, and the integrated-results list), about 542 KB of JSON.

## 2026-11-10 — API, Mumbai, and the pause fallback

Titan was read back from the local cache at 0 tokens. The 11–11.5% line is still page 6 of `TITAN_12052025105522_SEinvestorcalltranscriptQ4.pdf`: "As far as coming to 11% to 11.5% margin guidance, I think that stays." Status `segment_level`, scope Jewellery, actual blank. The verdict is the code sentence that no consolidated guidance in these transcripts can be checked.

BSE returns 403 from both Washington and Mumbai, so it stays out of the live path. NSE's announcement API and NSE PDF downloads answered from Mumbai (`bom1`). The API is one Python function in that region, 60 seconds max. `pyproject.toml` points the entrypoint at `api.index:handler`. Routes rewrite onto it: `/api/health`, `/api/feed`, `/api/ledger`, `/api/alerts/config`. CORS is open so a later frontend, a separate Vercel project with root directory `web/`, can call it. The old probe moved to `spike/probe_server.py` so the deploy is one bundle. yfinance, pandas, and numpy together are about 140 MB, under Vercel's 250 MB unzipped limit, so they stay.

Vercel's disk is ephemeral. Parsed quarters are `series_quarter`, keyed by symbol and period, and a results card is `results_card` on the same key. Raw XBRL and PDF bytes stay under `/tmp` on the server and in the local sqlite file on the laptop. A Marico series read with the raw-file cache hidden still returned 10 quarters, 6 with revenue, and did not call the downloader. The warm Marico ledger after that was 0 tokens and 0 file downloads.

`/api/feed` returns a stored snapshot when one exists for that as-of, window, symbol list, and thresholds. Otherwise it computes and stores. `/api/ledger` returns `{progress, ledger}` and does one uncached stage per call (discover, then the series, then one guidance batch) so a cold ticker stays inside 60 seconds. The client repeats until `stage` is `complete`. `/api/alerts/config` is the defaults, 5% and 2.5x.

`scripts/snapshot.py` wrote the 6 Nov 2026 feeds (24h and 72h, default portfolio, default thresholds) and the ledgers for MARICO, ASIANPAINT, TITAN, CGPOWER, and DMART into Supabase and into `data/snapshot`. The 24h feed was 2 cards and 5 alerts, the 72h feed 10 cards and 8 alerts, both at 0 model tokens because the extractions were already cached. CG Power and DMart needed a fresh guidance pass (about 13,400 and 5,600 tokens). If Supabase is paused, those same JSON files are what the API serves. A ticker with no file, such as a cold PIDILITIND, still needs the live cache and NSE.

Production is `https://finn-r4y3.vercel.app`. Checked 10 Nov 2026 after the env vars were set.

| Call | Seconds | Result |
| --- | --- | --- |
| `GET /api/feed?as_of=2026-11-06&hours=72` | 1.44 | `source=cache`, 10 cards, 8 alerts, 0 tokens. Window 3 Nov 23:59:59 to 6 Nov 23:59:59. |
| `GET /api/ledger?symbol=MARICO` | 0.94 | `source=cache`, complete 7/7, 0 tokens. Verdict: +144 bps against 140–150 bps, 16.51% against at least 10%, 25.76% against 17–19%. |
| PIDILITIND, 9 calls | 6.44, 11.11, 17.83, 9.59, 6.06, 5.81, 7.80, 4.69, 10.42 | discover 7/7, series 6/10, then one transcript per call until complete 7/7. About 21,100 guidance tokens plus one verdict. Slowest call 17.83s. |

BSE stays out of this path: 403 from Washington and from Mumbai. NSE answered from Mumbai, which is why the function region is `bom1`. The 6 Nov feed is the stored replay, not a live re-download. PIDILITIND had no snapshot file, so those nine calls were live. The verdict it stored compares a 23.96% margin with a "at least 200 bps" promise and marks it missed. That comparison is not trusted until the basis-point row is checked.

## 2026-11-10 — Ledger QA: basis points are a change

The Pidilite miss was page 4 of `AnnPdfOpen.aspx?Pname=ecbc316a-5f8d-4143-8061-df7980b55a66.pdf`: "Our gross margins at a stand-alone level improved by about 200 basis points as input prices remained benign." The model typed it as consolidated EBITDA margin, at least 200 bps, quarter ended 2025-12-31. The closed-quarter path then compared the 23.96% margin level with 200. A basis-point figure is a year-on-year change. Margin-expansion promises are now scored on that change, over the same span already used for Marico. A margin level is still scored on the level.

A row is scored only when the quote and the series agree on kind: level versus change, percent versus basis points, growth versus margin. The measure reports which of those it returned, and that has to match the promise. The metric has to be named in the quote, and the period and scope have to be stated. A gross-margin or standalone sentence, a basis-point figure on a non-margin metric, or a quote that says basis points while the promise is a level, is `not_scored` with a plain reason and a blank actual. `missed` is not used unless both figures are in the same unit.

The Pidilite sentence is `not_scored`: it is a standalone gross margin, and it reports a result rather than guidance. The verdict is the code sentence that no consolidated guidance in these transcripts can be checked. Re-judging the six demo ledgers used 0 guidance tokens. Asian Paints needed one new verdict (1,335 tokens) after the closed-year margin note was filled in. Live `GET /api/ledger` for PIDILITIND, MARICO, and ASIANPAINT returns `source=cache` with these verdicts. PIDILITIND is now in `data/snapshot` as well as Supabase.

## 2026-11-10 — Briefing screen

The frontend is a Vite + React + TypeScript app in `web/`, with Tailwind and framer-motion. It does not import `finn_core`. The API base is `VITE_API_BASE` (`web/.env`, gitignored; `web/.env.example` has the production host). The first screen is the briefing only. Research is a tab with one sentence, because the promise ledger is the next screen.

The layout is a 390px column. On a wider window that column sits in the centre. Light paper, one green, IBM Plex Sans for text and IBM Plex Mono for figures. No mock filings. The default replay is 6 Nov 2026, 72 hours, which is the stored feed: 8 movers, 10 filings, 30 routine. 24 hours is the other stored window (5 movers, 2 filings, 10 routine). A 7-day chip is there; that window is not snapshotted, so the API computes it.

Results cards show revenue, EBITDA, PBT and PAT in ₹ crore, with QoQ and YoY chips and a three-bar comparison (year-ago, previous, this quarter). EBITDA is labelled "approx., derived". A percent against a negative or zero base is replaced with "swung to profit", "swung to loss", or "still a loss". Bharat Forge PAT for the September 2026 quarter, from a loss of 89.73 crore, reads "swung to profit" rather than −407%. A bank or NBFC reason from the API replaces the EBITDA row. Management cards carry the person, role, change and effective date, with the filing profile collapsed. Titan's retirement of Noel Tata has no profile, and the card says so. Other material cards are a category, the company and the one-line summary. Every card links to the filing. Routine filings are one row, "30 routine filings", opening to a count per company.

Alert thresholds open in a sheet. The defaults, 5% and 2.5×, come from `/api/alerts/config`. Moving a slider refetches `/api/feed` with those parameters. A mover chip opens the filings around that day. Loading is a skeleton, a failed load keeps a retry, and an empty window says nothing was filed.

PWA: `manifest.webmanifest`, 192 and 512 icons, theme colour `#f3f1eb`, and a small service worker so a phone can install it. Checked locally at 390×844: the 72-hour feed, the Marico move sheet, the HDFC profile, the routine list, the 24-hour window, the settings defaults, and the centred column at 1280px wide.

## 2026-11-10 — Research tab, and a second Vercel project

Research is the other tab in `web/`. It calls the existing `/api/ledger?symbol=` until `progress.stage` is `complete`. A failed step keeps the last progress and a retry calls the same URL again, so the server cursor resumes. The API contract and `finn_core` are unchanged. CORS on the API is already `Access-Control-Allow-Origin: *`, so a new frontend domain is allowed without an API change.

The search accepts any NSE symbol (letters, digits, `&`, hyphen). Chips are MARICO, ASIANPAINT, TITAN, and PIDILITIND, with a line that any NSE ticker works. Recent symbols stay in `localStorage`. A symbol with other characters is refused before a request.

The ledger opens with the verdict, then a coverage chip (`7 of 7 transcripts, 6 quarters of results`). A thin-history note, when the API sends one, is its own line. DMart’s is “Only 2 transcripts in the last seven quarters.” Scored rows are grouped delivered, tracking ahead, on track, behind, partly, missed. Opening one shows the quote, page, document, speaker, promised against actual, and the arithmetic. A word the quote used and the band we stored is labelled, for example `'high-teen' read as 17–19%`. Revisions of scored promises are a short timeline: date, value, set, raised, cut, or maintained. Marico’s margin band goes from 150–200 bps on 30 Jan 2026 to 140–150 bps on 11 Aug 2026, marked cut. Rows that cannot be checked (`not_scored`, `segment_level`, `low_confidence`, `not_checkable`) sit in one collapsed section with the plain reason. If nothing was scored, that section starts open. Pending rows are “Not yet due”. Long-term targets are their own collapsed group.

The snapshot is the latest quarter, trailing twelve months, and six revenue bars with an EBITDA-margin line. EBITDA is labelled derived and excluding other income. PAT margin is PAT divided by revenue, labelled as that.

`web/vercel.json` rewrites unknown paths to `index.html` so a refresh still opens the app. The API project stays the one with root `/`. The frontend is a second Vercel project whose root directory is `web`, framework Vite, and build-time env `VITE_API_BASE=https://finn-r4y3.vercel.app`.

Checked locally at 390px: Marico from cache (verdict, coverage, chart, the high-teen row, the cut, the unverifiable reasons), an invalid `!!` that does not call the API, and a typed DMART that keeps a recent chip and shows the thin-history note. The live frontend is `https://web-eosin-ten-23.vercel.app`.

## 2026-11-10 — A dollar range is not a percent

The live Wipro ledger scored “we expect our revenues to be in the range of $2.571 billion to $2.625 billion” as revenue growth of 2.571–2.625% and marked it tracking ahead of consolidated growth of 9.81%. Numbers under 100 were kept, and nothing asked what unit they were in.

Every promise now has `unit` (percent, bps, currency_usd, currency_inr, count, ratio, other) and `kind` (level or change). Both are read from the quote. The model is asked for them, and the quote wins if they disagree. A row is scored only when the unit matches the comparison (growth needs a percent, a margin needs a percent or basis points) and `quote_check` finds that unit on those numbers, not only the digits. Dollars are `not_scored`: “Guided in US dollars for the IT services segment; our series is consolidated INR.” Constant-currency wording is `not_scored` for the same reason: the series is consolidated rupees. Segment guidance stays `segment_level`. Guidance version stays `v3`, so stored transcripts are not extracted again just to add the field.

The first transcript was labelled “Reading results” because that label belonged to the step that had just finished. While a request is in flight the label is now the step being read, so the first guidance call says “Reading transcript 1 of 7”.

Re-judged from cache at 0 guidance tokens: Marico still 3 scored rows (140–150 bps on track at +144 bps, revenue 16.51% ahead of at least 10%, EBITDA growth 25.76% ahead of 17–19%). Asian Paints still 2 (FY2026 18.37% delivered, FY2027 18.16% on track). Titan, Pidilite, CG Power and DMart still have no scored row. Wipro’s re-read has no scored row. The dollar sentence that came back is page 7 of the 17 Apr 2025 transcript, “$2.505 billion to $2.557 billion”, `currency_usd`, `not_scored`, with that reason. The snapshots, including Wipro, were written again at 0 tokens.

Fresh reads, not in the demo set:

| Ticker | Scored | What was scored |
| --- | ---: | --- |
| INFY | 3 | FY2026 operating margin 20–22% partly, actual 22.94%. FY2027 the same band, ahead, H1 23.70%. Revenue growth 1.5–3% ahead, H1 12.32%. |
| HINDUNILVR | 2 | Margin 22.5–23.5% behind, H1 22.39%. Ice-cream demerger 50–60 bps behind, actual −52 bps. |
| SBIN | 0 | Nothing consolidated could be checked. |
| BRITANNIA | 0 | Nothing consolidated could be checked. |

Two of those scored rows need a look, and they were left scored. Infosys “1.5% to 3%” does not say constant currency in the stored sentence, and 12.32% rupee growth is a long way from that band. Hindustan Unilever’s “Ice Cream demerger is expected to result in an improvement of 50–60 bps” is a separation, and the H1 margin moved the other way. Asian’s two rows still quote PBDIT and are scored as EBITDA margin, as before.

## 2026-11-10 — Verify the passage before a score

Each new ticker failed in a different way: a dollar range, constant currency sitting outside the short quote, a demerger treated as a margin change. Another company-specific rule would miss the next one. A row that arithmetic would score is now checked first.

The check reads the quote and about three sentences either side. It adds `basis` (reported, constant_currency, pro_forma, other, not_stated) and `conditional_on` (the named corporate event, or empty). Constant currency in the promise’s own sentence sets the basis. A neighboring sentence about a different business does not: Marico’s international “mid-teen constant currency” sits beside the consolidated double-digit line and must not pull that line out. If the same filing has already stated consolidated revenue guidance in constant currency, a later sentence that drops the words keeps that basis. That is what catches Infosys.

The verifier is a second Gemini call, cached as `guidance_verify` by symbol, document, and row (`v2`). It returns `consolidated`, `reported_basis`, `independent_of_named_event`, and `metric_named`, each with an evidence quote. Any false flag makes the row `not_scored` with a plain reason. A general condition such as “subject to stable macros” stays on the row as `caveat` and does not block the score. An event blocks the score only when it qualifies this quote. A demerger in the quote does. An acquisition mentioned beside a different metric does not. Guidance extraction stays on `v3`, so the stored promises are not extracted again.

`gemini-3.6-flash` and `gemini-3.8-flash` were both at the free 20-request daily cap, with a retry about 16 hours out. The verifier used `gemini-3-flash-preview`, and `gemini-3.5-flash-lite` when that model was busy. A quota or transport error does not wipe a score. Constant-currency and pro-forma basis still do.

Cached verifier calls: Marico 5 calls, 10,477 tokens, all `gemini-3-flash-preview`. Asian Paints 4 calls, 6,063 tokens. Infosys 10 calls, 10,033 tokens. Hindustan Unilever 2 calls, 1,523 tokens. HCLTech 2 calls, 1,535 tokens. One earlier Marico pass (11,091 tokens) was discarded after it treated the international sentence as the consolidated basis.

Marico’s three rows stayed scored: revenue 16.51% ahead of at least 10%, EBITDA margin +144 bps inside 140–150 bps, EBITDA growth 25.76% ahead of 17–19%. The growth row carries the caveat “subject to stable macros”. Asian Paints’ two rows stayed scored, each with `definition_note` “Company says PBDIT; we compute EBITDA excluding other income”.

Infosys “we are revising our revenue guidance to 1.5% to 3%” is `not_scored`. That page does not say constant currency. The same filing, earlier, says “1.5% to 3% Y-on-Y growth in constant currency terms.” The verifier, looking only at the revision page, said `reported_basis` true. The filing-level basis overrode it: “The same filing states this revenue guidance in constant currency.” The operating-margin rows at 20–22% stayed scored (FY2026 partly at 22.94%, FY2027 ahead at 23.70%). Hindustan Unilever’s “Ice Cream demerger is expected to result in an improvement of 50-60 bps to the reported margin” is `not_scored`, `conditional_on` “Ice Cream demerger”. The 22.5–23.5% mid-term margin stayed scored, tracking behind at 22.39%. “Mid-term” was mapped to FY2027.

Six tickers not seen before, each with 0 scored rows. Nestlé had one transcript. Dabur, UltraTech, and Bajaj Auto speak of “growth” without naming revenue or EBITDA in the sentence, so those lines stay low confidence. HCLTech and Tech Mahindra state revenue guidance in constant currency, or as services, or as EBIT margin. HCL’s company-level “2.5% to 4%” is the same sentence as “constant currency revenue growth” for services. The verifier called that quote reported. The sentence set the basis, and the row is not scored. Fresh guidance reads for those six were about 145,000 Flash-Lite tokens. The demo snapshots were rewritten at 0 tokens.

## 2026-11-11 — Operating margin is EBIT, and a year has to be named

The Infosys 20–22% rows were scored against EBITDA. That series is `(PBT + finance costs + depreciation − other income) / revenue`. FY2026 is the four quarters ending 31 Mar 2026: EBITDA 40,990 on revenue 1,78,650, which is 22.94%. H1 FY2027 is the June and September 2026 quarters: EBITDA 23,098 on revenue 97,455, which is 23.70%, against 23.60% a year earlier. Infosys’s “operating margin” is after depreciation, so those rows were on the wrong profit.

EBIT is now `PBT + finance costs − other income`, depreciation left in, as a percent of revenue. The same bank and NBFC block that drops EBITDA drops EBIT. Series cache version is `v2`, so the quarters were recomputed from the stored filings. A quote that says EBITDA or PBDIT stays on EBITDA. A quote that says “operating margin” or “EBIT margin” is scored on EBIT, with a `definition_note` that states the formula. A quote that only says “margin” is not scored. Extraction stays on `v3`; the metric is remapped when the row is judged.

Infosys, re-scored on EBIT. FY2026: PBT + finance costs − other income = 36,089 on revenue 1,78,650, which is 20.20%, inside 20–22%, so the row is now delivered. H1 FY2027: EBIT 20,493 on revenue 97,455, which is 21.03%, against 20.92% a year earlier (+11 bps), on track inside the same band. Both quotes say “operating margin”. The verifier kept both. The 1.5–3% revenue revision stays `not_scored` because the same filing states it in constant currency.

HCLTech, which had no scored row, now has two, both EBIT. FY2026 “full year EBIT margin guidance of 17% to 18%” is 16.44% (EBIT 21,393 on revenue 1,30,144), partly, below the band. The same passage raises services and company revenue guidance in constant currency; that is a different sentence, and the margin sentence itself names EBIT. FY2027 “EBIT margin guidance remains at 17.5% to 18.5%” is H1 17.52% (EBIT 12,296 on revenue 70,199) against 16.77% a year earlier (+75 bps), on track. That sentence also gives company growth of 2.5% to 4% and does not say constant currency; only the margin half is scored. Tech Mahindra still has no scored row.

A promise is scored only when its own quote, or the passage when the quote names no period, states a fiscal year, “this year”, “full year”, or “next year”. “Mid-term”, “near-term”, “medium term”, and “long-term” in the quote, with no year in that quote, go to `long_term_targets`. “Next year” and “after this year” are the following fiscal year, not the year the call is in. A neighboring sentence that says “this year” does not date a quote that says “next year”. If the quote and the passage name neither a year nor a vague horizon, the year the extractor attached is kept. That is what leaves Asian Paints’ undated 18–20% PBDIT band on FY2026 and FY2027.

Hindustan Unilever’s 22.5–23.5% row is no longer scored. The quote is “we expect the mid-term margin guidance to remain around our current guided range of 22.5% to 23.5%.” The passage also says “we expect FY ’27 to be better than FY ’26”, which is about the year, not the horizon of the margin band, and it does not mention the demerger. It does not say EBITDA or EBIT. A different passage says “Our current near to mid-term guidance is 22-23%, hence everything else being equal, Ice Cream demerger adds 50-60 bps to this guidance.” Adding 50 bps to 22–23% lands on 22.5–23.5%, the low end of that 50–60 bps adjustment. The 22.5–23.5% sentence does not say that, so that row is not marked event-dependent. Both passages say mid-term, so both rows sit in `long_term_targets` and neither is scored.

Marico’s three previous rows are unchanged: EBITDA margin +144 bps inside 140–150 bps, revenue 16.51% ahead of at least 10%, EBITDA growth 25.76% ahead of high-teen 17–19%. A fourth row is new. On 30 Jan 2026 the quote is “we would strive for improving the operating margin by about 150-200 basis points”, in a passage about next year. That is now EBIT, H1 FY2027 17.93% versus 16.66% (+127 bps), tracking behind. The passage does not say depreciation. It is scored because the quote says “operating margin”, with the definition note. It used to be an earlier revision of the EBITDA 140–150 bps band. Asian Paints is unchanged: FY2027 18.16% on track, FY2026 18.37% delivered, both still PBDIT read as EBITDA.

`gemini-3.6-flash` and `gemini-3.8-flash` share a 20-request daily free cap (`gemini-3.5-flash` aliases 3.6). Extraction stays on `gemini-3.5-flash-lite`. The one verdict per ticker tries `gemini-3.6-flash`, then `gemini-3-flash-preview`, then Flash-Lite, one attempt each. The verifier tries the preview, then Flash-Lite. Groq is called only after a Gemini 429, and only for extraction and verification. The free models on Groq’s docs on 11 Nov 2026 are `openai/gpt-oss-20b` and `qwen/qwen3.8-27b` for extraction, and `openai/gpt-oss-120b` then `openai/gpt-oss-20b` for verification (30 RPM, 1,000 requests/day, 8,000 tokens/minute). Llama 3.1 8B and Llama 3.3 70B are enterprise on that page, so they are not used. If every provider returns a daily limit, the ledger raises `QuotaError` and the API answers 429 `{"error": "daily_limit", "message": "daily free-tier limit reached; cached companies still work"}`. A cached snapshot is returned before any model call. A quota error does not advance the cursor and does not write a partial ledger. Each usage bucket records `model` and `models`.

This pass spent new verifier tokens on Infosys (7 calls, 6,929, preview) and HCLTech (5 calls, 3,592, Flash-Lite). Marico’s corrected verdict was 602 Flash-Lite tokens after `gemini-3.6-flash` and the preview had used the daily cap. Asian Paints, the demo set, and the snapshot rewrite were 0 tokens. 850 cache rows were copied to Supabase, including the `v2` quarters.

## 2026-11-11 — Ambiguous operating margin, latest guidance, borderline

Forcing “operating margin” onto EBIT was wrong when the passage does not define it. A quote that says EBITDA, EBIT, or PBDIT still uses that metric. A quote that says “operating margin” or “operating profit” and does not define it is read twice, once as EBITDA and once as EBIT. It is scored only when both readings have the same status. When they disagree the row is `not_scored`, reason `definition ambiguous`, and both readings stay on the row.

Infosys “operating margin guidance … 20% to 22%” disagrees, so neither year is scored. FY2026: EBIT 20.2% inside the 20–22% band; EBITDA 22.94% above it. H1 FY2027: EBIT 21.03% inside the band (on track); EBITDA 23.7% above it (ahead). The EBITDA figures are the same 22.94% and 23.70% from the previous pass.

For one company, one margin family (EBITDA, EBIT, operating margin), and one fiscal period, only the latest statement is scored. Earlier values are revisions marked `superseded`. Marico’s 30 Jan 2026 “operating margin … 150-200 basis points” is the earlier statement. Both readings were behind (+127 bps EBIT, +144 bps EBITDA), but it is not scored. The 11 Aug 2026 EBITDA margin of 140–150 bps stays scored, on track at +144 bps. The three Marico EBITDA and revenue rows are otherwise unchanged: +144 bps, revenue 16.51% ahead of at least 10%, EBITDA growth 25.76% ahead of 17–19%. Asian Paints is unchanged: FY2027 18.16% on track, FY2026 18.37% delivered, both still PBDIT read as EBITDA.

EBITDA and EBIT are derived, so a miss that is only a rounding away from the band is not called partly or missed. If the actual is within 60 bps of a band edge, the status is `borderline` and the definition note says the figure is derived. The stated window was 50 bps. HCLTech FY2026 is 16.44% against 17–18%, which is 56 bps under 17%, so a 50 bps window would still have said partly. The window is 60 bps so this row is borderline: “16.44% against 17–18%, 56 bps under the band.” FY2027 EBIT 17.52% against 17.5–18.5% stays on track. A growth range and a margin range in the same sentence stay with the words in front of them, so “2.5% to 4%” is not a revision of the EBIT band. Hindustan Unilever’s 22.5–23.5% line stays a long-term target.

The re-score used cached guidance and cached verdicts except HCLTech’s borderline verdict, 376 Flash-Lite tokens. The ledger scoring rules stop here.

## 2026-11-11 — Briefing orientation, signed moves, dark theme, ledger states

The briefing opens with a three-step sheet the first time, remembered after it is closed, and the menu can open it again. The menu also holds the 18-name portfolio filter (the feed `symbols` parameter), mover thresholds, data and method, and theme. Under the wordmark is one line on what the app does, then a count taken from the feed already on screen: results, deals, management changes, other filings, movers. The window still defaults to 72 hours. The first results card is the lead, with an accent border. A window shorter than 72 hours that has three filings or fewer says so and offers 72 hours.

A price move was stored as an absolute percent, so a fall looked like a rise. `signed_move_pct` is now beside `move_pct`. CG Power on 6 Nov 2026 is −4.43% on the live feed (`move_pct` stays 4.43). Movers show an arrow and a colour, and the volume caption says “vs 20-day avg”. The replay line is “Replay mode: showing 6 Nov 2026 so the demo stays stable.” Dates on the cards and the mover sheet include the year. A card shows the ticker once and the company name once. The mover sheet lists each filing by its time relative to the session and by the one-line summary, under “Filings around this move.”

Light stays the default: cream paper `#f3f1eb`, green `#1b5e45`. Dark is ink `#171611`, not black, with softened text `#e7e2d6` and the same green lifted to `#8fceb3`. Every colour is a CSS variable, including the fall and amber used for a down move and a borderline row. The choice follows the phone, and a manual choice is remembered. Contrast of ink, mute, accent, fall, and amber is above 4.5:1 on both paper and cards.

At 390×844 and 360×740, in both themes, the tab bar’s bottom edge sits on the viewport and nothing in the briefing overflows it. The bar already carries `padding-bottom: env(safe-area-inset-bottom)`. In this browser that inset is 0, so the padding computes to 0 and the labels sit on the bottom edge rather than past it.

The research tab now renders the statuses the ledger already returns. Delivered, tracking ahead, on track, tracking behind, partly, and missed stay grouped. Borderline is amber, shows the promised band and the actual, the definition note, and the line that the figure is derived and sits within about 60 bps of the band edge. A `definition ambiguous` row shows both readings (the note after that prefix) and one line on why it is not scored. A superseded number is only in the revisions timeline, labelled superseded. `definition_note` and the word-band reading sit on the row. Segment, low confidence, and long-term targets keep their own place, with the stored reason. A 429 `daily_limit` shows “Daily free-tier limit reached. Cached companies still work.” and buttons for MARICO, ASIANPAINT, TITAN, CGPOWER, DMART, PIDILITIND, and WIPRO. If that same company is already on screen, it stays. The model line (guidance, verification, verdict) is only in Data and method.

## 2026-11-11 — Briefing polish: intro sheet, compact results

Opening “How FINN works” showed only “1 of 3”. The sheet was a flex column with a max height and no definite height, so the body collapsed to one line, and the intro opened under the menu that was still closing. The sheet now scrolls as a whole, the header sticks, and the intro sits above that closing menu. First run and the menu reopen both show the title, the short description, and Next, Back, and Done, for all three steps, in light and dark, at 390×844.

A results card lays Revenue, EBITDA, PBT, and PAT out as a 2×2 grid. Each cell has the value and the QoQ and YoY chips. Tapping a cell opens the three bars, captioned “yr ago – prev qtr – now”. The lead Titan card, takeaway and source links included, fits on one phone screen under the header at 390×844 in both themes.

The line at the top is computed from the numbers on the card. Titan reads “Revenue +10.1% YoY, PAT +113.7% YoY. EBITDA margin 14.5%, +4.5 pts YoY.” A negative or zero base uses the existing wording, so Bharat Forge PAT quarter-on-quarter says “swung to profit”. A bank or NBFC with an EBITDA reason drops the EBITDA cell and the margin sentence. A QoQ or YoY change past ±100%, or a base at or below zero, adds “Large swing. Check for one-off items; derived EBITDA includes exceptional items.”

Source links are labelled by type: XBRL filing, Investor presentation, Outcome of board meeting PDF, or NSE filing. Two links of the same specific type collapse to one. Two generic NSE filings stay if their subjects differ. The date control shows “6 Nov 2026”.

No model call. `finn_core` is unchanged. The web app is what gets redeployed.

## 2026-11-11 — Company search, and a readable XBRL label

Research no longer calls NSE while someone is typing. `scripts/refresh_equities.py` downloads the official equity list, `EQUITY_L.csv` on nsearchives (the file linked from NSE's securities-available-for-trading page), and writes `web/src/data/equities.json`. The copy fetched on 11 Nov 2026 has 2,633 names: 2,397 EQ, 202 BE, 34 BZ. A short alias file maps the names people actually type: Zomato to ETERNAL, Bharat Seats to BHARATSE, Bajaj Auto to BAJAJ-AUTO, Mahindra to M&M. The listed symbol for Bharat Seats is BHARATSE.

The box takes a company name or a symbol. Suggestions read "Company name (SYMBOL)". A tap starts that ledger. Enter does the same when one match is clear. "Ltd" and the other company-form words are ignored, and a small misspelling still matches. Text that is not a listed symbol never calls the ledger. `M&M` goes out as `symbol=M%26M`. `BAJAJ-AUTO` keeps the hyphen.

The eight checks: "wipro" and "Wipro Ltd" are Wipro Limited (WIPRO). "pidilite" is Pidilite Industries Limited (PIDILITIND). "bajaj auto" is Bajaj Auto Limited (BAJAJ-AUTO). "zomato" is ETERNAL LIMITED (ETERNAL). "hind unilever" is Hindustan Unilever Limited (HINDUNILVR). "asian paint" is Asian Paints Limited (ASIANPAINT). "zzzzqqq" says "No listed company found" and offers Faze Three (FAZE3Q), A2Z Infra (A2ZINFRA) and Adani Ports (ADANIPORTS), with no ledger request.

The results-card link that used to say "XBRL filing" now says "XBRL data (raw, machine-readable)" and sits after the outcome PDF and the investor presentation. When that file is the only source, the card adds that it is not a page to read. On the 6 Nov replay both results cards still have the PDF and the presentation ahead of it.

Scoring is unchanged. The web app was redeployed: `dpl_32gEzEj7LvoFiZrZXWi88a6GLkxX` is Ready and aliased to https://web-eosin-ten-23.vercel.app.

## 2026-11-11 — Stable movers, quieter search, ledger prewarm

The 6 Nov, 72-hour feed with and without `move_pct=5` and `volume_n=2.5` is one cache key, `2026-11-06|72|5|2.5|*`. Both return the same eight movers, in this order: MARICO 3 Nov +10.0% (8.17×), BAJFINANCE 5 Nov +7.65% (3.45×), CGPOWER 6 Nov −4.43% (5.12×), TITAN 6 Nov +3.42% (5.55×), BHARATFORG 5 Nov −3.30% (4.75×), MARUTI 5 Nov +5.48% (2.59×), MARICO 4 Nov +1.32% (2.56×), SUNPHARMA 4 Nov +0.20% (2.80×). A fresh load of the web app requests that same URL. The initial state is 72 hours, 5%, and 2.5×.

The three movers on the phone are a second stored feed, written 11 Nov 2026 at 05:53 UTC, with the same day and the same 5% move and a volume multiple of 8. At 8× only three sessions remain, and they are the three price moves: MARICO 3 Nov, BAJFINANCE 5 Nov, MARUTI 5 Nov. The five volume-only chips drop, which is why the names differ. The summary counted `alerts.length` and the strip rendered that same list, so one response stays consistent. Two screenshots differed because they were two thresholds. The strip now says which threshold produced it (“Above 5% or 2.5× volume.”), and the settings sheet can return to those defaults. Alerts are ordered by severity, then symbol, then date, including when a stored feed is served. A cache miss for a pinned replay key serves `data/snapshot` instead of downloading prices again. A stored price series of 21 or more sessions is kept if a later download is shorter.

A query with no reasonable listed match shows only “No listed company found”. The nearest-name list is gone. “wipro” still offers Wipro Limited (WIPRO).

`scripts/prewarm.py` reads NSE’s Nifty 50 file (`ind_nifty50list.csv` on nsearchives, 50 names on 11 Nov 2026), adds the 18 portfolio names and DMART, ASIANPAINT, ETERNAL, PIDILITIND, and dedupes to 59. The official file has no size column, so the run starts with the large names and the names this project already tests, then the rest of the file, then the portfolio names that are outside the fifty. One ticker at a time, three seconds apart. A complete snapshot is skipped. A failed ticker does not replace one. `QuotaError` stops the run. Finished ledgers are also written under `data/snapshot` (42 files, 0.9 MB). Supabase holds 1,965 cache rows and 35.0 MB of payload JSON. The free database limit is 500 MB.

The run stopped on INDIGO when every provider returned the daily limit, after one guidance stage (11,944 tokens). That ledger was not saved as complete. Seventeen names were not started: JSWSTEEL, JIOFIN, MAXHEALTH, NESTLEIND, ONGC, POWERGRID, SBILIFE, SHRIRAMFIN, TATACONSUM, TMPV, TATASTEEL, TECHM, BHARATFORG, PERSISTENT, POLYCAB, DIXON, BHARATSEATS. A later run skips the finished ones. Each `promise_ledger` call resets its token counter, so the printed token column is the last stage. The stage lines sum to 595,421 tokens. New scored rows: TCS 1, BEL 3, CIPLA 3, DRREDDY 1. The stored ones were left as they were: MARICO 3, HCLTECH 2, ASIANPAINT 2. Scoring rules were not changed.

| Symbol | Status | Scored | Seconds | Models |
|---|---|---:|---:|---|
| RELIANCE | complete | 0 | 67.0 | gemini-3.5-flash-lite |
| TCS | complete | 1 | 86.9 | gemini-3.5-flash-lite, gemini-3-flash-preview, gemini-3.6-flash |
| HDFCBANK | skipped | 0 | 0 | gemini-3.5-flash-lite |
| BHARTIARTL | complete | 0 | 58.4 | gemini-3.5-flash-lite |
| ICICIBANK | complete | 0 | 58.4 | gemini-3.5-flash-lite |
| INFY | skipped | 0 | 0 | gemini-3.5-flash-lite |
| SBIN | complete | 0 | 3.5 | gemini-3.5-flash-lite |
| HINDUNILVR | complete | 0 | 2.7 | gemini-3.5-flash-lite |
| ITC | complete | 0 | 21.3 | |
| LT | complete | 0 | 47.9 | gemini-3.5-flash-lite |
| BAJFINANCE | complete | 0 | 69.6 | gemini-3.5-flash-lite |
| HCLTECH | skipped | 2 | 0 | gemini-3.5-flash-lite |
| MARUTI | complete | 0 | 51.4 | gemini-3.5-flash-lite |
| SUNPHARMA | complete | 0 | 49.9 | gemini-3.5-flash-lite |
| AXISBANK | complete | 0 | 49.7 | gemini-3.5-flash-lite |
| TITAN | skipped | 0 | 0 | gemini-3.5-flash-lite |
| ASIANPAINT | skipped | 2 | 0 | gemini-3.5-flash-lite, gemini-3-flash-preview |
| DMART | skipped | 0 | 0 | gemini-3.5-flash-lite |
| MARICO | skipped | 3 | 0 | gemini-3.5-flash-lite, gemini-3-flash-preview |
| PIDILITIND | skipped | 0 | 0 | gemini-3.5-flash-lite |
| CGPOWER | skipped | 0 | 0 | gemini-3.5-flash-lite |
| ETERNAL | complete | 0 | 63.8 | gemini-3.5-flash-lite |
| M&M | complete | 0 | 82.1 | gemini-3.5-flash-lite |
| BAJAJ-AUTO | complete | 0 | 3.7 | gemini-3.5-flash-lite |
| KOTAKBANK | complete | 0 | 34.2 | gemini-3.5-flash-lite |
| NTPC | complete | 0 | 63.5 | gemini-3.5-flash-lite |
| ULTRACEMCO | complete | 0 | 3.9 | gemini-3.5-flash-lite |
| TRENT | complete | 0 | 18.3 | |
| BEL | complete | 3 | 91.3 | gemini-3.5-flash-lite, gemini-3-flash-preview |
| ADANIENT | complete | 0 | 46.3 | gemini-3.5-flash-lite |
| ADANIPORTS | complete | 0 | 47.6 | gemini-3.5-flash-lite |
| APOLLOHOSP | complete | 0 | 43.8 | gemini-3.5-flash-lite |
| BSE | complete | 0 | 50.6 | gemini-3.5-flash-lite |
| BAJAJFINSV | complete | 0 | 56.7 | gemini-3.5-flash-lite |
| CIPLA | complete | 3 | 77.4 | gemini-3.5-flash-lite |
| COALINDIA | complete | 0 | 24.7 | gemini-3.5-flash-lite |
| DRREDDY | complete | 1 | 73.6 | gemini-3.5-flash-lite |
| EICHERMOT | complete | 0 | 85.9 | gemini-3.5-flash-lite |
| GRASIM | complete | 0 | 90.3 | gemini-3.5-flash-lite |
| HDFCLIFE | complete | 0 | 46.7 | gemini-3.5-flash-lite |
| HINDALCO | complete | 0 | 79.1 | gemini-3.5-flash-lite |
| INDIGO | quota | | | |

The API is `dpl_5fUGLvfZFq3wPzJohWxK6U1xnFBD`, Ready, aliased to https://finn-r4y3.vercel.app. The web app is `dpl_6TCRaEawsuRtAzYVAwKh2Pnvwia1`, Ready, aliased to https://web-eosin-ten-23.vercel.app. The default feed still returns those eight movers.

## Morning refresh, live briefing, numbers at a glance

Scoring rules were not changed.

`/api/cron/daily` is on the API project. Vercel runs it at `30 3 * * *`, which is 09:00 IST. The caller must send `Authorization: Bearer` matching `CRON_SECRET`. A missing or wrong token is 401. The handler reads and writes one heartbeat row so the free Supabase project stays awake, then collects announcements once for the 18 portfolio names and stores today's 24h and 72h feeds at the default 5% and 2.5× thresholds. The phone's Live view reads those stored feeds and does not rebuild them. A first cold attempt hit the 60-second limit before either window was saved. The job now does one sweep, with a 0.4s gap between exchange calls, and stores the 72h feed before it assembles 24h from the same filings. The proof call returned 200 in 15.1 seconds: heartbeat `2026-11-11T14:46:37+05:30`, 72h stored with 2 cards, 0 alerts and 5 routine companies, 24h stored and empty. Token count was 0 because those summaries were already cached.

The briefing opens on Replay (6 Nov 2026). Live is today. One line under the switch says what each does. On a phone, Live 72h showed the Bajaj Finance warrant allotment and the L&T metro order, and no mover past the threshold. Live 24h said nothing was filed and offered the replay. Live 7 days said that window has not been refreshed and offered the replay.

At a glance sits above the guidance on Research. It is arithmetic on the six-quarter series already on the ledger, with no model call. EBITDA is labelled derived. MARICO: revenue up 11.9% and the six quarters rising, derived EBITDA margin 211 bps higher and expanding, PAT up 31.0%, no loss quarter and no move past 100%. CGPOWER: the series is incomplete for the quarters ended 30 Sep 2025 and 30 Jun 2025, so revenue, derived EBITDA margin, and PAT are not compared with a year ago. The quarters that have revenue are rising. No loss quarter.

The API is `dpl_5yXmUobKX5fpfWiw5HLdxCXyhArH`, Ready, aliased to https://finn-r4y3.vercel.app. The web app is `dpl_8VQni181rzDaWeG14AKaA8mgT8pC`, Ready, aliased to https://web-eosin-ten-23.vercel.app.
