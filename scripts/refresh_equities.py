"""Refresh the static NSE equity list used by Research search.

The app does not call NSE while someone types. This script downloads the
official equity list once and writes web/src/data/equities.json.

Source: https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv
(the file linked from NSE's "Securities available for trading" page).
"""

import csv
import io
import json
from collections import Counter
from datetime import date
from pathlib import Path

import requests

SOURCE = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "src" / "data" / "equities.json"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def cell(row: dict, name: str) -> str:
    for key, value in row.items():
        if key.strip() == name:
            return (value or "").strip()
    return ""


def main() -> None:
    response = requests.get(SOURCE, timeout=30, headers={"User-Agent": UA})
    response.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    companies = []
    series = Counter()
    seen = set()
    for row in rows:
        symbol = cell(row, "SYMBOL")
        name = cell(row, "NAME OF COMPANY")
        kind = cell(row, "SERIES")
        if not symbol or not name or symbol in seen:
            continue
        seen.add(symbol)
        series[kind or "?"] += 1
        companies.append([symbol, name])
    companies.sort(key=lambda item: item[0])
    meta = {
        "source": SOURCE,
        "fetched": date.today().isoformat(),
        "series": dict(sorted(series.items())),
        "count": len(companies),
    }
    lines = ["{"]
    for key, value in meta.items():
        lines.append(f"  {json.dumps(key)}: {json.dumps(value, ensure_ascii=False)},")
    lines.append('  "companies": [')
    for symbol, name in companies:
        lines.append(f"    {json.dumps([symbol, name], ensure_ascii=False)},")
    lines[-1] = lines[-1].rstrip(",")
    lines.append("  ]")
    lines.append("}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {len(companies)} companies to {OUT.relative_to(ROOT)}")
    print("series", dict(series))


if __name__ == "__main__":
    main()
