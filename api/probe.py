"""Datacenter probe for BSE, NSE, Screener, and one company-IR PDF.

No environment secrets are read. VERCEL_REGION is the platform region name.
"""

import json
import os
import re
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler
from urllib.parse import urljoin, urlparse

import requests

HTTP_TIMEOUT = 10
REGION = os.environ.get("VERCEL_REGION") or "unknown"
TICKERS = ("RELIANCE", "CGPOWER")
# Scrip codes confirmed by the laptop spike's BSE symbol search.
SCRIPS = {"RELIANCE": "500325", "CGPOWER": "500093"}
EXCHANGE_HOSTS = (
    "bseindia.com",
    "nseindia.com",
    "nsearchives.nseindia.com",
    "screener.in",
    "youtube.com",
    "youtu.be",
)
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
PDF_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/pdf,*/*",
    "Accept-Language": "en-IN,en;q=0.9",
}


def base(status, ok, nbytes):
    return {"status": status, "ok": bool(ok), "bytes": nbytes, "region": REGION}


def failed(exc: Exception) -> dict:
    row = base(None, False, 0)
    row["error"] = f"{type(exc).__name__}: {exc}"[:180]
    return row


def window():
    end = date.today()
    return end - timedelta(days=7), end


def bse_call(scrip: str):
    start, end = window()
    response = requests.get(
        "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w",
        params={
            "pageno": 1,
            "strCat": "-1",
            "strPrevDate": start.strftime("%Y%m%d"),
            "strScrip": scrip,
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
    pdf = ""
    if table:
        for row in table:
            name = str(row.get("ATTACHMENTNAME") or "")
            if name:
                pdf = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/" + name
                break
    meta = base(response.status_code, table is not None, len(response.content))
    meta["rows"] = len(table) if table is not None else 0
    return meta, pdf


def range_pdf(session: requests.Session, url: str, headers: dict) -> dict:
    if not url:
        row = base(None, False, 0)
        row["error"] = "no pdf link"
        return row
    merged = dict(headers)
    merged["Range"] = "bytes=0-15"
    response = session.get(url, headers=merged, timeout=HTTP_TIMEOUT, stream=True)
    chunk = b""
    try:
        for part in response.iter_content(16):
            if not part:
                continue
            chunk += part
            if len(chunk) >= 16:
                break
    finally:
        response.close()
    prefix = chunk[:16]
    advertised = response.headers.get("Content-Length")
    nbytes = int(advertised) if advertised and advertised.isdigit() else len(prefix)
    is_pdf = prefix.startswith(b"%PDF")
    row = base(response.status_code, response.status_code in (200, 206) and is_pdf, nbytes)
    row["host"] = urlparse(url).netloc
    return row


def nse_session():
    session = requests.Session()
    session.headers.update(NSE_HEADERS)
    home_status = None
    home_error = ""
    try:
        home = session.get("https://www.nseindia.com/", timeout=HTTP_TIMEOUT)
        home_status = home.status_code
    except Exception as exc:
        home_error = f"{type(exc).__name__}: {exc}"[:180]
    session.headers["Accept"] = "application/json, text/plain, */*"
    session.headers["Referer"] = "https://www.nseindia.com/"
    return session, home_status, home_error


def nse_call(session: requests.Session, symbol: str):
    start, end = window()
    response = session.get(
        "https://www.nseindia.com/api/corporate-announcements",
        params={
            "index": "equities",
            "symbol": symbol,
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
    pdf = ""
    if rows:
        for row in rows:
            link = str(row.get("attchmntFile") or "")
            if link.startswith("http"):
                pdf = link
                break
    meta = base(response.status_code, rows is not None, len(response.content))
    meta["rows"] = len(rows) if rows is not None else 0
    return meta, pdf


def screener_page(symbol: str):
    url = f"https://www.screener.in/company/{symbol}/consolidated/"
    response = requests.get(url, headers=SCREENER_HEADERS, timeout=HTTP_TIMEOUT, allow_redirects=True)
    body = response.content
    lowered = body.lower()
    meta = base(response.status_code, response.status_code == 200 and b"documents" in lowered, len(body))
    meta["rows"] = lowered.count(b'class="documents') + lowered.count(b"class='documents")
    link = ""
    fallback = ""
    if response.status_code == 200:
        for href in re.findall(r'href=["\']([^"\']+)["\']', response.text, flags=re.I):
            absolute = urljoin(response.url, href)
            if ".pdf" not in absolute.lower():
                continue
            host = urlparse(absolute).netloc.lower()
            if not host or any(blocked in host for blocked in EXCHANGE_HOSTS):
                continue
            if not fallback:
                fallback = absolute
            if any(word in absolute.lower() for word in ("transcript", "concall", "annual")):
                link = absolute
                break
    return meta, link or fallback


def yfinance_probe() -> dict:
    import socket

    import yfinance as yf

    end = date.today() + timedelta(days=1)
    start = date.today() - timedelta(days=30)
    socket.setdefaulttimeout(12)
    out = {}
    for symbol in TICKERS:
        frame = yf.download(
            f"{symbol}.NS",
            start=start.isoformat(),
            end=end.isoformat(),
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
        )
        rows = 0 if frame is None or getattr(frame, "empty", True) else int(len(frame))
        item = base(None, rows > 0, None)
        item["rows"] = rows
        out[symbol] = item
    return out


def run(fn):
    try:
        return fn()
    except Exception as exc:
        return failed(exc)


def build() -> dict:
    bse = {}
    bse_pdf = {}
    bse_links = {}
    for symbol in TICKERS:
        try:
            meta, link = bse_call(SCRIPS[symbol])
            bse[symbol] = meta
            bse_links[symbol] = link
        except Exception as exc:
            bse[symbol] = failed(exc)
            bse_links[symbol] = ""
    session = requests.Session()
    for symbol, link in bse_links.items():
        try:
            bse_pdf[symbol] = range_pdf(session, link, BSE_HEADERS)
        except Exception as exc:
            bse_pdf[symbol] = failed(exc)

    nse_session_obj, home_status, home_error = nse_session()
    nse_repeat = {"homepage_status": home_status, "region": REGION}
    if home_error:
        nse_repeat["homepage_error"] = home_error
    nse_links = {}
    for symbol in TICKERS:
        tries = []
        pdf = ""
        for _ in range(3):
            try:
                meta, link = nse_call(nse_session_obj, symbol)
            except Exception as exc:
                meta, link = failed(exc), ""
            tries.append(meta)
            if link and not pdf:
                pdf = link
        nse_links[symbol] = pdf
        nse_repeat[symbol] = {
            "region": REGION,
            "succeeded": sum(1 for item in tries if item.get("ok")),
            "tries": tries,
        }

    nse_pdf = {}
    for symbol, link in nse_links.items():
        try:
            nse_pdf[symbol] = range_pdf(nse_session_obj, link, dict(nse_session_obj.headers))
        except Exception as exc:
            nse_pdf[symbol] = failed(exc)

    screener = {}
    ir_pdf = {}
    ir_session = requests.Session()
    for symbol in TICKERS:
        try:
            meta, link = screener_page(symbol)
            screener[symbol] = meta
        except Exception as exc:
            screener[symbol] = failed(exc)
            link = ""
        try:
            ir_pdf[symbol] = range_pdf(ir_session, link, PDF_HEADERS)
        except Exception as exc:
            ir_pdf[symbol] = failed(exc)

    return {
        "region": REGION,
        "bse": bse,
        "bse_pdf": bse_pdf,
        "nse_repeat": nse_repeat,
        "nse_pdf": nse_pdf,
        "screener": screener,
        "ir_pdf": ir_pdf,
        "yfinance": run(yfinance_probe),
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            payload = build()
        except Exception as exc:
            payload = failed(exc)
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return
