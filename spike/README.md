These scripts are the feasibility study. They are not on the request path.

- `01_prices.py` — thirty days of NSE close and volume from Yahoo Finance.
- `02_bse_announcements.py` — BSE corporate announcements. The datacenter call does not succeed, which is why the live app uses NSE.
- `03_nse_announcements.py` — a week of NSE corporate announcements.
- `04_screener.py` — public screener.in links to annual reports and concalls.
- `05_documents.py` — one results PDF and one transcript.
- `06_gemini.py` — which Gemini models the free key can see, and one short call.
- `probe_server.py` — the same sources from a datacenter address, the check that decided the host.
