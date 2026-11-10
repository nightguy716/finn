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
