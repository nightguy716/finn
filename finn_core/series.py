"""Last quarters of revenue, EBITDA, PBT, and PAT from each quarter's own XBRL.

One integrated filing contributes its current-quarter facts only. Figures are
INR crore. A quarter with no filing is kept in the list and flagged.
"""

from datetime import date, timedelta

from finn_core.config import market_symbol
from finn_core.documents import quarter_ends
from finn_core.nse_client import NSEClient, NSEError
from finn_core.results_card import _load_xbrl
from finn_core.xbrl_parse import ebitda, ebitda_block_reason, metrics_from, parse_period_end, parse_xbrl


def quarterly_series(symbol: str, quarters: int = 6, as_of: date | None = None, client=None, cache=None) -> dict:
    as_of = as_of or date.today()
    symbol = symbol.upper()
    market = market_symbol(symbol)
    client = client or NSEClient(cache=cache)
    cache = cache if cache is not None else client.cache
    expected = quarter_ends(as_of, quarters)
    failures = []
    by_period = {}
    try:
        rows = client.get_financial_results(market, expected[-1] - timedelta(days=100), as_of)
    except NSEError as exc:
        rows = []
        failures.append({"symbol": symbol, "step": "integrated_results", "detail": str(exc)})
    for row in rows:
        period = parse_period_end(row.get("period_end") or "")
        if period is not None:
            by_period[period] = row
    output = []
    for period in expected:
        row = by_period.get(period)
        if row is None or not row.get("xbrl_url"):
            output.append(_blank(period, ["missing"]))
            continue
        try:
            statement = parse_xbrl(_load_xbrl(client, cache, market, row))
        except (NSEError, OSError, RuntimeError, ValueError) as exc:
            failures.append({"symbol": symbol, "step": "xbrl", "detail": f"{period.isoformat()} {exc}"})
            output.append(_blank(period, ["xbrl unreadable"]))
            continue
        metrics = metrics_from(statement.current)
        flags = []
        if statement.current is None:
            span = next((item for item in statement.periods if item.context_id == "OneD"), None)
            if span is not None and span.start is not None and span.end is not None and (span.end - span.start).days > 100:
                flags.append(
                    f"OneD is {span.start.isoformat()} to {span.end.isoformat()}, not a single quarter"
                )
            else:
                flags.append("current-quarter revenue or PAT is missing")
            reason = ""
            value = None
        else:
            if metrics.get("revenue") is None or metrics.get("pat") is None:
                flags.append("current-quarter revenue or PAT is missing")
            reason = ebitda_block_reason(market, row.get("xbrl_url") or "", metrics)
            value = None if reason else ebitda(metrics)
        revenue = metrics.get("revenue")
        margin = round(value / revenue * 100.0, 2) if value is not None and revenue else None
        output.append(
            {
                "period": period.isoformat(),
                "revenue": revenue,
                "ebitda": value,
                "ebitda_margin_pct": margin,
                "pbt": metrics.get("pbt"),
                "pat": metrics.get("pat"),
                "source_url": row.get("xbrl_url") or "",
                "flags": flags,
                "ebitda_reason": reason,
            }
        )
    return {"symbol": symbol, "unit": "INR crore", "quarters": output, "failures": failures}


def _blank(period: date, flags: list[str]) -> dict:
    return {
        "period": period.isoformat(),
        "revenue": None,
        "ebitda": None,
        "ebitda_margin_pct": None,
        "pbt": None,
        "pat": None,
        "source_url": "",
        "flags": flags,
        "ebitda_reason": "",
    }
