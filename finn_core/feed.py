"""Push feed for one replayable window.

    python -m finn_core.feed --as-of 2026-11-06 --hours 72
"""

import argparse
import json
import sys
from datetime import date, datetime, timedelta

from finn_core.cache import open_cache
from finn_core.classify import PRIORITY, Classification, classify
from finn_core.config import PORTFOLIO, company_name, market_symbol
from finn_core.events import SUMMARY_CATEGORIES, cluster
from finn_core.llm import generate_json
from finn_core.nse_client import NSEClient, NSEError
from finn_core.prices import detect_alerts, fetch_eod
from finn_core.results_card import _load_pdf_text, build_results_card

CARD_CATEGORIES = ("results", "management_change") + SUMMARY_CATEGORIES
EXTRACT_VERSION = "v2"
MGMT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "person_name": {"type": "STRING"},
        "role": {"type": "STRING"},
        "change_type": {
            "type": "STRING",
            "enum": ["appointment", "resignation", "retirement", "change_in_designation"],
        },
        "effective_date": {"type": "STRING"},
        "profile": {"type": "STRING"},
    },
    "required": ["person_name", "role", "change_type", "effective_date", "profile"],
}
SUMMARY_SCHEMA = {
    "type": "OBJECT",
    "properties": {"line": {"type": "STRING"}},
    "required": ["line"],
}


def build_feed(
    as_of,
    window_hours: float,
    symbols: list[str] | None = None,
    move_pct: float = 5.0,
    volume_n: float = 2.5,
    alert_cap: int = 8,
    client: NSEClient | None = None,
    cache=None,
) -> dict:
    """One JSON object for the window ending at `as_of`. A date means 23:59:59 that day."""
    as_of = _as_of(as_of)
    start = as_of - timedelta(hours=window_hours)
    symbols = [symbol.upper() for symbol in (symbols or list(PORTFOLIO))]
    own_cache = cache is None
    cache = cache or open_cache()
    client = client or NSEClient(cache=cache)
    usage = {
        "management_change": {"calls": 0, "cache_hits": 0, "tokens": 0},
        "summary": {"calls": 0, "cache_hits": 0, "tokens": 0},
        "total_tokens": 0,
    }
    failures: list[str] = []
    fetch_start = (start - timedelta(days=1)).date()
    filings = []
    for symbol in symbols:
        for row in _load(client, symbol, fetch_start, as_of.date(), failures):
            when = _parse_nse_dt(row.get("timestamp") or "")
            if when is None or when.date() < fetch_start or when > as_of:
                continue
            filings.append({**row, "symbol": symbol, "when": when, "label": _label(row)})

    events = cluster(filings)
    in_window = [event for event in events if start < event["when"] <= as_of]
    cards = []
    card_ids = set()
    for event in in_window:
        if event["category"] not in CARD_CATEGORIES:
            continue
        cards.append(_card(event, as_of, client, cache, usage, failures))
        card_ids.add(event["id"])
    cards.sort(key=lambda card: (card["priority"], card["timestamp"]), reverse=True)

    routine: dict[str, int] = {}
    for event in in_window:
        if event["id"] in card_ids:
            continue
        routine[event["symbol"]] = routine.get(event["symbol"], 0) + len(event["filings"])

    alerts = _alerts(symbols, events, {card["id"]: card for card in cards}, start.date(), as_of.date(), move_pct, volume_n, alert_cap, failures)
    usage["total_tokens"] = usage["management_change"]["tokens"] + usage["summary"]["tokens"]
    payload = {
        "as_of": as_of.isoformat(timespec="seconds"),
        "window_hours": window_hours,
        "window_start": start.isoformat(timespec="seconds"),
        "move_pct": move_pct,
        "volume_n": volume_n,
        "cards": cards,
        "routine": [
            {"symbol": symbol, "company": company_name(symbol), "count": routine[symbol]}
            for symbol in sorted(routine)
        ],
        "alerts": alerts,
        "usage": usage,
        "failures": failures,
    }
    if own_cache:
        cache.close()
    return payload


def _card(event: dict, as_of: datetime, client, cache, usage: dict, failures: list[str]) -> dict:
    symbol = event["symbol"]
    sources = _sources(event)
    body: dict
    headline = event["subject"]
    if event["category"] == "results":
        body, headline = _results_body(symbol, as_of, client, cache, event, failures)
    elif event["category"] == "management_change":
        body = _management_body(event, client, cache, usage, failures)
        headline = _management_headline(event, body)
    else:
        body = _summary_body(event, client, cache, usage, failures)
        if body.get("line"):
            headline = body["line"]
    return {
        "id": event["id"],
        "symbol": symbol,
        "company": company_name(symbol),
        "category": event["category"],
        "priority": event["priority"],
        "timestamp": event["when"].isoformat(timespec="seconds"),
        "headline": headline,
        "body": body,
        "source_urls": [source["url"] for source in sources if source["url"]],
        "sources": sources,
    }


def _results_body(symbol: str, as_of: datetime, client, cache, event: dict, failures: list[str]) -> tuple[dict, str]:
    try:
        card = build_results_card(symbol, client, cache, today=as_of.date())
    except Exception as exc:
        failures.append(f"{symbol} results card {type(exc).__name__}: {exc}")
        return {"error": str(exc)}, f"{company_name(symbol)} results"
    period = card.get("period_label") or card.get("period") or ""
    headline = f"{company_name(symbol)} results for the quarter ended {period}"
    body = {
        "period": card.get("period"),
        "scope": card.get("scope"),
        "revenue_basis": card.get("revenue_basis"),
        "metrics": card.get("metrics"),
        "ebitda_margin_pct": card.get("ebitda_margin_pct"),
        "ebitda_reason": card.get("ebitda_reason") or "",
        "flags": card.get("flags") or [],
        "source": card.get("source"),
    }
    return body, headline


def _management_body(event: dict, client, cache, usage: dict, failures: list[str]) -> dict:
    text, note, from_pdf = _event_text(event, client, cache, failures, limit=30000)
    url = _primary_url(event)
    cached = cache.get("mgmt_llm", event["symbol"], url or event["id"], EXTRACT_VERSION)
    if isinstance(cached, dict) and "body" in cached:
        usage["management_change"]["cache_hits"] += 1
        return cached["body"]
    if not text.strip():
        body = _blank_management("The filing has no attachment text.")
        return body
    prompt = (
        "This is the full text of one exchange disclosure about a management change. "
        "Extract only facts written in the text. Do not use outside knowledge and do not guess. "
        "profile is the biographical background the disclosure itself gives: education, experience, or previous employers. "
        "If the disclosure has no such profile, set profile to an empty string. "
        "Do not turn the job title into a profile.\n\n"
        + text
    )
    try:
        payload, call_usage = generate_json(prompt, MGMT_SCHEMA)
    except RuntimeError as exc:
        failures.append(f"{event['symbol']} management extract {exc}")
        return _blank_management(str(exc))
    profile = _blank_to_none(payload.get("profile"))
    body = {
        "person": _blank_to_none(payload.get("person_name")),
        "role": _blank_to_none(payload.get("role")),
        "change_type": payload.get("change_type") or _change_type(event["subject"]),
        "effective_date": _blank_to_none(payload.get("effective_date")),
        "profile": profile,
        "profile_note": "" if profile else "The disclosure has no biographical profile.",
        "text_note": note,
    }
    if from_pdf or not _has_pdf(event):
        cache.put(
            "mgmt_llm",
            event["symbol"],
            url or event["id"],
            EXTRACT_VERSION,
            {"body": body, "usage": call_usage},
        )
    bucket = usage["management_change"]
    bucket["calls"] += 1
    bucket["tokens"] += int(call_usage.get("total_tokens") or 0)
    return body


def _summary_body(event: dict, client, cache, usage: dict, failures: list[str]) -> dict:
    cached = cache.get("summary_llm", event["symbol"], event["id"], EXTRACT_VERSION)
    if isinstance(cached, dict) and cached.get("line"):
        usage["summary"]["cache_hits"] += 1
        return {"line": cached["line"]}
    text, note, from_pdf = _event_text(event, client, cache, failures, limit=12000)
    if not text.strip():
        return {"line": event["subject"], "text_note": "The filing has no attachment text."}
    prompt = (
        "Write one plain sentence a portfolio manager can scan. "
        "Say what the company disclosed. Include the other party, the amount, or the order only if the text states it. "
        "One line, no advice, no adjectives, no facts that are not in the text.\n\n"
        f"Subject: {event['subject']}\n\n{text}"
    )
    try:
        payload, call_usage = generate_json(prompt, SUMMARY_SCHEMA)
    except RuntimeError as exc:
        failures.append(f"{event['symbol']} summary {exc}")
        return {"line": event["subject"], "text_note": str(exc)}
    line = " ".join(str(payload.get("line") or "").split())
    if not line:
        line = event["subject"]
    if from_pdf or not _has_pdf(event):
        cache.put(
            "summary_llm",
            event["symbol"],
            event["id"],
            EXTRACT_VERSION,
            {"line": line, "usage": call_usage, "text_note": note},
        )
    bucket = usage["summary"]
    bucket["calls"] += 1
    bucket["tokens"] += int(call_usage.get("total_tokens") or 0)
    return {"line": line}


def _has_pdf(event: dict) -> bool:
    return any((filing.get("pdf_url") or "").lower().split("?")[0].endswith(".pdf") for filing in event["filings"])


def _event_text(event: dict, client, cache, failures: list[str], limit: int) -> tuple[str, str, bool]:
    pieces = []
    used_pdf = False
    for filing in event["filings"]:
        url = filing.get("pdf_url") or ""
        if url.lower().split("?")[0].endswith(".pdf"):
            try:
                pieces.append(_load_pdf_text(client, cache, event["symbol"], filing.get("timestamp") or event["id"], url))
                used_pdf = True
            except (NSEError, OSError, RuntimeError) as exc:
                failures.append(f"{event['symbol']} pdf {type(exc).__name__}: {exc}")
                if filing.get("text"):
                    pieces.append(filing["text"])
        elif filing.get("text"):
            pieces.append(filing["text"])
    share = max(1500, limit // max(len(pieces), 1))
    note = "Attachment PDF." if used_pdf else "Exchange attachment text."
    return "\n\n".join(piece[:share] for piece in pieces)[:limit], note, used_pdf


def _alerts(symbols, events, cards_by_id: dict, start: date, end: date, move_pct: float, volume_n: float, alert_cap: int, failures: list[str]) -> list[dict]:
    try:
        bars = fetch_eod(symbols, start - timedelta(days=45), end)
    except Exception as exc:
        failures.append(f"prices {type(exc).__name__}: {exc}")
        return []
    found = []
    for symbol in symbols:
        for alert in detect_alerts(bars.get(symbol) or [], volume_n=volume_n, move_pct=move_pct, start=start, end=end):
            day = date.fromisoformat(alert["date"])
            nearby = []
            for event in events:
                if event["symbol"] != symbol:
                    continue
                if abs((event["when"].date() - day).days) <= 1:
                    card = cards_by_id.get(event["id"]) or {}
                    nearby.append(
                        {
                            "id": event["id"],
                            "category": event["category"],
                            "headline": event["subject"],
                            "summary": card.get("headline") or "",
                            "timestamp": event["when"].isoformat(timespec="seconds"),
                        }
                    )
            nearby.sort(key=lambda item: item["category"] != "results")
            found.append(
                {
                    "symbol": symbol,
                    "company": company_name(symbol),
                    "date": alert["date"],
                    "close": alert["close"],
                    "move_pct": alert["move_pct"],
                    "signed_move_pct": alert["signed_move_pct"],
                    "volume_ratio": alert["volume_ratio"],
                    "severity": alert["severity"],
                    "price_hit": alert["price_hit"],
                    "volume_hit": alert["volume_hit"],
                    "events": nearby[:6],
                }
            )
    found.sort(key=lambda alert: alert["severity"], reverse=True)
    return found[: max(alert_cap, 0)]


def _sources(event: dict) -> list[dict]:
    sources = []
    seen = set()
    for filing in sorted(event["filings"], key=lambda item: item["when"], reverse=True):
        urls = []
        if filing.get("pdf_url"):
            urls.append(filing["pdf_url"])
        if filing.get("xbrl_url"):
            urls.append(filing["xbrl_url"])
        for url in urls:
            if not url or url in seen:
                continue
            seen.add(url)
            sources.append(
                {
                    "subject": filing.get("subject") or "",
                    "url": url,
                    "timestamp": filing["when"].isoformat(timespec="seconds"),
                }
            )
    return sources


def _primary_url(event: dict) -> str:
    for source in _sources(event):
        if source["url"].lower().split("?")[0].endswith(".pdf"):
            return source["url"]
    sources = _sources(event)
    return sources[0]["url"] if sources else ""


def _management_headline(event: dict, body: dict) -> str:
    kind = (body.get("change_type") or "change").replace("_", " ")
    person = body.get("person") or ""
    role = body.get("role") or ""
    if person and role:
        return f"{kind.capitalize()}: {person}, {role}"
    if person:
        return f"{kind.capitalize()}: {person}"
    return event["subject"]


def _blank_management(note: str) -> dict:
    return {
        "person": None,
        "role": None,
        "change_type": None,
        "effective_date": None,
        "profile": None,
        "profile_note": note,
        "text_note": "",
    }


def _blank_to_none(value) -> str | None:
    text = " ".join(str(value or "").split())
    if not text or text.lower() in {"null", "none", "n/a", "na", "not available", "not mentioned", "nil", "-"}:
        return None
    return text


def _change_type(subject: str) -> str:
    folded = subject.lower()
    if "retir" in folded:
        return "retirement"
    if "resign" in folded:
        return "resignation"
    if "appoint" in folded:
        return "appointment"
    return "change_in_designation"


def _load(client: NSEClient, symbol: str, start: date, end: date, failures: list[str]) -> list[dict]:
    market = market_symbol(symbol)
    rows: list[dict] = []
    try:
        rows.extend(client.get_announcements(market, start, end))
    except NSEError as exc:
        failures.append(f"{symbol} announcements {exc}")
    try:
        rows.extend(client.get_financial_results(market, start, end))
    except NSEError as exc:
        failures.append(f"{symbol} results {exc}")
    return rows


def _label(row: dict):
    if row.get("filing_kind") == "results":
        return Classification("results", 0.98, PRIORITY["results"])
    return classify(row.get("subject") or "", row.get("text") or "")


def _parse_nse_dt(value: str) -> datetime | None:
    text = str(value or "").strip()
    parts = text.split("-")
    if len(parts) >= 3 and parts[1].isalpha():
        parts[1] = parts[1].title()
        text = "-".join(parts)
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _as_of(value) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, 23, 59, 59)
    text = str(value).strip()
    if len(text) == 10:
        day = datetime.strptime(text, "%Y-%m-%d")
        return day.replace(hour=23, minute=59, second=59)
    return datetime.fromisoformat(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the push feed JSON for a replayable window")
    parser.add_argument("--as-of", required=True, help="Window end. A date means 23:59:59 that day")
    parser.add_argument("--hours", type=float, default=24)
    parser.add_argument("--symbols", default="ALL")
    parser.add_argument("--move-pct", type=float, default=5.0)
    parser.add_argument("--volume-n", type=float, default=2.5)
    parser.add_argument("--alert-cap", type=int, default=8)
    args = parser.parse_args(argv)
    symbols = None if args.symbols.strip().upper() == "ALL" else [part.strip().upper() for part in args.symbols.split(",") if part.strip()]
    payload = build_feed(args.as_of, args.hours, symbols, args.move_pct, args.volume_n, args.alert_cap)
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    usage = payload["usage"]
    print(
        f"tokens {usage['total_tokens']}  management calls {usage['management_change']['calls']} "
        f"hits {usage['management_change']['cache_hits']}  summary calls {usage['summary']['calls']} "
        f"hits {usage['summary']['cache_hits']}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
