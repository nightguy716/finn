"""Prioritised filing digest for the portfolio.

    python -m finn_core.digest --hours 24 --symbols ALL
    python -m finn_core.digest --hours 168 --move-pct 5 --volume-n 2.5 --alert-cap 8
"""

import argparse
import sys
from datetime import date, datetime, timedelta

from finn_core.cache import FileCache
from finn_core.classify import MATERIAL_MIN, MEDIUM_MIN, PRIORITY, Classification, classify
from finn_core.config import PORTFOLIO, market_symbol
from finn_core.nse_client import NSEClient, NSEError
from finn_core.prices import detect_alerts, fetch_eod


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    symbols = list(PORTFOLIO) if args.symbols.strip().upper() == "ALL" else [part.strip().upper() for part in args.symbols.split(",") if part.strip()]
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(hours=args.hours)
    start = start_dt.date()
    end = end_dt.date()
    # One extra day so an alert can show the filing from the session before.
    fetch_start = start - timedelta(days=1)

    cache = FileCache()
    client = NSEClient(cache=cache)
    context = []
    failures = []
    for symbol in symbols:
        rows = _load(client, symbol, fetch_start, end, failures)
        for row in rows:
            when = _parse_nse_dt(row["timestamp"])
            if when is not None and (when.date() < fetch_start or when.date() > end):
                continue
            labelled = _label(row)
            context.append({**row, "symbol": symbol, "when": when, "label": labelled})

    items = [
        item
        for item in context
        if item["when"] is None or start_dt <= item["when"] <= end_dt
    ]
    print(_render(items, failures, start, end, symbols))
    print(_render_alerts(symbols, context, start, end, args.volume_n, args.move_pct, args.alert_cap))
    cache.close()
    return 0


def _load(client: NSEClient, symbol: str, start: date, end: date, failures: list) -> list[dict]:
    market = market_symbol(symbol)
    rows: list[dict] = []
    try:
        rows = client.get_announcements(market, start, end)
        print(f"NSE {symbol} {len(rows)}", file=sys.stderr)
    except NSEError as exc:
        failures.append((symbol, str(exc)))
        print(f"NSE {symbol} failed", file=sys.stderr)
    try:
        results = client.get_financial_results(market, start, end)
        print(f"NSE results {symbol} {len(results)}", file=sys.stderr)
        rows = rows + results
    except NSEError as exc:
        failures.append((symbol, f"results {exc}"))
        print(f"NSE results {symbol} failed", file=sys.stderr)
    return rows


def _label(row: dict) -> Classification:
    if row.get("filing_kind") == "results":
        return Classification("results", 0.98, PRIORITY["results"])
    return classify(row["subject"], row["text"])


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prioritised NSE filing digest")
    parser.add_argument("--hours", type=float, default=24, help="Look back this many hours (default 24)")
    parser.add_argument("--symbols", default="ALL", help="ALL, or a comma-separated ticker list")
    parser.add_argument("--volume-n", type=float, default=2.5, help="Alert when volume exceeds N times the prior 20 sessions (default 2.5)")
    parser.add_argument("--move-pct", type=float, default=5.0, help="Alert when the absolute daily close move exceeds X percent (default 5)")
    parser.add_argument("--alert-cap", type=int, default=8, help="How many alerts to print, highest severity first (default 8)")
    return parser.parse_args(argv)


def _render(items: list[dict], failures: list[tuple[str, str]], start: date, end: date, symbols: list[str]) -> str:
    material = [item for item in items if _bucket(item) == "material"]
    medium = [item for item in items if _bucket(item) == "medium"]
    routine = [item for item in items if _bucket(item) == "routine"]
    unsure = [item for item in items if _bucket(item) == "needs_llm"]
    material.sort(key=lambda item: (item["label"].priority, item["when"] or datetime.min), reverse=True)
    medium.sort(key=lambda item: (item["label"].priority, item["when"] or datetime.min), reverse=True)

    lines = [f"DIGEST {start.isoformat()} .. {end.isoformat()}  {len(items)} filings"]
    lines.append("")
    lines.append("MATERIAL")
    if not material:
        lines.append("  none")
    for item in material:
        lines.append(_filing_line(item))
    lines.append("")
    lines.append("MEDIUM")
    if not medium:
        lines.append("  none")
    for item in medium:
        lines.append(_filing_line(item))
    lines.append("")
    lines.append("NEEDS_LLM")
    if not unsure:
        lines.append("  none")
    for item in unsure:
        hint = f"  hint={item['label'].hint}" if item["label"].hint else ""
        lines.append(f"  {item['symbol']:<12}  {item['timestamp']:<22}  {item['subject']}{hint}")
    lines.append("")
    lines.append("ROUTINE")
    counts: dict[str, int] = {}
    for item in routine:
        counts[item["symbol"]] = counts.get(item["symbol"], 0) + 1
    if not counts:
        lines.append("  none")
    for symbol in sorted(counts):
        lines.append(f"  {symbol:<12}  {counts[symbol]}")
    lines.append("")
    lines.append("RESULTS BY TICKER")
    result_counts = {symbol: 0 for symbol in symbols}
    for item in items:
        if item["label"].category == "results":
            result_counts[item["symbol"]] = result_counts.get(item["symbol"], 0) + 1
    for symbol in symbols:
        lines.append(f"  {symbol:<12}  {result_counts.get(symbol, 0)}")
    lines.append("")
    lines.append("BY CATEGORY")
    totals: dict[str, int] = {}
    for item in items:
        name = item["label"].category
        totals[name] = totals.get(name, 0) + 1
    for name, count in sorted(totals.items(), key=lambda pair: (-pair[1], pair[0])):
        lines.append(f"  {name:<20}  {count}")
    lines.append("")
    lines.append("FAILURES")
    if not failures:
        lines.append("  none")
    for symbol, detail in failures:
        lines.append(f"  {symbol}  {detail}")
    return "\n".join(line for line in lines if line is not None)


def _filing_line(item: dict) -> str:
    label = item["label"]
    return f"  {label.priority:3d}  {label.category:<20}  {item['symbol']:<12}  {item['timestamp']:<22}  {item['subject']}"


def _render_alerts(
    symbols: list[str],
    context: list[dict],
    start: date,
    end: date,
    volume_n: float,
    move_pct: float,
    alert_cap: int,
) -> str:
    lines = ["", f"ALERTS  one per ticker per day, top {alert_cap} by |move| x volume  (N={volume_n:g}x, X={move_pct:g}%)"]
    try:
        history_start = start - timedelta(days=45)
        bars = fetch_eod(symbols, history_start, end)
    except Exception as exc:
        lines.append(f"  price fetch failed: {type(exc).__name__}: {exc}")
        return "\n".join(lines)
    found = []
    missing = []
    for symbol in symbols:
        series = bars.get(symbol) or []
        if not series:
            missing.append(symbol)
            continue
        for alert in detect_alerts(series, volume_n=volume_n, move_pct=move_pct, start=start, end=end):
            found.append({**alert, "symbol": symbol})
    found.sort(key=lambda alert: alert["severity"], reverse=True)
    shown = found[: max(alert_cap, 0)]
    if not shown:
        lines.append("  none")
    else:
        lines.append(f"  showing {len(shown)} of {len(found)}")
    for alert in shown:
        bits = [f"sev {alert['severity']:g}", f"move {alert['move_pct']}%"]
        if alert["volume_ratio"] is not None:
            bits.append(f"volume {alert['volume_ratio']}x")
        lines.append(f"  {alert['symbol']:<12}  {alert['date']}  close {alert['close']}  {', '.join(bits)}")
        day = date.fromisoformat(alert["date"])
        nearby = _nearby(context, alert["symbol"], day)
        if not nearby:
            lines.append("      no filing within 1 day")
            continue
        for item in nearby:
            lines.append("    " + _filing_line(item).rstrip())
    if missing:
        lines.append("  no bars: " + ", ".join(missing))
    return "\n".join(lines)


def _nearby(context: list[dict], symbol: str, day: date) -> list[dict]:
    found = []
    for item in context:
        if item["symbol"] != symbol or item["when"] is None:
            continue
        if abs((item["when"].date() - day).days) <= 1:
            found.append(item)
    found.sort(key=lambda item: (item["label"].priority, item["when"] or datetime.min), reverse=True)
    return found[:6]


def _bucket(item: dict) -> str:
    label = item["label"]
    if label.category == "needs_llm":
        return "needs_llm"
    if label.priority >= MATERIAL_MIN:
        return "material"
    if label.priority >= MEDIUM_MIN:
        return "medium"
    return "routine"


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


if __name__ == "__main__":
    raise SystemExit(main())
