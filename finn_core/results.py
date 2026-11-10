"""Print results cards.

    python -m finn_core.results TITAN BHARATFORG MARICO RELIANCE TRENT ITC HDFCBANK
"""

import json
import sys
from datetime import date

from finn_core.cache import FileCache
from finn_core.nse_client import NSEClient, _broadcast_sort
from finn_core.results_card import build_results_card, find_results_pdf, pdf_text
from finn_core.xbrl_parse import parse_period_end

DEFAULT = ["TITAN", "BHARATFORG", "MARICO", "RELIANCE", "TRENT", "ITC", "HDFCBANK"]
CHECK = ("TITAN", "MARICO")


def main(argv: list[str] | None = None) -> int:
    symbols = [part.upper() for part in (argv if argv is not None else sys.argv[1:]) if part.strip()]
    if not symbols:
        symbols = list(DEFAULT)
    cache = FileCache()
    client = NSEClient(cache=cache)
    cards = []
    for symbol in symbols:
        print(f"card {symbol}", file=sys.stderr)
        card = build_results_card(symbol, client, cache)
        cards.append(card)
        print(json.dumps(card, indent=2))
        print()
    print(_summary(cards))
    checks = [card for card in cards if card["symbol"] in CHECK and card.get("source") == "xbrl"]
    if checks:
        print()
        print(_cross_check(client, cache, checks))
    cache.close()
    return 0


def _summary(cards: list[dict]) -> str:
    lines = ["SUMMARY"]
    tokens = 0
    for card in cards:
        usage = card.get("usage") or {}
        tokens += int(usage.get("total_tokens") or 0)
        revenue = (card.get("metrics") or {}).get("revenue") or {}
        pat = (card.get("metrics") or {}).get("pat") or {}
        ebitda = (card.get("metrics") or {}).get("ebitda")
        ebitda_now = "" if ebitda is None else ebitda.get("current")
        flags = "; ".join(card.get("flags") or []) or "none"
        lines.append(
            f"  {card['symbol']:<12} {card.get('period') or '-':<12} {card.get('source') or 'FAILED':<8} "
            f"rev {revenue.get('current')}  ebitda {ebitda_now}  pat {pat.get('current')}  flags {flags}"
        )
    lines.append(f"model tokens {tokens}")
    return "\n".join(lines)


def _cross_check(client, cache, cards: list[dict]) -> str:
    lines = ["PDF CROSS-CHECK"]
    for card in cards:
        period_end = parse_period_end(card.get("period") or "")
        broadcast = _broadcast_sort(card.get("broadcast") or "")
        day = broadcast.date() if broadcast.year > 2000 else period_end or date.today()
        url = find_results_pdf(client, card["symbol"], day)
        if not url:
            lines.append(f"  {card['symbol']}: no results PDF next to the broadcast")
            continue
        try:
            text = _pdf_text_cached(client, cache, card["symbol"], card.get("period_label") or card.get("period") or "", url)
        except Exception as exc:
            lines.append(f"  {card['symbol']}: PDF read failed {type(exc).__name__}")
            continue
        lines.append(f"  {card['symbol']} pdf {url}")
        metrics = card.get("metrics") or {}
        for key in ("revenue", "pbt", "pat"):
            block = metrics.get(key) or {}
            lines.append(
                f"    {key} XBRL current {block.get('current')}  qoq {block.get('qoq')}  yoy {block.get('yoy')}"
            )
        for label in ("revenue from operations", "profit before tax", "profit for the period"):
            excerpt = _excerpt_at(text, label)
            if excerpt:
                lines.append(f"    pdf {label}: {excerpt}")
    return "\n".join(lines)


def _pdf_text_cached(client, cache, symbol: str, period: str, url: str) -> str:
    cached = cache.get("pdf_text", symbol, period, url)
    if isinstance(cached, str) and cached:
        return cached
    data = client.get_bytes(url, symbol)
    text = pdf_text(data)
    cache.put("pdf_text", symbol, period, url, text)
    return text


def _excerpt_at(text: str, label: str) -> str:
    folded = text.lower()
    index = folded.find(label)
    if index < 0:
        return ""
    return " ".join(text[index : index + 280].split())


if __name__ == "__main__":
    raise SystemExit(main())
