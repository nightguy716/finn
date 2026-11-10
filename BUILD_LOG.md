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
