"""Prioritised filing digest for the portfolio.

    python -m finn_core.digest --hours 24 --symbols ALL
"""

import argparse
import sys
from datetime import date, datetime, timedelta

from finn_core import PORTFOLIO, market_symbol
from finn_core.cache import FileCache
from finn_core.classify import classify
from finn_core.nse_client import NSEClient, NSEError
from finn_core.prices import detect_alerts, fetch_eod

MATERIAL_MIN = 60


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    symbols = list(PORTFOLIO) if args.symbols.strip().upper() == "ALL" else [part.strip().upper() for part in args.symbols.split(",") if part.strip()]
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(hours=args.hours)
    start = start_dt.date()
    end = end_dt.date()

    cache = FileCache()
    client = NSEClient(cache=cache)
    items = []
    failures = []
    for symbol in symbols:
        try:
            rows = client.get_announcements(market_symbol(symbol), start, end)
        except NSEError as exc:
            failures.append((symbol, str(exc)))
            print(f"NSE {symbol} failed", file=sys.stderr)
            continue
        print(f"NSE {symbol} {len(rows)}", file=sys.stderr)
        for row in rows:
            when = _parse_nse_dt(row["timestamp"])
            if when is not None and not (start_dt <= when <= end_dt):
                continue
            labelled = classify(row["subject"], row["text"])
            items.append({**row, "symbol": symbol, "when": when, "label": labelled})

    print(_render(items, failures, start, end))
    print(_render_alerts(symbols, start, end, args.volume_n, args.move_pct))
    cache.close()
    return 0


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prioritised NSE filing digest")
    parser.add_argument("--hours", type=float, default=24, help="Look back this many hours (default 24)")
    parser.add_argument("--symbols", default="ALL", help="ALL, or a comma-separated ticker list")
    parser.add_argument("--volume-n", type=float, default=2.0, help="Alert when volume exceeds N times the prior 20 sessions")
    parser.add_argument("--move-pct", type=float, default=3.0, help="Alert when the absolute daily close move exceeds X percent")
    return parser.parse_args(argv)


def _render(items: list[dict], failures: list[tuple[str, str]], start: date, end: date) -> str:
    material = [item for item in items if _bucket(item) == "material"]
    routine = [item for item in items if _bucket(item) == "routine"]
    unsure = [item for item in items if _bucket(item) == "needs_llm"]
    material.sort(key=lambda item: (item["label"].priority, item["when"] or datetime.min), reverse=True)

    lines = [f"DIGEST {start.isoformat()} .. {end.isoformat()}  {len(items)} filings"]
    lines.append("")
    lines.append("MATERIAL")
    if not material:
        lines.append("  none")
    for item in material:
        label = item["label"]
        lines.append(
            f"  {label.priority:3d}  {label.category:<20}  {item['symbol']:<12}  {item['timestamp']:<22}  {item['subject']}"
        )
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


def _render_alerts(symbols: list[str], start: date, end: date, volume_n: float, move_pct: float) -> str:
    lines = ["", f"ALERTS  volume > {volume_n:g}x 20-day avg, or |move| > {move_pct:g}%"]
    try:
        history_start = start - timedelta(days=45)
        bars = fetch_eod(symbols, history_start, end)
    except Exception as exc:
        lines.append(f"  price fetch failed: {type(exc).__name__}: {exc}")
        return "\n".join(lines)
    any_alert = False
    missing = []
    for symbol in symbols:
        series = bars.get(symbol) or []
        if not series:
            missing.append(symbol)
            continue
        found = detect_alerts(series, volume_n=volume_n, move_pct=move_pct, start=start, end=end)
        for alert in found:
            any_alert = True
            bits = []
            if alert["price_hit"]:
                bits.append(f"move {alert['move_pct']}%")
            if alert["volume_hit"]:
                bits.append(f"volume {alert['volume_ratio']}x")
            lines.append(f"  {symbol:<12}  {alert['date']}  close {alert['close']}  {', '.join(bits)}")
    if not any_alert:
        lines.append("  none")
    if missing:
        lines.append("  no bars: " + ", ".join(missing))
    return "\n".join(lines)


def _bucket(item: dict) -> str:
    category = item["label"].category
    if category == "needs_llm":
        return "needs_llm"
    if category == "routine" or item["label"].priority < MATERIAL_MIN:
        return "routine"
    return "material"


def _parse_nse_dt(value: str) -> datetime | None:
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


if __name__ == "__main__":
    raise SystemExit(main())
