"""Last quarters of revenue, EBITDA, PBT, and PAT from each quarter's own XBRL.

One integrated filing contributes its current-quarter facts only. Figures are
INR crore. A quarter with no filing is kept in the list and flagged.

A filing whose OneD span is a half year is not used as that quarter. The
missing quarter is half minus the other quarter when that other quarter is
already in the series. Otherwise the quarter stays blank.
"""

from datetime import date, timedelta

from finn_core.config import market_symbol
from finn_core.documents import quarter_ends
from finn_core.nse_client import NSEClient, NSEError
from finn_core.results_card import _load_xbrl
from finn_core.xbrl_parse import ebitda, ebitda_block_reason, metrics_from, parse_period_end, parse_xbrl


SERIES_VERSION = "v1"


def quarterly_series(symbol: str, quarters: int = 6, as_of: date | None = None, client=None, cache=None) -> dict:
    as_of = as_of or date.today()
    symbol = symbol.upper()
    market = market_symbol(symbol)
    client = client or NSEClient(cache=cache)
    cache = cache if cache is not None else client.cache
    expected = quarter_ends(as_of, quarters)
    cached = _read_cached_series(cache, symbol, expected)
    if cached is not None:
        return {"symbol": symbol, "unit": "INR crore", "quarters": cached, "failures": []}
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
    halves = []
    ytds = []
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
        ytd = _ytd(statement, market, row.get("xbrl_url") or "")
        if ytd is not None:
            ytds.append({"period": period.isoformat(), **ytd})
        if statement.current is None:
            span = next((item for item in statement.periods if item.context_id == "OneD"), None)
            blank = _blank(period, ["current-quarter revenue or PAT is missing"])
            blank["source_url"] = row.get("xbrl_url") or ""
            if span is not None and span.start is not None and span.end is not None and (span.end - span.start).days > 100:
                blank["flags"] = [
                    f"OneD is {span.start.isoformat()} to {span.end.isoformat()}, not a single quarter"
                ]
                half_metrics = metrics_from(span)
                reason = ebitda_block_reason(market, row.get("xbrl_url") or "", half_metrics)
                half_value = None if reason else ebitda(half_metrics)
                halves.append(
                    {
                        "period": period.isoformat(),
                        "start": span.start.isoformat(),
                        "end": span.end.isoformat(),
                        "revenue": half_metrics.get("revenue"),
                        "ebitda": half_value,
                        "pbt": half_metrics.get("pbt"),
                        "pat": half_metrics.get("pat"),
                    }
                )
            output.append(blank)
            continue
        metrics = metrics_from(statement.current)
        flags = []
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
                "basis": "xbrl",
            }
        )
    apply_half_year(output, halves, ytds)
    if not any(item.get("step") == "integrated_results" for item in failures):
        _store_series(cache, symbol, output)
    return {"symbol": symbol, "unit": "INR crore", "quarters": output, "failures": failures}


def _read_cached_series(cache, symbol: str, expected: list[date]):
    """Every quarter must already be stored. One miss means the filing is parsed again."""
    if cache is None:
        return None
    quarters = []
    for period in expected:
        row = cache.get("series_quarter", symbol, period.isoformat(), SERIES_VERSION)
        if not isinstance(row, dict) or row.get("period") != period.isoformat():
            return None
        quarters.append(row)
    return quarters


def _store_series(cache, symbol: str, quarters: list[dict]) -> None:
    if cache is None:
        return
    for row in quarters:
        period = row.get("period") or ""
        if period:
            cache.put("series_quarter", symbol, period, SERIES_VERSION, row)


def half_pair(start: date, end: date) -> tuple[date, date] | None:
    """The two quarter-ends inside a standard Indian half year, earlier first."""
    days = (end - start).days
    if not 160 <= days <= 200:
        return None
    if end.month == 3 and end.day == 31 and start.month == 10 and start.day == 1:
        return date(start.year, 12, 31), end
    if end.month == 9 and end.day == 30 and start.month == 4 and start.day == 1:
        return date(end.year, 6, 30), end
    return None


def subtract_quarter(half: dict, earlier: dict) -> dict | None:
    """Later quarter = half-year minus the earlier quarter. Revenue must stay positive."""
    derived = {}
    for key in ("revenue", "ebitda", "pbt", "pat"):
        left, right = half.get(key), earlier.get(key)
        derived[key] = None if left is None or right is None else round(left - right, 2)
    if derived["revenue"] is None or derived["revenue"] <= 0:
        return None
    if derived["ebitda"] is not None:
        derived["ebitda_margin_pct"] = round(derived["ebitda"] / derived["revenue"] * 100.0, 2)
    else:
        derived["ebitda_margin_pct"] = None
    return derived


def apply_half_year(quarters: list[dict], halves: list[dict], ytds: list[dict] | None = None) -> None:
    by_period = {row["period"]: row for row in quarters}
    ytd_by = {item["period"]: item for item in ytds or []}
    for half in halves:
        row = by_period.get(half["period"])
        if row is None or row.get("revenue") is not None:
            continue
        start = date.fromisoformat(half["start"])
        end = date.fromisoformat(half["end"])
        pair = half_pair(start, end)
        if pair is None:
            row["flags"] = [f"OneD is {half['start']} to {half['end']}, not a single quarter"]
            continue
        earlier, later = pair
        if later.isoformat() != half["period"]:
            row["flags"] = [f"OneD is {half['start']} to {half['end']}, not a single quarter"]
            continue
        other = by_period.get(earlier.isoformat())
        if other is None or other.get("revenue") is None:
            row["flags"] = [
                f"OneD is {half['start']} to {half['end']}, a half year. "
                f"{earlier.isoformat()} is missing, so this quarter is left blank."
            ]
            continue
        if _one_d_is_the_quarter(half, ytd_by.get(half["period"]), ytd_by.get(earlier.isoformat())):
            _adopt(row, half)
            row["flags"] = [
                f"OneD is dated {half['start']} to {half['end']}, but {half['revenue']} equals "
                f"the year-to-date minus the {earlier.isoformat()} year-to-date, so this is the quarter itself."
            ]
            continue
        derived = subtract_quarter(half, other)
        if derived is None:
            row["flags"] = [
                f"OneD is {half['start']} to {half['end']}. Subtracting {earlier.isoformat()} "
                "did not produce a usable revenue figure, so this quarter is left blank."
            ]
            continue
        _adopt(row, derived)
        row["flags"] = [
            f"Derived: {later.isoformat()} = half-year {half['start']} to {half['end']} minus {earlier.isoformat()}."
        ]


def _ytd(statement, market: str, url: str) -> dict | None:
    span = next((item for item in statement.periods if item.context_id == "FourD"), None)
    if span is None:
        return None
    metrics = metrics_from(span)
    if metrics.get("revenue") is None:
        return None
    reason = ebitda_block_reason(market, url, metrics)
    return {
        "revenue": metrics.get("revenue"),
        "ebitda": None if reason else ebitda(metrics),
        "pbt": metrics.get("pbt"),
        "pat": metrics.get("pat"),
    }


def _one_d_is_the_quarter(half: dict, this_ytd: dict | None, earlier_ytd: dict | None) -> bool:
    """A six-month date can still hold the quarter, when the amount matches the change in year-to-date."""
    if not this_ytd or not earlier_ytd:
        return False
    left, right = this_ytd.get("revenue"), earlier_ytd.get("revenue")
    stated = half.get("revenue")
    if left is None or right is None or stated is None:
        return False
    implied = round(left - right, 2)
    if implied <= 0:
        return False
    return abs(implied - stated) <= max(1.0, 0.01 * abs(stated))


def _adopt(row: dict, values: dict) -> None:
    row["revenue"] = values.get("revenue")
    row["ebitda"] = values.get("ebitda")
    row["pbt"] = values.get("pbt")
    row["pat"] = values.get("pat")
    revenue, ebitda_value = row["revenue"], row["ebitda"]
    row["ebitda_margin_pct"] = (
        round(ebitda_value / revenue * 100.0, 2) if ebitda_value is not None and revenue else values.get("ebitda_margin_pct")
    )
    row["basis"] = "derived"
    row["ebitda_reason"] = "" if row["ebitda"] is not None else row.get("ebitda_reason") or ""


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
        "basis": "",
    }
