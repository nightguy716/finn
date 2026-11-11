import unittest
from datetime import date

from finn_core.prices import detect_alerts


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


if __name__ == "__main__":
    unittest.main()
