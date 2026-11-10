"""Keyword checks against announcement subjects from the 7-day digest."""

import unittest

from finn_core.classify import PRIORITY, classify

MATERIAL = [
    ("Acquisition", "m_and_a", 90),
    ("Change in Management", "management_change", 82),
    ("Retirement", "management_change", 82),
    ("Action(s) taken or orders passed", "litigation", 78),
    ("Credit Rating", "credit_rating", 74),
    ("Bagging/Receiving of orders/contracts", "order_contract", 62),
    ("Outcome of Board Meeting", "board_meeting", 44),
    ("Shareholders meeting", "shareholder_meeting", 40),
    ("ESOP/ESOS/ESPS", "esop", 28),
    ("Copy of Newspaper Publication", "routine", 8),
]

ROUTINE_SUBJECTS = [
    "Updates",
    "General Updates",
    "News Verification",
    "Monitoring Agency Report",
    "Committee Meeting Updates",
]

TITAN_RESULTS = (
    "Titan Company Limited has submitted to the Exchange, "
    "the financial results for the period ended September 30, 2026."
)
TRANSCRIPT = (
    "Pursuant to Regulation 30, copy of transcript of the earnings conference call held on November 2, 2026."
)
SCHEDULE = "This is to inform you that the Company will hold an investor/analyst conference call on Monday."

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

    def test_concall_notice_is_low_and_transcript_is_medium(self):
        notice = classify("Analysts/Institutional Investor Meet/Con. Call Updates", SCHEDULE)
        self.assertEqual(notice.category, "concall")
        self.assertEqual(notice.priority, 30)
        recorded = classify("Analysts/Institutional Investor Meet/Con. Call Updates", TRANSCRIPT)
        self.assertEqual(recorded.category, "concall")
        self.assertEqual(recorded.priority, 52)

    def test_board_outcome_with_results_text_is_results(self):
        got = classify("Outcome of Board Meeting", TITAN_RESULTS)
        self.assertEqual(got.category, "results")
        self.assertEqual(got.priority, 95)

    def test_presentation_and_auditors(self):
        presentation = classify("Investor Presentation")
        self.assertEqual(presentation.category, "concall")
        self.assertEqual(presentation.priority, 48)
        auditors = classify("Change in Auditors")
        self.assertEqual(auditors.category, "management_change")
        self.assertEqual(auditors.priority, 42)
        self.assertEqual(auditors.hint, "auditor")

    def test_vague_subjects_are_routine(self):
        for subject in ROUTINE_SUBJECTS:
            got = classify(subject)
            self.assertEqual(got.category, "routine", subject)
            self.assertGreaterEqual(got.confidence, 0.6, subject)
            self.assertLess(got.priority, 40, subject)

    def test_vague_subject_follows_the_attachment_text(self):
        got = classify("General Updates", "The company completed the acquisition of the subsidiary.")
        self.assertEqual(got.category, "m_and_a")
        self.assertEqual(got.priority, 90)

    def test_allotment_uses_attachment_text(self):
        self.assertEqual(classify("Allotment of Securities").category, "fund_raise")
        self.assertEqual(classify("Allotment of Securities", DIXON_ALLOTMENT).category, "esop")

    def test_unknown_subject_still_needs_llm(self):
        got = classify("Press Release")
        self.assertEqual(got.category, "needs_llm")
        self.assertLess(got.confidence, 0.6)

    def test_acquisition_outranks_newspaper(self):
        self.assertGreater(PRIORITY["results"], PRIORITY["routine"])
        self.assertGreater(
            classify("Acquisition").priority,
            classify("Copy of Newspaper Publication").priority,
        )


if __name__ == "__main__":
    unittest.main()
