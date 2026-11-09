"""One-shot datacenter probe. No env vars and no Gemini key."""

import json
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler

import requests

HTTP_TIMEOUT = 8
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
BSE_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.bseindia.com",
    "Referer": "https://www.bseindia.com/",
}
NSE_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
    "Connection": "keep-alive",
}
SCREENER_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-IN,en;q=0.9",
}


def _fail(exc: Exception) -> dict:
    return {
        "status": None,
        "ok": False,
        "rows": 0,
        "bytes": 0,
        "error": f"{type(exc).__name__}: {exc}"[:180],
    }


def probe_bse() -> dict:
    end = date.today()
    start = end - timedelta(days=7)
    response = requests.get(
        "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w",
        params={
            "pageno": 1,
            "strCat": "-1",
            "strPrevDate": start.strftime("%Y%m%d"),
            "strScrip": "500325",
            "strSearch": "P",
            "strToDate": end.strftime("%Y%m%d"),
            "strType": "C",
            "subcategory": "-1",
        },
        headers=BSE_HEADERS,
        timeout=HTTP_TIMEOUT,
    )
    table = None
    if response.status_code == 200:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("Table"), list):
            table = payload["Table"]
    return {
        "status": response.status_code,
        "ok": table is not None,
        "rows": len(table) if table is not None else 0,
        "bytes": len(response.content),
    }


def probe_nse() -> dict:
    end = date.today()
    start = end - timedelta(days=7)
    session = requests.Session()
    session.headers.update(NSE_HEADERS)
    home = session.get("https://www.nseindia.com/", timeout=HTTP_TIMEOUT)
    session.headers["Accept"] = "application/json, text/plain, */*"
    session.headers["Referer"] = "https://www.nseindia.com/"
    response = session.get(
        "https://www.nseindia.com/api/corporate-announcements",
        params={
            "index": "equities",
            "symbol": "RELIANCE",
            "from_date": start.strftime("%d-%m-%Y"),
            "to_date": end.strftime("%d-%m-%Y"),
        },
        timeout=HTTP_TIMEOUT,
    )
    rows = None
    if response.status_code == 200:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            found = payload.get("data") if "data" in payload else payload.get("rows")
            if isinstance(found, list):
                rows = found
    return {
        "status": response.status_code,
        "ok": rows is not None,
        "rows": len(rows) if rows is not None else 0,
        "bytes": len(response.content),
        "homepage_status": home.status_code,
    }


def probe_screener() -> dict:
    response = requests.get(
        "https://www.screener.in/company/RELIANCE/consolidated/",
        headers=SCREENER_HEADERS,
        timeout=HTTP_TIMEOUT,
        allow_redirects=True,
    )
    body = response.content
    lowered = body.lower()
    rows = lowered.count(b'class="documents') + lowered.count(b"class='documents")
    return {
        "status": response.status_code,
        "ok": response.status_code == 200 and b"documents" in lowered,
        "rows": rows,
        "bytes": len(body),
    }


def probe_price() -> dict:
    import socket

    import yfinance as yf

    end = date.today() + timedelta(days=1)
    start = date.today() - timedelta(days=30)
    socket.setdefaulttimeout(12)
    frame = yf.download(
        "RELIANCE.NS",
        start=start.isoformat(),
        end=end.isoformat(),
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    rows = 0 if frame is None or frame.empty else int(len(frame))
    return {"status": None, "ok": rows > 0, "rows": rows, "bytes": None}


def _run(fn) -> dict:
    try:
        return fn()
    except Exception as exc:
        return _fail(exc)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        payload = {
            "bse": _run(probe_bse),
            "nse": _run(probe_nse),
            "screener": _run(probe_screener),
            "yfinance": _run(probe_price),
        }
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return
