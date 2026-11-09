"""Last 7 days of BSE corporate announcements for RELIANCE, MARICO, CGPOWER.

Public JSON only. One scrip-code lookup per name, then one announcements page.
"""

import json
import re
import time
from datetime import date, timedelta
from html import unescape

import requests

TICKERS = ["RELIANCE", "MARICO", "CGPOWER"]
PAUSE_S = 2.0
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.bseindia.com",
    "Referer": "https://www.bseindia.com/",
}
PREFIXES = (
    "https://www.bseindia.com/xml-data/corpfiling/AttachLive/",
    "https://www.bseindia.com/xml-data/corpfiling/AttachHis/",
)


def get_json(session: requests.Session, url: str, params: dict) -> tuple[int, object | None, str]:
    response = session.get(url, params=params, timeout=30)
    text = response.text[:400].replace("\n", " ")
    try:
        return response.status_code, response.json(), text
    except ValueError:
        return response.status_code, None, text


def lookup_scrip(session: requests.Session, ticker: str) -> dict:
    url = "https://api.bseindia.com/BseIndiaAPI/api/PeerSmartSearch/w"
    status, payload, snippet = get_json(session, url, {"Type": "SS", "text": ticker})
    print(f"lookup {ticker}: HTTP {status}")
    if status != 200 or not isinstance(payload, str):
        print(f"lookup blocked or unexpected: {snippet}")
        return {}
    found = []
    for code, name, span in re.findall(
        r"liclick\('(\d+)','([^']*)'\).*?<span>(.*?)</span>", payload, flags=re.S
    ):
        plain = re.sub(r"<[^>]+>", " ", unescape(span)).replace("\xa0", " ")
        parts = plain.split()
        symbol = parts[0] if parts else ""
        found.append({"code": code, "name": unescape(name), "symbol": symbol})
    exact = [row for row in found if row["symbol"].upper() == ticker]
    print(f"lookup hits {len(found)} exact {len(exact)}")
    if not exact:
        print("candidates:", json.dumps(found[:6], ensure_ascii=False))
        return {}
    chosen = exact[0]
    print(f"chosen scrip {chosen['code']} {chosen['name']} symbol {chosen['symbol']}")
    return chosen


def pdf_url(session: requests.Session, filename: str, cache: dict) -> str:
    if not filename:
        return ""
    if str(filename).startswith("http"):
        return str(filename)
    if "prefix" in cache:
        return cache["prefix"] + filename
    for prefix in PREFIXES:
        url = prefix + filename
        probe = session.get(url, headers={"Range": "bytes=0-15"}, timeout=30, stream=True)
        chunk = next(probe.iter_content(16), b"")
        ok = probe.status_code in (200, 206) and chunk.startswith(b"%PDF")
        print(f"attachment probe {probe.status_code} pdf {ok} {url[:90]}")
        probe.close()
        time.sleep(PAUSE_S)
        if ok:
            cache["prefix"] = prefix
            return url
    return PREFIXES[0] + filename


def announcements(session: requests.Session, code: str, start: date, end: date) -> tuple[str, list]:
    params = {
        "pageno": 1,
        "strCat": "-1",
        "strPrevDate": start.strftime("%Y%m%d"),
        "strScrip": code,
        "strSearch": "P",
        "strToDate": end.strftime("%Y%m%d"),
        "strType": "C",
        "subcategory": "-1",
    }
    for path in ("AnnSubCategoryGetData/w", "AnnGetData/w"):
        url = f"https://api.bseindia.com/BseIndiaAPI/api/{path}"
        status, payload, snippet = get_json(session, url, params)
        print(f"{path} HTTP {status}")
        if status != 200 or not isinstance(payload, dict):
            print(f"non-json or blocked: {snippet}")
            continue
        table = payload.get("Table")
        if isinstance(table, list):
            if table:
                print(f"row keys: {sorted(table[0].keys())}")
            return path, table
        print(f"no Table: {snippet}")
    return "", []


def field(row: dict, *names: str, iso_t: bool = False) -> str:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            text = str(value)
            return text.replace("T", " ") if iso_t else text
    return ""


def main() -> None:
    end = date.today()
    start = end - timedelta(days=7)
    print(f"window {start.isoformat()} .. {end.isoformat()}")
    session = requests.Session()
    session.headers.update(HEADERS)
    prefix_cache: dict = {}
    for ticker in TICKERS:
        print(f"\n=== {ticker} ===")
        found = lookup_scrip(session, ticker)
        time.sleep(PAUSE_S)
        code = found.get("code") or ""
        if not code:
            print("no scrip code")
            continue
        path, rows = announcements(session, code, start, end)
        print(f"endpoint {path or 'none'} count {len(rows)}")
        shown = rows[:10]
        for row in shown:
            filename = field(row, "ATTACHMENTNAME", "ATTACHMENT")
            link = pdf_url(session, filename, prefix_cache) if filename else ""
            print(
                json.dumps(
                    {
                        "headline": field(row, "NEWSSUB", "HEADLINE", "More"),
                        "category": field(row, "CATEGORYNAME", "CATEGORY"),
                        "subcategory": field(row, "SUBCATNAME"),
                        "timestamp": field(row, "News_submission_dt", "DissemDT", "DT_TM", "NEWS_DT", iso_t=True),
                        "pdf": link,
                    },
                    ensure_ascii=False,
                )
            )
        if len(rows) > len(shown):
            print(f"... {len(rows) - len(shown)} more not printed")
        time.sleep(PAUSE_S)


if __name__ == "__main__":
    main()
