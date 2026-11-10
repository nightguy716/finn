"""Find concall transcripts and the latest annual report for any NSE ticker.

Primary route is the NSE announcement feed. A single from/to call covered
four years for Titan (back to the requested start, 639 rows, no page token),
so the feed is not paged unless a long window comes back short. Screener's
public company page is the next place a transcript link shows up. The company
site linked from that page is the last resort. No news and no broker notes.
"""

import hashlib
import io
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from finn_core.cache import FileCache
from finn_core.config import market_symbol
from finn_core.nse_client import NSEClient, NSEError, _broadcast_sort
from finn_core.xbrl_parse import previous_quarter_end

CONCALL_SUBJECT = "analysts/institutional investor meet/con. call updates"
HTML_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-IN,en;q=0.9",
}
_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_FY = re.compile(r"Q([1-4])\s*FY\s*['’]?(\d{2,4})", re.I)
_QCODE = re.compile(r"Q([1-4])(\d{2})(?!\d)", re.I)
_QONLY = re.compile(r"Q([1-4])(?!\d)", re.I)
_CALL_MONTH = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(20\d{2})",
    re.I,
)
_NAMED_DAY = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[-_ ](\d{1,2})[-_ ](20\d{2})",
    re.I,
)


def quarter_ends(day: date, count: int) -> list[date]:
    """Most recent quarter-ends on or before `day`, newest first."""
    current = latest_quarter_end(day)
    found = []
    for _ in range(count):
        found.append(current)
        current = previous_quarter_end(current)
    return found


def latest_quarter_end(day: date) -> date:
    found = []
    for year in (day.year, day.year - 1):
        for month, last in ((3, 31), (6, 30), (9, 30), (12, 31)):
            end = date(year, month, last)
            if end <= day:
                found.append(end)
    return max(found)


def attachment_kind(text: str, url: str) -> str:
    """transcript, audio, or notice.

    A schedule that only promises a transcript later is a notice. "Copy of transcript"
    and an NSE subject of "about Transcript" are the transcript itself.
    """
    body = (text or "").lower()
    name = (url or "").rsplit("/", 1)[-1].lower()
    if "copy of transcript" in body or "about transcript" in body or "about earnings call transcript" in body:
        return "transcript"
    if "transcript" in name and "schedule" not in name:
        return "transcript"
    if any(phrase in body for phrase in ("will hold", "scheduled to be held", "schedule of")):
        return "notice"
    if "recording" in body or "recording" in name or "audio" in name or ".mp3" in name or ".mp4" in name:
        return "audio"
    if "transcript" in body and "will be uploaded" not in body and "will be made available" not in body:
        return "transcript"
    return "notice"


def period_from_filing(text: str, url: str, announced: date | None) -> date | None:
    """Quarter the filing belongs to. Filename codes first, then the call date."""
    name = (url or "").rsplit("/", 1)[-1]
    for blob in (name, text or ""):
        parsed = _fy_code(blob) or _short_code(blob)
        if parsed and _lag_ok(parsed, announced):
            return parsed
    for blob in (name, text or ""):
        match = _QONLY.search(blob)
        if match and announced is not None:
            parsed = _end_from_quarter_number(int(match.group(1)), announced)
            if _lag_ok(parsed, announced):
                return parsed
    named = _named_day(name) or _named_day(text or "")
    if named is not None and _lag_ok(latest_quarter_end(named), named):
        return latest_quarter_end(named)
    if announced is not None:
        parsed = latest_quarter_end(announced)
        if _lag_ok(parsed, announced):
            return parsed
    return None


def find_transcripts(symbol: str, quarters: int = 5, as_of: date | None = None, client=None, cache=None) -> dict:
    """Last `quarters` quarter-ends. Each row is found, audio_only, or not_found."""
    as_of = as_of or date.today()
    symbol = symbol.upper()
    market = market_symbol(symbol)
    client = client or NSEClient(cache=cache)
    cache = cache if cache is not None else client.cache
    failures: list[dict] = []
    expected = quarter_ends(as_of, quarters)
    start = expected[-1] - timedelta(days=7)
    try:
        rows = _announcements(client, market, start, as_of)
    except NSEError as exc:
        failures.append({"symbol": symbol, "step": "nse_announcements", "detail": str(exc)})
        rows = []
    candidates = []
    for row in rows:
        if (row.get("subject") or "").strip().lower() != CONCALL_SUBJECT:
            continue
        url = row.get("pdf_url") or ""
        kind = attachment_kind(row.get("text") or "", url)
        if kind == "notice" or not url:
            continue
        announced = _as_date(row.get("timestamp") or "")
        period = period_from_filing(row.get("text") or "", url, announced)
        if period not in expected or announced is None:
            continue
        candidates.append(
            {
                "period": period,
                "date": announced,
                "url": url,
                "route": "nse",
                "kind": kind,
                "lag": (announced - period).days,
                "earnings": "earning" in (row.get("text") or "").lower(),
            }
        )
    chosen = _pick(candidates)
    pointer_urls = _drop_pointer_letters(symbol, chosen, client, cache, failures)
    missing = [period for period in expected if chosen.get(period, {}).get("kind") != "transcript"]
    if missing:
        try:
            page = _screener(symbol, cache)
        except (requests.RequestException, OSError, RuntimeError) as exc:
            page = {"transcripts": [], "annual": [], "website": ""}
            failures.append({"symbol": symbol, "step": "screener", "detail": str(exc)})
        screener_rows = []
        for item in page.get("transcripts") or []:
            if item["period"] not in missing:
                continue
            screener_rows.append(item)
        for item in _pick(screener_rows).values():
            current = chosen.get(item["period"])
            if item["kind"] == "transcript" or current is None:
                chosen[item["period"]] = item
        still = [period for period in expected if chosen.get(period, {}).get("kind") != "transcript"]
        website = page.get("website") or ""
        if still and website:
            try:
                ir_rows = _ir_transcripts(symbol, website, cache, still, pointer_urls)
            except (requests.RequestException, OSError, RuntimeError) as exc:
                ir_rows = []
                failures.append({"symbol": symbol, "step": "ir", "detail": str(exc)})
            for item in _pick(ir_rows).values():
                current = chosen.get(item["period"])
                if item["kind"] == "transcript" or current is None:
                    chosen[item["period"]] = item
        elif still and not website and not any(item["step"] == "screener" for item in failures):
            failures.append({"symbol": symbol, "step": "ir", "detail": "The public Screener page has no company website."})
    quarters_out = []
    for period in expected:
        item = chosen.get(period)
        if item is None:
            quarters_out.append(
                {"period": period.isoformat(), "date": None, "url": "", "route": "none", "status": "not_found"}
            )
            continue
        status = "found" if item["kind"] == "transcript" else "audio_only"
        quarters_out.append(
            {
                "period": period.isoformat(),
                "date": item["date"].isoformat() if isinstance(item["date"], date) else item["date"],
                "url": item["url"],
                "route": item["route"],
                "status": status,
            }
        )
    return {"symbol": symbol, "quarters": quarters_out, "failures": failures}


def find_annual_report(symbol: str, client=None, cache=None) -> dict:
    """Latest annual-report PDF. NSE's annual-reports feed, then Screener."""
    symbol = symbol.upper()
    market = market_symbol(symbol)
    client = client or NSEClient(cache=cache)
    cache = cache if cache is not None else client.cache
    try:
        rows = client.get_annual_reports(market)
    except NSEError as exc:
        rows = []
        nse_error = str(exc)
    else:
        nse_error = ""
    if rows:
        row = rows[0]
        return {
            "symbol": symbol,
            "year": row["to_year"],
            "from_year": row["from_year"],
            "to_year": row["to_year"],
            "url": row["url"],
            "route": "nse",
            "status": "found",
            "failures": [],
        }
    failures = []
    if nse_error:
        failures.append({"symbol": symbol, "step": "nse_annual_report", "detail": nse_error})
    try:
        page = _screener(symbol, cache)
    except (requests.RequestException, OSError, RuntimeError) as exc:
        failures.append({"symbol": symbol, "step": "screener_annual_report", "detail": str(exc)})
        page = {"annual": []}
    annual = page.get("annual") or []
    if not annual:
        if not nse_error:
            failures.append({"symbol": symbol, "step": "annual_report", "detail": "No annual report on NSE or the public Screener page."})
        return {"symbol": symbol, "year": "", "url": "", "route": "none", "status": "not_found", "failures": failures}
    best = max(annual, key=lambda item: item["year"])
    return {
        "symbol": symbol,
        "year": best["year"],
        "url": best["url"],
        "route": "screener",
        "status": "found",
        "failures": failures,
    }


def extract_pdf(symbol: str, url: str, client=None, cache=None) -> dict:
    """Page-numbered text for one PDF. Cached by symbol and URL. Image-only PDFs are marked scanned."""
    symbol = symbol.upper()
    client = client or NSEClient(cache=cache)
    cache = cache if cache is not None else client.cache
    if cache is not None:
        cached = cache.get("doc_text", symbol, url, "v1")
        if isinstance(cached, dict) and "pages" in cached:
            return cached
    try:
        data = _download(client, url, symbol)
    except (NSEError, requests.RequestException, OSError, RuntimeError) as exc:
        return {"url": url, "chars": 0, "page_count": 0, "scanned": False, "pages": [], "error": str(exc)}
    if not data.startswith(b"%PDF"):
        return {"url": url, "chars": 0, "page_count": 0, "scanned": False, "pages": [], "error": "Download is not a PDF."}
    pages, error = _pages(data)
    chars = sum(len(page["text"]) for page in pages)
    scanned = bool(pages) and chars < 40 * len(pages)
    payload = {"url": url, "chars": chars, "page_count": len(pages), "scanned": scanned, "pages": pages, "error": error}
    if cache is not None and not error:
        folder = Path(cache.path).parent / "docs" / symbol
        folder.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", url.rsplit("/", 1)[-1])[:40].strip("._") or "doc"
        digest = hashlib.sha1(url.encode()).hexdigest()[:8]
        (folder / f"{stem}_{digest}.pdf").write_bytes(data)
        cache.put("doc_text", symbol, url, "v1", payload)
    return payload


def _announcements(client, symbol: str, start: date, end: date) -> list[dict]:
    """One NSE call. Split the window only when the oldest row is far inside a long range."""
    rows = client.get_announcements(symbol, start, end)
    if (end - start).days < 200 or len(rows) < 200:
        return rows
    dates = [day for day in (_as_date(row.get("timestamp") or "") for row in rows) if day is not None]
    if not dates:
        return rows
    oldest = min(dates)
    if (oldest - start).days <= 60:
        return rows
    mid = start + timedelta(days=(end - start).days // 2)
    left = _announcements(client, symbol, start, mid)
    right = _announcements(client, symbol, mid + timedelta(days=1), end)
    seen = set()
    merged = []
    for row in left + right:
        key = (row.get("pdf_url") or "", row.get("timestamp") or "")
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
    return merged


def _pick(candidates: list[dict]) -> dict[date, dict]:
    grouped: dict[date, list[dict]] = {}
    for item in candidates:
        grouped.setdefault(item["period"], []).append(item)
    chosen = {}
    for period, items in grouped.items():
        transcripts = [item for item in items if item["kind"] == "transcript"]
        pool = transcripts or [item for item in items if item["kind"] == "audio"]
        if not pool:
            continue
        # An earnings-call transcript beats a later invite-only conference in the same quarter.
        preferred = [item for item in pool if item.get("earnings")] or pool
        preferred.sort(key=lambda item: item["date"])
        if len(preferred) > 1 and (preferred[-1]["date"] - preferred[0]["date"]).days <= 21:
            best = preferred[-1]
        else:
            best = min(preferred, key=lambda item: (item["lag"], item["date"]))
        chosen[period] = best
    return chosen


def _drop_pointer_letters(symbol: str, chosen: dict, client, cache, failures: list[dict]) -> list[str]:
    """An NSE 'transcript' that is only a letter pointing at the company site is not the transcript."""
    urls = []
    for period, item in list(chosen.items()):
        if item.get("route") != "nse" or item.get("kind") != "transcript":
            continue
        if not item["url"].lower().split("?")[0].endswith(".pdf"):
            continue
        extracted = extract_pdf(symbol, item["url"], client=client, cache=cache)
        if not _pointer_letter(extracted):
            continue
        found = _urls_in(extracted)
        urls.extend(found)
        detail = (
            f"{period.isoformat()} NSE file is a {extracted.get('page_count') or 0}-page letter "
            "pointing at the company website, not the transcript."
        )
        if found:
            detail += " " + " ".join(found)
        failures.append({"symbol": symbol, "step": "transcript", "detail": detail})
        del chosen[period]
    return urls


def _pointer_letter(payload: dict) -> bool:
    if payload.get("error"):
        return False
    if (payload.get("page_count") or 0) > 2 or (payload.get("chars") or 0) > 6000:
        return False
    text = " ".join((page.get("text") or "") for page in payload.get("pages") or []).lower()
    return "uploaded on" in text and "website" in text


def _urls_in(payload: dict) -> list[str]:
    text = " ".join((page.get("text") or "") for page in payload.get("pages") or [])
    return re.findall(r"https?://[^\s<>\"]+", text)


def _screener(symbol: str, cache) -> dict:
    if cache is not None:
        cached = cache.get("screener_html", symbol, "consolidated", "v1")
        if isinstance(cached, str) and "documents" in cached.lower():
            return _parse_screener(cached, f"https://www.screener.in/company/{symbol}/consolidated/")
    session = requests.Session()
    session.headers.update(HTML_HEADERS)
    last = None
    html = ""
    page_url = ""
    for suffix in ("consolidated", ""):
        page_url = f"https://www.screener.in/company/{symbol}/" + (f"{suffix}/" if suffix else "")
        time.sleep(2.5)
        response = session.get(page_url, timeout=30)
        last = response
        if response.status_code == 200 and b"documents" in response.content.lower():
            html = response.text
            page_url = response.url
            break
    if not html:
        status = last.status_code if last is not None else "none"
        raise RuntimeError(f"Screener HTTP {status} for {symbol}")
    if cache is not None:
        cache.put("screener_html", symbol, "consolidated", "v1", html)
    return _parse_screener(html, page_url)


def _parse_screener(html: str, page_url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    transcripts = []
    annual = []
    for block in soup.select("div.documents"):
        heading = block.find(["h2", "h3"])
        title = heading.get_text(" ", strip=True).lower() if heading else ""
        if "concall" in title:
            for li in block.select("li"):
                label = li.get_text(" ", strip=True)
                call = _call_month(label)
                if call is None:
                    continue
                period = latest_quarter_end(call)
                if (call - period).days > 100:
                    continue
                for anchor in li.find_all("a", href=True):
                    name = anchor.get_text(" ", strip=True).lower()
                    if "summary" in name:
                        continue
                    kind = "transcript" if name == "transcript" else "audio" if name in ("rec", "recording", "audio") else ""
                    if not kind:
                        continue
                    transcripts.append(
                        {
                            "period": period,
                            "date": call,
                            "url": urljoin(page_url, anchor["href"]),
                            "route": "screener",
                            "kind": kind,
                            "lag": (call - period).days,
                        }
                    )
        elif "annual" in title:
            for anchor in block.find_all("a", href=True):
                name = anchor.get_text(" ", strip=True)
                if "annual report" not in name.lower() or "summary" in name.lower():
                    continue
                match = re.search(r"(20\d{2})", name)
                if not match:
                    continue
                annual.append({"year": match.group(1), "url": urljoin(page_url, anchor["href"])})
    website = ""
    for anchor in soup.find_all("a", href=True):
        if anchor.get_text(" ", strip=True).lower() == "website":
            website = anchor["href"].strip()
            break
    return {"transcripts": transcripts, "annual": annual, "website": website}


def _ir_transcripts(symbol: str, website: str, cache, needed: list[date], extra_urls: list[str] | None = None) -> list[dict]:
    home_error = ""
    try:
        home_html, home_url = _fetch_html(symbol, website, cache)
    except (requests.RequestException, OSError, RuntimeError) as exc:
        home_html, home_url = "", website
        home_error = str(exc)
    host = _host(home_url)
    links = []
    for href, text in _anchors(home_html, home_url):
        if _host(href) != host or href.lower().split("?")[0].endswith(".pdf"):
            continue
        blob = f"{text} {href}".lower()
        if any(word in blob for word in ("investor", "financial", "shareholder", "earning", "concall", "transcript")):
            links.append(href)
    pages = [(home_html, home_url)]
    seeds = []
    for href in extra_urls or []:
        if href not in seeds:
            seeds.append(href)
    for href in seeds + links[:4]:
        try:
            pages.append(_fetch_html(symbol, href, cache))
        except (requests.RequestException, OSError, RuntimeError):
            continue
    found = []
    seen = set()
    for html, page_url in pages:
        for href, text in _anchors(html, page_url):
            if href in seen:
                continue
            blob = f"{text} {href}".lower()
            path = href.lower().split("?")[0]
            if "transcript" not in blob or not path.endswith(".pdf"):
                continue
            seen.add(href)
            announced = _named_day(href) or _named_day(text)
            period = period_from_filing(text, href, announced)
            if period not in needed:
                continue
            when = announced or period
            found.append(
                {
                    "period": period,
                    "date": when,
                    "url": href,
                    "route": "ir",
                    "kind": "transcript",
                    "lag": (when - period).days,
                }
            )
    if home_error and not found:
        raise RuntimeError(home_error)
    return found


def _fetch_html(symbol: str, url: str, cache) -> tuple[str, str]:
    if cache is not None:
        cached = cache.get("ir_html", symbol, url, "v1")
        if isinstance(cached, str) and cached:
            return cached, url
    candidates = [url]
    if url.startswith("http://"):
        candidates.append("https://" + url[len("http://") :])
    last = "no response"
    for candidate in candidates:
        time.sleep(2.5)
        try:
            response = requests.get(candidate, headers=HTML_HEADERS, timeout=20)
        except requests.RequestException as exc:
            last = str(exc)
            continue
        if response.status_code == 200 and "html" in response.headers.get("content-type", "text/html"):
            if cache is not None:
                cache.put("ir_html", symbol, url, "v1", response.text)
            return response.text, response.url
        last = f"HTTP {response.status_code}"
    raise RuntimeError(f"IR {url} {last}")


def _anchors(html: str, page_url: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    found = []
    for anchor in soup.find_all("a", href=True):
        href = urljoin(page_url, anchor["href"].strip())
        if href.startswith("http"):
            found.append((href, anchor.get_text(" ", strip=True)))
    return found


def _download(client, url: str, symbol: str) -> bytes:
    host = _host(url)
    if "nseindia.com" in host:
        return client.get_bytes(url, symbol)
    last = ""
    for attempt in range(3):
        client._wait()
        try:
            response = requests.get(url, headers={**HTML_HEADERS, "Accept": "*/*"}, timeout=60)
        except requests.RequestException as exc:
            last = str(exc)
            time.sleep(2 ** attempt)
            continue
        if response.status_code == 200 and response.content:
            return response.content
        last = f"HTTP {response.status_code}"
        time.sleep(2 ** attempt)
    raise RuntimeError(f"{symbol} download {url} {last}")


def _pages(data: bytes) -> tuple[list[dict], str]:
    import warnings

    from pypdf import PdfReader

    warnings.filterwarnings("ignore", message="fontTools is required")
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:
        return [], f"PDF could not be read: {exc}"
    pages = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        pages.append({"page": index, "text": text})
    return pages, ""


def _fy_code(blob: str) -> date | None:
    match = _FY.search(blob)
    if not match:
        return None
    return _fy_end(int(match.group(1)), int(match.group(2)))


def _short_code(blob: str) -> date | None:
    match = _QCODE.search(blob)
    if not match:
        return None
    return _fy_end(int(match.group(1)), int(match.group(2)))


def _fy_end(quarter: int, fy: int) -> date:
    """FY27 means the year ending March 2027. Q2 of that year ends September 2026."""
    if fy < 100:
        fy += 2000
    if quarter == 1:
        return date(fy - 1, 6, 30)
    if quarter == 2:
        return date(fy - 1, 9, 30)
    if quarter == 3:
        return date(fy - 1, 12, 31)
    return date(fy, 3, 31)


def _end_from_quarter_number(quarter: int, announced: date) -> date:
    """Q4 filed in May is the March quarter of that calendar year. Q3 filed in February is the previous December."""
    month = {1: 6, 2: 9, 3: 12, 4: 3}[quarter]
    last = {6: 30, 9: 30, 12: 31, 3: 31}[month]
    year = announced.year if month <= announced.month else announced.year - 1
    return date(year, month, last)


def _lag_ok(period: date, announced: date | None) -> bool:
    if announced is None:
        return True
    return -5 <= (announced - period).days <= 120


def _call_month(label: str) -> date | None:
    match = _CALL_MONTH.search(label)
    if not match:
        return None
    return date(int(match.group(2)), _MONTHS[match.group(1).lower()[:3]], 1)


def _named_day(blob: str) -> date | None:
    match = _NAMED_DAY.search(blob or "")
    if not match:
        return None
    try:
        return date(int(match.group(3)), _MONTHS[match.group(1).lower()[:3]], int(match.group(2)))
    except ValueError:
        return None


def _as_date(value: str) -> date | None:
    parsed = _broadcast_sort(value)
    if parsed == datetime.min:
        return None
    return parsed.date()


def _host(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _cache():
    return FileCache()
