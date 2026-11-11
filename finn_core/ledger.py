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

from finn_core.cache import FileCache, open_cache
from finn_core.documents import extract_pdf, find_transcripts, quarter_ends
from finn_core.llm import (
    FLASH,
    FLASH_FALLBACKS,
    FLASH_LITE,
    GROQ_EXTRACTION,
    GROQ_VERIFY,
    QuotaError,
    generate_json,
)
from finn_core.nse_client import NSEClient
from finn_core.series import quarterly_series

CHECKABLE = {"revenue_growth", "ebitda_margin", "ebit_margin", "ebitda_growth", "pat_growth"}
MARGIN_KEYS = {"ebitda_margin", "ebit_margin"}
METRIC_KEYS = CHECKABLE | {"volume_growth", "capex"}
LOOKBACK = 7
SERIES_QUARTERS = 10
CHART_QUARTERS = 6
GUIDANCE_VERSION = "v3"
VERDICT_VERSION = "v2"
VERIFY_VERSION = "v2"
_FORWARD = re.compile(
    r"guidan\w*|expect\w*|target\w*|outlook|\baim(?:ing|ed)?\b|going forward|"
    r"next year|next quarter|coming quarter|full year|fy\s*'?\d{2}|\bcapex\b|volume growth|"
    r"double[- ]digit|mid[- ]teen|high[- ]teen|low[- ]teen|basis point",
    re.I,
)
_LOOKBACK_HINT = re.compile(r"fy\s*'?26|next quarter|coming quarter|subsequent quarter", re.I)
_WORD = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?%?")
_PART = re.compile(
    r"portfolio|\bbrand\b|international|segment|division|category|"
    r"digital[- ]first|subsidiary|\bpiece\b|\bsku\b|\b(?!our\b)\w+\s+business",
    re.I,
)
UNITS = {"percent", "bps", "currency_usd", "currency_inr", "count", "ratio", "other"}
_MOVEMENT = re.compile(r"increas|decreas|grow|decline|expand|reduc|higher|lower|improv", re.I)
_METRIC_WORDS = {
    "revenue_growth": re.compile(r"revenue|top[- ]line", re.I),
    "ebitda_margin": re.compile(r"\bebitda\b|\bpbdit\b", re.I),
    "ebit_margin": re.compile(r"operating margin|\bebit margin\b", re.I),
    "ebitda_growth": re.compile(r"ebitda|operating profit|pbdit", re.I),
    "pat_growth": re.compile(r"\bpat\b|profit after tax|net profit|bottom[- ]line", re.I),
    "volume_growth": re.compile(r"\bvolume\b", re.I),
    "capex": re.compile(r"capex|capital expenditure", re.I),
}
_VAGUE_HORIZON = re.compile(r"mid[- ]term|medium[- ]term|near[- ]term|long[- ]term", re.I)
_EXPLICIT_FY = re.compile(
    r"\bFY\s*'?\s*(\d{2,4})\b|financial year\s*'?\s*(\d{2,4})|fiscal year\s*'?\s*(\d{2,4})",
    re.I,
)
_THIS_YEAR = re.compile(r"\b(?:this year|full year|current year|the financial year)\b", re.I)
_NEXT_YEAR = re.compile(r"\bnext year\b|\b(?:after|beyond|following)\s+this year\b", re.I)
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
                    "scope": {"type": "STRING"},
                    "scope_name": {"type": "STRING"},
                    "unit": {"type": "STRING"},
                    "kind": {"type": "STRING"},
                    "basis": {"type": "STRING"},
                    "conditional_on": {"type": "STRING"},
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
                    "scope",
                    "scope_name",
                    "unit",
                    "kind",
                    "basis",
                    "conditional_on",
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
    "ebit_margin": "EBIT margin",
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
    stop_after: str = "complete",
) -> dict:
    """One stage of the ledger. Uncached transcripts stop after max_guidance_calls."""
    as_of = as_of or date.today()
    symbol = symbol.upper()
    client = client or NSEClient(cache=cache)
    cache = cache if cache is not None else client.cache
    timing = {}
    usage = {
        "guidance": {"calls": 0, "cache_hits": 0, "tokens": 0, "dropped": 0, "model": ""},
        "verdict": {"calls": 0, "cache_hits": 0, "tokens": 0, "model": ""},
        "verify": {"calls": 0, "cache_hits": 0, "tokens": 0, "model": ""},
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
    if stop_after == "discover":
        found = sum(1 for row in transcripts["quarters"] if row["status"] == "found")
        return _stopped(
            symbol,
            transcripts,
            None,
            {"stage": "discover", "done": found, "total": len(transcripts["quarters"])},
            timing,
            usage,
        )
    series = stage(
        "series",
        lambda: quarterly_series(symbol, quarters=SERIES_QUARTERS, as_of=as_of, client=client, cache=cache),
    )
    if stop_after == "series":
        covered = _coverage(transcripts, series["quarters"])
        timing["total"] = round(sum(timing.values()), 2)
        return _stopped(
            symbol,
            transcripts,
            series,
            {"stage": "series", "done": covered["quarters_with_results"], "total": covered["quarters_of"]},
            timing,
            usage,
            covered=covered,
        )
    promises, lookback, done, total = stage(
        "guidance",
        lambda: _guidance_rows(symbol, transcripts, cache, client, usage, max_guidance_calls),
    )
    checked = stage("check", lambda: _check_rows(promises, series["quarters"], as_of))
    checked = stage("verify", lambda: verify_scored(symbol, checked, cache, usage))
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
    usage["total_tokens"] = usage["guidance"]["tokens"] + usage["verdict"]["tokens"] + usage["verify"]["tokens"]
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


def _stopped(symbol, transcripts, series, progress, timing, usage, covered=None) -> dict:
    quarters = [] if series is None else series.get("quarters") or []
    if covered is None:
        covered = _coverage(transcripts, quarters)
    usage["total_tokens"] = usage["guidance"]["tokens"] + usage["verdict"]["tokens"]
    timing["total"] = round(sum(value for key, value in timing.items() if key != "total"), 2)
    return {
        "symbol": symbol,
        "coverage": covered,
        "lookback": {},
        "snapshot": _snapshot(quarters) if quarters else {},
        "rows": [],
        "long_term_targets": [],
        "revisions": {"raised": 0, "cut": 0, "maintained": 0, "items": []},
        "verdict": "",
        "progress": progress,
        "timing": timing,
        "usage": usage,
    }


def select_pages(pages: list[dict], limit: int = 12) -> list[dict]:
    """Up to 12 pages, ranked by forward-looking words per word of text."""
    scored = []
    for page in pages:
        text = page.get("text") or ""
        hits = len(_FORWARD.findall(text))
        if hits:
            scored.append((hits / max(1, len(text.split())), hits, page))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    chosen = []
    chars = 0
    for _, _, page in scored[:limit]:
        snippet = surrounding(page.get("text") or "")[:2500]
        if chars + len(snippet) > 32000 and chosen:
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


def quote_check(evidence: str, low: float | None, high: float | None, unit: str | None = None) -> str:
    """Whether these numbers, and their unit, are actually in the stored quote."""
    if low is None and high is None:
        return "ok"
    stated = read_unit(evidence, low, high)
    if unit and stated != unit:
        return f"The quote states {stated}, not {unit}."
    if stated == "other":
        return "The quote does not state the unit."
    text = re.sub(r"\s*-\s*", "-", (evidence or "").lower())
    missing = []
    for value in (low, high):
        if value is None or _number_in_text(text, value) or _from_named_band(text, value):
            continue
        missing.append(f"{value:g}")
    if not missing:
        return "ok"
    return "Not in the quote: " + ", ".join(missing)


def read_unit(evidence: str, low: float | None, high: float | None) -> str:
    """Unit of these numbers, read from the quote. A model label does not decide it."""
    text = re.sub(r"\s*-\s*", "-", (evidence or "").lower())
    spans = []
    for value in (low, high):
        spans.extend(_number_spans(text, value))
    if not spans:
        return "percent" if _from_named_band(text, low) or _from_named_band(text, high) else "other"
    start = max(0, min(span[0] for span in spans) - 20)
    end = min(len(text), max(span[1] for span in spans) + 32)
    window = text[start:end]
    if re.search(r"\$|\busd\b|u\.s\. dollar|us dollar|\bdollars?\b", window):
        return "currency_usd"
    if re.search(r"basis points?|\bbps\b", window):
        return "bps"
    if re.search(r"%|percent", window):
        return "percent"
    if re.search(r"\binr\b|₹|\bcrores?\b|\blakhs?\b|\brupees?\b|\brs\.?\b", window):
        return "currency_inr"
    if re.search(r"\d+(?:\.\d+)?\s*x\b", window):
        return "ratio"
    if _from_named_band(text, low) or _from_named_band(text, high):
        return "percent"
    return "other"


def read_kind(unit: str, metric_key: str, evidence: str) -> str:
    """A growth rate or a basis-point move is a change. An amount or a margin percent is a level."""
    if unit == "bps":
        return "change"
    if unit in ("currency_usd", "currency_inr", "count", "ratio"):
        return "level"
    if unit == "percent" and metric_key in ("revenue_growth", "ebitda_growth", "pat_growth", "volume_growth"):
        return "change"
    if unit == "percent" and re.search(r"(expand|improv|increase|decrease|reduc).{0,40}(percent|%)", evidence or "", re.I):
        return "change"
    return "level"


def judge_promise(promise: dict, quarters: list[dict], as_of: date | None = None) -> dict | None:
    """Fill actual and status. The model does not do this arithmetic."""
    as_of = as_of or date.today()
    by_period = {row["period"]: row for row in quarters}
    latest = _latest(quarters)
    evidence = promise.get("evidence") or ""
    passage = promise.get("passage") or evidence
    key = promise.get("metric_key") or ""
    if key not in METRIC_KEYS:
        key = _infer_metric(evidence) or ""
    key, unclear_margin = _align_metric(key, evidence, passage)
    if key not in METRIC_KEYS:
        return None
    raw_low, raw_high = _num(promise.get("target_low")), _num(promise.get("target_high"))
    seen = read_unit(evidence, raw_low, raw_high)
    if seen in ("currency_usd", "currency_inr") and (_number_spans(evidence.lower(), raw_low) or _number_spans(evidence.lower(), raw_high)):
        low, high = raw_low, raw_high
    else:
        low, high = sanitize_bounds(evidence, raw_low, raw_high, key)
    unit = read_unit(evidence, low, high)
    kind = read_kind(unit, key, evidence)
    direction = promise.get("direction") or ""
    if low is None and high is None and not _MOVEMENT.search(evidence):
        return None
    if _reported_result(evidence) and not _other_margin(evidence):
        return None
    bps = unit == "bps"
    row = {
        "promise": _promise_line(
            {"metric_key": key, "target_period": promise.get("target_period"), "direction": direction},
            low,
            high,
            unit,
            evidence,
        ),
        "source_quote": evidence,
        "page": promise.get("page"),
        "source_document": promise.get("source_document"),
        "speaker": promise.get("speaker") or "",
        "period_promised": promise.get("target_period") or "",
        "actual": None,
        "actual_value": None,
        "actual_detail": "",
        "promised": _target_phrase(low, high, unit, evidence),
        "status": "not_checkable",
        "note": "",
        "quote_check": quote_check(evidence, low, high, unit),
        "unit": unit,
        "kind": kind,
        "passage": passage,
        "basis": read_basis(passage, promise.get("basis"), evidence),
        "conditional_on": promise.get("conditional_on") or None,
        "basis_note": promise.get("basis_note") or "",
        "caveat": "",
        "definition_note": _definition_note(key, evidence),
        "scope": promise.get("scope") or "consolidated",
        "scope_name": promise.get("scope_name") or "",
        "metric_key": key,
        "target_low": low,
        "target_high": high,
        "call_period": promise.get("call_period") or "",
        "call_date": promise.get("call_date") or "",
        "calls": [],
        "revisions": [],
    }
    if row["scope"] in ("segment", "geography", "other"):
        named = row["scope_name"] or row["scope"]
        row["status"] = "segment_level"
        row["note"] = f"{named} guidance is not compared with the consolidated series."
        return row
    if _explicit_period(evidence, row["passage"], promise.get("call_period") or "") == "vague":
        row["status"] = "long_term"
        row["period_promised"] = ""
        row["promise"] = _promise_line(
            {"metric_key": key, "target_period": "a longer horizon", "direction": direction},
            low,
            high,
            unit,
            evidence,
        )
        row["note"] = "The passage says mid-term or near-term, not a fiscal year or a quarter."
        if unclear_margin:
            row["note"] += " The passage does not say whether this margin is EBITDA or EBIT."
        return row
    if unclear_margin:
        _not_scored(row, "The passage does not say whether this margin is EBITDA or EBIT.")
        return row
    if re.search(r"gross margin", evidence, re.I) and _unit_block(row, key, bps):
        return row
    if not _METRIC_WORDS[key].search(evidence):
        row["status"] = "low_confidence"
        row["note"] = "The quoted sentence does not name the metric."
        return row
    if unit == "currency_usd":
        _not_scored(row, "Guided in US dollars for the IT services segment; our series is consolidated INR.")
        return row
    if re.search(r"constant[- ]currency", evidence, re.I):
        _not_scored(row, "Constant-currency guidance is not the consolidated rupee series.")
        return row
    blocked = _unit_block(row, key, bps)
    if blocked:
        return row
    if row["scope"] in ("segment", "geography", "other"):
        row["status"] = "segment_level"
        named = row["scope_name"] or row["scope"]
        row["note"] = f"{named} guidance is not compared with the consolidated series."
        return row
    if _PART.search(evidence):
        row["status"] = "segment_level"
        row["note"] = "Constant-currency or a part of the business, not the consolidated figure."
        return row
    if key not in CHECKABLE:
        row["note"] = "Volume and capex cannot be verified from the quarterly series."
        return row
    refused = _refuse_unit(row, key)
    if refused:
        return row
    stated = _explicit_period(evidence, row["passage"], promise.get("call_period") or "")
    if stated is not None and stated != "vague":
        kind, end = stated
        row["period_promised"] = f"FY{end.year}" if kind == "fiscal_year" else end.isoformat()
        row["promise"] = _promise_line(
            {"metric_key": key, "target_period": row["period_promised"], "direction": direction},
            low,
            high,
            unit,
            evidence,
        )
    else:
        kind, end = _parse_period(promise.get("target_period") or "")
    if _is_long_term(end, promise.get("horizon") or "", as_of):
        row["status"] = "long_term"
        row["note"] = "More than three years out."
        return row
    if end is None:
        row["note"] = "The quote does not name a quarter or a fiscal year."
        return row
    if kind == "fiscal_year" and latest is not None and end > latest:
        measured, detail, unit = _ytd_measure(key, end.year, latest, by_period, bps)
        if measured is None:
            row["status"] = "pending"
            row["note"] = detail
            return row
        if _reject_scored(row, key, bps, measured, unit, direction):
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
        measured, note, unit = _fy_measure(key, end.year, by_period, direction, low, high, bps)
    else:
        measured, note, unit = _quarter_measure(key, end, by_period, direction, low, high, bps)
    if measured is None:
        row["status"] = "pending" if "outside" in note or "missing" in note else "not_checkable"
        row["note"] = note
        return row
    if _reject_scored(row, key, bps, measured, unit, direction):
        return row
    status = compare_target(measured, low, high, direction if low is None and high is None else "")
    if status == "not_checkable":
        row["note"] = "The quote has no number and no clear direction."
        return row
    row["status"] = status
    row["actual_value"] = measured
    row["actual"] = _format_actual(measured, bps)
    row["actual_detail"] = note
    return row


def _other_margin(evidence: str) -> bool:
    gross = bool(re.search(r"gross margin", evidence or "", re.I)) and not re.search(r"\bebitda\b|\bpbdit\b", evidence or "", re.I)
    alone = bool(re.search(r"stand-?alone", evidence or "", re.I))
    return gross or alone


def _unit_block(row: dict, key: str, bps: bool) -> bool:
    """Refuse a row whose quote is a different margin or a different reporting basis."""
    evidence = row.get("source_quote") or ""
    gross = bool(re.search(r"gross margin", evidence, re.I)) and not re.search(r"\bebitda\b|\bpbdit\b", evidence, re.I)
    alone = bool(re.search(r"stand-?alone", evidence, re.I))
    if gross or alone:
        if gross and alone and key in MARGIN_KEYS:
            reason = "The quote is a standalone gross margin, not the consolidated EBITDA margin."
        elif gross and key in MARGIN_KEYS:
            reason = "The quote is a gross margin, not the EBITDA margin."
        elif alone:
            reason = "The quote is standalone, not the consolidated series."
        else:
            reason = "The quote is a gross margin, not the consolidated EBITDA margin."
        _not_scored(row, reason)
        return True
    if bps and key not in MARGIN_KEYS:
        _not_scored(row, "A basis-point figure is a margin change, not this metric.")
        return True
    if not row.get("period_promised"):
        _not_scored(row, "The period is not stated.")
        return True
    if (row.get("scope") or "") not in ("consolidated", "segment", "geography", "other"):
        _not_scored(row, "The scope is not stated.")
        return True
    return False


def _refuse_unit(row: dict, key: str) -> bool:
    """Score only a percent or basis-point promise whose quote states that unit."""
    if row.get("target_low") is None and row.get("target_high") is None:
        return False
    unit = row.get("unit") or "other"
    if row.get("quote_check") != "ok":
        _not_scored(row, row.get("quote_check") or "The quote does not state the unit.")
        return True
    if unit == "currency_inr":
        _not_scored(row, "The promise is in rupees, and the series comparison is a percent.")
        return True
    if key in ("revenue_growth", "ebitda_growth", "pat_growth") and unit != "percent":
        _not_scored(row, "Growth is only scored from a percent stated in the quote.")
        return True
    if key in MARGIN_KEYS and unit not in ("percent", "bps"):
        _not_scored(row, "A margin is only scored from a percent or from basis points in the quote.")
        return True
    if key in MARGIN_KEYS and unit == "percent" and row.get("kind") == "change":
        _not_scored(row, "The quote states a margin change, not a margin level.")
        return True
    return False


def _expected_unit(key: str, bps: bool, low, high, direction: str) -> str:
    """What kind of number the promise is asking to be scored against."""
    if bps:
        return "bps_change"
    if key in ("revenue_growth", "ebitda_growth", "pat_growth"):
        return "pct_change"
    if key in MARGIN_KEYS and low is None and high is None and direction:
        return "pp_change"
    return "pct_level"


def _reject_scored(row: dict, key: str, bps: bool, measured, unit: str, direction: str = "") -> bool:
    """A scored status needs the promise and the actual in the same kind of number."""
    if measured is None or not unit:
        _not_scored(row, "There is no actual in the same unit as the promise.")
        return True
    expected = _expected_unit(key, bps, row.get("target_low"), row.get("target_high"), direction)
    if unit != expected:
        _not_scored(row, "The promise and the actual are not in the same unit.")
        return True
    if bps and not re.search(r"basis point|\bbps\b", row.get("source_quote") or "", re.I):
        _not_scored(row, "The quote does not state basis points.")
        return True
    if key in MARGIN_KEYS and not bps and re.search(r"basis point|\bbps\b", row.get("source_quote") or "", re.I):
        _not_scored(row, "The quote is a basis-point change, not a margin level.")
        return True
    return False


def _not_scored(row: dict, reason: str) -> None:
    row["status"] = "not_scored"
    row["note"] = reason
    row["actual"] = None
    row["actual_value"] = None


def merge_rows(rows: list[dict]) -> tuple[list[dict], list[dict], dict]:
    """One row per metric and period. Repeats list the calls. A changed number is a revision."""
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        confidence = "low" if row["status"] in ("low_confidence", "not_scored") else "named"
        groups.setdefault(
            (row["metric_key"], row["period_promised"], _unit(row), confidence, row.get("scope") or "consolidated"),
            [],
        ).append(row)
    current = []
    long_term = []
    summary = {"raised": 0, "cut": 0, "maintained": 0, "items": []}
    for items in groups.values():
        items.sort(key=lambda item: (item.get("call_date") or "", item.get("page") or 0))
        named = [item for item in items if item["status"] != "low_confidence"]
        numbered = [
            item for item in named
            if item.get("target_low") is not None or item.get("target_high") is not None
        ]
        latest = dict((numbered or named or items)[-1])
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
    return row.get("unit") or ("bps" if "bps" in (row.get("promised") or "") else "percent")


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
        r"\b(delivered|have gone|has gone|have achieved|was |were |stood at|we've got|we got|driven by|been able|over the quarters?|grew by|growth has been|improved|expanded by)\b",
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
            _remember_model(usage["guidance"], (cached.get("usage") or {}).get("model") or "")
            done += 1
        elif max_calls and new_calls >= max_calls:
            continue
        else:
            new_calls += 1
            batch, hit, tokens, dropped, error, model = _promises_for_document(symbol, item, document, cache, selected)
            bucket = usage["guidance"]
            if error:
                bucket.setdefault("errors", []).append(f"{item['period']}: {error}")
            bucket["dropped"] += dropped
            if tokens:
                bucket["calls"] += 1
                bucket["tokens"] += tokens
                _remember_model(bucket, model)
            if not error:
                done += 1
        by_page = {page["page"]: page.get("text") or "" for page in pages}
        for promise in batch:
            stamped = dict(promise)
            stamped["call_period"] = item["period"]
            stamped["call_date"] = item.get("date") or item["period"]
            stamped["passage"] = passage_around(by_page.get(stamped.get("page")) or "", stamped.get("evidence") or "")
            stamped["basis"] = read_basis(stamped["passage"], stamped.get("basis"), stamped.get("evidence") or "")
            stamped["conditional_on"] = _named_event(stamped.get("conditional_on"))
            promises.append(stamped)
    _carry_stated_basis(promises)
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


def _promises_for_document(symbol, item, document, cache, pages) -> tuple[list[dict], bool, int, int, str, str]:
    url = item["url"]
    full = {page["page"]: page.get("text") or "" for page in document.get("pages") or []}
    if not pages or document.get("scanned"):
        if cache is not None:
            cache.put("guidance_llm", symbol, url, GUIDANCE_VERSION, {"promises": [], "dropped": 0, "usage": {}})
        return [], False, 0, 0, "", ""
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
        "Keep segment and geography guidance. Do not drop it. "
        "scope is consolidated, segment, geography, or other. "
        "scope_name is the division, product, or region in this passage, or empty when scope is consolidated. "
        "If the lines around the sentence are about a division, brand, product, or country, scope is not consolidated. "
        "evidence is consecutive words from one page, 25 words or fewer. "
        "metric_key is revenue_growth, ebitda_margin, ebitda_growth, pat_growth, volume_growth, or capex. "
        "horizon is quarter, fiscal_year, or multi_year. "
        "target_period is YYYY-MM-DD or FY####. "
        "target_low and target_high are numbers printed in that sentence, or empty. "
        "unit is the unit of those numbers: percent, bps, currency_usd, currency_inr, count, ratio, or other. "
        "A dollar figure is currency_usd, not a percent. A rupee or crore figure is currency_inr. "
        "kind is level or change. A growth rate or a basis-point move is a change. "
        "A margin percent, or a revenue amount, is a level. "
        "A basis-point range stays in basis points. direction is up, down, or empty. "
        "Read the quote and about three sentences either side of it on the same page. "
        "basis is reported, constant_currency, pro_forma, other, or not_stated. "
        "If this promise is in constant currency, including when those words are in its own sentence, basis is constant_currency. "
        "A constant-currency figure for a different business or metric does not set this promise's basis. "
        "conditional_on is the named corporate event the number depends on, such as a demerger, merger, "
        "acquisition, or sale, or empty. A general condition such as stable macros is not an event. "
        "Record a stated basis-point range for this year's margin even when the same answer also discusses growth. "
        "At most 8 promises. Use nothing beyond these pages.\n\n"
        + body
    )
    try:
        payload, call_usage = generate_json(prompt, GUIDANCE_SCHEMA, groq_models=GROQ_EXTRACTION)
    except QuotaError:
        raise
    except RuntimeError as exc:
        return [], False, 0, 0, str(exc), ""
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
    return kept, False, tokens, dropped, "", str(call_usage.get("model") or "")


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
        low, high = apply_word_bands(evidence, None, None, key)
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
    scope, scope_name = assign_scope(evidence, text, str(raw.get("scope") or ""), str(raw.get("scope_name") or ""))
    unit = read_unit(evidence, low, high)
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
        "scope": scope,
        "scope_name": scope_name,
        "unit": unit if unit in UNITS else "other",
        "kind": read_kind(unit, key, evidence),
        "basis": read_basis(passage_around(text, evidence), raw.get("basis"), evidence),
        "conditional_on": _named_event(raw.get("conditional_on")),
        "passage": passage_around(text, evidence),
    }


_DIVISIONS = (
    ("Jewellery", re.compile(r"jewellery|jewelry", re.I)),
    ("Watches", re.compile(r"\bwatches\b", re.I)),
    ("Eyewear", re.compile(r"eyewear|eye care", re.I)),
    ("Fragrances", re.compile(r"fragrance", re.I)),
    ("Foods", re.compile(r"\bfoods\b", re.I)),
)


def assign_scope(evidence: str, page: str, model_scope: str, model_name: str) -> tuple[str, str]:
    """Consolidated only when the passage is about the company. A named division wins."""
    scope = (model_scope or "").strip().lower()
    if scope not in ("consolidated", "segment", "geography", "other"):
        scope = "consolidated"
    name = " ".join((model_name or "").split())
    if re.search(r"consolidat", evidence or "", re.I):
        return "consolidated", ""
    window = _passage(page or "", evidence or "")
    nearest = _nearest_division(window)
    if nearest:
        return "segment", name or nearest
    if re.search(r"\binternational\b|\boverseas\b|\bexports?\b", window, re.I):
        return "geography", name or "international"
    if scope == "consolidated":
        return "consolidated", ""
    return scope, name


def _passage(page: str, evidence: str) -> str:
    hay = page or ""
    needle = " ".join((evidence or "").split())
    if not needle:
        return hay[:800]
    folded = hay.lower()
    at = folded.find(needle[:40].lower())
    if at < 0:
        return hay[:800]
    return hay[max(0, at - 700): at + len(needle)]


def _nearest_division(window: str) -> str:
    found = ""
    position = -1
    for label, pattern in _DIVISIONS:
        match = None
        for match in pattern.finditer(window or ""):
            pass
        if match is not None and match.start() >= position:
            found = label
            position = match.start()
    return found


def _remember_model(bucket: dict, model: str) -> None:
    if not model:
        return
    bucket["model"] = model
    seen = bucket.setdefault("models", [])
    if model not in seen:
        seen.append(model)


def _align_metric(key: str, quote: str, passage: str) -> tuple[str, bool]:
    """Operating margin and EBIT margin use EBIT. EBITDA and PBDIT stay on EBITDA. A bare margin is not scored."""
    family = _margin_family(quote, passage)
    if family == "ebit":
        return "ebit_margin", False
    if family == "ebitda" and key in ("ebitda_margin", "ebit_margin", ""):
        return "ebitda_margin", False
    if family == "unclear" and key in ("ebitda_margin", "ebit_margin", ""):
        return key or "ebitda_margin", True
    return key, False


def _margin_family(quote: str, passage: str) -> str:
    if re.search(r"\bebitda\b|\bpbdit\b", quote or "", re.I):
        return "ebitda"
    if re.search(r"operating margin|\bebit margin\b", quote or "", re.I):
        return "ebit"
    if re.search(r"\bebitda\b|\bpbdit\b", passage or "", re.I):
        return "ebitda"
    if re.search(r"operating margin|\bebit margin\b", passage or "", re.I):
        return "ebit"
    if re.search(r"\bmargin\b", quote or "", re.I):
        return "unclear"
    return ""


def _definition_note(key: str, evidence: str) -> str:
    if key == "ebitda_margin" and re.search(r"\bpbdit\b", evidence or "", re.I):
        return "Company says PBDIT; we compute EBITDA excluding other income"
    if key == "ebit_margin" and re.search(r"operating margin", evidence or "", re.I):
        return "Company says operating margin; we compute EBIT as PBT + finance costs − other income, as a percent of revenue."
    if key == "ebit_margin":
        return "Company says EBIT margin; we compute EBIT as PBT + finance costs − other income, as a percent of revenue."
    return ""


def _explicit_period(quote: str, passage: str, call_period: str):
    """The quote's own year wins. Mid-term is a longer horizon unless that same text also names a year."""
    named = _named_year(quote, call_period)
    if named is not None:
        return named
    if _VAGUE_HORIZON.search(quote or ""):
        return "vague"
    named = _named_year(passage, call_period)
    if named is not None:
        return named
    if _VAGUE_HORIZON.search(passage or ""):
        return "vague"
    return None


def _named_year(text: str, call_period: str):
    match = _EXPLICIT_FY.search(text or "")
    if match:
        raw = next(group for group in match.groups() if group)
        year = int(raw)
        if year < 100:
            year += 2000
        return "fiscal_year", date(year, 3, 31)
    try:
        call = date.fromisoformat((call_period or "")[:10])
    except ValueError:
        return None
    year = call.year if call.month <= 3 else call.year + 1
    if _NEXT_YEAR.search(text or ""):
        return "fiscal_year", date(year + 1, 3, 31)
    if _THIS_YEAR.search(text or ""):
        return "fiscal_year", date(year, 3, 31)
    return None


def _infer_metric(evidence: str) -> str | None:
    hits = [key for key, pattern in _METRIC_WORDS.items() if pattern.search(evidence or "")]
    if len(hits) == 1:
        return hits[0]
    return None


def passage_around(page: str, quote: str, radius: int = 3) -> str:
    """The quote plus about three sentences either side on the same page."""
    text = " ".join((page or "").split())
    needle = " ".join((quote or "").split())
    if not text:
        return needle
    sentences = [part for part in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text) if part]
    if not sentences:
        return text
    key = needle[:80].lower()
    at = None
    for index, sentence in enumerate(sentences):
        if key and (key[:40] in sentence.lower() or sentence.lower()[:40] in key):
            at = index
            break
    if at is None:
        found = text.lower().find(key[:40]) if key else -1
        if found < 0:
            return needle or text[:800]
        return text[max(0, found - 500): found + len(needle) + 500]
    start = max(0, at - radius)
    end = min(len(sentences), at + radius + 1)
    return " ".join(sentences[start:end])


def read_basis(passage: str, stated, quote: str = "") -> str:
    """Constant currency in this promise's sentence decides the basis. A neighboring sentence does not."""
    text = _basis_window(passage or "", quote or "")
    if re.search(r"constant[- ]currency", text, re.I):
        return "constant_currency"
    if re.search(r"pro[- ]?forma", text, re.I):
        return "pro_forma"
    basis = str(stated or "").strip().lower().replace(" ", "_")
    if basis in ("reported", "constant_currency", "pro_forma", "other", "not_stated"):
        return basis
    return "not_stated"


def _basis_window(passage: str, quote: str) -> str:
    text = " ".join((passage or "").split())
    needle = " ".join((quote or "").split())
    if not text or not needle:
        return text or needle
    sentences = [part for part in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text) if part]
    key = needle[:80].lower()
    for sentence in sentences:
        if key[:40] in sentence.lower() or sentence.lower()[:40] in key:
            return sentence
    return needle


def _carry_stated_basis(promises: list[dict]) -> None:
    """A filing that states consolidated revenue guidance in constant currency keeps that basis when a later sentence drops the words."""
    grouped: dict[str, list[dict]] = {}
    for promise in promises:
        grouped.setdefault(promise.get("source_document") or "", []).append(promise)
    for group in grouped.values():
        stated = any(
            (promise.get("scope") or "consolidated") == "consolidated"
            and promise.get("metric_key") == "revenue_growth"
            and promise.get("basis") == "constant_currency"
            and re.search(r"guidance", promise.get("evidence") or "", re.I)
            for promise in group
        )
        if not stated:
            continue
        for promise in group:
            if promise.get("metric_key") != "revenue_growth":
                continue
            if (promise.get("scope") or "consolidated") != "consolidated":
                continue
            if promise.get("basis") != "not_stated":
                continue
            evidence = promise.get("evidence") or ""
            if re.search(r"\brupee\b|\binr\b|reported basis", evidence, re.I):
                continue
            promise["basis"] = "constant_currency"
            promise["basis_note"] = "The same filing states this revenue guidance in constant currency."


def _named_event(value) -> str | None:
    text = " ".join(str(value or "").split())
    if not text or text.lower() in ("null", "none", "n/a", "na"):
        return None
    return text


VERIFY_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "consolidated": {"type": "BOOLEAN"},
        "consolidated_evidence": {"type": "STRING"},
        "reported_basis": {"type": "BOOLEAN"},
        "reported_basis_evidence": {"type": "STRING"},
        "independent_of_named_event": {"type": "BOOLEAN"},
        "independent_of_named_event_evidence": {"type": "STRING"},
        "metric_named": {"type": "BOOLEAN"},
        "metric_named_evidence": {"type": "STRING"},
        "conditional_on": {"type": "STRING"},
        "caveat": {"type": "STRING"},
    },
    "required": [
        "consolidated",
        "consolidated_evidence",
        "reported_basis",
        "reported_basis_evidence",
        "independent_of_named_event",
        "independent_of_named_event_evidence",
        "metric_named",
        "metric_named_evidence",
        "conditional_on",
        "caveat",
    ],
}


def apply_verification(row: dict, decision: dict) -> dict:
    """A scored row stays scored only when every verifier flag is true and the basis is reported."""
    flags = {
        "consolidated": bool(decision.get("consolidated")),
        "reported_basis": bool(decision.get("reported_basis")),
        "independent_of_named_event": bool(decision.get("independent_of_named_event")),
        "metric_named": bool(decision.get("metric_named")),
    }
    event = _named_event(decision.get("conditional_on"))
    if not flags["independent_of_named_event"] and not _event_binds(row, decision):
        flags["independent_of_named_event"] = True
        event = None
    row["verifier"] = {
        **flags,
        "model": str(decision.get("model") or ""),
        "evidence": {
            "consolidated": str(decision.get("consolidated_evidence") or ""),
            "reported_basis": str(decision.get("reported_basis_evidence") or ""),
            "independent_of_named_event": str(decision.get("independent_of_named_event_evidence") or ""),
            "metric_named": str(decision.get("metric_named_evidence") or ""),
        },
    }
    caveat = " ".join(str(decision.get("caveat") or "").split())
    if caveat and _CAVEAT_WORD.search(caveat) and not re.search(r"\d", caveat):
        row["caveat"] = caveat
    if event and not flags["independent_of_named_event"]:
        row["conditional_on"] = event
    if row.get("basis") == "constant_currency":
        _not_scored(row, row.get("basis_note") or "Constant-currency guidance is not the consolidated rupee series.")
        return row
    if row.get("basis") == "pro_forma":
        _not_scored(row, "Pro-forma guidance is not the reported consolidated series.")
        return row
    reasons = []
    if not flags["consolidated"]:
        reasons.append("The guidance is not for the consolidated company.")
    if not flags["reported_basis"]:
        reasons.append("The guidance is not on a reported basis.")
    if not flags["independent_of_named_event"]:
        name = event or "a named corporate event"
        row["conditional_on"] = name
        reasons.append(f"The guidance depends on {name}.")
    if not flags["metric_named"]:
        reasons.append("The passage does not name the metric being scored.")
    if reasons:
        _not_scored(row, " ".join(reasons))
    return row


def _event_binds(row: dict, decision: dict) -> bool:
    """An event unscores a row only when it qualifies this quote, not a neighboring metric."""
    quote = row.get("source_quote") or ""
    evidence = str(decision.get("independent_of_named_event_evidence") or "")
    if _EVENT_WORD.search(quote):
        return True
    metric = _METRIC_WORDS.get(row.get("metric_key") or "")
    return bool(metric and metric.search(evidence) and _EVENT_WORD.search(evidence))


_EVENT_WORD = re.compile(r"demerger|merger|acquisition|dispos|spin-?off|scheme of arrangement", re.I)
_CAVEAT_WORD = re.compile(
    r"subject to|assum|macro|demand|commodit|inflat|disruption|geopolit|monsoon|weather|unless|contingent|provid",
    re.I,
)


def verify_scored(symbol: str, rows: list[dict], cache, usage: dict) -> list[dict]:
    """Ask the stronger model about each row that arithmetic would score. Cache by document and row."""
    bucket = usage.setdefault("verify", {"calls": 0, "cache_hits": 0, "tokens": 0, "model": ""})
    for row in rows:
        if row.get("status") not in _SCORED:
            continue
        decision = _verifier_decision(symbol, row, cache, bucket)
        if decision.get("error"):
            row["verifier"] = {"error": decision["error"]}
            if row.get("basis") in ("constant_currency", "pro_forma"):
                apply_verification(row, _verify_clear())
            continue
        apply_verification(row, decision)
    return rows


def _verify_clear() -> dict:
    return {
        "consolidated": True,
        "reported_basis": True,
        "independent_of_named_event": True,
        "metric_named": True,
        "conditional_on": "",
        "caveat": "",
    }


def _verifier_decision(symbol: str, row: dict, cache, bucket: dict) -> dict:
    document = row.get("source_document") or ""
    row_key = hashlib.sha1(
        "\n".join((document, str(row.get("page") or ""), row.get("metric_key") or "", row.get("source_quote") or "")).encode()
    ).hexdigest()[:20]
    if cache is not None:
        cached = cache.get("guidance_verify", symbol, document[-180:], f"{VERIFY_VERSION}:{row_key}")
        if isinstance(cached, dict) and "decision" in cached:
            bucket["cache_hits"] += 1
            bucket["model"] = (cached.get("usage") or {}).get("model") or bucket.get("model") or ""
            return cached["decision"]
    passage = row.get("passage") or row.get("source_quote") or ""
    prompt = (
        "Decide whether this management promise can be compared with the consolidated reported figures. "
        "Use the passage, not outside knowledge of the company.\n"
        "consolidated is false only when this promise's number is limited to a division, brand, geography, or subsidiary. "
        "A nearby mention of standalone or a segment does not make a company-level promise false.\n"
        "reported_basis is false only when the quoted promise itself is in constant currency, pro forma, or another non-reported basis, "
        "including when the sentence just before or after says that this number is in constant currency. "
        "Constant currency for a different business, segment, or metric in a neighboring sentence does not apply. "
        "If this promise names no basis, reported_basis is true.\n"
        "independent_of_named_event is false only when the number depends on a named corporate event: "
        "a demerger, merger, acquisition, disposal, spin-off, or scheme. "
        "If there is no such event, the flag is true and conditional_on is empty. "
        "Commodity prices, demand, and 'subject to stable macros' are not events. Put those in caveat.\n"
        "metric_named is true when the quote or the sentences beside it name revenue, sales, EBITDA, PBDIT, "
        "operating margin, PAT, or profit. PBDIT and operating margin count as the margin metric.\n"
        "Each evidence field is a short quote from the passage that decided that flag.\n"
        "conditional_on is the event name, or empty. "
        "caveat is only a general condition on this promise, such as stable macros, demand, or commodity prices. "
        "Otherwise leave caveat empty.\n\n"
        f"Metric: {row.get('metric_key')}\n"
        f"Promise: {row.get('promise')}\n"
        f"Quote: {row.get('source_quote')}\n"
        f"Passage: {passage[:1800]}"
    )
    # 3.6-flash and 3.8-flash share a 20-request free daily cap and were exhausted.
    # 3-flash-preview is the Flash model that still answers; Flash-Lite covers a 503.
    try:
        payload, call_usage = generate_json(
            prompt,
            VERIFY_SCHEMA,
            ("gemini-3-flash-preview", FLASH_LITE),
            timeout=25,
            attempts=2,
            groq_models=GROQ_VERIFY,
        )
    except QuotaError:
        raise
    except RuntimeError as exc:
        return {
            "consolidated": False,
            "reported_basis": False,
            "independent_of_named_event": False,
            "metric_named": False,
            "consolidated_evidence": "",
            "reported_basis_evidence": "",
            "independent_of_named_event_evidence": "",
            "metric_named_evidence": "",
            "conditional_on": "",
            "caveat": "",
            "error": str(exc),
        }
    bucket["calls"] += 1
    bucket["tokens"] += int(call_usage.get("total_tokens") or 0)
    bucket["model"] = call_usage.get("model") or bucket.get("model") or ""
    payload = dict(payload)
    payload["model"] = bucket["model"]
    if cache is not None:
        cache.put(
            "guidance_verify",
            symbol,
            document[-180:],
            f"{VERIFY_VERSION}:{row_key}",
            {"decision": payload, "usage": call_usage},
        )
    return payload


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
                "ebit": row.get("ebit"),
                "ebit_margin_pct": row.get("ebit_margin_pct"),
                "pbt": row.get("pbt"),
                "finance_costs": row.get("finance_costs"),
                "depreciation": row.get("depreciation"),
                "other_income": row.get("other_income"),
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
            (FLASH, *FLASH_FALLBACKS, FLASH_LITE),
            timeout=20,
            attempts=1,
        )
    except QuotaError:
        raise
    except RuntimeError as exc:
        return f"Verdict unavailable: {exc}"
    line = " ".join(str(payload.get("line") or "").split())
    usage["verdict"]["calls"] += 1
    usage["verdict"]["tokens"] += int(call_usage.get("total_tokens") or 0)
    usage["verdict"]["model"] = call_usage.get("model") or ""
    if cache is not None and line:
        cache.put("verdict_llm", symbol, fingerprint, VERDICT_VERSION, {"line": line, "usage": call_usage})
    return line


def _fy_measure(key, year, by_period, direction, low, high, bps: bool = False):
    quarters = _fy_quarters(year)
    rows = [by_period.get(day.isoformat()) for day in quarters]
    if any(row is None or row.get("revenue") is None for row in rows):
        missing = [day.isoformat() for day, row in zip(quarters, rows) if row is None or row.get("revenue") is None]
        return None, "FY" + str(year) + " is missing " + ", ".join(missing) + ", so the year is not checked.", None
    if key in MARGIN_KEYS:
        field, label = _margin_field(key)
        level = _span_margin(quarters, by_period, field)
        if level is None:
            return None, f"FY{year} {label} is missing in a quarter, so the margin is not checked.", None
        if bps or (low is None and high is None and direction):
            base = _fy_margin(year - 1, by_period, field)
            if base is None:
                return None, f"FY{year - 1} is outside the series, so a change in margin cannot be checked.", None
            change = round((level - base) * 100) if bps else round(level - base, 2)
            if bps:
                return change, f"FY{year} {label} {level:.2f}% versus {base:.2f}% a year earlier ({change:+d} bps)", "bps_change"
            return change, "", "pp_change"
        return level, f"FY{year} {label} {level:.2f}%.", "pct_level"
    current = _fy_sum(year, by_period, _field(key))
    base = _fy_sum(year - 1, by_period, _field(key))
    if current is None or base in (None, 0):
        return None, f"The year before FY{year} is outside the series, so growth is not checked.", None
    return round((current / base - 1.0) * 100.0, 2), "", "pct_change"


def _ytd_measure(key, year, latest: date, by_period, bps: bool):
    days = [day for day in _fy_quarters(year) if day <= latest]
    if not days:
        return None, f"No quarter of FY{year} has been reported.", None
    prior = [_shift_year(day) for day in days]
    label = {1: "Q1", 2: "H1", 3: "9M"}[len(days)]
    if key in MARGIN_KEYS:
        field, margin_label = _margin_field(key)
        current = _span_margin(days, by_period, field)
        base = _span_margin(prior, by_period, field)
        if current is None:
            return None, f"{label} FY{year} is missing a quarter, so the margin is not tracked.", None
        if base is None:
            return None, f"The year-ago {label} is not in the series, so the margin is not tracked.", None
        change = round((current - base) * 100)
        detail = (
            f"{label} FY{year} {margin_label} {current:.2f}% versus {base:.2f}% a year earlier ({change:+d} bps)"
        )
        if bps:
            return change, detail, "bps_change"
        return current, detail, "pct_level"
    field = _field(key)
    current = _span_sum(days, by_period, field)
    base = _span_sum(prior, by_period, field)
    if current is None:
        return None, f"{label} FY{year} is missing a quarter, so growth is not tracked.", None
    if base in (None, 0):
        return None, f"The year-ago {label} is not in the series, so growth is not tracked.", None
    growth = round((current / base - 1.0) * 100.0, 2)
    name = {"ebitda": "EBITDA", "pat": "PAT", "revenue": "revenue"}[field]
    detail = f"{label} FY{year} {name} {current:,.2f} versus {label} FY{year - 1} {name} {base:,.2f}"
    return growth, detail, "pct_change"


def _quarter_measure(key, end: date, by_period, direction, low, high, bps: bool = False):
    row = by_period.get(end.isoformat())
    if row is None or row.get("revenue") is None:
        return None, f"{end.isoformat()} has no quarter figures.", None
    if key in MARGIN_KEYS:
        field, margin_label = _margin_field(key)
        level = row.get(f"{field}_margin_pct")
        if level is None:
            return None, f"{end.isoformat()} has no {margin_label}.", None
        if bps or (low is None and high is None and direction):
            base = _margin_on(_shift_year(end), by_period, field)
            if base is None:
                return None, f"The year-ago margin for {end.isoformat()} is not in the series.", None
            change = round((level - base) * 100) if bps else round(level - base, 2)
            if bps:
                return change, (
                    f"{end.isoformat()} {margin_label} {level:.2f}% versus {base:.2f}% a year earlier ({change:+d} bps)"
                ), "bps_change"
            return change, "", "pp_change"
        return level, f"{end.isoformat()} {margin_label} {level:.2f}%.", "pct_level"
    field = _field(key)
    current = row.get(field)
    base_row = by_period.get(_shift_year(end).isoformat())
    base = None if base_row is None else base_row.get(field)
    if current is None or base in (None, 0):
        return None, f"The year-ago {field} for {end.isoformat()} is not in the series.", None
    return round((current / base - 1.0) * 100.0, 2), "", "pct_change"


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


def _margin_field(key: str) -> tuple[str, str]:
    if key == "ebit_margin":
        return "ebit", "EBIT margin"
    return "ebitda", "EBITDA margin"


def _span_margin(days: list[date], by_period, field: str = "ebitda"):
    revenue = _span_sum(days, by_period, "revenue")
    profit = _span_sum(days, by_period, field)
    if revenue in (None, 0) or profit is None:
        return None
    return round(profit / revenue * 100.0, 2)


def _fy_sum(year: int, by_period, field: str):
    return _span_sum(_fy_quarters(year), by_period, field)


def _fy_margin(year: int, by_period, field: str = "ebitda"):
    return _span_margin(_fy_quarters(year), by_period, field)


def _margin_on(day: date, by_period, field: str = "ebitda"):
    row = by_period.get(day.isoformat())
    if row is None:
        return None
    return row.get(f"{field}_margin_pct")


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


def _promise_line(promise: dict, low, high, unit: str = "percent", evidence: str = "") -> str:
    label = LABELS.get(promise["metric_key"], promise["metric_key"])
    if unit in ("currency_usd", "currency_inr") and promise["metric_key"] == "revenue_growth":
        label = "Revenue"
    target = _target_phrase(low, high, unit, evidence)
    if target == "a direction only":
        if promise.get("direction") == "down":
            target = "to fall"
        elif promise.get("direction") == "up":
            target = "to rise"
    period = promise.get("target_period") or "an unnamed period"
    return f"{label} {target} for {period}"


def _target_phrase(low, high, unit: str = "percent", evidence: str = "") -> str:
    scale = _scale_word(evidence, unit)
    if unit == "bps":
        prefix, suffix = "", " bps"
    elif unit == "currency_usd":
        prefix, suffix = "US$", scale
    elif unit == "currency_inr":
        prefix, suffix = "₹", scale
    elif unit == "percent":
        prefix, suffix = "", "%"
    else:
        prefix, suffix = "", ""
    if low is not None and high is not None and abs(low - high) < 1e-6:
        return f"{prefix}{low:g}{suffix}"
    if low is not None and high is not None:
        return f"{prefix}{low:g}–{high:g}{suffix}"
    if low is not None:
        return f"at least {prefix}{low:g}{suffix}"
    if high is not None:
        return f"at most {prefix}{high:g}{suffix}"
    return "a direction only"


def _scale_word(evidence: str, unit: str) -> str:
    text = (evidence or "").lower()
    if unit == "currency_usd":
        if "billion" in text:
            return " billion"
        if "million" in text:
            return " million"
    if unit == "currency_inr":
        if "crore" in text:
            return " crore"
        if "lakh" in text:
            return " lakh"
    return ""


def _format_actual(value: float, bps: bool) -> str:
    if bps:
        return f"{value:+.0f} bps"
    return f"{value:g}%"


def _number_spans(text: str, value: float | None) -> list[tuple[int, int]]:
    if value is None:
        return []
    shown = f"{value:g}"
    return [(match.start(), match.end()) for match in re.finditer(rf"(?<!\d){re.escape(shown)}(?!\d)", text or "")]


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


def sanitize_bounds(
    evidence: str,
    low: float | None,
    high: float | None,
    metric_key: str | None = None,
) -> tuple[float | None, float | None]:
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
    return apply_word_bands(evidence, low, high, metric_key)


_BANDS = (
    (("mid-teen", "mid teen"), (13.0, 16.0)),
    (("high-teen", "high teen"), (17.0, 19.0)),
    (("low-teen", "low teen"), (10.0, 13.0)),
    (("double-digit", "double digit"), (10.0, None)),
    (("high single",), (7.0, 9.0)),
)


def apply_word_bands(
    evidence: str,
    low: float | None,
    high: float | None,
    metric_key: str | None = None,
) -> tuple[float | None, float | None]:
    """Named bands only when the quote itself uses them and states no number.

    A sentence that names two bands keeps the one next to this metric.
    """
    if low is not None or high is not None:
        return low, high
    text = re.sub(r"\s*-\s*", "-", (evidence or "").lower())
    found = []
    for phrases, bounds in _BANDS:
        for phrase in phrases:
            at = text.find(phrase)
            if at >= 0:
                found.append((at, bounds))
                break
    if not found:
        return low, high
    if len(found) == 1 or not metric_key or metric_key not in _METRIC_WORDS:
        return found[0][1]
    spots = [match.start() for match in _METRIC_WORDS[metric_key].finditer(text)]
    if not spots:
        return found[0][1]
    return min(found, key=lambda item: min(abs(item[0] - spot) for spot in spots))[1]


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
    cache = open_cache()
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
