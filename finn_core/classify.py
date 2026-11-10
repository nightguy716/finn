"""Keyword classification of NSE announcement subjects.

AGENTS.md names results and management changes as the enriched push cards and
says every other type gets a priority, not a full card. It does not list 16
names. These 16 are the digest taxonomy: the six material types called out for
the data layer, plus the other NSE subjects that actually show up.
"""

from dataclasses import dataclass
import re

LOW_CONFIDENCE = 0.6

CATEGORIES = (
    "results",
    "concall",
    "m_and_a",
    "fund_raise",
    "management_change",
    "litigation",
    "credit_rating",
    "dividend",
    "buyback",
    "order_contract",
    "board_meeting",
    "shareholder_meeting",
    "insider",
    "esop",
    "shareholding",
    "routine",
)

PRIORITY = {
    "results": 95,
    "m_and_a": 90,
    "fund_raise": 86,
    "management_change": 82,
    "litigation": 78,
    "credit_rating": 74,
    "concall": 70,
    "dividend": 66,
    "buyback": 66,
    "order_contract": 62,
    "board_meeting": 44,
    "shareholder_meeting": 40,
    "insider": 34,
    "esop": 28,
    "shareholding": 22,
    "routine": 8,
    "needs_llm": 16,
}

# First match wins. Specific subjects come before generic ones.
RULES: tuple[tuple[str, float, tuple[str, ...]], ...] = (
    ("results", 0.95, (r"financial results", r"unaudited", r"audited financial", r"quarterly results")),
    ("concall", 0.93, (r"con\.?\s*call", r"earnings call", r"\btranscript\b", r"analysts?/institutional investor meet", r"investor meet", r"conference call")),
    ("credit_rating", 0.95, (r"credit rating",)),
    ("m_and_a", 0.94, (r"\bacquisition\b", r"\bmerger\b", r"amalgamation", r"demerger", r"slump sale", r"scheme of arrangement", r"joint venture")),
    ("fund_raise", 0.93, (r"raising of funds", r"fund raising", r"preferential", r"\bqip\b", r"qualified institutional", r"rights issue", r"\bncds?\b", r"non-convertible debenture", r"private placement")),
    ("management_change", 0.90, (r"\bappointment\b", r"\bresignation\b", r"\bretirement\b", r"\bcessation\b", r"change in directorate", r"change in management", r"\bkmp\b")),
    ("litigation", 0.90, (r"orders passed", r"action\(s\) taken", r"\blitigation\b", r"\bpenalty\b", r"show[- ]cause", r"\bnclt\b", r"high court")),
    ("order_contract", 0.90, (r"bagging/receiving of orders", r"awarding of order", r"receipt of order", r"award of order")),
    ("buyback", 0.95, (r"buy\s?-?back", r"buyback")),
    ("dividend", 0.95, (r"\bdividend\b",)),
    ("shareholder_meeting", 0.92, (r"shareholders meeting", r"\bagm\b", r"\begm\b", r"postal ballot")),
    ("board_meeting", 0.88, (r"board meeting",)),
    ("insider", 0.90, (r"insider trading", r"\bsast\b", r"reg\.?\s*7\(2\)")),
    ("esop", 0.95, (r"\besop\b", r"\besos\b", r"\besps\b", r"employee stock")),
    ("shareholding", 0.92, (r"shareholding pattern",)),
    ("routine", 0.90, (r"newspaper", r"loss of share", r"duplicate share", r"trading window", r"book closure", r"record date")),
    ("routine", 0.40, (r"general updates?", r"\bupdates?\b", r"\bintimation\b")),
)


@dataclass(frozen=True)
class Classification:
    category: str
    confidence: float
    priority: int
    hint: str = ""


def classify(subject: str, text: str = "") -> Classification:
    allotment = _allotment(subject or "", text or "")
    if allotment is not None:
        return allotment
    hit = _match(subject or "")
    if hit is None and text:
        hit = _match(text[:600])
        if hit is not None:
            hit = Classification(hit.category, min(hit.confidence, 0.55), hit.priority, hit.hint)
    if hit is None:
        return Classification("needs_llm", 0.15, PRIORITY["needs_llm"])
    if hit.confidence < LOW_CONFIDENCE:
        return Classification("needs_llm", hit.confidence, PRIORITY["needs_llm"], hint=hit.category)
    return hit


def _allotment(subject: str, text: str) -> Classification | None:
    if not re.search(r"allotment of securities", subject, re.I):
        return None
    if re.search(r"\besop\b|\besos\b|\besps\b|employee stock", f"{subject}\n{text[:400]}", re.I):
        return Classification("esop", 0.9, PRIORITY["esop"])
    return Classification("fund_raise", 0.88, PRIORITY["fund_raise"])


def _match(blob: str) -> Classification | None:
    haystack = blob.lower()
    if not haystack.strip():
        return None
    for category, confidence, patterns in RULES:
        if any(re.search(pattern, haystack) for pattern in patterns):
            return Classification(category, confidence, PRIORITY[category])
    return None
