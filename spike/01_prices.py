"""Last 30 calendar days of EOD close and volume via yfinance (.NS)."""

from datetime import date, timedelta

import yfinance as yf

TICKERS = ["RELIANCE", "MARICO", "CGPOWER"]


def main() -> None:
    end = date.today() + timedelta(days=1)
    start = date.today() - timedelta(days=30)
    print(f"window {start.isoformat()} .. {date.today().isoformat()} (EOD)")
    for symbol in TICKERS:
        yahoo = f"{symbol}.NS"
        print(f"\n=== {yahoo} ===")
        frame = yf.download(
            yahoo,
            start=start.isoformat(),
            end=end.isoformat(),
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
        )
        if frame is None or frame.empty:
            print("no rows")
            continue
        view = frame
        if isinstance(frame.columns, type(frame.columns)) and getattr(frame.columns, "nlevels", 1) > 1:
            view = frame.droplevel(1, axis=1) if frame.columns.nlevels == 2 else frame
        cols = [c for c in ("Close", "Volume") if c in view.columns]
        print(f"rows {len(view)}")
        print(view[cols].tail(3).to_string())


if __name__ == "__main__":
    main()
