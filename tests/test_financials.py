"""Balance-sheet arithmetic stays on the tagged facts, and a broken pypdf file can still be read."""

import unittest
from unittest.mock import patch

from finn_core.financials import _parse, _statement
from finn_core.pdf_text import page_texts


def fact(tag: str, context: str, value: str) -> str:
    return f'<{tag} contextRef="{context}" unitRef="INR">{value}</{tag}>'


def filing(values: dict) -> str:
    contexts = """
    <xbrli:context id="OneI"><xbrli:period><xbrli:instant>2026-09-30</xbrli:instant></xbrli:period></xbrli:context>
    <xbrli:context id="PY_I"><xbrli:period><xbrli:instant>2026-03-31</xbrli:instant></xbrli:period></xbrli:context>
    <xbrli:context id="FourD"><xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate><xbrli:endDate>2026-09-30</xbrli:endDate></xbrli:period></xbrli:context>
    """
    body = "".join(fact(tag, context, value) for (tag, context), value in values.items())
    return (
        '<xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance">'
        + contexts
        + '<NatureOfReportStandaloneConsolidated contextRef="FourD">Consolidated</NatureOfReportStandaloneConsolidated>'
        + body
        + "</xbrl>"
    )


class StatementTest(unittest.TestCase):
    def test_half_year_ratios_use_the_same_period(self):
        parsed = _parse(
            filing(
                {
                    ("BorrowingsNoncurrent", "OneI"): "0",
                    ("BorrowingsNoncurrent", "PY_I"): "0",
                    ("BorrowingsCurrent", "OneI"): "10460000000",
                    ("BorrowingsCurrent", "PY_I"): "3550000000",
                    ("Equity", "OneI"): "50600000000",
                    ("Equity", "PY_I"): "44940000000",
                    ("CashAndCashEquivalents", "OneI"): "3360000000",
                    ("CashAndCashEquivalents", "PY_I"): "4040000000",
                    ("Inventories", "OneI"): "22970000000",
                    ("Inventories", "PY_I"): "16110000000",
                    ("TradeReceivablesCurrent", "OneI"): "17050000000",
                    ("TradeReceivablesNoncurrent", "OneI"): "0",
                    ("TradeReceivablesCurrent", "PY_I"): "13040000000",
                    ("TradeReceivablesNoncurrent", "PY_I"): "0",
                    ("TradePayablesCurrent", "OneI"): "21860000000",
                    ("TradePayablesNoncurrent", "OneI"): "0",
                    ("TradePayablesCurrent", "PY_I"): "16340000000",
                    ("TradePayablesNoncurrent", "PY_I"): "0",
                    ("CashFlowsFromUsedInOperatingActivities", "FourD"): "6920000000",
                    ("PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities", "FourD"): "2440000000",
                    ("PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities", "FourD"): "0",
                    ("ProfitOrLossAttributableToOwnersOfParent", "FourD"): "11800000000",
                    ("RevenueFromOperations", "FourD"): "78540000000",
                }
            )
        )
        body = _statement(parsed, None, parsed["crore"].get("PY_I"))
        self.assertEqual(body["cash"]["label"], "Half-year")
        self.assertEqual(body["balance_sheet"]["ratios"]["debt_to_equity"]["value"], 0.21)
        self.assertEqual(body["balance_sheet"]["ratios"]["debt_to_equity"]["prior"], 0.08)
        self.assertEqual(body["balance_sheet"]["ratios"]["net_debt"]["value"], 710)
        self.assertEqual(body["balance_sheet"]["ratios"]["working_capital"]["value"], 1816)
        self.assertEqual(body["cash"]["ratios"]["free_cash_flow"]["value"], 448)
        self.assertEqual(body["cash"]["ratios"]["cash_conversion"]["value"], 0.59)
        self.assertEqual(body["cash"]["flags"], [])

    def test_a_missing_purchase_line_is_not_treated_as_zero(self):
        parsed = _parse(
            filing(
                {
                    ("Equity", "OneI"): "10000000000",
                    ("Borrowings", "OneI"): "2000000000",
                    ("CashFlowsFromUsedInOperatingActivities", "FourD"): "1000000000",
                    ("PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities", "FourD"): "0",
                    ("ProfitLossForPeriod", "FourD"): "500000000",
                }
            )
        )
        body = _statement(parsed, None)
        self.assertIsNone(body["cash"]["ratios"]["free_cash_flow"]["value"])
        self.assertIn("PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities", body["cash"]["missing"])

    def test_a_bank_does_not_get_a_debt_ratio(self):
        parsed = _parse(
            filing(
                {
                    ("Borrowings", "OneI"): "7412907700000",
                    ("Deposits", "OneI"): "63473053600000",
                    ("InterestEarned", "FourD"): "100000000000",
                    ("CashFlowsFromUsedInOperatingActivities", "FourD"): "-358296400000",
                    ("ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates", "FourD"): "494741600000",
                }
            )
        )
        body = _statement(parsed, None)
        self.assertEqual(body["kind"], "bank")
        self.assertFalse(body["balance_sheet"]["ratios"]["debt_to_equity"]["meaningful"])
        self.assertFalse(body["balance_sheet"]["ratios"]["working_capital"]["meaningful"])
        self.assertIn("not meaningful", body["balance_sheet"]["takeaway"])


class PdfFallbackTest(unittest.TestCase):
    def test_pymupdf_reads_the_page_when_pypdf_fails(self):
        import pymupdf

        document = pymupdf.open()
        page = document.new_page()
        page.insert_text((72, 72), "Marico carries on business in branded consumer products.")
        data = document.tobytes()
        document.close()
        with patch("finn_core.pdf_text._pypdf", side_effect=RuntimeError("Invalid object in /Pages")):
            texts, reader = page_texts(data)
        self.assertEqual(reader, "pymupdf")
        self.assertEqual(len(texts), 1)
        self.assertIn("branded consumer products", texts[0])


if __name__ == "__main__":
    unittest.main()
