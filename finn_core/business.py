"""What the company does, from the annual report only.

NSE's annual-report link is the source. Text is taken from the pages that
look like the business overview, the company introduction, or the management
discussion, and from no more than 30 of them. A Flash-Lite call reads those
pages. A field with no quote on its page is dropped.
"""

import re
import time
from pathlib import Path

from finn_core.documents import find_annual_report
from finn_core.ledger import on_page
from finn_core.llm import FLASH_LITE, FLASH_LITE_FALLBACK, GROQ_EXTRACTION, generate_json
from finn_core.nse_client import NSEClient, NSEError

VERSION = "v3"
PAGE_CAP = 30
SCAN_SECONDS = 32
# Real section openings, not a contents line and not "our business partners".
# Background is the note that says what the company does. The segment note
# is where a revenue share is actually stated.

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "does": {"type": "OBJECT", "properties": {"text": {"type": "STRING"}, "page": {"type": "INTEGER"}, "evidence": {"type": "STRING"}}, "required": ["text", "page", "evidence"]},
        "makes_money": {"type": "OBJECT", "properties": {"text": {"type": "STRING"}, "page": {"type": "INTEGER"}, "evidence": {"type": "STRING"}}, "required": ["text", "page", "evidence"]},
        "segments": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "name": {"type": "STRING"},
                    "share": {"type": "STRING"},
                    "page": {"type": "INTEGER"},
                    "evidence": {"type": "STRING"},
                },
                "required": ["name", "share", "page", "evidence"],
            },
        },
        "geographies": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "name": {"type": "STRING"},
                    "share": {"type": "STRING"},
                    "page": {"type": "INTEGER"},
                    "evidence": {"type": "STRING"},
                },
                "required": ["name", "share", "page", "evidence"],
            },
        },
    },
    "required": ["does", "makes_money", "segments", "geographies"],
}


def business_snapshot(symbol: str, cache=None, client=None) -> dict:
    """One stage. A cached year returns at once. Pages, then one model call."""
    started = time.perf_counter()
    symbol = symbol.upper().strip()
    if not symbol:
        raise ValueError("symbol is required")
    client = client or NSEClient(cache=cache)
    report = find_annual_report(symbol, client=client, cache=cache)
    year = str(report.get("to_year") or report.get("year") or "")
    if report.get("status") != "found" or not report.get("url"):
        return _envelope(symbol, "not_found", year, "", None, {}, started, "computed", "No annual report was found on NSE.")
    if cache is not None:
        saved = cache.get("biz_snapshot", symbol, year or "unknown", VERSION)
        if isinstance(saved, dict) and saved.get("status") in {"ready", "unreadable"} and not _reread(saved):
            pages = (cache.get("biz_pages", symbol, year or "unknown", VERSION) or {}).get("pages") or []
            saved = {
                **saved,
                "snapshot": _stated_snapshot(_percent_shares(saved.get("snapshot")), pages),
                "source": "cache",
                "seconds": round(time.perf_counter() - started, 1),
            }
            return saved
    state = {}
    if cache is not None:
        state = cache.get("biz_pages", symbol, year or "unknown", VERSION) or {}
        if state.get("error") == "The annual report could not be read." and state.get("reader") != "final":
            state = {}
    if not state.get("done"):
        state = _scan(state, report, client, symbol, year, cache, time.perf_counter() + SCAN_SECONDS)
        if cache is not None:
            cache.put("biz_pages", symbol, year or "unknown", VERSION, state)
        if not state.get("done"):
            return _envelope(
                symbol,
                "partial",
                year,
                report["url"],
                None,
                {},
                started,
                "computed",
                "",
                {"stage": "pages", "done": state.get("cursor") or 0, "total": state.get("total") or 0},
            )
        if state.get("error"):
            body = _envelope(symbol, "unreadable", year, report["url"], None, {}, started, "computed", state["error"])
            if state.get("reader"):
                body["reader"] = state["reader"]
            if cache is not None:
                cache.put("biz_snapshot", symbol, year or "unknown", VERSION, {**body, "source": "computed"})
            return body
        if time.perf_counter() - started > 20:
            return _envelope(
                symbol,
                "partial",
                year,
                report["url"],
                None,
                {},
                started,
                "computed",
                "",
                {"stage": "extract", "done": len(state.get("pages") or []), "total": len(state.get("pages") or [])},
            )
    pages = state.get("pages") or []
    if not pages:
        body = _envelope(symbol, "unreadable", year, report["url"], None, {}, started, "computed", "Those pages have no business overview or management discussion.")
        body["reader"] = state.get("reader") or "checked"
        if cache is not None:
            cache.put("biz_snapshot", symbol, year or "unknown", VERSION, {**body, "source": "computed"})
        return body
    raw, usage = _ask(pages)
    snapshot = accept(raw, pages)
    if not any((snapshot["does"], snapshot["makes_money"], snapshot["segments"], snapshot["geographies"])):
        body = _envelope(symbol, "unreadable", year, report["url"], None, usage, started, "computed", "Nothing on those pages could be tied back to a quote.")
        if cache is not None:
            cache.put("biz_snapshot", symbol, year or "unknown", VERSION, {**body, "source": "computed"})
        return body
    body = _envelope(symbol, "ready", year, report["url"], snapshot, usage, started, "computed", "")
    if cache is not None:
        cache.put("biz_snapshot", symbol, year or "unknown", VERSION, {**body, "source": "computed"})
    return body


def select_pages(texts: list[str]) -> list[dict]:
    """Pages whose headings match a section, capped per section. `texts` is in order."""
    state = {"cursor": 0, "pages": [], "started": [], "open": {}}
    for text in texts:
        _consider(state, text)
        state["cursor"] = int(state["cursor"]) + 1
        if len(state["pages"]) >= PAGE_CAP:
            break
    return state["pages"]


def accept(raw: dict, pages: list[dict]) -> dict:
    """Drop any field whose quote is not on the page it names."""
    by_page = {int(page["page"]): page.get("text") or "" for page in pages}
    return {
        "does": _fact(raw.get("does"), by_page),
        "makes_money": _fact(raw.get("makes_money"), by_page),
        "segments": _items(raw.get("segments"), by_page),
        "geographies": _items(raw.get("geographies"), by_page),
    }


def _scan(state: dict, report: dict, client, symbol: str, year: str, cache, deadline: float) -> dict:
    state = {
        "cursor": int(state.get("cursor") or 0),
        "total": int(state.get("total") or 0),
        "pages": list(state.get("pages") or []),
        "started": list(state.get("started") or []),
        "open": dict(state.get("open") or {}),
        "done": False,
        "error": "",
        "url": report.get("url") or "",
    }
    try:
        data = _pdf_bytes(cache, client, symbol, year, report["url"])
    except (NSEError, OSError, RuntimeError) as exc:
        state["error"] = "The annual report could not be downloaded."
        state["detail"] = type(exc).__name__
        return state
    if not data.startswith(b"%PDF"):
        state["done"] = True
        state["error"] = "The annual report download is not a PDF."
        return state
    opened = _open_pdf(data)
    if opened is None:
        try:
            data = _pdf_bytes(cache, client, symbol, year, report["url"], refresh=True)
        except (NSEError, OSError, RuntimeError):
            data = b""
        opened = _open_pdf(data) if data.startswith(b"%PDF") else None
    if opened is None:
        state["done"] = True
        state["error"] = "The annual report could not be read."
        state["reader"] = "final" if data.rfind(b"%%EOF") >= len(data) - 2048 else "none"
        return state
    reader_name, text_at, total = opened
    state["reader"] = reader_name
    state["total"] = total
    while state["cursor"] < total and time.perf_counter() < deadline and len(state["pages"]) < PAGE_CAP:
        index = state["cursor"]
        try:
            text = text_at(index) or ""
        except Exception:
            text = ""
        _consider(state, text)
        state["cursor"] = index + 1
    if state["cursor"] >= total or len(state["pages"]) >= PAGE_CAP:
        state["done"] = True
        if not state["pages"]:
            state["error"] = "The annual report has no readable business overview or management discussion."
    return state


def _consider(state: dict, text: str) -> None:
    page = int(state["cursor"]) + 1
    if len(state["pages"]) >= PAGE_CAP:
        return
    compact = " ".join(text.split())
    low = compact.lower()
    open_sections = [name for name, end in state["open"].items() if page <= int(end)]
    if open_sections:
        state["pages"].append({"page": page, "section": open_sections[0], "text": compact[:1800]})
        return
    started = _opening(low)
    if started is None or started[0] in state["started"]:
        return
    name, span = started
    state["started"].append(name)
    state["open"][name] = page + span - 1
    state["pages"].append({"page": page, "section": name, "text": compact[:1800]})


def _opening(low: str) -> tuple[str, int] | None:
    if "background and operations" in low or "background of the company" in low:
        return "background", 2
    if any(key in low for key in ("engaged in the business of banking", "business of banking", "principal business of the bank")):
        return "background", 2
    head = low[:900]
    contents = ("company information" in head and "financial statements" in head) or (
        "statutory reports" in low and "financial statements" in low and "corporate overview" in low
    )
    if not contents and ("management discussion and analysis" in head or "management discussion & analysis" in head):
        return "discussion", 6
    if any(key in low for key in ("segment revenue", "external customers", "inter-segment")):
        return "segments", 3
    return None


def _ask(pages: list[dict]) -> tuple[dict, dict]:
    body = "\n\n".join(f"PAGE {page['page']}\n{page['text']}" for page in pages)
    prompt = (
        "These are pages from one annual report. Use nothing else. Do not use outside knowledge of the company. "
        "does.text is two plain sentences on what the company does. "
        "makes_money.text is one or two plain sentences on how it makes money. "
        "segments lists only segments the report names. share is the share of revenue exactly as stated, or an empty string if no figure is stated. "
        "geographies lists only places the report names. share is empty when no figure is stated. "
        "evidence is 8 to 20 consecutive words copied from the same page. page is that page's number. "
        "If a fact is not on these pages, use an empty string and page 0.\n\n"
        + body
    )
    return generate_json(prompt, SCHEMA, models=(FLASH_LITE, FLASH_LITE_FALLBACK), timeout=25, attempts=1, groq_models=GROQ_EXTRACTION)


def _fact(raw, by_page: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    text = _clean(raw.get("text"), 420)
    page, body = _page(raw, by_page)
    if not text or body is None or not on_page(_clean(raw.get("evidence"), 200), body) or not _stated(text, body):
        return None
    return {"text": text, "page": page}


def _items(raw, by_page: dict) -> list[dict]:
    rows = []
    if not isinstance(raw, list):
        return rows
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = _clean(item.get("name"), 80)
        page, body = _page(item, by_page)
        evidence = _clean(item.get("evidence"), 200)
        if not name or body is None or name.lower() not in body.lower() or not on_page(evidence, body):
            continue
        share = _clean(item.get("share"), 40)
        stated = f"{share} {evidence}".lower()
        if not share or "%" not in stated and "percent" not in stated or not any(char.isdigit() for char in share):
            share = ""
        rows.append({"name": name, "share": share or None, "page": page})
    return rows


def _page(raw: dict, by_page: dict) -> tuple[int, str | None]:
    try:
        page = int(raw.get("page") or 0)
    except (TypeError, ValueError):
        return 0, None
    return page, by_page.get(page)


def _stated(text: str, body: str) -> bool:
    """A claim stays only when a run of its own words is on the page."""
    claim = re.findall(r"[a-z0-9']+", text.lower())
    hay = " ".join(re.findall(r"[a-z0-9']+", body.lower()))
    if len(claim) < 6:
        return " ".join(claim) in hay
    return any(" ".join(claim[index : index + 6]) in hay for index in range(len(claim) - 5))


def _stated_snapshot(snapshot, pages: list[dict]):
    if not isinstance(snapshot, dict) or not pages:
        return snapshot
    by_page = {row["page"]: row.get("text") or "" for row in pages}
    cleaned = dict(snapshot)
    for key in ("does", "makes_money"):
        fact = snapshot.get(key)
        if not isinstance(fact, dict) or not _stated(str(fact.get("text") or ""), by_page.get(fact.get("page"), "")):
            cleaned[key] = None
    return cleaned


def _percent_shares(snapshot):
    if not isinstance(snapshot, dict):
        return snapshot
    cleaned = dict(snapshot)
    for key in ("segments", "geographies"):
        rows = []
        for item in snapshot.get(key) or []:
            if not isinstance(item, dict):
                continue
            share = str(item.get("share") or "")
            if "%" not in share and "percent" not in share.lower():
                item = {**item, "share": None}
            rows.append(item)
        cleaned[key] = rows
    return cleaned


def _clean(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _reread(saved: dict) -> bool:
    """An unread PDF is tried once more. A later failure is stamped so it does not loop."""
    messages = {
        "The annual report could not be read.",
        "Those pages have no business overview or management discussion.",
    }
    return saved.get("message") in messages and saved.get("reader") != "final"


def _open_pdf(data: bytes):
    """(reader name, text_at(index), page count). PyMuPDF is used when pypdf cannot list the pages."""
    if not data.startswith(b"%PDF"):
        return None
    try:
        from pypdf import PdfReader

        reader = PdfReader(_stream(data), strict=False)
        total = len(reader.pages)
        if total > 0:
            def text_at(index: int, held=reader) -> str:
                return held.pages[index].extract_text() or ""

            return "pypdf", text_at, total
    except Exception:
        pass
    try:
        from finn_core.pdf_text import _mupdf

        texts = _mupdf(data)
    except Exception:
        texts = []
    if not texts:
        return None

    def text_at(index: int, held=texts) -> str:
        return held[index] if 0 <= index < len(held) else ""

    return "pymupdf", text_at, len(texts)


def _pdf_bytes(cache, client, symbol: str, year: str, url: str, refresh: bool = False) -> bytes:
    path = _pdf_path(cache, symbol, year)
    if refresh and path.exists():
        try:
            path.unlink()
        except OSError:
            pass
    if not refresh and path.exists() and path.stat().st_size > 1000:
        data = path.read_bytes()
        if data.startswith(b"%PDF") and data.rfind(b"%%EOF") >= len(data) - 2048:
            return data
    from finn_core.documents import _download

    data = _download(client, url, symbol)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except OSError:
        pass
    return data


def _pdf_path(cache, symbol: str, year: str) -> Path:
    root = getattr(cache, "path", None)
    base = Path(root).parent if root else Path(".finn_cache")
    safe = "".join(char if char.isalnum() else "_" for char in (year or "latest"))
    return base / "docs" / symbol / f"annual_{safe}.pdf"


def _stream(data: bytes):
    import io

    return io.BytesIO(data)


def _envelope(symbol, status, year, url, snapshot, usage, started, source, message, progress=None) -> dict:
    return {
        "symbol": symbol,
        "status": status,
        "year": year,
        "url": url,
        "message": message,
        "snapshot": snapshot,
        "usage": usage or {"total_tokens": 0},
        "seconds": round(time.perf_counter() - started, 1),
        "source": source,
        "progress": progress or {"stage": "complete" if status != "partial" else "pages", "done": 0, "total": 0},
    }
