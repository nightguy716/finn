"""Promise Ledger. Guidance comes from transcript pages. Delivery is arithmetic.

    python -m finn_core.ledger MARICO DMART
"""

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import date

from finn_core.cache import FileCache
from finn_core.documents import extract_pdf, find_transcripts, quarter_ends
from finn_core.llm import FLASH, FLASH_FALLBACKS, generate_json
from finn_core.nse_client import NSEClient
from finn_core.series import quarterly_series

CHECKABLE = {"revenue_growth", "ebitda_margin", "ebitda_growth", "pat_growth"}
METRIC_KEYS = CHECKABLE | {"volume_growth", "capex", "other"}
_FORWARD = re.compile(
    r"guidan\w*|expect\w*|target\w*|outlook|\baim(?:ing|ed)?\b|going forward|"
    r"next year|next quarter|full year|fy\s*'?\d{2}|\bcapex\b|volume growth|"
    r"double[- ]digit|mid[- ]teen|high[- ]teen|low[- ]teen",
    re.I,
)
_WORD = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?%?")
GUIDANCE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "promises": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "metric_key": {"type": "STRING"},
                    "target_low": {"type": "STRING"},
                    "target_high": {"type": "STRING"},
                    "direction": {"type": "STRING"},
                    "horizon": {"type": "STRING"},
                    "target_period": {"type": "STRING"},
                    "speaker": {"type": "STRING"},
                    "evidence": {"type": "STRING"},
                    "page": {"type": "INTEGER"},
                },
                "required": [
                    "metric_key",
                    "target_low",
                    "target_high",
                    "direction",
                    "horizon",
                    "target_period",
                    "speaker",
                    "evidence",
                    "page",
                ],
            },
        }
    },
    "required": ["promises"],
}
VERDICT_SCHEMA = {
    "type": "OBJECT",
    "properties": {"line": {"type": "STRING"}},
    "required": ["line"],
}
LABELS = {
    "revenue_growth": "Revenue growth",
    "ebitda_margin": "EBITDA margin",
    "ebitda_growth": "EBITDA growth",
    "pat_growth": "PAT growth",
    "volume_growth": "Volume growth",
    "capex": "Capex",
    "other": "Other",
}


def promise_ledger(symbol: str, as_of: date | None = None, client=None, cache=None) -> dict:
    """Coverage, snapshot, promise rows, and a one-line verdict. Stages are cached."""
    as_of = as_of or date.today()
    symbol = symbol.upper()
    client = client or NSEClient(cache=cache)
    cache = cache if cache is not None else client.cache
    timing = {}
    usage = {
        "guidance": {"calls": 0, "cache_hits": 0, "tokens": 0, "dropped": 0},
        "verdict": {"calls": 0, "cache_hits": 0, "tokens": 0, "model": ""},
        "total_tokens": 0,
    }

    def stage(name, fn):
        started = time.perf_counter()
        value = fn()
        timing[name] = round(time.perf_counter() - started, 2)
        return value

    transcripts = stage("discover", lambda: find_transcripts(symbol, as_of=as_of, client=client, cache=cache))
    series = stage("series", lambda: quarterly_series(symbol, as_of=as_of, client=client, cache=cache))
    rows = stage("guidance", lambda: _guidance_rows(symbol, transcripts, cache, client, usage))
    checked = stage("check", lambda: _check_rows(rows, series["quarters"]))
    covered = _coverage(transcripts, series["quarters"])
    shot = _snapshot(series["quarters"])
    verdict = stage("verdict", lambda: _verdict(symbol, covered, shot, checked, cache, usage))
    usage["total_tokens"] = usage["guidance"]["tokens"] + usage["verdict"]["tokens"]
    timing["total"] = round(sum(timing.values()), 2)
    return {
        "symbol": symbol,
        "coverage": covered,
        "snapshot": shot,
        "rows": checked,
        "verdict": verdict,
        "timing": timing,
        "usage": usage,
    }


def select_pages(pages: list[dict], limit: int = 8) -> list[dict]:
    """Pages that contain forward-looking language, strongest first."""
    scored = []
    for page in pages:
        text = page.get("text") or ""
        hits = len(_FORWARD.findall(text))
        if hits:
            scored.append((hits, page))
    scored.sort(key=lambda item: item[0], reverse=True)
    chosen = []
    chars = 0
    for _, page in scored[:limit]:
        snippet = (page.get("text") or "")[:2500]
        if chars + len(snippet) > 14000 and chosen:
            break
        chosen.append({"page": page.get("page"), "text": snippet})
        chars += len(snippet)
    chosen.sort(key=lambda page: page["page"] or 0)
    return chosen


def on_page(snippet: str, text: str) -> bool:
    """Every word of the snippet appears, in order, on the page."""
    words = _WORD.findall((snippet or "").lower())[:25]
    if len(words) < 5:
        return False
    hay = (text or "").lower()
    pos = 0
    for word in words:
        found = hay.find(word, pos)
        if found < 0:
            return False
        pos = found + len(word)
    return True


def compare_target(actual: float, low: float | None, high: float | None, direction: str) -> str:
    """delivered, partly, missed, or not_checkable. Bands are in percentage points."""
    if low is not None and high is not None:
        if low <= actual <= high:
            return "delivered"
        if low - 2 <= actual <= high + 2:
            return "partly"
        return "missed"
    if low is not None:
        if actual >= low:
            return "delivered"
        if actual >= low - 2:
            return "partly"
        return "missed"
    if high is not None:
        if actual <= high:
            return "delivered"
        if actual <= high + 2:
            return "partly"
        return "missed"
    if direction == "up":
        if actual > 0.5:
            return "delivered"
        return "partly" if actual >= -0.5 else "missed"
    if direction == "down":
        if actual < -0.5:
            return "delivered"
        return "partly" if actual <= 0.5 else "missed"
    return "not_checkable"


_PART = re.compile(
    r"portfolio|\bbrand\b|international|segment|division|category|digital[- ]first|subsidiary|\bpiece\b|\b(?!our\b)\w+\s+business",
    re.I,
)
_MOVEMENT = re.compile(r"increas|decreas|grow|decline|expand|reduc|higher|lower|improv", re.I)


def _written_percent(text: str, value: float | None) -> bool:
    if value is None:
        return False
    return re.search(rf"(?<!\d){re.escape(f'{value:g}')}\s*(%|percent)", text) is not None


def sanitize_bounds(evidence: str, low: float | None, high: float | None) -> tuple[float | None, float | None]:
    """A crore target, a capacity figure, or a '3x' is not a percent. Named bands apply after that."""
    text = (evidence or "").lower()
    if re.search(r"\d+(?:\.\d+)?\s*x\b", text) and "%" not in text and "percent" not in text:
        low, high = None, None
    point = low is not None and high is not None and abs(low - high) < 1e-6
    if low is not None and not _written_percent(text, low) and (abs(low) >= 100 or point):
        low = None
    if high is not None and not _written_percent(text, high) and (abs(high) >= 100 or low is None):
        high = None
    number = low if low is not None else high
    if number is not None and (low is None or high is None) and _written_percent(text, number):
        floor = re.search(r"at least|more than|above|minimum|no less", text) is not None
        ceiling = re.search(r"at most|no more|not more|below|under |up to|capped", text) is not None
        if floor and not ceiling:
            low, high = number, None
        elif ceiling and not floor:
            low, high = None, number
        else:
            low, high = number, number
    return apply_word_bands(evidence, low, high)


def apply_word_bands(evidence: str, low: float | None, high: float | None) -> tuple[float | None, float | None]:
    """Named bands only when the quote itself uses them and states no number."""
    if low is not None or high is not None:
        return low, high
    text = re.sub(r"\s*-\s*", "-", (evidence or "").lower())
    if "mid-teen" in text or "mid teen" in text:
        return 13.0, 16.0
    if "high-teen" in text or "high teen" in text:
        return 17.0, 19.0
    if "low-teen" in text or "low teen" in text:
        return 10.0, 13.0
    if "double-digit" in text or "double digit" in text:
        return 10.0, None
    if "high single" in text:
        return 7.0, 9.0
    return low, high


def judge_promise(promise: dict, quarters: list[dict]) -> dict:
    """Fill actual and status. The model does not do this arithmetic."""
    by_period = {row["period"]: row for row in quarters}
    latest = _latest(quarters)
    key = promise["metric_key"]
    low, high = sanitize_bounds(promise["evidence"], promise.get("target_low"), promise.get("target_high"))
    direction = promise.get("direction") or ""
    if low is None and high is None and not _MOVEMENT.search(promise.get("evidence") or ""):
        return None
    row = {
        "promise": _promise_line(promise, low, high),
        "source_quote": promise["evidence"],
        "page": promise["page"],
        "source_document": promise["source_document"],
        "speaker": promise.get("speaker") or "",
        "period_promised": promise.get("target_period") or "",
        "actual": None,
        "actual_value": None,
        "status": "not_checkable",
        "note": "",
    }
    if key not in CHECKABLE:
        row["note"] = "Volume, capex, and other items cannot be verified from the quarterly series."
        return row
    evidence = promise.get("evidence") or ""
    if key == "ebitda_margin" and re.search(r"\bebit margin\b", evidence, re.I) and "ebitda" not in evidence.lower():
        row["note"] = "The quote is an EBIT margin, not the consolidated EBITDA margin."
        return row
    if _PART.search(evidence):
        row["note"] = "The quote is about a part of the business, not the consolidated figure."
        return row
    kind, end = _parse_period(promise.get("target_period") or "")
    horizon = promise.get("horizon") or kind
    if end is None and horizon == "multi_year":
        row["status"] = "pending"
        row["note"] = "Multi-year horizon is still open."
        return row
    if end is None:
        row["note"] = "The quote does not name a quarter or a fiscal year."
        return row
    if latest is None or end > latest:
        row["status"] = "pending"
        shown = latest.isoformat() if latest else "none"
        row["note"] = f"The period ends {end.isoformat()}, after the latest reported quarter {shown}."
        return row
    if horizon == "fiscal_year" or kind == "fiscal_year":
        measured, note = _fy_measure(key, end.year, by_period, direction, low, high)
    else:
        measured, note = _quarter_measure(key, end, by_period, direction, low, high)
    if measured is None:
        row["note"] = note
        return row
    status = compare_target(measured, low, high, direction if low is None and high is None else "")
    if status == "not_checkable":
        row["note"] = "The quote has no number and no clear direction."
        return row
    row["status"] = status
    row["actual_value"] = measured
    row["actual"] = f"{measured:g}%"
    return row


def _guidance_rows(symbol: str, transcripts: dict, cache, client, usage: dict) -> list[dict]:
    rows = []
    for item in transcripts["quarters"]:
        if item["status"] != "found" or not item.get("url"):
            continue
        document = extract_pdf(symbol, item["url"], client=client, cache=cache)
        promises, hit, tokens, dropped, error = _promises_for_document(
            symbol, item, document, cache
        )
        bucket = usage["guidance"]
        if error:
            bucket.setdefault("errors", []).append(f"{item['period']}: {error}")
        bucket["dropped"] += dropped
        if hit:
            bucket["cache_hits"] += 1
        elif tokens:
            bucket["calls"] += 1
            bucket["tokens"] += tokens
        rows.extend(promises)
    return rows


def _promises_for_document(symbol: str, item: dict, document: dict, cache) -> tuple[list[dict], bool, int, int, str]:
    url = item["url"]
    if cache is not None:
        cached = cache.get("guidance_llm", symbol, url, "v1")
        if isinstance(cached, dict) and "promises" in cached:
            return cached["promises"], True, 0, int(cached.get("dropped") or 0), ""
    pages = select_pages(document.get("pages") or [])
    if not pages or document.get("scanned"):
        if cache is not None:
            cache.put("guidance_llm", symbol, url, "v1", {"promises": [], "dropped": 0, "usage": {}})
        return [], False, 0, 0, ""
    call_period = date.fromisoformat(item["period"])
    fy = call_period.year if call_period.month == 3 else call_period.year + 1
    following = _next_quarter(call_period)
    body = "\n\n".join(f"PAGE {page['page']}\n{page['text']}" for page in pages)
    prompt = (
        "Extract explicit guidance spoken by management in this earnings-call transcript. "
        f"The call is about the quarter ended {call_period.isoformat()}, which is inside FY{fy} "
        f"(the year ending 31 March {fy}). Next quarter ends {following.isoformat()}. "
        f"Next fiscal year is FY{fy + 1}.\n"
        "Keep a promise only when the words state a number, a range, or a clear direction "
        "(rise, fall, at least, at most) for a future period. "
        "Skip vague optimism such as 'we remain positive' or 'we are confident'. "
        "evidence must be consecutive words copied from one page, 25 words or fewer. "
        "metric_key is one of revenue_growth, ebitda_margin, ebitda_growth, pat_growth, volume_growth, capex, other. "
        "horizon is quarter, fiscal_year, or multi_year. "
        "target_period is YYYY-MM-DD for a quarter or FY#### for a fiscal year. "
        "target_low and target_high are the numbers in the quote, without a percent sign, or empty. "
        "direction is up, down, or empty. speaker is a name printed on that page, or empty. "
        "At most 6 promises. Use nothing beyond these pages.\n\n"
        + body
    )
    try:
        payload, call_usage = generate_json(prompt, GUIDANCE_SCHEMA)
    except RuntimeError as exc:
        return [], False, 0, 0, str(exc)
    by_page = {page["page"]: page["text"] for page in pages}
    kept = []
    dropped = 0
    for raw in payload.get("promises") or []:
        promise = _clean_promise(raw, by_page, url)
        if promise is None:
            dropped += 1
            continue
        kept.append(promise)
    tokens = int(call_usage.get("total_tokens") or 0)
    if cache is not None:
        cache.put(
            "guidance_llm",
            symbol,
            url,
            "v1",
            {"promises": kept, "dropped": dropped, "usage": call_usage},
        )
    return kept, False, tokens, dropped, ""


def _clean_promise(raw: dict, by_page: dict, url: str) -> dict | None:
    if not isinstance(raw, dict):
        return None
    try:
        page = int(raw.get("page") or 0)
    except (TypeError, ValueError):
        return None
    text = by_page.get(page)
    evidence = " ".join(str(raw.get("evidence") or "").split())
    if text is None or not on_page(evidence, text):
        return None
    words = evidence.split()
    if len(words) > 25:
        evidence = " ".join(words[:25])
        if not on_page(evidence, text):
            return None
    key = str(raw.get("metric_key") or "other")
    if key not in METRIC_KEYS:
        key = "other"
    low = _num(raw.get("target_low"))
    high = _num(raw.get("target_high"))
    direction = str(raw.get("direction") or "").lower()
    if direction not in ("up", "down"):
        direction = ""
    if low is None and high is None and not direction:
        low, high = apply_word_bands(evidence, None, None)
    if low is None and high is None and not direction:
        return None
    if re.search(r"remain positive|we are confident|optimistic", evidence, re.I) and low is None and high is None:
        return None
    horizon = str(raw.get("horizon") or "")
    if horizon not in ("quarter", "fiscal_year", "multi_year"):
        horizon = ""
    speaker = str(raw.get("speaker") or "").strip()
    if speaker and speaker.lower() not in text.lower():
        speaker = ""
    kind, end = _parse_period(str(raw.get("target_period") or ""))
    target_period = f"FY{end.year}" if kind == "fiscal_year" and end else (end.isoformat() if end else "")
    if horizon == "" and kind:
        horizon = kind
    return {
        "metric_key": key,
        "target_low": low,
        "target_high": high,
        "direction": direction,
        "horizon": horizon,
        "target_period": target_period,
        "speaker": speaker,
        "evidence": evidence,
        "page": page,
        "source_document": url,
    }


def _check_rows(promises: list[dict], quarters: list[dict]) -> list[dict]:
    judged = [judge_promise(promise, quarters) for promise in promises]
    return [row for row in judged if row is not None]


def _coverage(transcripts: dict, quarters: list[dict]) -> dict:
    found = [row for row in transcripts["quarters"] if row["status"] == "found"]
    audio = [row["period"] for row in transcripts["quarters"] if row["status"] == "audio_only"]
    missing = [row["period"] for row in transcripts["quarters"] if row["status"] == "not_found"]
    with_results = sum(1 for row in quarters if row.get("revenue") is not None)
    gaps = [
        {"period": row["period"], "why": "; ".join(row.get("flags") or [])}
        for row in quarters
        if row.get("revenue") is None
    ]
    note = ""
    if len(found) == 0:
        note = "No transcript was found, so there is nothing to judge."
    elif len(found) == 1:
        note = "Only one transcript in the last five quarters. Too thin to judge whether management keeps its word."
    elif with_results < 4:
        note = "Fewer than four quarters of results are in the series, so a full year cannot be checked."
    return {
        "transcripts_found": len(found),
        "transcripts_of": len(transcripts["quarters"]),
        "quarters_with_results": with_results,
        "quarters_of": len(quarters),
        "audio_only": audio,
        "missing_quarters": missing,
        "series_gaps": gaps,
        "note": note,
    }


def _snapshot(quarters: list[dict]) -> dict:
    latest = next((row for row in quarters if row.get("revenue") is not None), None)
    ttm_revenue = None
    ttm_pat = None
    ttm_margin = None
    ttm_note = ""
    if latest is not None:
        window = [day.isoformat() for day in quarter_ends(date.fromisoformat(latest["period"]), 4)]
        by_period = {row["period"]: row for row in quarters}
        block = [by_period.get(period) for period in window]
        missing = [period for period, row in zip(window, block) if row is None or row.get("revenue") is None or row.get("pat") is None]
        if missing:
            ttm_note = "TTM is blank because " + ", ".join(missing) + " has no quarter figures."
        else:
            ttm_revenue = round(sum(row["revenue"] for row in block), 2)
            ttm_pat = round(sum(row["pat"] for row in block), 2)
            ebitdas = [row.get("ebitda") for row in block]
            if all(value is not None for value in ebitdas) and ttm_revenue:
                ttm_margin = round(sum(ebitdas) / ttm_revenue * 100.0, 2)
    return {
        "latest_quarter": None if latest is None else latest["period"],
        "revenue": None if latest is None else latest.get("revenue"),
        "ebitda_margin_pct": None if latest is None else latest.get("ebitda_margin_pct"),
        "pat": None if latest is None else latest.get("pat"),
        "ttm_revenue": ttm_revenue,
        "ttm_pat": ttm_pat,
        "ttm_ebitda_margin_pct": ttm_margin,
        "ttm_note": ttm_note,
        "series": [
            {
                "period": row["period"],
                "revenue": row.get("revenue"),
                "ebitda": row.get("ebitda"),
                "ebitda_margin_pct": row.get("ebitda_margin_pct"),
                "pat": row.get("pat"),
                "basis": row.get("basis") or "",
                "flags": row.get("flags") or [],
            }
            for row in quarters
        ],
    }


def _verdict(symbol: str, coverage: dict, snapshot: dict, rows: list[dict], cache, usage: dict) -> str:
    slim = {
        "note": coverage["note"],
        "transcripts_found": coverage["transcripts_found"],
        "transcripts_of": coverage["transcripts_of"],
        "latest_quarter": snapshot["latest_quarter"],
        "rows": [
            {
                "promise": row["promise"],
                "period_promised": row["period_promised"],
                "actual": row["actual"],
                "status": row["status"],
                "note": row["note"],
            }
            for row in rows
        ],
    }
    fingerprint = hashlib.sha1(json.dumps(slim, sort_keys=True).encode()).hexdigest()[:16]
    if cache is not None:
        cached = cache.get("verdict_llm", symbol, fingerprint, "v1")
        if isinstance(cached, dict) and cached.get("line"):
            usage["verdict"]["cache_hits"] += 1
            return cached["line"]
    if coverage["transcripts_found"] == 0:
        line = coverage["note"]
        if cache is not None:
            cache.put("verdict_llm", symbol, fingerprint, "v1", {"line": line, "usage": {}})
        return line
    prompt = (
        "Write one plain sentence for a portfolio manager. Use only the JSON. "
        "Do not add a fact that is not in it. If the note says the history is too thin, say that. "
        "If promises are still open, say so. No advice.\n\n"
        + json.dumps(slim)
    )
    try:
        payload, call_usage = generate_json(prompt, VERDICT_SCHEMA, (FLASH, *FLASH_FALLBACKS))
    except RuntimeError as exc:
        return f"Verdict unavailable: {exc}"
    line = " ".join(str(payload.get("line") or "").split())
    usage["verdict"]["calls"] += 1
    usage["verdict"]["tokens"] += int(call_usage.get("total_tokens") or 0)
    usage["verdict"]["model"] = call_usage.get("model") or ""
    if cache is not None and line:
        cache.put("verdict_llm", symbol, fingerprint, "v1", {"line": line, "usage": call_usage})
    return line


def _fy_measure(key, year, by_period, direction, low, high):
    quarters = [
        date(year - 1, 6, 30),
        date(year - 1, 9, 30),
        date(year - 1, 12, 31),
        date(year, 3, 31),
    ]
    rows = [by_period.get(day.isoformat()) for day in quarters]
    if any(row is None or row.get("revenue") is None for row in rows):
        missing = [day.isoformat() for day, row in zip(quarters, rows) if row is None or row.get("revenue") is None]
        return None, "FY" + str(year) + " is missing " + ", ".join(missing) + ", so the year is not checked."
    if key == "ebitda_margin":
        if any(row.get("ebitda") is None for row in rows):
            return None, f"FY{year} EBITDA is missing in a quarter, so the margin is not checked."
        revenue = sum(row["revenue"] for row in rows)
        if not revenue:
            return None, f"FY{year} revenue is zero."
        level = round(sum(row["ebitda"] for row in rows) / revenue * 100.0, 2)
        if low is None and high is None and direction:
            base = _fy_margin(year - 1, by_period)
            if base is None:
                return None, f"FY{year - 1} is outside the series, so a change in margin cannot be checked."
            return round(level - base, 2), ""
        return level, ""
    current = _fy_sum(year, by_period, _field(key))
    base = _fy_sum(year - 1, by_period, _field(key))
    if current is None or base in (None, 0):
        return None, f"The year before FY{year} is outside the six-quarter series, so growth is not checked."
    return round((current / base - 1.0) * 100.0, 2), ""


def _quarter_measure(key, end: date, by_period, direction, low, high):
    row = by_period.get(end.isoformat())
    if row is None or row.get("revenue") is None:
        return None, f"{end.isoformat()} has no quarter figures."
    if key == "ebitda_margin":
        level = row.get("ebitda_margin_pct")
        if level is None:
            return None, f"{end.isoformat()} has no EBITDA margin."
        if low is None and high is None and direction:
            base = _margin_on(_shift_year(end), by_period)
            if base is None:
                return None, f"The year-ago margin for {end.isoformat()} is not in the series."
            return round(level - base, 2), ""
        return level, ""
    field = _field(key)
    current = row.get(field)
    base_row = by_period.get(_shift_year(end).isoformat())
    base = None if base_row is None else base_row.get(field)
    if current is None or base in (None, 0):
        return None, f"The year-ago {field} for {end.isoformat()} is not in the series."
    return round((current / base - 1.0) * 100.0, 2), ""


def _fy_sum(year: int, by_period, field: str):
    days = [date(year - 1, 6, 30), date(year - 1, 9, 30), date(year - 1, 12, 31), date(year, 3, 31)]
    total = 0.0
    for day in days:
        row = by_period.get(day.isoformat())
        if row is None or row.get(field) is None:
            return None
        total += row[field]
    return total


def _fy_margin(year: int, by_period):
    revenue = _fy_sum(year, by_period, "revenue")
    ebitda = _fy_sum(year, by_period, "ebitda")
    if revenue in (None, 0) or ebitda is None:
        return None
    return ebitda / revenue * 100.0


def _margin_on(day: date, by_period):
    row = by_period.get(day.isoformat())
    if row is None:
        return None
    return row.get("ebitda_margin_pct")


def _field(key: str) -> str:
    if key == "pat_growth":
        return "pat"
    if key == "ebitda_growth":
        return "ebitda"
    return "revenue"


def _latest(quarters: list[dict]) -> date | None:
    for row in quarters:
        if row.get("revenue") is not None:
            return date.fromisoformat(row["period"])
    return None


def _parse_period(value: str) -> tuple[str, date | None]:
    text = (value or "").upper().replace(" ", "")
    match = re.fullmatch(r"FY(\d{2,4})", text)
    if match:
        year = int(match.group(1))
        if year < 100:
            year += 2000
        return "fiscal_year", date(year, 3, 31)
    try:
        return "quarter", date.fromisoformat(value[:10])
    except ValueError:
        return "", None


def _promise_line(promise: dict, low, high) -> str:
    label = LABELS.get(promise["metric_key"], "Other")
    if low is not None and high is not None and abs(low - high) < 1e-6:
        target = f"{low:g}%"
    elif low is not None and high is not None:
        target = f"{low:g}–{high:g}%"
    elif low is not None:
        target = f"at least {low:g}%"
    elif high is not None:
        target = f"at most {high:g}%"
    elif promise.get("direction") == "up":
        target = "to rise"
    elif promise.get("direction") == "down":
        target = "to fall"
    else:
        target = "as stated"
    period = promise.get("target_period") or "an unnamed period"
    return f"{label} {target} for {period}"


def _next_quarter(day: date) -> date:
    month = day.month + 3
    year = day.year
    if month > 12:
        month -= 12
        year += 1
    last = {3: 31, 6: 30, 9: 30, 12: 31}[month]
    return date(year, month, last)


def _shift_year(day: date) -> date:
    try:
        return day.replace(year=day.year - 1)
    except ValueError:
        return date(day.year - 1, day.month, 28)


def _num(value) -> float | None:
    text = str(value or "").strip().replace("%", "").replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Promise Ledger for one or more NSE tickers")
    parser.add_argument("symbols", nargs="+")
    args = parser.parse_args()
    cache = FileCache()
    client = NSEClient(cache=cache)
    packets = [promise_ledger(symbol, client=client, cache=cache) for symbol in args.symbols]
    json.dump(packets, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
