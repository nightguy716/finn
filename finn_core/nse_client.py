"""NSE corporate announcements. Public homepage cookie, then the JSON feed.

The Mumbai probe got HTTP 200 from the API when the homepage returned 403,
so a failed homepage does not abort the announcements call.
"""

import time
from datetime import date

import requests

HOME = "https://www.nseindia.com/"
ANNOUNCEMENTS = "https://www.nseindia.com/api/corporate-announcements"
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

    def _fetch(self, symbol: str, start: date, end: date) -> list[dict]:
        params = {
            "index": "equities",
            "symbol": symbol,
            "from_date": start.strftime("%d-%m-%Y"),
            "to_date": end.strftime("%d-%m-%Y"),
        }
        last_status = None
        last_detail = ""
        for attempt in range(self.max_retries):
            if self._session is None or attempt:
                self._open_session()
            self._wait()
            try:
                response = self._session.get(ANNOUNCEMENTS, params=params, timeout=25)
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
            return [_normalise(symbol, row) for row in _rows(payload)]
        raise NSEError(symbol, last_status, last_detail or "retries exhausted")


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
