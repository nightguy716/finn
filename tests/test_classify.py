"""Keyword checks against announcement subjects from the 7-day digest."""

import unittest

from finn_core.classify import PRIORITY, classify

MATERIAL = [
    ("Acquisition", "m_and_a", 90),
    ("Change in Management", "management_change", 82),
    ("Retirement", "management_change", 82),
    ("Action(s) taken or orders passed", "litigation", 78),
    ("Credit Rating", "credit_rating", 74),
    ("Analysts/Institutional Investor Meet/Con. Call Updates", "concall", 70),
    ("Bagging/Receiving of orders/contracts", "order_contract", 62),
    ("Outcome of Board Meeting", "board_meeting", 44),
    ("Shareholders meeting", "shareholder_meeting", 40),
    ("ESOP/ESOS/ESPS", "esop", 28),
    ("Copy of Newspaper Publication", "routine", 8),
]

VAGUE = [
    "Updates",
    "General Updates",
    "News Verification",
    "Change in Auditors",
    "Investor Presentation",
    "Monitoring Agency Report",
    "Committee Meeting Updates",
]

DIXON_ALLOTMENT = (
    "Dixon Technologies (India) Limited has informed the Exchange regarding "
    "allotment of 37750 securities pursuant to ESOP/ESPS at its meeting held on November 05, 2026"
)


class ClassifyTests(unittest.TestCase):
    def test_subjects_from_the_digest(self):
        for subject, category, priority in MATERIAL:
            got = classify(subject)
            self.assertEqual(got.category, category, subject)
            self.assertEqual(got.priority, priority, subject)
            self.assertGreaterEqual(got.confidence, 0.6, subject)

    def test_allotment_uses_attachment_text(self):
        self.assertEqual(classify("Allotment of Securities").category, "fund_raise")
        self.assertEqual(classify("Allotment of Securities", DIXON_ALLOTMENT).category, "esop")

    def test_vague_subjects_need_llm(self):
        for subject in VAGUE:
            got = classify(subject)
            self.assertEqual(got.category, "needs_llm", subject)
            self.assertLess(got.confidence, 0.6, subject)

    def test_acquisition_outranks_newspaper(self):
        self.assertGreater(PRIORITY["results"], PRIORITY["routine"])
        self.assertGreater(
            classify("Acquisition").priority,
            classify("Copy of Newspaper Publication").priority,
        )


if __name__ == "__main__":
    unittest.main()
