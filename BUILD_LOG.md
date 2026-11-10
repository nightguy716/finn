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
