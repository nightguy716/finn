"""Parsed series is reused, and a paused cache falls back to the snapshot file."""

import os
import unittest
from datetime import date
from unittest.mock import patch

from finn_core.api_routes import alert_config, daily_cron, feed_key, feed_view, ledger_view
from finn_core.feed import order_alerts
from finn_core.documents import quarter_ends
from finn_core.series import SERIES_VERSION, quarterly_series


class Mem:
    def __init__(self):
        self.rows = {}

    def get(self, source, symbol, start, end):
        return self.rows.get((source, symbol, start, end))

    def put(self, source, symbol, start, end, payload):
        self.rows[(source, symbol, start, end)] = payload


class NoDownload:
    def get_bytes(self, url, symbol=""):
        raise AssertionError(url)

    def get_financial_results(self, *args, **kwargs):
        raise AssertionError("results feed")


class SeriesCacheTest(unittest.TestCase):
    def test_a_cached_series_does_not_touch_xbrl(self):
        day = date(2026, 11, 10)
        cache = Mem()
        for period in quarter_ends(day, 4):
            cache.put(
                "series_quarter",
                "MARICO",
                period.isoformat(),
                SERIES_VERSION,
                {"period": period.isoformat(), "revenue": 1, "flags": []},
            )
        packet = quarterly_series("MARICO", quarters=4, as_of=day, client=NoDownload(), cache=cache)
        self.assertEqual(len(packet["quarters"]), 4)
        self.assertEqual(packet["quarters"][0]["revenue"], 1)


class RouteTest(unittest.TestCase):
    def test_alert_defaults(self):
        self.assertEqual(alert_config(), {"move_pct": 5.0, "volume_n": 2.5})

    def test_feed_key_uses_the_whole_portfolio_when_symbols_are_empty(self):
        self.assertEqual(feed_key("2026-11-06", 72, None, 5, 2.5), "2026-11-06|72|5|2.5|*")

    def test_a_paused_cache_serves_the_snapshot_file(self):
        filed = {"cards": [{"symbol": "TITAN"}], "alerts": []}
        with patch("finn_core.api_routes._open", return_value=(None, True)), patch(
            "finn_core.api_routes._file_for", return_value=filed
        ):
            body = feed_view({"as_of": ["2026-11-06"], "hours": ["72"]})
        self.assertEqual(body["source"], "file")
        self.assertEqual(body["cards"][0]["symbol"], "TITAN")

    def test_a_paused_cache_serves_a_stored_ledger(self):
        filed = {"symbol": "MARICO", "progress": {"stage": "complete", "done": 7, "total": 7}, "rows": []}
        with patch("finn_core.api_routes._open", return_value=(None, True)), patch(
            "finn_core.api_routes._file_for", return_value=filed
        ):
            body = ledger_view({"symbol": ["MARICO"]})
        self.assertEqual(body["source"], "file")
        self.assertEqual(body["progress"]["stage"], "complete")

    def test_a_cache_miss_serves_the_snapshot_and_does_not_recompute(self):
        cache = Mem()
        filed = {
            "cards": [{"symbol": "TITAN"}],
            "alerts": [
                {"symbol": "TITAN", "date": "2026-11-06", "severity": 1},
                {"symbol": "MARICO", "date": "2026-11-03", "severity": 9},
            ],
        }
        with patch("finn_core.api_routes._open", return_value=(cache, False)), patch(
            "finn_core.api_routes._file_for", return_value=filed
        ), patch("finn_core.api_routes.build_feed", side_effect=AssertionError("recomputed")):
            body = feed_view({"as_of": ["2026-11-06"], "hours": ["72"]})
        self.assertEqual(body["source"], "file")
        self.assertEqual([row["symbol"] for row in body["alerts"]], ["MARICO", "TITAN"])
        stored = cache.get("feed_snapshot", "FEED", "2026-11-06|72|5|2.5|*", "v1")
        self.assertEqual(stored["cards"][0]["symbol"], "TITAN")

    def test_equal_severity_orders_by_symbol_then_date(self):
        ordered = order_alerts(
            [
                {"symbol": "TITAN", "date": "2026-11-06", "severity": 5},
                {"symbol": "TITAN", "date": "2026-11-04", "severity": 5},
                {"symbol": "MARICO", "date": "2026-11-05", "severity": 5},
            ]
        )
        self.assertEqual(
            [(row["symbol"], row["date"]) for row in ordered],
            [("MARICO", "2026-11-05"), ("TITAN", "2026-11-04"), ("TITAN", "2026-11-06")],
        )

    def test_a_live_read_does_not_compute_when_nothing_is_stored(self):
        cache = Mem()
        with patch("finn_core.api_routes._open", return_value=(cache, False)), patch(
            "finn_core.api_routes.build_feed", side_effect=AssertionError("recomputed")
        ):
            body = feed_view({"as_of": ["2026-11-11"], "hours": ["24"], "stored": ["1"]})
        self.assertFalse(body["stored"])
        self.assertEqual(body["cards"], [])
        self.assertEqual(body["alerts"], [])

    def test_cron_rejects_a_bad_token(self):
        with patch.dict(os.environ, {"CRON_SECRET": "correct"}):
            with self.assertRaises(PermissionError):
                daily_cron({"Authorization": "Bearer wrong"})

    def test_cron_writes_a_heartbeat_and_both_windows(self):
        cache = Mem()
        calls = []

        def collected(client, symbols, as_of, window_hours):
            calls.append(window_hours)
            return [{"symbol": "TITAN"}], []

        def assembled(filings, failures, as_of, window_hours, symbols, move_pct, volume_n, alert_cap, client, cache):
            return {
                "as_of": as_of.isoformat(),
                "window_hours": window_hours,
                "cards": [{"symbol": filings[0]["symbol"]}],
                "alerts": [],
                "routine": [],
                "usage": {"total_tokens": 0},
            }

        with patch.dict(os.environ, {"CRON_SECRET": "correct"}), patch(
            "finn_core.api_routes._open", return_value=(cache, False)
        ), patch("finn_core.api_routes.collect_filings", side_effect=collected), patch(
            "finn_core.api_routes.assemble_feed", side_effect=assembled
        ):
            body = daily_cron({"Authorization": "Bearer correct"})
        self.assertEqual(calls, [72])
        self.assertTrue(body["ok"])
        self.assertEqual([row["status"] for row in body["windows"]], ["stored", "stored"])
        self.assertIsNotNone(cache.get("heartbeat", "FINN", "daily", "v1"))
        self.assertEqual(cache.get("feed_snapshot", "FEED", f"{body['as_of']}|24|5|2.5|*", "v1")["cards"][0]["symbol"], "TITAN")
        self.assertIsNotNone(cache.get("feed_snapshot", "FEED", f"{body['as_of']}|72|5|2.5|*", "v1"))


if __name__ == "__main__":
    unittest.main()
