"""Last 7 days of NSE corporate announcements.

Warms a session from the public homepage, then calls the public JSON feed.
Stops and reports blocked on 401/403. Does not retry past a block.
"""

import json
import time
from datetime import date, timedelta

import requests

TICKERS = ["RELIANCE", "MARICO", "CGPOWER"]
PAUSE_S = 2.0
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
    "Connection": "keep-alive",
}


def main() -> None:
    end = date.today()
    start = end - timedelta(days=7)
    print(f"window {start.strftime('%d-%m-%Y')} .. {end.strftime('%d-%m-%Y')}")
    session = requests.Session()
    session.headers.update(HEADERS)
    home = session.get("https://www.nseindia.com/", timeout=30)
    print(f"homepage HTTP {home.status_code} cookie_names {list(session.cookies.keys())}")
    if home.status_code in (401, 403):
        print("BLOCKED at homepage. No further NSE calls.")
        return
    time.sleep(PAUSE_S)
    session.headers["Accept"] = "application/json, text/plain, */*"
    session.headers["Referer"] = "https://www.nseindia.com/"
    for symbol in TICKERS:
        print(f"\n=== {symbol} ===")
        response = session.get(
            "https://www.nseindia.com/api/corporate-announcements",
            params={
                "index": "equities",
                "symbol": symbol,
                "from_date": start.strftime("%d-%m-%Y"),
                "to_date": end.strftime("%d-%m-%Y"),
            },
            timeout=30,
        )
        print(f"announcements HTTP {response.status_code} bytes {len(response.content)}")
        if response.status_code in (401, 403):
            print("BLOCKED. Body starts:", response.text[:180].replace("\n", " "))
            print("Stopping NSE calls.")
            return
        try:
            payload = response.json()
        except ValueError:
            print("non-json:", response.text[:180].replace("\n", " "))
            time.sleep(PAUSE_S)
            continue
        rows = payload if isinstance(payload, list) else payload.get("data") or payload.get("rows") or []
        if isinstance(payload, dict) and not rows:
            print(f"dict keys {list(payload.keys())[:12]}")
        print(f"count {len(rows) if isinstance(rows, list) else 'n/a'}")
        if isinstance(rows, list) and rows:
            print(f"row keys: {sorted(rows[0].keys())}")
            for row in rows[:10]:
                print(
                    json.dumps(
                        {
                            "headline": row.get("desc"),
                            "timestamp": row.get("an_dt") or row.get("sort_date"),
                            "pdf": row.get("attchmntFile"),
                            "industry": row.get("smIndustry"),
                        },
                        ensure_ascii=False,
                    )
                )
            if len(rows) > 10:
                print(f"... {len(rows) - 10} more not printed")
        time.sleep(PAUSE_S)


if __name__ == "__main__":
    main()
