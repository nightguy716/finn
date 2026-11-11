"""One Mumbai function for health, the push feed, the ledger, and alert defaults.

Rewrites send /api/feed and the other routes here with ?route= added.
The pyproject entrypoint is api.index:handler, the same shape as the probe.
"""

import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from finn_core.api_routes import alert_config, daily_cron, feed_view, financials_view, health, ledger_view, snapshot_view
from finn_core.llm import LIMIT_MESSAGE, QuotaError


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self._send(204, b"")

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        route = (params.get("route") or [""])[0] or parsed.path.removeprefix("/api/").strip("/")
        try:
            if route == "health":
                payload, status = health(), 200
            elif route == "feed":
                payload, status = feed_view(params), 200
            elif route == "ledger":
                payload, status = ledger_view(params), 200
            elif route == "snapshot":
                payload, status = snapshot_view(params), 200
            elif route == "financials":
                payload, status = financials_view(params), 200
            elif route in ("alerts/config", "alerts"):
                payload, status = alert_config(), 200
            elif route == "cron/daily":
                payload, status = daily_cron(self.headers), 200
            else:
                payload, status = {"error": "not found"}, 404
        except PermissionError:
            payload, status = {"error": "unauthorized"}, 401
        except ValueError as exc:
            payload, status = {"error": str(exc)[:160]}, 400
        except QuotaError:
            payload, status = {"error": "daily_limit", "message": LIMIT_MESSAGE}, 429
        except Exception:
            payload, status = {"error": "request failed"}, 500
        self._send(status, json.dumps(payload).encode())

    def _send(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return
