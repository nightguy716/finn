"""Read-only HTTP routes. One Vercel function dispatches to these.

A stored feed or ledger is returned as-is. Supabase being paused falls back
to the JSON files in data/snapshot. A cold ledger does one stage per call.
"""

import json
from pathlib import Path

from finn_core.cache import open_cache
from finn_core.config import PORTFOLIO
from finn_core.feed import build_feed, order_alerts
from finn_core.ledger import promise_ledger
from finn_core.nse_client import NSEClient

SNAPSHOT_DIR = Path(__file__).resolve().parents[1] / "data" / "snapshot"
FEED_VERSION = "v1"
DEFAULT_MOVE = 5.0
DEFAULT_VOLUME = 2.5


def health() -> dict:
    return {"ok": True}


def alert_config() -> dict:
    return {"move_pct": DEFAULT_MOVE, "volume_n": DEFAULT_VOLUME}


def feed_view(params: dict) -> dict:
    as_of = _one(params, "as_of", "2026-11-06")
    hours = float(_one(params, "hours", "24"))
    move_pct = float(_one(params, "move_pct", str(DEFAULT_MOVE)))
    volume_n = float(_one(params, "volume_n", str(DEFAULT_VOLUME)))
    raw_symbols = _one(params, "symbols", "")
    symbols = [part.strip().upper() for part in raw_symbols.split(",") if part.strip()] or None
    key = feed_key(as_of, hours, symbols, move_pct, volume_n)
    cache, failed = _open()
    if cache is not None and not failed:
        try:
            hit = cache.get("feed_snapshot", "FEED", key, FEED_VERSION)
        except Exception:
            failed = True
            hit = None
        if isinstance(hit, dict) and hit.get("cards") is not None:
            return _serve(hit, "cache")
    filed = _file_for("feeds", key)
    if isinstance(filed, dict) and filed.get("cards") is not None:
        if cache is not None and not failed:
            try:
                cache.put("feed_snapshot", "FEED", key, FEED_VERSION, filed)
            except Exception:
                pass
        return _serve(filed, "file")
    if cache is None or failed:
        raise RuntimeError("cache is unavailable")
    payload = build_feed(as_of, hours, symbols, move_pct, volume_n, cache=cache, client=NSEClient(cache=cache))
    try:
        cache.put("feed_snapshot", "FEED", key, FEED_VERSION, payload)
    except Exception:
        pass
    return _serve(payload, "computed")


def _serve(payload: dict, source: str) -> dict:
    alerts = payload.get("alerts")
    if isinstance(alerts, list):
        payload = {**payload, "alerts": order_alerts(alerts)}
    return {**payload, "source": source}


def ledger_view(params: dict) -> dict:
    symbol = _one(params, "symbol", "").upper().strip()
    if not symbol:
        raise ValueError("symbol is required")
    cache, failed = _open()
    if cache is not None and not failed:
        try:
            saved = cache.get("ledger_snapshot", symbol, "complete", FEED_VERSION)
        except Exception:
            failed = True
            saved = None
        if isinstance(saved, dict) and (saved.get("progress") or {}).get("stage") == "complete":
            return {"progress": saved["progress"], "ledger": saved, "source": "cache"}
    filed = _file_for("ledgers", symbol)
    if failed and filed is not None:
        progress = filed.get("progress") or {"stage": "complete", "done": 0, "total": 0}
        return {"progress": progress, "ledger": filed, "source": "file"}
    if cache is None:
        if filed is not None:
            progress = filed.get("progress") or {"stage": "complete", "done": 0, "total": 0}
            return {"progress": progress, "ledger": filed, "source": "file"}
        raise RuntimeError("cache is unavailable")
    cursor = cache.get("ledger_cursor", symbol, "v1", FEED_VERSION) or {}
    stop = cursor.get("stop") or "discover"
    if stop == "complete":
        packet = promise_ledger(symbol, client=NSEClient(cache=cache), cache=cache, max_guidance_calls=1)
    else:
        packet = promise_ledger(
            symbol,
            client=NSEClient(cache=cache),
            cache=cache,
            max_guidance_calls=1,
            stop_after=stop,
        )
    progress = packet["progress"]
    if stop == "discover":
        nxt = "series"
    elif stop == "series":
        nxt = "guidance"
    elif progress.get("stage") == "complete":
        nxt = "complete"
        cache.put("ledger_snapshot", symbol, "complete", FEED_VERSION, packet)
    else:
        nxt = "guidance"
    cache.put("ledger_cursor", symbol, "v1", FEED_VERSION, {"stop": nxt})
    return {"progress": progress, "ledger": packet, "source": "computed"}


def feed_key(as_of: str, hours: float, symbols: list[str] | None, move_pct: float, volume_n: float) -> str:
    names = "*" if not symbols else ",".join(sorted(symbols))
    return f"{as_of}|{hours:g}|{move_pct:g}|{volume_n:g}|{names}"


def snapshot_index() -> dict:
    path = SNAPSHOT_DIR / "index.json"
    if not path.exists():
        return {"feeds": {}, "ledgers": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _file_for(kind: str, key: str):
    name = (snapshot_index().get(kind) or {}).get(key)
    if not name:
        return None
    path = SNAPSHOT_DIR / name
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _open():
    try:
        return open_cache(), False
    except Exception:
        return None, True


def _one(params: dict, name: str, default: str) -> str:
    value = params.get(name)
    if isinstance(value, list):
        value = value[0] if value else ""
    if value is None or value == "":
        return default
    return str(value)


def portfolio() -> list[str]:
    return list(PORTFOLIO)
