"""Compute one ledger at a time and store the finished ones.

The constituent list is NSE's Nifty 50 file. The 18 portfolio names and the
four ad-hoc names are added. A complete snapshot is skipped, so a later run
resumes. QuotaError stops the run. A failed ticker does not replace a
complete ledger.

    python scripts/prewarm.py
"""

import csv
import io
import json
import os
import sys
import time
from pathlib import Path

import requests

os.environ.setdefault("CACHE_BACKEND", "supabase")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from finn_core.api_routes import FEED_VERSION
from finn_core.cache import open_cache
from finn_core.config import PORTFOLIO
from finn_core.ledger import promise_ledger
from finn_core.llm import QuotaError
from finn_core.nse_client import NSEClient

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "snapshot"
NIFTY_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv"
# Used only when the official file cannot be downloaded. This is the file's
# contents on 11 Nov 2026, not a live read.
NIFTY_FALLBACK = (
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK", "BSE",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL", "CIPLA",
    "COALINDIA", "DRREDDY", "EICHERMOT", "ETERNAL", "GRASIM", "HCLTECH",
    "HDFCBANK", "HDFCLIFE", "HINDALCO", "HINDUNILVR", "ICICIBANK", "ITC",
    "INFY", "INDIGO", "JSWSTEEL", "JIOFIN", "KOTAKBANK", "LT", "M&M", "MARUTI",
    "MAXHEALTH", "NTPC", "NESTLEIND", "ONGC", "POWERGRID", "RELIANCE",
    "SBILIFE", "SHRIRAMFIN", "SBIN", "SUNPHARMA", "TCS", "TATACONSUM", "TMPV",
    "TATASTEEL", "TECHM", "TITAN", "TRENT", "ULTRACEMCO",
)
ADHOC = ("DMART", "ASIANPAINT", "ETERNAL", "PIDILITIND")
# The official file has no size column. These are the large names, and the
# names this project already tests, placed first. The rest follow the file.
PRIORITY = (
    "RELIANCE", "TCS", "HDFCBANK", "BHARTIARTL", "ICICIBANK", "INFY", "SBIN",
    "HINDUNILVR", "ITC", "LT", "BAJFINANCE", "HCLTECH", "MARUTI", "SUNPHARMA",
    "AXISBANK", "TITAN", "ASIANPAINT", "DMART", "MARICO", "PIDILITIND",
    "CGPOWER", "ETERNAL", "M&M", "BAJAJ-AUTO", "KOTAKBANK", "NTPC",
    "ULTRACEMCO", "TRENT", "BEL",
)
SCORED = {
    "delivered",
    "partly",
    "missed",
    "borderline",
    "tracking_ahead",
    "tracking_on_track",
    "tracking_behind",
}
FILE_CAP = 1_500_000
PAUSE = 3


def main() -> int:
    names, source = ticker_list()
    print("source", source, flush=True)
    print("tickers", len(names), " ".join(names), flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    cache = open_cache()
    client = NSEClient(cache=cache)
    rows = []
    stopped = ""
    try:
        for index, symbol in enumerate(names):
            if index:
                time.sleep(PAUSE)
            try:
                row = one(symbol, cache, client)
            except QuotaError:
                row = {
                    "symbol": symbol,
                    "status": "quota",
                    "scored": "",
                    "tokens": "",
                    "seconds": "",
                    "models": "",
                }
                rows.append(row)
                _status(cache, symbol, row)
                stopped = "quota"
                print("stop daily limit", symbol, flush=True)
                break
            rows.append(row)
            _status(cache, symbol, row)
            print(_line(row), flush=True)
            if row["status"] == "quota":
                stopped = "quota"
                break
    finally:
        _print_table(rows)
        used = _storage(cache)
        print("storage", used, flush=True)
        cache.close()
    if stopped == "quota":
        return 0
    return 0


def ticker_list() -> tuple[list[str], str]:
    nifty, source = _nifty()
    universe = set(nifty) | set(PORTFOLIO) | set(ADHOC)
    ordered: list[str] = []
    seen: set[str] = set()

    def add(items) -> None:
        for symbol in items:
            key = str(symbol).upper().strip()
            if not key or key in seen or key not in universe:
                continue
            seen.add(key)
            ordered.append(key)

    add(PRIORITY)
    add(nifty)
    add(PORTFOLIO)
    add(ADHOC)
    return ordered, source


def _nifty() -> tuple[tuple[str, ...], str]:
    try:
        response = requests.get(
            NIFTY_URL,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "text/csv"},
            timeout=30,
        )
        response.raise_for_status()
        symbols = []
        for row in csv.DictReader(io.StringIO(response.text)):
            symbol = (row.get("Symbol") or row.get("SYMBOL") or "").strip().upper()
            if symbol:
                symbols.append(symbol)
        if len(symbols) >= 45:
            return tuple(symbols), "official ind_nifty50list.csv"
    except requests.RequestException as exc:
        print("nifty list unavailable", type(exc).__name__, flush=True)
    return NIFTY_FALLBACK, "approximate copy of ind_nifty50list.csv from 2026-11-11"


def one(symbol: str, cache, client) -> dict:
    existing = _complete(cache, symbol)
    if existing is not None:
        _write_file(symbol, existing, replace=False)
        return _row(symbol, "skipped", existing, 0.0)
    started = time.perf_counter()
    packet = {"progress": {"stage": "discover", "done": 0, "total": 1}, "usage": {}}
    stalls = 0
    before = -1
    spent = 0
    try:
        while packet["progress"]["stage"] != "complete":
            packet = promise_ledger(symbol, client=client, cache=cache)
            spent += int((packet.get("usage") or {}).get("total_tokens") or 0)
            progress = packet["progress"]
            print(" ", symbol, progress, "tokens", packet["usage"]["total_tokens"], "spent", spent, flush=True)
            if progress["stage"] == "complete":
                break
            if progress["done"] <= before:
                stalls += 1
                if stalls >= 2:
                    break
            else:
                stalls = 0
            before = progress["done"]
            time.sleep(1)
    except QuotaError:
        raise
    except Exception as exc:
        seconds = round(time.perf_counter() - started, 1)
        print(" ", symbol, "error", type(exc).__name__, flush=True)
        return {
            "symbol": symbol,
            "status": "error",
            "scored": "",
            "tokens": spent,
            "seconds": seconds,
            "models": type(exc).__name__,
        }
    seconds = round(time.perf_counter() - started, 1)
    row = _row(symbol, "incomplete" if packet["progress"]["stage"] != "complete" else "complete", packet, seconds)
    row["tokens"] = spent
    if packet["progress"]["stage"] != "complete":
        return row
    _save(cache, symbol, packet)
    _write_file(symbol, packet, replace=True)
    return row


def _complete(cache, symbol: str):
    try:
        saved = cache.get("ledger_snapshot", symbol, "complete", FEED_VERSION)
    except Exception:
        return None
    if isinstance(saved, dict) and (saved.get("progress") or {}).get("stage") == "complete":
        return saved
    return None


def _save(cache, symbol: str, packet: dict) -> None:
    """A complete ledger is stored. Anything else is left untouched."""
    if (packet.get("progress") or {}).get("stage") != "complete":
        return
    try:
        cache.put("ledger_snapshot", symbol, "complete", FEED_VERSION, packet)
        cache.put("ledger_cursor", symbol, "v1", FEED_VERSION, {"stop": "complete"})
    except Exception as exc:
        print(" ", symbol, "store failed", type(exc).__name__, flush=True)


def _write_file(symbol: str, packet: dict, replace: bool) -> None:
    if (packet.get("progress") or {}).get("stage") != "complete":
        return
    safe = symbol.replace("&", "_").replace("/", "_")
    name = f"ledger-{safe}.json"
    path = OUT / name
    if path.exists() and not replace:
        _index(symbol, name)
        return
    text = json.dumps(packet, indent=2)
    if len(text.encode("utf-8")) > FILE_CAP:
        print(" ", symbol, "file skipped, larger than", FILE_CAP, flush=True)
        return
    path.write_text(text, encoding="utf-8")
    _index(symbol, name)


def _index(symbol: str, name: str) -> None:
    index_path = OUT / "index.json"
    index = {"feeds": {}, "ledgers": {}}
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
    index.setdefault("feeds", {})
    ledgers = index.setdefault("ledgers", {})
    if ledgers.get(symbol) == name and index_path.exists():
        return
    ledgers[symbol] = name
    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")


def _row(symbol: str, status: str, packet: dict, seconds: float) -> dict:
    usage = packet.get("usage") or {}
    return {
        "symbol": symbol,
        "status": status,
        "scored": _scored(packet),
        "tokens": usage.get("total_tokens", 0),
        "seconds": seconds,
        "models": ", ".join(_models(usage)),
    }


def _scored(packet: dict) -> int:
    return sum(1 for row in packet.get("rows") or [] if row.get("status") in SCORED)


def _models(usage: dict) -> list[str]:
    found = []
    for name in ("guidance", "verify", "verdict"):
        bucket = usage.get(name) or {}
        for model in list(bucket.get("models") or []) + [bucket.get("model") or ""]:
            if model and model not in found:
                found.append(model)
    return found


def _status(cache, symbol: str, row: dict) -> None:
    try:
        cache.put("prewarm", symbol, "status", "v1", row)
    except Exception as exc:
        print(" ", symbol, "progress not stored", type(exc).__name__, flush=True)


def _line(row: dict) -> str:
    return (
        f"{row['symbol']:14} {row['status']:12} scored={row['scored']} "
        f"tokens={row['tokens']} seconds={row['seconds']} models={row['models']}"
    )


def _print_table(rows: list[dict]) -> None:
    print("progress", flush=True)
    print(f"{'symbol':14} {'status':12} {'scored':>6} {'tokens':>8} {'seconds':>8} models", flush=True)
    for row in rows:
        print(
            f"{row['symbol']:14} {str(row['status']):12} {str(row['scored']):>6} "
            f"{str(row['tokens']):>8} {str(row['seconds']):>8} {row['models']}",
            flush=True,
        )


def _storage(cache) -> str:
    remote = getattr(cache, "remote", None)
    client = getattr(remote, "_client", None)
    base = getattr(remote, "_base", "")
    key = getattr(remote, "_key", "")
    if client is None or not base or not key:
        return "unavailable"
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Prefer": "count=exact"}
    total = 0
    count = 0
    start = 0
    page = 100
    while True:
        end = start + page - 1
        response = client.get(
            f"{base}/cache_entries",
            params={"select": "payload"},
            headers={**headers, "Range": f"{start}-{end}"},
            timeout=120.0,
        )
        if response.status_code not in (200, 206):
            return f"unread HTTP {response.status_code}"
        rows = response.json()
        if not isinstance(rows, list) or not rows:
            break
        for row in rows:
            total += len(json.dumps(row.get("payload"), separators=(",", ":")).encode("utf-8"))
        count += len(rows)
        if len(rows) < page:
            break
        start += page
    mebibytes = total / (1024 * 1024)
    return f"{count} cache rows, {mebibytes:.1f} MB of payload JSON. The free database limit is 500 MB."


if __name__ == "__main__":
    raise SystemExit(main())
