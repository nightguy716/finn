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
