"""XBRL scaling, EBITDA, and the results card. No network."""

import unittest
from datetime import date

from finn_core.results_card import _assemble, _empty_usage, _metrics_from_model, _sanity, _to_crore
from finn_core.xbrl_parse import (
    ebitda,
    ebitda_block_reason,
    metrics_from,
    parse_xbrl,
    previous_quarter_end,
    year_ago_end,
)

# Absolute rupees, LevelOfRounding Crores, same shape as Titan's Sep 2026 filing.
# FourD is the half year and must not be read as the quarter.
FIXTURE = """<?xml version="1.0"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance">
  <context id="OneD"><period><startDate>2026-07-01</startDate><endDate>2026-09-30</endDate></period></context>
  <context id="FourD"><period><startDate>2026-04-01</startDate><endDate>2026-09-30</endDate></period></context>
  <unit id="INR"><measure>iso4217:INR</measure></unit>
  <LevelOfRounding contextRef="OneD">Crores</LevelOfRounding>
  <RevenueFromOperations contextRef="OneD" unitRef="INR" decimals="-7">206140000000</RevenueFromOperations>
  <RevenueFromOperations contextRef="FourD" unitRef="INR" decimals="-7">419700000000</RevenueFromOperations>
  <OtherIncome contextRef="OneD" unitRef="INR" decimals="-7">8160000000</OtherIncome>
  <FinanceCosts contextRef="OneD" unitRef="INR" decimals="-7">5360000000</FinanceCosts>
  <DepreciationDepletionAndAmortisationExpense contextRef="OneD" unitRef="INR" decimals="-7">2630000000</DepreciationDepletionAndAmortisationExpense>
  <ProfitBeforeTax contextRef="OneD" unitRef="INR" decimals="-7">30010000000</ProfitBeforeTax>
  <TaxExpense contextRef="OneD" unitRef="INR" decimals="-7">6070000000</TaxExpense>
  <ProfitLossForPeriod contextRef="OneD" unitRef="INR" decimals="-5">23927300000</ProfitLossForPeriod>
</xbrl>
"""

LAKH_FIXTURE = """<?xml version="1.0"?>
<xbrl>
  <context id="OneD"><period><startDate>2026-07-01</startDate><endDate>2026-09-30</endDate></period></context>
  <LevelOfRounding contextRef="OneD">Lakhs</LevelOfRounding>
  <RevenueFromOperations contextRef="OneD" unitRef="INR">2061400</RevenueFromOperations>
  <ProfitBeforeTax contextRef="OneD" unitRef="INR">300100</ProfitBeforeTax>
  <ProfitLossForPeriod contextRef="OneD" unitRef="INR">239273</ProfitLossForPeriod>
</xbrl>
"""


class XbrlTests(unittest.TestCase):
    def test_rupee_facts_become_crore_and_fourd_is_not_the_quarter(self):
        parsed = parse_xbrl(FIXTURE)
        self.assertEqual(parsed.scale, "rupee")
        self.assertEqual(parsed.current.end, date(2026, 9, 30))
        metrics = metrics_from(parsed.current)
        self.assertEqual(metrics["revenue"], 20614.0)
        self.assertEqual(metrics["pbt"], 3001.0)
        self.assertEqual(metrics["pat"], 2392.73)
        self.assertEqual(ebitda(metrics), 2984.0)
        self.assertEqual(parsed.year_to_date.crore["RevenueFromOperations"], 41970.0)
        self.assertIn("previous_quarter", parsed.missing)
        self.assertIn("year_ago_quarter", parsed.missing)
        self.assertNotIn("current_quarter", parsed.missing)

    def test_lakh_presentation_when_the_anchor_is_small(self):
        parsed = parse_xbrl(LAKH_FIXTURE)
        self.assertEqual(parsed.scale, "lakh")
        self.assertEqual(metrics_from(parsed.current)["revenue"], 20614.0)

    def test_quarter_ends(self):
        self.assertEqual(previous_quarter_end(date(2026, 9, 30)), date(2026, 6, 30))
        self.assertEqual(previous_quarter_end(date(2026, 6, 30)), date(2026, 3, 31))
        self.assertEqual(previous_quarter_end(date(2026, 3, 31)), date(2025, 12, 31))
        self.assertEqual(year_ago_end(date(2026, 9, 30)), date(2025, 9, 30))

    def test_bank_and_nbfc_have_no_ebitda(self):
        metrics = {"pbt": 100.0, "finance_costs": 40.0, "depreciation": 2.0, "other_income": 1.0, "revenue": 200.0}
        self.assertEqual(ebitda(metrics), 141.0)
        self.assertIn("bank", ebitda_block_reason("HDFCBANK", "", metrics))
        self.assertIn("NBFC", ebitda_block_reason("BAJFINANCE", "https://example/INTEGRATED_FILING_NBFC_x.xml", metrics))
        self.assertEqual(ebitda_block_reason("TITAN", "https://example/INDAS.xml", metrics), "")

    def test_card_carries_qoq_yoy_and_flags_a_broken_tax_identity(self):
        current = {
            "revenue": 1000.0,
            "other_income": 10.0,
            "finance_costs": 20.0,
            "depreciation": 30.0,
            "pbt": 200.0,
            "pat": 50.0,
            "pat_total": 50.0,
            "tax": 10.0,
            "share": 0.0,
            "revenue_basis": "revenue_from_operations",
        }
        previous = {**current, "revenue": 800.0, "pbt": 150.0, "pat": 40.0, "pat_total": 40.0}
        card = _assemble(
            symbol="TITAN",
            period_end=date(2026, 9, 30),
            period_label="30-SEP-2026",
            scope="Consolidated",
            source="xbrl",
            source_url="https://example/current.xml",
            broadcast="05-Nov-2026 19:11:12",
            current=current,
            previous=previous,
            yoy=None,
            xbrl_url="https://example/INDAS.xml",
            parsed=None,
            comparison_urls={"qoq": "https://example/prev.xml", "yoy": ""},
            extra_flags=[],
            usage=_empty_usage(),
        )
        self.assertEqual(card["source"], "xbrl")
        self.assertEqual(card["metrics"]["revenue"]["current"], 1000.0)
        self.assertEqual(card["metrics"]["revenue"]["qoq"], 800.0)
        self.assertEqual(card["metrics"]["revenue"]["qoq_pct"], 25.0)
        self.assertIsNone(card["metrics"]["revenue"]["yoy"])
        self.assertEqual(card["metrics"]["ebitda"]["current"], 240.0)
        self.assertTrue(any(flag.startswith("pbt_tax_pat") for flag in card["flags"]))
        self.assertEqual(_sanity({"revenue": -5, "pat": 10, "pbt": None}, "")[0], "revenue_not_positive: -5")

    def test_pdf_unit_conversion(self):
        current, previous, yoy = _metrics_from_model(
            {
                "unit": "lakh",
                "revenue_current": 2061400,
                "revenue_previous": 100000,
                "revenue_year_ago": 90000,
                "pbt_current": 300100,
                "pat_current": 239273,
                "finance_costs_current": 53600,
                "depreciation_current": 26300,
                "other_income_current": 81600,
            }
        )
        self.assertEqual(current["revenue"], 20614.0)
        self.assertEqual(previous["revenue"], 1000.0)
        self.assertEqual(_to_crore(10, "million"), 1.0)


if __name__ == "__main__":
    unittest.main()
