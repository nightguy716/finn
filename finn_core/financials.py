"""Balance sheet and cash quality from one integrated-filing XBRL.

No model call. Quarterly filings do not carry the balance sheet, so the latest
half-year or full-year filing that does is used. A quarter is never mixed into
a half-year or full-year ratio. Banks, NBFCs and insurers are marked, and
debt-to-equity and working capital are not computed for them.
"""

from datetime import date, timedelta

from finn_core.config import market_symbol
from finn_core.nse_client import NSEClient, NSEError
from finn_core.results_card import _load_xbrl
from finn_core.xbrl_parse import _date, _divisor, _local, _number, _scale, parse_period_end

VERSION = "v2"
XBRLI = "http://www.xbrl.org/2003/instance"

INSTANT = ("OneI", "PY_I")
FLOW = "FourD"
FACE = (
    "BorrowingsCurrent",
    "BorrowingsNoncurrent",
    "Borrowings",
    "Equity",
    "CashAndCashEquivalents",
    "Inventories",
    "TradeReceivablesCurrent",
    "TradeReceivablesNoncurrent",
    "TradeReceivables",
    "TradePayablesCurrent",
    "TradePayablesNoncurrent",
    "TradePayables",
    "RevenueFromOperations",
    "ProfitLossForPeriod",
    "ProfitOrLossAttributableToOwnersOfParent",
    "ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates",
    "CashFlowsFromUsedInOperatingActivities",
    "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
    "PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities",
    "InterestEarned",
    "Deposits",
    "Advances",
    "GrossPremiumWritten",
    "PremiumEarned",
    "NetPremiumIncome",
)


def company_financials(symbol: str, cache=None, client=None) -> dict:
    """One request. A stored period returns at once."""
    import time

    started = time.perf_counter()
    symbol = symbol.upper().strip()
    if not symbol:
        raise ValueError("symbol is required")
    client = client or NSEClient(cache=cache)
    if cache is not None:
        saved = cache.get("financials", symbol, "latest", VERSION)
        if isinstance(saved, dict) and saved.get("status") in {"ready", "not_found"}:
            return {**saved, "source": "cache", "seconds": round(time.perf_counter() - started, 1)}
    try:
        body = _build(symbol, client, cache)
    except NSEError as exc:
        body = {"symbol": symbol, "status": "unavailable", "message": f"The filings could not be read ({type(exc).__name__}).", "usage": {"total_tokens": 0}}
    body["source"] = body.get("source") or "computed"
    body["seconds"] = round(time.perf_counter() - started, 1)
    if cache is not None and body.get("status") in {"ready", "not_found"}:
        cache.put("financials", symbol, "latest", VERSION, {**body, "source": "computed"})
    return body


def _build(symbol: str, client, cache) -> dict:
    started_at = date.today()
    market = market_symbol(symbol)
    rows = client.get_financial_results(market, started_at - timedelta(days=800), started_at)
    ordered = []
    for row in rows:
        period = parse_period_end(row.get("period_end") or "")
        if period is not None and row.get("xbrl_url"):
            ordered.append((period, row))
    ordered.sort(key=lambda item: item[0], reverse=True)
    chosen = None
    compared = None
    for period, row in ordered[:8]:
        parsed = _parse(_load_xbrl(client, cache, market, row))
        if _has_position(parsed):
            chosen = (period, row, parsed)
            break
    if chosen is None:
        return {
            "symbol": symbol,
            "status": "not_found",
            "message": "No half-year or annual filing with a balance sheet was found.",
            "usage": {"total_tokens": 0},
        }
    period, row, parsed = chosen
    prior_face = {}
    prior_on = (parsed["contexts"].get("PY_I") or {}).get("instant")
    for other_period, other in ordered:
        if prior_on is not None and other_period == prior_on:
            prior_face = _parse(_load_xbrl(client, cache, market, other))["crore"].get("OneI") or {}
        if other_period == _year_ago(period):
            compared = _parse(_load_xbrl(client, cache, market, other))
    statement = _statement(parsed, compared, prior_face)
    statement.update(
        {
            "symbol": symbol,
            "status": "ready",
            "scope": parsed["nature"] or row.get("scope") or "Unknown",
            "source_url": row.get("xbrl_url") or "",
            "usage": {"total_tokens": 0},
            "source": "computed",
        }
    )
    return statement


def _parse(payload: bytes | str) -> dict:
    from xml.etree import ElementTree as ET

    root = ET.fromstring(payload)
    contexts = {}
    for context in list(root.findall(f".//{{{XBRLI}}}context")) + list(root.findall(".//context")):
        context_id = context.get("id") or ""
        if context_id not in {"OneI", "PY_I", "FourD", "OneD"}:
            continue
        period = context.find(f"{{{XBRLI}}}period")
        if period is None:
            period = context.find("period")
        if period is None:
            continue
        contexts[context_id] = {
            "start": _date(period.findtext(f"{{{XBRLI}}}startDate") or period.findtext("startDate")),
            "end": _date(period.findtext(f"{{{XBRLI}}}endDate") or period.findtext("endDate")),
            "instant": _date(period.findtext(f"{{{XBRLI}}}instant") or period.findtext("instant")),
        }
    raw: dict[str, dict[str, float]] = {}
    nature = ""
    anchor = None
    for element in root.iter():
        name = _local(element.tag)
        if name == "NatureOfReportStandaloneConsolidated" and (element.text or "").strip():
            nature = element.text.strip()
        context_id = element.get("contextRef")
        if name not in FACE or context_id not in contexts or element.get("unitRef") != "INR":
            continue
        value = _number(element.text)
        if value is None:
            continue
        raw.setdefault(context_id, {})[name] = value
        if anchor is None or abs(value) > anchor:
            anchor = abs(value)
    scale = _scale("", anchor)
    divisor = _divisor(scale)
    crore = {
        context_id: {name: round(value / divisor, 2) for name, value in facts.items()}
        for context_id, facts in raw.items()
    }
    return {"contexts": contexts, "crore": crore, "nature": nature, "kind": _kind(crore)}


def _kind(crore: dict) -> str:
    names = {name for facts in crore.values() for name in facts}
    if names & {"GrossPremiumWritten", "PremiumEarned", "NetPremiumIncome"}:
        return "insurer"
    if "Deposits" in names or ("InterestEarned" in names and "RevenueFromOperations" not in names):
        return "bank" if "Deposits" in names else "nbfc"
    return "company"


def _has_position(parsed: dict) -> bool:
    face = parsed["crore"].get("OneI") or {}
    flow = parsed["contexts"].get(FLOW) or {}
    start, end = flow.get("start"), flow.get("end")
    if _span(start, end) not in {"Half-year", "Full-year"}:
        return False
    return any(name in face for name in ("Equity", "Borrowings", "BorrowingsCurrent", "BorrowingsNoncurrent"))


def _year_ago(period: date) -> date:
    try:
        return period.replace(year=period.year - 1)
    except ValueError:
        return date(period.year - 1, period.month, 28)


def _statement(parsed: dict, compared: dict | None, prior_face: dict | None = None) -> dict:
    now = parsed["crore"].get("OneI") or {}
    prior = prior_face or {}
    flow = parsed["crore"].get(FLOW) or {}
    context = parsed["contexts"].get(FLOW) or {}
    instant = parsed["contexts"].get("OneI") or {}
    previous = parsed["contexts"].get("PY_I") or {}
    span = _span(context.get("start"), context.get("end"))
    financial = parsed["kind"] != "company"
    lines, missing = _position_lines(now, prior)
    debt, debt_missing = _sum_present(now, ("BorrowingsCurrent", "BorrowingsNoncurrent"), "Borrowings")
    debt_prior, _prior_gap = _sum_present(prior, ("BorrowingsCurrent", "BorrowingsNoncurrent"), "Borrowings")
    equity = now.get("Equity")
    equity_prior = prior.get("Equity")
    cash = now.get("CashAndCashEquivalents")
    cash_prior = prior.get("CashAndCashEquivalents")
    if "Equity" not in now:
        missing.append("Equity")
    if "CashAndCashEquivalents" not in now:
        missing.append("CashAndCashEquivalents")
    working, working_missing = _working_capital(now)
    working_prior, _prior_working_gap = _working_capital(prior)
    missing.extend(working_missing)
    ratios = {
        "debt_to_equity": _ratio(debt, equity, debt_prior, equity_prior, financial, "Total borrowings divided by total equity."),
        "net_debt": _net_debt(debt, cash, debt_prior, cash_prior, financial),
        "working_capital": _working_ratio(working, working_prior, financial),
    }
    flags = []
    if ratios["debt_to_equity"].get("value") is not None and ratios["debt_to_equity"].get("prior") is not None:
        if ratios["debt_to_equity"]["value"] - ratios["debt_to_equity"]["prior"] >= 0.5:
            flags.append(
                f"Debt-to-equity rose from {ratios['debt_to_equity']['prior']:.2f} at { _show(previous.get('instant')) } to {ratios['debt_to_equity']['value']:.2f}."
            )
    receivable_note, receivable_flag = _receivables_against_revenue(parsed, compared)
    if receivable_flag:
        flags.append(receivable_flag)
    balance = {
        "as_of": _show(instant.get("instant")),
        "compared_with": _show(previous.get("instant")) if prior else "",
        "lines": lines,
        "ratios": ratios,
        "missing": _unique(missing + debt_missing),
        "flags": flags,
        "takeaway": _balance_line(parsed["kind"], ratios, instant.get("instant"), previous.get("instant")),
    }
    cash_lines, cash_missing, cash_flags, cash_ratios = _cash(flow, span)
    return {
        "kind": parsed["kind"],
        "balance_sheet": balance,
        "cash": {
            "label": span,
            "start": _show(context.get("start")),
            "end": _show(context.get("end")),
            "lines": cash_lines,
            "ratios": cash_ratios,
            "missing": cash_missing,
            "flags": cash_flags,
            "receivables": receivable_note,
            "takeaway": _cash_line(span, context.get("end"), cash_ratios, cash_flags),
        },
    }


def _position_lines(now: dict, prior: dict) -> tuple[list[dict], list[str]]:
    spec = (
        ("borrowings_noncurrent", "Borrowings, non-current", "BorrowingsNoncurrent"),
        ("borrowings_current", "Borrowings, current", "BorrowingsCurrent"),
        ("borrowings", "Borrowings", "Borrowings"),
        ("equity", "Total equity", "Equity"),
        ("cash", "Cash and cash equivalents", "CashAndCashEquivalents"),
        ("inventories", "Inventories", "Inventories"),
        ("receivables", "Trade receivables", None),
        ("payables", "Trade payables", None),
    )
    lines = []
    missing = []
    for key, label, tag in spec:
        if key == "receivables":
            value, gap = _sum_present(now, ("TradeReceivablesCurrent", "TradeReceivablesNoncurrent"), "TradeReceivables")
            previous, _gap = _sum_present(prior, ("TradeReceivablesCurrent", "TradeReceivablesNoncurrent"), "TradeReceivables")
            used = "TradeReceivablesCurrent + TradeReceivablesNoncurrent"
        elif key == "payables":
            value, gap = _sum_present(now, ("TradePayablesCurrent", "TradePayablesNoncurrent"), "TradePayables")
            previous, _gap = _sum_present(prior, ("TradePayablesCurrent", "TradePayablesNoncurrent"), "TradePayables")
            used = "TradePayablesCurrent + TradePayablesNoncurrent"
        else:
            value = now.get(tag) if tag in now else None
            previous = prior.get(tag) if tag in prior else None
            gap = [tag] if tag not in now else []
            used = tag
        if tag == "Borrowings" and ("BorrowingsCurrent" in now or "BorrowingsNoncurrent" in now):
            continue
        if gap and key in {"borrowings_noncurrent", "borrowings_current"} and "Borrowings" in now and "BorrowingsCurrent" not in now:
            continue
        missing.extend(gap)
        if value is None and previous is None and gap:
            lines.append({"key": key, "label": label, "tag": used, "value": None, "prior": None})
            continue
        if value is None and not gap and key not in {"receivables", "payables"}:
            continue
        lines.append({"key": key, "label": label, "tag": used, "value": value, "prior": previous})
    return lines, missing


def _cash(flow: dict, span: str) -> tuple[list[dict], list[str], list[str], dict]:
    ocf = flow.get("CashFlowsFromUsedInOperatingActivities")
    ppe = flow.get("PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities")
    intangible = flow.get("PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities")
    pat, pat_tag = _pat(flow)
    missing = []
    if ocf is None:
        missing.append("CashFlowsFromUsedInOperatingActivities")
    if ppe is None:
        missing.append("PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities")
    if intangible is None:
        missing.append("PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities")
    if pat is None:
        missing.append("ProfitLossForPeriod")
    capex = None if ppe is None or intangible is None else round(ppe + intangible, 2)
    free = None if ocf is None or capex is None else round(ocf - capex, 2)
    conversion = None if ocf is None or pat in (None, 0) else round(ocf / pat, 2)
    lines = [
        {"key": "operating_cash_flow", "label": "Net cash from operating activities", "tag": "CashFlowsFromUsedInOperatingActivities", "value": ocf},
        {"key": "capex_ppe", "label": "Purchase of property, plant and equipment", "tag": "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities", "value": ppe},
        {"key": "capex_intangible", "label": "Purchase of intangible assets", "tag": "PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities", "value": intangible},
        {"key": "pat", "label": "Profit for the same period", "tag": pat_tag, "value": pat},
    ]
    ratios = {
        "free_cash_flow": {"value": free, "definition": "Operating cash flow minus the two purchase lines above. A missing purchase line is not treated as zero."},
        "cash_conversion": {"value": conversion, "definition": "Operating cash flow divided by profit for this same period."},
    }
    flags = []
    if pat is not None and pat > 0 and ocf is not None and ocf < 0:
        flags.append(f"Profit for this {span.lower()} is positive and operating cash flow is negative.")
    return lines, missing, flags, ratios


def _pat(flow: dict) -> tuple[float | None, str]:
    owners = flow.get("ProfitOrLossAttributableToOwnersOfParent")
    total = flow.get("ProfitLossForPeriod")
    bank = flow.get("ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates")
    if owners not in (None, 0):
        return owners, "ProfitOrLossAttributableToOwnersOfParent"
    if total is not None:
        return total, "ProfitLossForPeriod"
    if bank is not None:
        return bank, "ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates"
    return None, ""


def _receivables_against_revenue(parsed: dict, compared: dict | None) -> tuple[dict, str]:
    """Same span only: this FourD against the year-ago filing's FourD, and the two balance-sheet dates."""
    if compared is None:
        return {"status": "not_available", "reason": "No filing for the previous comparable period was found."}, ""
    now_flow = (parsed["contexts"].get(FLOW) or {})
    then_flow = (compared["contexts"].get(FLOW) or {})
    if _span(now_flow.get("start"), now_flow.get("end")) != _span(then_flow.get("start"), then_flow.get("end")):
        return {"status": "not_available", "reason": "The previous filing does not cover the same length of period."}, ""
    revenue_now = (parsed["crore"].get(FLOW) or {}).get("RevenueFromOperations")
    revenue_then = (compared["crore"].get(FLOW) or {}).get("RevenueFromOperations")
    receivables_now, _gap = _sum_present(parsed["crore"].get("OneI") or {}, ("TradeReceivablesCurrent", "TradeReceivablesNoncurrent"), "TradeReceivables")
    receivables_then, _then_gap = _sum_present(compared["crore"].get("OneI") or {}, ("TradeReceivablesCurrent", "TradeReceivablesNoncurrent"), "TradeReceivables")
    if None in (revenue_now, revenue_then, receivables_now, receivables_then) or revenue_then == 0 or receivables_then == 0:
        return {"status": "not_available", "reason": "Revenue or trade receivables is missing in one of the two periods."}, ""
    revenue_growth = round((revenue_now / revenue_then - 1) * 100, 1)
    receivables_growth = round((receivables_now / receivables_then - 1) * 100, 1)
    note = {
        "status": "ready",
        "revenue_growth_pct": revenue_growth,
        "receivables_growth_pct": receivables_growth,
        "current_end": _show((parsed["contexts"].get("OneI") or {}).get("instant")),
        "previous_end": _show((compared["contexts"].get("OneI") or {}).get("instant")),
    }
    flag = ""
    if receivables_growth > 0 and receivables_growth - revenue_growth >= 15:
        flag = (
            f"Trade receivables grew {receivables_growth:.0f}% and revenue grew {revenue_growth:.0f}% "
            f"over the same { _span(now_flow.get('start'), now_flow.get('end')).lower() }."
        )
    return note, flag


def _ratio(debt, equity, debt_prior, equity_prior, financial: bool, definition: str) -> dict:
    if financial:
        return {"value": None, "prior": None, "meaningful": False, "definition": definition, "reason": "Not meaningful for a bank, NBFC or insurer."}
    value = None if debt is None or equity in (None, 0) else round(debt / equity, 2)
    prior = None if debt_prior is None or equity_prior in (None, 0) else round(debt_prior / equity_prior, 2)
    return {"value": value, "prior": prior, "meaningful": True, "definition": definition}


def _net_debt(debt, cash, debt_prior, cash_prior, financial: bool) -> dict:
    definition = "Total borrowings minus cash and cash equivalents. Cash is the CashAndCashEquivalents tag only, not other bank balances."
    if financial:
        return {"value": None, "prior": None, "meaningful": False, "definition": definition, "reason": "Not meaningful for a bank, NBFC or insurer."}
    value = None if debt is None or cash is None else round(debt - cash, 2)
    prior = None if debt_prior is None or cash_prior is None else round(debt_prior - cash_prior, 2)
    return {"value": value, "prior": prior, "meaningful": True, "definition": definition}


def _working_ratio(working, prior, financial: bool) -> dict:
    definition = "Inventories plus trade receivables minus trade payables. Current and non-current receivables and payables are both included."
    if financial:
        return {"value": None, "prior": None, "meaningful": False, "definition": definition, "reason": "Not meaningful for a bank, NBFC or insurer."}
    return {"value": working, "prior": prior, "meaningful": True, "definition": definition}


def _working_capital(facts: dict) -> tuple[float | None, list[str]]:
    inventories = facts.get("Inventories")
    receivables, receive_gap = _sum_present(facts, ("TradeReceivablesCurrent", "TradeReceivablesNoncurrent"), "TradeReceivables")
    payables, pay_gap = _sum_present(facts, ("TradePayablesCurrent", "TradePayablesNoncurrent"), "TradePayables")
    missing = (["Inventories"] if "Inventories" not in facts else []) + receive_gap + pay_gap
    if inventories is None or receivables is None or payables is None:
        return None, missing
    return round(inventories + receivables - payables, 2), []


def _sum_present(facts: dict, parts: tuple[str, ...], single: str) -> tuple[float | None, list[str]]:
    if single in facts and not any(part in facts for part in parts):
        return facts[single], []
    if not any(part in facts for part in parts):
        return None, [single if single not in facts else part for part in parts if part not in facts] or [single]
    total = 0.0
    missing = []
    for part in parts:
        if part in facts:
            total += facts[part]
        else:
            missing.append(part)
    if missing:
        return None, missing
    return round(total, 2), []


def _span(start: date | None, end: date | None) -> str:
    if start is None or end is None:
        return ""
    days = (end - start).days
    if 160 <= days <= 200:
        return "Half-year"
    if 330 <= days <= 380:
        return "Full-year"
    return ""


def _balance_line(kind: str, ratios: dict, as_of, compared) -> str:
    if kind != "company":
        label = {"bank": "a bank", "nbfc": "an NBFC", "insurer": "an insurer"}.get(kind, "this company")
        return f"Debt-to-equity and working capital are not meaningful for {label}."
    debt = ratios["debt_to_equity"]
    net = ratios["net_debt"]
    if debt.get("value") is None:
        return f"Debt-to-equity is not available at {_show(as_of)}."
    text = f"Debt-to-equity is {debt['value']:.2f}"
    if debt.get("prior") is not None:
        text += f", against {debt['prior']:.2f} at {_show(compared)}"
    if net.get("value") is not None:
        text += f". Net debt is {_crore(net['value'])}"
    return text + "."


def _cash_line(span: str, end, ratios: dict, flags: list[str]) -> str:
    conversion = (ratios.get("cash_conversion") or {}).get("value")
    free = (ratios.get("free_cash_flow") or {}).get("value")
    if conversion is None and free is None:
        return f"{span or 'This period'} cash flow is not available."
    parts = [f"{span} to {_show(end)}."]
    if conversion is not None:
        parts.append(f"Operating cash flow is {conversion:.0%} of profit.")
    if free is not None:
        parts.append(f"Free cash flow is {_crore(free)}.")
    if flags:
        parts.append(flags[0])
    return " ".join(parts)


def _crore(value: float) -> str:
    return f"{value:,.0f} crore" if abs(value) >= 10 else f"{value:,.2f} crore"


def _show(value) -> str:
    if value is None:
        return ""
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _unique(items: list[str]) -> list[str]:
    seen = []
    for item in items:
        if item and item not in seen:
            seen.append(item)
    return seen


