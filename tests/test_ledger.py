"""Promise checks and half-year subtraction. No network."""

import unittest
from datetime import date

from finn_core.ledger import (
    apply_word_bands,
    assign_scope,
    compare_target,
    compare_tracking,
    judge_promise,
    merge_rows,
    on_page,
    quote_check,
    select_pages,
)
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
                "evidence": "EBITDA margin guidance of 18% to 20%",
                "page": 1,
                "source_document": "https://example/t.pdf",
                "speaker": "",
            },
            quarters,
        )
        self.assertEqual(delivered["status"], "delivered")
        self.assertEqual(delivered["actual"], "18.5%")
        behind = judge_promise(
            {
                "metric_key": "revenue_growth",
                "target_low": 10,
                "target_high": None,
                "direction": "",
                "horizon": "fiscal_year",
                "target_period": "FY2027",
                "evidence": "we expect revenue growth of at least 10 percent this year",
                "page": 1,
                "source_document": "https://example/t.pdf",
                "speaker": "",
                "call_date": "2026-11-06",
                "call_period": "2026-09-30",
            },
            quarters,
            date(2026, 11, 10),
        )
        self.assertEqual(behind["status"], "tracking_behind")
        self.assertEqual(behind["actual"], "0%")
        self.assertIn("H1 FY2027 revenue", behind["actual_detail"])

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
        self.assertEqual(quote_check(crore["source_quote"], 10, None), "ok")
        unnamed = judge_promise(
            {
                "metric_key": "revenue_growth",
                "target_low": 24,
                "target_high": 25,
                "direction": "",
                "horizon": "fiscal_year",
                "target_period": "FY2027",
                "evidence": "we are saying mid-20s about in the range of 24%, 25% on the minimum side",
                "page": 17,
                "source_document": "u",
                "speaker": "",
            },
            quarters,
            date(2026, 11, 10),
        )
        self.assertEqual(unnamed["status"], "low_confidence")
        self.assertEqual(compare_tracking(12, 10, None), "tracking_ahead")
        self.assertEqual(compare_tracking(11, 10, 12), "tracking_on_track")

    def test_forward_pages_are_kept(self):
        pages = [
            {"page": 1, "text": "Revenue for the quarter was higher."},
            {"page": 2, "text": "We expect EBITDA margin of 19 percent next year."},
        ]
        chosen = select_pages(pages)
        self.assertEqual([page["page"] for page in chosen], [2])

    def test_jewellery_guidance_is_not_scored(self):
        quote = "As far as coming to 11% to 11.5% margin guidance, I think that stays."
        page = (
            "operating leverage coming in the jewellery business is quite normal. "
            + quote
        )
        scope, name = assign_scope(quote, page, "consolidated", "")
        self.assertEqual((scope, name), ("segment", "Jewellery"))
        row = judge_promise(
            {
                "metric_key": "ebitda_margin",
                "target_low": 11,
                "target_high": 11.5,
                "direction": "",
                "horizon": "fiscal_year",
                "target_period": "FY2026",
                "evidence": quote,
                "page": 6,
                "source_document": "u",
                "speaker": "",
                "scope": scope,
                "scope_name": name,
            },
            [quarter("2026-03-31", 100, 9, 5, 9)],
            date(2026, 11, 10),
        )
        self.assertEqual(row["status"], "segment_level")
        self.assertIsNone(row["actual"])
        self.assertIn("Jewellery", row["note"])

    def test_each_band_stays_with_its_metric(self):
        evidence = (
            "At a consolidated level, we aim to deliver double-digit revenue growth "
            "and high-teen EBITDA growth"
        )
        self.assertEqual(apply_word_bands(evidence, None, None, "revenue_growth"), (10.0, None))
        self.assertEqual(apply_word_bands(evidence, None, None, "ebitda_growth"), (17.0, 19.0))

    def test_a_basis_point_promise_is_a_change_and_a_gross_margin_is_not_scored(self):
        quarters = [
            quarter("2025-12-31", 100, 20, 10, 20),
            quarter("2024-12-31", 100, 18, 8, 18),
        ]
        change = judge_promise(
            {
                "metric_key": "ebitda_margin",
                "target_low": 200,
                "target_high": None,
                "direction": "",
                "horizon": "quarter",
                "target_period": "2025-12-31",
                "evidence": "We expect EBITDA margin to expand by about 200 basis points",
                "page": 4,
                "source_document": "https://example/p.pdf",
                "speaker": "",
                "scope": "consolidated",
            },
            quarters,
            date(2026, 11, 10),
        )
        self.assertEqual(change["status"], "delivered")
        self.assertEqual(change["actual"], "+200 bps")
        self.assertNotIn("%", change["actual"])
        gross = judge_promise(
            {
                "metric_key": "ebitda_margin",
                "target_low": 200,
                "target_high": None,
                "direction": "",
                "horizon": "quarter",
                "target_period": "2025-12-31",
                "evidence": "Our gross margins at a stand-alone level improved by about 200 basis points as input prices remained benign.",
                "page": 4,
                "source_document": "https://example/p.pdf",
                "speaker": "",
                "scope": "consolidated",
            },
            quarters,
            date(2026, 11, 10),
        )
        self.assertEqual(gross["status"], "not_scored")
        self.assertIsNone(gross["actual"])
        self.assertIn("gross", gross["note"])
        self.assertEqual(gross["unit"], "bps")
        self.assertEqual(gross["kind"], "change")
        self.assertEqual(change["unit"], "bps")
        self.assertEqual(change["kind"], "change")
        self.assertNotEqual(quote_check(gross["source_quote"], 200, None, "percent"), "ok")

    def test_a_dollar_revenue_range_is_not_scored_as_a_percent(self):
        quote = "we expect our revenues to be in the range of $2.571 billion to $2.625 billion"
        quarters = [
            quarter("2026-09-30", 25000, 5000, 3000),
            quarter("2026-06-30", 24231.30, 4800, 2900),
            quarter("2025-09-30", 23000, 4500, 2700),
            quarter("2025-06-30", 21831.90, 4300, 2500),
        ]
        row = judge_promise(
            {
                "metric_key": "revenue_growth",
                "target_low": 2.571,
                "target_high": 2.625,
                "direction": "",
                "horizon": "fiscal_year",
                "target_period": "FY2027",
                "evidence": quote,
                "page": 6,
                "source_document": "https://nsearchives.nseindia.com/corporate/Wipro_Secretarial_16102026163132_SEIntimation16102026.pdf",
                "speaker": "",
                "scope": "consolidated",
            },
            quarters,
            date(2026, 11, 10),
        )
        self.assertEqual(row["status"], "not_scored")
        self.assertEqual(row["unit"], "currency_usd")
        self.assertEqual(row["kind"], "level")
        self.assertIsNone(row["actual"])
        self.assertNotIn("%", row["promise"])
        self.assertIn("US$2.571", row["promise"])
        self.assertEqual(
            row["note"],
            "Guided in US dollars for the IT services segment; our series is consolidated INR.",
        )
        self.assertNotEqual(quote_check(quote, 2.571, 2.625, "percent"), "ok")
        self.assertEqual(quote_check(quote, 2.571, 2.625, "currency_usd"), "ok")
        constant = judge_promise(
            {
                "metric_key": "revenue_growth",
                "target_low": 2,
                "target_high": 4,
                "direction": "",
                "horizon": "fiscal_year",
                "target_period": "FY2027",
                "evidence": "We expect consolidated revenue growth of 2% to 4% in constant currency terms",
                "page": 7,
                "source_document": "u",
                "speaker": "",
                "scope": "consolidated",
            },
            quarters,
            date(2026, 11, 10),
        )
        self.assertEqual(constant["status"], "not_scored")
        self.assertIsNone(constant["actual"])
        self.assertIn("Constant-currency", constant["note"])

    def test_marico_and_asian_paints_scored_rows_stay_the_same(self):
        marico = [
            quarter("2026-09-30", 3854, 728, 400),
            quarter("2026-06-30", 4000, 800, 420),
            quarter("2025-09-30", 3341, 615, 300),
            quarter("2025-06-30", 3400, 600, 310),
        ]
        revenue = judge_promise(
            {
                "metric_key": "revenue_growth",
                "target_low": 10,
                "target_high": None,
                "direction": "",
                "horizon": "fiscal_year",
                "target_period": "FY2027",
                "evidence": "The strong start to this year has set us well to achieve our full year aspirations of delivering double-digit revenue growth to cross INR15,000 crores",
                "page": 6,
                "source_document": "u",
                "speaker": "",
                "scope": "consolidated",
            },
            marico,
            date(2026, 11, 10),
        )
        ebitda = judge_promise(
            {
                "metric_key": "ebitda_growth",
                "target_low": 17,
                "target_high": 19,
                "direction": "",
                "horizon": "fiscal_year",
                "target_period": "FY2027",
                "evidence": "At a consolidated level, we aim to deliver double-digit revenue growth to cross INR15,000 crores in revenues and high-teen EBITDA growth, subject to stable macros.",
                "page": 5,
                "source_document": "u",
                "speaker": "",
                "scope": "consolidated",
            },
            marico,
            date(2026, 11, 10),
        )
        margin = judge_promise(
            {
                "metric_key": "ebitda_margin",
                "target_low": 140,
                "target_high": 150,
                "direction": "",
                "horizon": "fiscal_year",
                "target_period": "FY2027",
                "evidence": "then the reverse math would suggest that EBITDA margin would expand in the range of about 140 to 150 basis points as compared to last",
                "page": 10,
                "source_document": "u",
                "speaker": "Pawan Agrawal",
                "scope": "consolidated",
            },
            marico,
            date(2026, 11, 10),
        )
        self.assertEqual(revenue["status"], "tracking_ahead")
        self.assertEqual(revenue["actual"], "16.51%")
        self.assertEqual(revenue["promise"], "Revenue growth at least 10% for FY2027")
        self.assertEqual(revenue["unit"], "percent")
        self.assertEqual(ebitda["status"], "tracking_ahead")
        self.assertEqual(ebitda["actual"], "25.76%")
        self.assertEqual(ebitda["promise"], "EBITDA growth 17–19% for FY2027")
        self.assertEqual(margin["status"], "tracking_on_track")
        self.assertEqual(margin["actual"], "+144 bps")
        self.assertEqual(margin["unit"], "bps")
        asian_open = [
            quarter("2026-09-30", 10000, 1816, 900),
            quarter("2026-06-30", 10000, 1816, 900),
            quarter("2025-09-30", 10000, 1791, 800),
            quarter("2025-06-30", 10000, 1791, 800),
        ]
        open_year = judge_promise(
            {
                "metric_key": "ebitda_margin",
                "target_low": 18,
                "target_high": 20,
                "direction": "",
                "horizon": "fiscal_year",
                "target_period": "FY2027",
                "evidence": "We are still garnering around the guidance of 18-20% of our PBDIT margins holds.",
                "page": 20,
                "source_document": "u",
                "speaker": "",
                "scope": "consolidated",
            },
            asian_open,
            date(2026, 11, 10),
        )
        closed = [
            quarter("2026-03-31", 100, 18.37, 10),
            quarter("2025-12-31", 100, 18.37, 10),
            quarter("2025-09-30", 100, 18.37, 10),
            quarter("2025-06-30", 100, 18.37, 10),
        ]
        delivered = judge_promise(
            {
                "metric_key": "ebitda_margin",
                "target_low": 18,
                "target_high": 20,
                "direction": "",
                "horizon": "fiscal_year",
                "target_period": "FY2026",
                "evidence": "maintain the whole guidance of 18 to 20% PBDIT margin band.",
                "page": 27,
                "source_document": "u",
                "speaker": "",
                "scope": "consolidated",
            },
            closed,
            date(2026, 11, 10),
        )
        self.assertEqual(open_year["status"], "tracking_on_track")
        self.assertEqual(open_year["actual"], "18.16%")
        self.assertEqual(open_year["promise"], "EBITDA margin 18–20% for FY2027")
        self.assertEqual(open_year["unit"], "percent")
        self.assertEqual(open_year["kind"], "level")
        self.assertEqual(delivered["status"], "delivered")
        self.assertEqual(delivered["actual"], "18.37%")
        self.assertEqual(delivered["unit"], "percent")

    def test_a_reported_margin_is_not_scored(self):
        row = judge_promise(
            {
                "metric_key": "ebitda_margin",
                "target_low": 43,
                "target_high": None,
                "direction": "",
                "horizon": "quarter",
                "target_period": "2025-06-30",
                "evidence": "we've been able to stay at margin range of about 43% over the quarters",
                "page": 17,
                "source_document": "u",
                "speaker": "",
            },
            [quarter("2025-06-30", 100, 18, 10)],
            date(2026, 11, 10),
        )
        self.assertIsNone(row)

    def test_same_promise_is_one_row_and_a_changed_number_is_a_revision(self):
        first = judge_promise(
            {
                "metric_key": "ebitda_margin",
                "target_low": 18,
                "target_high": 20,
                "direction": "",
                "horizon": "fiscal_year",
                "target_period": "FY2026",
                "evidence": "EBITDA margin guidance stays at 18 to 20 percent",
                "page": 4,
                "source_document": "https://example/a.pdf",
                "speaker": "",
                "call_date": "2025-11-01",
                "call_period": "2025-09-30",
            },
            [quarter("2026-03-31", 100, 19, 10)],
            date(2026, 11, 10),
        )
        second = dict(first)
        second["call_date"] = "2026-02-01"
        second["call_period"] = "2025-12-31"
        second["page"] = 9
        raised = dict(second)
        raised["target_low"] = 19
        raised["target_high"] = 21
        raised["promised"] = "19–21%"
        raised["call_date"] = "2026-05-01"
        rows, long_term, summary = merge_rows([first, second, raised])
        self.assertEqual(len(rows) + len(long_term), 1)
        self.assertEqual(summary["maintained"], 1)
        self.assertEqual(summary["raised"], 1)
        self.assertEqual(len(rows[0]["calls"]) if rows else len(long_term[0]["calls"]), 3)


if __name__ == "__main__":
    unittest.main()
