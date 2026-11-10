"""Promise Ledger. Guidance comes from transcript pages. Delivery is arithmetic.

    python -m finn_core.ledger MARICO DMART

A cold ticker stops after a few uncached transcripts and returns progress
{stage, done, total}. Call it again to continue. Cached stages are free.
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
from finn_core.llm import FLASH, FLASH_LITE, generate_json
from finn_core.nse_client import NSEClient
from finn_core.series import quarterly_series

CHECKABLE = {"revenue_growth", "ebitda_margin", "ebitda_growth", "pat_growth"}
METRIC_KEYS = CHECKABLE | {"volume_growth", "capex"}
LOOKBACK = 7
SERIES_QUARTERS = 10
CHART_QUARTERS = 6
GUIDANCE_VERSION = "v2"
VERDICT_VERSION = "v2"
_FORWARD = re.compile(
    r"guidan\w*|expect\w*|target\w*|outlook|\baim(?:ing|ed)?\b|going forward|"
    r"next year|next quarter|coming quarter|full year|fy\s*'?\d{2}|\bcapex\b|volume growth|"
    r"double[- ]digit|mid[- ]teen|high[- ]teen|low[- ]teen|basis point",
    re.I,
)
_LOOKBACK_HINT = re.compile(r"fy\s*'?26|next quarter|coming quarter|subsequent quarter", re.I)
_WORD = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?%?")
_PART = re.compile(
    r"constant currency|portfolio|\bbrand\b|international|segment|division|category|"
    r"digital[- ]first|subsidiary|\bpiece\b|\bsku\b|\b(?!our\b)\w+\s+business",
    re.I,
)
_MOVEMENT = re.compile(r"increas|decreas|grow|decline|expand|reduc|higher|lower|improv", re.I)
_METRIC_WORDS = {
    "revenue_growth": re.compile(r"revenue|top[- ]line", re.I),
    "ebitda_margin": re.compile(r"margin|pbdit|ebitda", re.I),
    "ebitda_growth": re.compile(r"ebitda|operating profit|pbdit", re.I),
    "pat_growth": re.compile(r"\bpat\b|profit after tax|net profit|bottom[- ]line", re.I),
    "volume_growth": re.compile(r"\bvolume\b", re.I),
    "capex": re.compile(r"capex|capital expenditure", re.I),
}
_SCORED = {
    "delivered",
    "partly",
    "missed",
    "tracking_ahead",
    "tracking_on_track",
    "tracking_behind",
}
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
}


def promise_ledger(
    symbol: str,
    as_of: date | None = None,
    client=None,
    cache=None,
    max_guidance_calls: int = 3,
) -> dict:
    """One stage of the ledger. Uncached transcripts stop after max_guidance_calls."""
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

    transcripts = stage(
        "discover",
        lambda: find_transcripts(symbol, quarters=LOOKBACK, as_of=as_of, client=client, cache=cache),
    )
    series = stage(
        "series",
        lambda: quarterly_series(symbol, quarters=SERIES_QUARTERS, as_of=as_of, client=client, cache=cache),
    )
    promises, lookback, done, total = stage(
        "guidance",
        lambda: _guidance_rows(symbol, transcripts, cache, client, usage, max_guidance_calls),
    )
    checked = stage("check", lambda: _check_rows(promises, series["quarters"], as_of))
    rows, long_term, revisions = merge_rows(checked)
    covered = _coverage(transcripts, series["quarters"])
    shot = _snapshot(series["quarters"])
    complete = done >= total
    if complete:
        verdict = stage("verdict", lambda: _verdict(symbol, covered, rows, revisions, cache, usage))
        progress = {"stage": "complete", "done": total, "total": total}
    else:
        verdict = ""
        timing["verdict"] = 0.0
        progress = {"stage": "guidance", "done": done, "total": total}
    usage["total_tokens"] = usage["guidance"]["tokens"] + usage["verdict"]["tokens"]
    timing["total"] = round(sum(timing.values()), 2)
    return {
        "symbol": symbol,
        "coverage": covered,
        "lookback": lookback,
        "snapshot": shot,
        "rows": rows,
        "long_term_targets": long_term,
        "revisions": revisions,
        "verdict": verdict,
        "progress": progress,
        "timing": timing,
        "usage": usage,
    }


def select_pages(pages: list[dict], limit: int = 8) -> list[dict]:
    """Pages that contain forward-looking language, strongest first, then in page order."""
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
        snippet = surrounding(page.get("text") or "")[:2500]
        if chars + len(snippet) > 14000 and chosen:
            break
        chosen.append({"page": page.get("page"), "text": snippet, "full": page.get("text") or ""})
        chars += len(snippet)
    chosen.sort(key=lambda page: page["page"] or 0)
    return chosen


def surrounding(text: str) -> str:
    """The forward-looking sentence plus the sentence on either side."""
    parts = [part.strip() for part in re.split(r"(?<=[.!])\s+", text or "") if part.strip()]
    if not parts:
        return (text or "")[:2500]
    keep = set()
    for index, part in enumerate(parts):
        if _FORWARD.search(part):
            keep.update(range(max(0, index - 1), min(len(parts), index + 2)))
    if not keep:
        return (text or "")[:2500]
    return " ".join(parts[index] for index in sorted(keep))


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
        if abs(low - high) < 1e-6:
            if abs(actual - low) <= 1:
                return "delivered"
            return "missed"
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


def compare_tracking(actual: float, low: float | None, high: float | None) -> str:
    """How the year so far sits against the promised range."""
    if low is not None and high is not None and abs(low - high) < 1e-6:
        if abs(actual - low) <= 1:
            return "tracking_on_track"
        return "tracking_ahead" if actual > low else "tracking_behind"
    if low is not None and high is not None:
        if low <= actual <= high:
            return "tracking_on_track"
        return "tracking_ahead" if actual > high else "tracking_behind"
    if low is not None:
        if actual >= low + 2:
            return "tracking_ahead"
        if actual >= low:
            return "tracking_on_track"
        return "tracking_behind"
    if high is not None:
        if actual <= high:
            return "tracking_on_track"
        return "tracking_behind"
    return "pending"


def quote_check(evidence: str, low: float | None, high: float | None) -> str:
    """Whether each stated number is actually in the stored quote."""
    text = re.sub(r"\s*-\s*", "-", (evidence or "").lower())
    missing = []
    for value in (low, high):
        if value is None or _number_in_text(text, value) or _from_named_band(text, value):
            continue
        missing.append(f"{value:g}")
    if not missing:
        return "ok"
    return "Not in the quote: " + ", ".join(missing)


def judge_promise(promise: dict, quarters: list[dict], as_of: date | None = None) -> dict | None:
    """Fill actual and status. The model does not do this arithmetic."""
    as_of = as_of or date.today()
    by_period = {row["period"]: row for row in quarters}
    latest = _latest(quarters)
    evidence = promise.get("evidence") or ""
    key = promise.get("metric_key") or ""
    if key not in METRIC_KEYS:
        key = _infer_metric(evidence) or ""
    if key not in METRIC_KEYS:
        return None
    low, high = sanitize_bounds(evidence, promise.get("target_low"), promise.get("target_high"))
    direction = promise.get("direction") or ""
    if low is None and high is None and not _MOVEMENT.search(evidence):
        return None
    if _reported_result(evidence):
        return None
    bps = bool(re.search(r"basis point|\bbps\b", evidence, re.I))
    row = {
        "promise": _promise_line({"metric_key": key, "target_period": promise.get("target_period"), "direction": direction}, low, high, bps),
        "source_quote": evidence,
        "page": promise.get("page"),
        "source_document": promise.get("source_document"),
        "speaker": promise.get("speaker") or "",
        "period_promised": promise.get("target_period") or "",
        "actual": None,
        "actual_value": None,
        "actual_detail": "",
        "promised": _target_phrase(low, high, bps),
        "status": "not_checkable",
        "note": "",
        "quote_check": quote_check(evidence, low, high),
        "metric_key": key,
        "target_low": low,
        "target_high": high,
        "call_period": promise.get("call_period") or "",
        "call_date": promise.get("call_date") or "",
        "calls": [],
        "revisions": [],
    }
    if not _METRIC_WORDS[key].search(evidence):
        row["status"] = "low_confidence"
        row["note"] = "The quoted sentence does not name the metric."
        return row
    if _PART.search(evidence):
        row["status"] = "segment_level"
        row["note"] = "Constant-currency or a part of the business, not the consolidated figure."
        return row
    if key not in CHECKABLE:
        row["note"] = "Volume and capex cannot be verified from the quarterly series."
        return row
    if key == "ebitda_margin" and re.search(r"\bebit margin\b", evidence, re.I) and "ebitda" not in evidence.lower():
        row["status"] = "segment_level"
        row["note"] = "The quote is an EBIT margin, not the consolidated EBITDA margin."
        return row
    kind, end = _parse_period(promise.get("target_period") or "")
    if _is_long_term(end, promise.get("horizon") or "", as_of):
        row["status"] = "long_term"
        row["note"] = "More than three years out."
        return row
    if end is None:
        row["note"] = "The quote does not name a quarter or a fiscal year."
        return row
    if kind == "fiscal_year" and latest is not None and end > latest:
        measured, detail = _ytd_measure(key, end.year, latest, by_period, bps)
        if measured is None:
            row["status"] = "pending"
            row["note"] = detail
            return row
        row["status"] = compare_tracking(measured, low, high)
        row["actual_value"] = measured
        row["actual"] = _format_actual(measured, bps)
        row["actual_detail"] = detail
        row["note"] = detail
        return row
    if latest is None or end > latest:
        row["status"] = "pending"
        shown = latest.isoformat() if latest else "none"
        row["note"] = f"The period ends {end.isoformat()}, after the latest reported quarter {shown}."
        return row
    if kind == "fiscal_year":
        measured, note = _fy_measure(key, end.year, by_period, direction, low, high)
    else:
        measured, note = _quarter_measure(key, end, by_period, direction, low, high)
    if measured is None:
        row["status"] = "pending" if "outside" in note or "missing" in note else "not_checkable"
        row["note"] = note
        return row
    status = compare_target(measured, low, high, direction if low is None and high is None else "")
    if status == "not_checkable":
        row["note"] = "The quote has no number and no clear direction."
        return row
    row["status"] = status
    row["actual_value"] = measured
    row["actual"] = f"{measured:g}%"
    row["actual_detail"] = note
    return row


def merge_rows(rows: list[dict]) -> tuple[list[dict], list[dict], dict]:
    """One row per metric and period. Repeats list the calls. A changed number is a revision."""
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        confidence = "low" if row["status"] == "low_confidence" else "named"
        groups.setdefault((row["metric_key"], row["period_promised"], _unit(row), confidence), []).append(row)
    current = []
    long_term = []
    summary = {"raised": 0, "cut": 0, "maintained": 0, "items": []}
    for items in groups.values():
        items.sort(key=lambda item: (item.get("call_date") or "", item.get("page") or 0))
        named = [item for item in items if item["status"] != "low_confidence"]
        latest = dict(named[-1] if named else items[-1])
        sequence = []
        previous = None
        for item in items:
            signature = (item.get("target_low"), item.get("target_high"))
            change = _change(previous, signature)
            sequence.append(
                {
                    "date": item.get("call_date") or "",
                    "call_period": item.get("call_period") or "",
                    "value": item.get("promised") or "",
                    "change": change,
                    "page": item.get("page"),
                    "quote": item.get("source_quote") or "",
                }
            )
            if change in summary:
                summary[change] += 1
            previous = signature
        latest["calls"] = [
            {
                "date": item.get("call_date") or "",
                "call_period": item.get("call_period") or "",
                "page": item.get("page"),
                "quote": item.get("source_quote") or "",
                "document": _file_name(item.get("source_document") or ""),
            }
            for item in items
        ]
        latest["revisions"] = sequence if len(items) > 1 else []
        if len(items) > 1:
            summary["items"].append(
                {
                    "promise": latest["promise"],
                    "period": latest["period_promised"],
                    "sequence": [{"date": step["date"], "value": step["value"], "change": step["change"]} for step in sequence],
                }
            )
        if latest["status"] == "long_term":
            long_term.append(latest)
        else:
            current.append(latest)
    current.sort(key=lambda item: (_status_rank(item["status"]), item.get("period_promised") or ""))
    return current, long_term, summary


def _unit(row: dict) -> str:
    promised = row.get("promised") or ""
    return "bps" if "bps" in promised else "pct"


def _near_hint(text: str) -> bool:
    """FY26 or 'next quarter' within a short span of a forward-looking word."""
    for match in _LOOKBACK_HINT.finditer(text or ""):
        window = text[max(0, match.start() - 180): match.end() + 180]
        if _FORWARD.search(window):
            return True
    return False


def _reported_result(evidence: str) -> bool:
    """A sentence about the quarter just reported, with no forward word, is not guidance."""
    if re.search(r"guidan|expect|target|outlook|\baim\b|aspire|maintain|going forward|next year|full year|this year", evidence or "", re.I):
        return False
    return re.search(
        r"\b(delivered|have gone|has gone|have achieved|was |were |stood at|we've got|we got|driven by)\b",
        evidence or "",
        re.I,
    ) is not None


def _change(previous, signature) -> str:
    if previous is None:
        return "set"
    old, new = _mid(previous), _mid(signature)
    if old is None or new is None or abs(new - old) < 0.5:
        return "maintained"
    return "raised" if new > old else "cut"


def _mid(signature) -> float | None:
    low, high = signature
    if low is not None and high is not None:
        return (low + high) / 2
    return low if low is not None else high


def _status_rank(status: str) -> int:
    order = {
        "missed": 0,
        "tracking_behind": 1,
        "partly": 2,
        "tracking_on_track": 3,
        "delivered": 4,
        "tracking_ahead": 5,
        "pending": 6,
        "low_confidence": 7,
        "segment_level": 8,
        "not_checkable": 9,
    }
    return order.get(status, 10)


def _guidance_rows(symbol, transcripts, cache, client, usage, max_calls: int):
    found = [item for item in transcripts["quarters"] if item["status"] == "found" and item.get("url")]
    promises = []
    done = 0
    new_calls = 0
    pages_hint = 0
    pages_dropped = []
    for item in found:
        document = extract_pdf(symbol, item["url"], client=client, cache=cache)
        pages = document.get("pages") or []
        selected = select_pages(pages)
        sent = {page["page"] for page in selected}
        for page in pages:
            text = page.get("text") or ""
            mentions = _near_hint(text)
            if mentions and page.get("page") not in sent:
                pages_hint += 1
                pages_dropped.append({"period": item["period"], "page": page.get("page")})
            elif mentions:
                pages_hint += 1
        cached = cache.get("guidance_llm", symbol, item["url"], GUIDANCE_VERSION) if cache is not None else None
        if isinstance(cached, dict) and "promises" in cached:
            batch = cached["promises"]
            usage["guidance"]["cache_hits"] += 1
            usage["guidance"]["dropped"] += int(cached.get("dropped") or 0)
            done += 1
        elif max_calls and new_calls >= max_calls:
            continue
        else:
            new_calls += 1
            batch, hit, tokens, dropped, error = _promises_for_document(symbol, item, document, cache, selected)
            bucket = usage["guidance"]
            if error:
                bucket.setdefault("errors", []).append(f"{item['period']}: {error}")
            bucket["dropped"] += dropped
            if tokens:
                bucket["calls"] += 1
                bucket["tokens"] += tokens
            if not error:
                done += 1
        for promise in batch:
            stamped = dict(promise)
            stamped["call_period"] = item["period"]
            stamped["call_date"] = item.get("date") or item["period"]
            promises.append(stamped)
    fy26 = sum(1 for promise in promises if promise.get("target_period") == "FY2026")
    next_quarter = sum(1 for promise in promises if _is_next_quarter(promise))
    lookback = {
        "quarters": LOOKBACK,
        "fy26_statements": fy26,
        "next_quarter_statements": next_quarter,
        "pages_mentioning_fy26_or_next_quarter": pages_hint,
        "pages_dropped_by_prefilter": len(pages_dropped),
        "dropped_pages": pages_dropped[:12],
    }
    return promises, lookback, done, len(found)


def _promises_for_document(symbol, item, document, cache, pages) -> tuple[list[dict], bool, int, int, str]:
    url = item["url"]
    full = {page["page"]: page.get("text") or "" for page in document.get("pages") or []}
    if not pages or document.get("scanned"):
        if cache is not None:
            cache.put("guidance_llm", symbol, url, GUIDANCE_VERSION, {"promises": [], "dropped": 0, "usage": {}})
        return [], False, 0, 0, ""
    call_period = date.fromisoformat(item["period"])
    fy = call_period.year if call_period.month == 3 else call_period.year + 1
    following = _next_quarter(call_period)
    body = "\n\n".join(f"PAGE {page['page']}\n{page['text']}" for page in pages)
    prompt = (
        "Extract explicit numeric guidance spoken by management. "
        f"The call is about the quarter ended {call_period.isoformat()}, inside FY{fy} "
        f"(the year ending 31 March {fy}). Next quarter ends {following.isoformat()}. "
        f"Next fiscal year is FY{fy + 1}.\n"
        "Each evidence sentence must itself name the metric in plain words: revenue, EBITDA, "
        "margin, PAT, volume, or capex. A neighbouring sentence does not count. "
        "Skip a sentence that only gives a percentage. Skip 'we remain positive'. "
        "Skip constant-currency, portfolio, brand, international, and segment remarks. "
        "evidence is consecutive words from one page, 25 words or fewer. "
        "metric_key is revenue_growth, ebitda_margin, ebitda_growth, pat_growth, volume_growth, or capex. "
        "horizon is quarter, fiscal_year, or multi_year. "
        "target_period is YYYY-MM-DD or FY####. "
        "target_low and target_high are numbers printed in that sentence, or empty. "
        "A basis-point range stays in basis points. direction is up, down, or empty. "
        "At most 6 promises. Use nothing beyond these pages.\n\n"
        + body
    )
    try:
        payload, call_usage = generate_json(prompt, GUIDANCE_SCHEMA)
    except RuntimeError as exc:
        return [], False, 0, 0, str(exc)
    kept = []
    dropped = 0
    for raw in payload.get("promises") or []:
        promise = _clean_promise(raw, full, url)
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
            GUIDANCE_VERSION,
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
    key = str(raw.get("metric_key") or "")
    if key not in METRIC_KEYS:
        key = _infer_metric(evidence) or ""
    if key not in METRIC_KEYS:
        return None
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


def _infer_metric(evidence: str) -> str | None:
    hits = [key for key, pattern in _METRIC_WORDS.items() if pattern.search(evidence or "")]
    if len(hits) == 1:
        return hits[0]
    return None


def _check_rows(promises: list[dict], quarters: list[dict], as_of: date) -> list[dict]:
    judged = [judge_promise(promise, quarters, as_of) for promise in promises]
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
    elif len(found) < 3:
        word = "transcript" if len(found) == 1 else "transcripts"
        note = f"Only {len(found)} {word} in the last seven quarters. Too thin to judge whether management keeps its word."
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
    chart = [row for row in quarters if row.get("period")][:CHART_QUARTERS]
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
            for row in chart
        ],
    }


def _verdict(symbol: str, coverage: dict, rows: list[dict], revisions: dict, cache, usage: dict) -> str:
    scored = [
        {
            "promise": row["promise"],
            "period_promised": row["period_promised"],
            "actual": row["actual"],
            "promised": row["promised"],
            "status": row["status"],
            "detail": row.get("actual_detail") or row.get("note") or "",
        }
        for row in rows
        if row["status"] in _SCORED
    ]
    slim = {
        "thin_history": coverage["note"],
        "facts": scored[:8],
    }
    fingerprint = hashlib.sha1(json.dumps(slim, sort_keys=True).encode()).hexdigest()[:16]
    if cache is not None:
        cached = cache.get("verdict_llm", symbol, fingerprint, VERDICT_VERSION)
        if isinstance(cached, dict) and cached.get("line"):
            usage["verdict"]["cache_hits"] += 1
            usage["verdict"]["model"] = (cached.get("usage") or {}).get("model") or ""
            return cached["line"]
    if coverage["transcripts_found"] == 0 or not scored:
        line = coverage["note"] or "No consolidated guidance in these transcripts can be checked against the series."
        if cache is not None:
            cache.put("verdict_llm", symbol, fingerprint, VERDICT_VERSION, {"line": line, "usage": {}})
        return line
    prompt = (
        "Write one or two sentences. Lead with the actual number against the promised number. "
        "Use only these facts. If thin_history is not empty, include it. "
        "Do not give advice and do not summarise how many times guidance was edited.\n\n"
        + json.dumps(slim)
    )
    try:
        payload, call_usage = generate_json(
            prompt,
            VERDICT_SCHEMA,
            (FLASH, FLASH_LITE),
            timeout=20,
            attempts=1,
        )
    except RuntimeError as exc:
        return f"Verdict unavailable: {exc}"
    line = " ".join(str(payload.get("line") or "").split())
    usage["verdict"]["calls"] += 1
    usage["verdict"]["tokens"] += int(call_usage.get("total_tokens") or 0)
    usage["verdict"]["model"] = call_usage.get("model") or ""
    if cache is not None and line:
        cache.put("verdict_llm", symbol, fingerprint, VERDICT_VERSION, {"line": line, "usage": call_usage})
    return line


def _fy_measure(key, year, by_period, direction, low, high):
    quarters = _fy_quarters(year)
    rows = [by_period.get(day.isoformat()) for day in quarters]
    if any(row is None or row.get("revenue") is None for row in rows):
        missing = [day.isoformat() for day, row in zip(quarters, rows) if row is None or row.get("revenue") is None]
        return None, "FY" + str(year) + " is missing " + ", ".join(missing) + ", so the year is not checked."
    if key == "ebitda_margin":
        level = _span_margin(quarters, by_period)
        if level is None:
            return None, f"FY{year} EBITDA is missing in a quarter, so the margin is not checked."
        if low is None and high is None and direction:
            base = _fy_margin(year - 1, by_period)
            if base is None:
                return None, f"FY{year - 1} is outside the series, so a change in margin cannot be checked."
            return round(level - base, 2), ""
        return level, ""
    current = _fy_sum(year, by_period, _field(key))
    base = _fy_sum(year - 1, by_period, _field(key))
    if current is None or base in (None, 0):
        return None, f"The year before FY{year} is outside the series, so growth is not checked."
    return round((current / base - 1.0) * 100.0, 2), ""


def _ytd_measure(key, year, latest: date, by_period, bps: bool):
    days = [day for day in _fy_quarters(year) if day <= latest]
    if not days:
        return None, f"No quarter of FY{year} has been reported."
    prior = [_shift_year(day) for day in days]
    label = {1: "Q1", 2: "H1", 3: "9M"}[len(days)]
    if key == "ebitda_margin":
        current = _span_margin(days, by_period)
        base = _span_margin(prior, by_period)
        if current is None:
            return None, f"{label} FY{year} is missing a quarter, so the margin is not tracked."
        if base is None:
            return None, f"The year-ago {label} is not in the series, so the margin is not tracked."
        change = round((current - base) * 100)
        detail = (
            f"{label} FY{year} EBITDA margin {current:.2f}% versus {base:.2f}% a year earlier ({change:+d} bps)"
        )
        return (change if bps else current), detail
    field = _field(key)
    current = _span_sum(days, by_period, field)
    base = _span_sum(prior, by_period, field)
    if current is None:
        return None, f"{label} FY{year} is missing a quarter, so growth is not tracked."
    if base in (None, 0):
        return None, f"The year-ago {label} is not in the series, so growth is not tracked."
    growth = round((current / base - 1.0) * 100.0, 2)
    name = {"ebitda": "EBITDA", "pat": "PAT", "revenue": "revenue"}[field]
    detail = f"{label} FY{year} {name} {current:,.2f} versus {label} FY{year - 1} {name} {base:,.2f}"
    return growth, detail


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


def _fy_quarters(year: int) -> list[date]:
    return [date(year - 1, 6, 30), date(year - 1, 9, 30), date(year - 1, 12, 31), date(year, 3, 31)]


def _span_sum(days: list[date], by_period, field: str):
    total = 0.0
    for day in days:
        row = by_period.get(day.isoformat())
        if row is None or row.get(field) is None or row.get("revenue") is None:
            return None
        total += row[field]
    return round(total, 2)


def _span_margin(days: list[date], by_period):
    revenue = _span_sum(days, by_period, "revenue")
    ebitda = _span_sum(days, by_period, "ebitda")
    if revenue in (None, 0) or ebitda is None:
        return None
    return round(ebitda / revenue * 100.0, 2)


def _fy_sum(year: int, by_period, field: str):
    return _span_sum(_fy_quarters(year), by_period, field)


def _fy_margin(year: int, by_period):
    return _span_margin(_fy_quarters(year), by_period)


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


def _is_long_term(end: date | None, horizon: str, as_of: date) -> bool:
    if horizon == "multi_year" and end is None:
        return True
    if end is None:
        return False
    return end > _add_years(as_of, 3)


def _is_next_quarter(promise: dict) -> bool:
    kind, end = _parse_period(promise.get("target_period") or "")
    call = promise.get("call_period") or ""
    if kind != "quarter" or end is None or not call:
        return False
    try:
        return end == _next_quarter(date.fromisoformat(call))
    except ValueError:
        return False


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


def _promise_line(promise: dict, low, high, bps: bool = False) -> str:
    label = LABELS.get(promise["metric_key"], promise["metric_key"])
    target = _target_phrase(low, high, bps)
    if target == "a direction only":
        if promise.get("direction") == "down":
            target = "to fall"
        elif promise.get("direction") == "up":
            target = "to rise"
    period = promise.get("target_period") or "an unnamed period"
    return f"{label} {target} for {period}"


def _target_phrase(low, high, bps: bool = False) -> str:
    unit = " bps" if bps else "%"
    if low is not None and high is not None and abs(low - high) < 1e-6:
        return f"{low:g}{unit}"
    if low is not None and high is not None:
        return f"{low:g}–{high:g}{unit}"
    if low is not None:
        return f"at least {low:g}{unit}"
    if high is not None:
        return f"at most {high:g}{unit}"
    return "a direction only"


def _format_actual(value: float, bps: bool) -> str:
    if bps:
        return f"{value:+.0f} bps"
    return f"{value:g}%"


def _number_in_text(text: str, value: float) -> bool:
    shown = f"{value:g}"
    return re.search(rf"(?<!\d){re.escape(shown)}(?:\s*(%|percent))?", text) is not None


def _from_named_band(text: str, value: float) -> bool:
    bands = {
        "double-digit": (10,),
        "double digit": (10,),
        "high-teen": (17, 19),
        "high teen": (17, 19),
        "mid-teen": (13, 16),
        "mid teen": (13, 16),
        "low-teen": (10, 13),
        "low teen": (10, 13),
        "high single": (7, 9),
    }
    for phrase, values in bands.items():
        if phrase in text and value in values:
            return True
    return False


def _written_percent(text: str, value: float | None) -> bool:
    if value is None:
        return False
    return re.search(rf"(?<!\d){re.escape(f'{value:g}')}\s*(%|percent)", text) is not None


def sanitize_bounds(evidence: str, low: float | None, high: float | None) -> tuple[float | None, float | None]:
    """A crore target or a '3x' is not a percent. Basis points and named bands are kept."""
    text = (evidence or "").lower()
    if re.search(r"basis point|\bbps\b", text):
        return low, high
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


def _add_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return date(day.year + years, day.month, 28)


def _file_name(url: str) -> str:
    return (url or "").rsplit("/", 1)[-1]


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
    packets = []
    for symbol in args.symbols:
        packet = {"progress": {"stage": "guidance", "done": 0, "total": 1}}
        stalls = 0
        while packet["progress"]["stage"] != "complete":
            before = packet["progress"]["done"]
            packet = promise_ledger(symbol, client=client, cache=cache)
            if packet["progress"]["done"] <= before:
                stalls += 1
                if stalls >= 2:
                    break
        packets.append(packet)
    json.dump(packets, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
