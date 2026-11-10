"""Promise checks and half-year subtraction. No network."""

import unittest
from datetime import date

from finn_core.ledger import compare_target, judge_promise, on_page, select_pages
from finn_core.series import apply_half_year, subtract_quarter


def quarter(period, revenue, ebitda, pat, margin=None):
    return {
        "period": period,
        "revenue": revenue,
        "ebitda": ebitda,
        "ebitda_margin_pct": margin if margin is not None else (None if revenue in (None, 0) or ebitda is None else round(ebitda / revenue * 100, 2)),
        "pbt": None,
        "pat": pat,
        "flags": [],
        "basis": "xbrl" if revenue is not None else "",
    }


class SeriesGapTests(unittest.TestCase):
    def test_half_minus_known_quarter(self):
        derived = subtract_quarter(
            {"revenue": 1000, "ebitda": 200, "pbt": 150, "pat": 110},
            {"revenue": 400, "ebitda": 80, "pbt": 60, "pat": 40},
        )
        self.assertEqual(derived["revenue"], 600)
        self.assertEqual(derived["pat"], 70)
        self.assertEqual(derived["ebitda_margin_pct"], 20.0)

    def test_missing_other_quarter_stays_blank(self):
        quarters = [
            quarter("2026-03-31", None, None, None),
            quarter("2025-12-31", 400, 80, 40),
            quarter("2025-09-30", None, None, None),
        ]
        halves = [
            {"period": "2026-03-31", "start": "2025-10-01", "end": "2026-03-31", "revenue": 1000, "ebitda": 200, "pbt": 150, "pat": 110},
            {"period": "2025-09-30", "start": "2025-04-01", "end": "2025-09-30", "revenue": 900, "ebitda": 180, "pbt": 140, "pat": 100},
        ]
        apply_half_year(quarters, halves)
        self.assertEqual(quarters[0]["revenue"], 600)
        self.assertEqual(quarters[0]["basis"], "derived")
        self.assertIsNone(quarters[2]["revenue"])
        self.assertIn("2025-06-30 is missing", quarters[2]["flags"][0])

    def test_half_year_date_that_matches_the_year_to_date_change_is_the_quarter(self):
        quarters = [
            quarter("2026-03-31", None, None, None),
            quarter("2025-12-31", 3175.35, 361.75, 284.83),
        ]
        halves = [
            {"period": "2026-03-31", "start": "2025-10-01", "end": "2026-03-31", "revenue": 3441.76, "ebitda": 462.72, "pbt": 490.41, "pat": 365.49},
        ]
        ytds = [
            {"period": "2026-03-31", "revenue": 12417.95},
            {"period": "2025-12-31", "revenue": 8976.19},
        ]
        apply_half_year(quarters, halves, ytds)
        self.assertEqual(quarters[0]["revenue"], 3441.76)
        self.assertIn("year-to-date", quarters[0]["flags"][0])


class PromiseTests(unittest.TestCase):
    def test_quote_must_appear_on_the_page(self):
        page = "We expect revenue growth of 8 to 10 percent in FY26, said the CFO."
        self.assertTrue(on_page("expect revenue growth of 8 to 10 percent in FY26", page))
        self.assertFalse(on_page("expect revenue growth of 20 percent in FY26", page))

    def test_margin_inside_the_range_is_delivered_and_a_future_year_is_pending(self):
        quarters = [
            quarter("2026-09-30", 100, 20, 10),
            quarter("2026-06-30", 100, 20, 10),
            quarter("2026-03-31", 100, 19, 10, 19),
            quarter("2025-12-31", 100, 19, 10, 19),
            quarter("2025-09-30", 100, 18, 10, 18),
            quarter("2025-06-30", 100, 18, 10, 18),
        ]
        delivered = judge_promise(
            {
                "metric_key": "ebitda_margin",
                "target_low": 18,
                "target_high": 20,
                "direction": "",
                "horizon": "fiscal_year",
                "target_period": "FY2026",
                "evidence": "margin",
                "page": 1,
                "source_document": "https://example/t.pdf",
                "speaker": "",
            },
            quarters,
        )
        self.assertEqual(delivered["status"], "delivered")
        self.assertEqual(delivered["actual"], "18.5%")
        pending = judge_promise(
            {
                "metric_key": "revenue_growth",
                "target_low": 10,
                "target_high": None,
                "direction": "",
                "horizon": "fiscal_year",
                "target_period": "FY2027",
                "evidence": "growth",
                "page": 1,
                "source_document": "https://example/t.pdf",
                "speaker": "",
            },
            quarters,
        )
        self.assertEqual(pending["status"], "pending")
        self.assertIsNone(pending["actual"])

    def test_volume_is_not_checkable_and_a_miss_is_outside_the_band(self):
        self.assertEqual(compare_target(8, 16, 18, ""), "missed")
        self.assertEqual(compare_target(14.5, 16, 18, ""), "partly")
        quarters = [quarter("2026-09-30", 100, 20, 10)]
        volume = judge_promise(
            {
                "metric_key": "volume_growth",
                "target_low": 5,
                "target_high": 7,
                "direction": "",
                "horizon": "quarter",
                "target_period": "2026-09-30",
                "evidence": "volume",
                "page": 2,
                "source_document": "u",
                "speaker": "",
            },
            quarters,
        )
        self.assertEqual(volume["status"], "not_checkable")
        crore = judge_promise(
            {
                "metric_key": "revenue_growth",
                "target_low": 15000,
                "target_high": None,
                "direction": "up",
                "horizon": "fiscal_year",
                "target_period": "FY2027",
                "evidence": "delivering double-digit revenue growth to cross INR15,000 crores",
                "page": 6,
                "source_document": "u",
                "speaker": "",
            },
            quarters,
        )
        self.assertIn("at least 10%", crore["promise"])
        self.assertNotIn("15000", crore["promise"])

    def test_forward_pages_are_kept(self):
        pages = [
            {"page": 1, "text": "Revenue for the quarter was higher."},
            {"page": 2, "text": "We expect EBITDA margin of 19 percent next year."},
        ]
        chosen = select_pages(pages)
        self.assertEqual([page["page"] for page in chosen], [2])


if __name__ == "__main__":
    unittest.main()
