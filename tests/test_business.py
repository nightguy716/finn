"""Annual-report pages are capped, and a quote that is not on the page is dropped."""

import unittest
from unittest.mock import patch

from finn_core.business import accept, business_snapshot, select_pages


class Mem:
    def __init__(self):
        self.rows = {}

    def get(self, source, symbol, start, end):
        return self.rows.get((source, symbol, start, end))

    def put(self, source, symbol, start, end, payload):
        self.rows[(source, symbol, start, end)] = payload


def page(heading: str, body: str) -> str:
    return f"{heading}\n{body} " + ("word " * 120)


class SelectTest(unittest.TestCase):
    def test_sections_are_capped_and_a_later_discussion_is_kept(self):
        texts = ["short"] * 4
        texts.append(page("Corporate Overview Statutory Reports Financial Statements Management discussion and analysis 40", "A contents page."))
        texts.append(page("Background and operations", "Marico carries on business in branded consumer products."))
        texts.append(page("Continued", "The brands include Parachute and Saffola."))
        texts.extend("nothing here " * 80 for _ in range(6))
        texts.append(page("Management discussion and analysis", "Revenue grew in India."))
        texts.extend(page("Discussion continued", "Parachute and Saffola led growth.") for _ in range(5))
        texts.append(page("Operating segment", "Segment revenue from India was 80 percent. Reportable segments are India and International."))
        chosen = select_pages(texts)
        sections = {row["section"] for row in chosen}
        self.assertNotIn(5, {row["page"] for row in chosen})
        self.assertIn("background", sections)
        self.assertIn("discussion", sections)
        self.assertIn("segments", sections)
        self.assertLessEqual(len(chosen), 30)
        self.assertEqual(chosen[0]["page"], 6)

    def test_a_quote_off_the_page_is_dropped(self):
        text = "Marico sells coconut oil and value added hair oils across India. Hair oils contributed 40 percent of revenue."
        pages = [{"page": 3, "text": text}]
        raw = {
            "does": {"text": "Marico sells coconut oil.", "page": 3, "evidence": "sells coconut oil and value added hair"},
            "makes_money": {"text": "It mines coal.", "page": 3, "evidence": "mines coal in open pits overseas today"},
            "segments": [
                {"name": "Hair oils", "share": "40%", "page": 3, "evidence": "Hair oils contributed 40 percent of revenue"},
                {"name": "Coal", "share": "10%", "page": 9, "evidence": "Coal contributed 10 percent of revenue"},
            ],
            "geographies": [{"name": "India", "share": "", "page": 3, "evidence": "value added hair oils across India"}],
        }
        kept = accept(raw, pages)
        self.assertEqual(kept["does"]["page"], 3)
        self.assertIsNone(kept["makes_money"])
        self.assertEqual(kept["segments"], [{"name": "Hair oils", "share": "40%", "page": 3}])
        self.assertEqual(kept["geographies"], [{"name": "India", "share": None, "page": 3}])

    def test_a_sentence_that_changes_the_subject_is_dropped(self):
        text = "Global IT service providers are equipped to support enterprises with technology and business process services across cybersecurity and cloud infrastructure."
        pages = [{"page": 35, "text": text}]
        raw = {
            "does": {
                "text": "Wipro provides a wide range of technology and business process services including consulting and cloud infrastructure.",
                "page": 35,
                "evidence": "technology and business process services across cybersecurity",
            },
            "makes_money": {"text": "", "page": 0, "evidence": ""},
            "segments": [],
            "geographies": [],
        }
        self.assertIsNone(accept(raw, pages)["does"])

    def test_a_stored_snapshot_does_not_call_the_model(self):
        cache = Mem()
        cache.put(
            "biz_snapshot",
            "MARICO",
            "2025",
            "v3",
            {"status": "ready", "symbol": "MARICO", "year": "2025", "snapshot": {"does": {"text": "Makes oil.", "page": 4}}, "usage": {"total_tokens": 12}},
        )
        report = {"status": "found", "url": "https://example.com/a.pdf", "year": "2025", "to_year": "2025"}
        with patch("finn_core.business.find_annual_report", return_value=report), patch(
            "finn_core.business._ask", side_effect=AssertionError("model")
        ):
            body = business_snapshot("MARICO", cache=cache, client=object())
        self.assertEqual(body["source"], "cache")
        self.assertEqual(body["usage"]["total_tokens"], 12)


if __name__ == "__main__":
    unittest.main()
