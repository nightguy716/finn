"""Pull-side documents for one ticker: transcripts, annual report, quarterly series.

    python -m finn_core.pull TITAN MARICO CGPOWER DMART ASIANPAINT
"""

import argparse
import json
import sys

from finn_core.cache import FileCache
from finn_core.documents import extract_pdf, find_annual_report, find_transcripts
from finn_core.nse_client import NSEClient
from finn_core.series import quarterly_series


def build_pull(symbol: str, client=None, cache=None) -> dict:
    """Discovery plus page-numbered transcript text. No model calls."""
    client = client or NSEClient(cache=cache)
    cache = cache if cache is not None else client.cache
    transcripts = find_transcripts(symbol, client=client, cache=cache)
    annual = find_annual_report(symbol, client=client, cache=cache)
    series = quarterly_series(symbol, client=client, cache=cache)
    texts = []
    failures = list(transcripts["failures"]) + list(annual["failures"]) + list(series["failures"])
    for row in transcripts["quarters"]:
        if row["status"] != "found":
            continue
        if not _looks_like_pdf(row["url"]):
            failures.append(
                {
                    "symbol": symbol.upper(),
                    "step": "extract",
                    "detail": f"{row['period']} transcript URL is not a PDF: {row['url']}",
                }
            )
            continue
        extracted = extract_pdf(symbol, row["url"], client=client, cache=cache)
        if extracted.get("error"):
            failures.append({"symbol": symbol.upper(), "step": "extract", "detail": f"{row['period']} {extracted['error']}"})
        elif extracted.get("scanned"):
            failures.append(
                {
                    "symbol": symbol.upper(),
                    "step": "extract",
                    "detail": f"{row['period']} PDF has {extracted['page_count']} pages and almost no text; it looks scanned.",
                }
            )
        texts.append(
            {
                "period": row["period"],
                "url": row["url"],
                "chars": extracted.get("chars") or 0,
                "page_count": extracted.get("page_count") or 0,
                "scanned": bool(extracted.get("scanned")),
                "error": extracted.get("error") or "",
            }
        )
    return {
        "symbol": symbol.upper(),
        "transcripts": transcripts["quarters"],
        "annual_report": {key: annual[key] for key in ("year", "url", "route", "status")},
        "series": series["quarters"],
        "text": texts,
        "failures": failures,
    }


def _looks_like_pdf(url: str) -> bool:
    path = url.lower().split("?")[0]
    if path.endswith(".pdf"):
        return True
    return ".pdf" in url.lower() and not path.endswith((".mp3", ".mp4", ".wav"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover filings and the quarterly series for NSE tickers")
    parser.add_argument("symbols", nargs="*", default=["TITAN", "MARICO", "CGPOWER", "DMART", "ASIANPAINT"])
    args = parser.parse_args()
    cache = FileCache()
    client = NSEClient(cache=cache)
    packets = []
    for symbol in args.symbols:
        packet = build_pull(symbol, client=client, cache=cache)
        packets.append(packet)
        found = sum(1 for row in packet["transcripts"] if row["status"] == "found")
        chars = sum(row["chars"] for row in packet["text"])
        print(f"{symbol}: transcripts {found}/5 chars {chars} failures {len(packet['failures'])}", file=sys.stderr)
    json.dump(packets, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
