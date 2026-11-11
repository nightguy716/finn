"""EOD close and volume, plus volume and price-move alerts."""

from datetime import date, timedelta

import yfinance as yf

from finn_core.config import market_symbol


EOD_ENOUGH = 21


def cached_eod(symbols: list[str], start: date, end: date, cache=None) -> tuple[dict[str, list[dict]], str | None]:
    """Bars for these symbols. A stored series of 21 or more sessions is kept.

    A later download replaces stored bars only when it is at least as long.
    A failed or short download does not wipe a longer series.
    """
    kept: dict[str, list[dict]] = {}
    short: dict[str, list[dict]] = {}
    missing: list[str] = []
    for symbol in symbols:
        rows = _read_bars(cache, symbol, start, end)
        if len(rows) >= EOD_ENOUGH:
            kept[symbol] = rows
        else:
            short[symbol] = rows
            missing.append(symbol)
    fresh: dict[str, list[dict]] = {}
    error = None
    if missing:
        try:
            fresh = fetch_eod(missing, start, end)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
    out: dict[str, list[dict]] = {}
    for symbol in symbols:
        if symbol in kept:
            out[symbol] = kept[symbol]
            continue
        got = fresh.get(symbol) or []
        old = short.get(symbol) or []
        if got and len(got) >= len(old):
            _write_bars(cache, symbol, start, end, got)
            out[symbol] = got
        else:
            out[symbol] = old
    return out, error


def fetch_eod(symbols: list[str], start: date, end: date) -> dict[str, list[dict]]:
    """Daily bars from `start` through `end`, inclusive of `end`."""
    if not symbols:
        return {}
    frame = yf.download(
        [f"{market_symbol(symbol)}.NS" for symbol in symbols],
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        interval="1d",
        auto_adjust=False,
        group_by="ticker",
        progress=False,
        threads=False,
    )
    return {symbol: _bars(frame, market_symbol(symbol)) for symbol in symbols}


def detect_alerts(
    bars: list[dict],
    *,
    volume_n: float = 2.5,
    move_pct: float = 5.0,
    start: date | None = None,
    end: date | None = None,
) -> list[dict]:
    """One alert per session when volume exceeds N times the prior 20, or the close moves more than X%.

    Move and volume are one row. Severity is |move %| times the volume ratio
    (ratio 1 when the 20-day average is not available), so a large move on
    heavy volume ranks first.
    """
    alerts = []
    for index, bar in enumerate(bars):
        if start is not None and bar["date"] < start:
            continue
        if end is not None and bar["date"] > end:
            continue
        if index < 1 or not bar["close"] or not bars[index - 1]["close"]:
            continue
        signed = (bar["close"] / bars[index - 1]["close"] - 1.0) * 100.0
        move = abs(signed)
        prior = bars[max(0, index - 20) : index]
        ratio = None
        if len(prior) >= 20:
            average = sum(item["volume"] for item in prior[-20:]) / 20.0
            if average > 0:
                ratio = bar["volume"] / average
        volume_hit = ratio is not None and ratio > volume_n
        price_hit = move > move_pct
        if not volume_hit and not price_hit:
            continue
        weight = ratio if ratio is not None else 1.0
        alerts.append(
            {
                "date": bar["date"].isoformat(),
                "close": round(bar["close"], 2),
                "move_pct": round(move, 2),
                "signed_move_pct": round(signed, 2),
                "volume_ratio": round(ratio, 2) if ratio is not None else None,
                "volume_hit": volume_hit,
                "price_hit": price_hit,
                "severity": round(move * weight, 2),
            }
        )
    return alerts


def _bar_key(end: date) -> str:
    return f"{end.isoformat()}|v1"


def _read_bars(cache, symbol: str, start: date, end: date) -> list[dict]:
    if cache is None:
        return []
    try:
        raw = cache.get("eod_bars", symbol, start.isoformat(), _bar_key(end))
    except Exception:
        return []
    rows = []
    for item in raw or []:
        if not isinstance(item, dict) or item.get("date") is None:
            continue
        day = item["date"]
        if isinstance(day, str):
            day = date.fromisoformat(day[:10])
        rows.append({"date": day, "close": float(item["close"]), "volume": float(item.get("volume") or 0)})
    rows.sort(key=lambda item: item["date"])
    return rows


def _write_bars(cache, symbol: str, start: date, end: date, rows: list[dict]) -> None:
    if cache is None or not rows:
        return
    payload = [
        {"date": bar["date"].isoformat(), "close": bar["close"], "volume": bar["volume"]}
        for bar in rows
    ]
    try:
        cache.put("eod_bars", symbol, start.isoformat(), _bar_key(end), payload)
    except Exception:
        return


def _bars(frame, symbol: str) -> list[dict]:
    if frame is None or getattr(frame, "empty", True):
        return []
    yahoo = f"{symbol}.NS"
    columns = frame.columns
    if getattr(columns, "nlevels", 1) > 1:
        level0 = set(columns.get_level_values(0))
        if yahoo in level0:
            view = frame[yahoo]
        elif symbol in level0:
            view = frame[symbol]
        else:
            return []
    else:
        view = frame
    if "Close" not in view.columns or "Volume" not in view.columns:
        return []
    view = view.dropna(subset=["Close", "Volume"])
    rows = []
    for stamp, close, volume in zip(view.index, view["Close"], view["Volume"]):
        rows.append(
            {
                "date": stamp.date() if hasattr(stamp, "date") else stamp,
                "close": float(close),
                "volume": float(volume or 0),
            }
        )
    rows.sort(key=lambda item: item["date"])
    return rows
