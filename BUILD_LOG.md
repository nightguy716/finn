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
