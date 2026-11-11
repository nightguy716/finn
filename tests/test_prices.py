import unittest
from datetime import date
from unittest.mock import patch

from finn_core.prices import cached_eod, detect_alerts


def bar(day: str, close: float, volume: float = 100.0) -> dict:
    return {"date": date.fromisoformat(day), "close": close, "volume": volume}


class AlertSignTests(unittest.TestCase):
    def test_a_fall_keeps_its_sign(self):
        bars = [bar("2026-11-05", 100), bar("2026-11-06", 90)]
        alerts = detect_alerts(bars, move_pct=5, volume_n=100)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["move_pct"], 10.0)
        self.assertEqual(alerts[0]["signed_move_pct"], -10.0)

    def test_a_rise_stays_positive(self):
        bars = [bar("2026-11-05", 100), bar("2026-11-06", 108)]
        alerts = detect_alerts(bars, move_pct=5, volume_n=100)
        self.assertEqual(alerts[0]["signed_move_pct"], 8.0)
        self.assertEqual(alerts[0]["move_pct"], 8.0)


class StoredBarsTests(unittest.TestCase):
    def test_a_long_stored_series_is_not_downloaded_again(self):
        class Store:
            def __init__(self):
                self.rows = {}

            def get(self, source, symbol, start, end):
                return self.rows.get((source, symbol, start, end))

            def put(self, source, symbol, start, end, payload):
                self.rows[(source, symbol, start, end)] = payload

        cache = Store()
        stored = [{"date": f"2026-10-{day:02d}", "close": 100, "volume": 10} for day in range(1, 23)]
        cache.put("eod_bars", "TITAN", "2026-09-22", "2026-11-06|v1", stored)
        with patch("finn_core.prices.fetch_eod", side_effect=AssertionError("downloaded")):
            bars, error = cached_eod(["TITAN"], date(2026, 9, 22), date(2026, 11, 6), cache)
        self.assertIsNone(error)
        self.assertEqual(len(bars["TITAN"]), 22)
        self.assertEqual(bars["TITAN"][0]["close"], 100)

    def test_a_shorter_download_does_not_replace_stored_bars(self):
        class Store:
            def __init__(self):
                self.rows = {}

            def get(self, source, symbol, start, end):
                return self.rows.get((source, symbol, start, end))

            def put(self, source, symbol, start, end, payload):
                self.rows[(source, symbol, start, end)] = payload

        cache = Store()
        stored = [{"date": f"2026-10-{day:02d}", "close": 100, "volume": 10} for day in range(1, 6)]
        cache.put("eod_bars", "TITAN", "2026-09-22", "2026-11-06|v1", stored)
        short = [{"date": date(2026, 11, 6), "close": 1, "volume": 1}]
        with patch("finn_core.prices.fetch_eod", return_value={"TITAN": short}):
            bars, error = cached_eod(["TITAN"], date(2026, 9, 22), date(2026, 11, 6), cache)
        self.assertIsNone(error)
        self.assertEqual(len(bars["TITAN"]), 5)
        self.assertEqual(bars["TITAN"][0]["close"], 100)
        self.assertEqual(len(cache.rows[("eod_bars", "TITAN", "2026-09-22", "2026-11-06|v1")]), 5)


if __name__ == "__main__":
    unittest.main()
