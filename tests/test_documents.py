"""Quarter matching for transcripts. No network."""

import unittest
from datetime import date

from finn_core.documents import (
    _parse_screener,
    _pick,
    attachment_kind,
    period_from_filing,
    quarter_ends,
)


class QuarterTests(unittest.TestCase):
    def test_last_five_quarters_from_november(self):
        self.assertEqual(
            quarter_ends(date(2026, 11, 10), 5),
            [
                date(2026, 9, 30),
                date(2026, 6, 30),
                date(2026, 3, 31),
                date(2025, 12, 31),
                date(2025, 9, 30),
            ],
        )

    def test_filename_codes_follow_the_fiscal_year(self):
        self.assertEqual(
            period_from_filing("", "https://nse/TITAN_SEaudiocallQ227.pdf", date(2026, 11, 5)),
            date(2026, 9, 30),
        )
        self.assertEqual(
            period_from_filing("Earnings Call Transcripts", "https://nse/SEanalystcalltranscriptQ1.pdf", date(2026, 8, 11)),
            date(2026, 6, 30),
        )
        self.assertEqual(
            period_from_filing("Transcript", "https://nse/SEIntimationtranscriptq4.pdf", date(2026, 5, 14)),
            date(2026, 3, 31),
        )
        self.assertEqual(
            period_from_filing("Transcript", "https://nse/SEtranscriptQ3.pdf", date(2026, 2, 13)),
            date(2025, 12, 31),
        )

    def test_kind(self):
        self.assertEqual(attachment_kind("has informed the Exchange about Earnings Call Transcripts", "https://nse/a.pdf"), "transcript")
        self.assertEqual(attachment_kind("copy of transcript of the earnings call", "https://nse/SEintimation.pdf"), "transcript")
        self.assertEqual(attachment_kind("Link of Recording", "https://nse/audio.pdf"), "audio")
        self.assertEqual(attachment_kind("Schedule of meet", "https://nse/invite.pdf"), "notice")
        schedule = (
            "This is to inform you that the Company will hold an investor conference call on November 2, 2026. "
            "A transcript will be uploaded afterwards."
        )
        self.assertEqual(attachment_kind(schedule, "https://nse/Schedule_of_Conference_call.pdf"), "notice")

    def test_earnings_transcript_beats_a_later_conference(self):
        period = date(2025, 12, 31)
        earnings = {
            "period": period,
            "date": date(2026, 1, 30),
            "url": "earn",
            "route": "nse",
            "kind": "transcript",
            "lag": 30,
            "earnings": True,
        }
        other = {
            "period": period,
            "date": date(2026, 2, 18),
            "url": "other",
            "route": "nse",
            "kind": "transcript",
            "lag": 49,
            "earnings": False,
        }
        self.assertEqual(_pick([earnings, other])[period]["url"], "earn")

    def test_revision_keeps_the_later_transcript_and_an_extra_call_does_not(self):
        period = date(2026, 3, 31)
        early = {"period": period, "date": date(2026, 5, 12), "url": "a", "route": "nse", "kind": "transcript", "lag": 42}
        revised = {"period": period, "date": date(2026, 5, 20), "url": "b", "route": "nse", "kind": "transcript", "lag": 50}
        extra = {"period": period, "date": date(2026, 6, 18), "url": "c", "route": "nse", "kind": "transcript", "lag": 79}
        self.assertEqual(_pick([early, revised])[period]["url"], "b")
        self.assertEqual(_pick([early, extra])[period]["url"], "a")

    def test_screener_row_maps_the_call_month_to_the_quarter(self):
        html = """
        <div class="documents"><h3>Concalls</h3>
          <ul>
            <li>Nov 2026 Transcript AI Summary PPT REC
              <a href="https://www.bseindia.com/rec.pdf">REC</a>
            </li>
            <li>Aug 2026 Transcript
              <a href="https://example.com/t.pdf">Transcript</a>
              <a href="https://www.screener.in/ai">AI Summary</a>
            </li>
            <li>May 2026 Transcript <a href="https://example.com/may.pdf">Transcript</a></li>
            <li>Jun 2026 Transcript <a href="https://example.com/jun.pdf">Transcript</a></li>
          </ul>
        </div>
        <div class="documents"><h3>Annual reports</h3>
          <ul><li><a href="https://example.com/ar.pdf">Annual Report 2026</a></li></ul>
        </div>
        <a href="https://www.example.com">Website</a>
        """
        parsed = _parse_screener(html, "https://www.screener.in/company/TITAN/consolidated/")
        self.assertEqual(parsed["website"], "https://www.example.com")
        self.assertEqual(parsed["annual"][0]["year"], "2026")
        chosen = _pick(parsed["transcripts"])
        self.assertEqual(chosen[date(2026, 9, 30)]["kind"], "audio")
        self.assertEqual(chosen[date(2026, 6, 30)]["url"], "https://example.com/t.pdf")
        self.assertEqual(chosen[date(2026, 3, 31)]["url"], "https://example.com/may.pdf")
        self.assertTrue(all("screener.in/ai" not in item["url"] for item in parsed["transcripts"]))


if __name__ == "__main__":
    unittest.main()
