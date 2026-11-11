"""NSE corporate announcements and integrated financial results.

The Mumbai probe got HTTP 200 from the API when the homepage returned 403,
so a failed homepage does not abort the announcements call.
"""

import time
from datetime import date, datetime

import requests

HOME = "https://www.nseindia.com/"
ANNOUNCEMENTS = "https://www.nseindia.com/api/corporate-announcements"
# Current quarterly financials. The older corporates-financial-results feed
# still answers, but its symbol query stops before this results season.
INTEGRATED_RESULTS = "https://www.nseindia.com/api/integrated-filing-results"
ANNUAL_REPORTS = "https://www.nseindia.com/api/annual-reports"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
HOME_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
    "Connection": "keep-alive",
}


class NSEError(RuntimeError):
    def __init__(self, symbol: str, status: int | None, detail: str):
        self.symbol = symbol
        self.status = status
        super().__init__(f"{symbol}: HTTP {status} {detail[:160]}")


class NSEClient:
    def __init__(self, min_interval: float = 1.25, max_retries: int = 3, cache=None):
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.cache = cache
        self._session: requests.Session | None = None
        self._last = 0.0

    def _wait(self) -> None:
        elapsed = time.monotonic() - self._last
        if self._last and elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last = time.monotonic()

    def _open_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update(HOME_HEADERS)
        try:
            session.get(HOME, timeout=20)
        except requests.RequestException:
            pass
        session.headers["Accept"] = "application/json, text/plain, */*"
        session.headers["Referer"] = HOME
        self._session = session
        self._last = time.monotonic()
        return session

    def get_announcements(self, symbol: str, start: date, end: date) -> list[dict]:
        key_start = start.isoformat()
        key_end = end.isoformat()
        if self.cache is not None:
            cached = self.cache.get("nse_announcements", symbol, key_start, key_end)
            if cached is not None:
                return cached
        rows = self._fetch(symbol, start, end)
        if self.cache is not None:
            self.cache.put("nse_announcements", symbol, key_start, key_end, rows)
        return rows

    def get_financial_results(self, symbol: str, start: date, end: date) -> list[dict]:
        """Integrated Filing financials whose broadcast date falls in the window.

        One row per period, preferring the consolidated original. Governance
        filings on the same endpoint are dropped.
        """
        key_start = start.isoformat()
        key_end = end.isoformat()
        if self.cache is not None:
            cached = self.cache.get("nse_integrated_results", symbol, key_start, key_end)
            if cached is not None:
                return cached
        raw = self._request(
            symbol,
            INTEGRATED_RESULTS,
            {"index": "equities", "symbol": symbol, "period": "Quarterly"},
        )
        rows = []
        for row in _choose_financials(raw):
            when = _broadcast_date(str(row.get("broadcast_Date") or ""))
            if when is None or not (start <= when <= end):
                continue
            rows.append(_financial(symbol, row))
        if self.cache is not None:
            self.cache.put("nse_integrated_results", symbol, key_start, key_end, rows)
        return rows

    def get_annual_reports(self, symbol: str) -> list[dict]:
        """Annual-report PDFs from /api/annual-reports. Newest submission first."""
        year = str(date.today().year)
        if self.cache is not None:
            cached = self.cache.get("nse_annual_reports", symbol, year, "v1")
            if cached is not None:
                return cached
        raw = self._request(symbol, ANNUAL_REPORTS, {"index": "equities", "symbol": symbol})
        rows = []
        for row in raw:
            if not isinstance(row, dict):
                continue
            url = _usable_url(row.get("fileName"))
            if not url:
                continue
            rows.append(
                {
                    "from_year": str(row.get("fromYr") or ""),
                    "to_year": str(row.get("toYr") or ""),
                    "url": url,
                    "timestamp": str(row.get("broadcast_dttm") or row.get("disseminationDateTime") or ""),
                }
            )
        rows.sort(key=lambda row: (row["to_year"], row["timestamp"]), reverse=True)
        if self.cache is not None:
            self.cache.put("nse_annual_reports", symbol, year, "v1", rows)
        return rows

    def _fetch(self, symbol: str, start: date, end: date) -> list[dict]:
        params = {
            "index": "equities",
            "symbol": symbol,
            "from_date": start.strftime("%d-%m-%Y"),
            "to_date": end.strftime("%d-%m-%Y"),
        }
        raw = self._request(symbol, ANNOUNCEMENTS, params)
        return [_normalise(symbol, row) for row in raw]

    def _request(self, symbol: str, url: str, params: dict) -> list:
        last_status = None
        last_detail = ""
        for attempt in range(self.max_retries):
            if self._session is None or attempt:
                self._open_session()
            self._wait()
            try:
                response = self._session.get(url, params=params, timeout=25)
            except requests.RequestException as exc:
                last_status = None
                last_detail = str(exc)
                time.sleep(2 ** attempt)
                self._session = None
                continue
            last_status = response.status_code
            if response.status_code in (403, 429, 500, 502, 503):
                last_detail = response.text[:120].replace("\n", " ")
                time.sleep(2 ** attempt)
                self._session = None
                continue
            if response.status_code != 200:
                raise NSEError(symbol, response.status_code, response.text[:120].replace("\n", " "))
            try:
                payload = response.json()
            except ValueError as exc:
                raise NSEError(symbol, response.status_code, f"non-json {exc}") from exc
            return _rows(payload)
        raise NSEError(symbol, last_status, last_detail or "retries exhausted")

    def get_bytes(self, url: str, symbol: str = "") -> bytes:
        """Download an NSE archive file with the same session and backoff as the JSON calls."""
        last_status = None
        last_detail = ""
        for attempt in range(self.max_retries):
            if self._session is None or attempt:
                self._open_session()
            self._wait()
            try:
                response = self._session.get(url, headers={"Accept": "*/*"}, timeout=90)
            except requests.RequestException as exc:
                last_status = None
                last_detail = str(exc)
                time.sleep(2 ** attempt)
                self._session = None
                continue
            last_status = response.status_code
            if response.status_code in (403, 429, 500, 502, 503):
                last_detail = response.text[:120].replace("\n", " ")
                time.sleep(2 ** attempt)
                self._session = None
                continue
            if response.status_code != 200 or not response.content:
                raise NSEError(symbol or url, response.status_code, response.text[:120].replace("\n", " "))
            body = response.content
            expected = int(response.headers.get("Content-Length") or 0)
            if expected and len(body) + 100 < expected:
                last_detail = "short body"
                time.sleep(2 ** attempt)
                self._session = None
                continue
            if body.startswith(b"%PDF") and body.rfind(b"%%EOF") < len(body) - 2048:
                last_detail = "truncated pdf"
                time.sleep(2 ** attempt)
                self._session = None
                continue
            return body
        raise NSEError(symbol or url, last_status, last_detail or "retries exhausted")


def _rows(payload) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        found = payload.get("data") if "data" in payload else payload.get("rows")
        if isinstance(found, list):
            return found
    return []


def _normalise(symbol: str, row: dict) -> dict:
    return {
        "symbol": row.get("symbol") or symbol,
        "subject": str(row.get("desc") or ""),
        "text": str(row.get("attchmntText") or ""),
        "pdf_url": str(row.get("attchmntFile") or ""),
        "timestamp": str(row.get("an_dt") or row.get("sort_date") or ""),
    }


def _choose_financials(rows: list) -> list[dict]:
    """One financials row per period. Consolidated beats standalone."""
    groups: dict[str, list[dict]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if "financial" not in str(row.get("type") or "").lower():
            continue
        groups.setdefault(str(row.get("qe_Date") or ""), []).append(row)
    chosen = []
    for group in groups.values():
        consolidated = [row for row in group if str(row.get("consolidated") or "").lower() == "consolidated"]
        pool = consolidated or group
        pool.sort(key=lambda row: _broadcast_sort(str(row.get("broadcast_Date") or "")), reverse=True)
        chosen.append(pool[0])
    return chosen


def _financial(symbol: str, row: dict) -> dict:
    consolidated = str(row.get("consolidated") or "").strip()
    audited = str(row.get("audited") or "").strip()
    period = str(row.get("qe_Date") or "").strip()
    parts = ["Financial Results", consolidated, audited]
    if period:
        parts.append(f"period ended {period}")
    xbrl = _usable_url(row.get("xbrl"))
    ixbrl = _usable_url(row.get("ixbrl"))
    pdf = _usable_url(row.get("pdf_attach")) or xbrl or ixbrl
    return {
        "symbol": row.get("symbol") or symbol,
        "subject": " ".join(part for part in parts if part),
        "text": "",
        "pdf_url": pdf,
        "xbrl_url": xbrl,
        "period_end": period,
        "scope": consolidated or "Unknown",
        "timestamp": str(row.get("broadcast_Date") or ""),
        "filing_kind": "results",
    }


def _usable_url(value) -> str:
    text = str(value or "").strip()
    if not text.startswith("http"):
        return ""
    if text.rstrip("/").endswith("/null") or text.endswith("null"):
        return ""
    return text


def _broadcast_date(value: str) -> date | None:
    parsed = _broadcast_sort(value)
    if parsed == datetime.min:
        return None
    return parsed.date()


def _broadcast_sort(value: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.min
    # NSE mixes "02-Nov-2026 21:03:19" and "30-SEP-2026".
    month = text.split("-")
    if len(month) >= 3 and month[1].isalpha():
        month[1] = month[1].title()
        text = "-".join(month)
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return datetime.min
