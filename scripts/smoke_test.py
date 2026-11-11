"""Check the production web app and API. Prints pass or fail. Sends no secret."""

import json
import re
import sys
import urllib.error
import urllib.request

WEB = "https://web-eosin-ten-23.vercel.app"
API = "https://finn-r4y3.vercel.app"


def fetch(url: str, timeout: float = 40) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers={"Accept": "*/*", "User-Agent": "finn-smoke"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def report(name: str, ok: bool, detail: str = "") -> bool:
    print(f"{'pass' if ok else 'fail'}  {name}" + (f"  {detail}" if detail else ""))
    return ok


def main() -> int:
    ok = True

    status, body = fetch(f"{API}/api/health")
    try:
        health = json.loads(body)
    except json.JSONDecodeError:
        health = {}
    ok &= report("health", status == 200 and health.get("ok") is True, f"{status}")

    status, body = fetch(f"{API}/api/feed?as_of=2026-11-06&hours=72")
    try:
        feed = json.loads(body)
    except json.JSONDecodeError:
        feed = {}
    cards = feed.get("cards")
    ok &= report(
        "replay feed",
        status == 200 and isinstance(cards, list),
        f"{status} cards={len(cards) if isinstance(cards, list) else 'none'}",
    )

    status, body = fetch(f"{API}/api/ledger?symbol=MARICO")
    try:
        ledger = json.loads(body)
    except json.JSONDecodeError:
        ledger = {}
    stage = ((ledger.get("progress") or {}).get("stage")) or ((ledger.get("ledger") or {}).get("progress") or {}).get("stage")
    symbol = (ledger.get("ledger") or {}).get("symbol") or ledger.get("symbol")
    ok &= report("cached ledger", status == 200 and symbol == "MARICO" and stage == "complete", f"{status} {symbol} {stage}")

    status, body = fetch(WEB + "/")
    html = body.decode("utf-8", errors="replace")
    scripts = re.findall(r'src="(/assets/[^"]+\.js)"', html)
    found = False
    for src in scripts:
        script_status, script = fetch(WEB + src, timeout=60)
        if script_status == 200 and b"Marico" in script and b"MARICO" in script:
            found = True
            break
    ok &= report("company-name lookup", status == 200 and "FINN" in html and found, f"page={status} assets={len(scripts)}")

    status, body = fetch(f"{API}/api/cron/daily")
    try:
        cron = json.loads(body)
    except json.JSONDecodeError:
        cron = {}
    ok &= report("cron without secret", status == 401 and cron.get("error") == "unauthorized", f"{status}")

    print("pass" if ok else "fail")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
