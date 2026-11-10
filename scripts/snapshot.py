"""Store the replay feeds and the five demo ledgers.

JSON files land in data/snapshot. The same objects are written to Supabase
when CACHE_BACKEND=supabase. Raw XBRL stays on the local disk.
"""

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("CACHE_BACKEND", "supabase")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from finn_core.api_routes import FEED_VERSION, feed_key
from finn_core.cache import FileCache, open_cache
from finn_core.feed import build_feed
from finn_core.ledger import promise_ledger
from finn_core.nse_client import NSEClient

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "snapshot"
LEDGERS = ("MARICO", "ASIANPAINT", "TITAN", "CGPOWER", "DMART", "PIDILITIND", "WIPRO")
KEEP = {
    "guidance_llm",
    "verdict_llm",
    "doc_text",
    "pdf_text",
    "pdf_llm",
    "mgmt_llm",
    "summary_llm",
    "nse_announcements",
    "nse_integrated_results",
    "nse_annual_reports",
    "screener_html",
    "ir_html",
    "series_quarter",
    "results_card",
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    remote = open_cache()
    copied = _copy(remote)
    print("copied", copied, flush=True)
    client = NSEClient(cache=remote)
    index = {"feeds": {}, "ledgers": {}}
    for hours in (24, 72):
        print("feed", hours, flush=True)
        payload = build_feed("2026-11-06", hours, cache=remote, client=client)
        key = feed_key("2026-11-06", hours, None, 5, 2.5)
        name = f"feed-2026-11-06-{hours}.json"
        _dump(name, payload)
        remote.put("feed_snapshot", "FEED", key, FEED_VERSION, payload)
        index["feeds"][key] = name
        print("feed", hours, "cards", len(payload["cards"]), "alerts", len(payload["alerts"]), "tokens", payload["usage"]["total_tokens"], flush=True)
    for symbol in LEDGERS:
        packet = _finish(symbol, remote, client)
        name = f"ledger-{symbol}.json"
        _dump(name, packet)
        remote.put("ledger_snapshot", symbol, "complete", FEED_VERSION, packet)
        remote.put("ledger_cursor", symbol, "v1", FEED_VERSION, {"stop": "complete"})
        index["ledgers"][symbol] = name
        print("ledger", symbol, packet["progress"], "tokens", packet["usage"]["total_tokens"], flush=True)
    _dump("index.json", index)
    _prove_no_xbrl(remote)
    remote.close()


def _copy(remote) -> int:
    local = FileCache()
    rows = local._db.execute("select source, symbol, start, end, payload from cache").fetchall()
    count = 0
    for source, symbol, start, end, payload in rows:
        if source not in KEEP:
            continue
        remote.put(source, symbol, start, end, json.loads(payload))
        count += 1
        if count % 25 == 0:
            print("copy", count, source, symbol, flush=True)
    local.close()
    return count


def _finish(symbol, cache, client) -> dict:
    packet = {"progress": {"stage": "guidance", "done": 0, "total": 1}}
    stalls = 0
    while packet["progress"]["stage"] != "complete":
        before = packet["progress"]["done"]
        packet = promise_ledger(symbol, client=client, cache=cache)
        print(" ", symbol, packet["progress"], "gtok", packet["usage"]["guidance"]["tokens"], flush=True)
        if packet["progress"]["done"] <= before:
            stalls += 1
            if stalls >= 2:
                break
    return packet


def _prove_no_xbrl(cache) -> None:
    client = NSEClient(cache=cache)
    calls = []
    original = client.get_bytes

    def wrapped(url, symbol=""):
        calls.append(url)
        return original(url, symbol)

    client.get_bytes = wrapped
    packet = promise_ledger("MARICO", client=client, cache=cache)
    print("warm_marico", packet["progress"], "tokens", packet["usage"]["total_tokens"], "downloads", len(calls), flush=True)


def _dump(name: str, payload) -> None:
    (OUT / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
