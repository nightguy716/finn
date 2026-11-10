"""Event clustering. No network."""

import unittest
from datetime import datetime

from finn_core.classify import Classification
from finn_core.events import cluster


def filing(symbol, subject, when, category, priority, text=""):
    return {
        "symbol": symbol,
        "subject": subject,
        "text": text,
        "pdf_url": f"https://example/{symbol}/{subject}.pdf",
        "timestamp": when.strftime("%d-%b-%Y %H:%M:%S"),
        "when": when,
        "label": Classification(category, 0.9, priority),
    }


class ClusterTests(unittest.TestCase):
    def test_results_pack_is_one_event_and_acquisitions_merge(self):
        day = datetime(2026, 11, 5, 16, 50, 49)
        later = datetime(2026, 11, 5, 19, 11, 12)
        presentation = datetime(2026, 11, 5, 17, 16, 16)
        retirement = datetime(2026, 11, 5, 18, 51, 55)
        auditors = datetime(2026, 11, 5, 18, 36, 30)
        buy_one = datetime(2026, 11, 6, 17, 16, 32)
        buy_two = datetime(2026, 11, 6, 17, 20, 51)
        items = [
            filing("TITAN", "Outcome of Board Meeting", day, "results", 95),
            filing("TITAN", "Financial Results Consolidated", later, "results", 95),
            filing("TITAN", "Investor Presentation", presentation, "concall", 48),
            filing("TITAN", "Retirement", retirement, "management_change", 82),
            filing("TITAN", "Change in Auditors", auditors, "management_change", 42),
            filing("MARICO", "Acquisition", buy_one, "m_and_a", 90),
            filing("MARICO", "Acquisition", buy_two, "m_and_a", 90),
        ]
        events = cluster(items)
        results = [event for event in events if event["symbol"] == "TITAN" and event["category"] == "results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(len(results[0]["filings"]), 3)
        subjects = {item["subject"] for item in results[0]["filings"]}
        self.assertIn("Investor Presentation", subjects)
        management = [event for event in events if event["symbol"] == "TITAN" and event["category"] == "management_change"]
        self.assertEqual(len(management), 2)
        deals = [event for event in events if event["symbol"] == "MARICO"]
        self.assertEqual(len(deals), 1)
        self.assertEqual(len(deals[0]["filings"]), 2)
        self.assertEqual(deals[0]["category"], "m_and_a")


if __name__ == "__main__":
    unittest.main()
