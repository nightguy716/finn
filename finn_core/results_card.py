"""Quarterly results card. XBRL first; the results PDF is the fallback.

QoQ and YoY are not contexts inside one integrated-filing XBRL. They are the
current-quarter facts of the previous-quarter filing and the year-ago filing.
"""

import hashlib
import io
import re
from datetime import date, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

from finn_core.config import market_symbol
from finn_core.llm import generate_json
from finn_core.nse_client import NSEClient, NSEError, _broadcast_sort
from finn_core.xbrl_parse import (
    change_pct,
    ebitda,
    ebitda_block_reason,
    metrics_from,
    parse_period_end,
    parse_xbrl,
    previous_quarter_end,
    year_ago_end,
)

HEADLINES = ("revenue", "ebitda", "pbt", "pat")
REVENUE_RANGE = (1.0, 1_000_000.0)
PAT_ABS_MAX = 300_000.0


def build_results_card(symbol: str, client: NSEClient, cache, *, today: date | None = None) -> dict:
    symbol = symbol.upper()
    today = today or date.today()
    usage = _empty_usage()
    try:
        rows = client.get_financial_results(market_symbol(symbol), today - timedelta(days=540), today)
    except NSEError as exc:
        return _failed(symbol, f"results feed failed: {exc}", usage)
    if not rows:
        return _failed(symbol, "no integrated financials filing", usage)
    current_row = max(rows, key=lambda row: _broadcast_sort(row.get("timestamp") or ""))
    period_end = parse_period_end(current_row.get("period_end") or "")
    if period_end is None:
        return _failed(symbol, f"unreadable period {current_row.get('period_end')}", usage)

    parsed = None
    parse_error = ""
    try:
        xml = _load_xbrl(client, cache, symbol, current_row)
        parsed = parse_xbrl(xml)
    except (NSEError, ET.ParseError, UnicodeError) as exc:
        parse_error = f"{type(exc).__name__}: {exc}"

    current_metrics = metrics_from(parsed.current) if parsed is not None else None
    if current_metrics is None or current_metrics.get("revenue") is None or current_metrics.get("pat") is None:
        return _from_pdf(
            symbol,
            client,
            cache,
            current_row,
            period_end,
            usage,
            reason=parse_error or "XBRL current quarter is missing revenue or PAT",
        )

    by_period = {}
    for row in rows:
        end = parse_period_end(row.get("period_end") or "")
        if end is not None:
            by_period[end] = row
    previous_metrics, previous_url, previous_flag = _comparison(client, cache, symbol, by_period, previous_quarter_end(period_end))
    yoy_metrics, yoy_url, yoy_flag = _comparison(client, cache, symbol, by_period, year_ago_end(period_end))
    return _assemble(
        symbol=symbol,
        period_end=period_end,
        period_label=current_row.get("period_end") or "",
        scope=current_row.get("scope") or "",
        source="xbrl",
        source_url=current_row.get("xbrl_url") or "",
        broadcast=current_row.get("timestamp") or "",
        current=current_metrics,
        previous=previous_metrics,
        yoy=yoy_metrics,
        xbrl_url=current_row.get("xbrl_url") or "",
        parsed=parsed,
        comparison_urls={"qoq": previous_url, "yoy": yoy_url},
        extra_flags=[flag for flag in (previous_flag, yoy_flag) if flag],
        usage=usage,
    )


def _comparison(client, cache, symbol: str, by_period: dict, end: date):
    row = by_period.get(end)
    if row is None:
        return None, "", f"missing filing for quarter ended {end.isoformat()}"
    try:
        parsed = parse_xbrl(_load_xbrl(client, cache, symbol, row))
    except (NSEError, ET.ParseError, UnicodeError) as exc:
        return None, row.get("xbrl_url") or "", f"quarter {end.isoformat()} XBRL failed: {type(exc).__name__}"
    if parsed.current is None or parsed.current.end != end:
        return None, row.get("xbrl_url") or "", f"quarter {end.isoformat()} OneD is not that quarter"
    return metrics_from(parsed.current), row.get("xbrl_url") or "", ""


def _assemble(
    *,
    symbol: str,
    period_end: date,
    period_label: str,
    scope: str,
    source: str,
    source_url: str,
    broadcast: str,
    current: dict,
    previous: dict | None,
    yoy: dict | None,
    xbrl_url: str,
    parsed,
    comparison_urls: dict,
    extra_flags: list[str],
    usage: dict,
) -> dict:
    reason = ebitda_block_reason(symbol, xbrl_url, current)
    current_view = _with_ebitda(current, reason)
    previous_view = _with_ebitda(previous, reason) if previous else None
    yoy_view = _with_ebitda(yoy, reason) if yoy else None
    metrics = {}
    for key in HEADLINES:
        if key == "ebitda" and reason:
            metrics[key] = None
            continue
        metrics[key] = _line(current_view, previous_view, yoy_view, key)
    flags = list(extra_flags)
    flags.extend(_sanity(current_view, reason))
    contexts = []
    missing = []
    missing_reason = ""
    scale = ""
    rounding = ""
    if parsed is not None:
        scale = parsed.scale
        rounding = parsed.rounding
        missing = list(parsed.missing)
        missing_reason = parsed.missing_reason
        for period in parsed.periods:
            role = "other"
            if parsed.current is not None and period.context_id == parsed.current.context_id:
                role = "current_quarter"
            elif parsed.year_to_date is not None and period.context_id == parsed.year_to_date.context_id:
                role = "year_to_date"
            contexts.append(
                {
                    "id": period.context_id,
                    "start": period.start.isoformat() if period.start else "",
                    "end": period.end.isoformat() if period.end else "",
                    "role": role,
                }
            )
        if previous is not None:
            missing = [name for name in missing if name != "previous_quarter"]
        if yoy is not None:
            missing = [name for name in missing if name != "year_ago_quarter"]
        if missing_reason and (previous is not None or yoy is not None):
            missing_reason += (
                " QoQ and YoY are the OneD figures from those filings, as originally reported."
                " A later statement can restate the comparative columns; that restatement is not in the XBRL."
            )
    margin = None
    if not reason:
        margin = {
            "current": _margin(current_view.get("ebitda"), current_view.get("revenue")),
            "qoq": _margin((previous_view or {}).get("ebitda"), (previous_view or {}).get("revenue")),
            "yoy": _margin((yoy_view or {}).get("ebitda"), (yoy_view or {}).get("revenue")),
        }
    return {
        "symbol": symbol,
        "period": period_end.isoformat(),
        "period_label": period_label,
        "scope": scope,
        "revenue_basis": current.get("revenue_basis") or "",
        "metrics": metrics,
        "ebitda_margin_pct": margin,
        "ebitda_reason": reason,
        "source": source,
        "source_url": source_url,
        "broadcast": broadcast,
        "comparison_urls": comparison_urls,
        "xbrl_contexts": contexts,
        "missing_contexts": missing,
        "missing_reason": missing_reason,
        "scale": scale,
        "rounding": rounding,
        "flags": flags,
        "usage": usage,
    }


def _with_ebitda(metrics: dict | None, reason: str) -> dict:
    metrics = dict(metrics or {})
    metrics["ebitda"] = None if reason else ebitda(metrics)
    return metrics


def _line(current: dict, previous: dict | None, yoy: dict | None, key: str) -> dict:
    cur = current.get(key)
    prev = None if previous is None else previous.get(key)
    ago = None if yoy is None else yoy.get(key)
    return {
        "current": cur,
        "qoq": prev,
        "yoy": ago,
        "qoq_pct": change_pct(cur, prev),
        "yoy_pct": change_pct(cur, ago),
    }


def _margin(profit: float | None, revenue: float | None) -> float | None:
    if profit is None or not revenue:
        return None
    return round(profit / revenue * 100.0, 2)


def _sanity(metrics: dict, ebitda_reason: str) -> list[str]:
    flags = []
    revenue = metrics.get("revenue")
    pat = metrics.get("pat")
    if revenue is None:
        flags.append("revenue_missing")
    elif revenue <= 0:
        flags.append(f"revenue_not_positive: {revenue}")
    elif not (REVENUE_RANGE[0] <= revenue <= REVENUE_RANGE[1]):
        flags.append(f"revenue_out_of_range: {revenue} crore")
    if pat is None:
        flags.append("pat_missing")
    elif pat <= 0:
        flags.append(f"pat_not_positive: {pat}")
    elif abs(pat) > PAT_ABS_MAX:
        flags.append(f"pat_out_of_range: {pat} crore")
    pbt = metrics.get("pbt")
    tax = metrics.get("tax")
    identity = metrics.get("pat_total")
    if identity is None:
        identity = pat
    share = metrics.get("share") or 0.0
    if pbt is not None and tax is not None and identity is not None and abs(pbt) >= 1:
        expected = identity + tax - share
        gap = abs(pbt - expected) / abs(pbt)
        if gap > 0.03:
            flags.append(
                f"pbt_tax_pat: PBT {pbt} vs PAT+tax-share {round(expected, 2)} ({gap:.1%})"
            )
    if ebitda_reason and metrics.get("ebitda") not in (None,):
        flags.append("ebitda_present_for_finance_company")
    return flags


def _from_pdf(symbol, client, cache, row, period_end: date, usage: dict, reason: str) -> dict:
    broadcast_day = _broadcast_sort(row.get("timestamp") or "").date()
    if broadcast_day.year < 2000:
        broadcast_day = period_end
    pdf_url = find_results_pdf(client, symbol, broadcast_day)
    flags = [f"xbrl_failed: {reason}"]
    if not pdf_url:
        flags.append("pdf_missing")
        return _failed(symbol, "; ".join(flags), usage, period_end=period_end, scope=row.get("scope") or "")
    try:
        text = _load_pdf_text(client, cache, symbol, row.get("period_end") or period_end.isoformat(), pdf_url)
    except (NSEError, OSError, RuntimeError) as exc:
        flags.append(f"pdf_download_failed: {type(exc).__name__}")
        return _failed(symbol, "; ".join(flags), usage, period_end=period_end, scope=row.get("scope") or "")
    try:
        extracted, usage = _extract_metrics(cache, symbol, row.get("period_end") or period_end.isoformat(), pdf_url, text)
    except RuntimeError as exc:
        flags.append(f"pdf_llm_failed: {exc}")
        return _failed(symbol, "; ".join(flags), usage, period_end=period_end, scope=row.get("scope") or "", source_url=pdf_url)
    current, previous, yoy = extracted
    card = _assemble(
        symbol=symbol,
        period_end=period_end,
        period_label=row.get("period_end") or "",
        scope=row.get("scope") or "",
        source="pdf_llm",
        source_url=pdf_url,
        broadcast=row.get("timestamp") or "",
        current=current,
        previous=previous,
        yoy=yoy,
        xbrl_url="",
        parsed=None,
        comparison_urls={"qoq": pdf_url, "yoy": pdf_url},
        extra_flags=flags,
        usage=usage,
    )
    card["missing_reason"] = "XBRL parse failed. Figures are from the results PDF via the extraction model."
    return card


def find_results_pdf(client: NSEClient, symbol: str, broadcast: date) -> str:
    try:
        rows = client.get_announcements(market_symbol(symbol), broadcast - timedelta(days=2), broadcast + timedelta(days=2))
    except NSEError:
        return ""
    best = ""
    best_score = -10**9
    for row in rows:
        url = row.get("pdf_url") or ""
        if ".pdf" not in url.lower():
            continue
        blob = f"{row.get('subject') or ''} {row.get('text') or ''}".lower()
        score = 0
        if "newspaper" in blob:
            score -= 4
        if "outcome of board" in blob:
            score += 6
        if "financial result" in blob:
            score += 3
        if "unaudited" in blob or "audited" in blob:
            score += 1
        if score == 0 and "financial result" not in blob and "outcome of board" not in blob:
            continue
        if score > best_score:
            best_score = score
            best = url
    return best


def pdf_text(payload: bytes) -> str:
    import warnings

    from pypdf import PdfReader

    warnings.filterwarnings("ignore", message="fontTools is required")
    reader = PdfReader(io.BytesIO(payload))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _load_xbrl(client, cache, symbol: str, row: dict) -> bytes:
    url = row.get("xbrl_url") or ""
    if not url:
        raise NSEError(symbol, None, "no xbrl url")
    period = row.get("period_end") or ""
    cached = cache.get("xbrl_xml", symbol, period, url)
    if isinstance(cached, str) and "<" in cached[:200]:
        return cached.encode("utf-8")
    data = client.get_bytes(url, symbol)
    cache.put("xbrl_xml", symbol, period, url, data.decode("utf-8", errors="replace"))
    return data


def _load_pdf_text(client, cache, symbol: str, period: str, url: str) -> str:
    cached = cache.get("pdf_text", symbol, period, url)
    if isinstance(cached, str) and cached:
        return cached
    data = client.get_bytes(url, symbol)
    folder = Path(cache.path).parent / "docs" / symbol
    folder.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", period).strip("._")[:60] or "doc"
    digest = hashlib.sha1(url.encode()).hexdigest()[:8]
    (folder / f"{stem}_{digest}.pdf").write_bytes(data)
    text = pdf_text(data)
    cache.put("pdf_text", symbol, period, url, text)
    return text


def _extract_metrics(cache, symbol: str, period: str, url: str, text: str):
    cached = cache.get("pdf_llm", symbol, period, url)
    if isinstance(cached, dict) and cached.get("current"):
        usage = cached.get("usage") or _empty_usage()
        return (cached["current"], cached.get("previous"), cached.get("yoy")), usage
    excerpt = _excerpt(text)
    payload, usage = _gemini(excerpt)
    current, previous, yoy = _metrics_from_model(payload)
    cache.put(
        "pdf_llm",
        symbol,
        period,
        url,
        {"current": current, "previous": previous, "yoy": yoy, "usage": usage, "raw": payload},
    )
    return (current, previous, yoy), usage


def _excerpt(text: str) -> str:
    folded = text.lower()
    start = folded.find("revenue from operations")
    if start < 0:
        start = folded.find("statement of profit")
    if start < 0:
        start = 0
    start = max(0, start - 500)
    return text[start : start + 50000]


def _metrics_from_model(payload: dict) -> tuple[dict, dict, dict]:
    unit = str(payload.get("unit") or "crore")

    def period(suffix: str) -> dict:
        def grab(name: str) -> float | None:
            return _to_crore(payload.get(f"{name}_{suffix}"), unit)

        pat = grab("pat")
        return {
            "revenue": grab("revenue"),
            "other_income": grab("other_income"),
            "finance_costs": grab("finance_costs"),
            "depreciation": grab("depreciation"),
            "pbt": grab("pbt"),
            "pat": pat,
            "tax": grab("tax"),
            "pat_total": pat,
            "share": 0.0,
            "nci": 0.0,
            "interest_earned": None,
            "product_sales": None,
            "revenue_basis": "pdf",
        }

    return period("current"), period("previous"), period("year_ago")


def _to_crore(value, unit: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    label = unit.lower()
    if "lakh" in label:
        return round(number / 100.0, 2)
    if "million" in label:
        return round(number / 10.0, 2)
    if label in ("rupee", "rupees", "inr"):
        return round(number / 10_000_000.0, 2)
    return round(number, 2)


def _gemini(excerpt: str) -> tuple[dict, dict]:
    prompt = (
        "Extract quarterly consolidated profit and loss figures from this results filing text. "
        "Use only numbers printed in the text. Do not calculate and do not use outside knowledge. "
        "The three columns are the current quarter, the immediately previous quarter, and the same quarter a year earlier. "
        "Ignore half-year and full-year columns. "
        "unit is the scale printed on the statement. "
        "Profit after tax is the profit attributable to owners when that line is shown, otherwise profit for the period.\n\n"
        + excerpt
    )
    schema = {
        "type": "OBJECT",
        "properties": {
            "unit": {"type": "STRING", "enum": ["crore", "lakh", "million", "rupee"]},
            "revenue_current": {"type": "NUMBER"},
            "revenue_previous": {"type": "NUMBER"},
            "revenue_year_ago": {"type": "NUMBER"},
            "other_income_current": {"type": "NUMBER"},
            "other_income_previous": {"type": "NUMBER"},
            "other_income_year_ago": {"type": "NUMBER"},
            "finance_costs_current": {"type": "NUMBER"},
            "finance_costs_previous": {"type": "NUMBER"},
            "finance_costs_year_ago": {"type": "NUMBER"},
            "depreciation_current": {"type": "NUMBER"},
            "depreciation_previous": {"type": "NUMBER"},
            "depreciation_year_ago": {"type": "NUMBER"},
            "pbt_current": {"type": "NUMBER"},
            "pbt_previous": {"type": "NUMBER"},
            "pbt_year_ago": {"type": "NUMBER"},
            "tax_current": {"type": "NUMBER"},
            "tax_previous": {"type": "NUMBER"},
            "tax_year_ago": {"type": "NUMBER"},
            "pat_current": {"type": "NUMBER"},
            "pat_previous": {"type": "NUMBER"},
            "pat_year_ago": {"type": "NUMBER"},
        },
        "required": ["unit", "revenue_current", "pbt_current", "pat_current"],
    }
    return generate_json(prompt, schema)


def _empty_usage() -> dict:
    return {"model": "", "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


def _failed(symbol: str, reason: str, usage: dict, period_end: date | None = None, scope: str = "", source_url: str = "") -> dict:
    return {
        "symbol": symbol,
        "period": period_end.isoformat() if period_end else "",
        "period_label": "",
        "scope": scope,
        "revenue_basis": "",
        "metrics": {key: None for key in HEADLINES},
        "ebitda_margin_pct": None,
        "ebitda_reason": "",
        "source": "",
        "source_url": source_url,
        "broadcast": "",
        "comparison_urls": {"qoq": "", "yoy": ""},
        "xbrl_contexts": [],
        "missing_contexts": ["current_quarter", "previous_quarter", "year_ago_quarter"],
        "missing_reason": reason,
        "scale": "",
        "rounding": "",
        "flags": [reason],
        "usage": usage,
    }
