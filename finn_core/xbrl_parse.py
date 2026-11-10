"""Parse an NSE integrated-filing XBRL into quarterly P&L lines, in INR crore.

One filing publishes the current quarter as context OneD and the year-to-date
as FourD. The previous quarter and the year-ago quarter are not contexts in
that file; the caller reads them from those quarters' own filings.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from xml.etree import ElementTree as ET

XBRLI = "http://www.xbrl.org/2003/instance"
CRORE = 10_000_000

# First tag present wins. Income is total income, so it is only the revenue
# line when the statement has no RevenueFromOperations (banks).
REVENUE_TAGS = ("RevenueFromOperations",)
INCOME_TAGS = ("Income",)
OTHER_INCOME_TAGS = ("OtherIncome",)
FINANCE_TAGS = ("FinanceCosts",)
DEPRECIATION_TAGS = ("DepreciationDepletionAndAmortisationExpense",)
PBT_TAGS = ("ProfitBeforeTax", "ProfitLossFromOrdinaryActivitiesBeforeTax")
PAT_TAGS = ("ProfitLossForPeriod", "ProfitLossForThePeriod")
OWNERS_TAGS = ("ProfitOrLossAttributableToOwnersOfParent",)
NCI_TAGS = ("ProfitOrLossAttributableToNonControllingInterests",)
TAX_TAGS = ("TaxExpense",)
SHARE_TAGS = (
    "ShareOfProfitLossOfAssociatesAndJointVenturesAccountedForUsingEquityMethod",
    "ShareOfProfitLossOfAssociates",
)
INTEREST_EARNED_TAGS = ("InterestEarned",)
PRODUCT_SALES_TAGS = ("RevenueFromSaleOfProduct",)

MONEY_TAGS = (
    REVENUE_TAGS
    + INCOME_TAGS
    + OTHER_INCOME_TAGS
    + FINANCE_TAGS
    + DEPRECIATION_TAGS
    + PBT_TAGS
    + PAT_TAGS
    + OWNERS_TAGS
    + NCI_TAGS
    + TAX_TAGS
    + SHARE_TAGS
    + INTEREST_EARNED_TAGS
    + PRODUCT_SALES_TAGS
)


@dataclass
class PeriodFacts:
    context_id: str
    start: date | None
    end: date | None
    raw: dict[str, float] = field(default_factory=dict)
    crore: dict[str, float] = field(default_factory=dict)


@dataclass
class XbrlStatement:
    rounding: str
    scale: str
    periods: list[PeriodFacts]
    current: PeriodFacts | None
    year_to_date: PeriodFacts | None
    previous_in_file: PeriodFacts | None
    year_ago_in_file: PeriodFacts | None
    missing: list[str]
    missing_reason: str


def parse_xbrl(payload: bytes | str) -> XbrlStatement:
    root = ET.fromstring(payload)
    contexts = _contexts(root)
    rounding = _text(root, "LevelOfRounding")
    raw: dict[str, dict[str, float]] = {}
    for element in root.iter():
        name = _local(element.tag)
        context_id = element.get("contextRef")
        if name not in MONEY_TAGS or not context_id or element.get("unitRef") != "INR":
            continue
        value = _number(element.text)
        if value is None or context_id not in contexts:
            continue
        raw.setdefault(context_id, {}).setdefault(name, value)

    anchor = _anchor(raw.get("OneD", {}))
    scale = _scale(rounding, anchor)
    periods = []
    for context_id, (start, end) in contexts.items():
        facts = raw.get(context_id) or {}
        if not facts:
            continue
        periods.append(
            PeriodFacts(
                context_id=context_id,
                start=start,
                end=end,
                raw=facts,
                crore={name: round(value / _divisor(scale), 2) for name, value in facts.items()},
            )
        )
    by_id = {period.context_id: period for period in periods}
    current = by_id.get("OneD")
    year_to_date = by_id.get("FourD")
    if current is not None and not _is_quarter(current.start, current.end):
        current = None
    previous_in_file, year_ago_in_file = _comparison_in_file(periods, current)
    missing = []
    if current is None:
        missing.append("current_quarter")
    if previous_in_file is None:
        missing.append("previous_quarter")
    if year_ago_in_file is None:
        missing.append("year_ago_quarter")
    reason = ""
    if "previous_quarter" in missing or "year_ago_quarter" in missing:
        reason = (
            "This XBRL has the current quarter as OneD and the year-to-date as FourD. "
            "The previous quarter and the year-ago quarter are not separate contexts in the same file."
        )
    return XbrlStatement(
        rounding=rounding,
        scale=scale,
        periods=periods,
        current=current,
        year_to_date=year_to_date,
        previous_in_file=previous_in_file,
        year_ago_in_file=year_ago_in_file,
        missing=missing,
        missing_reason=reason,
    )


def metrics_from(period: PeriodFacts | None) -> dict[str, float | None]:
    """Headline lines in crore. PAT prefers profit attributable to owners."""
    if period is None:
        return {key: None for key in ("revenue", "other_income", "finance_costs", "depreciation", "pbt", "pat", "tax", "pat_total", "nci", "share", "interest_earned", "product_sales", "revenue_basis")}
    crore = period.crore
    revenue = _first(crore, REVENUE_TAGS)
    basis = "revenue_from_operations"
    if revenue is None:
        revenue = _first(crore, INCOME_TAGS)
        basis = "total_income"
    owners = _first(crore, OWNERS_TAGS)
    total = _first(crore, PAT_TAGS)
    return {
        "revenue": revenue,
        "revenue_basis": basis if revenue is not None else "",
        "other_income": _first(crore, OTHER_INCOME_TAGS),
        "finance_costs": _first(crore, FINANCE_TAGS),
        "depreciation": _first(crore, DEPRECIATION_TAGS),
        "pbt": _first(crore, PBT_TAGS),
        "pat": owners if owners is not None else total,
        "pat_total": total,
        "tax": _first(crore, TAX_TAGS),
        "nci": _first(crore, NCI_TAGS),
        "share": _first(crore, SHARE_TAGS),
        "interest_earned": _first(crore, INTEREST_EARNED_TAGS),
        "product_sales": _first(crore, PRODUCT_SALES_TAGS),
    }


def ebitda(metrics: dict[str, float | None]) -> float | None:
    """PBT + finance costs + depreciation - other income. Missing addends are zero."""
    if metrics.get("pbt") is None:
        return None
    return round(
        metrics["pbt"]
        + (metrics.get("finance_costs") or 0.0)
        + (metrics.get("depreciation") or 0.0)
        - (metrics.get("other_income") or 0.0),
        2,
    )


def ebitda_block_reason(symbol: str, xbrl_url: str, metrics: dict) -> str:
    """Empty string when EBITDA is a meaningful line."""
    folded = symbol.upper()
    url = (xbrl_url or "").upper()
    if folded == "HDFCBANK" or "BANKING" in url:
        return "EBITDA is not meaningful for a bank: interest expense is the cost of funds."
    if folded == "BAJFINANCE" or "NBFC" in url:
        return "EBITDA is not meaningful for an NBFC: finance cost is the cost of funds."
    interest = metrics.get("interest_earned") or 0.0
    sales = metrics.get("product_sales")
    revenue = metrics.get("revenue") or 0.0
    finance = metrics.get("finance_costs") or 0.0
    if interest > 0 and sales == 0 and revenue > 0 and finance > 0.25 * revenue:
        return "EBITDA is not meaningful: interest earned is the revenue and finance cost is the cost of funds."
    if metrics.get("pbt") is None:
        return "PBT is missing, so EBITDA is not computed."
    if metrics.get("finance_costs") is None and metrics.get("depreciation") is None:
        return "Finance costs and depreciation are not in the filing, so EBITDA is not computed."
    return ""


def change_pct(current: float | None, base: float | None) -> float | None:
    if current is None or base in (None, 0):
        return None
    return round((current / base - 1.0) * 100.0, 2)


def previous_quarter_end(day: date) -> date:
    month = day.month - 3
    year = day.year
    if month <= 0:
        month += 12
        year -= 1
    return _month_end(year, month)


def year_ago_end(day: date) -> date:
    try:
        return day.replace(year=day.year - 1)
    except ValueError:
        return date(day.year - 1, day.month, 28)


def parse_period_end(value: str) -> date | None:
    text = str(value or "").strip()
    parts = text.split("-")
    if len(parts) >= 3 and parts[1].isalpha():
        parts[1] = parts[1].title()
        text = "-".join(parts[:3])
    for fmt in ("%d-%b-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _contexts(root: ET.Element) -> dict[str, tuple[date | None, date | None]]:
    found = {}
    contexts = list(root.findall(f".//{{{XBRLI}}}context")) + list(root.findall(".//context"))
    for context in contexts:
        context_id = context.get("id") or ""
        if "Reportable" in context_id or "Expenses" in context_id or context_id.startswith("D_"):
            continue
        period = context.find(f"{{{XBRLI}}}period")
        if period is None:
            period = context.find("period")
        if period is None:
            continue
        start = _date(period.findtext(f"{{{XBRLI}}}startDate") or period.findtext("startDate"))
        end = _date(period.findtext(f"{{{XBRLI}}}endDate") or period.findtext("endDate"))
        if start is None or end is None:
            continue
        found[context_id] = (start, end)
    return found


def _comparison_in_file(periods: list[PeriodFacts], current: PeriodFacts | None) -> tuple[PeriodFacts | None, PeriodFacts | None]:
    if current is None or current.end is None:
        return None, None
    previous_end = previous_quarter_end(current.end)
    ago_end = year_ago_end(current.end)
    previous = None
    year_ago = None
    for period in periods:
        if period.context_id in ("OneD", "FourD") or not _is_quarter(period.start, period.end):
            continue
        if period.end == previous_end:
            previous = period
        elif period.end == ago_end:
            year_ago = period
    return previous, year_ago


def _anchor(raw: dict[str, float]) -> float | None:
    values = [abs(raw[name]) for name in ("RevenueFromOperations", "Income", "ProfitBeforeTax", "ProfitLossForPeriod") if name in raw]
    return max(values) if values else None


def _scale(rounding: str, anchor: float | None) -> str:
    """How the fact numbers are stored. Large anchors are absolute rupees."""
    if anchor is not None and abs(anchor) >= 1e8:
        return "rupee"
    label = rounding.lower()
    if "lakh" in label:
        return "lakh"
    if "million" in label:
        return "million"
    if "crore" in label:
        return "crore"
    if anchor is not None and abs(anchor) >= 1e7:
        return "rupee"
    return "crore"


def _divisor(scale: str) -> float:
    return {"rupee": CRORE, "lakh": 100.0, "million": 10.0, "crore": 1.0}[scale]


def _first(crore: dict[str, float], tags: tuple[str, ...]) -> float | None:
    for tag in tags:
        if tag in crore:
            return crore[tag]
    return None


def _is_quarter(start: date | None, end: date | None) -> bool:
    if start is None or end is None:
        return False
    days = (end - start).days
    return 80 <= days <= 100


def _month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def _date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _number(value: str | None) -> float | None:
    if value is None:
        return None
    text = value.strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _text(root: ET.Element, name: str) -> str:
    for element in root.iter():
        if _local(element.tag) == name and (element.text or "").strip():
            return element.text.strip()
    return ""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
