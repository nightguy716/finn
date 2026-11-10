"""Merge duplicate filings into one event. The filings stay attached as sources.

Results filed the same day (the outcome PDF and the integrated XBRL) are one
results event. An investor presentation that day is a source, not a second card.
Two filings with the same subject on the same day, such as Marico's two
acquisition intimations, are one event. A retirement and an auditor change on
the same day stay separate.
"""

import re
from datetime import datetime

SUMMARY_CATEGORIES = ("m_and_a", "fund_raise", "litigation", "credit_rating", "order_contract")


def cluster(items: list[dict]) -> list[dict]:
    used: set[int] = set()
    events: list[dict] = []
    results_groups: dict[tuple[str, object], list[int]] = {}
    for index, item in enumerate(items):
        when = item.get("when")
        if when is None or _category(item) != "results":
            continue
        results_groups.setdefault((item["symbol"], when.date()), []).append(index)
    for (symbol, day), indexes in results_groups.items():
        extra = []
        for index, item in enumerate(items):
            if index in indexes:
                continue
            when = item.get("when")
            if item.get("symbol") != symbol or when is None or when.date() != day:
                continue
            if _results_attachment(item):
                extra.append(index)
        group = [items[index] for index in indexes + extra]
        for index in indexes + extra:
            used.add(index)
        events.append(_event(group, category="results"))

    buckets: dict[tuple, list[int]] = {}
    for index, item in enumerate(items):
        if index in used:
            continue
        when = item.get("when")
        if when is None:
            continue
        key = (item["symbol"], _category(item), _norm(item.get("subject") or ""), when.date())
        buckets.setdefault(key, []).append(index)
    for indexes in buckets.values():
        for index in indexes:
            used.add(index)
        events.append(_event([items[index] for index in indexes]))
    events.sort(key=lambda event: (event["priority"], event["when"]), reverse=True)
    return events


def _event(filings: list[dict], category: str | None = None) -> dict:
    core = filings
    if category == "results":
        core = [item for item in filings if _category(item) == "results"] or filings
    primary = max(core, key=lambda item: item["when"])
    subject = primary.get("subject") or ""
    if category is None:
        category = _category(primary)
    return {
        "id": _event_id(primary["symbol"], category, primary["when"], subject),
        "symbol": primary["symbol"],
        "category": category,
        "priority": max(item["label"].priority for item in filings),
        "when": primary["when"],
        "subject": subject,
        "filings": filings,
    }


def _results_attachment(item: dict) -> bool:
    subject = (item.get("subject") or "").lower()
    if "investor presentation" in subject:
        return True
    text = f"{subject} {item.get('text') or ''}".lower()
    return "newspaper" in subject and "result" in text


def _category(item: dict) -> str:
    return item["label"].category


def _norm(subject: str) -> str:
    return re.sub(r"\s+", " ", subject).strip().lower()


def _event_id(symbol: str, category: str, when: datetime, subject: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", _norm(subject)).strip("-")[:48]
    return f"{symbol.lower()}-{category}-{when.strftime('%Y%m%d%H%M')}-{slug or 'filing'}"
